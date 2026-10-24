import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path
from unittest.mock import patch

import certificates_cli
import launcher_maintenance
from kiosk.launcher.storage import DIRECTORIES, Storage, new_profile, read_profile, save_profile
from werkzeug.security import check_password_hash


class LauncherMaintenanceTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.storage = Storage(Path(self.directory.name) / "installation")
        for name in DIRECTORIES:
            self.storage.directory(name).mkdir(parents=True)
        self.addCleanup(patch.stopall)
        patch("launcher_maintenance.require_administrator").start()
        patch("launcher_maintenance.common_root", return_value=self.storage.root).start()
        patch("kiosk.launcher.installation.service_state", return_value="stopped").start()

    def invoke(self, *arguments):
        with patch("sys.argv", ["KioskMaintenance", *arguments]):
            return launcher_maintenance.main()

    def test_config_restore_requires_matching_identity_and_retains_damage(self):
        profile = new_profile("Previous device")
        save_profile(self.storage, profile)
        save_profile(self.storage, {**profile, "device_name": "Current device"})
        self.storage.profile.write_bytes(b"damaged configuration")
        with self.assertRaises(ValueError):
            self.invoke("restore-config", "--device-id", "different device")
        self.assertEqual(self.storage.profile.read_bytes(), b"damaged configuration")
        self.assertEqual(self.invoke("restore-config", "--device-id", profile["device_id"]), 0)
        self.assertEqual(read_profile(self.storage.profile), profile)
        self.assertEqual(self.storage.profile.with_suffix(".retained.json").read_bytes(), b"damaged configuration")

    def test_credential_commands_target_installed_storage_and_preserve_key(self):
        with patch("sys.stdin.isatty", return_value=True), patch("kiosk.core.credentials.getpass.getpass", side_effect=["initial-installed-password"] * 2):
            self.assertEqual(self.invoke("setup-admin"), 0)
        key = (self.storage.directory("secrets") / "session.key").read_bytes()
        with patch("sys.stdin.isatty", return_value=True), patch("kiosk.core.credentials.getpass.getpass", side_effect=["replacement-installed-password"] * 2):
            self.assertEqual(self.invoke("reset-admin-password"), 0)
        with closing(sqlite3.connect(self.storage.app_config()["DATABASE_PATH"])) as database:
            stored = database.execute("SELECT password_hash FROM users WHERE username='admin'").fetchone()[0]
        self.assertTrue(check_password_hash(stored, "replacement-installed-password"))
        self.assertEqual((self.storage.directory("secrets") / "session.key").read_bytes(), key)
        self.assertFalse((self.storage.directory("data") / "session.key").exists())

    def test_packaged_certificate_wrapper_rejects_source_activation_forms(self):
        for arguments in (["request", "--activate-profile=profile.json"], ["request", "--activate-profile", "profile.json"]):
            with self.subTest(arguments=arguments), patch("sys.argv", ["KioskCertificates", *arguments]), self.assertRaises(ValueError):
                certificates_cli.main()


if __name__ == "__main__":
    unittest.main()
