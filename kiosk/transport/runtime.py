import http.client
import json
import os
import secrets
import socket
import subprocess
import tempfile
import threading
import time
from pathlib import Path

from waitress import create_server

from kiosk.app import create_app
from kiosk.config import Config
from kiosk.transport.profile import CADDY_VERSION, load_profile, proxy_configuration
from kiosk.transport.profile_operations import ProfileLease, recover_profile
from kiosk.transport.windows import OwnedJob


def command(arguments, directory, deadline):
    timeout = deadline - time.monotonic()
    if timeout <= 0:
        raise TimeoutError("HTTPS startup timed out.")
    result = subprocess.run(arguments, cwd=directory, capture_output=True, timeout=timeout,
                            creationflags=subprocess.CREATE_NO_WINDOW)
    if result.returncode:
        raise RuntimeError("HTTPS proxy validation failed.")
    return result


def reserve_loopback():
    listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        listener.bind(("127.0.0.1", 0))
        return listener
    except BaseException:
        listener.close()
        raise


def admin_request(port, path, method="GET", timeout=1):
    connection = http.client.HTTPConnection("127.0.0.1", port, timeout=timeout)
    authority = f"127.0.0.1:{port}"
    try:
        connection.request(method, path, headers={"Origin": f"http://{authority}"})
        with connection.getresponse() as response:
            return response.status, response.read(65536)
    finally:
        connection.close()


def connect_local_proxy(profile, timeout):
    target = "127.0.0.1" if profile.listen_host == "0.0.0.0" else profile.listen_host
    return socket.create_connection((target, profile.port), timeout=timeout, source_address=(target, 0))


def probe_https(profile, context, identity, timeout=1):
    connection = http.client.HTTPSConnection(profile.hostname, profile.port, context=context, timeout=timeout)
    connection._create_connection = lambda address, timeout, source_address=None: connect_local_proxy(profile, timeout)
    try:
        connection.request("GET", "/api/version", headers={"Host": profile.authority})
        with connection.getresponse() as response:
            data = response.read(65536)
            return response.status == 200 and response.getheader("X-Kiosk-Instance") == identity and type(json.loads(data).get("content_version")) is int
    finally:
        connection.close()


class ManagedHttps:
    def __init__(self, profile, app_factory=create_app, startup_timeout=30):
        self.profile = profile
        self.app_factory = app_factory
        self.deadline = time.monotonic() + startup_timeout
        self.identity = secrets.token_hex(24)
        self.process = None
        self.job = None
        self.server = None
        self.thread = None
        self.temporary = None
        self.admin_reservation = None
        self.backend_reservation = None
        self.admin_port = None
        self.loop_stopped = threading.Event()
        self.closed = False
        self.close_result = None
        self.phase = "preflight"

    def start(self):
        if self.temporary is not None or self.closed:
            raise RuntimeError("An HTTPS runtime cannot be started twice.")
        if os.name != "nt":
            raise RuntimeError("Managed HTTPS currently supports Windows only.")
        try:
            self.temporary = tempfile.TemporaryDirectory(prefix="kiosk-managed-https-")
            root = Path(self.temporary.name)
            self.admin_reservation = reserve_loopback()
            self.backend_reservation = reserve_loopback()
            self.admin_port = self.admin_reservation.getsockname()[1]
            backend_port = self.backend_reservation.getsockname()[1]
            configuration = proxy_configuration(self.profile, backend_port, self.admin_port, Config.MAX_CONTENT_LENGTH, self.identity)
            config_file = root / "proxy.json"
            config_file.write_text(json.dumps(configuration), encoding="utf-8")
            version = command([str(self.profile.caddy_executable), "version"], root, self.deadline)
            if version.stdout.decode("utf-8").split()[0] != CADDY_VERSION:
                raise ValueError("Unexpected HTTPS proxy version.")
            command([str(self.profile.caddy_executable), "validate", "--config", str(config_file)], root, self.deadline)
            self.phase = "application"
            self.app = self.app_factory({"SESSION_COOKIE_SECURE": True, "SESSION_COOKIE_HTTPONLY": True,
                                         "SESSION_COOKIE_SAMESITE": "Lax", "TRUSTED_HOSTS": [self.profile.hostname],
                                         "SERVER_HOST": "127.0.0.1", "SERVER_PORT": backend_port})
            if self.app.config["MAX_CONTENT_LENGTH"] != Config.MAX_CONTENT_LENGTH:
                configuration = proxy_configuration(self.profile, backend_port, self.admin_port, self.app.config["MAX_CONTENT_LENGTH"], self.identity)
                config_file.write_text(json.dumps(configuration), encoding="utf-8")
                command([str(self.profile.caddy_executable), "validate", "--config", str(config_file)], root, self.deadline)

            def identified(environ, start_response):
                def respond(status, headers, exc_info=None):
                    if environ.get("PATH_INFO") == "/api/version":
                        headers = [*headers, ("X-Kiosk-Instance", self.identity)]
                    return start_response(status, headers, exc_info)
                return self.app(environ, respond)

            self.backend_reservation.close()
            self.backend_reservation = None
            self.phase = "backend"
            self.server = create_server(identified, host="127.0.0.1", port=backend_port, threads=4, map={},
                                        max_request_body_size=self.app.config["MAX_CONTENT_LENGTH"],
                                        trusted_proxy="127.0.0.1", trusted_proxy_count=1,
                                        trusted_proxy_headers={"x-forwarded-for", "x-forwarded-proto", "x-forwarded-host"},
                                        clear_untrusted_proxy_headers=True)
            self.thread = threading.Thread(target=self.serve, daemon=True)
            self.thread.start()
            self.phase = "proxy"
            self.job = OwnedJob()
            self.admin_reservation.close()
            self.admin_reservation = None
            if time.monotonic() >= self.deadline:
                raise TimeoutError("HTTPS startup timed out.")
            self.process = subprocess.Popen([str(self.profile.caddy_executable), "run", "--config", str(config_file)],
                                            cwd=root, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                            creationflags=subprocess.CREATE_NO_WINDOW)
            self.job.assign(self.process)
            self.phase = "readiness"
            context = self.profile.trust_context()
            while time.monotonic() < self.deadline:
                self.check_running()
                try:
                    timeout = min(0.5, self.deadline - time.monotonic())
                    status, body = admin_request(self.admin_port, f"/id/{self.identity}", timeout=timeout)
                    if status == 200 and json.loads(body).get("@id") == self.identity and probe_https(self.profile, context, self.identity, timeout):
                        self.phase = "running"
                        return self
                except (OSError, ValueError, http.client.HTTPException):
                    pass
                time.sleep(0.05)
            raise TimeoutError("HTTPS startup timed out.")
        except BaseException:
            self.close()
            raise

    def serve(self):
        try:
            while not self.loop_stopped.is_set():
                self.server.asyncore.loop(timeout=0.05, count=1, map=self.server._map)
        except Exception:
            self.loop_stopped.set()
        finally:
            self.loop_stopped.set()

    def check_running(self):
        if (self.process is None or self.process.poll() is not None or self.loop_stopped.is_set()
                or self.thread is None or not self.thread.is_alive() or self.server is None
                or self.server.socket.fileno() < 0):
            raise RuntimeError("An owned HTTPS component stopped.")

    def close(self):
        if self.closed:
            return self.close_result
        result = {"proxy_forced": False, "backend_stopped": True, "temporary_removed": False}
        try:
            if self.process is not None:
                if self.process.poll() is None:
                    stop_deadline = time.monotonic() + 10
                    try:
                        status, body = admin_request(self.admin_port, f"/id/{self.identity}", timeout=0.5)
                        if status == 200 and json.loads(body).get("@id") == self.identity:
                            admin_request(self.admin_port, "/stop", "POST", timeout=0.5)
                    except (OSError, ValueError, http.client.HTTPException):
                        pass
                    try:
                        self.process.wait(timeout=max(0, stop_deadline - time.monotonic() - 0.5))
                    except subprocess.TimeoutExpired:
                        result["proxy_forced"] = True
                        self.process.kill()
                        self.process.wait(timeout=0.5)
                result["proxy_exit_code"] = self.process.returncode
        finally:
            try:
                if self.job is not None:
                    self.job.close()
                if self.server is not None:
                    try:
                        result["backend_stopped"] = self.server.task_dispatcher.shutdown(timeout=8)
                    finally:
                        self.loop_stopped.set()
                        if self.thread is not None:
                            self.thread.join(timeout=1)
                        self.server.close()
                        self.server.asyncore.close_all(map=self.server._map)
                    result["backend_stopped"] = result["backend_stopped"] and not self.server.task_dispatcher.threads
                if self.thread is not None and self.thread.is_alive():
                    result["backend_stopped"] = False
            finally:
                for reservation in (self.admin_reservation, self.backend_reservation):
                    if reservation is not None:
                        reservation.close()
                if self.temporary is not None:
                    root = Path(self.temporary.name)
                    self.temporary.cleanup()
                    result["temporary_removed"] = not root.exists()
                self.closed = True
                self.close_result = result
        return result


def run_https(filename, path="/kiosk", auto_launch=True):
    runtime = None
    lease = None
    code = 0
    try:
        lease = ProfileLease(filename).acquire()
        if recover_profile(filename):
            print("Recovered the previous HTTPS profile after an interrupted certificate activation.", flush=True)
        profile = load_profile(filename)
        runtime = ManagedHttps(profile)
        runtime.start()
        for route in ("/kiosk", "/kiosk/events", "/tv", "/preview", "/admin/login", "/api/version"):
            print(profile.public_origin + route, flush=True)
        print("HTTPS ready. Manual stop: Ctrl+C", flush=True)
        if auto_launch:
            from kiosk.server import launch_browser

            if not launch_browser(profile.public_origin + path, kiosk_mode=True):
                print("Browser could not be opened; use the HTTPS URL above.", flush=True)
        while True:
            runtime.check_running()
            time.sleep(0.1)
    except KeyboardInterrupt:
        pass
    except Exception as error:
        phase = runtime.phase if runtime is not None else "configuration"
        print(f"HTTPS {phase} failed ({type(error).__name__}); no HTTP fallback.", flush=True)
        code = 1
    finally:
        if runtime is not None:
            try:
                result = runtime.close()
                if result["proxy_forced"] or not result["backend_stopped"] or not result["temporary_removed"] or result.get("proxy_exit_code", 0) != 0:
                    print("HTTPS shutdown required forced cleanup or encountered an error.", flush=True)
                    code = 1
            except Exception as error:
                print(f"HTTPS cleanup failed ({type(error).__name__}).", flush=True)
                code = 1
        if lease is not None:
            lease.close()
    return code
