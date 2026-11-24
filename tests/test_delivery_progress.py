"""Focused progress/order/security/accounting checks on disposable installations."""
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import secrets
import tempfile
import threading
import time
import unittest
from unittest.mock import Mock, patch
from contextlib import contextmanager

from kiosk.delivery.operator import distribution, publish_current_events
from kiosk.delivery.progress import validate
from kiosk.delivery.protocol import DeliveryError, decode, encode
from kiosk.display.delivery_progress import Reporter
from kiosk.display.delivery_transport import TransportError
from kiosk.display.delivery_client import Client
from kiosk.publication.exporter import PackageError
from tests.test_operator_delivery import fixture_app, enroll, admin_client
from tools.emit_delivery_progress_handoff import vectors


class ProgressTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.app = fixture_app(self.temp.name)
        self.state = self.app.extensions['device_delivery']
        self.now = int(time.time())
        self.state.clock = lambda: self.now
        self.secret = enroll(self.state, 'device-public')
        publish_current_events(self.app, secrets.token_hex(16))
        self.owner = self.state.authenticate(self.secret)
        self.target = self.state.progress_target(self.owner)
        self.base = dict(self.target, attempt=100, sequence=100, state='waiting', completed_bytes=0,
                         total_bytes=1024, error='none')

    def post(self, body, secret=None):
        return self.app.test_client().post('/api/v2/client/progress', base_url='https://localhost',
            headers={'Authorization': 'Bearer '+(secret or self.secret)}, json=body)

    def test_public_validation_vectors(self):
        for body in vectors()['accepts']:
            validate(body)
        for entry in vectors()['rejects']:
            with self.subTest(entry['name']), self.assertRaises(DeliveryError) as caught:
                validate(entry['body'])
            self.assertEqual(caught.exception.code, entry['error'])

    def test_ordering_vectors_and_statuses(self):
        for entry in vectors()['ordering']:
            body = {**entry['body'], **self.target}
            if entry.get('error') == 'binding_refused':
                body['device_id'] = 'foreign'
            if entry.get('error') == 'assignment_changed':
                body['generation'] = 2
            response = self.post(body)
            self.assertEqual(response.status_code, entry['http'], response.json)
            self.assertEqual(response.json.get('error', response.json.get('state')), entry.get('error', entry.get('state')))

    def test_concurrent_reordered_reports_keep_latest(self):
        bodies = [dict(self.base, sequence=100+i, state='downloading', completed_bytes=i) for i in range(20)]
        with ThreadPoolExecutor(max_workers=4) as pool:
            results = list(pool.map(lambda body: self.state.progress(self.owner, body), bodies))
        self.assertTrue(all(row['state'] in ('recorded', 'superseded') for row in results))
        target = distribution(self.state)['selected']['targets'][0]
        self.assertEqual(target['transfer']['sequence'], 119)
        self.assertEqual(target['transfer']['completed_bytes'], 19)

    def test_ready_count_frozen_legacy_contact_stale_and_history(self):
        self.post(dict(self.base, state='verified', completed_bytes=1024))
        model = distribution(self.state)['selected']
        self.assertEqual((model['ready'], len(model['targets'])), (0, 1))
        receipt = dict(version=1, receipt_id='receipt-public', group_id=self.target['group_id'],
                       device_id=self.target['device_id'], generation=1, package_id=self.target['package_id'],
                       mode='tv', session='session-public', result='ready')
        self.state.receipt(self.owner, receipt)
        self.state.receipt(self.owner, receipt)
        enroll(self.state, 'legacy-later')
        self.state.authenticate(self.secret)
        self.now += 121
        model = distribution(self.state)['selected']
        self.assertEqual((model['ready'], len(model['targets'])), (1, 1))
        self.assertTrue(model['targets'][0]['stale'])
        self.assertIsNone(model['later_members'][0]['transfer'])
        self.assertIsNone(model['later_members'][0]['last_contact'])
        self.state.revoke(self.target['device_id'])
        self.assertEqual(distribution(self.state)['selected']['ready'], 1)
        self.assertEqual(self.post(dict(self.base, sequence=101)).status_code, 401)
        self.assertEqual(self.post(self.base, secret='a'*64).status_code, 401)

    def test_route_bounds_authentication_and_page_escaping(self):
        client = self.app.test_client()
        self.assertEqual(client.post('/api/v2/client/progress', base_url='https://localhost', json=self.base).status_code, 401)
        self.assertEqual(client.post('/api/v2/client/progress', json=self.base).status_code, 403)
        headers = {'Authorization': 'Bearer '+self.secret}
        self.assertEqual(client.post('/api/v2/client/progress', base_url='https://localhost', headers=headers,
                                     data=b'x'*2049, content_type='application/json').status_code, 413)
        self.assertEqual(client.post('/api/v2/client/progress', base_url='https://localhost', headers=headers,
                                     data=b'{}').status_code, 415)
        self.assertEqual(self.post(dict(self.base, group_id='foreign')).status_code, 403)
        self.assertEqual(self.post(dict(self.base, package_id='b'*64)).status_code, 409)
        self.post(dict(self.base, state='error', error='storage'))
        response = admin_client(self.app).get('/admin/delivery', base_url='https://localhost')
        self.assertEqual(response.status_code, 200)
        self.assertIn(b'storage', response.data)
        self.assertNotIn(self.secret.encode(), response.data)
        self.assertEqual(client.get('/admin/delivery', base_url='https://localhost').status_code, 302)
        self.assertEqual(admin_client(self.app).post('/admin/delivery/publish', base_url='https://localhost').status_code, 403)

    def test_terminal_retry_old_assignment_and_contact_coalescing(self):
        self.state.progress(self.owner, dict(self.base, state='error', error='storage'))
        response = self.post(dict(self.base, sequence=101, state='downloading'))
        self.assertEqual((response.status_code, response.json['error']), (409, 'progress_conflict'))
        self.assertEqual(self.post(dict(self.base, attempt=102, sequence=102, state='downloading')).status_code, 200)
        initial_contact = distribution(self.state)['selected']['targets'][0]['last_contact']
        self.now += 15
        self.state.authenticate(self.secret)
        self.assertEqual(distribution(self.state)['selected']['targets'][0]['last_contact'], initial_contact)
        with self.state.connection() as db:
            self.state._assign(db, self.owner['profile'], 'b'*64, 'c'*64, 'new')
        self.assertEqual(self.post(dict(self.base, sequence=103)).status_code, 409)
        self.assertIsNone(distribution(self.state)['selected']['targets'][0]['transfer'])
        self.assertEqual(distribution(self.state, generation=1)['selected']['targets'][0]['transfer']['sequence'], 102)

    def test_device_budget_bounded_and_retry_after(self):
        limiter = self.app.extensions['device_progress_limiter']
        for i in range(150):
            self.assertEqual(limiter.reserve('devices', self.owner['device_id']), 0)
        response = self.post(self.base)
        self.assertEqual(response.status_code, 429)
        self.assertGreater(int(response.headers['Retry-After']), 0)
        with self.state.connection(write=False) as db:
            self.assertEqual(db.execute('SELECT count(*) FROM device_progress').fetchone()[0], 0)


class ReporterTests(unittest.TestCase):
    def test_incompatible_discovery_race_does_not_label_new_compatible_assignment(self):
        calls = []
        target = dict(version=1, device_id='device', group_id='group', generation=2, package_id='a'*64)
        class Transport:
            def json(self, path, **kwargs):
                calls.append(path)
                return target if path == '/api/v2/client/progress' else {'compatible_assignment': True}
        with tempfile.TemporaryDirectory() as folder:
            reporter = Reporter(Path(folder)/'sequence.json')
            reporter.offer(Transport(), {key: target[key] for key in ('version','device_id','group_id')},
                           reporter.begin(), 'incompatible', error='requires_update')
            deadline = time.monotonic()+2
            while reporter.pending is not None and time.monotonic()<deadline:
                time.sleep(.01)
            self.assertIsNone(reporter.pending)
            self.assertEqual(len(calls), 2)
            self.assertTrue(calls[1].startswith('/api/v2/client/assignment?'))
            reporter.close()

    def test_native_start_failure_reports_only_exact_attempted_target(self):
        client = Client.__new__(Client)
        client.transport = Mock()
        client.native = Mock()
        client.progress = Mock()
        client.progress_target = dict(version=1, device_id='device', group_id='group', generation=3, package_id='b'*64)
        client.store = client.cache = client.state = client.profile = client.shell = Path('unused')
        @contextmanager
        def failed(*args, **kwargs):
            raise PackageError('display_start_failed')
            yield
        with patch('kiosk.display.delivery_client.PublicationStore') as store, \
                patch('kiosk.display.coordinator._confirmed_view', return_value=None), \
                patch('kiosk.display.delivery_client.display_session', failed):
            store.return_value.active.return_value.name = 'b'*64
            with self.assertRaisesRegex(PackageError, 'display_start_failed'):
                with client.display():
                    self.fail('failed native session yielded')
        client.progress.offer.assert_called_once()
        self.assertEqual(client.progress.offer.call_args.args[1], client.progress_target)
        self.assertEqual(client.progress.offer.call_args.kwargs['error'], 'candidate_refused')

    def test_single_slot_nonblocking_and_retry(self):
        entered, release = threading.Event(), threading.Event()
        records = []
        class Transport:
            def json(self, path, *, body):
                entered.set()
                release.wait(3)
                records.append(body)
                if len(records) == 1:
                    raise TransportError('network_unavailable')
                return dict(version=1, sequence=body['sequence'], state='recorded')
        with tempfile.TemporaryDirectory() as folder:
            reporter = Reporter(Path(folder)/'sequence.json')
            target = dict(version=1, device_id='device', group_id='group', generation=1, package_id='a'*64)
            attempt = reporter.begin()
            reporter.offer(Transport(), target, attempt, 'waiting', 0, 1024)
            self.assertTrue(entered.wait(2))
            started = time.monotonic()
            for i in range(10000):
                reporter.offer(Transport(), target, attempt, 'downloading', i % 1024, 1024)
            reporter.offer(Transport(), target, attempt, 'verified', 1024, 1024)
            self.assertLess(time.monotonic()-started, 1)
            self.assertEqual(reporter.pending[1]['state'], 'verified')
            release.set()
            deadline = time.monotonic()+12
            while reporter.pending is not None and time.monotonic() < deadline:
                time.sleep(.01)
            self.assertIsNone(reporter.pending)
            self.assertEqual(len(records), 2)
            sequence = decode((Path(folder)/'sequence.json').read_bytes())['sequence']
            self.assertGreater(Reporter(Path(folder)/'sequence.json').begin(), sequence)
            reporter.close()
