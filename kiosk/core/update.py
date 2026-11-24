"""Signed offline update package: format, verification and versioning.

A package is a directory containing exactly:

    manifest.json        versioned metadata and payload hashes
    manifest.json.sig    Ed25519 signature over the exact manifest.json bytes
    <installer files>    the Inno Setup installers, one per manifest entry

Verification is fail-closed and happens *before* any installer content is read
or executed: the signature authenticates the publisher, the manifest binds the
payload hashes, and every payload byte is then compared to those hashes. This
module has no Flask/launcher dependency so the server and client builds both
stay lean; it imports only the maintained ``cryptography`` package and stdlib.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import secrets
import shutil
from pathlib import Path

from kiosk.core.update_crypto import public_key_id, verify_signature

SCHEMA_VERSION = 1
MANIFEST_NAME = "manifest.json"
SIGNATURE_NAME = "manifest.json.sig"
MANIFEST_LIMIT = 256 * 1024
SUPPORTED_PRODUCTS = {"kiosk-server", "kiosk-connect"}
PLATFORM = "win-x64"
# Durable-data schema version the update package's application code owns. The
# offline update path performs no schema migration: an update is accepted only
# when its declared schema matches the installed data (or the device has no data
# yet). This rejects unsupported migration paths instead of assuming old binaries
# can always read newer data.
DATA_SCHEMA_VERSION = 1


def new_transaction_id():
    """Short, unpredictable identifier for one update transaction."""
    return secrets.token_hex(8)

_VERSION_PART = re.compile(r"^\d+$")


def parse_version(text):
    """Dotted numeric version; non-numeric trailing segments are ignored for ordering."""
    if not isinstance(text, str) or not text or len(text) > 64:
        raise ValueError("The version is invalid.")
    parts = []
    for part in text.split("."):
        if _VERSION_PART.match(part):
            parts.append(int(part))
        else:
            break
    if not parts:
        raise ValueError("The version has no numeric component.")
    return tuple(parts)


def version_compare(left, right):
    """Return -1, 0 or 1 comparing two version strings."""
    left, right = parse_version(left), parse_version(right)
    for a, b in zip(left, right):
        if a != b:
            return -1 if a < b else 1
    return (len(left) > len(right)) - (len(left) < len(right))


def _duplicate_guard(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("The manifest contains a duplicate field.")
        result[key] = value
    return result


def _safe_name(name):
    if not isinstance(name, str) or not name or len(name) > 255:
        raise ValueError("A manifest path is invalid.")
    path = Path(name)
    if path.is_absolute() or ".." in path.parts or ":" in name or name.startswith(("\\", "/")):
        raise ValueError("A manifest path is invalid.")
    return name


def _file_digest(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def verify_package(directory, public_key_pem, *, product, platform=PLATFORM, current_version=None):
    """Validate a package directory and return its manifest.

    ``product`` and ``platform`` are the expected identity; ``current_version``,
    when given, rejects a same-or-older version (inappropriate downgrade).
    """
    directory = Path(os.path.abspath(directory))
    if not directory.is_dir():
        raise ValueError("The update package directory is unavailable.")
    manifest_path = directory / MANIFEST_NAME
    signature_path = directory / SIGNATURE_NAME
    for path in (manifest_path, signature_path):
        if path.is_symlink() or not path.is_file():
            raise ValueError("The update package is missing its manifest or signature.")
    manifest_bytes = manifest_path.read_bytes()
    if len(manifest_bytes) > MANIFEST_LIMIT:
        raise ValueError("The update manifest is too large.")
    signature = signature_path.read_bytes()
    verify_signature(public_key_pem, manifest_bytes, signature)

    manifest = json.loads(manifest_bytes.decode("utf-8"), object_pairs_hook=_duplicate_guard)
    if not isinstance(manifest, dict) or manifest.get("schema_version") != SCHEMA_VERSION:
        raise ValueError("The update manifest version is unsupported.")
    if manifest.get("product") != product or manifest.get("platform") != platform:
        raise ValueError("The update package is for a different product or platform.")
    if manifest.get("key_id") != public_key_id(public_key_pem):
        raise ValueError("The update package is signed with an untrusted key.")
    version = manifest.get("version")
    parse_version(version)
    if current_version is not None:
        if version_compare(version, current_version) <= 0:
            raise ValueError("The update package is not newer than the installed version.")
        if manifest.get("min_compatible") and version_compare(current_version, manifest["min_compatible"]) < 0:
            raise ValueError("The installed version is too old for this update.")
    if "data_schema" in manifest and (type(manifest["data_schema"]) is not int or manifest["data_schema"] < 1):
        raise ValueError("The update manifest has an invalid data schema.")
    files = manifest.get("files")
    if not isinstance(files, dict) or not files:
        raise ValueError("The update manifest lists no payload.")

    expected = {_safe_name(name): digest for name, digest in files.items()}
    if not all(isinstance(digest, str) and re.fullmatch(r"[0-9a-f]{64}", digest) for digest in expected.values()):
        raise ValueError("The update manifest has an invalid payload hash.")
    actual = {path.relative_to(directory).as_posix() for path in directory.rglob("*")
              if path.is_file() and path.name not in (MANIFEST_NAME, SIGNATURE_NAME)}
    if actual != set(expected):
        raise ValueError("The update package contains unexpected or missing files.")
    for name, digest in expected.items():
        path = directory / name
        if path.is_symlink() or not path.is_file() or _file_digest(path) != digest:
            raise ValueError("A package payload does not match its manifest.")
    return manifest


def verify_snapshot(directory, manifest):
    """Verify a transaction-owned snapshot contains exactly the manifest payload.

    After a package has been verified at its user-supplied path, the installer is
    copied into a protected, transaction-owned snapshot directory; the bytes that
    are actually executed are then re-checked against the manifest here, so a
    concurrent modification of the original path cannot change what runs.
    """
    directory = Path(os.path.abspath(directory))
    if not directory.is_dir():
        raise ValueError("The transaction snapshot is unavailable.")
    files = manifest.get("files")
    if not isinstance(files, dict) or not files:
        raise ValueError("The update manifest lists no payload.")
    expected = {_safe_name(name): digest for name, digest in files.items()}
    actual = {path.relative_to(directory).as_posix() for path in directory.rglob("*")
              if path.is_file()}
    if actual != set(expected):
        raise ValueError("The transaction snapshot contains unexpected or missing files.")
    for name, digest in expected.items():
        path = directory / name
        if path.is_symlink() or not path.is_file() or _file_digest(path) != digest:
            raise ValueError("The transaction snapshot does not match its manifest.")
    return directory


def copy_directory(source, destination, exclude=frozenset()):
    """Copy a directory tree consistently.

    The caller must quiesce writes first (for a database, stop the only writer).
    Reparse points and symlinks are refused; ``exclude`` lists top-level directory
    names that are not part of the durable state (ephemeral logs/temp/status).
    """
    source = Path(os.path.abspath(source))
    destination = Path(os.path.abspath(destination))
    if not source.is_dir():
        raise ValueError("The source directory is unavailable.")
    if destination.exists():
        raise ValueError("The backup destination already exists.")
    if source == destination or destination.is_relative_to(source) or source.is_relative_to(destination):
        raise ValueError("The backup destination must be disjoint from the source.")
    for dirpath, dirnames, filenames in os.walk(source, followlinks=False):
        current = Path(dirpath)
        relative = current.relative_to(source)
        if not relative.parts:
            dirnames[:] = [name for name in dirnames if name not in exclude]
        for name in dirnames:
            path = current / name
            if path.is_symlink() or _is_reparse(path):
                raise ValueError("Reparse paths are not supported in a backup.")
        target = destination / relative
        target.mkdir(parents=True, exist_ok=True)
        for name in filenames:
            path = current / name
            if path.is_symlink() or _is_reparse(path):
                raise ValueError("Reparse paths are not supported in a backup.")
            shutil.copy2(path, target / name)
    return destination


def _is_reparse(path):
    import stat
    return bool(path.exists() and getattr(path.stat(follow_symlinks=False), "st_file_attributes", 0) & stat.FILE_ATTRIBUTE_REPARSE_POINT)


def swap_directories(staging, live, backup):
    """Activate a staged directory tree, retaining the previous one at ``backup``.

    ``staging`` must already contain a complete, verified installation. On success
    ``live`` is the new tree and ``backup`` is the previous one. Directory renames
    are atomic enough that a running process keeps its loaded image while the path
    moves; callers that still run from ``live`` must not need its on-disk path
    again until the swap is complete.
    """
    staging = Path(os.path.abspath(staging))
    live = Path(os.path.abspath(live))
    backup = Path(os.path.abspath(backup))
    if not staging.is_dir():
        raise ValueError("The staged installation is unavailable.")
    if backup.exists():
        raise ValueError("A previous rollback copy already exists; review it first.")
    if live.exists():
        os.replace(live, backup)
    os.replace(staging, live)
    return backup


def rollback_directories(live, backup, discarded):
    """Undo a swap: move ``live`` aside to ``discarded`` and restore ``backup``."""
    live = Path(os.path.abspath(live))
    backup = Path(os.path.abspath(backup))
    discarded = Path(os.path.abspath(discarded))
    if not backup.is_dir():
        raise ValueError("The rollback source is unavailable.")
    if discarded.exists():
        raise ValueError("The discarded path already exists; review it first.")
    if live.exists():
        os.replace(live, discarded)
    os.replace(backup, live)
    return discarded
