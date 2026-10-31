"""Versioned display-package validation; hashes do not establish authenticity."""
import hashlib
from pathlib import PurePosixPath


def validate_manifest(manifest):
    if not isinstance(manifest, dict) or manifest.get("schema_version") != 1 or type(manifest.get("schema_version")) is not int:
        raise ValueError("Unsupported package schema")
    if not isinstance(manifest.get("revision"), str) or not manifest["revision"] or len(manifest["revision"]) > 128:
        raise ValueError("Invalid revision")
    if manifest.get("renderer") != "events-v1":
        raise ValueError("Unsupported renderer")
    files = manifest.get("files")
    if not isinstance(files, list) or not files or len(files) > 10000:
        raise ValueError("Invalid file inventory")
    seen = set()
    for entry in files:
        if not isinstance(entry, dict):
            raise ValueError("Invalid file entry")
        name = entry.get("path")
        if not isinstance(name, str) or not name or len(name) > 240 or any(c in name for c in '\\:<>"|?*%#'):
            raise ValueError("Invalid package path")
        parts = name.split("/")
        if any(part in ("", ".", "..") or part.endswith((".", " ")) for part in parts) or PurePosixPath(name).is_absolute():
            raise ValueError("Unsafe package path")
        if any(any(ord(char) < 32 for char in part) or part.split(".")[0].upper() in {"CON", "PRN", "AUX", "NUL", *(f"COM{i}" for i in range(1, 10)), *(f"LPT{i}" for i in range(1, 10))} for part in parts):
            raise ValueError("Nonportable package path")
        if name.casefold() in seen:
            raise ValueError("Duplicate package path")
        seen.add(name.casefold())
        if type(entry.get("size")) is not int or not 0 <= entry["size"] <= 256 * 1024 * 1024:
            raise ValueError("Invalid file size")
        digest = entry.get("sha256")
        if not isinstance(digest, str) or len(digest) != 64 or any(c not in "0123456789abcdef" for c in digest):
            raise ValueError("Invalid file digest")
    return manifest


def verify_payload(entry, payload):
    if len(payload) != entry["size"] or hashlib.sha256(payload).hexdigest() != entry["sha256"]:
        raise ValueError("Package file integrity failure")
