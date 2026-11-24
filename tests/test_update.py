"""Signed offline update package: verification, versioning and safe swap."""
import hashlib
import json
import shutil
import tempfile
import unittest
from pathlib import Path

from kiosk.core.update import (
    MANIFEST_NAME,
    SIGNATURE_NAME,
    copy_directory,
    parse_version,
    rollback_directories,
    swap_directories,
    verify_package,
    version_compare,
)
from kiosk.core.update_crypto import generate_key, public_key_id, sign, verify_signature


def _key():
    private, public = generate_key()
    return private, public


def _package(root, product="kiosk-server", version="3.0.0", min_compatible="2.0.0",
              private=None, public=None, payload=b"installer-bytes", extra_files=(),
              manifest_overrides=None):
    private, public = private, public
    if private is None:
        private, public = _key()
    manifest = {
        "schema_version": 1, "product": product, "platform": "win-x64", "version": version,
        "min_compatible": min_compatible, "key_id": public_key_id(public),
        "files": {"installer.exe": hashlib.sha256(payload).hexdigest()},
    }
    if manifest_overrides:
        manifest.update(manifest_overrides)
    (root / "installer.exe").write_bytes(payload)
    for name, content in extra_files:
        (root / name).write_bytes(content)
    manifest_bytes = json.dumps(manifest, indent=2).encode("utf-8")
    (root / MANIFEST_NAME).write_bytes(manifest_bytes)
    (root / SIGNATURE_NAME).write_bytes(sign(private, manifest_bytes))
    return manifest, private, public


class VersionTests(unittest.TestCase):
    def test_ordering(self):
        self.assertEqual(version_compare("3.0.0", "2.0.0"), 1)
        self.assertEqual(version_compare("2.0.0", "2.0.0"), 0)
        self.assertEqual(version_compare("2.0.0", "3.0.0"), -1)
        self.assertEqual(version_compare("3.0.0", "2.0-stage3-dev"), 1)
        self.assertEqual(version_compare("2.1", "2.1.0"), -1)
        self.assertEqual(parse_version("3.0.0"), (3, 0, 0))
        with self.assertRaises(ValueError):
            parse_version("not-a-version")
        with self.assertRaises(ValueError):
            parse_version("")


class UpdateCryptoTests(unittest.TestCase):
    def test_sign_verify_and_tamper(self):
        private, public = _key()
        signature = sign(private, b"manifest")
        verify_signature(public, b"manifest", signature)
        with self.assertRaises(ValueError):
            verify_signature(public, b"manifest-x", signature)
        with self.assertRaises(ValueError):
            verify_signature(public, b"manifest", b"\x00" * 64)
        self.assertEqual(len(signature), 64)
        self.assertEqual(public_key_id(public), public_key_id(public))

    def test_foreign_key_rejected(self):
        _, public = _key()
        other_private, _ = _key()
        signature = sign(other_private, b"manifest")
        with self.assertRaises(ValueError):
            verify_signature(public, b"manifest", signature)


class VerifyPackageTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)

    def dir(self, name="pkg"):
        path = self.root / name
        path.mkdir(exist_ok=False)
        return path

    def test_valid_package(self):
        package = self.dir()
        _, private, public = _package(package)
        result = verify_package(package, public, product="kiosk-server", current_version="2.0.0")
        self.assertEqual(result["version"], "3.0.0")

    def test_tampered_manifest_rejected(self):
        package = self.dir()
        _, private, public = _package(package)
        manifest_path = package / MANIFEST_NAME
        manifest_path.write_bytes(manifest_path.read_bytes().replace(b"3.0.0", b"9.9.9"))
        with self.assertRaises(ValueError):
            verify_package(package, public, product="kiosk-server")

    def test_foreign_signed_manifest_rejected(self):
        package = self.dir()
        _, private, public = _package(package)
        other_private, _ = _key()
        # Re-sign the manifest with a different (untrusted) key.
        manifest_bytes = (package / MANIFEST_NAME).read_bytes()
        (package / SIGNATURE_NAME).write_bytes(sign(other_private, manifest_bytes))
        with self.assertRaises(ValueError):
            verify_package(package, public, product="kiosk-server")

    def test_downgrade_rejected(self):
        package = self.dir()
        _, private, public = _package(package, version="2.0.0")
        with self.assertRaises(ValueError):
            verify_package(package, public, product="kiosk-server", current_version="3.0.0")

    def test_wrong_product_and_platform(self):
        package = self.dir()
        _, private, public = _package(package, product="kiosk-connect")
        with self.assertRaises(ValueError):
            verify_package(package, public, product="kiosk-server")
        package2 = self.dir("pkg2")
        _, _, public2 = _package(package2, product="kiosk-server",
                                 manifest_overrides={"platform": "linux"})
        with self.assertRaises(ValueError):
            verify_package(package2, public2, product="kiosk-server")

    def test_unexpected_file_rejected(self):
        package = self.dir()
        _, private, public = _package(package, extra_files=(("evil.dll", b"x"),))
        with self.assertRaises(ValueError):
            verify_package(package, public, product="kiosk-server")

    def test_payload_hash_mismatch_rejected(self):
        package = self.dir()
        _, private, public = _package(package)
        (package / "installer.exe").write_bytes(b"tampered")
        with self.assertRaises(ValueError):
            verify_package(package, public, product="kiosk-server")

    def test_key_id_rotation_rejected(self):
        package = self.dir()
        _, private, public = _package(package)
        other_private, other_public = _key()
        # Rewrite the manifest claiming the other key, signed by the other key.
        manifest = json.loads((package / MANIFEST_NAME).read_text())
        manifest["key_id"] = public_key_id(other_public)
        manifest_bytes = json.dumps(manifest, indent=2).encode("utf-8")
        (package / MANIFEST_NAME).write_bytes(manifest_bytes)
        (package / SIGNATURE_NAME).write_bytes(sign(other_private, manifest_bytes))
        # Verification against the original trusted key fails (untrusted key id).
        with self.assertRaises(ValueError):
            verify_package(package, public, product="kiosk-server")


class SwapTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)

    def test_copy_and_swap_and_rollback(self):
        source = self.root / "data"
        (source / "config").mkdir(parents=True)
        (source / "data").mkdir()
        (source / "config" / "device.json").write_text('{"k": "v"}')
        (source / "data" / "kiosk.sqlite").write_bytes(b"db")
        (source / "logs").mkdir()
        (source / "logs" / "x.log").write_text("log")
        backup = self.root / "data.backup"
        copy_directory(source, backup, exclude=frozenset(("logs",)))
        self.assertTrue((backup / "config" / "device.json").is_file())
        self.assertTrue((backup / "data" / "kiosk.sqlite").is_file())
        self.assertFalse((backup / "logs").exists())

        live = self.root / "live"
        staging = self.root / "staging"
        old = self.root / "live.old"
        (live / "a").mkdir(parents=True)
        (live / "a" / "v.txt").write_text("old")
        (staging / "b").mkdir(parents=True)
        (staging / "b" / "v.txt").write_text("new")
        swap_directories(staging, live, old)
        self.assertTrue((live / "b" / "v.txt").is_file())
        self.assertTrue((old / "a" / "v.txt").is_file())
        discarded = self.root / "live.bad"
        rollback_directories(live, old, discarded)
        self.assertTrue((live / "a" / "v.txt").is_file())
        self.assertTrue((discarded / "b" / "v.txt").is_file())

    def test_swap_refuses_existing_backup(self):
        live = self.root / "live"
        staging = self.root / "staging"
        old = self.root / "live.old"
        (live / "a").mkdir(parents=True)
        (staging / "b").mkdir(parents=True)
        (old / "x").mkdir(parents=True)
        with self.assertRaises(ValueError):
            swap_directories(staging, live, old)


if __name__ == "__main__":
    unittest.main()
