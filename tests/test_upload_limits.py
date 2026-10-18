import io
import sqlite3
import tempfile
import threading
import unittest
import urllib.request
import urllib.error
from contextlib import closing
from pathlib import Path
from unittest.mock import patch

from PIL import Image
from waitress import create_server
from werkzeug.datastructures import FileStorage
from werkzeug.exceptions import RequestEntityTooLarge
from flask.testing import FlaskClient

from kiosk.app import create_app
from kiosk.core.credentials import save_admin_password
from kiosk.core.images import process_event_image
from kiosk.server import run_waitress, run_waitress_with_launcher
from tests.browser_client import browser_client


class UploadLimitTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.config = {'TESTING': True, 'SECRET_KEY': 'upload-test', 'BASE_DIR': self.root, 'INSTANCE_DIR': self.root / 'instance', 'DATABASE_PATH': self.root / 'instance/db.sqlite', 'PRIVATE_UPLOAD_DIR': self.root / 'instance/uploads', 'PUBLIC_UPLOAD_DIR': self.root / 'static/uploads', 'STATIC_FOLDER': self.root / 'static'}
        self.app = create_app(self.config)
        save_admin_password(self.app, 'upload-test-password', setup=True)
        self.client = browser_client(self.app)
        self.assertEqual(self.client.post('/admin/login', data={'username': 'admin', 'password': 'upload-test-password'}).status_code, 302)

    def png(self, size=(10, 10)):
        output = io.BytesIO()
        Image.new('RGB', size, 'blue').save(output, 'PNG')
        return output.getvalue()

    def snapshot(self):
        with closing(sqlite3.connect(self.config['DATABASE_PATH'])) as database:
            dump = list(database.iterdump())
        files = {str(p.relative_to(self.root)): p.read_bytes() for directory in ('instance/uploads', 'static/uploads') for p in (self.root / directory).rglob('*') if p.is_file()}
        return dump, files

    def upload(self, data, path='/admin/events/create'):
        field = 'site_icon' if path == '/admin/settings' else 'event_image'
        return self.client.post(path, data={'title': 'Test', field: (io.BytesIO(data), 'photo.png')})

    def test_file_and_pixel_boundaries_and_preservation(self):
        data = self.png()
        self.app.config.update(MAX_UPLOAD_FILE_BYTES=len(data), MAX_IMAGE_PIXELS=100)
        self.assertEqual(self.upload(data).status_code, 302)
        before = self.snapshot()
        for path in ('/admin/events/create', '/admin/events/1/edit', '/admin/settings'):
            self.app.config['MAX_UPLOAD_FILE_BYTES'] = len(data)-1
            self.assertEqual(self.upload(data, path).status_code, 413)
            self.app.config['MAX_UPLOAD_FILE_BYTES'] = len(data)
            self.app.config['MAX_IMAGE_PIXELS'] = 99
            self.assertEqual(self.upload(data, path).status_code, 413)
            self.app.config['MAX_IMAGE_PIXELS'] = 100
            self.assertEqual(self.upload(b'broken', path).status_code, 400)
            self.assertEqual(self.snapshot(), before)
        self.assertEqual(self.upload(data, '/admin/events/1/edit').status_code, 302)
        self.assertEqual(self.upload(data, '/admin/settings').status_code, 302)

    def test_partial_output_cleanup(self):
        before = self.snapshot()
        def fail(source, target, size):
            target.write_bytes(b'partial')
            raise OSError('simulated disk failure')
        with patch('kiosk.core.images.save_optimized_image', side_effect=fail):
            with self.assertRaises(OSError):
                self.upload(self.png())
        self.assertEqual(self.snapshot(), before)

    def test_request_and_field_exact_boundaries(self):
        token = self.client.get('/kiosk').get_data(as_text=True).split('name="csrf-token" content="')[1].split('"')[0]
        raw = FlaskClient(self.app)
        with self.client.session_transaction() as source, raw.session_transaction() as target:
            target.update(source)
        self.app.config['MAX_CONTENT_LENGTH'] = 64
        self.assertEqual(raw.post('/admin/fullscreen/validate', data=b' '*64, content_type='application/json', headers={'X-CSRF-Token': token}).status_code, 400)
        self.assertEqual(raw.post('/admin/fullscreen/validate', data=b' '*65, content_type='application/json', headers={'X-CSRF-Token': token}).status_code, 413)
        self.app.config['MAX_CONTENT_LENGTH'] = 20000
        self.app.config['MAX_FORM_MEMORY_SIZE'] = 256
        self.assertEqual(self.client.post('/admin/tags/create', data={'name': 'x'*256}).status_code, 302)
        before = self.snapshot()
        self.assertEqual(self.client.post('/admin/tags/create', data={'name': 'x'*257}).status_code, 413)
        self.assertEqual(self.snapshot(), before)

    def test_icon_partial_output_and_truncated_decode_cleanup(self):
        self.assertEqual(self.upload(self.png(), '/admin/settings').status_code, 302)
        before = self.snapshot()
        def fail(source, target):
            target.write_bytes(b'partial icon')
            raise OSError('simulated icon failure')
        with patch('kiosk.core.images.save_optimized_icon', side_effect=fail):
            with self.assertRaises(OSError):
                self.upload(self.png(), '/admin/settings')
        self.assertEqual(self.snapshot(), before)
        data = self.png((100, 100))
        self.assertEqual(self.upload(data[:len(data)//2]).status_code, 400)
        self.assertEqual(self.snapshot(), before)

    def test_actual_stream_size_ignores_declared_length(self):
        before = self.snapshot()
        self.app.config['MAX_UPLOAD_FILE_BYTES'] = 4
        with self.app.app_context():
            with self.assertRaises(RequestEntityTooLarge):
                process_event_image(FileStorage(stream=io.BytesIO(b'12345'), filename='fake.png', content_length=1))
        self.assertEqual(self.snapshot(), before)

    def test_body_form_limits_and_json_error(self):
        self.app.config['MAX_CONTENT_LENGTH'] = 128
        before = self.snapshot()
        self.assertEqual(self.client.post('/admin/fullscreen/validate', json={'padding': 'x'*200}).status_code, 413)
        self.assertFalse(self.client.post('/admin/fullscreen/validate', json={'padding': 'x'*200}).json['success'])
        self.app.config['MAX_CONTENT_LENGTH'] = 20000
        self.app.config['MAX_FORM_PARTS'] = 2
        self.assertEqual(self.upload(self.png()).status_code, 302)
        before = self.snapshot()
        self.app.config['MAX_FORM_PARTS'] = 1
        self.assertEqual(self.upload(self.png()).status_code, 413)
        self.app.config['MAX_FORM_PARTS'] = 100
        self.app.config['MAX_FORM_MEMORY_SIZE'] = 256
        self.assertEqual(self.client.post('/admin/tags/create', data={'name': 'x'*257}).status_code, 413)
        self.assertEqual(self.snapshot(), before)

    def test_configuration_and_server_entrypoints(self):
        for name in ('MAX_CONTENT_LENGTH', 'MAX_UPLOAD_FILE_BYTES', 'MAX_IMAGE_PIXELS', 'MAX_FORM_MEMORY_SIZE', 'MAX_FORM_PARTS'):
            for invalid in (0, -1, None, True):
                with self.assertRaisesRegex(ValueError, name):
                    create_app({**self.config, name: invalid})
        with patch('kiosk.server.create_app', return_value=self.app), patch('kiosk.server.serve') as serve, patch('kiosk.server.local_server_is_ready', return_value=False), patch('kiosk.server.wait_for_local_server', return_value=True):
            run_waitress(host='127.0.0.1', port=5000)
            self.assertEqual(serve.call_args.kwargs['max_request_body_size'], 20*1024*1024)
            run_waitress_with_launcher(host='127.0.0.1', port=5000, auto_launch=False)
            self.assertEqual(serve.call_count, 2)
            self.assertEqual(serve.call_args.kwargs['max_request_body_size'], 20*1024*1024)

    def test_waitress_http_body_rejection(self):
        server = create_server(self.app, host='127.0.0.1', port=0, max_request_body_size=256)
        thread = threading.Thread(target=server.run, daemon=True)
        thread.start()
        try:
            base = f'http://127.0.0.1:{server.effective_port}'
            with urllib.request.urlopen(base+'/api/version', timeout=5) as response:
                self.assertEqual(response.status, 200)
            before = self.snapshot()
            with self.assertRaises(urllib.error.HTTPError) as error:
                urllib.request.urlopen(urllib.request.Request(base+'/admin/events/create', data=b'x'*257), timeout=5)
            self.assertEqual(error.exception.code, 413)
            error.exception.close()
            self.assertEqual(self.snapshot(), before)
        finally:
            server.close()
            thread.join(timeout=3)
