import http.client
import json
import math
import os
import time
import zipfile
from pathlib import Path
from urllib.parse import urlsplit

from kiosk.launcher.storage import atomic_json, safe_local_path
from kiosk.launcher.errors import StatusAccessDenied
from kiosk.transport.profile import unique_object


STATUS_FIELDS = {"schema_version", "state", "version", "pid", "device_name", "device_id", "mode", "orientation", "origin", "identity", "updated_at", "error"}


def read_status(storage):
    try:
        path = safe_local_path(storage.directory("status") / "runtime.json")
        with path.open("rb") as stream:
            content = stream.read(16385)
    except PermissionError:
        raise StatusAccessDenied("Cannot read the installed service status. Ask an administrator to review installation permissions.") from None
    if len(content) > 16384:
        raise ValueError("Status is too large.")
    data = json.loads(content, object_pairs_hook=unique_object)
    if not isinstance(data, dict) or set(data) != STATUS_FIELDS or type(data["schema_version"]) is not int or data["schema_version"] != 1:
        raise ValueError("Invalid local server status.")
    for name in ("state", "version", "device_name", "device_id", "mode", "orientation", "origin", "identity"):
        if not isinstance(data[name], str) or len(data[name]) > 512 or any(ord(char) < 32 for char in data[name]):
            raise ValueError("Invalid local server status value.")
    if data["error"] is not None and (not isinstance(data["error"], str) or not data["error"].isidentifier() or len(data["error"]) > 100):
        raise ValueError("Invalid local error identifier.")
    if type(data["updated_at"]) not in (float, int) or not math.isfinite(data["updated_at"]) or type(data["pid"]) is not int or data["pid"] <= 0:
        raise ValueError("Invalid local server timestamp or process.")
    if data["state"] not in {"starting", "running", "stopping", "stopped", "recovering", "failed"}:
        raise ValueError("Unknown local server state.")
    return data


def check_ready(storage, status):
    if status["state"] != "running" or time.time() - status["updated_at"] > 10:
        return False
    origin = urlsplit(status["origin"])
    if origin.scheme == "http":
        if origin.hostname != "127.0.0.1" or origin.path or origin.username or origin.password:
            return False
        connection = http.client.HTTPConnection("127.0.0.1", origin.port, timeout=.7)
    elif origin.scheme == "https":
        import ssl

        certificate = storage.directory("status") / "authority.pem"
        connection = http.client.HTTPSConnection(origin.hostname, origin.port, timeout=.7, context=ssl.create_default_context(cafile=str(certificate)))
    else:
        return False
    try:
        connection.request("GET", "/api/version")
        with connection.getresponse() as response:
            data = response.read(16385)
            parsed = json.loads(data) if len(data) <= 16384 else None
            return (response.status == 200 and response.getheader("X-Kiosk-Instance") == status["identity"]
                    and isinstance(parsed, dict) and type(parsed.get("content_version")) is int)
    except (OSError, ValueError, http.client.HTTPException):
        return False
    finally:
        connection.close()


def user_directory():
    value = os.environ.get("LOCALAPPDATA")
    if not value:
        raise RuntimeError("Windows LocalAppData is unavailable.")
    path = safe_local_path(Path(value) / "Kiosk")
    path.mkdir(exist_ok=True)
    return path


def maintenance_enabled():
    return (user_directory() / "maintenance.json").exists()


def set_maintenance(enabled):
    path = user_directory() / "maintenance.json"
    if enabled:
        atomic_json(path, {"maintenance": True})
    else:
        path.unlink(missing_ok=True)


def export_diagnostics(storage, destination):
    destination = safe_local_path(destination)
    if destination.is_relative_to(storage.root):
        raise ValueError("Export diagnostics outside installation storage.")
    status = read_status(storage)
    allowed = {key: status[key] for key in ("schema_version", "state", "version", "mode", "orientation", "updated_at", "error")}
    allowed["free_bytes"] = __import__("shutil").disk_usage(storage.root.anchor).free
    with zipfile.ZipFile(destination, "x", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("status.json", json.dumps(allowed, indent=2))
        archive.writestr("README.txt", "Allowlisted local startup status only. No database, content, host identity, cookies, passwords or private keys.\n")
