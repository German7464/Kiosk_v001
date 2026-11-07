"""Device administration, using disposable roots and the real session/CSRF path."""
from contextlib import closing
import json
from pathlib import Path
import secrets
import sqlite3
import tempfile
import unittest

from kiosk.delivery.operator import distribution, publish_current_events
from kiosk.delivery.protocol import DeliveryError, PROFILE, encode, sha
from tests import test_operator_delivery as fixtures


class DeviceAdminTests(unittest.TestCase):
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

    def pending(self, device='device-one'):
        secret = secrets.token_hex(32)
        binding = {'version': 1, 'request_id': secrets.token_hex(16), 'device_id': device,
                   'group_id': 'operator-fixture', 'profile': PROFILE,
                   'origin': 'https://localhost:18443', 'nonce': secrets.token_hex(16),
                   'secret_verifier': sha(bytes.fromhex(secret))}
        result = self.state.begin(binding)
        form = {'csrf_token': 'a' * 64, 'user_code': result['user_code'],
                'binding_sha256': sha(encode(binding)), 'decision': 'approve'}
        return binding, result, form, secret

    def review(self, binding, form, client=None, json_route=False, **extra):
        client = client or self.client
        path = '/admin/devices/' + binding['request_id']
        if json_route:
            payload = {key: value for key, value in form.items() if key != 'csrf_token'}
            return client.post(path + '/decision', json=payload, base_url=self.origin,
                               headers={'X-CSRF-Token': form.get('csrf_token', '')}, **extra)
        return client.post(path + '/review', data=form, base_url=self.origin, **extra)

    def revoke(self, device, **changes):
        row = next(item for item in self.state.admin_devices()['devices'] if item['device_id'] == device)
        form = {'csrf_token': 'a' * 64, 'confirm_device_id': device, 'review_hash': row['review_hash'], **changes}
        return self.client.post('/admin/devices/' + device + '/confirm-revoke', data=form, base_url=self.origin)

    def test_admin_session_https_csrf_and_native_bearer_not_authority(self):
        binding, pending, form, secret = self.pending()
        guest = self.app.test_client()
        for headers in ({}, {'Authorization': 'Bearer ' + secret}):
            self.assertEqual(guest.get('/admin/devices', base_url=self.origin, headers=headers).status_code, 302)
            self.assertEqual(self.review(binding, form, guest, headers=headers).status_code, 403)
        self.assertEqual(self.client.get('/admin/devices').status_code, 403)
        self.assertEqual(self.client.get('/admin/devices', base_url=self.origin).status_code, 200)
        self.assertEqual(self.review(binding, {**form, 'csrf_token': ''}).status_code, 403)
        self.assertEqual(self.client.post('/admin/devices/device-one/confirm-revoke', base_url=self.origin).status_code, 403)
        self.assertEqual(self.state.pending()[0]['state'], 'pending')

    def test_view_manual_code_exact_facts_no_secrets_and_navigation(self):
        binding, pending, form, secret = self.pending()
        page = self.client.get('/admin/devices', base_url=self.origin)
        self.assertEqual(page.status_code, 200)
        self.assertEqual(page.headers['Cache-Control'], 'no-store')
        for value in (binding['request_id'], binding['device_id'], binding['nonce'], binding['origin'],
                      'operator-server', PROFILE, form['binding_sha256']):
            self.assertIn(value.encode(), page.data)
        for value in (secret, binding['secret_verifier'], pending['device_code'], pending['user_code'], 'secret_verifier'):
            self.assertNotIn(value.encode(), page.data)
        self.assertIn(b'name="user_code" required', page.data)
        self.assertNotIn(b'name="user_code" value=', page.data)
        model = json.dumps(self.state.admin_devices())
        for value in (secret, binding['secret_verifier'], pending['device_code'], pending['user_code']):
            self.assertNotIn(value, model)
        self.assertIn(b'/admin/devices', self.client.get('/admin', base_url=self.origin).data)

    def test_missing_malformed_wrong_code_and_binding_refused(self):
        binding, pending, form, secret = self.pending()
        for change, expected in (({'user_code': ''}, 400), ({'user_code': 'Я' * 8}, 400),
                                 ({'user_code': 'AAAAAAAA' if pending['user_code'] != 'AAAAAAAA' else 'BBBBBBBB'}, 403),
                                 ({'binding_sha256': '0' * 64}, 403)):
            self.assertEqual(self.review(binding, {**form, **change}).status_code, expected)
        self.assertEqual(self.state.pending()[0]['state'], 'pending')
        self.assertEqual(self.review(binding, form).status_code, 303)

    def test_code_attempt_limit_shared_with_existing_json_route_and_other_requests(self):
        binding, pending, form, secret = self.pending()
        wrong = {**form, 'user_code': 'AAAAAAAA' if pending['user_code'] != 'AAAAAAAA' else 'BBBBBBBB'}
        for index in range(5):
            self.assertEqual(self.review(binding, wrong, json_route=index % 2 == 0).status_code, 403)
        for json_route in (False, True):
            response = self.review(binding, form, json_route=json_route)
            self.assertEqual(response.status_code, 429)
            self.assertIn('Retry-After', response.headers)
        # A second logged-in session still shares the source/request budget.
        self.assertEqual(self.review(binding, form, fixtures.admin_client(self.app)).status_code, 429)
        self.assertEqual(self.state.pending()[0]['state'], 'pending')

    def test_source_limit_prevents_request_id_rotation_bypass(self):
        for index in range(20):
            binding, pending, form, secret = self.pending('other-' + str(index))
            self.assertEqual(self.review(binding, {**form, 'user_code': ''}).status_code, 400)
        binding, pending, form, secret = self.pending('last')
        self.assertEqual(self.review(binding, form, json_route=True).status_code, 429)

    def test_expired_missing_and_changed_server_binding_are_refused(self):
        binding, pending, form, secret = self.pending()
        self.now += 601
        self.assertEqual(self.review(binding, form).status_code, 410)
        self.assertEqual(self.review({**binding, 'request_id': 'absent'}, form).status_code, 410)
        self.now -= 601
        config = self.state.configuration()
        (self.state.root / 'public.json').write_bytes(encode({**config, 'origin': 'https://elsewhere:18443'}))
        self.assertEqual(self.review(binding, form).status_code, 403)
        with self.state.connection() as db:
            self.assertEqual(db.execute('SELECT count(*) FROM devices').fetchone()[0], 0)

    def test_approve_retry_conflict_and_denial_retry(self):
        binding, pending, form, secret = self.pending()
        self.assertEqual(self.review(binding, form).status_code, 303)
        first = self.state.authenticate(secret)
        self.assertEqual(self.review(binding, form, json_route=True).status_code, 200)
        self.assertEqual(self.state.authenticate(secret)['credential_id'], first['credential_id'])
        self.assertEqual(self.review(binding, {**form, 'decision': 'deny'}).status_code, 409)
        other, pending, denial, secret = self.pending('denied-device')
        denial['decision'] = 'deny'
        self.assertEqual(self.review(other, denial).status_code, 303)
        self.assertEqual(self.review(other, denial, json_route=True).status_code, 200)
        self.assertEqual(self.review(other, {**denial, 'decision': 'approve'}).status_code, 409)
        with self.assertRaisesRegex(DeliveryError, 'enrollment_denied'):
            self.state.poll({'device_code': pending['device_code']})

    def test_revoke_confirmation_unknown_retry_and_approval_replay(self):
        binding, pending, form, secret = self.pending()
        self.review(binding, form)
        self.assertEqual(self.revoke('device-one', confirm_device_id='').status_code, 400)
        self.assertEqual(self.revoke('device-one', review_hash='0' * 64).status_code, 409)
        self.assertEqual(self.revoke('device-one').status_code, 303)
        self.assertEqual(self.revoke('device-one').status_code, 303)
        self.assertEqual(self.review(binding, form, json_route=True).status_code, 409)
        with self.assertRaisesRegex(DeliveryError, 'invalid_credential'):
            self.state.authenticate(secret)
        response = self.client.post('/admin/devices/absent/confirm-revoke', base_url=self.origin,
                                    data={'csrf_token': 'a' * 64, 'confirm_device_id': 'absent', 'review_hash': '0' * 64})
        self.assertEqual(response.status_code, 404)

    def test_stale_revoke_and_superseded_approval_do_not_change_replacement(self):
        old, pending, form, secret = self.pending()
        self.review(old, form)
        old_hash = self.state.admin_devices()['devices'][0]['review_hash']
        new, pending, replacement, new_secret = self.pending()
        self.review(new, replacement)
        self.assertEqual(self.revoke('device-one', review_hash=old_hash).status_code, 409)
        self.assertEqual(self.review(old, form).status_code, 409)
        self.assertEqual(self.state.authenticate(new_secret)['revoked'], 0)

    def test_device_list_expiry_revocation_xss_and_credential_exclusion(self):
        binding, pending, form, secret = self.pending()
        self.review(binding, form)
        credential = self.state.authenticate(secret)['credential_id']
        self.now += 7 * 86400
        page = self.client.get('/admin/devices', base_url=self.origin)
        self.assertEqual(page.status_code, 200)
        self.assertIn(b'Expired', page.data)
        self.assertIn(binding['device_id'].encode(), page.data)
        for value in (secret, credential, binding['secret_verifier'], pending['device_code'], pending['user_code']):
            self.assertNotIn(value.encode(), page.data)
        self.revoke('device-one')
        self.assertIn(b'Revoked', self.client.get('/admin/devices', base_url=self.origin).data)
        with self.state.connection() as db:
            db.execute('UPDATE devices SET profile=?', ('<script>alert(1)</script>',))
        page = self.client.get('/admin/devices', base_url=self.origin)
        self.assertNotIn(b'<script>alert(1)</script>', page.data)
        self.assertIn(b'&lt;script&gt;', page.data)

    def test_revoke_preserves_publication_targets_history_bytes_and_ready(self):
        binding, pending, form, secret = self.pending()
        self.review(binding, form)
        generation = publish_current_events(self.app, secrets.token_hex(16))
        selected = distribution(self.state)['selected']
        package = selected['package_id']
        self.state.receipt(self.state.authenticate(secret), {
            'version': 1, 'receipt_id': secrets.token_hex(16), 'group_id': 'operator-fixture',
            'device_id': binding['device_id'], 'generation': generation, 'package_id': package,
            'mode': 'tv', 'session': 'unit-synthetic-session', 'result': 'ready'})
        with self.state.connection() as db:
            before = {table: [tuple(r) for r in db.execute('SELECT * FROM ' + table)] for table in
                      ('assignments', 'assignment_history', 'assignment_cohorts', 'assignment_targets', 'receipts')}
        files = {p.relative_to(self.state.root).as_posix(): sha(p.read_bytes())
                 for p in (self.state.root / 'publications').rglob('*') if p.is_file()}
        self.assertEqual(self.revoke('device-one').status_code, 303)
        after = distribution(self.state)['selected']
        self.assertEqual((len(after['targets']), after['ready'], after['outstanding']), (1, 1, 0))
        self.assertEqual(after['targets'][0]['eligibility'], 'revoked')
        with self.state.connection() as db:
            for table, rows in before.items():
                self.assertEqual([tuple(r) for r in db.execute('SELECT * FROM ' + table)], rows)
        self.assertEqual({name: sha((self.state.root / name).read_bytes()) for name in files}, files)
        for path in ('/api/v2/client/status', '/api/v2/group/trust',
                     '/api/v2/publications/' + package + '/tv/index.html',
                     '/api/v2/client/assignment?renderer=x&resource_profile=' + PROFILE):
            self.assertEqual(self.client.get(path, base_url=self.origin,
                             headers={'Authorization': 'Bearer ' + secret}).status_code, 401)


if __name__ == '__main__':
    unittest.main()
