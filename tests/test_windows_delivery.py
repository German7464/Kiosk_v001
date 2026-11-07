"""Affected native trust/capture/outbox boundaries; not VM renderer acceptance."""
from contextlib import contextmanager
from copy import deepcopy
from io import BytesIO
import json
from pathlib import Path
import secrets
import tempfile
import time
import unittest
from unittest.mock import patch, Mock

from kiosk.delivery.protocol import DeliveryError, PROFILE, encode, sha
from kiosk.delivery.publication import publish
from kiosk.delivery.state import DeliveryState
from kiosk.display.delivery_authority import PrivateState, bootstrap, origin
from kiosk.display.delivery_capture import Capture, validate_metadata, verify_captured
from kiosk.display.delivery_client import Client
from kiosk.display.delivery_transport import Transport, TransportError
from kiosk.display.native_crypto import b64, protect, verify_signature, certificate_spki
from kiosk.publication.exporter import PackageError
from kiosk.publication.store import PublicationStore
from tests import test_publication_export as fixtures

PUBLIC = Path(__file__).parent / 'fixtures/device-delivery-v1-public.json'


class NativeAuthorityTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.public = json.loads(PUBLIC.read_text())
        self.anchor = self.public['bootstrap']
        self.now = self.anchor['issued_at'] + 60
        self.clock = patch('kiosk.display.delivery_authority.time.time', return_value=self.now)
        self.clock.start()
        self.addCleanup(self.clock.stop)
        self.state = PrivateState(self.root)
        self.state.data['bootstrap'] = self.anchor
        self.state.confirm_time(self.now)
        import base64
        payload = json.loads(base64.b64decode(self.public['trust']['payload_base64']))
        self.pin = payload['servers'][0]['tls_spki_sha256']

    def test_real_cng_signature_dpapi_restart_and_secrets_not_plaintext(self):
        self.state.data['secret'] = 'a' * 64
        self.state.verify_trust(self.public['trust'], self.pin)
        persisted = PrivateState(self.root)
        self.assertEqual(persisted.data, self.state.data)
        self.assertNotIn(b'a' * 64, (self.root / 'native.dpapi').read_bytes())

    def test_unknown_key_signature_payload_and_group_server_origin_tls_binding(self):
        for field, value in [('key_id', '0' * 64), ('signature_base64', 'A' * 512), ('payload_base64', 'e30=')]:
            envelope = deepcopy(self.public['trust'])
            envelope[field] = value
            with self.subTest(field=field), self.assertRaises(PackageError):
                self.state.verify_trust(envelope, self.pin)
        for field in ('group_id', 'server_id', 'origin'):
            original = self.state.data['bootstrap'][field]
            self.state.data['bootstrap'][field] = 'different' if field != 'origin' else 'https://localhost:19443'
            with self.subTest(field=field), self.assertRaises(PackageError):
                self.state.verify_trust(self.public['trust'], self.pin)
            self.state.data['bootstrap'][field] = original
        with self.assertRaisesRegex(PackageError, 'server_refused'):
            self.state.verify_trust(self.public['trust'], '0' * 64)

    def test_trust_rollback_and_equal_generation_payload_conflict(self):
        self.state.verify_trust(self.public['trust'], self.pin)
        self.state.verify_trust(self.public['trust'], self.pin)
        self.state.data['trust']['generation'] = 2
        with self.assertRaisesRegex(PackageError, 'rollback'):
            self.state.verify_trust(self.public['trust'], self.pin)
        self.state.data['trust']['generation'] = 1
        self.state.data['trust']['payload_sha256'] = '0' * 64
        with self.assertRaisesRegex(PackageError, 'conflict'):
            self.state.verify_trust(self.public['trust'], self.pin)

    def test_clock_reboot_backward_expiry_and_explicit_confirmation(self):
        self.state.verify_trust(self.public['trust'], self.pin)
        original = deepcopy(self.state.data['clock'])
        self.state.data['clock']['boot'] = 'different'
        with self.assertRaisesRegex(PackageError, 'confirmation_required'):
            self.state.now()
        self.state.confirm_time(self.now)
        with patch('kiosk.display.delivery_authority.time.time', return_value=self.now - 100):
            with self.assertRaisesRegex(PackageError, 'uncertain_time'):
                self.state.now()
        with patch('kiosk.display.delivery_authority.time.time', return_value=self.now + 8 * 86400):
            with self.assertRaisesRegex(PackageError, 'time_refused'):
                self.state.verify_trust(self.public['trust'], self.pin)
        self.assertEqual(original['boot'], self.state.data['clock']['boot'])

    def test_bootstrap_bounds_key_digest_expiry_and_origin(self):
        self.assertEqual(bootstrap(self.anchor, self.now), self.anchor)
        with self.assertRaisesRegex(PackageError, 'expired'):
            bootstrap(self.anchor, self.anchor['expires_at'])
        for value in ('http://localhost:8443', 'https://localhost', 'https://user@localhost:8443',
                      'https://localhost:8443/', 'https://localhost:8443?x=1', 'https://localhost:8443#x'):
            with self.subTest(value=value), self.assertRaises(PackageError):
                origin(value)
        bad = deepcopy(self.anchor)
        bad['group_key_id'] = '0' * 64
        with self.assertRaisesRegex(PackageError, 'key_mismatch'):
            bootstrap(bad, self.now)

    def test_offline_association_exact_facts_without_new_authority(self):
        self.state.data.update(binding={'device_id': 'device', 'request_id': 'request', 'profile': PROFILE},
                               credential={'expires_at': self.now + 30})
        self.state.verify_trust(self.public['trust'], self.pin)
        metadata = {'package_id': 'c' * 64}
        assignment = {'version': 1, 'group_id': self.anchor['group_id'], 'device_id': 'device', 'profile': PROFILE,
                      'generation': 1, 'metadata_sha256': sha(encode(metadata)), 'publication': metadata}
        self.state.accept(assignment)
        self.state.data.update(revoked=True, clock={'boot': 'wrong'})
        self.assertEqual(self.state.accepted('c' * 64)['generation'], 1)
        with self.assertRaises(PackageError):
            self.state.accept(assignment)
        self.state.data['binding']['request_id'] = 'another'
        with self.assertRaisesRegex(PackageError, 'association_refused'):
            self.state.accepted('c' * 64)

    def test_assignment_durable_rollback_conflict_and_binding(self):
        self.state.data['binding'] = {'device_id': 'device', 'profile': PROFILE}
        value = {'version': 1, 'group_id': self.anchor['group_id'], 'device_id': 'device', 'profile': PROFILE,
                 'generation': 2, 'metadata_sha256': sha(encode({})), 'publication': {}}
        self.state.validate_assignment(value)
        self.state = PrivateState(self.root)
        for changed in ({'generation': 1}, {'device_id': 'other'}, {'metadata_sha256': '0' * 64},
                        {'publication': {'changed': True}, 'metadata_sha256': sha(encode({'changed': True}))}):
            with self.subTest(changed=changed), self.assertRaises(PackageError):
                self.state.validate_assignment({**value, **changed})


class Response(BytesIO):
    def __init__(self, payload, status=200, headers=None, interrupt=False):
        super().__init__(payload)
        self.status, self.headers, self.interrupt = status, headers or {}, interrupt

    def getheader(self, name, default=None):
        return self.headers.get(name, default)

    def read(self, size=-1):
        if self.interrupt and self.tell() >= 65536:
            raise TransportError('controlled_interruption')
        return super().read(size)


class ArtifactTransport:
    def __init__(self, root):
        self.root, self.requests = root, []
        self.interrupt, self.change_headers, self.full_after_range, self.fail_status = False, {}, False, 0

    @contextmanager
    def response(self, path, headers):
        self.requests.append((path, headers))
        relative = path.split('/', 5)[5]
        payload = (self.root / relative).read_bytes()
        offset = int(headers.get('Range', 'bytes=0-')[6:-1])
        status = 206 if offset else 200
        if self.full_after_range:
            status, offset = 200, 0
        if self.fail_status:
            status = self.fail_status
        response_headers = {'ETag': '"' + sha(payload) + '"', 'Accept-Ranges': 'bytes',
                            'Content-Length': str(len(payload) - offset), 'Content-Type': 'application/octet-stream'}
        if status == 206:
            response_headers['Content-Range'] = f'bytes {offset}-{len(payload)-1}/{len(payload)}'
        response_headers.update(self.change_headers)
        yield Response(payload[offset:], status, response_headers, self.interrupt)


class NativeCaptureTests(unittest.TestCase):
    def setUp(self):
        self.fixture = fixtures.ExportTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.fixture.export()
        self.root = self.fixture.root
        state = DeliveryState(self.root / 'delivery')
        self.metadata = publish(state, self.fixture.destination)
        self.source = state.root / 'publications' / self.metadata['package_id']
        self.assignment = {'version': 1, 'group_id': 'group', 'device_id': 'device', 'profile': PROFILE,
                           'generation': 1, 'metadata_sha256': sha(encode(self.metadata)), 'publication': self.metadata}
        self.capture_root = self.root / 'capture'
        self.capture_root.mkdir()
        self.capture = Capture(self.capture_root)
        self.transport = ArtifactTransport(self.source)

    def test_complete_capture_verification_and_unchanged_no_download(self):
        package = self.capture.fetch(self.assignment, self.transport)
        count = len(self.transport.requests)
        self.assertTrue((package / 'manifest.json').exists())
        self.capture.fetch(self.assignment, self.transport)
        self.assertEqual(len(self.transport.requests), count)

    def test_verified_reuse_never_changes_original_bytes(self):
        self.capture.reuse_roots = (self.source,)
        before = {p: p.read_bytes() for p in self.source.rglob('*') if p.is_file()}
        self.capture.fetch(self.assignment, self.transport)
        self.assertEqual(self.transport.requests, [])
        self.assertGreater(self.capture.stats['reused_bytes'], 0)
        self.assertTrue(all(p.read_bytes() == data for p, data in before.items()))

    def test_measured_image_time_refuses_without_claiming_decoder_cancellation(self):
        with patch('kiosk.display.delivery_capture.time.monotonic', side_effect=[0, 0, 6]):
            with self.assertRaisesRegex(PackageError, 'image_elapsed_budget'):
                verify_captured(self.source, self.metadata)

    def _large(self):
        # Transport boundary only; final package admission must reject the arbitrary added file.
        payload = secrets.token_bytes(200000)
        path = self.source / 'package/large.bin'
        path.write_bytes(payload)
        entry = {'path': 'large.bin', 'size': len(payload), 'sha256': sha(payload)}
        return payload, entry

    def test_interrupted_durable_prefix_fresh_capture_resume_and_hash(self):
        payload, entry = self._large()
        target = self.capture_root / 'large.bin'
        journal = {'offsets': {}}
        jp = self.capture_root / 'prefix.json'
        self.transport.interrupt = True
        with self.assertRaises(TransportError):
            self.capture._download(target, 'package/large.bin', entry, self.metadata['package_id'], self.transport, journal, jp)
        self.assertEqual(target.stat().st_size, 65536)
        self.assertEqual(json.loads(jp.read_text())['offsets']['package/large.bin'], 65536)
        fresh = Capture(self.capture_root)
        self.transport.interrupt = False
        fresh._download(target, 'package/large.bin', entry, self.metadata['package_id'], self.transport, json.loads(jp.read_text()), jp)
        self.assertEqual(target.read_bytes(), payload)
        self.assertEqual(fresh.stats['resumed_offsets'], [65536])

    def test_200_after_range_replaces_prefix_and_crash_length_reconciles(self):
        payload, entry = self._large()
        target = self.capture_root / 'large.bin'
        target.write_bytes(payload[:70000])
        journal = {'offsets': {'package/large.bin': 65536}}
        self.transport.full_after_range = True
        self.capture._download(target, 'package/large.bin', entry, self.metadata['package_id'], self.transport, journal, self.capture_root/'prefix.json')
        self.assertEqual(target.read_bytes(), payload)
        self.assertEqual(self.capture.stats['restarts'], ['full_200_after_range'])

    def test_bad_validator_range_length_and_416_are_bounded(self):
        payload, entry = self._large()
        for headers in ({'ETag': '"wrong"'}, {'Content-Range': 'bytes 0-0/1'}, {'Content-Length': '1'}):
            target = self.capture_root / 'large.bin'
            target.write_bytes(payload[:65536])
            self.transport.change_headers = headers
            with self.subTest(headers=headers), self.assertRaises(PackageError):
                self.capture._download(target, 'package/large.bin', entry, self.metadata['package_id'], self.transport,
                                       {'offsets': {'package/large.bin': 65536}}, self.capture_root/'prefix.json')
        self.transport.change_headers, self.transport.fail_status = {}, 416
        self.transport.requests.clear()
        with self.assertRaises(TransportError):
            self.capture._download(target, 'package/large.bin', entry, self.metadata['package_id'], self.transport,
                                   {'offsets': {'package/large.bin': 65536}}, self.capture_root/'prefix.json')
        self.assertEqual(len(self.transport.requests), 1)

    def test_budget_disk_reserve_and_full_hash_failure_preserve_old_store(self):
        item = deepcopy(self.metadata)
        item['package']['files'] = [{'path': f'file-{i}', 'size': 64*1024*1024, 'sha256': 'a'*64} for i in range(4)]
        with self.assertRaisesRegex(PackageError, 'capture_limit'):
            validate_metadata(item)
        with patch('kiosk.display.delivery_capture.shutil.disk_usage', return_value=Mock(free=0)):
            with self.assertRaisesRegex(PackageError, 'disk_full'):
                self.capture.fetch(self.assignment, self.transport)
        payload, entry = self._large()
        target = self.capture_root/'hash.bin'
        wrong = {**entry, 'sha256': 'a'*64}
        # The server falsely echoes the claimed validator but sends different bytes.
        self.transport.change_headers = {'ETag': '"' + wrong['sha256'] + '"'}
        with self.assertRaisesRegex(PackageError, 'hash_refused'):
            self.capture._download(target, 'package/large.bin', wrong, self.metadata['package_id'], self.transport,
                                   {'offsets': {}}, self.capture_root/'prefix.json')
        self.assertEqual(self.capture.stats['restarts'], ['hash_mismatch', 'hash_mismatch'])
        self.assertEqual(target.stat().st_size, 0)

    def test_assignment_change_full_resync_and_unowned_capture(self):
        self.capture.fetch(self.assignment, self.transport)
        self.transport.requests.clear()
        changed = {**self.assignment, 'generation': 2}
        self.capture.fetch(changed, self.transport)
        self.assertGreater(len(self.transport.requests), 0)
        self.transport.requests.clear()
        self.capture.fetch(changed, self.transport, full_resync=True)
        self.assertGreater(len(self.transport.requests), 0)
        (self.capture_root / 'owner.json').write_text('{}')
        with self.assertRaisesRegex(PackageError, 'unowned_capture'):
            self.capture.reset()

    def test_incompatible_and_alias_inventory_refused_before_network(self):
        variants = []
        for key, value in [('resource_profile', 'other'), ('limits', {}), ('renderer', {}), ('package_id', 'bad')]:
            item = deepcopy(self.metadata)
            item[key] = value
            variants.append(item)
        item = deepcopy(self.metadata)
        item['package']['files'].append(dict(item['package']['files'][0]))
        variants.append(item)
        for item in variants:
            with self.subTest(item=item.get('resource_profile')), self.assertRaises((PackageError, DeliveryError)):
                self.capture.fetch({**self.assignment, 'publication': item}, self.transport)
        self.assertEqual(self.transport.requests, [])

    def test_missing_corrupt_file_and_activation_failure_preserve_active(self):
        store = PublicationStore(self.root/'store')
        store.install(self.fixture.destination)
        before = (store.root/'active.json').read_bytes()
        self.transport.fail_status = 409
        with self.assertRaises(TransportError):
            self.capture.fetch(self.assignment, self.transport)
        self.assertEqual((store.root/'active.json').read_bytes(), before)
        self.transport.fail_status = 0
        self.capture.fetch(self.assignment, self.transport)
        (self.capture_root/'work/package/data/events.json').write_bytes(b'corrupt')
        with self.assertRaises(PackageError):
            store.install(self.capture_root/'work/package')
        self.assertEqual((store.root/'active.json').read_bytes(), before)


class NativeClientTests(unittest.TestCase):
    def test_enrollment_secret_precedes_request_and_lost_responses_recover_same_credential(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            public = json.loads(PUBLIC.read_text())
            bootstrap_path = root/'bootstrap.json'
            bootstrap_path.write_bytes(encode(public['bootstrap']))
            now = public['bootstrap']['issued_at'] + 60
            server = DeliveryState(root/'server', clock=lambda: now)
            (server.root/'public.json').write_bytes(encode(public))
            client = Client.__new__(Client)
            (root/'private').mkdir()
            client.native = PrivateState(root/'private')
            fake = Mock()
            lost = {'authorize': True, 'token': True, 'approval_pending': False}

            def call(path, *, body=None, **kwargs):
                state = PrivateState(root/'private').data
                self.assertEqual(state['secret'], client.native.data['secret'])
                if path.endswith('/status'):
                    if lost['approval_pending']:
                        raise TransportError('pending_before_operator_decision', 401)
                    try:
                        return server._device(server.authenticate(state['secret']))
                    except DeliveryError:
                        raise TransportError('unauthorized', 401)
                if path.endswith('/authorize'):
                    result = server.begin(body)
                    if lost['authorize']:
                        lost['authorize'] = False
                        raise TransportError('lost_authorize_response')
                    return result
                if lost['approval_pending']:
                    binding = client.native.data['binding']
                    pending = client.native.data['pending']
                    server.approve(binding['request_id'], {'decision': 'approve', 'user_code': pending['user_code'],
                                                         'binding_sha256': sha(encode(binding))})
                    lost['approval_pending'] = False
                result = server.poll(body)
                if result['state'] == 'approved' and lost['token']:
                    lost['token'] = False
                    raise TransportError('lost_token_response')
                return result

            fake.json.side_effect = call
            client.connect = lambda: fake
            with patch('kiosk.display.delivery_authority.time.time', return_value=now):
                with self.assertRaisesRegex(TransportError, 'lost_authorize'):
                    client.enroll(bootstrap_path, sha(bootstrap_path.read_bytes()), now)
                original = deepcopy(client.native.data)
                pending = client.enroll()
                binding = client.native.data['binding']
                lost['approval_pending'] = True
                client.native.data['next_poll'] = now - 1
                with self.assertRaisesRegex(TransportError, 'lost_token'):
                    client.enroll()
                # /status recovers the same approved metadata even if the token reply was lost.
                approved = client.enroll()
                self.assertEqual(approved['result'], 'approved')
                self.assertEqual(original['secret'], client.native.data['secret'])
                self.assertEqual(original['binding'], client.native.data['binding'])
                identity = client.native.data['credential']['credential_id']
                self.assertEqual(client.enroll()['result'], 'approved')
                self.assertEqual(client.native.data['credential']['credential_id'], identity)

    def test_stale_native_status_cannot_queue_ready(self):
        client = Client.__new__(Client)
        client.native = Mock()
        native = Mock()
        native.process.poll.return_value = None
        native.process.pid = 123
        native.pending, native.receipt_pending, native.session = None, False, 'fresh'
        with patch('kiosk.display.delivery_client._view_identity', return_value='a'*64), \
                patch('kiosk.display.delivery_client._read_json', return_value={'session_id': 'stale'}):
            with self.assertRaisesRegex(PackageError, 'not_confirmed'):
                client.queue_ready(native)
        client.native.save.assert_not_called()

    def test_actual_redirect_and_tls_failure_are_rejected_before_content(self):
        transport = Transport(json.loads(PUBLIC.read_text())['bootstrap'], secret='a' * 64)
        connection = Mock()
        response = Mock(status=302)
        connection.getresponse.return_value = response
        with patch('kiosk.display.delivery_transport.http.client.HTTPSConnection', return_value=connection), \
                patch('kiosk.display.delivery_transport.certificate_spki', return_value=b'public-spki'):
            with self.assertRaisesRegex(TransportError, 'redirect_refused'):
                transport.json('/api/v2/group/trust')
        connection.close.assert_called_once()
        connection.request.assert_called_once()
        import ssl
        connection.reset_mock()
        connection.connect.side_effect = ssl.SSLCertVerificationError('controlled wrong chain/name')
        with patch('kiosk.display.delivery_transport.http.client.HTTPSConnection', return_value=connection):
            with self.assertRaisesRegex(TransportError, 'network_unavailable'):
                transport.json('/api/v2/group/trust')
        connection.request.assert_not_called()

    def test_outbox_lost_ack_retries_exact_body_and_id(self):
        client = Client.__new__(Client)
        body = {'receipt_id': 'stable-real-session-id'}
        client.native = Mock()
        client.native.data = {'outbox': [body]}
        client.native.save.side_effect = [OSError('controlled durable-write failure'), None]
        transport = Mock()
        transport.json.return_value = {'version': 1, 'receipt_id': body['receipt_id'], 'state': 'recorded'}
        client.connect = lambda: transport
        with self.assertRaises(OSError):
            client.flush_ready()
        # Simulated fresh process loads the durable pre-ack queue.
        client.native.data = {'outbox': [deepcopy(body)]}
        client.flush_ready()
        self.assertEqual(transport.json.call_args_list[0], transport.json.call_args_list[1])
        self.assertEqual(client.native.data['outbox'], [])

    def test_expired_or_revoked_status_stops_new_authority(self):
        client = Client.__new__(Client)
        client.native = Mock()
        client.native.data = {'revoked': True}
        client.connect = Mock()
        with self.assertRaisesRegex(PackageError, 'revoked'):
            client._online_authority()
        client.connect.assert_not_called()

    def test_redirect_and_scope_have_no_http_fallback(self):
        anchor = json.loads(PUBLIC.read_text())['bootstrap']
        transport = Transport(anchor, secret='a' * 64)
        self.assertTrue(transport.context.check_hostname)
        import ssl
        self.assertEqual(transport.context.verify_mode, ssl.CERT_REQUIRED)
        for path in ('http://attacker.invalid/', '/admin/devices/pending', '/api/v2/x\r\nX: value'):
            with self.subTest(path=path), self.assertRaises(PackageError):
                with transport.response(path):
                    pass
