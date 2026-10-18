import sqlite3
import tempfile
import unittest
from concurrent.futures import ProcessPoolExecutor
from contextlib import closing
from pathlib import Path
from unittest.mock import patch

from kiosk.app import create_app
from kiosk.core.security import load_session_key


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
        client = app.test_client()
        statuses = {path: client.get(path).status_code for path in
                    ('/kiosk', '/kiosk/events', '/tv', '/preview', '/admin/login',
                     '/api/version', '/api/events', '/api/tags')}
        self.assertEqual(set(statuses.values()), {200})
        self.assertEqual(client.get('/admin').status_code, 302)
        self.assertEqual(client.post('/admin/login', data={'username': 'admin', 'password': 'admin'}).status_code, 302)
        cookie = client.get_cookie('session')
        restarted = create_app(config).test_client()
        restarted.set_cookie('session', cookie.value)
        self.assertEqual(restarted.get('/admin').status_code, 200)
        print('Flask routes:', statuses, '/admin: 302 before login, 200 after restart')

    def test_mvp_database_copy_is_unchanged(self):
        source = self.config('mvp')
        create_app({**source, 'SECRET_KEY': 'dev'})
        with closing(sqlite3.connect(source['DATABASE_PATH'])) as database:
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
