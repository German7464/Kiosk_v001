import io
import json
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

from PIL import Image
from werkzeug.security import check_password_hash

from kiosk.app import create_app
from kiosk.database import get_database
from kiosk.server import find_clientkiosk_executable, launch_clientkiosk, local_server_is_ready, reset_admin_password, reset_admin_password_command, startup_launch_lines, startup_message, run_waitress_with_launcher
from serve import parse_args


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
        admin_response = self.client.get("/admin")
        self.assertEqual(admin_response.status_code, 200)
        self.assertIn('href="/preview"', admin_response.get_data(as_text=True))

        logout = self.client.post("/admin/logout")
        self.assertEqual(logout.status_code, 302)
        self.assertEqual(self.client.get("/admin").status_code, 302)

    def test_serve_cli_arguments_and_startup_message(self):
        default_args = parse_args([])
        loopback_args = parse_args(["--host", "127.0.0.1"])
        lan_args = parse_args(["--host", "0.0.0.0"])
        specific_args = parse_args(["--host", "192.168.1.117", "--port", "5000"])
        no_client_args = parse_args(["--no-client"])
        reset_args = parse_args(["--reset-admin-password"])

        self.assertEqual(default_args.host, "127.0.0.1")
        self.assertEqual(default_args.port, 5000)
        self.assertFalse(default_args.reset_admin_password)
        self.assertFalse(default_args.no_client)
        self.assertEqual(loopback_args.host, "127.0.0.1")
        self.assertEqual(lan_args.host, "0.0.0.0")
        self.assertEqual(specific_args.host, "192.168.1.117")
        self.assertEqual(specific_args.port, 5000)
        self.assertTrue(no_client_args.no_client)
        self.assertTrue(reset_args.reset_admin_password)

        loopback_app = create_app(
            {
                "TESTING": True,
                "BASE_DIR": self.test_root,
                "INSTANCE_DIR": self.instance_dir,
                "DATABASE_PATH": self.instance_dir / "kiosk.sqlite",
                "PRIVATE_UPLOAD_DIR": self.instance_dir / "uploads",
                "PUBLIC_UPLOAD_DIR": self.static_dir / "uploads",
                "STATIC_FOLDER": self.static_dir,
                "SECRET_KEY": "test",
                "SERVER_HOST": "127.0.0.1",
                "SERVER_PORT": 5000,
            }
        )
        lan_app = create_app(
            {
                "TESTING": True,
                "BASE_DIR": self.test_root,
                "INSTANCE_DIR": self.instance_dir,
                "DATABASE_PATH": self.instance_dir / "kiosk.sqlite",
                "PRIVATE_UPLOAD_DIR": self.instance_dir / "uploads",
                "PUBLIC_UPLOAD_DIR": self.static_dir / "uploads",
                "STATIC_FOLDER": self.static_dir,
                "SECRET_KEY": "test",
                "SERVER_HOST": "0.0.0.0",
                "SERVER_PORT": 5000,
            }
        )
        specific_host_app = create_app(
            {
                "TESTING": True,
                "BASE_DIR": self.test_root,
                "INSTANCE_DIR": self.instance_dir,
                "DATABASE_PATH": self.instance_dir / "kiosk.sqlite",
                "PRIVATE_UPLOAD_DIR": self.instance_dir / "uploads",
                "PUBLIC_UPLOAD_DIR": self.static_dir / "uploads",
                "STATIC_FOLDER": self.static_dir,
                "SECRET_KEY": "test",
                "SERVER_HOST": "192.168.1.117",
                "SERVER_PORT": 5000,
            }
        )

        self.assertIn("Other devices cannot connect to 127.0.0.1.", startup_message(loopback_app))

        lan_message = startup_message(lan_app)
        self.assertIn("Local URLs (127.0.0.1):", lan_message)
        self.assertIn("Other devices should use the computer LAN IP address.", lan_message)
        self.assertIn("If another device cannot connect, disable VPN, check that both devices are on the same Wi-Fi, and allow TCP port 5000 in Windows Firewall.", lan_message)

        specific_message = startup_message(specific_host_app)
        self.assertIn("Other devices should use http://192.168.1.117:5000.", specific_message)
        with patch("kiosk.server.find_clientkiosk_executable") as find_client_mock, patch("kiosk.server.launch_browser") as launch_browser_mock:
            no_client_message = startup_launch_lines("0.0.0.0", 5000, path="/kiosk", auto_launch=False)

        find_client_mock.assert_not_called()
        launch_browser_mock.assert_not_called()
        self.assertIn("Automatic kiosk client/browser launch: disabled", "\n".join(no_client_message))
        self.assertIn("Automatic client/browser launch disabled with --no-client.", "\n".join(no_client_message))
        self.assertIn("Open this URL manually: http://127.0.0.1:5000/kiosk", "\n".join(no_client_message))

        self.assertTrue(local_server_is_ready(5000, opener=lambda url, timeout=0.5: type("Response", (), {"status": 200})()))
        self.assertFalse(local_server_is_ready(5000, opener=lambda url, timeout=0.5: (_ for _ in ()).throw(OSError())))

        with patch("kiosk.server.find_clientkiosk_executable", return_value=None), patch("kiosk.server.launch_browser") as launch_browser, patch("kiosk.server.create_app") as create_app_mock, patch("kiosk.server.serve") as serve_mock:
            output = io.StringIO()
            with redirect_stdout(output):
                with patch("kiosk.server.local_server_is_ready", return_value=True):
                    run_waitress_with_launcher(host="0.0.0.0", port=5000, path="/tv")

            create_app_mock.assert_not_called()
            serve_mock.assert_not_called()
            launch_browser.assert_called_once_with("http://127.0.0.1:5000/tv", kiosk_mode=True)
            self.assertIn("Existing local server detected", output.getvalue())

    def test_clientkiosk_detection_and_launch_fallback(self):
        with tempfile.TemporaryDirectory() as client_directory_name:
            client_directory = Path(client_directory_name)
            client_executable = client_directory / "ClientKiosk.exe"
            client_executable.write_text("stub", encoding="utf-8")

            self.assertEqual(find_clientkiosk_executable(base_dir=client_directory), client_executable)
            with patch("kiosk.server.clientkiosk_search_directories", return_value=[client_directory / "missing"]):
                self.assertIsNone(find_clientkiosk_executable())

        client_path = Path("C:/ClientKiosk.exe")

        with patch("kiosk.server.subprocess.Popen") as popen_mock:
            launched = launch_clientkiosk(client_path, "0.0.0.0", 5000, "/tv")

        self.assertTrue(launched)
        popen_mock.assert_called_once()
        command = popen_mock.call_args.args[0]
        self.assertEqual(command[0], str(client_path))
        self.assertEqual(command[1:], ["--url", "http://127.0.0.1:5000/tv", "--host", "127.0.0.1", "--port", "5000", "--mode", "tv"])

        with patch("kiosk.server.find_clientkiosk_executable", return_value=None), patch("kiosk.server.launch_browser", return_value=False) as launch_browser:
            output_lines = startup_launch_lines("0.0.0.0", 5000, path="/kiosk", auto_launch=True)

        launch_browser.assert_called_once_with("http://127.0.0.1:5000/kiosk", kiosk_mode=True)
        joined_lines = "\n".join(output_lines)
        self.assertIn("Automatic kiosk client/browser launch: enabled", joined_lines)
        self.assertIn("ClientKiosk.exe was not found.", joined_lines)
        self.assertIn("Default browser could not be opened.", joined_lines)
        self.assertIn("Open this URL manually: http://127.0.0.1:5000/kiosk", joined_lines)

    def test_kiosk_fullscreen_unlock_uses_current_admin_credentials(self):
        self.login()

        wrong_response = self.client.post(
            "/admin/fullscreen/validate",
            data=json.dumps({"username": "admin", "password": "wrong"}),
            content_type="application/json",
        )
        self.assertEqual(wrong_response.status_code, 200)
        self.assertEqual(wrong_response.get_json(), {"success": False})
        self.assertNotIn("password_hash", wrong_response.get_data(as_text=True))
        self.assertEqual(set(wrong_response.get_json().keys()), {"success"})

        correct_response = self.client.post(
            "/admin/fullscreen/validate",
            data=json.dumps({"username": "admin", "password": "admin"}),
            content_type="application/json",
        )
        self.assertEqual(correct_response.status_code, 200)
        self.assertEqual(correct_response.get_json(), {"success": True})
        self.assertNotIn("password_hash", correct_response.get_data(as_text=True))
        self.assertEqual(set(correct_response.get_json().keys()), {"success"})

        change_response = self.client.post(
            "/admin/password/change",
            data={
                "current_password": "admin",
                "new_password": "changed-admin-password",
                "confirm_password": "changed-admin-password",
            },
        )
        self.assertEqual(change_response.status_code, 302)

        old_password_response = self.client.post(
            "/admin/fullscreen/validate",
            data=json.dumps({"username": "admin", "password": "admin"}),
            content_type="application/json",
        )
        self.assertEqual(old_password_response.get_json(), {"success": False})

        new_password_response = self.client.post(
            "/admin/fullscreen/validate",
            data=json.dumps({"username": "admin", "password": "changed-admin-password"}),
            content_type="application/json",
        )
        self.assertEqual(new_password_response.get_json(), {"success": True})

        kiosk_home_js = Path("kiosk/static/js/kiosk_home.js").read_text(encoding="utf-8")
        self.assertIn("requestFullscreen", kiosk_home_js)
        self.assertIn("requestKioskFullscreenExit", kiosk_home_js)
        self.assertNotIn("admin/admin", kiosk_home_js)
        self.assertNotIn("exitFullscreen().call(document)", kiosk_home_js)

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

    def test_kiosk_events_inactivity_warning_and_preview_link(self):
        self.login()

        kiosk_events_response = self.client.get("/kiosk/events")
        self.assertEqual(kiosk_events_response.status_code, 200)
        self.assertIn("data-inactivity-warning", kiosk_events_response.get_data(as_text=True))
        self.assertNotIn("kiosk.inactivity_warning_title", kiosk_events_response.get_data(as_text=True))
        self.assertNotIn("KIOSK.INACTIVITY_WARNING_LABEL", kiosk_events_response.get_data(as_text=True))

        kiosk_events_js = Path("kiosk/static/js/kiosk_events.js").read_text(encoding="utf-8")
        self.assertIn("const inactivityWarningDelaySeconds = 120;", kiosk_events_js)
        self.assertIn("const inactivityWarningCountdownSeconds = 30;", kiosk_events_js)
        self.assertIn('window.location.href = "/kiosk";', kiosk_events_js)
        self.assertIn("hideInactivityWarning", kiosk_events_js)
        self.assertIn("resetInactivityTimer", kiosk_events_js)
        self.assertIn("data-inactivity-warning-countdown", Path("kiosk/templates/kiosk_events.html").read_text(encoding="utf-8"))

        for language in ("ru", "en", "de"):
            translation_text = Path(f"kiosk/translations/{language}.json").read_text(encoding="utf-8")
            self.assertIn("kiosk.inactivity_warning_text", translation_text)
            self.assertNotIn("kiosk.inactivity_warning_message", translation_text)
            self.assertNotIn("kiosk.inactivity_warning_touch", translation_text)

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
