import io
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

from PIL import Image
from werkzeug.security import check_password_hash

from kiosk.app import create_app
from kiosk.database import get_database
from kiosk.server import reset_admin_password, reset_admin_password_command, startup_message


class MvpSmokeTests(unittest.TestCase):
    def setUp(self):
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.test_root = Path(self.temporary_directory.name)
        self.instance_dir = self.test_root / "instance"
        self.static_dir = self.test_root / "static"
        self.app = create_app(
            {
                "TESTING": True,
                "BASE_DIR": self.test_root,
                "INSTANCE_DIR": self.instance_dir,
                "DATABASE_PATH": self.instance_dir / "kiosk.sqlite",
                "PRIVATE_UPLOAD_DIR": self.instance_dir / "uploads",
                "PUBLIC_UPLOAD_DIR": self.static_dir / "uploads",
                "STATIC_FOLDER": self.static_dir,
                "SECRET_KEY": "test",
            }
        )
        self.client = self.app.test_client()

    def tearDown(self):
        self.temporary_directory.cleanup()

    def test_main_routes_and_authentication(self):
        expected_statuses = {
            "/kiosk": 200,
            "/kiosk/events": 200,
            "/tv": 200,
            "/preview": 200,
            "/admin": 302,
            "/admin/login": 200,
            "/api/version": 200,
            "/api/events": 200,
            "/api/tags": 200,
        }

        for path, expected_status in expected_statuses.items():
            with self.subTest(path=path):
                response = self.client.get(path)
                self.assertEqual(response.status_code, expected_status)

        wrong_login = self.client.post(
            "/admin/login",
            data={"username": "admin", "password": "wrong"},
        )
        self.assertEqual(wrong_login.status_code, 401)

        login = self.login()
        self.assertEqual(login.status_code, 302)
        self.assertEqual(self.client.get("/admin").status_code, 200)

        logout = self.client.post("/admin/logout")
        self.assertEqual(logout.status_code, 302)
        self.assertEqual(self.client.get("/admin").status_code, 302)

    def test_event_tag_and_image_flow(self):
        self.login()
        event_id = self.create_event("Hidden smoke event")
        event = self.fetch_event(event_id)

        self.assertEqual(event["status"], "hidden")
        self.assertNotIn(event_id, self.api_event_ids())
        self.assert_image_outputs_exist(event)

        self.assertEqual(self.client.post(f"/admin/events/{event_id}/toggle").status_code, 302)
        self.assertIn(event_id, self.api_event_ids())
        self.assertEqual(self.client.get(f"/api/events/{event_id}").status_code, 200)

        edit_response = self.client.post(
            f"/admin/events/{event_id}/edit",
            data={
                "title": "Edited smoke event",
                "short_description": "Edited short description",
                "full_description": "Edited full description",
                "event_date": "2030-01-02",
                "place": "Edited place",
                "status": "active",
                "sort_order": "5",
            },
        )
        self.assertEqual(edit_response.status_code, 302)
        self.assertEqual(self.fetch_event(event_id)["title"], "Edited smoke event")

        tag_id = self.create_tag("Smoke tag")
        self.assertEqual(self.edit_tag(tag_id, "Edited smoke tag").status_code, 302)
        self.assertEqual(self.assign_tag(event_id, tag_id).status_code, 302)

        event_list_item = self.get_api_event(event_id, "/api/events")
        event_detail = self.client.get(f"/api/events/{event_id}").get_json()["event"]
        self.assertEqual(event_list_item["tags"][0]["name"], "Edited smoke tag")
        self.assertEqual(event_detail["tags"][0]["name"], "Edited smoke tag")

        self.assertEqual(self.client.post(f"/admin/tags/{tag_id}/delete").status_code, 302)
        event_after_tag_delete = self.client.get(f"/api/events/{event_id}").get_json()["event"]
        self.assertEqual(event_after_tag_delete["tags"], [])

        self.assertEqual(self.client.post(f"/admin/events/{event_id}/delete").status_code, 302)
        self.assertEqual(self.client.get(f"/api/events/{event_id}").status_code, 404)

    def test_settings_flow_increases_content_version(self):
        self.login()
        initial_version = self.client.get("/api/version").get_json()["content_version"]
        response = self.client.post(
            "/admin/settings",
            data={
                "site_title": "Smoke Test Kiosk",
                "interface_language": "ru",
            },
        )
        next_version = self.client.get("/api/version").get_json()["content_version"]

        self.assertEqual(response.status_code, 302)
        self.assertGreater(next_version, initial_version)

        with self.app.app_context():
            rows = get_database().execute(
                "SELECT key, value FROM settings WHERE key IN (?, ?)",
                ("site_title", "interface_language"),
            ).fetchall()
            settings = {row["key"]: row["value"] for row in rows}

        self.assertEqual(settings["site_title"], "Smoke Test Kiosk")
        self.assertEqual(settings["interface_language"], "ru")

    def test_admin_password_reset_uses_temporary_database(self):
        temporary_password = reset_admin_password(self.app)

        with self.app.app_context():
            row = get_database().execute(
                "SELECT password_hash FROM users WHERE username = ?",
                ("admin",),
            ).fetchone()

        self.assertIsNotNone(row)
        self.assertNotEqual(row["password_hash"], temporary_password)
        self.assertTrue(check_password_hash(row["password_hash"], temporary_password))
        self.assertFalse((Path.cwd() / "instance" / "kiosk.sqlite").samefile(self.instance_dir / "kiosk.sqlite") if (Path.cwd() / "instance" / "kiosk.sqlite").exists() else False)

        normal_output = startup_message(self.app)
        self.assertNotIn("Temporary password:", normal_output)

        reset_output = io.StringIO()
        with redirect_stdout(reset_output):
            reset_admin_password_command(self.app)

        self.assertIn("Temporary password:", reset_output.getvalue())

    def login(self):
        return self.client.post(
            "/admin/login",
            data={"username": "admin", "password": "admin"},
        )

    def create_event(self, title):
        response = self.client.post(
            "/admin/events/create",
            data={
                "title": title,
                "short_description": "Short description",
                "full_description": "Full description",
                "event_date": "2030-01-01",
                "place": "Smoke room",
                "status": "hidden",
                "sort_order": "1",
                "event_image": (self.create_image_file(), "event.png"),
            },
            content_type="multipart/form-data",
        )
        self.assertEqual(response.status_code, 302)

        with self.app.app_context():
            row = get_database().execute(
                "SELECT id FROM events WHERE title = ?",
                (title,),
            ).fetchone()

        self.assertIsNotNone(row)
        return row["id"]

    def create_tag(self, name):
        response = self.client.post("/admin/tags/create", data={"name": name})
        self.assertEqual(response.status_code, 302)

        with self.app.app_context():
            row = get_database().execute(
                "SELECT id FROM tags WHERE name = ?",
                (name,),
            ).fetchone()

        self.assertIsNotNone(row)
        return row["id"]

    def edit_tag(self, tag_id, name):
        return self.client.post(f"/admin/tags/{tag_id}/edit", data={"name": name})

    def assign_tag(self, event_id, tag_id):
        return self.client.post(
            f"/admin/events/{event_id}/tags",
            data={"tag_ids": [str(tag_id)]},
        )

    def fetch_event(self, event_id):
        with self.app.app_context():
            return get_database().execute(
                "SELECT * FROM events WHERE id = ?",
                (event_id,),
            ).fetchone()

    def api_event_ids(self):
        return {event["id"] for event in self.client.get("/api/events").get_json()["events"]}

    def get_api_event(self, event_id, path):
        events = self.client.get(path).get_json()["events"]
        return next(event for event in events if event["id"] == event_id)

    def create_image_file(self):
        image_file = io.BytesIO()
        image = Image.new("RGB", (32, 32), "blue")
        image.save(image_file, "PNG")
        image_file.seek(0)
        return image_file

    def assert_image_outputs_exist(self, event):
        self.assertTrue((self.test_root / event["image_original"]).is_file())

        for key in ("image_kiosk", "image_tv", "image_thumb"):
            image_path = event[key].removeprefix("/static/")
            self.assertTrue((self.static_dir / image_path).is_file())


if __name__ == "__main__":
    unittest.main()
