import argparse
import getpass
import hashlib
import ipaddress
import json
import os
import queue
import secrets
import shutil
import socket
import ssl
import threading
import time
import warnings
from datetime import datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory

from PIL import Image

from kiosk.core.credentials import validate_password
from kiosk.database import get_database, increase_content_version
from kiosk.transport.profile import load_profile
from kiosk.transport.runtime import ManagedHttps
from tools.check_https_prototype import Client
from tools.check_managed_https import fixture_factory
from tools.https_runtime import command, verify_caddy


CLIENT_CHECKS = frozenset({
    "unknown_authority", "routes", "csrf_cookie_login", "upload_images_version_fullscreen",
    "password_revocation", "restart_session", "forwarding_host", "source_budget", "remote_budget_after_local",
    "internal_ports_closed", "plaintext_rejected",
})
BROWSER_RESULTS = {
    "untrusted": "ERR_CERT_AUTHORITY_INVALID",
    "trusted": "pages_images_navigation_fullscreen",
    "updated": "LAN_updated_visible_without_reload",
    "removed": "ERR_CERT_AUTHORITY_INVALID",
}


def lan_ipv4(value):
    address = ipaddress.IPv4Address(value)
    if address.is_loopback or address.is_unspecified or address.is_multicast or address.is_reserved or int(address) >> 24 == 0:
        raise ValueError("Unicast LAN IPv4 required.")
    return str(address)


def validate_addresses(server, client, port):
    server, client = lan_ipv4(server), lan_ipv4(client)
    if server == client or type(port) is not int or not 1024 <= port <= 65535:
        raise ValueError("Distinct addresses and an unprivileged TCP port are required.")
    with socket.socket() as listener:
        listener.bind((server, port))
    return server, client


def validate_client_report(filename, session):
    filename = Path(filename)
    if filename.stat().st_size > 32768:
        raise ValueError("Client report too large.")
    data = json.loads(filename.read_text(encoding="utf-8-sig"))
    if (not isinstance(data, dict) or set(data) != {"schema_version", "session", "success", "checks", "http_statuses", "error"}
            or type(data["schema_version"]) is not int or data["schema_version"] != 1
            or data["session"] != session or data["success"] is not True or data["error"] is not None
            or not isinstance(data["checks"], list) or len(data["checks"]) != len(CLIENT_CHECKS)
            or any(not isinstance(item, str) for item in data["checks"]) or set(data["checks"]) != CLIENT_CHECKS):
        raise ValueError("Incomplete or unrelated client report.")
    codes = data["http_statuses"]
    if (not isinstance(codes, dict) or not {"200", "302", "400", "401", "403", "429"} <= set(codes)
            or any(key not in {"200", "302", "400", "401", "403", "429"}
                   or type(value) is not int or not 0 < value < 10000 for key, value in codes.items())):
        raise ValueError("Invalid client HTTP status evidence.")
    return {"checks": sorted(CLIENT_CHECKS), "http_statuses": codes}


def cleanup_ok(result):
    return (result.get("proxy_forced") is False and result.get("proxy_exit_code") == 0
            and result.get("backend_stopped") is True and result.get("temporary_removed") is True)


class Observations:
    def __init__(self, server, client, authority, session):
        self.server, self.client, self.authority, self.session = server, client, authority, session
        self.lock = threading.Lock()
        self.counts = {"server": 0, "client": 0}
        self.invalid = 0
        self.remote_429 = 0
        self.budget_marked = 0

    def wrap(self, application):
        def observed(environ, start_response):
            peer = environ.get("REMOTE_ADDR")
            valid = (environ.get("wsgi.url_scheme") == "https" and environ.get("HTTP_HOST") == self.authority
                     and peer in {self.server, self.client}
                     and all(name not in environ for name in ("HTTP_FORWARDED", "HTTP_X_REAL_IP", "HTTP_X_FORWARDED_PORT")))
            with self.lock:
                self.invalid += not valid
                if peer in {self.server, self.client}:
                    self.counts["client" if peer == self.client else "server"] += 1

            def respond(status, headers, exc_info=None):
                if peer == self.client:
                    with self.lock:
                        if status.startswith("429 "):
                            self.remote_429 = time.monotonic()
                        if (environ.get("PATH_INFO") == "/api/version"
                                and environ.get("QUERY_STRING") == f"lan_budget={self.session}"):
                            self.budget_marked = time.monotonic()
                return start_response(status, headers, exc_info)
            return application(environ, respond)
        return observed


class LanFixture:
    def __init__(self, args, root, password):
        self.args, self.root, self.password = args, root, password
        self.session = secrets.token_hex(16)
        self.runtime = None
        self.cleanups = []
        self.browser = {}
        self.client_report = None
        self.local_budget = 0
        self.updated = False
        self.restarted = False
        self.manifest = root / "client/session.json"
        authority = f"{args.server_ip}:{args.port}"
        self.observations = Observations(args.server_ip, args.client_ip, authority, self.session)
        self.factory = fixture_factory(root / "installation", password)
        self.profile_file = root / "https.json"

    def app_factory(self, overrides):
        app = self.factory(overrides)
        app.wsgi_app = self.observations.wrap(app.wsgi_app)
        return app

    def prepare(self):
        deadline = time.monotonic() + 60
        verify_caddy(self.args.caddy, self.root, deadline)
        command([str(self.args.pwsh), "-NoProfile", "-NonInteractive", "-File",
                 str(Path(__file__).with_name("https_certificates.ps1")), "-OutputDirectory", str(self.root),
                 "-LanAddress", self.args.server_ip], self.root, deadline)
        self.profile_file.write_text(json.dumps({
            "schema_version": 1, "public_origin": f"https://{self.args.server_ip}:{self.args.port}",
            "listen_host": self.args.server_ip, "caddy_executable": str(self.args.caddy),
            "certificate_file": "valid.pem", "private_key_file": "valid.key", "ca_file": "authority.pem",
        }), encoding="utf-8")
        bundle = self.manifest.parent
        bundle.mkdir()
        for name in ("check_lan_https.ps1", "browser_trust.ps1"):
            shutil.copy2(Path(__file__).with_name(name), bundle / name)
        shutil.copy2(self.root / "authority.pem", bundle / "authority.pem")
        Image.new("RGB", (1920, 1080), "teal").save(bundle / "fixture.png")
        der = ssl.PEM_cert_to_DER_cert((self.root / "authority.pem").read_text(encoding="utf-8"))
        self.digest = hashlib.sha256(der).hexdigest()
        self.start()

    def start(self):
        self.runtime = ManagedHttps(load_profile(self.profile_file), self.app_factory)
        self.runtime.start()
        self.check_listeners()
        self.manifest.write_text(json.dumps({"schema_version": 1, "session": self.session,
            "origin": self.runtime.profile.public_origin, "client_ip": self.args.client_ip,
            "backend_port": int(self.runtime.server.effective_port), "admin_port": self.runtime.admin_port}), encoding="utf-8")

    def check_listeners(self):
        script = ("Get-NetTCPConnection -State Listen -ErrorAction Stop | Where-Object { $_.OwningProcess -in @(" +
                  f"{os.getpid()},{self.runtime.process.pid}" + ") } | Select-Object LocalAddress,LocalPort,OwningProcess | ConvertTo-Json -Compress")
        result = command([str(self.args.pwsh), "-NoProfile", "-NonInteractive", "-Command", script], self.root, time.monotonic() + 15)
        listeners = json.loads(result.stdout.decode("utf-8-sig"))
        if isinstance(listeners, dict):
            listeners = [listeners]
        actual = {(item["LocalAddress"], item["LocalPort"], item["OwningProcess"]) for item in listeners}
        expected = {(self.args.server_ip, self.args.port, self.runtime.process.pid),
                    ("127.0.0.1", self.runtime.admin_port, self.runtime.process.pid),
                    ("127.0.0.1", int(self.runtime.server.effective_port), os.getpid())}
        if actual != expected:
            raise RuntimeError("Unexpected owned listeners.")

    def stop(self):
        if self.runtime is not None:
            result = self.runtime.close()
            self.cleanups.append(result)
            self.runtime = None
            if not cleanup_ok(result):
                raise RuntimeError("Managed cleanup incomplete.")

    def restart(self):
        self.stop()
        self.start()
        self.restarted = True

    def budget(self):
        now = time.monotonic()
        with self.observations.lock:
            if not (0 < now - self.observations.remote_429 < 30 and 0 < now - self.observations.budget_marked < 30):
                raise RuntimeError("Run budget immediately after the client budget prompt.")
        report = {"http_statuses": {}}
        client = Client(self.args.port, self.runtime.profile.trust_context(), now + 15, report)
        client.base = self.runtime.profile.public_origin
        client.form("/admin/login", {"username": "lan-independent-source", "password": "invalid"}, 401)
        self.local_budget = time.monotonic()

    def update(self):
        if self.browser.get("trusted") != BROWSER_RESULTS["trusted"]:
            raise RuntimeError("Record trusted browser observation first.")
        with self.runtime.app.app_context():
            database = get_database()
            if database.execute("SELECT COUNT(*) FROM events").fetchone()[0] != 1:
                raise RuntimeError("Expected the client event fixture.")
            database.execute("UPDATE events SET title = ?", ("LAN updated",))
            increase_content_version(database)
            database.commit()
        self.updated = True

    def finish(self):
        with self.observations.lock:
            valid = (self.observations.invalid == 0 and all(self.observations.counts.values())
                     and self.observations.remote_429 > self.local_budget > 0)
        if (not valid or not self.restarted or not self.updated or self.client_report is None
                or self.browser != BROWSER_RESULTS):
            raise RuntimeError("LAN evidence incomplete.")
        with self.runtime.app.app_context():
            rows = get_database().execute("SELECT image_kiosk, image_tv, image_thumb FROM events").fetchall()
            if len(rows) != 1:
                raise RuntimeError("Missing event fixture.")
            for filename in rows[0]:
                if not filename or not filename.startswith("/static/uploads/"):
                    raise RuntimeError("Invalid fixture media path.")
                media = self.runtime.app.config["PUBLIC_UPLOAD_DIR"] / filename.removeprefix("/static/uploads/")
                if not media.resolve().is_relative_to(self.runtime.app.config["PUBLIC_UPLOAD_DIR"].resolve()):
                    raise RuntimeError("Fixture media outside isolated uploads.")
                with Image.open(media) as image:
                    image.load()


def execute(fixture, line):
    action, _, value = line.strip().partition(" ")
    if action == "restart" and not value:
        fixture.restart()
    elif action == "budget" and not value:
        fixture.budget()
    elif action == "update" and not value:
        fixture.update()
    elif action == "import" and value:
        fixture.client_report = validate_client_report(value, fixture.session)
    elif action == "record":
        stage, _, result = value.partition(" ")
        if stage not in BROWSER_RESULTS or result != BROWSER_RESULTS[stage]:
            raise ValueError("Unknown browser observation.")
        previous = {"trusted": "untrusted", "updated": "trusted", "removed": "updated"}.get(stage)
        if (previous and previous not in fixture.browser) or (stage == "updated" and not fixture.updated):
            raise ValueError("Browser observation out of order.")
        fixture.browser[stage] = result
    elif action == "finish" and not value:
        fixture.finish()
        return False
    elif action == "abort" and not value:
        raise EOFError("LAN check aborted.")
    else:
        raise ValueError("Unknown LAN command.")
    return True


def firewall_commands(args, session):
    name = f"Kiosk-LAN-test-{session}"
    return (f"New-NetFirewallRule -Name '{name}' -DisplayName '{name}' -Direction Inbound -Action Allow "
            f"-Protocol TCP -LocalAddress {args.server_ip} -LocalPort {args.port} -RemoteAddress {args.client_ip} -Profile Private",
            f"Remove-NetFirewallRule -Name '{name}'")


def main(argv=None):
    parser = argparse.ArgumentParser(description="Disposable two-PC HTTPS verification; no automatic trust/firewall changes.")
    parser.add_argument("--server-ip", required=True)
    parser.add_argument("--client-ip", required=True)
    parser.add_argument("--port", type=int, default=8443)
    parser.add_argument("--caddy", type=Path, required=True)
    parser.add_argument("--pwsh", type=Path, required=True)
    parser.add_argument("--minutes", type=int, default=60)
    args = parser.parse_args(argv)
    if os.name != "nt" or not 1 <= args.minutes <= 120:
        parser.error("Windows and a 1-120 minute budget are required.")
    report = {"success": False, "physical_lan": "Pending", "checks": [], "browser_observations": {}, "cleanup": {}}
    fixture = None
    temporary = None
    started = time.monotonic()
    try:
        args.server_ip, args.client_ip = validate_addresses(args.server_ip, args.client_ip, args.port)
        args.caddy, args.pwsh = args.caddy.resolve(strict=True), args.pwsh.resolve(strict=True)
        with warnings.catch_warnings():
            warnings.simplefilter("error", getpass.GetPassWarning)
            password = getpass.getpass("Disposable admin password (also enter on client): ")
            validate_password(password)
            if password != getpass.getpass("Confirm disposable password: "):
                raise ValueError("Passwords differ.")
        with TemporaryDirectory(prefix="kiosk-lan-check-") as directory:
            temporary = Path(directory)
            fixture = LanFixture(args, temporary, password)
            try:
                fixture.prepare()
                print(f"Client bundle (PUBLIC files only): {fixture.manifest.parent}", flush=True)
                print(f"Verify CA SHA-256 independently: {fixture.digest}", flush=True)
                print(f"Origin: {fixture.runtime.profile.public_origin}", flush=True)
                add, remove = firewall_commands(args, fixture.session)
                print(f"Optional manual firewall rule (elevated PowerShell):\n{add}\nCleanup:\n{remove}", flush=True)
                print("Commands: restart, budget, update, import <client-report>, record <stage> <result>, finish, abort", flush=True)
                inputs = queue.Queue()

                def read_console():
                    try:
                        while True:
                            inputs.put(input())
                    except EOFError:
                        inputs.put("abort")

                threading.Thread(target=read_console, daemon=True).start()
                print("lan> ", end="", flush=True)
                deadline = started + args.minutes * 60
                running = True
                while running:
                    fixture.runtime.check_running()
                    if time.monotonic() >= deadline:
                        raise TimeoutError("LAN session expired.")
                    try:
                        line = inputs.get(timeout=0.1)
                    except queue.Empty:
                        continue
                    try:
                        running = execute(fixture, line)
                        print("Command completed.", flush=True)
                    except (ValueError, RuntimeError) as error:
                        print(f"Command rejected ({type(error).__name__}). Check documented prerequisites.", flush=True)
                    if running:
                        print("lan> ", end="", flush=True)
                report["checks"] = fixture.client_report["checks"] + ["three_expected_listeners", "local_source_independent", "three_images_decoded"]
                report["http_statuses"] = fixture.client_report["http_statuses"]
                report["browser_observations"] = dict(fixture.browser)
                print("Confirm remote test root absent, Chrome profile removed, and optional firewall rule removed.", flush=True)
                while True:
                    fixture.runtime.check_running()
                    if time.monotonic() >= deadline:
                        raise TimeoutError("Cleanup confirmation expired.")
                    try:
                        confirmation = inputs.get(timeout=0.1)
                    except queue.Empty:
                        continue
                    if confirmation != "cleanup-confirmed":
                        raise RuntimeError("Operator cleanup not confirmed.")
                    break
                report["cleanup"]["operator_confirmed"] = True
            finally:
                fixture.stop()
        report["success"] = True
        report["physical_lan"] = "Verified"
    except (Exception, KeyboardInterrupt) as error:
        report["error"] = type(error).__name__
    finally:
        report["cleanup"]["temporary_removed"] = temporary is not None and not temporary.exists()
        report["cleanup"]["managed"] = fixture.cleanups if fixture else []
        report["success"] = report["success"] and report["cleanup"]["temporary_removed"]
        if not report["success"]:
            report["physical_lan"] = "Pending"
        report["elapsed_seconds"] = round(time.monotonic() - started, 3)
        output = Path(__file__).resolve().parent.parent / "logs/https" / ("lan-" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ") + ".json")
        output.parent.mkdir(parents=True, exist_ok=True)
        with output.open("x", encoding="utf-8") as stream:
            json.dump(report, stream, indent=2)
        print(json.dumps(report, indent=2))
        print(f"Report: logs/https/{output.name}")
        if fixture:
            print("If interrupted, complete remote CA/profile cleanup and remove only the printed firewall rule.")
    return 0 if report["success"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
