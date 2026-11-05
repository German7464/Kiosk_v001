from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import json
import secrets
import unittest
from unittest.mock import patch

from kiosk.app import create_app
from kiosk.core.credentials import save_admin_password
from kiosk.delivery.protocol import DeliveryError, LIMITS, PROFILE, decode, encode, sha
from kiosk.delivery.publication import publish
from kiosk.delivery.state import DeliveryState
from tests import test_publication_export as fixtures


class DeliveryTests(unittest.TestCase):
    def setUp(self):
        self.fixture = fixtures.ExportTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.root = self.fixture.root
        self.now = 1_800_000_000
        self.state = DeliveryState(self.root / 'delivery', clock=lambda: self.now)
        self.config = {'version': 1, 'group_id': 'lab-group', 'server_id': 'lab-server',
                       'origin': 'https://localhost:8443', 'bootstrap': {}, 'trust': {}}
        (self.state.root / 'public.json').write_bytes(encode(self.config))
        self.secret = secrets.token_hex(32)
        self.binding = {'version': 1, 'request_id': secrets.token_hex(16), 'device_id': 'phone-1',
                        'group_id': 'lab-group', 'profile': PROFILE, 'origin': self.config['origin'],
                        'nonce': secrets.token_hex(16), 'secret_verifier': sha(bytes.fromhex(self.secret))}

    def enroll(self):
        pending = self.state.begin(self.binding)
        decision = {'user_code': pending['user_code'], 'binding_sha256': sha(encode(self.binding)), 'decision': 'approve'}
        self.state.approve(self.binding['request_id'], decision)
        return pending, decision

    def publication(self):
        self.fixture.export()
        return publish(self.state, self.fixture.destination)

    def app(self):
        base = self.root / 'app'
        app = create_app({'TESTING': True, 'SECRET_KEY': 'disposable-test-key',
                          'INSTANCE_DIR': base / 'instance', 'DATABASE_PATH': base / 'instance/kiosk.sqlite',
                          'PRIVATE_UPLOAD_DIR': base / 'private', 'PUBLIC_UPLOAD_DIR': base / 'public',
                          'STATIC_FOLDER': base / 'static', 'DEVICE_DELIVERY_ROOT': self.state.root})
        app.extensions['device_delivery'] = self.state
        return app

    def test_strict_cross_platform_metadata(self):
        for payload in (b'{"a":1,"a":2}', b'{"a":1.0}', b'{"a":NaN}', b'{"a":9223372036854775808}',
                        b'\xef\xbb\xbf{}', b'{"a":"\\ud800"}', b'{} trailing', b'[]'):
            with self.subTest(payload=payload), self.assertRaises(DeliveryError):
                decode(payload)
        self.assertEqual(decode(b'{"a":true,"b":12}'), {'a': True, 'b': 12})

    def test_enrollment_lost_responses_restart_and_concurrent_approval(self):
        first = self.state.begin(self.binding)
        self.assertEqual(first, self.state.begin(self.binding))
        decision = {'user_code': first['user_code'], 'binding_sha256': sha(encode(self.binding)), 'decision': 'approve'}
        with ThreadPoolExecutor(max_workers=4) as pool:
            results = list(pool.map(lambda _: self.state.approve(self.binding['request_id'], decision), range(8)))
        self.assertEqual(len({row['credential_id'] for row in results}), 1)
        restarted = DeliveryState(self.state.root, clock=lambda: self.now)
        self.assertEqual(restarted.poll({'device_code': first['device_code']}), self.state.poll({'device_code': first['device_code']}))
        self.assertEqual(restarted.authenticate(self.secret)['device_id'], 'phone-1')
        with restarted.connection() as db:
            self.assertEqual(db.execute('SELECT count(*) FROM devices').fetchone()[0], 1)
        # Server DB never retains the bearer credential itself.
        self.assertNotIn(self.secret.encode(), (self.state.root / 'delivery.sqlite').read_bytes())

    def test_replay_wrong_binding_poll_throttle_denial_and_expiry(self):
        pending = self.state.begin(self.binding)
        with self.assertRaisesRegex(DeliveryError, 'request_conflict'):
            self.state.begin({**self.binding, 'nonce': 'different'})
        self.assertEqual(self.state.poll({'device_code': pending['device_code']})['state'], 'pending')
        with self.assertRaisesRegex(DeliveryError, 'slow_down'):
            self.state.poll({'device_code': pending['device_code']})
        decision = {'user_code': pending['user_code'], 'binding_sha256': '0' * 64, 'decision': 'approve'}
        with self.assertRaisesRegex(DeliveryError, 'binding_refused'):
            self.state.approve(self.binding['request_id'], decision)
        self.state.approve(self.binding['request_id'], {**decision, 'binding_sha256': sha(encode(self.binding)), 'decision': 'deny'})
        with self.assertRaisesRegex(DeliveryError, 'enrollment_denied'):
            self.state.poll({'device_code': pending['device_code']})
        self.now += 601
        with self.assertRaisesRegex(DeliveryError, 'enrollment_expired'):
            self.state.begin(self.binding)

    def test_credential_replacement_revocation_and_expiry(self):
        self.enroll()
        previous = self.state.authenticate(self.secret)
        replacement = secrets.token_hex(32)
        self.binding = {**self.binding, 'request_id': secrets.token_hex(16), 'nonce': secrets.token_hex(16),
                        'secret_verifier': sha(bytes.fromhex(replacement))}
        self.enroll()
        with self.assertRaisesRegex(DeliveryError, 'invalid_credential'):
            self.state.authenticate(self.secret)
        self.assertNotEqual(previous['credential_id'], self.state.authenticate(replacement)['credential_id'])
        self.state.revoke('phone-1')
        with self.assertRaisesRegex(DeliveryError, 'invalid_credential'):
            self.state.authenticate(replacement)

    def test_expiry_never_renews_from_poll(self):
        pending, decision = self.enroll()
        self.now += 7 * 86400
        with self.assertRaisesRegex(DeliveryError, 'invalid_credential'):
            self.state.authenticate(self.secret)

    def test_prepare_both_views_and_resource_refusal_preserves_assignment(self):
        metadata = self.publication()
        identity = metadata['package_id']
        generation = self.state.assign(PROFILE, identity, sha(encode(metadata)))
        self.assertEqual(generation, 1)
        self.assertEqual(publish(self.state, self.fixture.destination), metadata)
        self.assertEqual(self.state.assign(PROFILE, identity, sha(encode(metadata))), 1)
        self.assertEqual(metadata['limits'], LIMITS)
        for mode in ('kiosk', 'tv'):
            self.assertTrue((self.state.root / 'publications' / identity / mode / 'index.html').is_file())
        self.enroll()
        owner = self.state.authenticate(self.secret)
        with self.assertRaisesRegex(DeliveryError, 'requires_update'):
            self.state.assignment(owner, 'unknown', PROFILE)
        with patch('kiosk.delivery.publication.LIMITS', {**LIMITS, 'max_pixels': 1}):
            with fixtures.connection(self.fixture.db) as db:
                db.execute("UPDATE settings SET value='8' WHERE key='content_version'")
            self.fixture.export(self.root / 'bad-profile')
            with self.assertRaisesRegex(DeliveryError, 'unsupported_resource_profile'):
                publish(self.state, self.root / 'bad-profile')
        assigned = self.state.assignment(owner, metadata['renderer']['build_id'], PROFILE)
        self.assertEqual(assigned['publication']['package_id'], identity)
        self.assertEqual(assigned['generation'], generation)

    def test_http_authorization_artifact_integrity_and_receipt_retry(self):
        metadata = self.publication()
        self.state.assign(PROFILE, metadata['package_id'], sha(encode(metadata)))
        self.enroll()
        client = self.app().test_client()
        origin = self.config['origin']
        headers = {'Authorization': 'Bearer ' + self.secret}
        path = '/api/v2/client/assignment?renderer=' + metadata['renderer']['build_id'] + '&resource_profile=' + PROFILE
        self.assertEqual(client.get(path, base_url=origin).status_code, 401)
        self.assertEqual(client.get(path, headers=headers).status_code, 403)
        self.assertEqual(client.get(path, base_url=origin, headers=headers).status_code, 200)
        base = '/api/v2/publications/' + metadata['package_id']
        response = client.get(base + '/kiosk/index.html', base_url=origin, headers=headers)
        self.assertEqual(response.status_code, 200)
        self.assertIn(b'bootstrap', response.data)
        response.close()
        self.assertEqual(client.get(base + '/package/delivery.sqlite', base_url=origin, headers=headers).status_code, 404)
        self.assertEqual(client.get('/api/v2/publications/' + '0' * 64 + '/package/manifest.json', base_url=origin, headers=headers).status_code, 409)
        receipt = {'version': 1, 'receipt_id': secrets.token_hex(16), 'group_id': 'lab-group', 'device_id': 'phone-1',
                   'generation': 1, 'package_id': metadata['package_id'], 'mode': 'tv', 'session': 'session-1', 'result': 'ready'}
        for _ in range(2):
            self.assertEqual(client.post('/api/v2/client/receipts', json=receipt, base_url=origin, headers=headers).status_code, 200)
        self.assertEqual(client.post('/api/v2/client/receipts', json={**receipt, 'mode': 'kiosk'}, base_url=origin, headers=headers).status_code, 409)
        (self.state.root / 'publications' / metadata['package_id'] / 'kiosk/index.html').write_bytes(b'tampered')
        self.assertEqual(client.get(base + '/kiosk/index.html', base_url=origin, headers=headers).status_code, 503)
        self.state.revoke('phone-1')
        self.assertEqual(client.get(path, base_url=origin, headers=headers).status_code, 401)

    def test_admin_routes_use_existing_login_and_csrf(self):
        app = self.app()
        save_admin_password(app, 'disposable-test-password', setup=True)
        client = app.test_client()
        origin = self.config['origin']
        pending = self.state.begin(self.binding)
        self.assertEqual(client.get('/admin/devices/pending', base_url=origin).status_code, 302)
        from kiosk.core.credentials import session_credential_token
        from kiosk.database import get_database
        with app.app_context():
            user = get_database().execute("SELECT * FROM users WHERE username='admin'").fetchone()
            credential_token = session_credential_token(user)
            user_id = user['id']
        csrf = 'a' * 64
        with client.session_transaction(base_url=origin) as session:
            session.update(admin_user_id=user_id, credential_token=credential_token, csrf_token=csrf)
        response = client.get('/admin/devices/pending', base_url=origin)
        self.assertEqual(response.status_code, 200)
        row = response.json['requests'][0]
        self.assertNotIn('secret_verifier', row['binding'])
        decision = {'user_code': pending['user_code'], 'binding_sha256': row['binding_sha256'], 'decision': 'approve'}
        path = '/admin/devices/' + self.binding['request_id'] + '/decision'
        self.assertEqual(client.post(path, json=decision, base_url=origin).status_code, 403)
        self.assertEqual(client.post(path, json=decision, base_url=origin, headers={'X-CSRF-Token': csrf}).status_code, 200)

    def test_resumed_artifact_reconstructs_exact_bytes_and_rejects_bad_ranges(self):
        metadata = self.publication()
        self.state.assign(PROFILE, metadata['package_id'], sha(encode(metadata)))
        self.enroll()
        client = self.app().test_client()
        path = '/api/v2/publications/' + metadata['package_id'] + '/kiosk/index.html'
        headers = {'Authorization': 'Bearer ' + self.secret}
        entry = next(x for x in metadata['kiosk']['files'] if x['path'] == 'index.html')
        etag = '"' + entry['sha256'] + '"'
        def get(extra=None):
            return client.get(path, base_url=self.config['origin'], headers={**headers, **(extra or {})})
        full = get()
        original = full.data
        self.assertEqual(full.headers['ETag'], etag)
        full.close()
        parts = []
        for interval in ('0-16', '17-'):
            response = get({'Range': 'bytes=' + interval, 'If-Range': etag})
            self.assertEqual(response.status_code, 206)
            self.assertEqual(int(response.headers['Content-Length']), len(response.data))
            parts.append(response.data)
            response.close()
        self.assertEqual(b''.join(parts), original)
        self.assertEqual(sha(b''.join(parts)), entry['sha256'])
        for interval in ('-12', '0-1,4-5', '5-2', str(len(original)) + '-', '9' * 21 + '-'):
            response = get({'Range': 'bytes=' + interval, 'If-Range': etag})
            self.assertEqual(response.status_code, 416)
            self.assertEqual(response.headers['Content-Range'], 'bytes */' + str(len(original)))
            response.close()
        for validator in (None, '"different"', 'W/' + etag):
            extra = {'Range': 'bytes=17-'}
            if validator is not None:
                extra['If-Range'] = validator
            response = get(extra)
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.data, original)
            response.close()
        (self.state.root / 'publications' / metadata['package_id'] / 'kiosk/index.html').write_bytes(b'broken')
        self.assertEqual(get({'Range': 'bytes=17-', 'If-Range': etag}).status_code, 503)
        self.state.revoke('phone-1')
        self.assertEqual(get({'Range': 'bytes=17-', 'If-Range': etag}).status_code, 401)

    def test_transfer_capacity_releases_on_disconnect_without_blocking_metadata(self):
        metadata = self.publication()
        self.state.assign(PROFILE, metadata['package_id'], sha(encode(metadata)))
        self.enroll()
        app = self.app()
        client = app.test_client()
        headers = {'Authorization': 'Bearer ' + self.secret}
        kwargs = {'base_url': self.config['origin'], 'headers': headers}
        path = '/api/v2/publications/' + metadata['package_id'] + '/kiosk/index.html'
        responses = [client.get(path, buffered=False, **kwargs) for _ in range(2)]
        try:
            self.assertTrue(all(r.status_code == 200 for r in responses))
            busy = client.get(path, **kwargs)
            self.assertEqual(busy.status_code, 429)
            self.assertEqual(busy.json['error'], 'transfer_busy')
            self.assertEqual(busy.headers['Retry-After'], '5')
            self.assertEqual(client.get('/api/v2/client/status', **kwargs).status_code, 200)
            responses[0].close()
            replacement = client.get(path, **kwargs)
            self.assertEqual(replacement.status_code, 200)
            replacement.close()
        finally:
            for response in responses:
                response.close()
        # Read/validation failures must also release the slot.
        target = self.state.root / 'publications' / metadata['package_id'] / 'kiosk/index.html'
        target.write_bytes(b'bad')
        for _ in range(3):
            self.assertEqual(client.get(path, **kwargs).status_code, 503)

    def test_queued_receipt_requires_exact_historical_assignment(self):
        metadata = self.publication()
        self.enroll()
        owner = self.state.authenticate(self.secret)
        self.state.assign(PROFILE, metadata['package_id'], sha(encode(metadata)))
        receipt = {'version': 1, 'receipt_id': 'receipt-1', 'group_id': 'lab-group', 'device_id': 'phone-1',
                   'generation': 2, 'package_id': metadata['package_id'], 'mode': 'tv', 'session': 'session-1', 'result': 'ready'}
        with self.assertRaisesRegex(DeliveryError, 'unknown_assignment'):
            self.state.receipt(owner, receipt)
        self.assertEqual(self.state.receipt(owner, {**receipt, 'generation': 1})['state'], 'recorded')

    def test_corrupt_catalog_and_failed_catalog_capacity_do_not_change_assignment(self):
        metadata = self.publication()
        self.state.assign(PROFILE, metadata['package_id'], sha(encode(metadata)))
        record = self.state.root / 'publications' / metadata['package_id'] / 'delivery.json'
        original = record.read_bytes()
        record.write_bytes(encode({**metadata, 'revision': '123'}))
        with self.assertRaisesRegex(DeliveryError, 'publication_integrity'):
            publish(self.state, self.fixture.destination)
        record.write_bytes(original)
        with fixtures.connection(self.fixture.db) as db:
            db.execute("UPDATE settings SET value='8' WHERE key='content_version'")
        self.fixture.export(self.root / 'candidate')
        with patch('kiosk.delivery.publication.MAX_CATALOG_BYTES', 1):
            with self.assertRaisesRegex(DeliveryError, 'catalog_full'):
                publish(self.state, self.root / 'candidate')
        self.assertFalse(any((self.state.root / 'publications').glob('.delivery-*')))
        self.enroll()
        assignment = self.state.assignment(self.state.authenticate(self.secret), metadata['renderer']['build_id'], PROFILE)
        self.assertEqual(assignment['publication']['package_id'], metadata['package_id'])

    def test_http_pending_conflict_expiry_and_content_type(self):
        client = self.app().test_client()
        origin = self.config['origin']
        path = '/api/v2/device/authorize'
        self.assertEqual(client.post(path, json=self.binding, base_url=origin).status_code, 200)
        self.assertEqual(client.post(path, json={**self.binding, 'nonce': 'changed'}, base_url=origin).status_code, 409)
        self.assertEqual(client.post(path, data=b'{}', base_url=origin).status_code, 415)
        self.assertEqual(client.post(path, data=b'{"version":1,"version":1}', content_type='application/json', base_url=origin).status_code, 400)
        self.now += 601
        self.assertEqual(client.post(path, json=self.binding, base_url=origin).status_code, 410)

    def test_failed_approval_transaction_preserves_previous_credential(self):
        self.enroll()
        first = self.state.authenticate(self.secret)
        other = {**self.binding, 'device_id': 'phone-2', 'request_id': secrets.token_hex(16)}
        pending = self.state.begin(other)
        decision = {'user_code': pending['user_code'], 'binding_sha256': sha(encode(other)), 'decision': 'approve'}
        with self.assertRaisesRegex(DeliveryError, 'credential_conflict'):
            self.state.approve(other['request_id'], decision)
        self.assertEqual(self.state.authenticate(self.secret)['credential_id'], first['credential_id'])


if __name__ == '__main__':
    unittest.main()
