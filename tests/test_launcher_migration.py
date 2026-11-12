"""Focused checks for the bounded runtime import and opt-in delivery marker."""
import hashlib
import io
import json
import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path
from unittest.mock import patch

from PIL import Image

from kiosk.app import create_app
from kiosk.core.credentials import save_admin_password
from kiosk.delivery.state import DeliveryState
from kiosk.launcher.migration import import_runtime
from kiosk.launcher.storage import Storage
from tests.browser_client import browser_client
from tools.certificates import crypto, pem_bytes


class LauncherMigrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.installation = "0f6f0d3c-6f6f-4a63-9d3a-2d3d1f4d0001"
        password = "temporary-migration-authority-password"
        authority = crypto("initialize", installation=cls.installation, password=password)
        cls.fingerprint = hashlib.sha256(pem_bytes(authority["authority"])).hexdigest()
        request = crypto("request", installation=cls.installation, names=["127.0.0.1"])
        signed = crypto("sign", installation=cls.installation, csr=request["csr"], password=password, **authority)
        cls.key, cls.certificate, cls.authority = request["key"], signed["certificate"], signed["authority"]

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        source = self.root / "lab"
        (source / "instance/uploads").mkdir(parents=True)
        (source / "public/uploads").mkdir(parents=True)
        (source / "delivery/publications").mkdir(parents=True)
        (source / "tls").mkdir()
        config = {"BASE_DIR": source, "INSTANCE_DIR": source / "instance",
                  "DATABASE_PATH": source / "instance/kiosk.sqlite",
                  "PRIVATE_UPLOAD_DIR": source / "instance/uploads",
                  "PUBLIC_UPLOAD_DIR": source / "public/uploads",
                  "STATIC_DIR": source / "public", "DEVICE_DELIVERY_ROOT": source / "delivery"}
        app = create_app(config)
        save_admin_password(app, "migration-test-password", setup=True)
        client = browser_client(app)
        self.assertEqual(client.post("/admin/login", data={"username": "admin", "password": "migration-test-password"}).status_code, 302)
        image = io.BytesIO()
        Image.new("RGB", (64, 48), "blue").save(image, format="PNG")
        image.seek(0)
        self.assertEqual(client.post("/admin/events/create", data={"title": "Migrated", "status": "active",
                                                                   "event_image": (image, "event.png")}).status_code, 302)
        (source / "delivery/public.json").write_text(json.dumps({
            "version": 1, "group_id": "group-1", "server_id": "server-1",
            "origin": "https://127.0.0.1:18443", "bootstrap": {}, "trust": {}}), encoding="utf-8")
        DeliveryState(source / "delivery")
        (source / "tls/tls-cert.pem").write_text(self.certificate, encoding="utf-8")
        (source / "tls/tls-key.pem").write_text(self.key, encoding="utf-8")
        self.ca_file = self.root / "ca.pem"
        self.ca_file.write_text(self.authority, encoding="utf-8")
        self.source = source
        self.storage = Storage(self.root / "installed")
        self.cookie = client.get_cookie("session").value

    def test_import_preserves_events_identity_session_and_tls(self):
        with patch("kiosk.launcher.windows.protect_storage"):
            record = import_runtime(self.storage, self.source, self.ca_file, self.fingerprint, source_stopped=True)
        self.assertEqual((record["group_id"], record["server_id"], record["origin"]),
                         ("group-1", "server-1", "https://127.0.0.1:18443"))
        self.assertTrue((self.storage.directory("config") / "delivery-enabled.json").is_file())
        self.assertEqual((self.storage.directory("status") / "migration.json").is_file(), True)
        app_config = self.storage.app_config()
        self.assertEqual(app_config["DEVICE_DELIVERY_ROOT"], self.storage.directory("data") / "delivery")
        migrated = browser_client(create_app(app_config))
        migrated.set_cookie("session", self.cookie)
        self.assertEqual(migrated.get("/admin").status_code, 200)
        events = migrated.get("/api/events").json["events"]
        self.assertEqual([event["title"] for event in events], ["Migrated"])
        with closing(sqlite3.connect(self.storage.directory("data") / "kiosk.sqlite")) as database:
            original = database.execute("SELECT image_original FROM events").fetchone()[0]
        self.assertTrue(original.startswith("data/uploads/"), original)
        for url in (events[0]["image_original"], events[0]["image_kiosk"], events[0]["image_tv"], events[0]["image_thumb"]):
            if url.startswith("/static/"):
                self.assertEqual(migrated.get(url).status_code, 200, url)
        generation = self.storage.directory("secrets") / record["generation"]
        self.assertEqual(generation.joinpath("authority.pem").read_bytes(), self.ca_file.read_bytes())
        self.assertEqual(generation.joinpath("server.key").read_bytes(), self.source.joinpath("tls/tls-key.pem").read_bytes())
        # The source is retained byte for byte.
        self.assertTrue((self.source / "instance/kiosk.sqlite").is_file())

    def test_import_requires_confirmation_new_destination_and_matching_ca(self):
        with patch("kiosk.launcher.windows.protect_storage"), self.assertRaises(ValueError):
            import_runtime(self.storage, self.source, self.ca_file, self.fingerprint)
        with patch("kiosk.launcher.windows.protect_storage"), self.assertRaises(ValueError):
            import_runtime(self.storage, self.source, self.ca_file, "0" * 64, source_stopped=True)
        self.assertFalse(self.storage.root.exists())
        with patch("kiosk.launcher.windows.protect_storage"):
            import_runtime(self.storage, self.source, self.ca_file, self.fingerprint, source_stopped=True)
        with patch("kiosk.launcher.windows.protect_storage"), self.assertRaises(ValueError):
            import_runtime(self.storage, self.source, self.ca_file, self.fingerprint, source_stopped=True)

    def test_delivery_marker_is_opt_in_and_validated(self):
        with patch("kiosk.launcher.windows.protect_storage"):
            import_runtime(self.storage, self.source, self.ca_file, self.fingerprint, source_stopped=True)
        plain = Storage(self.root / "plain")
        for name in ("data", "config", "secrets", "logs", "temp", "updates", "status"):
            plain.directory(name).mkdir(parents=True)
        self.assertNotIn("DEVICE_DELIVERY_ROOT", plain.app_config())
        self.assertEqual(plain.enable_delivery(), plain.directory("data") / "delivery")
        self.assertEqual(plain.app_config()["DEVICE_DELIVERY_ROOT"], plain.directory("data") / "delivery")
        (plain.directory("config") / "delivery-enabled.json").write_text('{"schema_version": 2}', encoding="utf-8")
        with self.assertRaises(ValueError):
            plain.app_config()


if __name__ == "__main__":
    unittest.main()
