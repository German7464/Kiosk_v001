"""Smartphone pairing: server lookup/decision flow, QR contract and Windows UI."""
import io
import json
import re
import secrets
import tempfile
import unittest
from pathlib import Path

from PIL import Image

from kiosk.database import get_database
from kiosk.delivery.protocol import PROFILE, encode, sha
from kiosk.display.qr_pairing import pairing_url, qr_image, qr_png_bytes
from tests import test_operator_delivery as fixtures
from tests.qr_decode import decode_qr_image


class PairingServerTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.app = fixtures.fixture_app(self.root)
        self.state = self.app.extensions['device_delivery']
        self.now = 1_800_000_000
        self.state.clock = lambda: self.now
        self.client = fixtures.admin_client(self.app)
        self.origin = 'https://localhost'
        self.csrf = 'a' * 64

    def pending(self, device='device-one'):
        secret = secrets.token_hex(32)
        binding = {'version': 1, 'request_id': secrets.token_hex(16), 'device_id': device,
                   'group_id': 'operator-fixture', 'profile': PROFILE,
                   'origin': 'https://localhost:18443', 'nonce': secrets.token_hex(16),
                   'secret_verifier': sha(bytes.fromhex(secret))}
        pending = self.state.begin(binding)
        return binding, pending, secret

    def lookup(self, code, client=None, base_url=None, csrf='a' * 64):
        client = client or self.client
        response = client.post('/admin/devices/pair/lookup', json={'code': code},
                               base_url=base_url or self.origin,
                               headers={'X-CSRF-Token': csrf})
        return response

    def test_pair_page_shell_and_lookup_never_approve(self):
        binding, pending, secret = self.pending()
        # The entry shell is reachable without a session (a phone scans it first).
        shell = self.app.test_client().get('/admin/devices/pair', base_url=self.origin)
        self.assertEqual(shell.status_code, 200)
        self.assertIn(b'id="pair-form"', shell.data)
        # Fragment is browser-local; GET does not approve.
        self.assertEqual(self.state.pending()[0]['state'], 'pending')
        # Lookup is read-only and does not change state.
        self.assertEqual(self.lookup(pending['user_code']).status_code, 200)
        self.assertEqual(self.state.pending()[0]['state'], 'pending')

    def test_lookup_returns_exact_facts_without_secrets(self):
        binding, pending, secret = self.pending()
        response = self.lookup(pending['user_code'])
        self.assertEqual(response.status_code, 200)
        review = response.get_json()['review']
        self.assertEqual(review['request_id'], binding['request_id'])
        self.assertEqual(review['binding_sha256'], sha(encode(binding)))
        self.assertEqual(review['device_id'], binding['device_id'])
        self.assertEqual(review['group_id'], 'operator-fixture')
        self.assertEqual(review['server_id'], 'operator-server')
        self.assertEqual(review['origin'], 'https://localhost:18443')
        self.assertEqual(review['profile'], PROFILE)
        self.assertEqual(review['state'], 'pending')
        body = response.get_data(as_text=True)
        for secret_value in (secret, binding['secret_verifier'], pending['device_code'],
                             pending['user_code'], 'secret_verifier', 'device_code'):
            self.assertNotIn(secret_value, body)

    def test_lookup_bounds_input_and_distinguishes_unknown_expired(self):
        binding, pending, secret = self.pending()
        for code in ('', 'ABC', 'Я' * 8, '0' * 8, 'a' * 8, 'ABC' + '0' * 5):
            response = self.lookup(code)
            self.assertEqual(response.status_code, 400, code)
            self.assertEqual(response.get_json()['error'], 'invalid_user_code')
        self.assertEqual(self.lookup('ZZZZZZZZ').status_code, 404)  # unknown valid-format code
        self.now += 601
        self.assertEqual(self.lookup(pending['user_code']).status_code, 410)  # expired
        self.assertEqual(self.lookup(pending['user_code']).get_json()['error'], 'enrollment_expired')

    def test_pair_page_localizes_messages_and_offers_cancel(self):
        shell = self.app.test_client().get('/admin/devices/pair', base_url=self.origin)
        self.assertEqual(shell.status_code, 200)
        page = shell.get_data(as_text=True)
        self.assertIn('id="pair-messages"', page)
        self.assertIn('id="pair-cancel"', page)
        self.assertIn('id="pair-decisions"', page)
        self.assertIn('Cancel and start over', page)
        with self.app.app_context():
            database = get_database()
            database.execute("UPDATE settings SET value='ru' WHERE key='interface_language'")
            database.commit()
        russian = self.app.test_client().get('/admin/devices/pair', base_url=self.origin).get_data(as_text=True)
        self.assertIn('Отменить и начать заново', russian)
        payload = re.search(r'<script type="application/json" id="pair-messages">(.*?)</script>', russian, re.S)[1]
        messages = json.loads(payload)
        self.assertEqual(messages['checking'], 'Проверка кода…')  # JS message uses selected language.
        self.assertEqual(messages['network_error'][:10], 'Сервер нед')
        with self.app.app_context():
            database = get_database()
            database.execute("UPDATE settings SET value='en' WHERE key='interface_language'")
            database.commit()

    def test_lookup_requires_session_https_csrf_and_json(self):
        binding, pending, secret = self.pending()
        guest = self.app.test_client()
        # Establish a session (and CSRF token) exactly like a scanned phone does,
        # then an unauthenticated lookup is redirected to the login page.
        shell = guest.get('/admin/devices/pair', base_url=self.origin)
        token = re.search(rb'name="csrf-token" content="([^"]+)"', shell.data)[1].decode()
        response = guest.post('/admin/devices/pair/lookup', json={'code': pending['user_code']},
                              base_url=self.origin, headers={'X-CSRF-Token': token})
        self.assertEqual(response.status_code, 302)
        self.assertIn('/admin/login', response.headers['Location'])
        # Wrong CSRF: refused.
        self.assertEqual(self.lookup(pending['user_code'], csrf='b' * 64).status_code, 403)
        # Plain HTTP: https_required.
        self.assertEqual(self.lookup(pending['user_code'], base_url='http://localhost').status_code, 403)
        # Non-JSON body: json_required.
        response = self.client.post('/admin/devices/pair/lookup',
                                    data='code=' + pending['user_code'],
                                    base_url=self.origin, headers={'X-CSRF-Token': self.csrf})
        self.assertEqual(response.status_code, 415)

    def test_prelookup_rate_limit_is_bounded(self):
        binding, pending, secret = self.pending()
        limiter = self.app.extensions['pair_lookup_limiter']
        limiter.account_limit = 3
        limiter.source_limit = 30
        for _ in range(3):
            self.assertEqual(self.lookup('ZZZZZZZZ').status_code, 404)
        response = self.lookup(pending['user_code'])
        self.assertEqual(response.status_code, 429)
        self.assertEqual(response.get_json()['error'], 'code_lookup_limit')

    def test_pair_flow_approve_and_deny_reuse_existing_decision(self):
        binding, pending, secret = self.pending()
        review = self.lookup(pending['user_code']).get_json()['review']
        approve = {'user_code': pending['user_code'], 'binding_sha256': review['binding_sha256'],
                   'decision': 'approve'}
        response = self.client.post('/admin/devices/' + binding['request_id'] + '/decision',
                                    json=approve, base_url=self.origin,
                                    headers={'X-CSRF-Token': self.csrf})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()['state'], 'approved')
        self.assertEqual(self.state.authenticate(secret)['revoked'], 0)
        # Idempotent re-approve stays approved; conflicting decision is refused.
        self.assertEqual(self.client.post('/admin/devices/' + binding['request_id'] + '/decision',
                         json=approve, base_url=self.origin, headers={'X-CSRF-Token': self.csrf}).status_code, 200)
        self.assertEqual(self.client.post('/admin/devices/' + binding['request_id'] + '/decision',
                         json={**approve, 'decision': 'deny'}, base_url=self.origin,
                         headers={'X-CSRF-Token': self.csrf}).status_code, 409)
        other, other_pending, other_secret = self.pending('denied-device')
        other_review = self.lookup(other_pending['user_code']).get_json()['review']
        deny = {'user_code': other_pending['user_code'], 'binding_sha256': other_review['binding_sha256'],
                'decision': 'deny'}
        self.assertEqual(self.client.post('/admin/devices/' + other['request_id'] + '/decision',
                         json=deny, base_url=self.origin, headers={'X-CSRF-Token': self.csrf}).status_code, 200)
        with self.assertRaisesRegex(Exception, 'enrollment_denied'):
            self.state.poll({'device_code': other_pending['device_code']})

    def test_login_next_pair_is_fixed_and_not_open_redirect(self):
        def login(next_value):
            client = self.app.test_client()
            path = '/admin/login' + (('?next=' + next_value) if next_value else '')
            page = client.get(path, base_url=self.origin)
            token = re.search(rb'name="csrf_token" value="([^"]+)"', page.data)[1].decode()
            return client.post('/admin/login', data={'csrf_token': token, 'username': 'admin',
                                                     'password': 'disposable-operator-password',
                                                     'next': next_value or ''}, base_url=self.origin)
        self.assertTrue(login('pair').headers['Location'].endswith('/admin/devices/pair'))
        self.assertTrue(login(None).headers['Location'].endswith('/admin'))
        for hostile in ('https://evil.example', 'pair//evil', 'devices', 'pair/'):
            location = login(hostile).headers['Location']
            self.assertFalse('evil' in location)
            self.assertNotIn(hostile, location)
        self.assertTrue(login('pair').headers['Location'].endswith('/admin/devices/pair'))


class PairingQrTests(unittest.TestCase):
    def test_pairing_url_is_the_exact_contract(self):
        self.assertEqual(pairing_url('https://localhost:18443', 'ABCDEFGH'),
                         'https://localhost:18443/admin/devices/pair#v=1&code=ABCDEFGH')
        # Trailing slash is normalized; the fragment keeps the code out of the query.
        self.assertEqual(pairing_url('https://localhost:18443/', '23456789'),
                         'https://localhost:18443/admin/devices/pair#v=1&code=23456789')
        self.assertNotIn('?', pairing_url('https://localhost:18443', 'ABCDEFGH'))

    def test_qr_carries_only_origin_and_code(self):
        origin = 'https://192.0.2.10:8443'
        code = 'ABCDEFGH'
        url = pairing_url(origin, code)
        self.assertEqual(url, origin + '/admin/devices/pair#v=1&code=' + code)
        for secret in ('device_code', 'Bearer ', 'PRIVATE', 'credential', 'secret'):
            self.assertNotIn(secret.lower(), url.lower())

    def test_generated_qr_decodes_to_exact_contract(self):
        origin = 'https://localhost:18443'
        code = 'KQ7WMN4X'
        url = pairing_url(origin, code)
        png = qr_png_bytes(url)
        self.assertTrue(png.startswith(b'\x89PNG'))
        image = Image.open(io.BytesIO(png))
        self.assertEqual(image.mode, 'RGB')
        # An independent decoder (no Nayuki import) recovers the exact URL.
        self.assertEqual(decode_qr_image(image, scale=8, border=4), url)

    def test_qr_renders_quiet_zone_and_rejects_wrong_origin_shape(self):
        # Quiet zone is all light: the four outer module rows/columns are white.
        url = pairing_url('https://localhost:18443', 'ABCDEFGH')
        image = qr_image(url)
        size = image.size[0]
        scale = 8
        for x in range(size):
            for y in range(0, 4 * scale):
                self.assertEqual(image.getpixel((x, y))[0], 255)
        # The generated URL always starts with the configured origin, never a foreign one.
        self.assertTrue(pairing_url('https://localhost:18443', 'ABCDEFGH').startswith('https://localhost:18443'))


class PairingConnectUiTests(unittest.TestCase):
    def test_window_show_and_clear_qr(self):
        import tkinter as tk
        from kiosk.display.connect_ui import Window
        import queue
        from unittest.mock import Mock
        connection = Mock()
        connection.events = queue.Queue()
        connection.busy = False
        root = tk.Tk()
        root.withdraw()
        try:
            window = Window(root, connection)
            window.show_qr('https://localhost:18443', 'ABCDEFGH')
            self.assertIsNotNone(window.qr_photo)
            window.clear_qr()
            self.assertIsNone(window.qr_photo)
            # An empty or malformed code leaves no QR.
            window.show_qr('https://localhost:18443', 'SHORT')
            self.assertIsNone(window.qr_photo)
            window.show_qr('', 'ABCDEFGH')
            self.assertIsNone(window.qr_photo)
        finally:
            try:
                root.destroy()
            except tk.TclError:
                pass

    def test_window_replaces_qr_and_clears_on_terminal_state(self):
        import queue
        import tkinter as tk
        from unittest.mock import Mock
        from kiosk.display.connect_ui import Window

        connection = Mock()
        connection.events = queue.Queue()
        connection.busy = False
        root = tk.Tk()
        root.withdraw()
        try:
            window = Window(root, connection)
            window.show_qr('https://localhost:18443', 'ABCDEFGH')
            first = window.qr_photo
            self.assertIsNotNone(first)
            window.show_qr('https://localhost:18443', '23456789')
            second = window.qr_photo
            self.assertIsNotNone(second)
            self.assertIsNot(first, second)  # A new pending code replaces the old QR.
            connection.events.put({'state': 'approved', 'code': '23456789',
                                   'origin': 'https://localhost:18443', 'device': 'd'})
            window.tick()
            self.assertIsNone(window.qr_photo)
            self.assertEqual(window.code.get(), '—')
            connection.events.put({'state': 'pending', 'code': '23456789',
                                   'origin': 'https://localhost:18443', 'device': 'd'})
            window.tick()
            self.assertIsNotNone(window.qr_photo)
            connection.events.put({'state': 'cancelled'})
            window.tick()
            self.assertIsNone(window.qr_photo)
        finally:
            try:
                root.destroy()
            except tk.TclError:
                pass

    def test_persistent_events_redact_active_code(self):
        import tkinter as tk
        from kiosk.display.connect_ui import Window
        import queue
        from unittest.mock import Mock
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        events = Path(temp.name) / 'events.jsonl'
        connection = Mock()
        connection.events = queue.Queue()
        connection.busy = False
        root = tk.Tk()
        root.withdraw()
        try:
            window = Window(root, connection, events=events)
            connection.events.put({'state': 'pending', 'code': 'ABCDEFGH',
                                   'origin': 'https://localhost:18443', 'device': 'd'})
            window.tick()
        finally:
            try:
                root.destroy()
            except tk.TclError:
                pass
        content = events.read_text(encoding='utf-8')
        self.assertIn('"state": "pending"', content)
        self.assertIn('https://localhost:18443', content)
        self.assertNotIn('ABCDEFGH', content)
        self.assertNotIn('"code"', content)


if __name__ == '__main__':
    unittest.main()
