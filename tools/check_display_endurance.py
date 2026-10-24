import argparse
import hashlib
import http.client
import io
import ipaddress
import json
import math
import os
from pathlib import Path
import re
import secrets
import shutil
import socket
import ssl
import subprocess
import tempfile
import threading
import time
from urllib.parse import urlsplit
import zipfile


DURATION = 1800
SCHEDULE = ((300, "update_1"), (600, "stop"), (660, "restart"), (720, "update_2"), (1500, "update_3"))
STATE_PATH = "/_display-test/state"


def write_json(path, data):
    temporary = path.with_suffix(".pending")
    temporary.write_text(json.dumps(data, indent=2), encoding="utf-8")
    for attempt in range(21):
        try:
            os.replace(temporary, path)
            return
        except PermissionError:
            if attempt == 20:
                raise
            time.sleep(.05)


def due_actions(elapsed, completed):
    return [name for seconds, name in SCHEDULE if elapsed >= seconds and name not in completed]


def classify_sample(sample, outages):
    if sample.get("error") in {"ConnectionRefusedError", "TimeoutError", "ConnectionResetError", "OSError", "RemoteDisconnected"}:
        if any(sample["start"] <= end and sample["end"] >= start for start, end in outages):
            return "expected_outage"
    return "ok" if sample.get("status") == 200 and sample.get("valid") is True else "unexpected_failure"


def validate_manifest(manifest, digest, authority):
    if not re.fullmatch(r"[a-f0-9]{64}", digest):
        raise ValueError("Exact independently compared SHA-256 required")
    actual = hashlib.sha256(ssl.PEM_cert_to_DER_cert(authority.read_text(encoding="utf-8"))).hexdigest()
    origin = urlsplit(manifest["origin"])
    address = ipaddress.IPv4Address(origin.hostname)
    if (manifest.get("schema_version") != 1 or actual != digest or origin.scheme != "https"
            or origin.username or origin.password or origin.path or origin.query or origin.fragment
            or not origin.port or address.is_unspecified or address.is_multicast or address.is_loopback
            or not re.fullmatch(r"[a-f0-9]{32}", manifest.get("session", ""))
            or not re.fullmatch(r"[a-f0-9]{64}", manifest.get("display_capability", ""))):
        raise ValueError("Invalid fixture manifest or authority")
    return origin


def request_json(origin, context, path, session=None):
    connection = http.client.HTTPSConnection(origin.hostname, origin.port, context=context, timeout=10)
    deadline = time.monotonic() + 10
    expired = threading.Event()
    transports = []

    def remaining():
        seconds = deadline - time.monotonic()
        if seconds <= 0 or expired.is_set():
            raise TimeoutError("Request deadline exceeded")
        return seconds

    def connect(address, timeout, source_address=None):
        transport = socket.create_connection(address, timeout=remaining(), source_address=source_address)
        transports.append(transport)
        transport.settimeout(remaining())
        return transport

    def expire():
        expired.set()
        for transport in tuple(transports):
            try:
                transport.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass

    connection._create_connection = connect
    timer = threading.Timer(10, expire)
    timer.daemon = True
    timer.start()
    response = None
    try:
        connection.connect()
        transports.append(connection.sock)
        connection.sock.settimeout(remaining())
        headers = {"X-Display-Test": session} if session else {}
        connection.request("GET", path, headers=headers)
        connection.sock.settimeout(remaining())
        response = connection.getresponse()
        chunks = []
        size = 0
        while True:
            seconds = remaining()
            transport = connection.sock or getattr(response.fp, "raw", None)
            if transport is not None:
                transport = getattr(transport, "_sock", transport)
                transport.settimeout(seconds)
            chunk = response.read1(min(65536, 2 * 1024 * 1024 + 1 - size))
            if not chunk:
                break
            size += len(chunk)
            if size > 2 * 1024 * 1024:
                raise ValueError("Response bound exceeded")
            chunks.append(chunk)
        result = json.loads(b"".join(chunks))
        remaining()
        return response.status, result
    except (OSError, http.client.HTTPException) as error:
        if expired.is_set():
            raise TimeoutError("Request deadline exceeded") from error
        raise
    finally:
        timer.cancel()
        if response is not None:
            response.close()
        connection.close()
        for transport in transports:
            transport.close()


def valid_payload(path, data):
    if path == "/api/version":
        return isinstance(data, dict) and type(data.get("content_version")) is int and data["content_version"] >= 1
    return (isinstance(data, dict) and isinstance(data.get("events"), list) and len(data["events"]) == 3
            and all(isinstance(item, dict) and type(item.get("id")) is int
                    and re.fullmatch(r"Endurance [1-3] / generation [0-3]", item.get("title", ""))
                    and isinstance(item.get("image_tv"), str) and item["image_tv"].startswith("/static/uploads/")
                    for item in data["events"]))


def client_main(args):
    manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
    origin = validate_manifest(manifest, args.ca_sha256, args.manifest.parent / "authority.pem")
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    context.minimum_version = ssl.TLSVersion.TLSv1_2
    context.load_verify_locations(cafile=str(args.manifest.parent / "authority.pem"))
    report = {"schema_version": 1, "session": manifest["session"], "completed": False, "samples": [], "error": None}
    began = None
    try:
        waiting_deadline = time.monotonic() + 1200
        while time.monotonic() < waiting_deadline:
            before = time.monotonic()
            status, state = request_json(origin, context, STATE_PATH, manifest["display_capability"])
            after = time.monotonic()
            elapsed = state.get("elapsed")
            if status != 200:
                raise ValueError("Fixture identity rejected")
            if elapsed is not None:
                if type(elapsed) not in (int, float) or not math.isfinite(elapsed) or not 0 <= elapsed <= 15:
                    raise ValueError("Client must join at the beginning")
                began = (before + after) / 2 - elapsed
                report["alignment_uncertainty_seconds"] = (after - before) / 2
                break
            print("Waiting for server start", flush=True)
            time.sleep(2)
        if began is None:
            raise TimeoutError("Start not received")
        print("30-minute client sampling started", flush=True)
        next_sample = time.monotonic()
        while time.monotonic() - began < DURATION:
            if time.monotonic() < next_sample:
                time.sleep(min(.2, next_sample - time.monotonic()))
                continue
            for path in ("/api/version", "/api/events"):
                sample = {"route": path, "start": round(time.monotonic() - began, 3)}
                try:
                    status, data = request_json(origin, context, path)
                    sample.update(status=status, valid=bool(valid_payload(path, data)))
                    if sample["valid"]:
                        sample["version" if path == "/api/version" else "generation"] = (
                            data["content_version"] if path == "/api/version" else int(data["events"][0]["title"][-1]))
                except (OSError, ValueError, http.client.HTTPException) as error:
                    sample["error"] = type(error).__name__
                sample["end"] = round(time.monotonic() - began, 3)
                sample["milliseconds"] = round((sample["end"] - sample["start"]) * 1000, 1)
                report["samples"].append(sample)
            write_json(args.output, report)
            next_sample = max(next_sample + 10, time.monotonic())
        report["completed"] = True
    except (Exception, KeyboardInterrupt) as error:
        report["error"] = type(error).__name__
    finally:
        report["elapsed"] = round(time.monotonic() - began, 3) if began is not None else 0
        write_json(args.output, report)
    print(json.dumps({"completed": report["completed"], "samples": len(report["samples"]), "error": report["error"]}), flush=True)
    return 0 if report["completed"] else 1


def create_fixture(args, root, password, state):
    from tools.check_lan_https import LanFixture

    class DisplayFixture(LanFixture):
        def app_factory(self, overrides):
            app = super().app_factory(overrides)
            application = app.wsgi_app

            def observed(environ, start_response):
                if environ.get("PATH_INFO") == STATE_PATH:
                    if (environ.get("REQUEST_METHOD") != "GET" or environ.get("REMOTE_ADDR") != self.args.client_ip
                            or environ.get("wsgi.url_scheme") != "https" or environ.get("HTTP_X_DISPLAY_TEST") != state["capability"]):
                        start_response("404 Not Found", [("Content-Length", "0")])
                        return [b""]
                    elapsed = None if state["began"] is None else time.monotonic() - state["began"]
                    body = json.dumps({"elapsed": elapsed}).encode()
                    start_response("200 OK", [("Content-Type", "application/json"), ("Cache-Control", "no-store"), ("Content-Length", str(len(body)))])
                    return [body]
                return application(environ, start_response)
            app.wsgi_app = observed
            return app
    return DisplayFixture(args, root, password)


def change_content(fixture, generation):
    from PIL import Image, ImageDraw
    from werkzeug.datastructures import FileStorage
    from kiosk.core.images import process_event_image
    from kiosk.database import get_database
    from kiosk.features.admin.routes import save_event_change, update_event_images

    with fixture.runtime.app.app_context():
        database = get_database()
        for index, color in enumerate(("teal", "navy", "maroon"), 1):
            image = Image.new("RGB", (1280, 720), color)
            ImageDraw.Draw(image).text((70, 80), f"CARD {index} / GENERATION {generation}", fill="white", font_size=64)
            buffer = io.BytesIO()
            image.save(buffer, "PNG")
            buffer.seek(0)
            paths = process_event_image(FileStorage(buffer, filename="fixture.png", content_type="image/png"))
            title = f"Endurance {index} / generation {generation}"
            if generation == 0:
                cursor = database.execute("INSERT INTO events(title,short_description,event_date,place,status,sort_order,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?)",
                                          (title, "Synthetic endurance fixture", "2026-11-01", "Isolated LAN test", "active", index, "test", "test"))
                event_id = cursor.lastrowid
            else:
                event_id = index
                database.execute("UPDATE events SET title=? WHERE id=?", (title, event_id))
            update_event_images(database, event_id, paths)
        save_event_change(database)
        return int(database.execute("SELECT value FROM settings WHERE key='content_version'").fetchone()[0])


def collect_resources(args, fixture):
    process_ids = [os.getpid()]
    if fixture.runtime is not None:
        process_ids.append(fixture.runtime.process.pid)
    script = ("Get-Process -Id " + ",".join(map(str, process_ids))
              + " -ErrorAction Stop | Select-Object Id,CPU,WorkingSet64,PrivateMemorySize64 | ConvertTo-Json -Compress")
    result = subprocess.run([str(args.pwsh), "-NoProfile", "-NonInteractive", "-Command", script],
                            capture_output=True, timeout=10, creationflags=subprocess.CREATE_NO_WINDOW, check=True)
    rows = json.loads(result.stdout.decode("utf-8-sig"))
    rows = rows if isinstance(rows, list) else [rows]
    return [{"role": "python" if row["Id"] == os.getpid() else "caddy", "pid": row["Id"],
             "cpu_seconds": row["CPU"], "working_bytes": row["WorkingSet64"], "private_bytes": row["PrivateMemorySize64"]} for row in rows]


def run_schedule(fixture, state, report, clock=time.monotonic, sleeper=time.sleep, resources=collect_resources):
    completed = set()
    next_resource = 0
    state["began"] = clock()
    while clock() - state["began"] < DURATION:
        elapsed = clock() - state["began"]
        if (report["output"] / "control.txt").read_text().strip() == "abort":
            raise KeyboardInterrupt()
        for action in due_actions(elapsed, completed):
            started = clock() - state["began"]
            if action == "stop":
                report["outages"].append([started, None])
                fixture.stop()
            elif action == "restart":
                fixture.start()
                report["outages"][-1][1] = clock() - state["began"]
            else:
                report["generation"] += 1
                report["version"] = change_content(fixture, report["generation"])
            completed.add(action)
            report["actions"].append({"action": action, "start": started, "end": clock() - state["began"]})
            print(json.dumps(report["actions"][-1]), flush=True)
        if fixture.runtime is not None:
            fixture.runtime.check_running()
        if elapsed >= next_resource:
            report["resources"].append({"elapsed": elapsed, "processes": resources(fixture.args, fixture)})
            next_resource = elapsed + 60
        report["elapsed"] = clock() - state["began"]
        write_json(report["output"] / "status.json", {key: value for key, value in report.items() if key != "output"})
        sleeper(.2)
    report["elapsed"] = clock() - state["began"]
    report["schedule_completed"] = len(completed) == len(SCHEDULE)
    write_json(report["output"] / "status.json", {key: value for key, value in report.items() if key != "output"})


def server_main(args):
    from tools.check_lan_https import cleanup_ok, validate_addresses

    if os.name != "nt":
        raise ValueError("Windows required")
    args.caddy = args.caddy.resolve(strict=True)
    args.pwsh = args.pwsh.resolve(strict=True)
    args.output = args.output.resolve()
    args.server_ip, args.client_ip = validate_addresses(args.server_ip, args.client_ip, args.port)
    args.output.mkdir(parents=True, exist_ok=False)
    control = args.output / "control.txt"
    control.write_text("wait")
    report = {"schema_version": 1, "output": args.output, "schedule_completed": False, "elapsed": 0,
              "generation": 0, "actions": [], "outages": [], "resources": [], "error": None, "cleanup": {}}
    fixture = None
    root = None
    state = {"began": None, "capability": secrets.token_hex(32)}
    try:
        with tempfile.TemporaryDirectory(prefix="kiosk-display-endurance-") as directory:
            root = Path(directory)
            fixture = create_fixture(args, root, secrets.token_urlsafe(24), state)
            try:
                fixture.prepare()
                report["session"] = fixture.session
                report["version"] = change_content(fixture, 0)
                bundle = fixture.manifest.parent
                manifest = json.loads(fixture.manifest.read_text())
                fixture.manifest.write_text(json.dumps({**manifest, "display_capability": state["capability"]}), encoding="utf-8")
                shutil.copy2(Path(__file__), bundle / Path(__file__).name)
                with zipfile.ZipFile(args.output / "client.zip", "w", zipfile.ZIP_DEFLATED) as archive:
                    for name in ("check_display_endurance.py", "browser_trust.ps1", "session.json", "authority.pem"):
                        archive.write(bundle / name, name)
                print(json.dumps({"origin": fixture.runtime.profile.public_origin, "ca_sha256": fixture.digest,
                                  "zip_sha256": hashlib.sha256((args.output / "client.zip").read_bytes()).hexdigest()}), flush=True)
                deadline = time.monotonic() + 1200
                while control.read_text().strip() != "start":
                    if control.read_text().strip() == "abort" or time.monotonic() > deadline:
                        raise TimeoutError("Preparation cancelled or expired")
                    fixture.runtime.check_running()
                    time.sleep(.2)
                run_schedule(fixture, state, report)
                print("Schedule complete; copy client report and finish browser observations, then write finish to control.txt", flush=True)
                deadline = time.monotonic() + 600
                while control.read_text().strip() != "finish":
                    if control.read_text().strip() == "abort" or time.monotonic() > deadline:
                        raise TimeoutError("Completion not confirmed")
                    fixture.runtime.check_running()
                    time.sleep(.2)
                with fixture.observations.lock:
                    report["source_counts"] = dict(fixture.observations.counts)
                    report["invalid_metadata"] = fixture.observations.invalid
            finally:
                fixture.stop()
                report["cleanup"]["managed"] = fixture.cleanups
                report["cleanup"]["managed_ok"] = bool(fixture.cleanups) and all(cleanup_ok(item) for item in fixture.cleanups)
    except (Exception, KeyboardInterrupt) as error:
        report["error"] = type(error).__name__
    finally:
        report["cleanup"]["temporary_removed"] = root is not None and not root.exists()
        write_json(args.output / "server.json", {key: value for key, value in report.items() if key != "output"})
    return 0 if report["schedule_completed"] and not report["error"] and report["cleanup"].get("managed_ok") else 1


def summarize(server, client):
    if server.get("session") != client.get("session") or not server.get("session"):
        raise ValueError("Unrelated session reports")
    outages = server["outages"]
    if len(outages) != 1 or any(end is None or end < start for start, end in outages):
        raise ValueError("Incomplete outage interval")
    counts = {"ok": 0, "expected_outage": 0, "unexpected_failure": 0}
    for sample in client["samples"]:
        counts[classify_sample(sample, outages)] += 1
    generations = sorted({sample["generation"] for sample in client["samples"] if "generation" in sample})
    routes = {route: [sample for sample in client["samples"] if sample["route"] == route] for route in ("/api/version", "/api/events")}
    coverage = all(len(samples) >= 160 and samples[0]["start"] <= 15 and samples[-1]["end"] >= 1780
                   and all(second["start"] - first["start"] <= 31 for first, second in zip(samples, samples[1:]))
                   for samples in routes.values())
    success = (server.get("schedule_completed") is True and client.get("completed") is True
               and not server.get("error") and not client.get("error") and server.get("elapsed", 0) >= DURATION
               and client.get("elapsed", 0) >= DURATION and client.get("alignment_uncertainty_seconds", 100) <= 2
               and server.get("invalid_metadata") == 0 and server.get("source_counts", {}).get("client", 0) > 0
               and server.get("cleanup", {}).get("managed_ok") is True and server["cleanup"].get("temporary_removed") is True
               and coverage and generations == [0, 1, 2, 3] and counts["unexpected_failure"] == 0 and counts["expected_outage"] > 0)
    return {"automated_scope_passed": success, "classifications": counts, "generations": generations,
            "coverage": coverage, "browser_and_trust_cleanup": "Pending external observations"}


def main():
    parser = argparse.ArgumentParser()
    modes = parser.add_subparsers(dest="mode", required=True)
    server = modes.add_parser("server")
    server.add_argument("--server-ip", required=True)
    server.add_argument("--client-ip", required=True)
    server.add_argument("--port", type=int, default=8443)
    server.add_argument("--caddy", type=Path, required=True)
    server.add_argument("--pwsh", type=Path, required=True)
    server.add_argument("--output", type=Path, required=True)
    client = modes.add_parser("client")
    client.add_argument("--manifest", type=Path, required=True)
    client.add_argument("--ca-sha256", required=True)
    client.add_argument("--output", type=Path, required=True)
    summary = modes.add_parser("summarize")
    summary.add_argument("--server-report", type=Path, required=True)
    summary.add_argument("--client-report", type=Path, required=True)
    args = parser.parse_args()
    if args.mode == "server":
        return server_main(args)
    if args.mode == "client":
        return client_main(args)
    result = summarize(json.loads(args.server_report.read_text()), json.loads(args.client_report.read_text()))
    print(json.dumps(result, indent=2))
    return 0 if result["automated_scope_passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
