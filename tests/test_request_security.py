import io
import json
import re
import sqlite3
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from html.parser import HTMLParser
from pathlib import Path
from unittest.mock import patch

from PIL import Image

from kiosk.app import create_app
from kiosk.core.credentials import save_admin_password
from kiosk.core.request_security import AuthenticationLimiter
from kiosk.database import get_database


class FormParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.forms = []
        self.current = None

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "form":
            self.current = {"method": attrs.get("method", "get"), "action": attrs.get("action"), "token": None}
            self.forms.append(self.current)
        if tag == "input" and self.current is not None and attrs.get("name") == "csrf_token":
            self.current["token"] = attrs.get("value")

    def handle_endtag(self, tag):
        if tag == "form":
            self.current = None


class RequestSecurityTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        root = Path(self.directory.name)
        self.app = create_app({"TESTING": True, "BASE_DIR": root, "INSTANCE_DIR": root / "instance", "DATABASE_PATH": root / "instance/kiosk.sqlite", "PRIVATE_UPLOAD_DIR": root / "instance/uploads", "PUBLIC_UPLOAD_DIR": root / "public/uploads", "STATIC_FOLDER": root / "public"})
        save_admin_password(self.app, "security-test-password", setup=True)
        self.client = self.app.test_client()

    def token(self, client=None, page="/kiosk"):
        response = (client or self.client).get(page)
        self.assertEqual(response.status_code, 200)
        return re.search(r'<meta name="csrf-token" content="([^"]+)"', response.get_data(as_text=True)).group(1)

    def login(self):
        return self.client.post("/admin/login", data={"username": "admin", "password": "security-test-password", "csrf_token": self.token()})

    def dump(self):
        with closing(sqlite3.connect(self.app.config["DATABASE_PATH"])) as database:
            return list(database.iterdump())

    def test_all_admin_post_routes_reject_missing_token_without_mutation(self):
        self.assertEqual(self.login().status_code, 302)
        before = self.dump()
        paths = []
        for rule in self.app.url_map.iter_rules():
            if rule.endpoint.startswith("admin.") and "POST" in rule.methods:
                path = rule.rule.replace("<int:event_id>", "1").replace("<int:tag_id>", "1")
                paths.append(path)
                with self.subTest(path=path):
                    response = self.client.post(path, data={"name": "forged", "site_title": "forged"})
                    self.assertEqual(response.status_code, 403)
        self.assertEqual(self.dump(), before)
        self.assertEqual(self.client.get("/admin").status_code, 200)
        self.assertEqual(len(paths), 14)
        print("CSRF Flask checks:", len(paths), "administrative POST routes reject missing tokens with 403")

    def test_tokens_are_session_bound_validated_and_rotated(self):
        first = self.token()
        other = self.app.test_client()
        foreign = self.token(other)
        self.assertNotEqual(first, foreign)
        for value in ("", "wrong", foreign, "я" * 64):
            with self.subTest(value=value[:5]):
                self.assertEqual(self.client.post("/admin/login", data={"username": "admin", "password": "security-test-password", "csrf_token": value}).status_code, 403)
        self.assertEqual(self.login().status_code, 302)
        after_login = self.token()
        self.assertNotEqual(first, after_login)
        self.assertEqual(self.client.post("/admin/tags/create", data={"name": "forged", "csrf_token": first}).status_code, 403)
        self.assertEqual(self.client.post("/admin/logout", headers={"X-CSRF-Token": after_login}).status_code, 302)
        self.assertNotEqual(after_login, self.token())

    def test_rendered_forms_include_working_tokens(self):
        parser = FormParser()
        parser.feed(self.client.get("/admin/login").get_data(as_text=True))
        self.assertEqual(len(parser.forms), 1)
        response = self.client.post(parser.forms[0]["action"], data={"username": "admin", "password": "security-test-password", "csrf_token": parser.forms[0]["token"]})
        self.assertEqual(response.status_code, 302)
        with self.app.app_context():
            database = get_database()
            database.execute("INSERT INTO events (title, created_at, updated_at) VALUES ('Test', 'old', 'old')")
            database.execute("INSERT INTO tags (name, created_at, updated_at) VALUES ('Test', 'old', 'old')")
            database.commit()
        forms = {}
        for page in ("/admin", "/admin/events", "/admin/events/create", "/admin/events/1/edit", "/admin/events/1/tags", "/admin/tags", "/admin/tags/1/edit", "/admin/settings", "/admin/password/change"):
            response = self.client.get(page)
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.headers["Cache-Control"], "no-store")
            parser = FormParser()
            parser.feed(response.get_data(as_text=True))
            for form in parser.forms:
                if form["method"] == "post":
                    self.assertEqual(form["token"], self.token())
                    forms[form["action"]] = form["token"]
        for rule in self.app.url_map.iter_rules():
            if rule.endpoint.startswith("admin.") and "POST" in rule.methods and rule.endpoint not in {"admin.login_post", "admin.fullscreen_validate"}:
                path = rule.rule.replace("<int:event_id>", "1").replace("<int:tag_id>", "1")
                self.assertIn(path, forms)
        response = self.client.post("/admin/tags/create", data={"name": "Allowed", "csrf_token": forms["/admin/tags/create"]})
        self.assertEqual(response.status_code, 302)
        self.assertIn("Allowed", self.client.get("/admin/tags").get_data(as_text=True))

    def test_multipart_upload_and_version_change_with_token(self):
        self.login()
        image = io.BytesIO()
        Image.new("RGB", (32, 32), "blue").save(image, "PNG")
        image.seek(0)
        version = self.client.get("/api/version").json["content_version"]
        response = self.client.post("/admin/events/create", data={"title": "Uploaded", "status": "active", "csrf_token": self.token(), "event_image": (image, "event.png")}, content_type="multipart/form-data")
        self.assertEqual(response.status_code, 302)
        event = self.client.get("/api/events").json["events"][0]
        with self.client.get(event["image_kiosk"]) as image_response:
            self.assertEqual(image_response.status_code, 200)
        self.assertGreater(self.client.get("/api/version").json["content_version"], version)

    def test_fullscreen_json_csrf_and_malformed_payloads(self):
        data = {"username": "admin", "password": "security-test-password"}
        response = self.client.post("/admin/fullscreen/validate", json=data)
        self.assertEqual(response.status_code, 403)
        self.assertFalse(response.json["success"])
        headers = {"X-CSRF-Token": self.token()}
        response = self.client.post("/admin/fullscreen/validate", json=data, headers=headers)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json, {"success": True})
        for data in ([], None, "not an object"):
            response = self.client.post("/admin/fullscreen/validate", data=json.dumps(data), content_type="application/json", headers=headers)
            self.assertEqual(response.status_code, 400)
            self.assertFalse(response.json["success"])

    def test_login_and_fullscreen_share_limits_despite_new_cookies_and_forwarded_headers(self):
        with patch("kiosk.core.request_security.time.monotonic", return_value=100):
            token = self.token()
            for index in range(10):
                if index % 2:
                    response = self.client.post("/admin/fullscreen/validate", json={"username": "admin", "password": "wrong"}, headers={"X-CSRF-Token": token})
                    self.assertEqual(response.status_code, 200)
                else:
                    response = self.client.post("/admin/login", data={"username": "admin", "password": "wrong", "csrf_token": token})
                    self.assertEqual(response.status_code, 401)
            fresh = self.app.test_client()
            fresh_token = self.token(fresh)
            response = fresh.post("/admin/login", data={"username": "admin", "password": "security-test-password", "csrf_token": fresh_token}, headers={"X-Forwarded-For": "192.0.2.99"})
            self.assertEqual(response.status_code, 429)
            self.assertEqual(response.headers["Retry-After"], "60")
            other_source = fresh.post("/admin/login", data={"username": "admin", "password": "wrong", "csrf_token": fresh_token}, environ_overrides={"REMOTE_ADDR": "192.0.2.1"})
            self.assertEqual(other_source.status_code, 401)
        with patch("kiosk.core.request_security.time.monotonic", return_value=160):
            self.assertEqual(self.login().status_code, 302)

    def test_source_limit_prevents_username_rotation(self):
        token = self.token()
        with patch("kiosk.core.request_security.time.monotonic", return_value=100):
            for index in range(40):
                response = self.client.post("/admin/login", data={"username": f"missing-{index}", "password": "wrong", "csrf_token": token})
                self.assertEqual(response.status_code, 401)
            response = self.client.post("/admin/fullscreen/validate", json={"username": "admin", "password": "security-test-password"}, headers={"X-CSRF-Token": token})
            self.assertEqual(response.status_code, 429)
            self.assertFalse(response.json["success"])
        print("Throttle Flask checks: login/fullscreen 429 with Retry-After; expiry permits retry")

    def test_current_password_checks_share_authenticated_account_budget(self):
        with patch("kiosk.core.request_security.time.monotonic", return_value=100):
            self.login()
            token = self.token()
            for index in range(9):
                response = self.client.post("/admin/password/change", data={"username": f"spoof-{index}", "current_password": "wrong", "new_password": "replacement-password", "confirm_password": "replacement-password", "csrf_token": token})
                self.assertEqual(response.status_code, 401)
            before = self.dump()
            response = self.client.post("/admin/password/change", data={"current_password": "security-test-password", "new_password": "replacement-password", "confirm_password": "replacement-password", "csrf_token": token})
            self.assertEqual(response.status_code, 429)
            self.assertEqual(self.dump(), before)

    def test_limiter_concurrency_expiry_and_capacity(self):
        limiter = AuthenticationLimiter()
        with patch("kiosk.core.request_security.time.monotonic", return_value=100), ThreadPoolExecutor(max_workers=12) as pool:
            results = list(pool.map(lambda index: limiter.reserve("source", "admin"), range(30)))
        self.assertEqual(results.count(0), 10)
        self.assertEqual(results.count(60), 20)
        limiter = AuthenticationLimiter(capacity=4)
        with patch("kiosk.core.request_security.time.monotonic", return_value=100):
            self.assertEqual(limiter.reserve("first", "admin"), 0)
            self.assertEqual(limiter.reserve("second", "admin"), 0)
            self.assertEqual(limiter.reserve("third", "admin"), 60)
            self.assertEqual(len(limiter.entries), 4)
        with patch("kiosk.core.request_security.time.monotonic", return_value=160):
            self.assertEqual(limiter.reserve("third", "admin"), 0)
            self.assertEqual(len(limiter.entries), 2)

    def test_invalid_csrf_does_not_consume_password_budget_and_cookie_policy(self):
        self.token()
        for index in range(12):
            self.assertEqual(self.client.post("/admin/login").status_code, 403)
        self.assertEqual(self.login().status_code, 302)
        self.assertEqual(len(self.app.extensions["authentication_limiter"].entries), 2)
        response = self.app.test_client().get("/kiosk")
        self.assertIn("HttpOnly", response.headers["Set-Cookie"])
        self.assertIn("SameSite=Lax", response.headers["Set-Cookie"])
        self.assertEqual(response.headers["Cache-Control"], "no-store")
        for path in ("/api/events", "/api/tags", "/api/version"):
            response = self.app.test_client().get(path)
            self.assertEqual(response.status_code, 200)
            self.assertNotIn("csrf", json.dumps(response.json))
            self.assertNotIn("Set-Cookie", response.headers)


if __name__ == "__main__":
    unittest.main()
