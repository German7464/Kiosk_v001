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
from kiosk.launcher.storage import DIRECTORIES, Storage, atomic_json, import_mvp, new_profile, read_profile, save_profile
from tests.browser_client import browser_client


class LauncherStorageTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.storage = Storage(self.root / "installed")

    def directories(self):
        for name in DIRECTORIES:
            self.storage.directory(name).mkdir(parents=True)

    def source(self):
        source = self.root / "mvp"
        config = {"BASE_DIR": source, "INSTANCE_DIR": source / "instance", "DATABASE_PATH": source / "instance/kiosk.sqlite",
                  "PRIVATE_UPLOAD_DIR": source / "instance/uploads", "PUBLIC_UPLOAD_DIR": source / "kiosk/static/uploads",
                  "STATIC_DIR": source / "kiosk/static"}
        app = create_app(config)
        save_admin_password(app, "isolated-storage-test-password", setup=True)
        client = browser_client(app)
        self.assertEqual(client.post("/admin/login", data={"username": "admin", "password": "isolated-storage-test-password"}).status_code, 302)
        return source, app, client

    def test_separate_storage_and_routes(self):
        app = create_app(self.storage.app_config())
        self.assertTrue((self.storage.root / "secrets/session.key").is_file())
        self.assertFalse((self.storage.root / "data/session.key").exists())
        self.assertTrue((self.storage.root / "data/kiosk.sqlite").is_file())
        for route in ("/kiosk", "/kiosk/events", "/tv", "/preview", "/admin/login", "/api/version", "/api/events", "/api/tags"):
            self.assertEqual(app.test_client().get(route).status_code, 200, route)
        self.assertEqual(app.test_client().get("/admin").status_code, 302)
        self.assertEqual(app.test_client().post("/admin/login").status_code, 403)

    def test_profile_identity_previous_and_corruption(self):
        self.directories()
        profile = new_profile("Hall")
        save_profile(self.storage, profile)
        changed = {**profile, "device_name": "New Hall", "port": 5100}
        save_profile(self.storage, changed)
        self.assertEqual(read_profile(self.storage.profile), changed)
        self.assertEqual(read_profile(self.storage.profile.with_suffix(".previous.json")), profile)
        with self.assertRaises(ValueError):
            save_profile(self.storage, new_profile("replacement"))
        self.storage.profile.write_text("corrupted", encoding="utf-8")
        with self.assertRaises(ValueError):
            save_profile(self.storage, changed)
        self.assertEqual(self.storage.profile.read_text(), "corrupted")

    def test_invalid_and_duplicate_configuration(self):
        self.directories()
        profile = new_profile("Hall")
        for field, value in (("port", True), ("port", 80), ("device_name", "\n"), ("mode", "remote"), ("server_autostart", 1), ("schema_version", True)):
            with self.subTest(field=field, value=value), self.assertRaises(ValueError):
                save_profile(self.storage, {**profile, field: value})
        self.storage.profile.write_text(json.dumps(profile)[:-1] + ', "port": 6000}', encoding="utf-8")
        with self.assertRaises(ValueError):
            read_profile(self.storage.profile)

    def test_atomic_failure_preserves_configuration(self):
        self.directories()
        profile = new_profile("Hall")
        save_profile(self.storage, profile)
        original = self.storage.profile.read_bytes()
        with patch("kiosk.launcher.storage.os.replace", side_effect=PermissionError), patch("kiosk.launcher.storage.time.sleep"), self.assertRaises(PermissionError):
            atomic_json(self.storage.profile, {**profile, "device_name": "Changed"})
        self.assertEqual(self.storage.profile.read_bytes(), original)
        self.assertEqual(list(self.storage.profile.parent.glob(".kiosk-*")), [])

    def test_import_preserves_content_key_credentials_session_and_images(self):
        source, app, client = self.source()
        content = io.BytesIO()
        Image.new("RGB", (80, 60), "red").save(content, format="PNG")
        content.seek(0)
        response = client.post("/admin/events/create", data={"title": "Imported event", "status": "active", "event_image": (content, "test.png")})
        self.assertEqual(response.status_code, 302)
        before = client.get("/api/events").json
        version = client.get("/api/version").json
        original_database = (source / "instance/kiosk.sqlite").read_bytes()
        with patch("kiosk.launcher.windows.protect_storage"):
            import_mvp(source, self.storage, source_stopped=True)
        self.assertEqual((source / "instance/kiosk.sqlite").read_bytes(), original_database)
        migrated = browser_client(create_app(self.storage.app_config()))
        migrated.set_cookie("session", client.get_cookie("session").value)
        self.assertEqual(migrated.get("/admin").status_code, 200)
        self.assertEqual(migrated.get("/api/version").json, version)
        after = migrated.get("/api/events").json
        for event in before["events"]:
            event["image_original"] = event["image_original"].replace("instance/uploads/", "data/uploads/")
        self.assertEqual(after, before)
        with closing(sqlite3.connect(self.storage.root / "data/kiosk.sqlite")) as database:
            images = database.execute("SELECT image_original, image_kiosk, image_tv, image_thumb FROM events").fetchone()
        self.assertTrue(images[0].startswith("data/uploads/"))
        for url in images[1:]:
            with migrated.get(url) as response:
                self.assertEqual(response.status_code, 200)

    def test_import_failure_does_not_activate_or_modify_source(self):
        source, app, client = self.source()
        key = (source / "instance/session.key").read_bytes()
        with self.assertRaises(ValueError):
            import_mvp(source, self.storage)
        with patch("kiosk.launcher.windows.protect_storage"), patch("kiosk.launcher.storage.verify_database", side_effect=ValueError), self.assertRaises(ValueError):
            import_mvp(source, self.storage, source_stopped=True)
        self.assertFalse(self.storage.root.exists())
        self.assertEqual((source / "instance/session.key").read_bytes(), key)
        self.assertEqual(list(self.root.glob(".kiosk-import-*")), [])

    def test_existing_destination_is_never_overwritten(self):
        source, app, client = self.source()
        self.directories()
        with self.assertRaises(ValueError):
            import_mvp(source, self.storage, source_stopped=True)


if __name__ == "__main__":
    unittest.main()
