"""Native Windows publisher controller over a real DPAPI key and exact bytes."""
import base64
import contextlib
import copy
import io
import os
import tempfile
import unittest
from pathlib import Path

from kiosk.delivery.protocol import PROFILE, decode, encode, sha
from kiosk.delivery.state import DeliveryState
from kiosk.publication import authority as a
from kiosk.publication.materialize import prepare_publication
from kiosk.publication.publish_ui import CANDIDATE_PATH, PublisherBridge, bundle
from kiosk.publication.publisher import LocalPublisher
from kiosk.publication.workspace import Workspace
from tools.publisher_authority import init, authorize


class FakeResponse:
    def __init__(self, payload):
        self.payload = io.BytesIO(payload)
        self.status = 200
        self.headers = {'ETag': '"%s"' % sha(payload), 'Accept-Ranges': 'bytes',
                        'Content-Type': 'application/octet-stream',
                        'Content-Length': str(len(payload))}

    def getheader(self, name, default=None):
        return self.headers.get(name, default)

    def read(self, size=-1):
        return self.payload.read(size)


class FakeTransport:
    """Serves exactly the prepared catalog bytes; records the approval body."""

    def __init__(self, state, document, tamper=False):
        self.state, self.document, self.tamper = state, document, tamper
        self.approvals = []

    def json(self, path, *, body=None, authenticated=True):
        if body is None and path.startswith(CANDIDATE_PATH):
            return decode(encode(self.document))
        if path == '/editor/native/approve' and body is not None:
            self.approvals.append(body)
            return {'state': 'approved'}
        raise AssertionError('unexpected route ' + path)

    @contextlib.contextmanager
    def response(self, path, headers=None, *, authenticated=True):
        prefix = CANDIDATE_PATH + self.document['plan']['id'] + '/'
        assert path.startswith(prefix), path
        # Candidate review bytes are public; the publisher transport has no device secret.
        assert authenticated is False
        relative = path[len(prefix):]
        group, name = relative.split('/', 1)
        payload = (self.state.root / 'publications' / self.document['publication']['package_id']
                   / group / name).read_bytes()
        if self.tamper and name == 'data/events.json':
            value = decode(payload)
            value['events'][0]['title'] = 'Substituted'
            payload = encode(value)
        response = FakeResponse(payload)
        entry = next(item for item in self.document['publication'][group]['files']
                     if item['path'] == name)
        response.headers['ETag'] = '"' + entry['sha256'] + '"'
        yield response


class FailingTransport(FakeTransport):
    """Simulates a lost response after signing but before server acknowledgement."""

    def json(self, path, *, body=None, authenticated=True):
        if body is not None:
            raise OSError('network_unavailable')
        return super().json(path, body=body, authenticated=authenticated)


@unittest.skipUnless(os.name == 'nt', 'Windows DPAPI publisher boundary')
class WindowsPublisherBridgeTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        folder = Path(self.tmp.name)
        self.now = 2_000_000_000
        self.password = 'disposable bridge test password'
        self.public = init(folder / 'offline', 'group', 'https://kiosk.example:20443',
                           self.password, self.now)
        self.publisher = LocalPublisher(folder / 'keys')
        self.identity = self.publisher.create()
        request = self.publisher.public_request('group', self.public['origin'], 'alice', self.now)
        self.bundle = authorize(folder / 'offline', self.password, request, 'user', 'alice', self.now)
        self.publisher.install(base64.b64decode(self.bundle['root_spki']), self.public['root_sha256'],
                               self.bundle['policy'], self.bundle['chain'], self.bundle['group_id'],
                               self.bundle['origin'], self.now)
        self.workspace = Workspace(folder / 'workspace.sqlite',
                                   base64.b64decode(self.bundle['root_spki']), 'group',
                                   self.public['origin'], clock=lambda: self.now)
        self.workspace.install_policy(self.bundle['policy'])
        browser = 'b' * 64
        token, challenge = self.workspace.create_login(browser, 'Chrome')
        self.chain = self.bundle['chain']
        self.workspace.accept_login(token, a.signed(self.private_key(), 'login', challenge), self.chain)
        self.secret = self.workspace.consume_login(token, browser)[0]
        self.uploads = folder / 'uploads'
        self.uploads.mkdir()
        self.delivery = self.delivery_state(folder)

    def private_key(self):
        return self.publisher._read()[1]

    def delivery_state(self, folder):
        state = DeliveryState(folder / 'delivery', clock=lambda: self.now)
        (state.root / 'public.json').write_bytes(encode(dict(version=1, group_id='group',
            server_id='server', origin=self.public['origin'], bootstrap={}, trust={})))
        from kiosk.display.cache import renderer_identity
        with state.connection() as db:
            db.execute("INSERT OR REPLACE INTO display_profiles VALUES ('events-tv','Events TV','tv',3)")
            db.execute("INSERT OR REPLACE INTO device_profiles VALUES ('display1','events-tv')")
            db.execute("INSERT OR REPLACE INTO device_capabilities VALUES ('display1',?)",
                       (encode(dict(version=1, platform='windows', modes=['tv'], content=['events'],
                                    resource_profile=PROFILE, renderer=renderer_identity())),))
            db.execute('INSERT OR REPLACE INTO devices VALUES (?,?,?,?,?,0)',
                       ('display1', PROFILE, 'c' * 64, 'v' * 64, self.now + 86400))
        return state

    def prepare(self):
        event = dict(title='Prepared Event', short_description='', full_description='',
                     event_date='2026-11-16', place='Hall', sort_order=0, status='active',
                     images=[], tags=['News'])
        self.workspace.save(self.secret, '1', 0, event, {})
        self.workspace.ready(self.secret, '1', 1)
        self.workspace.update_settings(self.secret, 0, {'site_title': 'Museum'})
        return prepare_publication(self.workspace, self.secret, {'1': 1},
                                   self.delivery.publisher_targets(), [], self.delivery,
                                   self.uploads, Path('kiosk'))

    def test_review_then_explicit_publish_posts_exact_approval(self):
        document = self.prepare()
        transport = FakeTransport(self.delivery, document)
        bridge = PublisherBridge(self.publisher, transport, self.publisher.root,
                                 lambda: self.now)
        candidate = bridge.open(document['plan']['id'])
        facts = bridge.summarize(candidate)
        self.assertEqual(facts['events'][0]['title'], 'Prepared Event')
        self.assertEqual(facts['settings'], {'site_title': 'Museum'})
        self.assertEqual(facts['targets'][0]['device'], 'display1')
        self.assertEqual(facts['revision'], 1)
        self.assertEqual(transport.approvals, [])
        bridge.publish(candidate)
        self.assertEqual(len(transport.approvals), 1)
        posted = transport.approvals[0]
        verified, policy = a.approval(posted['approval'], posted['chain'], self.bundle['policy'],
                                      base64.b64decode(self.bundle['root_spki']), 'group',
                                      self.public['origin'], self.now,
                                      ancestry=document['ancestry'])
        self.assertEqual(verified['id'], document['plan']['id'])
        self.assertEqual(posted['id'], document['plan']['id'])
        bridge.discard(candidate)

    def test_substituted_candidate_bytes_are_refused_before_any_signature(self):
        document = self.prepare()
        transport = FakeTransport(self.delivery, document, tamper=True)
        bridge = PublisherBridge(self.publisher, transport, self.publisher.root,
                                 lambda: self.now)
        with self.assertRaises(ValueError):
            bridge.open(document['plan']['id'])
        self.assertEqual(transport.approvals, [])
        self.assertEqual(self.publisher.pending, {})

    def test_same_user_new_device_can_be_authorized_by_existing_device(self):
        child = LocalPublisher(Path(self.tmp.name) / 'child')
        child.create()
        request = child.public_request('group', self.public['origin'], 'alice', self.now)
        bridge = PublisherBridge(self.publisher, FakeTransport(self.delivery, self.prepare()),
                                 self.publisher.root, lambda: self.now)
        bundle_value = bridge.authorize_device(request)
        self.assertEqual(bundle_value['group_id'], 'group')
        child.install(base64.b64decode(bundle_value['root_spki']),
                      bundle_value['root_sha256'], bundle_value['policy'],
                      bundle_value['chain'], bundle_value['group_id'],
                      bundle_value['origin'], self.now)
        status = child.status(self.now)
        self.assertEqual((status['user_id'], status['role']), ('alice', 'user'))
        # A delegated child cannot delegate further.
        grand = LocalPublisher(Path(self.tmp.name) / 'grand')
        grand.create()
        with self.assertRaises(ValueError):
            child.authorize_own_device(
                grand.public_request('group', self.public['origin'], 'alice', self.now), self.now)

    def test_bundle_reader_is_bounded(self):
        path = Path(self.tmp.name) / 'bundle.json'
        path.write_bytes(encode(dict(root_spki='x')))
        self.assertEqual(bundle(path), {'root_spki': 'x'})
        path.write_bytes(b'{' + b'0' * 65536)
        with self.assertRaises(ValueError):
            bundle(path)

    def test_lost_response_keeps_exact_approval_for_restart_retry(self):
        document = self.prepare()
        failing = FailingTransport(self.delivery, document)
        bridge = PublisherBridge(self.publisher, failing, self.publisher.root,
                                 lambda: self.now)
        candidate = bridge.open(document['plan']['id'])
        with self.assertRaises(OSError):
            bridge.publish(candidate)
        pending = LocalPublisher(self.publisher.root).pending_approval()
        self.assertEqual(pending['id'], document['plan']['id'])
        self.assertNotIn(document['plan']['id'],
                          (LocalPublisher(self.publisher.root)._read()[0]
                           .get('publication_heads', [])))
        transport = FakeTransport(self.delivery, document)
        reopened = PublisherBridge(LocalPublisher(self.publisher.root), transport,
                                   self.publisher.root, lambda: self.now)
        response = reopened.retry()
        self.assertEqual(response['state'], 'approved')
        self.assertEqual(transport.approvals[-1]['id'], document['plan']['id'])
        self.assertEqual(transport.approvals[-1]['approval'], pending['approval'])
        self.assertIsNone(LocalPublisher(self.publisher.root).pending_approval())
        self.assertEqual(LocalPublisher(self.publisher.root)._read()[0]['publication_heads'],
                         [document['plan']['id']])
        with self.assertRaises(ValueError):
            reopened.retry()

    def test_duplicate_plan_cannot_be_signed_after_commit(self):
        document = self.prepare()
        transport = FakeTransport(self.delivery, document)
        bridge = PublisherBridge(self.publisher, transport, self.publisher.root,
                                 lambda: self.now)
        candidate = bridge.open(document['plan']['id'])
        bridge.publish(candidate)
        with self.assertRaises(ValueError):
            self.publisher.publish(candidate.ticket, self.now)

    def test_policy_conflict_group_replacement_and_explicit_root_recovery(self):
        import tools.publisher_authority as admin
        # Same policy version with different content is refused, not silently used.
        root_key, _, policy = admin.load(Path(self.tmp.name) / 'offline', self.password, self.now)
        conflicting = dict(policy)
        conflicting['expires'] += 1
        with self.assertRaises(ValueError):
            self.publisher.install(base64.b64decode(self.bundle['root_spki']),
                                   self.public['root_sha256'],
                                   a.signed(root_key, 'policy', conflicting), self.bundle['chain'],
                                   'group', self.public['origin'], self.now)
        # A different group with the same pinned root is a replacement, not a switch.
        other_policy = dict(policy, group_id='other', version=policy['version'] + 1)
        other_grant = a.signed(root_key, 'device', dict(
            group_id='other', origin=self.public['origin'], user_id='alice', role='user',
            issued=self.now, expires=policy['expires'], can_delegate=True,
            device_key=self.identity['device_key']))
        with self.assertRaisesRegex(ValueError, 'publisher_group_replacement_requires_recovery'):
            self.publisher.install(base64.b64decode(self.bundle['root_spki']),
                                   self.public['root_sha256'],
                                   a.signed(root_key, 'policy', other_policy), [other_grant],
                                   'other', self.public['origin'], self.now)
        # A second independently rooted authority is a recovery, never a normal import.
        second = init(Path(self.tmp.name) / 'offline2', 'group2',
                      'https://kiosk2.example:20443', self.password, self.now)
        request = self.publisher.public_request('group2', second['origin'], 'alice', self.now)
        bundle2 = authorize(Path(self.tmp.name) / 'offline2', self.password, request, 'user',
                            'alice', self.now)
        with self.assertRaisesRegex(ValueError, 'publisher_root_replacement_requires_recovery'):
            self.publisher.install(base64.b64decode(bundle2['root_spki']), second['root_sha256'],
                                   bundle2['policy'], bundle2['chain'], 'group2',
                                   bundle2['origin'], self.now)
        with self.assertRaisesRegex(ValueError, 'publisher_recovery_not_confirmed'):
            self.publisher.recover(base64.b64decode(bundle2['root_spki']), second['root_sha256'],
                                   bundle2['policy'], bundle2['chain'], 'group2',
                                   bundle2['origin'], self.now, 'no')
        self.publisher.recover(base64.b64decode(bundle2['root_spki']), second['root_sha256'],
                               bundle2['policy'], bundle2['chain'], 'group2',
                               bundle2['origin'], self.now, 'REPLACE')
        self.assertEqual(self.publisher.status(self.now)['group_id'], 'group2')
        self.assertIsNone(self.publisher._read()[0].get('publication_heads'))
        self.assertIsNone(self.publisher.pending_approval())


if __name__ == '__main__':
    unittest.main()
