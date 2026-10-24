import json
import os
import re
import shutil
import sqlite3
import stat
import tempfile
import time
import uuid
from contextlib import closing
from dataclasses import dataclass
from pathlib import Path

from kiosk.transport.profile import unique_object


DIRECTORIES = ("data", "config", "secrets", "logs", "temp", "updates", "status")


def safe_local_path(path):
    path = Path(os.path.abspath(path))
    if str(path).startswith("\\\\"):
        raise ValueError("Shared storage is not supported.")
    for part in (path, *path.parents):
        if part.is_symlink() or part.exists() and getattr(part.stat(follow_symlinks=False), "st_file_attributes", 0) & stat.FILE_ATTRIBUTE_REPARSE_POINT:
            raise ValueError("Reparse paths are not supported.")
    return path


def common_root():
    value = os.environ.get("PROGRAMDATA")
    if not value:
        raise RuntimeError("Windows ProgramData is unavailable.")
    return safe_local_path(Path(value) / "Kiosk")


@dataclass(frozen=True)
class Storage:
    root: Path

    def __post_init__(self):
        object.__setattr__(self, "root", safe_local_path(self.root))

    def directory(self, name):
        if name not in DIRECTORIES:
            raise ValueError("Unknown storage directory.")
        return safe_local_path(self.root / name)

    @property
    def profile(self):
        return self.directory("config") / "device.json"

    def app_config(self):
        data = self.directory("data")
        return {"BASE_DIR": self.root, "INSTANCE_DIR": data,
                "DATABASE_PATH": data / "kiosk.sqlite", "PRIVATE_UPLOAD_DIR": data / "uploads",
                "PUBLIC_UPLOAD_DIR": data / "public/uploads", "STATIC_DIR": data / "public",
                "SECRETS_DIR": self.directory("secrets")}


def atomic_json(path, data):
    path = safe_local_path(path)
    encoded = json.dumps(data, ensure_ascii=False, indent=2).encode("utf-8")
    descriptor, name = tempfile.mkstemp(prefix=".kiosk-", dir=path.parent)
    temporary = Path(name)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(encoded)
            stream.flush()
            os.fsync(stream.fileno())
        for attempt in range(21):
            try:
                os.replace(temporary, path)
                break
            except PermissionError:
                if attempt == 20:
                    raise
                time.sleep(.05)
    finally:
        temporary.unlink(missing_ok=True)


def validate_profile(data):
    fields = {"schema_version", "device_id", "device_name", "language", "mode", "orientation", "server_autostart", "transport", "port"}
    if not isinstance(data, dict) or set(data) != fields:
        raise ValueError("Unknown or missing device configuration fields.")
    if type(data["schema_version"]) is not int or data["schema_version"] != 1:
        raise ValueError("Unsupported device configuration version.")
    if not isinstance(data["device_id"], str) or str(uuid.UUID(data["device_id"])) != data["device_id"]:
        raise ValueError("Invalid device identity.")
    name = data["device_name"]
    if not isinstance(name, str) or not 1 <= len(name.strip()) <= 100 or any(ord(char) < 32 for char in name):
        raise ValueError("Device name must contain 1 to 100 printable characters.")
    for field, allowed in (("language", {"ru", "en", "de"}), ("mode", {"kiosk", "tv"}),
                           ("orientation", {"landscape", "portrait"}), ("transport", {"loopback", "https"})):
        if not isinstance(data[field], str) or data[field] not in allowed:
            raise ValueError("Invalid device configuration selection.")
    if type(data["server_autostart"]) is not bool or type(data["port"]) is not int or not 1024 <= data["port"] <= 65535:
        raise ValueError("Invalid startup configuration.")
    return data


def read_profile(path):
    path = safe_local_path(path)
    if path.stat().st_size > 16384:
        raise ValueError("Device configuration is too large.")
    return validate_profile(json.loads(path.read_bytes(), object_pairs_hook=unique_object))


def save_profile(storage, data):
    validate_profile(data)
    if storage.profile.exists():
        previous = read_profile(storage.profile)
        if previous["device_id"] != data["device_id"]:
            raise ValueError("Device identity cannot be replaced.")
        atomic_json(storage.profile.with_suffix(".previous.json"), previous)
    atomic_json(storage.profile, data)


def new_profile(name, language="ru", mode="kiosk", orientation="landscape", server_autostart=True, port=5000):
    return validate_profile({"schema_version": 1, "device_id": str(uuid.uuid4()), "device_name": name,
                             "language": language, "mode": mode, "orientation": orientation,
                             "server_autostart": server_autostart, "transport": "loopback", "port": port})


def needs_administrator(storage):
    path = storage.app_config()["DATABASE_PATH"]
    if not path.exists():
        return True
    with closing(sqlite3.connect(path.as_uri() + "?mode=ro", uri=True)) as database:
        return database.execute("SELECT 1 FROM users LIMIT 1").fetchone() is None


def verify_database(path, public_uploads, originals):
    uri = path.as_uri() + "?mode=ro"
    with closing(sqlite3.connect(uri, uri=True)) as database:
        if database.execute("PRAGMA integrity_check").fetchall() != [("ok",)] or database.execute("PRAGMA foreign_key_check").fetchall():
            raise ValueError("Database integrity verification failed.")
        for row in database.execute("SELECT image_original, image_kiosk, image_tv, image_thumb FROM events"):
            for index, value in enumerate(row):
                if not value:
                    continue
                base = originals if index == 0 else public_uploads
                prefix = "data/uploads/" if index == 0 else "/static/uploads/"
                if not isinstance(value, str) or not value.startswith(prefix):
                    raise ValueError("An image reference uses an unsupported format.")
                relative = Path(value.removeprefix(prefix))
                candidate = safe_local_path(base / relative)
                if not candidate.is_relative_to(base) or not candidate.is_file():
                    raise ValueError("A referenced image is unavailable or outside storage.")
        row = database.execute("SELECT value FROM settings WHERE key = 'site_icon'").fetchone()
        if row and row[0]:
            if not row[0].startswith("/static/uploads/"):
                raise ValueError("The site icon uses an unsupported format.")
            relative = Path(row[0].removeprefix("/static/uploads/"))
            candidate = safe_local_path(public_uploads / relative)
            if not candidate.is_relative_to(public_uploads) or not candidate.is_file():
                raise ValueError("The referenced site icon is unavailable.")


def copy_tree(source, destination):
    source = safe_local_path(source)
    if not source.exists():
        return
    for directory, children, files in os.walk(source, followlinks=False):
        for child in (*children, *files):
            safe_local_path(Path(directory) / child)
    shutil.copytree(source, destination, dirs_exist_ok=True)


def import_mvp(source, storage, source_stopped=False):
    if source_stopped is not True:
        raise ValueError("Stop the source server and explicitly confirm it before importing.")
    source = safe_local_path(source)
    if storage.root.exists():
        raise ValueError("Import requires a new, empty installation path.")
    if source.is_relative_to(storage.root) or storage.root.is_relative_to(source):
        raise ValueError("Source and destination must be disjoint.")
    database_path = source / "instance/kiosk.sqlite"
    key = (source / "instance/session.key").read_bytes()
    if re.fullmatch(rb"[0-9a-f]{64}", key) is None:
        raise ValueError("The original session key is invalid.")
    storage.root.parent.mkdir(parents=True, exist_ok=True)
    pending = Path(tempfile.mkdtemp(prefix=".kiosk-import-", dir=storage.root.parent))
    try:
        staged = Storage(pending)
        for name in DIRECTORIES:
            staged.directory(name).mkdir()
        from kiosk.launcher.windows import protect_storage

        protect_storage(staged)
        with closing(sqlite3.connect(database_path.as_uri() + "?mode=rw", uri=True, timeout=1)) as guard:
            guard.execute("BEGIN IMMEDIATE")
            with closing(sqlite3.connect(database_path.as_uri() + "?mode=ro", uri=True)) as original:
                with closing(sqlite3.connect(staged.directory("data") / "kiosk.sqlite")) as target:
                    original.backup(target)
                    values = target.execute("SELECT id, image_original FROM events WHERE image_original IS NOT NULL AND image_original != ''").fetchall()
                    for event_id, value in values:
                        if not value.startswith("instance/uploads/"):
                            raise ValueError("An original image uses an unsupported format.")
                        target.execute("UPDATE events SET image_original = ? WHERE id = ?", ("data/uploads/" + value.removeprefix("instance/uploads/"), event_id))
                    target.commit()
            copy_tree(source / "instance/uploads", staged.directory("data") / "uploads")
            copy_tree(source / "kiosk/static/uploads", staged.directory("data") / "public/uploads")
            guard.rollback()
        (staged.directory("secrets") / "session.key").write_bytes(key)
        config = staged.app_config()
        verify_database(config["DATABASE_PATH"], config["PUBLIC_UPLOAD_DIR"], config["PRIVATE_UPLOAD_DIR"])
        pending.rename(storage.root)
    finally:
        if pending.exists():
            shutil.rmtree(pending)
