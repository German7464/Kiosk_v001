import io
import argparse
import json
import logging
import multiprocessing
import random
import re
import secrets
import sqlite3
import tempfile
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from datetime import datetime, timezone
from http.cookiejar import CookieJar
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import HTTPRedirectHandler, HTTPCookieProcessor, ProxyHandler, Request, build_opener

from PIL import Image
from waitress import create_server
from werkzeug.test import EnvironBuilder

from kiosk.app import create_app
from kiosk.core.credentials import save_admin_password
from tools.baseline_metrics import environment_details, summarize, working_memory


ROUTES = ("/kiosk", "/kiosk/events", "/tv", "/preview", "/api/version", "/api/events", "/api/tags")
PROFILE = {
    "events": 100, "active_events": 80, "tags": 20, "tags_per_event": 3,
    "images": 10, "landscape": [1920, 1080], "portrait": [1080, 1920],
    "warmups_per_route": 3, "sequential_per_route": 50, "concurrent_requests": 1000,
    "clients": 10, "waitress_threads": 4, "request_timeout_seconds": 10,
    "scenario_timeout_seconds": 180, "memory_sample_seconds": 0.1,
    "image_generator": "seeded grayscale random bytes converted to RGB; seed = image index",
}


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, request, response, code, message, headers, new_url):
        return None


class QueueDiagnostics(logging.Handler):
    def __init__(self):
        super().__init__()
        self.notifications = 0
        self.maximum_depth = 0
        self.errors = 0

    def emit(self, record):
        if record.levelno >= logging.ERROR:
            self.errors += 1
        if record.msg == "Task queue depth is %d" and record.args:
            self.notifications += 1
            self.maximum_depth = max(self.maximum_depth, record.args[0])


def serve_temporary(root, password, connection, stopped):
    server = None
    diagnostics = QueueDiagnostics()
    logger = logging.getLogger("waitress.queue")
    logger.addHandler(diagnostics)
    logger.propagate = False
    try:
        root = Path(root)
        app = create_app({
            "BASE_DIR": root, "INSTANCE_DIR": root / "instance",
            "DATABASE_PATH": root / "instance/kiosk.sqlite",
            "PRIVATE_UPLOAD_DIR": root / "instance/uploads",
            "PUBLIC_UPLOAD_DIR": root / "static/uploads", "STATIC_FOLDER": root / "static",
        })
        save_admin_password(app, password, setup=True)
        server = create_server(app, host="127.0.0.1", port=0, threads=4, map={},
                               max_request_body_size=app.config["MAX_CONTENT_LENGTH"])
        connection.send({"port": server.effective_port})
        while not stopped.is_set():
            server.asyncore.loop(timeout=0.05, count=1, map=server._map)
    except Exception as error:
        connection.send({"error": type(error).__name__})
    finally:
        if server is not None:
            server.task_dispatcher.shutdown()
            server.close()
            server.asyncore.close_all(map=server._map)
        connection.send({"queue_notifications": diagnostics.notifications,
                         "observed_max_queue_depth": diagnostics.maximum_depth,
                         "queue_errors": diagnostics.errors})
        connection.close()


def stop_server(process, stopped):
    stopped.set()
    process.join(5)
    forced = process.is_alive()
    if forced:
        process.terminate()
        process.join(5)
    if process.is_alive():
        raise RuntimeError("Temporary server could not be stopped.")
    return {"stopped": True, "forced": forced, "exit_code": process.exitcode}


def sample_memory(pid, stopped, values, errors):
    while not stopped.is_set():
        try:
            values.append(working_memory(pid))
        except OSError as error:
            errors.append(type(error).__name__)
            return
        stopped.wait(0.1)


def new_client():
    return build_opener(ProxyHandler({}), HTTPCookieProcessor(CookieJar()))


def exchange(client, base, path, deadline, data=None, headers=None):
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        return {"path": path, "status": 0, "bytes": 0, "milliseconds": 0, "error": "ScenarioTimeout"}, b""
    start = time.perf_counter()
    body = b""
    status = 0
    failure = None
    request = Request(base + path, data=data, headers=headers or {})
    try:
        try:
            response = client.open(request, timeout=min(10, remaining))
        except HTTPError as error:
            response = error
        with response:
            status = response.status
            body = response.read()
        if status != 200:
            failure = "UnexpectedHTTPStatus"
    except Exception as error:
        failure = type(error).__name__
    return {
        "path": path, "status": status, "bytes": len(body),
        "milliseconds": (time.perf_counter() - start) * 1000, "error": failure,
    }, body


def checked(client, base, path, deadline, report, data=None, headers=None):
    sample, body = exchange(client, base, path, deadline, data, headers)
    if sample["error"]:
        report["errors"].append(sample)
        raise RuntimeError("HTTP verification failed.")
    return body, sample


def post_form(client, base, path, deadline, report, data):
    page, unused = checked(client, base, "/kiosk", deadline, report)
    token = re.search(rb'name="csrf-token" content="([^"]+)"', page).group(1).decode("ascii")
    with closing(EnvironBuilder(method="POST", data=data)) as builder:
        environment = builder.get_environ()
        return checked(client, base, path, deadline, report, environment["wsgi.input"].read(),
                       {"Content-Type": environment["CONTENT_TYPE"], "X-CSRF-Token": token})


def prepare_dataset(client, base, root, password, deadline, report):
    unauthenticated = build_opener(ProxyHandler({}), NoRedirect())
    try:
        with unauthenticated.open(base + "/admin", timeout=10):
            raise RuntimeError("Unauthenticated administration accepted.")
    except HTTPError as error:
        with error:
            if error.code != 302 or not error.headers.get("Location", "").endswith("/admin/login"):
                raise RuntimeError("Unexpected unauthenticated administration response.")
    report["admin_before_login_status"] = 302
    post_form(client, base, "/admin/login", deadline, report, {"username": "admin", "password": password})
    checked(client, base, "/admin", deadline, report)
    report["admin_after_login_status"] = 200
    before = json.loads(checked(client, base, "/api/version", deadline, report)[0])["content_version"]
    for index in range(20):
        post_form(client, base, "/admin/tags/create", deadline, report, {"name": f"Baseline tag {index + 1:02d}"})
    report["uploads"] = []
    for index in range(100):
        data = {
            "title": f"{index + 1:03d} - " + "Exhibition / Ausstellung / \u0412\u044b\u0441\u0442\u0430\u0432\u043a\u0430 " * 4,
            "short_description": "Local event description. " * 8,
            "full_description": "Detailed multilingual content: caf\u00e9, \u043c\u0443\u0437\u0435\u0439, Ausstellung. " * 20,
            "place": "Main exhibition hall", "event_date": "2026-11-01",
            "status": "active" if index < 80 else "hidden", "sort_order": str(index),
        }
        source_bytes = None
        if index < 10:
            size = (1920, 1080) if index < 5 else (1080, 1920)
            image = Image.frombytes("L", size, random.Random(index).randbytes(size[0] * size[1])).convert("RGB")
            stream = io.BytesIO()
            image.save(stream, "PNG")
            source_bytes = stream.tell()
            stream.seek(0)
            data["event_image"] = (stream, "baseline.png")
        unused, sample = post_form(client, base, "/admin/events/create", deadline, report, data)
        if source_bytes is not None:
            report["uploads"].append({**sample, "dimensions": list(size), "source_bytes": source_bytes})
        post_form(client, base, f"/admin/events/{index + 1}/tags", deadline, report,
                  {"tag_ids": [str((index + offset) % 20 + 1) for offset in range(3)]})
    events = json.loads(checked(client, base, "/api/events", deadline, report)[0])["events"]
    tags = json.loads(checked(client, base, "/api/tags", deadline, report)[0])["tags"]
    if len(events) != 80 or len(tags) != 20 or any(len(event["tags"]) != 3 for event in events):
        raise RuntimeError("Public dataset verification failed.")
    if any(event["status"] != "active" or not event["title"] or not event["full_description"] for event in events):
        raise RuntimeError("Public event fields are invalid.")
    for event in events[:10]:
        for key in ("image_kiosk", "image_tv", "image_thumb"):
            body, unused = checked(client, base, event[key], deadline, report)
            with Image.open(io.BytesIO(body)) as image:
                image.load()
    after = json.loads(checked(client, base, "/api/version", deadline, report)[0])["content_version"]
    with closing(sqlite3.connect(root / "instance/kiosk.sqlite")) as database:
        counts = [database.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] for table in ("events", "tags", "event_tags")]
    if counts != [100, 20, 300] or after <= before:
        raise RuntimeError("Stored dataset or content version verification failed.")
    report["dataset_verified"] = {"events": 100, "active": 80, "hidden": 20, "tags": 20,
                                  "assignments": 300, "decoded_derivatives": 30, "version_before": before, "version_after": after}


def measure(client, base, deadline, report):
    report["phase"] = "sequential"
    report["sequential"] = {}
    for path in ROUTES:
        for unused in range(3):
            checked(client, base, path, deadline, report)
        start = time.perf_counter()
        samples = [exchange(client, base, path, deadline)[0] for unused in range(50)]
        report["sequential"][path] = summarize(samples, time.perf_counter() - start)
        report["errors"].extend(sample for sample in samples if sample["error"])
    local = threading.local()
    def request_one(index):
        if not hasattr(local, "client"):
            local.client = new_client()
        return exchange(local.client, base, ROUTES[index % len(ROUTES)], deadline)[0]
    report["phase"] = "concurrent"
    start = time.perf_counter()
    with ThreadPoolExecutor(max_workers=10) as pool:
        samples = list(pool.map(request_one, range(1000)))
    elapsed = time.perf_counter() - start
    report["concurrent"] = summarize(samples, elapsed)
    report["concurrent"]["routes"] = {
        path: summarize([sample for sample in samples if sample["path"] == path], elapsed) for path in ROUTES
    }
    report["errors"].extend(sample for sample in samples if sample["error"])
    if report["errors"]:
        raise RuntimeError("Measured requests contained errors.")


def run_scenario(root, report):
    context = multiprocessing.get_context("spawn")
    receiver, sender = context.Pipe(duplex=False)
    stopped = context.Event()
    memory_stopped = threading.Event()
    memory_values = []
    memory_errors = []
    password = secrets.token_urlsafe(32)
    process = context.Process(target=serve_temporary, args=(str(root), password, sender, stopped))
    sampler = None
    start = time.monotonic()
    deadline = start + 180
    process.start()
    watchdog = threading.Timer(180, process.terminate)
    watchdog.daemon = True
    watchdog.start()
    sender.close()
    try:
        report["phase"] = "server_startup"
        if not receiver.poll(30):
            raise RuntimeError("Temporary server startup timed out.")
        ready = receiver.recv()
        if "port" not in ready:
            raise RuntimeError("Temporary server startup failed.")
        memory_values.append(working_memory(process.pid))
        sampler = threading.Thread(target=sample_memory, args=(process.pid, memory_stopped, memory_values, memory_errors))
        sampler.start()
        base = f"http://127.0.0.1:{ready['port']}"
        client = new_client()
        report["phase"] = "dataset"
        prepare_dataset(client, base, root, password, deadline, report)
        measure(client, base, deadline, report)
        if memory_errors:
            raise RuntimeError("Server memory sampling failed.")
    finally:
        watchdog.cancel()
        watchdog.join()
        memory_stopped.set()
        if sampler is not None:
            sampler.join(2)
        report["memory"] = {
            "initial_working_bytes": memory_values[0] if memory_values else None,
            "observed_max_working_bytes": max(memory_values) if memory_values else None,
            "samples": len(memory_values), "sampling_errors": memory_errors,
        }
        report["server_shutdown"] = stop_server(process, stopped)
        report["scenario_elapsed_seconds"] = time.monotonic() - start
        if receiver.poll():
            try:
                report["server_diagnostics"] = receiver.recv()
            except EOFError:
                report["server_diagnostics"] = {"unavailable": True}
        receiver.close()
        if report["server_shutdown"]["forced"] or process.exitcode != 0:
            raise RuntimeError("Temporary server did not stop cleanly.")
        if report.get("server_diagnostics", {}).get("queue_errors"):
            raise RuntimeError("Waitress reported queue errors.")


def write_report(path, report):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def main():
    stamp = datetime.now(timezone.utc)
    report = {"timestamp_utc": stamp.isoformat(), "profile": PROFILE, "status": "failed", "errors": []}
    path = Path(__file__).resolve().parents[1] / "logs/measurements" / f"mvp-{stamp.strftime('%Y%m%dT%H%M%S%fZ')}.json"
    try:
        report["environment"] = environment_details()
        with tempfile.TemporaryDirectory(prefix="kiosk-baseline-") as directory:
            run_scenario(Path(directory), report)
        report["temporary_data_removed"] = True
        report["status"] = "passed"
        report["phase"] = "completed"
    except Exception as error:
        report["errors"].append({"type": type(error).__name__, "stage": report.get("phase", "scenario")})
    finally:
        write_report(path, report)
    print(f"MVP baseline {report['status']}. Report: {path}")
    return 0 if report["status"] == "passed" else 1


if __name__ == "__main__":
    argparse.ArgumentParser(description="Measure the fixed isolated Windows MVP profile; no external server or database is accepted.").parse_args()
    raise SystemExit(main())
