import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from kiosk.launcher.installation import install, uninstall, verify_package
from kiosk.launcher.storage import DIRECTORIES, Storage, new_profile, save_profile


class LauncherInstallationTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.package = self.root / "package"
        self.package.mkdir()
        for name in ("KioskLauncher.exe", "KioskService.exe", "KioskCertificates.exe", "KioskMaintenance.exe", "_internal/runtime.dll"):
            path = self.package / name
            path.parent.mkdir(exist_ok=True)
            path.write_bytes(b"isolated-package-fixture")
        files = {path.relative_to(self.package).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest() for path in self.package.rglob("*") if path.is_file()}
        (self.package / "package.json").write_text(json.dumps({"schema_version": 1, "files": files}), encoding="utf-8")
        self.installed = self.root / "binaries"
        self.storage = Storage(self.root / "data")
        for name in DIRECTORIES:
            self.storage.directory(name).mkdir(parents=True)
        self.profile = new_profile("Preserved device")
        save_profile(self.storage, self.profile)
        self.addCleanup(patch.stopall)
        patch("kiosk.launcher.installation.require_administrator").start()
        patch("kiosk.launcher.installation.binary_directory", return_value=self.installed).start()
        patch("kiosk.launcher.installation.common_root", return_value=self.storage.root).start()
        patch("kiosk.launcher.installation.service_state", return_value="absent").start()
        patch("kiosk.launcher.installation.hidden_run").start()
        patch("kiosk.launcher.installation.sys.frozen", True, create=True).start()
        patch("kiosk.launcher.installation.sys.executable", str(self.package / "KioskLauncher.exe")).start()

    def test_install_identical_reinstall_and_uninstall_preserve_data(self):
        original = self.storage.profile.read_bytes()
        install()
        self.assertTrue((self.installed / "KioskLauncher.exe").is_file())
        self.assertEqual(verify_package(self.installed), verify_package(self.package))
        install()
        self.assertEqual(self.storage.profile.read_bytes(), original)
        uninstall()
        self.assertFalse(self.installed.exists())
        self.assertEqual(self.storage.profile.read_bytes(), original)

    def test_explicit_data_deletion_requires_matching_identity(self):
        install()
        with self.assertRaises(ValueError):
            uninstall(delete_data=True, device_id="another installation")
        self.assertTrue(self.installed.exists())
        self.assertTrue(self.storage.root.exists())
        uninstall(delete_data=True, device_id=self.profile["device_id"])
        self.assertFalse(self.installed.exists())
        self.assertFalse(self.storage.root.exists())

    def test_tampering_extra_files_and_traversal_are_rejected(self):
        manifest = self.package / "package.json"
        original = manifest.read_bytes()
        (self.package / "extra.txt").write_text("unexpected")
        with self.assertRaises(ValueError):
            install()
        (self.package / "extra.txt").unlink()
        (self.package / "KioskService.exe").write_bytes(b"modified")
        with self.assertRaises(ValueError):
            install()
        manifest.write_text(json.dumps({"schema_version": 1, "files": {"../outside.exe": "a" * 64}}))
        with self.assertRaises(ValueError):
            install()
        self.assertFalse(self.installed.exists())

    def test_other_installed_version_is_preserved(self):
        install()
        (self.installed / "unknown.txt").write_text("preserve")
        with self.assertRaises(ValueError):
            install()
        self.assertEqual((self.installed / "unknown.txt").read_text(), "preserve")


if __name__ == "__main__":
    unittest.main()
