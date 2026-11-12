"""Bounded migration of a stopped legacy runtime tree into installed storage.

The demonstrated two-VM runtime kept its files in one task root:

    <source>/instance/kiosk.sqlite, instance/session.key, instance/uploads/
    <source>/public/uploads/                     public event images
    <source>/delivery/{public.json,delivery.sqlite,publications/}
    <source>/tls/tls-cert.pem, tls-key.pem       server chain + key

The supported installed layout is different (`data/`, `data/public/`,
`data/delivery/`, `secrets/`). This module copies that exact shape with the same
reservation/verification rules as the existing MVP import: the source is
retained, the destination must be new, and the imported bytes are verified before
the destination becomes active. Nothing is renamed, reissued or reenrolled.
"""
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import sqlite3
import ssl
import tempfile
from contextlib import closing

from kiosk.launcher.storage import (
    DIRECTORIES,
    Storage,
    atomic_json,
    copy_tree,
    safe_local_path,
    verify_database,
)
from kiosk.launcher.windows import protect_storage

REQUIRED_FILES = ("instance/kiosk.sqlite", "instance/session.key",
                  "delivery/public.json", "delivery/delivery.sqlite",
                  "tls/tls-cert.pem", "tls/tls-key.pem")


def digest(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def pem_der_sha256(path):
    text = Path(path).read_text(encoding="ascii")
    if len(text) > 65536:
        raise ValueError("A PEM certificate is required.")
    match = re.search(r"-----BEGIN CERTIFICATE-----.*?-----END CERTIFICATE-----", text, re.S)
    if match is None:
        raise ValueError("A PEM certificate is required.")
    return hashlib.sha256(ssl.PEM_cert_to_DER_cert(match[0])).hexdigest()


def checked_source(source):
    source = safe_local_path(source)
    if not source.is_dir():
        raise ValueError("The migration source directory is unavailable.")
    for name in REQUIRED_FILES:
        path = safe_local_path(source / name)
        if not path.is_file() or not path.is_relative_to(source):
            raise ValueError("The migration source is incomplete: " + name)
    for directory, children, files in os.walk(source, followlinks=False):
        for child in (*children, *files):
            safe_local_path(Path(directory) / child)
    return source


def empty_destination(storage):
    root = storage.root
    if not root.exists():
        return
    for path in root.rglob("*"):
        if path.is_file() or path.is_symlink():
            raise ValueError("Import requires an empty installation data root.")


def copied_database(source, destination):
    """Copy one consistent snapshot and only rewrite legacy original-image prefixes."""
    with closing(sqlite3.connect((source).as_uri() + "?mode=ro", uri=True)) as original:
        with closing(sqlite3.connect(destination)) as target:
            original.backup(target)
            values = target.execute(
                "SELECT id, image_original FROM events WHERE image_original IS NOT NULL AND image_original != ''"
            ).fetchall()
            for event_id, value in values:
                if not value.startswith("instance/uploads/"):
                    raise ValueError("An original image uses an unsupported format.")
                target.execute(
                    "UPDATE events SET image_original = ? WHERE id = ?",
                    ("data/uploads/" + value.removeprefix("instance/uploads/"), event_id),
                )
            target.commit()


def verify_delivery(root, expected_origin=None):
    with closing(sqlite3.connect((root / "delivery.sqlite").as_uri() + "?mode=ro", uri=True)) as database:
        if database.execute("PRAGMA integrity_check").fetchall() != [("ok",)]:
            raise ValueError("The delivery database integrity check failed.")
    public = json.loads((root / "public.json").read_text(encoding="utf-8"))
    if not isinstance(public, dict) or not all(isinstance(public.get(name), str) and public[name]
                                               for name in ("group_id", "server_id", "origin")):
        raise ValueError("The delivery configuration is invalid.")
    if expected_origin is not None and public["origin"] != expected_origin:
        raise ValueError("The delivery configuration belongs to another origin.")
    return public


def import_runtime(storage, source, ca_file, ca_sha256, *, source_stopped=False):
    if source_stopped is not True:
        raise ValueError("Stop the source runtime and explicitly confirm it before importing.")
    source = checked_source(source)
    ca_file = safe_local_path(ca_file)
    if not ca_file.is_file() or not re.fullmatch(r"[0-9a-f]{64}", ca_sha256 or ""):
        raise ValueError("Supply the public CA file and its lowercase SHA-256 fingerprint.")
    if pem_der_sha256(ca_file) != ca_sha256:
        raise ValueError("The supplied CA fingerprint does not match the file.")
    empty_destination(storage)

    key = (source / "instance/session.key").read_bytes()
    if re.fullmatch(rb"[0-9a-f]{64}", key) is None:
        raise ValueError("The source session key is invalid.")

    storage.root.parent.mkdir(parents=True, exist_ok=True)
    pending = Path(tempfile.mkdtemp(prefix=".kiosk-import-", dir=storage.root.parent))
    try:
        staged = Storage(pending)
        for name in DIRECTORIES:
            staged.directory(name).mkdir()
        protect_storage(staged)
        copied_database(safe_local_path(source / "instance/kiosk.sqlite"), staged.directory("data") / "kiosk.sqlite")
        copy_tree(source / "instance/uploads", staged.directory("data") / "uploads")
        copy_tree(source / "public/uploads", staged.directory("data") / "public/uploads")
        copy_tree(source / "delivery", staged.directory("data") / "delivery")
        (staged.directory("secrets") / "session.key").write_bytes(key)

        certificate = safe_local_path(source / "tls/tls-cert.pem")
        private_key = safe_local_path(source / "tls/tls-key.pem")
        certificate_sha256 = pem_der_sha256(certificate)
        generation = staged.directory("secrets") / ("https-" + certificate_sha256[:16])
        generation.mkdir()
        for name, item in (("server.pem", certificate), ("server.key", private_key), ("authority.pem", ca_file)):
            payload = item.read_bytes()
            if len(payload) > 65536:
                raise ValueError("A TLS input file is too large.")
            (generation / name).write_bytes(payload)
        # Real key/certificate binding check; chain, name and validity are verified
        # again by the product HTTPS probe when the profile is activated.
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        context.load_cert_chain(str(generation / "server.pem"), str(generation / "server.key"),
                                password=lambda: b"")

        config = staged.app_config()
        verify_database(config["DATABASE_PATH"], config["PUBLIC_UPLOAD_DIR"], config["PRIVATE_UPLOAD_DIR"])
        delivery = verify_delivery(staged.directory("data") / "delivery")
        staged.enable_delivery()
        record = {
            "schema_version": 1,
            "result": "imported",
            "source": str(source),
            "database_sha256": digest(config["DATABASE_PATH"]),
            "public_json_sha256": digest(staged.directory("data") / "delivery/public.json"),
            "certificate_sha256": certificate_sha256,
            "ca_sha256": ca_sha256,
            "generation": generation.name,
            "group_id": delivery["group_id"],
            "server_id": delivery["server_id"],
            "origin": delivery["origin"],
            "session_key_sha256": hashlib.sha256(key).hexdigest(),
            "source_retained": True,
        }
        atomic_json(staged.directory("status") / "migration.json", record)
        pending.rename(storage.root)
        return record
    finally:
        if pending.exists():
            shutil.rmtree(pending, ignore_errors=True)
