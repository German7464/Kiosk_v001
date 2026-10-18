import getpass
import io
import sqlite3
import tempfile
import unittest
import warnings
from concurrent.futures import ProcessPoolExecutor
from contextlib import closing, redirect_stderr, redirect_stdout
from pathlib import Path
from unittest.mock import patch

from werkzeug.security import check_password_hash, generate_password_hash

from kiosk.app import create_app
from kiosk.core.credentials import admin_password_command, save_admin_password, validate_password
from kiosk.database import get_database
from kiosk.server import reset_admin_password_command, setup_admin_command
from serve import main, parse_args


def concurrent_setup(config):
    app = create_app(config)
    try:
        save_admin_password(app, "parallel-test-password", setup=True)
        return "created"
    except ValueError:
        return "exists"


class CredentialTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        root = Path(self.directory.name)
        self.config = {
            "TESTING": True, "BASE_DIR": root, "INSTANCE_DIR": root / "instance",
            "DATABASE_PATH": root / "instance/kiosk.sqlite", "SECRET_KEY": "test",
            "PRIVATE_UPLOAD_DIR": root / "instance/uploads",
            "PUBLIC_UPLOAD_DIR": root / "static/uploads", "STATIC_FOLDER": root / "static",
        }
        self.app = create_app(self.config)
        self.client = self.app.test_client()
        self.password = "initial-test-password"

    def dump(self):
        with closing(sqlite3.connect(self.config["DATABASE_PATH"])) as database:
            return list(database.iterdump())

    def setup_admin(self):
        save_admin_password(self.app, self.password, setup=True)

    def login(self, client=None, password=None):
        return (client or self.client).post("/admin/login", data={"username": "admin", "password": password or self.password})

    def test_empty_installation_and_local_setup(self):
        self.assertIn(b"--setup-admin", self.client.get("/admin/login").data)
        self.assertEqual(self.login(password="admin").status_code, 401)
        before = self.dump()
        with self.assertRaisesRegex(ValueError, "does not exist"):
            save_admin_password(self.app, self.password)
        self.assertEqual(self.dump(), before)
        with patch("kiosk.core.credentials.sys.stdin.isatty", return_value=True), patch("kiosk.core.credentials.getpass.getpass", side_effect=[self.password] * 2), redirect_stdout(io.StringIO()) as output:
            self.assertEqual(setup_admin_command(self.app), 0)
        self.assertNotIn(self.password, output.getvalue())
        self.assertEqual(self.login().status_code, 302)
        self.assertEqual(self.client.get("/admin").status_code, 200)
        with self.app.app_context():
            user = get_database().execute("SELECT * FROM users").fetchone()
            self.assertTrue(check_password_hash(user["password_hash"], self.password))
            self.assertNotIn(user["password_hash"], self.client.get_cookie("session").value)
        before = self.dump()
        with self.assertRaisesRegex(ValueError, "already exist"):
            self.setup_admin()
        self.assertEqual(self.dump(), before)
        print("First-login Flask checks: /admin/login 200; blocked login 401; valid login 302; /admin 200")

    def test_concurrent_setup_has_one_winner(self):
        with ProcessPoolExecutor(max_workers=3) as pool:
            results = list(pool.map(concurrent_setup, [self.config] * 3))
        self.assertEqual(results.count("created"), 1)
        self.assertEqual(results.count("exists"), 2)
        with self.app.app_context():
            self.assertEqual(get_database().execute("SELECT COUNT(*) FROM users").fetchone()[0], 1)

    def test_legacy_credentials_and_existing_sessions_blocked_without_mutation(self):
        with self.app.app_context():
            database = get_database()
            database.execute("INSERT INTO users (username, password_hash, created_at, updated_at) VALUES ('admin', ?, 'old', 'old')", (generate_password_hash("admin"),))
            database.commit()
        before = self.dump()
        create_app(self.config)
        self.assertEqual(before, self.dump())
        self.assertIn(b"--reset-admin-password", self.client.get("/admin/login").data)
        self.assertEqual(self.login(password="admin").status_code, 401)
        self.assertEqual(self.client.post("/admin/fullscreen/validate", json={"username": "admin", "password": "admin"}).get_json(), {"success": False})
        with self.client.session_transaction() as session:
            session["admin_user_id"] = 1
            session["admin_username"] = "admin"
        self.assertEqual(self.client.post("/admin/settings", data={"site_title": "unauthorized"}).status_code, 302)
        self.assertEqual(self.dump(), before)
        save_admin_password(self.app, self.password)
        self.assertEqual(self.login().status_code, 302)

    def test_password_reset_revokes_all_sessions(self):
        self.setup_admin()
        second = self.app.test_client()
        self.login()
        self.login(second)
        save_admin_password(self.app, "replacement-password")
        self.assertEqual(self.client.get("/admin").status_code, 302)
        self.assertEqual(second.post("/admin/tags/create", data={"name": "blocked"}).status_code, 302)
        self.assertEqual(self.login().status_code, 401)
        self.assertEqual(self.login(password="replacement-password").status_code, 302)
        cookie = self.client.get_cookie("session")
        restarted = create_app(self.config).test_client()
        restarted.set_cookie("session", cookie.value)
        self.assertEqual(restarted.get("/admin").status_code, 200)

    def test_old_missing_tampered_and_deleted_user_sessions_rejected(self):
        self.setup_admin()
        for token in (None, "wrong-token", 3):
            with self.client.session_transaction() as session:
                session["admin_user_id"] = 1
                if token is not None:
                    session["credential_token"] = token
            self.assertEqual(self.client.get("/admin").status_code, 302)
        self.login()
        with self.app.app_context():
            database = get_database()
            database.execute("DELETE FROM users")
            database.commit()
        self.assertEqual(self.client.get("/admin").status_code, 302)

    def test_web_password_validation_and_session_revocation(self):
        self.setup_admin()
        self.login()
        second = self.app.test_client()
        self.login(second)
        for new, confirmation in (("short", "short"), ("x" * 129, "x" * 129), (self.password, "different")):
            response = self.client.post("/admin/password/change", data={"current_password": self.password, "new_password": new, "confirm_password": confirmation})
            self.assertEqual(response.status_code, 400)
        response = self.client.post("/admin/password/change", data={"current_password": self.password, "new_password": "new-valid-password", "confirm_password": "new-valid-password"})
        self.assertEqual(response.status_code, 302)
        self.assertTrue(response.location.endswith("/admin/login"))
        self.assertEqual(self.client.get("/admin").status_code, 302)
        self.assertEqual(second.get("/admin").status_code, 302)
        self.assertEqual(self.login(password="new-valid-password").status_code, 302)
        for value in ("x" * 12, "x" * 128, "длинный пароль с пробелами"):
            validate_password(value)

    def test_command_failures_leave_credentials_unchanged(self):
        before = self.dump()
        cases = [("short", "short"), (self.password, "mismatch"), EOFError(), KeyboardInterrupt()]
        for values in cases:
            effects = values if isinstance(values, tuple) else values
            with self.subTest(values=type(values).__name__), patch("kiosk.core.credentials.sys.stdin.isatty", return_value=True), patch("kiosk.core.credentials.getpass.getpass", side_effect=effects), redirect_stderr(io.StringIO()), redirect_stdout(io.StringIO()):
                self.assertEqual(setup_admin_command(self.app), 1)
            self.assertEqual(self.dump(), before)
        with patch("kiosk.core.credentials.sys.stdin.isatty", return_value=False), patch("kiosk.core.credentials.getpass.getpass") as prompt, redirect_stderr(io.StringIO()):
            self.assertEqual(setup_admin_command(self.app), 1)
            prompt.assert_not_called()
        def unsafe_prompt(*args):
            warnings.warn("unsafe terminal", getpass.GetPassWarning)
        with patch("kiosk.core.credentials.sys.stdin.isatty", return_value=True), patch("kiosk.core.credentials.getpass.getpass", side_effect=unsafe_prompt), redirect_stderr(io.StringIO()):
            self.assertEqual(setup_admin_command(self.app), 1)
        self.assertEqual(self.dump(), before)

    def test_storage_failure_rolls_back_and_sanitizes_errors(self):
        with self.app.app_context():
            database = get_database()
            database.execute("CREATE TRIGGER reject_admin BEFORE INSERT ON users BEGIN SELECT RAISE(ABORT, 'private-secret'); END")
            database.commit()
        before = self.dump()
        with self.assertRaises(RuntimeError) as error:
            self.setup_admin()
        self.assertNotIn("private-secret", str(error.exception))
        self.assertEqual(self.dump(), before)
        with patch("kiosk.core.credentials.sys.stdin.isatty", return_value=True), patch("kiosk.core.credentials.getpass.getpass", side_effect=[self.password] * 2), redirect_stderr(io.StringIO()) as errors, redirect_stdout(io.StringIO()) as output:
            self.assertEqual(setup_admin_command(self.app), 1)
        self.assertNotIn(self.password, errors.getvalue() + output.getvalue())
        self.assertNotIn("private-secret", errors.getvalue())
        self.assertEqual(self.dump(), before)

    def test_reset_command_and_cli_dispatch(self):
        self.setup_admin()
        replacement = "local-replacement-password"
        with patch("kiosk.core.credentials.sys.stdin.isatty", return_value=True), patch("kiosk.core.credentials.getpass.getpass", side_effect=[replacement] * 2), redirect_stdout(io.StringIO()) as output:
            self.assertEqual(reset_admin_password_command(self.app), 0)
        self.assertNotIn(replacement, output.getvalue())
        self.assertEqual(self.login(password=replacement).status_code, 302)
        self.assertTrue(parse_args(["--setup-admin"]).setup_admin)
        with patch("serve.setup_admin_command", return_value=0) as setup, patch("serve.run_waitress_with_launcher") as launch:
            self.assertEqual(main(["--setup-admin"]), 0)
            setup.assert_called_once_with()
            launch.assert_not_called()
        with patch("serve.reset_admin_password_command", return_value=1), patch("serve.run_waitress_with_launcher") as launch:
            self.assertEqual(main(["--reset-admin-password"]), 1)
            launch.assert_not_called()


if __name__ == "__main__":
    unittest.main()
