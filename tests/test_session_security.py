from tests.browser_client import browser_client
import sqlite3
import tempfile
import unittest
from concurrent.futures import ProcessPoolExecutor
from contextlib import closing
from pathlib import Path
from unittest.mock import patch

from kiosk.app import create_app
from kiosk.core.security import load_session_key
from kiosk.core.credentials import save_admin_password
from werkzeug.security import generate_password_hash


class SessionSecurityTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)

    def config(self, name='installation'):
        root = self.root / name
        return {'TESTING': True, 'BASE_DIR': root, 'INSTANCE_DIR': root / 'instance',
                'DATABASE_PATH': root / 'instance/kiosk.sqlite',
                'PRIVATE_UPLOAD_DIR': root / 'instance/uploads',
                'PUBLIC_UPLOAD_DIR': root / 'static/uploads', 'STATIC_FOLDER': root / 'static'}

    def test_key_persistence_and_installation_isolation(self):
        first = load_session_key(self.root / 'first')
        self.assertEqual(len(first), 64)
        self.assertEqual(first, load_session_key(self.root / 'first'))
        self.assertNotEqual(first, load_session_key(self.root / 'second'))

    def test_concurrent_process_initialization(self):
        with ProcessPoolExecutor(max_workers=4) as pool:
            keys = list(pool.map(load_session_key, [self.root] * 12))
        self.assertEqual(len(set(keys)), 1)
        self.assertEqual(list(self.root.iterdir()), [self.root / 'session.key'])

    def test_explicit_key_and_debug_default(self):
        config = self.config()
        app = create_app({**config, 'SECRET_KEY': 'explicit-test-key'})
        self.assertFalse(app.debug)
        self.assertFalse((config['INSTANCE_DIR'] / 'session.key').exists())
        with self.assertRaises(RuntimeError):
            create_app({**config, 'SECRET_KEY': ''})

    def test_invalid_keys_are_preserved_and_errors_are_sanitized(self):
        path = self.root / 'session.key'
        for content in (b'', b'private-invalid-value', b'\xff' * 64, b'a' * 63, b'a' * 65):
            path.write_bytes(content)
            with self.assertRaises(RuntimeError) as caught:
                load_session_key(self.root)
            self.assertNotIn('private-invalid-value', str(caught.exception))
            self.assertEqual(path.read_bytes(), content)

    def test_io_failures_stop_startup(self):
        for target in ('pathlib.Path.read_bytes', 'tempfile.NamedTemporaryFile', 'os.link', 'os.fsync'):
            with self.subTest(target=target), patch(target, side_effect=PermissionError('private-secret')):
                with self.assertRaises(RuntimeError) as caught:
                    load_session_key(self.root / target)
                self.assertNotIn('private-secret', str(caught.exception))
        self.assertFalse((self.root / 'session.key').exists())

    def test_session_survives_restart_and_public_routes(self):
        config = self.config()
        app = create_app(config)
        save_admin_password(app, "session-test-password", setup=True)
        client = browser_client(app)
        statuses = {path: client.get(path).status_code for path in
                    ('/kiosk', '/kiosk/events', '/tv', '/preview', '/admin/login',
                     '/api/version', '/api/events', '/api/tags')}
        self.assertEqual(set(statuses.values()), {200})
        self.assertEqual(client.get('/admin').status_code, 302)
        self.assertEqual(client.post('/admin/login', data={'username': 'admin', 'password': 'session-test-password'}).status_code, 302)
        cookie = client.get_cookie('session')
        restarted = browser_client(create_app(config))
        restarted.set_cookie('session', cookie.value)
        self.assertEqual(restarted.get('/admin').status_code, 200)
        print('Flask routes:', statuses, '/admin: 302 before login, 200 after restart')

    def test_logout_revokes_only_the_logged_out_cookie(self):
        config = self.config('logout')
        app = create_app(config)
        save_admin_password(app, 'logout-test-password', setup=True)
        first = browser_client(app)
        self.assertEqual(first.post('/admin/login', data={'username': 'admin', 'password': 'logout-test-password'}).status_code, 302)
        self.assertEqual(first.get('/admin').status_code, 200)
        logged_out = first.get_cookie('session').value
        second = browser_client(app)
        self.assertEqual(second.post('/admin/login', data={'username': 'admin', 'password': 'logout-test-password'}).status_code, 302)
        self.assertEqual(first.post('/admin/logout').status_code, 302)
        self.assertEqual(first.get('/admin').status_code, 302)
        # A copy of the exact logged-out cookie cannot authenticate again, including
        # after an application restart; only the revoked session id is recorded.
        for index, restarted in enumerate((browser_client(app), browser_client(create_app(config)))):
            with self.subTest(restart=index):
                restarted.set_cookie('session', logged_out)
                self.assertEqual(restarted.get('/admin').status_code, 302)
                self.assertEqual(restarted.get('/admin/events').status_code, 302)
        self.assertEqual(second.get('/admin').status_code, 200)
        self.assertEqual(second.get('/admin/events').status_code, 200)

    def test_capacity_cleanup_never_revives_a_logged_out_cookie(self):
        # A logout must stay effective after the bounded revocation table overflows.
        # Direct module checks use an explicit clock so the ordering is exact; the
        # HTTP-level replay below proves the same behaviour through the real route.
        from flask import session
        from kiosk.core import admin_sessions

        config = self.config('capacity')
        app = create_app(config)
        with app.test_request_context('/admin'):
            admin_sessions.start_session(now=1000)
            logged_out = session[admin_sessions.SESSION_ID_KEY]
            self.assertTrue(admin_sessions.revoke_current_session(now=1000))
            with patch.object(admin_sessions, 'MAX_REVOCATION_ROWS', 8):
                database = admin_sessions.get_database()
                for index in range(20):
                    database.execute(
                        "INSERT INTO revoked_admin_sessions (session_sha256, issued, expires) VALUES (?, ?, ?)",
                        ('%064x' % (index + 1), 2000 + index, 60000 + index))
                admin_sessions.start_session(now=2100)
                newer = session[admin_sessions.SESSION_ID_KEY]
                self.assertTrue(admin_sessions.revoke_current_session(now=2101))
                database.commit()
                self.assertTrue(admin_sessions.session_revoked(logged_out, 1000, now=2102))
                rows = database.execute("SELECT COUNT(*) FROM revoked_admin_sessions").fetchone()[0]
                self.assertEqual(rows, 8)
                cutoff = admin_sessions._cutoff(database)
                self.assertGreaterEqual(cutoff, 1000)
                # A session opened after the retained window stays valid.
                admin_sessions.start_session(now=cutoff + 1)
                fresh = session[admin_sessions.SESSION_ID_KEY]
                self.assertFalse(admin_sessions.session_revoked(fresh, cutoff + 1, now=cutoff + 2))

    def test_expired_sign_in_and_legacy_cookie_are_refused(self):
        from flask import session
        from kiosk.core import admin_sessions

        config = self.config('expiry')
        app = create_app(config)
        with app.test_request_context('/admin'):
            admin_sessions.start_session(now=1000)
            value, issued = session[admin_sessions.SESSION_ID_KEY], session[admin_sessions.SESSION_ISSUED_KEY]
            self.assertFalse(admin_sessions.session_revoked(value, issued, now=issued + 10))
            self.assertTrue(admin_sessions.session_revoked(
                value, issued, now=issued + admin_sessions.SESSION_LIFETIME_SECONDS))
            self.assertTrue(admin_sessions.session_revoked(value, None, now=issued + 10))
            self.assertTrue(admin_sessions.session_revoked(value, issued, now=issued - 3600))
            self.assertTrue(admin_sessions.session_revoked('x' * 63, issued, now=issued + 10))
            self.assertTrue(admin_sessions.session_revoked('x' * 64 + 'z', issued, now=issued + 10))

    def test_unreadable_capacity_cutoff_fails_closed_and_can_be_reset(self):
        from flask import session
        from kiosk.core import admin_sessions

        config = self.config('cutoff')
        app = create_app(config)
        with app.test_request_context('/admin'):
            admin_sessions.start_session(now=1000)
            value, issued = session[admin_sessions.SESSION_ID_KEY], session[admin_sessions.SESSION_ISSUED_KEY]
            database = admin_sessions.get_database()
            database.execute(
                "INSERT OR REPLACE INTO settings (key, value, updated_at) VALUES (?, ?, ?)",
                (admin_sessions.CUTOFF_KEY, 'not-a-number', 'x'))
            database.commit()
            # A damaged cutoff must not silently revive evicted sessions.
            self.assertTrue(admin_sessions.session_revoked(value, issued, now=issued + 1))
            # Documented recovery: remove the key, then sign in again.
            database.execute("DELETE FROM settings WHERE key = ?", (admin_sessions.CUTOFF_KEY,))
            database.commit()
            self.assertFalse(admin_sessions.session_revoked(value, issued, now=issued + 1))

    def test_http_replay_after_expiry_boundary_and_refresh(self):
        config = self.config('refresh')
        app = create_app(config)
        save_admin_password(app, 'refresh-test-password', setup=True)
        client = browser_client(app)
        self.assertEqual(client.post('/admin/login', data={
            'username': 'admin', 'password': 'refresh-test-password'}).status_code, 302)
        original = client.get_cookie('session').value
        # A CSRF token is created on first use, which re-signs the cookie with a
        # new timestamp and therefore must not move the sign-in time.
        self.assertEqual(client.get('/admin').status_code, 200)
        refreshed = client.get_cookie('session').value
        self.assertNotEqual(original, refreshed)
        self.assertEqual(client.post('/admin/logout').status_code, 302)
        for index, cookie in enumerate((original, refreshed)):
            with self.subTest(cookie=index):
                replay = browser_client(app)
                replay.set_cookie('session', cookie)
                self.assertEqual(replay.get('/admin').status_code, 302)

    def test_password_change_invalidates_other_administrator_sessions(self):
        config = self.config('password-change')
        app = create_app(config)
        save_admin_password(app, 'first-test-password', setup=True)
        first = browser_client(app)
        second = browser_client(app)
        self.assertEqual(first.post('/admin/login', data={
            'username': 'admin', 'password': 'first-test-password'}).status_code, 302)
        self.assertEqual(second.post('/admin/login', data={
            'username': 'admin', 'password': 'first-test-password'}).status_code, 302)
        self.assertEqual(first.get('/admin/password/change').status_code, 200)
        response = first.post('/admin/password/change', data={
            'current_password': 'first-test-password', 'new_password': 'second-test-password',
            'confirm_password': 'second-test-password'})
        self.assertEqual(response.status_code, 302)
        self.assertEqual(second.get('/admin').status_code, 302)
        self.assertEqual(first.get('/admin').status_code, 302)

    def test_existing_database_gains_the_revocation_sign_in_column(self):
        config = self.config('legacy-schema')
        config['INSTANCE_DIR'].mkdir(parents=True)
        with closing(sqlite3.connect(config['DATABASE_PATH'])) as database:
            database.executescript(
                "CREATE TABLE revoked_admin_sessions (session_sha256 TEXT PRIMARY KEY, expires INTEGER NOT NULL);"
                "INSERT INTO revoked_admin_sessions VALUES ('" + 'a' * 64 + "', 9999999999);")
        create_app(config)
        with closing(sqlite3.connect(config['DATABASE_PATH'])) as database:
            columns = {row[1] for row in database.execute("PRAGMA table_info(revoked_admin_sessions)")}
            self.assertIn('issued', columns)
            self.assertEqual(database.execute("SELECT COUNT(*) FROM revoked_admin_sessions").fetchone()[0], 1)

    def test_logout_requires_csrf_and_keeps_the_session(self):
        config = self.config('logout-csrf')
        app = create_app(config)
        save_admin_password(app, 'logout-test-password', setup=True)
        client = browser_client(app)
        self.assertEqual(client.post('/admin/login', data={'username': 'admin', 'password': 'logout-test-password'}).status_code, 302)
        from flask.testing import FlaskClient

        plain = FlaskClient(app)
        plain.set_cookie('session', client.get_cookie('session').value)
        self.assertEqual(plain.post('/admin/logout').status_code, 403)
        self.assertEqual(client.get('/admin').status_code, 200)


    def test_mvp_database_copy_is_unchanged(self):
        source = self.config('mvp')
        create_app({**source, 'SECRET_KEY': 'dev'})
        with closing(sqlite3.connect(source['DATABASE_PATH'])) as database:
            database.execute("INSERT INTO users (username, password_hash, created_at, updated_at) VALUES (?, ?, 'old', 'old')", ('admin', generate_password_hash('admin')))
            database.execute("INSERT INTO events (title, image_original, image_kiosk, image_tv, image_thumb, created_at, updated_at) VALUES ('Preserved', 'instance/uploads/original.png', '/static/uploads/kiosk.jpg', '/static/uploads/tv.jpg', '/static/uploads/thumb.jpg', 'old', 'old')")
            database.execute("INSERT INTO tags (name, created_at, updated_at) VALUES ('Preserved tag', 'old', 'old')")
            database.execute('INSERT INTO event_tags VALUES (1, 1)')
            database.commit()
            before = list(database.iterdump())
            destination = self.config('upgraded')
            destination['INSTANCE_DIR'].mkdir(parents=True)
            with closing(sqlite3.connect(destination['DATABASE_PATH'])) as copied:
                database.backup(copied)
        create_app(destination)
        with closing(sqlite3.connect(destination['DATABASE_PATH'])) as database:
            self.assertEqual(before, list(database.iterdump()))


if __name__ == '__main__':
    unittest.main()
