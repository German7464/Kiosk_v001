import hashlib
import json
import multiprocessing
import os
import socket
import subprocess
import threading
import time
from pathlib import Path

from waitress import create_server

from kiosk.app import create_app
from kiosk.core.credentials import save_admin_password


CADDY_VERSION = "v2.11.7"
CADDY_SHA256 = "5f93a9bd555f3aac9d33af2756ba14b3519d8cca4ffd55256bdaeab444c9db2a"
REQUEST_LIMIT = 20 * 1024 * 1024


def remaining(deadline, maximum=10):
    seconds = deadline - time.monotonic()
    if seconds <= 0:
        raise TimeoutError("HTTPS scenario deadline expired.")
    return min(seconds, maximum)


def command(arguments, root, deadline, expected=0):
    result = subprocess.run(arguments, cwd=root, capture_output=True, timeout=remaining(deadline, 30),
                            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
    if (result.returncode == 0) != (expected == 0):
        raise RuntimeError("Unexpected external command result.")
    return result


def verify_caddy(path, root, deadline):
    with Path(path).open("rb") as executable:
        digest = hashlib.file_digest(executable, "sha256").hexdigest()
    if digest != CADDY_SHA256:
        raise ValueError("Caddy executable does not match the pinned Windows amd64 release.")
    result = command([str(path), "version"], root, deadline)
    if result.stdout.decode().split()[0] != CADDY_VERSION:
        raise ValueError("Unexpected Caddy version.")
    return {"version": CADDY_VERSION, "sha256": digest}


def caddy_configuration(port, backend_port, certificate="valid", key=None):
    if type(port) is not int or type(backend_port) is not int or not 0 < port < 65536 or not 0 < backend_port < 65536:
        raise ValueError("Invalid loopback port.")
    if certificate not in {"valid", "renewed", "wrong-name", "expired"} or key not in {None, "renewed", "missing"}:
        raise ValueError("Invalid fixture selection.")
    key = key or certificate
    return f"""{{
    admin off
    persist_config off
    auto_https off
    skip_install_trust
    servers {{
        protocols h1 h2
    }}
    storage file_system {{
        root storage
    }}
}}
https://:{port} {{
    bind 127.0.0.1
    tls {certificate}.pem {key}.key {{
        protocols tls1.2 tls1.3
    }}
    @invalid not host 127.0.0.1
    respond @invalid 400
    @oversized expression `{{http.request.header.Content-Length}} != "" && int({{http.request.header.Content-Length}}) > {REQUEST_LIMIT}`
    respond @oversized 413
    request_body {{
        max_size {REQUEST_LIMIT}
    }}
    request_header -Forwarded
    request_header -X-Forwarded-*
    request_header -X-Real-IP
    reverse_proxy 127.0.0.1:{backend_port} {{
        header_up Host 127.0.0.1:{port}
        header_up X-Forwarded-Host 127.0.0.1:{port}
        header_up X-Forwarded-Proto https
        header_up X-Forwarded-For {{http.request.remote.host}}
    }}
}}
"""


def backend_main(root, password, connection, stopped):
    server = None
    timer = threading.Timer(180, stopped.set)
    timer.daemon = True
    timer.start()
    try:
        root = Path(root)
        app = create_app({
            "BASE_DIR": root, "INSTANCE_DIR": root / "instance", "DATABASE_PATH": root / "instance/kiosk.sqlite",
            "PRIVATE_UPLOAD_DIR": root / "instance/uploads", "PUBLIC_UPLOAD_DIR": root / "static/uploads",
            "STATIC_FOLDER": root / "static", "SESSION_COOKIE_SECURE": True, "TRUSTED_HOSTS": ["127.0.0.1"],
        })
        save_admin_password(app, password, setup=True)
        observation_lock = threading.Lock()

        def observed(environ, start_response):
            checks = {"scheme": environ.get("wsgi.url_scheme") == "https",
                      "address": environ.get("REMOTE_ADDR") == "127.0.0.1",
                      "host": environ.get("HTTP_HOST") == origin,
                      "forwarded_removed": "HTTP_FORWARDED" not in environ,
                      "real_ip_removed": "HTTP_X_REAL_IP" not in environ,
                      "forwarded_port_removed": "HTTP_X_FORWARDED_PORT" not in environ}
            with observation_lock:
                connection.send({"metadata_checks": checks})
            return app(environ, start_response)

        server = create_server(observed, host="127.0.0.1", port=0, threads=4, map={},
                               max_request_body_size=REQUEST_LIMIT, trusted_proxy="127.0.0.1", trusted_proxy_count=1,
                               trusted_proxy_headers={"x-forwarded-for", "x-forwarded-proto", "x-forwarded-host"},
                               clear_untrusted_proxy_headers=True)
        connection.send({"port": server.effective_port})
        origin_deadline = time.monotonic() + 10
        while not connection.poll(0.05):
            if stopped.is_set():
                return
            remaining(origin_deadline)
        origin = connection.recv()["origin"]
        while not stopped.is_set():
            server.asyncore.loop(timeout=0.05, count=1, map=server._map)
    except Exception:
        connection.send({"backend_error": True})
    finally:
        timer.cancel()
        if server is not None:
            server.task_dispatcher.shutdown()
            server.close()
            server.asyncore.close_all(map=server._map)
        connection.close()


def stop_process(process, stopped=None):
    forced = False
    if stopped is not None:
        stopped.set()
        process.join(timeout=5)
        if process.is_alive():
            forced = True
            process.terminate()
            process.join(timeout=5)
        alive = process.is_alive()
        code = process.exitcode
    else:
        if process.poll() is None:
            process.terminate()
            forced = True
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)
        alive = process.poll() is None
        code = process.returncode
    if alive:
        raise RuntimeError("Owned process did not stop.")
    return {"stopped": True, "forced": forced, "exit_code": code}


class Backend:
    def __init__(self, root, password, deadline):
        context = multiprocessing.get_context("spawn")
        self.connection, child = context.Pipe()
        self.stopped = context.Event()
        self.process = context.Process(target=backend_main, args=(root, password, child, self.stopped))
        self.observations = []
        self.closed = False
        self.process.start()
        child.close()
        try:
            if not self.connection.poll(remaining(deadline)):
                raise TimeoutError("Backend startup timed out.")
            self.port = int(self.connection.recv()["port"])
            self.reader = threading.Thread(target=self.read, daemon=True)
            self.reader.start()
        except BaseException:
            stop_process(self.process, self.stopped)
            self.connection.close()
            raise

    def read(self):
        try:
            while True:
                self.observations.append(self.connection.recv())
        except (EOFError, OSError):
            return

    def close(self):
        if self.closed:
            return self.result
        self.result = stop_process(self.process, self.stopped)
        self.reader.join(timeout=2)
        self.connection.close()
        self.closed = True
        if self.reader.is_alive():
            raise RuntimeError("Metadata reader did not stop.")
        return self.result


class Proxy:
    def __init__(self, executable, root, backend_port, deadline, certificate="valid", key=None):
        self.process = None
        self.root = Path(root)
        with socket.socket() as reserved:
            reserved.bind(("127.0.0.1", 0))
            self.port = reserved.getsockname()[1]
        configuration = self.root / "Caddyfile"
        configuration.write_text(caddy_configuration(self.port, backend_port, certificate, key), encoding="utf-8")
        arguments = [str(executable), "run", "--config", str(configuration), "--adapter", "caddyfile"]
        self.watchdog = threading.Timer(remaining(deadline, 180), self.expire)
        self.watchdog.daemon = True
        self.process = subprocess.Popen(arguments, cwd=root, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                        creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
        try:
            self.watchdog.start()
            ready_until = min(deadline, time.monotonic() + 10)
            while True:
                if self.process.poll() is not None:
                    raise RuntimeError("TLS proxy failed to start.")
                remaining(ready_until)
                try:
                    with socket.create_connection(("127.0.0.1", self.port), timeout=0.2):
                        break
                except OSError:
                    time.sleep(0.05)
        except BaseException:
            self.close()
            raise

    def expire(self):
        if self.process.poll() is None:
            self.process.kill()

    def close(self):
        self.watchdog.cancel()
        return stop_process(self.process)


def safe_report(path, report):
    allowed = {"success", "phase", "error", "checks", "http_statuses", "tls_failures", "caddy", "pwsh_version",
               "cleanup", "elapsed_seconds", "metadata_requests", "certificate_replaced"}
    if set(report) - allowed:
        raise ValueError("Unexpected report field.")
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8") as output:
        json.dump(report, output, indent=2)
        output.write("\n")
