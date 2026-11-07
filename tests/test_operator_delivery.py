"""Disposable full admin publication flow and immutable-recipient regression."""
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
import hashlib
from pathlib import Path
import re
import secrets
import shutil
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from kiosk.app import create_app
from kiosk.core.credentials import save_admin_password, session_credential_token
from kiosk.database import get_database
from kiosk.delivery.operator import distribution, publish_current_events
from kiosk.delivery.protocol import DeliveryError, PROFILE, encode, sha
from kiosk.delivery.state import DeliveryState


def fixture_app(root):
    """No lab helper, trust, automatic publisher or working data is involved."""
    root = Path(root)
    app = create_app({'TESTING': True, 'SECRET_KEY': 'operator-disposable-session-key',
                      'INSTANCE_DIR': root / 'instance', 'DATABASE_PATH': root / 'instance/events.sqlite',
                      'PRIVATE_UPLOAD_DIR': root / 'instance/uploads', 'PUBLIC_UPLOAD_DIR': root / 'public/uploads',
                      'STATIC_FOLDER': root / 'public', 'DEVICE_DELIVERY_ROOT': root / 'delivery'})
    state = app.extensions['device_delivery']
    (state.root / 'public.json').write_bytes(encode({
        'version': 1, 'group_id': 'operator-fixture', 'server_id': 'operator-server',
        'origin': 'https://localhost:18443', 'bootstrap': {}, 'trust': {}}))
    save_admin_password(app, 'disposable-operator-password', setup=True)
    with closing(sqlite3.connect(app.config['DATABASE_PATH'])) as db:
        db.execute("INSERT INTO events(title,full_description,status,created_at,updated_at) VALUES (?,?,?,?,?)",
                   ('Operator Events A', 'Synthetic operator accounting fixture.', 'active', '2026-11-05', '2026-11-05'))
        db.commit()
    return app


def admin_client(app):
    client = app.test_client()
    with app.app_context():
        user = get_database().execute("SELECT * FROM users WHERE username='admin'").fetchone()
        user_id, token = user['id'], session_credential_token(user)
    with client.session_transaction(base_url='https://localhost') as session:
        session.update(admin_user_id=user_id, admin_username='admin', credential_token=token, csrf_token='a' * 64)
    return client


def enroll(state, device_id):
    secret = secrets.token_hex(32)
    config = state.configuration()
    binding = {'version': 1, 'request_id': secrets.token_hex(16), 'device_id': device_id,
               'group_id': config['group_id'], 'profile': PROFILE, 'origin': config['origin'],
               'nonce': secrets.token_hex(16), 'secret_verifier': sha(bytes.fromhex(secret))}
    pending = state.begin(binding)
    state.approve(binding['request_id'], {'user_code': pending['user_code'],
                  'binding_sha256': sha(encode(binding)), 'decision': 'approve'})
    return secret


class OperatorDeliveryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.app = fixture_app(self.root)
        self.state = self.app.extensions['device_delivery']
        self.now = 1_800_000_000
        self.state.clock = lambda: self.now
        self.client = admin_client(self.app)

    def publish(self, operation_id=None):
        return publish_current_events(self.app, operation_id or secrets.token_hex(16))

    def change(self):
        with closing(sqlite3.connect(self.app.config['DATABASE_PATH'])) as db:
            db.execute("UPDATE settings SET value=CAST(value AS INTEGER)+1 WHERE key='content_version'")
            db.execute("UPDATE events SET title=title || ' changed'")
            db.commit()

    def ready(self, device_id, secret, generation, package_id, **extra):
        body = {'version': 1, 'receipt_id': secrets.token_hex(16), 'group_id': 'operator-fixture',
                'device_id': device_id, 'generation': generation, 'package_id': package_id,
                'mode': 'tv', 'session': 'ordinary-session', 'result': 'ready', **extra}
        response = self.client.post('/api/v2/client/receipts', json=body, base_url='https://localhost',
                                    headers={'Authorization': 'Bearer ' + secret})
        return response, body

    def selected(self, generation=None):
        return distribution(self.state, generation)['selected']

    def inventory(self, root):
        return {path.relative_to(root).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
                for path in root.rglob('*') if path.is_file()}

    def test_auth_csrf_explicit_publish_and_read_routes(self):
        guest = self.app.test_client()
        secret = enroll(self.state, 'original-one')
        for path in ('/admin/delivery', '/admin/delivery/1'):
            self.assertEqual(guest.get(path, base_url='https://localhost').status_code, 302)
            self.assertEqual(guest.get(path, base_url='https://localhost',
                             headers={'Authorization': 'Bearer ' + secret}).status_code, 302)
        self.assertEqual(guest.post('/admin/delivery/publish', base_url='https://localhost').status_code, 403)
        self.assertEqual(self.client.post('/admin/delivery/publish', base_url='https://localhost').status_code, 403)
        self.assertEqual(self.client.get('/admin/delivery').status_code, 403)
        page = self.client.get('/admin/delivery', base_url='https://localhost')
        self.assertEqual(page.status_code, 200)
        self.assertIsNone(self.selected())  # GET does not publish.
        operation = re.search(rb'name="operation_id" value="([a-f0-9]+)"', page.data)[1].decode()
        form = {'csrf_token': 'a' * 64, 'operation_id': operation}
        native = guest.post('/admin/delivery/publish', data=form, base_url='https://localhost',
                            headers={'Authorization': 'Bearer ' + secret})
        self.assertEqual(native.status_code, 403)
        response = self.client.post('/admin/delivery/publish', data=form, base_url='https://localhost')
        self.assertEqual(response.status_code, 303)
        self.assertTrue(response.location.endswith('/admin/delivery/1'))
        self.assertEqual(self.client.get(response.location, base_url='https://localhost').status_code, 200)
        self.assertEqual(self.selected()['outstanding'], 1)
        self.assertIn(b'/admin/delivery', self.client.get('/admin', base_url='https://localhost').data)
        self.assertEqual(self.client.post('/admin/delivery/publish', data={'csrf_token': 'a' * 64},
                         base_url='https://localhost').status_code, 400)
        self.assertEqual(self.client.get('/admin/delivery/999', base_url='https://localhost').status_code, 404)

    def test_no_delivery_opt_in_no_page_or_navigation(self):
        config = {key: self.app.config[key] for key in ('TESTING', 'SECRET_KEY', 'INSTANCE_DIR',
                  'DATABASE_PATH', 'PRIVATE_UPLOAD_DIR', 'PUBLIC_UPLOAD_DIR')}
        config.update(STATIC_FOLDER=self.root / 'public', DEVICE_DELIVERY_ROOT=None)
        disabled = create_app(config)
        client = admin_client(disabled)
        self.assertEqual(client.get('/admin/delivery', base_url='https://localhost').status_code, 404)
        self.assertNotIn(b'/admin/delivery', client.get('/admin', base_url='https://localhost').data)

    def test_frozen_targets_join_revoke_remove_profile_expiry_and_restart(self):
        secret = enroll(self.state, 'one')
        enroll(self.state, 'two')
        for name in ('revoked-before', 'expired-before', 'other-profile'):
            enroll(self.state, name)
        self.state.revoke('revoked-before')
        with self.state.connection() as db:
            db.execute('UPDATE devices SET expires=? WHERE device_id=?', (self.now, 'expired-before'))
            db.execute("UPDATE devices SET profile='other' WHERE device_id='other-profile'")
        self.publish()
        package = self.selected()['package_id']
        self.assertEqual(self.ready('one', secret, 1, package)[0].status_code, 200)
        self.state.revoke('one')
        late_secret = enroll(self.state, 'late')
        self.assertEqual(self.ready('late', late_secret, 1, package)[0].status_code, 200)
        with self.state.connection() as db:
            db.execute("DELETE FROM devices WHERE device_id='two'")
        restarted = DeliveryState(self.state.root, clock=lambda: self.now)
        view = distribution(restarted)['selected']
        self.assertEqual([(t['device_id'], t['eligibility']) for t in view['targets']], [('one', 'revoked'), ('two', 'absent')])
        self.assertEqual((view['ready'], view['outstanding']), (1, 1))
        self.assertEqual([r['device_id'] for r in view['other_reports']], ['late'])
        self.assertEqual(self.publish(), 1)  # Unchanged content never refreezes.
        self.assertEqual(len(self.selected()['targets']), 2)

    def test_delayed_duplicate_and_wrong_generation_receipts(self):
        secret = enroll(self.state, 'one')
        self.publish()
        first = self.selected()
        self.change()
        self.publish()
        second = self.selected()
        response, body = self.ready('one', secret, 1, first['package_id'])
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.selected(1)['ready'], 1)
        self.assertEqual(self.selected(2)['ready'], 0)
        headers = {'Authorization': 'Bearer ' + secret}
        for _ in range(2):
            self.assertEqual(self.client.post('/api/v2/client/receipts', json=body, headers=headers,
                             base_url='https://localhost').status_code, 200)
        self.assertEqual(self.client.post('/api/v2/client/receipts', json={**body, 'mode': 'kiosk'},
                         headers=headers, base_url='https://localhost').status_code, 409)
        self.assertEqual(self.ready('one', secret, 2, first['package_id'])[0].status_code, 409)
        self.assertEqual(self.ready('one', secret, 2, second['package_id'])[0].status_code, 200)
        self.assertEqual(self.ready('one', secret, 2, second['package_id'], mode='kiosk')[0].status_code, 200)
        self.assertEqual(self.selected(2)['ready'], 1)  # Two modes/sessions still one original device.
        self.assertEqual(self.selected(2)['targets'][0]['modes'], ['kiosk', 'tv'])
        # Even reassigning the exact old package creates a distinct activation generation.
        self.assertEqual(self.state.assign(PROFILE, first['package_id'], first['metadata_hash']), 3)
        self.assertEqual(self.selected(3)['ready'], 0)
        self.assertEqual(self.ready('one', secret, 3, first['package_id'])[0].status_code, 200)
        self.assertEqual(self.selected(3)['ready'], 1)

    def test_request_retry_after_source_changes_returns_original_publication(self):
        operation = secrets.token_hex(16)
        self.assertEqual(self.publish(operation), 1)
        self.change()
        self.assertEqual(self.publish(), 2)
        self.assertEqual(self.publish(operation), 1)
        self.assertEqual(self.selected()['generation'], 2)
        self.assertFalse(self.selected(1)['current'])

    def test_concurrent_publish_one_generation_and_frozen_cohort(self):
        enroll(self.state, 'one')
        operation = secrets.token_hex(16)
        with ThreadPoolExecutor(max_workers=4) as pool:
            generations = list(pool.map(lambda _: self.publish(operation), range(4)))
        self.assertEqual(generations, [1] * 4)
        # Independent requests for the same complete snapshot are idempotent too.
        with ThreadPoolExecutor(max_workers=4) as pool:
            self.assertEqual(list(pool.map(lambda _: self.publish(), range(4))), [1] * 4)
        with self.state.connection() as db:
            self.assertEqual(db.execute('SELECT count(*) FROM assignment_history').fetchone()[0], 1)
            self.assertEqual(db.execute('SELECT count(*) FROM assignment_targets').fetchone()[0], 1)

    def test_assignment_failure_rolls_back_targets_and_preserves_prior_content(self):
        enroll(self.state, 'one')
        self.publish()
        first = self.selected()
        prior = self.inventory(self.state.root / 'publications' / first['package_id'])
        self.change()
        # Fail at the final INSERT, after new assignment/history/cohort writes.
        with self.state.connection() as db:
            db.execute("""CREATE TRIGGER fail_operation BEFORE INSERT ON operator_publications
                BEGIN SELECT RAISE(ABORT,'fixture assignment failure'); END""")
        response = self.client.post('/admin/delivery/publish', data={'csrf_token': 'a' * 64,
                                   'operation_id': secrets.token_hex(16)}, base_url='https://localhost')
        self.assertEqual(response.status_code, 503)
        self.assertNotIn(b'fixture assignment failure', response.data)
        self.assertEqual(self.selected(), first)
        self.assertEqual(self.inventory(self.state.root / 'publications' / first['package_id']), prior)
        with self.state.connection() as db:
            self.assertEqual(db.execute('SELECT count(*) FROM assignment_cohorts').fetchone()[0], 1)
            self.assertEqual(db.execute('SELECT count(*) FROM assignment_history').fetchone()[0], 1)
        # The verified orphan is retained; the next successful request safely reuses it.
        with self.state.connection() as db:
            db.execute('DROP TRIGGER fail_operation')
        self.assertEqual(self.publish(), 2)

    def test_snapshot_and_verification_failure_preserve_assignment(self):
        self.publish()
        first = self.selected()
        prior = self.inventory(self.state.root / 'publications' / first['package_id'])
        self.change()
        for failure in ('export', 'verify'):
            if failure == 'export':
                from kiosk.publication.exporter import PackageError
                target, error = 'kiosk.delivery.operator.export_events_package', PackageError('private-path-secret')
            else:
                target, error = 'kiosk.delivery.publication.verify_package', DeliveryError('publication_integrity', 503)
            with self.subTest(failure=failure), patch(target, side_effect=error):
                response = self.client.post('/admin/delivery/publish', data={'csrf_token': 'a' * 64,
                                            'operation_id': secrets.token_hex(16)}, base_url='https://localhost')
                self.assertEqual(response.status_code, 409 if failure == 'export' else 503)
                self.assertNotIn(b'private-path-secret', response.data)
                self.assertEqual(self.selected(), first)
                self.assertEqual(self.inventory(self.state.root / 'publications' / first['package_id']), prior)
                self.assertFalse(list(self.state.root.glob('.operator-export-*')))

    def test_empty_cohort_and_late_ready_never_imply_original_display(self):
        self.publish()
        view = self.selected()
        self.assertEqual((view['targets'], view['ready'], view['outstanding']), ([], 0, 0))
        secret = enroll(self.state, 'late')
        self.assertEqual(self.ready('late', secret, 1, view['package_id'])[0].status_code, 200)
        self.assertEqual(self.selected()['ready'], 0)
        page = self.client.get('/admin/delivery/1', base_url='https://localhost').data
        self.assertIn(b'No original recipients.', page)
        self.assertIn(b'outside original counts', page)

    def test_legacy_upgrade_on_copy_is_unknown_and_never_backfilled(self):
        enroll(self.state, 'one')
        self.publish()
        copy = self.root / 'old-copy'
        shutil.copytree(self.state.root, copy)
        with closing(sqlite3.connect(copy / 'delivery.sqlite')) as db:
            for table in ('assignment_targets', 'assignment_cohorts', 'operator_publications'):
                db.execute('DROP TABLE ' + table)
            db.commit()
        upgraded = DeliveryState(copy, clock=lambda: self.now)
        view = distribution(upgraded)['selected']
        self.assertIsNone(view['targets'])
        self.assertIsNone(view['ready'])
        upgraded.assign(PROFILE, view['package_id'], view['metadata_hash'])
        self.assertIsNone(distribution(upgraded)['selected']['targets'])
        self.app.extensions['device_delivery'] = upgraded
        page = self.client.get('/admin/delivery/1', base_url='https://localhost')
        self.assertEqual(page.status_code, 200)
        self.assertIn(b'Original recipients unknown', page.data)
        self.assertNotIn(b'Original recipients unknown', self.client.get('/admin', base_url='https://localhost').data)
        self.assertEqual(len(distribution(self.state)['selected']['targets']), 1)  # Original untouched.

    def test_escaping_secret_exclusion_and_bounded_history_navigation(self):
        secret = enroll(self.state, 'one')
        self.publish()
        hostile = '<script>alert("stored")</script>'
        with self.state.connection() as db:
            db.execute('UPDATE assignment_targets SET device_id=?', (hostile,))
            db.execute('UPDATE assignment_cohorts SET revision=?', (hostile,))
            private = db.execute('SELECT verifier,credential_id FROM devices').fetchone()
            code = db.execute('SELECT device_code,user_code FROM enrollments').fetchone()
        page = self.client.get('/admin/delivery/1', base_url='https://localhost')
        self.assertEqual(page.status_code, 200)
        self.assertIn(b'&lt;script&gt;', page.data)
        self.assertNotIn(hostile.encode(), page.data)
        for value in (secret, *private, *code, str(self.state.root)):
            self.assertNotIn(value.encode(), page.data)
        for cursor in ('bad', '-1', '0', '9223372036854775808'):
            self.assertEqual(self.client.get('/admin/delivery?before=' + cursor, base_url='https://localhost').status_code, 400)
        with self.state.connection() as db:
            first = db.execute('SELECT * FROM assignment_history').fetchone()
            for generation in range(2, 31):
                db.execute('INSERT INTO assignment_history VALUES (?,?,?,?)',
                           (PROFILE, generation, first['package_id'], first['metadata_hash']))
        model = distribution(self.state)
        self.assertEqual(len(model['history']), 25)
        self.assertTrue(model['more'])
        earlier = self.client.get('/admin/delivery?before=6', base_url='https://localhost')
        self.assertEqual(earlier.status_code, 200)
        self.assertIn(b'/admin/delivery/1', earlier.data)


if __name__ == '__main__':
    unittest.main()
