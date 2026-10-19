import argparse
import http.client
import json
import multiprocessing
import os
import secrets
import shutil
import socket
import ssl
import subprocess
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path

from kiosk.app import create_app
from kiosk.core.credentials import save_admin_password
from kiosk.transport.profile import load_profile
from kiosk.transport.runtime import ManagedHttps, admin_request, command
from tools.check_https_prototype import Client, check_tls_rejection, exercise_application
from tools.https_runtime import safe_report


def fixture_factory(root, password, observations=None):
    def factory(overrides):
        app = create_app({**overrides, "BASE_DIR": root, "INSTANCE_DIR": root / "instance",
                          "DATABASE_PATH": root / "instance/kiosk.sqlite", "PRIVATE_UPLOAD_DIR": root / "instance/uploads",
                          "PUBLIC_UPLOAD_DIR": root / "static/uploads", "STATIC_FOLDER": root / "static"})
        if not (root / "initialized").exists():
            save_admin_password(app, password, setup=True)
            (root / "initialized").touch()
        if observations is not None:
            original = app.wsgi_app

            def observed(environ, start_response):
                observations.append({"scheme": environ.get("wsgi.url_scheme") == "https",
                                     "address": environ.get("REMOTE_ADDR") == "127.0.0.1",
                                     "host": environ.get("HTTP_HOST") == overrides["EXPECTED_AUTHORITY"],
                                     "stripped": all(name not in environ for name in ("HTTP_FORWARDED", "HTTP_X_REAL_IP", "HTTP_X_FORWARDED_PORT"))})
                return original(environ, start_response)

            app.wsgi_app = observed
        return app
    return factory


def owned_child(filename, root, connection):
    runtime = None
    try:
        runtime = ManagedHttps(load_profile(filename), fixture_factory(Path(root), secrets.token_urlsafe(24)))
        runtime.start()
        connection.send({"pid": runtime.process.pid, "temporary": runtime.temporary.name})
        while True:
            runtime.check_running()
            time.sleep(0.1)
    except BaseException:
        connection.send({"failed": True})
    finally:
        if runtime is not None:
            runtime.close()
        connection.close()


def live_scenario(caddy, pwsh, root, report):
    deadline = time.monotonic() + 180
    command([str(pwsh), "-NoProfile", "-NonInteractive", "-File", str(Path(__file__).with_name("https_certificates.ps1")),
             "-OutputDirectory", str(root)], root, deadline)
    with socket.socket() as reservation:
        reservation.bind(("127.0.0.1", 0))
        port = reservation.getsockname()[1]
    data = {"schema_version": 1, "public_origin": f"https://127.0.0.1:{port}", "listen_host": "127.0.0.1",
            "caddy_executable": str(caddy), "certificate_file": "valid.pem", "private_key_file": "valid.key", "ca_file": "authority.pem"}
    filename = root / "https.json"
    filename.write_text(json.dumps(data), encoding="utf-8")
    profile = load_profile(filename)
    observations = []
    password = secrets.token_urlsafe(24)
    factory = fixture_factory(root, password, observations)

    def observed_factory(overrides):
        return factory({**overrides, "EXPECTED_AUTHORITY": profile.authority})

    runtime = ManagedHttps(profile, observed_factory)
    try:
        runtime.start()
        report["phase"] = "managed_application"
        script = ("Get-NetTCPConnection -State Listen -ErrorAction Stop | Where-Object { $_.OwningProcess -in @(" +
                  f"{os.getpid()},{runtime.process.pid}" + ") } | Select-Object LocalAddress,LocalPort,OwningProcess | ConvertTo-Json -Compress")
        result = command([str(pwsh), "-NoProfile", "-NonInteractive", "-Command", script], root, deadline)
        listeners = json.loads(result.stdout.decode("utf-8-sig"))
        if isinstance(listeners, dict):
            listeners = [listeners]
        actual = {(item["LocalAddress"], item["LocalPort"], item["OwningProcess"]) for item in listeners}
        expected = {("127.0.0.1", port, runtime.process.pid), ("127.0.0.1", runtime.admin_port, runtime.process.pid),
                    ("127.0.0.1", int(runtime.server.effective_port), os.getpid())}
        if actual != expected:
            raise RuntimeError("Unexpected managed listener.")
        report["checks"].append("three_expected_listeners")
        plaintext = http.client.HTTPConnection("127.0.0.1", port, timeout=2)
        try:
            plaintext.request("GET", "/admin/login")
            with plaintext.getresponse() as response:
                response.read()
                if response.status != 400 or response.getheader("Set-Cookie"):
                    raise RuntimeError("Plaintext managed request was accepted.")
                report["http_statuses"]["400"] = report["http_statuses"].get("400", 0) + 1
        finally:
            plaintext.close()
        administration = http.client.HTTPConnection("127.0.0.1", runtime.admin_port, timeout=2)
        try:
            administration.request("GET", "/config/", headers={"Origin": "http://untrusted.invalid"})
            with administration.getresponse() as response:
                response.read()
                if response.status != 403:
                    raise RuntimeError("Untrusted administrative origin was accepted.")
        finally:
            administration.close()
        report["checks"].append("plaintext_and_untrusted_admin_origin_rejected")
        context = profile.trust_context()
        client = Client(port, context, deadline, report)
        exercise_application(client, password, context, report)
        check_tls_rejection(port, ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT), deadline, report, "unknown_authority")
        if not observations or any(not all(item.values()) for item in observations):
            raise RuntimeError("Incorrect managed request metadata.")
        report["metadata_requests"] = len(observations)
        report["cleanup"]["first"] = runtime.close()
        if report["cleanup"]["first"]["proxy_forced"] or report["cleanup"]["first"].get("proxy_exit_code") != 0:
            raise RuntimeError("Managed proxy did not stop gracefully.")
        report["checks"].append("graceful_proxy_backend_shutdown")
        runtime = ManagedHttps(profile, observed_factory)
        runtime.start()
        client.request("/admin")
        report["checks"].append("session_survives_managed_restart")
        status, unused = admin_request(runtime.admin_port, "/stop", "POST")
        if status != 200:
            raise RuntimeError("Managed proxy stop failed.")
        runtime.process.wait(timeout=10)
        try:
            runtime.check_running()
        except RuntimeError:
            report["checks"].append("proxy_failure_detected")
        else:
            raise RuntimeError("Proxy failure was ignored.")
    finally:
        report["cleanup"]["final"] = runtime.close()
    report["phase"] = "backend_failure"
    runtime = ManagedHttps(profile, fixture_factory(root, password))
    try:
        runtime.start()
        runtime.loop_stopped.set()
        runtime.thread.join(timeout=2)
        try:
            runtime.check_running()
        except RuntimeError:
            report["checks"].append("backend_failure_detected_and_proxy_stopped")
        else:
            raise RuntimeError("Backend failure was ignored.")
    finally:
        report["cleanup"]["backend_failure"] = runtime.close()
    if runtime.process.poll() != 0:
        raise RuntimeError("Proxy did not stop after backend failure.")
    for fixture, label in (("wrong-name", "wrong_name"), ("expired", "expired")):
        report["phase"] = label
        invalid = {**data, "certificate_file": f"{fixture}.pem", "private_key_file": f"{fixture}.key"}
        filename.write_text(json.dumps(invalid), encoding="utf-8")
        failed = ManagedHttps(load_profile(filename), fixture_factory(root, password), startup_timeout=3)
        try:
            failed.start()
        except TimeoutError:
            if not failed.closed or failed.process.poll() is None:
                raise RuntimeError("Invalid TLS startup was not cleaned up.") from None
            report["checks"].append(label + "_startup_rejected")
        else:
            failed.close()
            raise RuntimeError("Invalid TLS profile started.")
    filename.write_text(json.dumps(data), encoding="utf-8")
    report["phase"] = "occupied_port"
    with socket.socket() as occupied:
        occupied.bind(("127.0.0.1", port))
        occupied.listen()
        conflict = ManagedHttps(profile, fixture_factory(root, password), startup_timeout=5)
        try:
            conflict.start()
        except RuntimeError:
            if not conflict.closed or conflict.process.poll() is None:
                raise RuntimeError("Conflicting proxy was not cleaned up.") from None
        else:
            conflict.close()
            raise RuntimeError("Conflicting listener was reused.")
    report["checks"].append("occupied_port_rejected_without_reuse")
    for key in ("renewed.key", "missing.key"):
        filename.write_text(json.dumps({**data, "private_key_file": key}), encoding="utf-8")
        try:
            load_profile(filename)
        except (ValueError, ssl.SSLError):
            pass
        else:
            raise RuntimeError("Invalid certificate input accepted.")
    filename.write_text(json.dumps(data), encoding="utf-8")
    report["checks"].append("missing_mismatched_key_rejected")
    report["phase"] = "cli"
    installation = root / "cli-installation"
    installation.mkdir()
    source = Path(__file__).resolve().parent.parent
    shutil.copytree(source / "kiosk", installation / "kiosk", ignore=shutil.ignore_patterns("uploads", "__pycache__"))
    shutil.copy2(source / "serve.py", installation / "serve.py")
    console = root / "cli-output.txt"
    cli = None
    cli_proxy = None
    cli_directory = None
    try:
        with console.open("wb") as output:
            cli = subprocess.Popen([sys.executable, str(installation / "serve.py"), "--https-config", str(filename), "--no-client"],
                                   cwd=installation, stdout=output, stderr=output, creationflags=subprocess.CREATE_NO_WINDOW)
        ready_until = min(deadline, time.monotonic() + 30)
        while time.monotonic() < ready_until:
            if cli.poll() is not None:
                raise RuntimeError("CLI HTTPS startup failed.")
            if "HTTPS ready." in console.read_text(encoding="utf-8"):
                break
            time.sleep(0.05)
        else:
            raise TimeoutError("CLI HTTPS readiness timed out.")
        script = (f"$proxyPid = (Get-NetTCPConnection -State Listen -LocalPort {port} -ErrorAction Stop).OwningProcess; "
                  "(Get-CimInstance Win32_Process -Filter \"ProcessId=$proxyPid\" -ErrorAction Stop).CommandLine")
        result = command([str(pwsh), "-NoProfile", "-NonInteractive", "-Command", script], root, deadline)
        import re

        match = re.search(r'--config\s+"?([^"\r\n]+?proxy\.json)"?\s*$', result.stdout.decode("utf-8-sig").strip())
        if match is None:
            raise RuntimeError("Cannot identify CLI proxy configuration.")
        cli_config = Path(match.group(1)).resolve()
        candidate = cli_config.parent
        if candidate.parent != Path(tempfile.gettempdir()).resolve() or not candidate.name.startswith("kiosk-managed-https-"):
            raise RuntimeError("Unexpected CLI temporary directory.")
        cli_directory = candidate
        configuration = json.loads(cli_config.read_text(encoding="utf-8"))
        cli_proxy = int(configuration["admin"]["listen"].rsplit(":", 1)[1])
        Client(port, profile.trust_context(), deadline, report).request("/api/version")
        admin_request(cli_proxy, "/stop", "POST")
        if cli.wait(timeout=15) != 1 or cli_directory.exists():
            raise RuntimeError("CLI did not clean up after proxy failure.")
        if "no HTTP fallback" not in console.read_text(encoding="utf-8"):
            raise RuntimeError("CLI did not report protected transport failure.")
        report["checks"].append("real_cli_ready_and_proxy_failure_cleanup")
    finally:
        if cli is not None and cli.poll() is None:
            cli.kill()
            cli.wait(timeout=10)
        if cli_directory is not None and cli_directory.exists():
            shutil.rmtree(cli_directory)
    report["phase"] = "owner_failure"
    context = multiprocessing.get_context("spawn")
    parent, child = context.Pipe()
    owner = context.Process(target=owned_child, args=(filename, root, child))
    proxy_handle = None
    orphan = None
    try:
        owner.start()
        child.close()
        if not parent.poll(30):
            raise TimeoutError("Owned child did not start.")
        state = parent.recv()
        if "failed" in state:
            raise RuntimeError("Owned child failed.")
        orphan = Path(state["temporary"])
        import ctypes
        from ctypes import wintypes

        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        kernel.OpenProcess.restype = wintypes.HANDLE
        kernel.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
        kernel.WaitForSingleObject.restype = wintypes.DWORD
        kernel.CloseHandle.argtypes = [wintypes.HANDLE]
        kernel.CloseHandle.restype = wintypes.BOOL
        proxy_handle = kernel.OpenProcess(0x100000, False, state["pid"])
        if not proxy_handle:
            raise OSError("Cannot inspect owned proxy exit.")
        owner.terminate()
        owner.join(timeout=10)
        if owner.is_alive() or kernel.WaitForSingleObject(proxy_handle, 10000) != 0:
            raise RuntimeError("Owner failure left its proxy running.")
        report["checks"].append("owner_failure_kills_proxy")
    finally:
        if owner.is_alive():
            owner.terminate()
            owner.join(timeout=10)
        if proxy_handle:
            kernel.CloseHandle(proxy_handle)
        parent.close()
        if orphan is not None:
            if orphan.resolve().parent != Path(tempfile.gettempdir()).resolve() or not orphan.name.startswith("kiosk-managed-https-"):
                raise RuntimeError("Unexpected owner temporary directory.")
            shutil.rmtree(orphan)
    report["phase"] = "complete"


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--caddy", type=Path, required=True)
    parser.add_argument("--pwsh", type=Path, required=True)
    args = parser.parse_args(argv)
    started = time.monotonic()
    report = {"success": False, "phase": "certificates", "checks": [], "http_statuses": {}, "tls_failures": {}, "cleanup": {}}
    root = None
    try:
        with tempfile.TemporaryDirectory(prefix="kiosk-managed-check-") as directory:
            root = Path(directory)
            live_scenario(args.caddy.resolve(), args.pwsh.resolve(), root, report)
            for cleanup in report["cleanup"].values():
                if cleanup.get("proxy_forced") or not cleanup.get("backend_stopped") or not cleanup.get("temporary_removed") or cleanup.get("proxy_exit_code") != 0:
                    raise RuntimeError("Managed cleanup did not complete successfully.")
        report["success"] = True
    except Exception as error:
        report["error"] = type(error).__name__
    report["cleanup"]["temporary_removed"] = root is not None and not root.exists()
    report["elapsed_seconds"] = round(time.monotonic() - started, 3)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    output = Path(__file__).resolve().parent.parent / "logs/https" / f"managed-{stamp}.json"
    safe_report(output, report)
    print(json.dumps(report, indent=2))
    print(f"Report: logs/https/{output.name}")
    return 0 if report["success"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
