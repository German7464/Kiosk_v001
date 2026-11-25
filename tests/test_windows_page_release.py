"""Synthetic Windows v4 page delivery, storage and native publisher boundaries."""
import base64
import contextlib
import copy
import io
import json
import os
import shutil
import tempfile
import time
import unittest
from pathlib import Path
from urllib.parse import urlencode
from unittest.mock import patch

from kiosk.delivery.protocol import LIMITS, PROFILE, decode, encode, sha
from kiosk.display import page_view
from kiosk.display.delivery_authority import PrivateState
from kiosk.display.delivery_capture import Capture
import kiosk.display.delivery_client as delivery_client
from kiosk.display.delivery_client import check_page_assignment, admit_page_package
from kiosk.display.native_crypto import protect
from kiosk.publication import authority as a
from kiosk.publication import page_release as r
from kiosk.publication.publisher import LocalPublisher
from kiosk.publication.publish_ui import (CANDIDATE_PATH, PAGE_APPROVE_PATH,
                                          PAGE_OPEN_PATH, PAGE_PACKAGE_PATH,
                                          PublisherBridge)
from kiosk.publication.store import _atomic_write
from kiosk.display.delivery_transport import TransportError
from kiosk.trust.crypto import generate_private_key, key_id, spki_der

NOW = 2_000_000_000


def object_id(kind, number=1):
    return f'{kind}-{number:032x}'


def spki(key):
    return base64.b64encode(spki_der(key)).decode('ascii')


def revision_graph():
    event, hidden = '1001', '1002'
    dataset, block, layout, page = [object_id(name) for name in
                                    ('dataset', 'block', 'layout', 'page')]
    profile = object_id('profile')
    windows, android = object_id('assignment', 1), object_id('assignment', 2)
    objects = {
        event: dict(version=1, author='alice', dependencies={}, payload={
            'title': 'Notice', 'short_description': 'Short', 'full_description': 'Full',
            'event_date': None, 'place': 'Hall', 'sort_order': 1, 'status': 'active',
            'images': [], 'tags': []}),
        hidden: dict(version=1, author='alice', dependencies={}, payload={
            'title': 'Hidden', 'short_description': '', 'full_description': '',
            'event_date': None, 'place': '', 'sort_order': 2, 'status': 'hidden',
            'images': [], 'tags': []}),
        dataset: dict(version=1, author='alice', dependencies={event: 1}, payload={
            'schema': 1, 'name': 'Events', 'module': 'events', 'events': [event]}),
        block: dict(version=1, author='alice', dependencies={dataset: 1}, payload={
            'schema': 1, 'name': 'Cards', 'dataset': dataset, 'tags': [], 'limit': 3,
            'appearance': 'cards'}),
        layout: dict(version=1, author='alice', dependencies={block: 1}, payload={
            'schema': 1, 'target': 'tv-landscape', 'columns': 4, 'rows': 3,
            'placements': [dict(block=block, x=0, y=0, w=2, h=3)]}),
        page: dict(version=1, author='alice', dependencies={layout: 1}, payload={
            'schema': 1, 'name': 'Notice board', 'order': 0,
            'layouts': {'tv-landscape': layout}, 'fallback': 'tv-landscape'}),
        profile: dict(version=1, author='admin', dependencies={page: 1}, payload={
            'schema': 1, 'name': 'Shared', 'selection': {
                'pages': [page], 'start_page': page, 'transition_seconds': 15}}),
        windows: dict(version=1, author='admin', dependencies={profile: 1}, payload={
            'schema': 1, 'device': 'screen-windows', 'profile': profile,
            'selection': None}),
        android: dict(version=1, author='admin', dependencies={profile: 1}, payload={
            'schema': 1, 'device': 'screen-android', 'profile': profile,
            'selection': None}),
    }
    included = [dict(id=identity, version=entry['version'], author=entry['author'])
                for identity, entry in objects.items() if identity != hidden]
    excluded = [dict(id=hidden, version=2, author='alice', reason='working')]
    return {'plan': {'included': included, 'excluded': excluded}, 'objects': objects}


def publication_for(revision, destination, content, renderer=None):
    pin = renderer or page_view.renderer_pin()
    revision_sha = r.revision_sha256(revision)
    files = [{'path': r.PAGE_ENTRYPOINT, 'size': len(content), 'sha256': sha(content)}]
    manifest = {'schema_version': 2, 'kind': 'pages', 'revision': revision_sha,
                'renderer': 'pages-v1', 'resource_contract': 1, 'files': files,
                'entrypoints': [r.PAGE_ENTRYPOINT]}
    raw_manifest = encode(manifest)
    package_id = sha(raw_manifest)
    inventory = [{'path': 'manifest.json', 'size': len(raw_manifest),
                  'sha256': package_id}, *files]
    publication = {'version': 2, 'package_id': package_id, 'revision': revision_sha,
                   'raw_manifest_sha256': package_id,
                   'renderer': {'build_id': pin['build_id'],
                                'js_sha256': pin['js_sha256'],
                                'css_sha256': pin['css_sha256']},
                   'resource_profile': PROFILE, 'limits': dict(LIMITS),
                   'windows_images': {}, 'package': {'files': inventory},
                   'kiosk': {'files': []}, 'tv': {'files': []}}
    return publication, {'package': {'manifest.json': raw_manifest,
                                     r.PAGE_ENTRYPOINT: content}, 'kiosk': {}, 'tv': {}}


class SyntheticRelease:
    def __init__(self):
        self.root_key, self.device = generate_private_key(), generate_private_key()
        self.group, self.origin = 'group', 'https://kiosk.example:20443'
        self.policy = dict(group_id=self.group, origin=self.origin, version=1,
                           issued=NOW - 100, expires=NOW + 86400,
                           revoked_devices=[], revoked_users=[])
        self.grant = dict(group_id=self.group, origin=self.origin, user_id='user1',
                          role='user', device_key=spki(self.device),
                          issued=NOW - 100, expires=NOW + 3600, can_delegate=False)
        self.chain = [a.signed(self.root_key, 'device', self.grant)]
        self.policy_envelope = a.signed(self.root_key, 'policy', self.policy)
        self.authorization = dict(group_id=self.group, origin=self.origin, user_id='user1',
                                  device_id=key_id(self.device), policy_version=1,
                                  issued=NOW, expires=NOW + 600)
        self.revision = revision_graph()
        self.windows = self._target('screen-windows', 'tv-landscape',
                                    'windows-pages-v1', 'tv')
        self.android = self._target('screen-android', 'kiosk-portrait',
                                    'android-pages-v1', 'kiosk')
        self.prepared = r.prepare_release(revision=self.revision,
                                          authorization=self.authorization,
                                          targets=[self.windows, self.android])
        self.document = self.prepared['document']
        self.proof = {'approval': a.page_signed(self.device, self.document['plan']),
                      'chain': self.chain, 'policy': self.policy_envelope}

    def _target(self, device, projection, destination, mode):
        content = encode(r.project_target(self.revision, device, projection))
        publication, files = publication_for(self.revision, destination, content)
        return {'device_id': device, 'projection': projection,
                'destination': destination,
                'configuration': {'version': 1, 'profile_id': f'{mode}-profile',
                                  'revision': 1, 'mode': mode},
                'publication': publication, 'files': files}

    def assignment(self, device='screen-windows', generation=1):
        target = next(item for item in self.document['targets']
                      if item['device_id'] == device)
        return {'version': 4, 'group_id': self.group, 'device_id': device,
                'profile': PROFILE, 'generation': generation,
                'revision_sha256': self.document['plan']['revision_sha256'],
                'destination': target['destination'], 'projection': target['projection'],
                'metadata_sha256': sha(encode(target['metadata'])),
                'metadata': target['metadata'], 'display': target['configuration'],
                'publisher': self.proof}

    def files(self, device='screen-windows'):
        return self.prepared['artifacts'][device]['files']

    def renderer_args(self, assignment):
        pin = page_view.renderer_pin()
        return {'expected_js_sha256': pin['js_sha256'],
                'expected_css_sha256': pin['css_sha256']}

    def admit(self, assignment=None):
        assignment = assignment or self.assignment()
        return r.admit(assignment['publisher'], assignment, spki_der(self.root_key),
                       self.origin, NOW, files=self.files(assignment['device_id']),
                       expected_group_id=self.group,
                       expected_device_id=assignment['device_id'],
                       expected_profile=PROFILE,
                       expected_destination=assignment['destination'],
                       **self.renderer_args(assignment))


def write_package(root, files):
    root = Path(root)
    for name, payload in files['package'].items():
        target = root / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(payload)
    return root


class PageViewTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.release = SyntheticRelease()
        target = next(item for item in self.release.document['targets']
                      if item['device_id'] == 'screen-windows')
        self.metadata = target['metadata']
        self.package = write_package(self.root / 'package',
                                     self.release.files('screen-windows'))

    def test_build_and_verify_use_pinned_renderer_and_exact_data(self):
        view = page_view.build_page_view(self.package, self.root / 'view', mode='tv',
                                         metadata=self.metadata)
        descriptor = json.loads((view.parent / 'view.json').read_bytes())
        self.assertEqual(descriptor['renderer'], 'pages-v1')
        self.assertEqual(descriptor['mode'], 'tv')
        self.assertEqual(descriptor['package_sha256'],
                         self.metadata['publication']['package_id'])
        html = view.read_bytes()
        for name in (b'page_display.js', b'page_display.css', b'page_bootstrap.js',
                     b'kiosk-page-data', b'kiosk-media'):
            self.assertIn(name, html)
        self.assertEqual(page_view.verify_page_view(view.parent,
                         package_identity=descriptor['package_sha256'], mode='tv'), view)
        # The canonical renderer bytes in the view are pinned, not package supplied.
        self.assertEqual(sha((view.parent / 'page_display.js').read_bytes()),
                         page_view.renderer_pin()['js_sha256'])
        (view.parent / 'page_display.js').write_bytes(b'tampered')
        with self.assertRaisesRegex(Exception, 'cached_renderer_mismatch|cached_view_integrity'):
            page_view.verify_page_view(view.parent,
                                       package_identity=descriptor['package_sha256'], mode='tv')

    def test_pinned_lf_renderer_bytes_are_enforced(self):
        pin = page_view.renderer_pin()
        self.assertEqual(pin['js_sha256'],
                         '3528358ae2bb2f8a85d2c5f58fed6ba8b1c98ea37d842931460657e6f063e20d')
        self.assertEqual(pin['css_sha256'],
                         'd3fd8af903cacb3e5e5d33df69663002bfb3a9157f432997e448c8d8266a54cf')
        with patch.object(page_view, 'PAGE_JS_SHA256', '0' * 64):
            with self.assertRaisesRegex(Exception, 'asset_pin'):
                page_view.renderer_pin()

    def test_package_tamper_data_only_and_wrong_mode_are_refused(self):
        extra = self.root / 'extra'
        shutil.copytree(self.package, extra)
        (extra / 'app.js').write_bytes(b'alert(1)')
        with self.assertRaisesRegex(ValueError, 'inventory|data_only'):
            page_view.verify_page_package(extra, self.metadata)
        content = self.package / r.PAGE_ENTRYPOINT
        original = content.read_bytes()
        content.write_bytes(original.replace(b'Notice', b'Other!'))
        with self.assertRaisesRegex(ValueError, 'inventory|content'):
            page_view.verify_page_package(self.package, self.metadata)
        content.write_bytes(original)
        with self.assertRaisesRegex(ValueError, 'page_view_mode'):
            page_view.build_page_view(self.package, self.root / 'kiosk-view', mode='kiosk',
                                      metadata=self.metadata)


class FakeResponse:
    def __init__(self, payload, entry):
        self.payload = io.BytesIO(payload)
        self.status = 200
        self.entry = entry

    def getheader(self, name, default=None):
        headers = {'ETag': '"' + self.entry['sha256'] + '"', 'Accept-Ranges': 'bytes',
                   'Content-Type': 'application/octet-stream',
                   'Content-Length': str(self.entry['size'])}
        return headers.get(name, default)

    def read(self, size=-1):
        return self.payload.read(size)


class PageStorageTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.release = SyntheticRelease()
        target = next(item for item in self.release.document['targets']
                      if item['device_id'] == 'screen-windows')
        self.metadata = target['metadata']
        self.package = write_package(self.root / 'package',
                                     self.release.files('screen-windows'))
        self.store = self.root / 'store'
        self.cache = self.root / 'cache'
        self.store.mkdir()
        self.cache.mkdir()
        self.package_id = self.metadata['publication']['package_id']

    def test_install_activate_and_reuse_cached_view(self):
        view = page_view.install_page_for_display(self.package, self.metadata,
                                                  self.store, self.cache, mode='tv')
        self.assertTrue(view.is_file())
        self.assertEqual(page_view.active_page_package(self.store), self.package_id)
        self.assertEqual(page_view.active_kind(self.store), 'pages')
        self.assertEqual(page_view.prepare_cached_page_view(self.store, self.cache,
                                                            mode='tv'), view)
        (view.parent / 'page_display.css').write_bytes(b'tampered')
        with self.assertRaisesRegex(Exception, 'cached_|invalid_cached_view'):
            page_view.prepare_cached_page_view(self.store, self.cache, mode='tv')

    def test_invalid_candidate_keeps_previous_active_pointer(self):
        page_view.install_page_for_display(self.package, self.metadata,
                                           self.store, self.cache, mode='tv')
        pointer = (self.store / 'pages' / 'active.json').read_bytes()
        broken = write_package(self.root / 'broken',
                               self.release.files('screen-windows'))
        (broken / r.PAGE_ENTRYPOINT).write_bytes(b'{}')
        with self.assertRaises(ValueError):
            page_view.install_page_for_display(broken, self.metadata, self.store,
                                               self.cache, mode='tv')
        self.assertEqual((self.store / 'pages' / 'active.json').read_bytes(), pointer)
        self.assertEqual(page_view.active_page_package(self.store), self.package_id)

    def test_restart_reads_durable_page_pointer(self):
        view = page_view.install_page_for_display(self.package, self.metadata,
                                                  self.store, self.cache, mode='tv')
        # A fresh process has only the durable pages pointer, metadata and view.
        self.assertTrue((self.store / 'pages' / 'active.json').is_file())
        self.assertEqual(page_view.active_kind(self.store), 'pages')
        self.assertEqual(page_view.active_page_package(self.store), self.package_id)
        self.assertEqual(page_view.prepare_cached_page_view(self.store, self.cache, mode='tv'),
                         view)

    def test_wrong_target_metadata_is_refused_before_storage(self):
        android = next(item for item in self.release.document['targets']
                       if item['device_id'] == 'screen-android')
        with self.assertRaises(ValueError):
            page_view.install_page_for_display(self.package, android['metadata'],
                                               self.store, self.cache, mode='tv')
        self.assertIsNone(page_view.active_page_package(self.store))


class PackageTransport:
    def __init__(self, files, tamper=None):
        self.files = files
        self.tamper = tamper

    @contextlib.contextmanager
    def response(self, path, headers=None, *, authenticated=True):
        relative = path.split('/package/', 1)[1]
        entry = None
        for item in self.inventory:
            if item['path'] == relative:
                entry = item
        payload = self.files['package'][relative]
        if self.tamper == relative:
            payload = bytes([payload[0] ^ 0xFF]) + payload[1:]
        yield FakeResponse(payload, entry)


class CaptureTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.release = SyntheticRelease()
        self.assignment = self.release.assignment()
        self.files = self.release.files()
        self.inventory = self.assignment['metadata']['publication']['package']['files']

    def transport(self, tamper=None):
        value = PackageTransport(self.files, tamper)
        value.inventory = self.inventory
        return value

    def test_exact_package_download(self):
        (self.root / 'capture').mkdir()
        capture = Capture(self.root / 'capture')
        package = capture.fetch_pages(self.assignment, self.transport())
        self.assertEqual((package / 'manifest.json').read_bytes(),
                         self.files['package']['manifest.json'])
        self.assertIn('page-release.json', ''.join(os.listdir(package / 'data')))

    def test_byte_substitution_is_refused(self):
        (self.root / 'capture').mkdir()
        capture = Capture(self.root / 'capture')
        with self.assertRaisesRegex(ValueError, 'artifact_hash_refused'):
            capture.fetch_pages(self.assignment,
                                self.transport(tamper=r.PAGE_ENTRYPOINT))

    def test_inner_manifest_mismatch_and_wrong_package_are_refused(self):
        files = copy.deepcopy(self.files)
        manifest = decode(files['package']['manifest.json'])
        manifest['files'][0]['size'] += 1
        files['package']['manifest.json'] = encode(manifest)
        assignment = copy.deepcopy(self.assignment)
        inventory = assignment['metadata']['publication']['package']['files']
        outer = next(item for item in inventory if item['path'] == 'manifest.json')
        outer['size'] = len(files['package']['manifest.json'])
        outer['sha256'] = sha(files['package']['manifest.json'])
        assignment['metadata']['publication']['package_id'] = outer['sha256']
        assignment['metadata']['publication']['raw_manifest_sha256'] = outer['sha256']
        (self.root / 'capture').mkdir()
        capture = Capture(self.root / 'capture')
        inventory = assignment['metadata']['publication']['package']['files']
        with self.assertRaisesRegex(ValueError, 'package_inventory|manifest'):
            capture.fetch_pages(assignment, self._transport(files, inventory))
        broken = copy.deepcopy(self.assignment)
        broken['metadata']['publication']['package_id'] = '0' * 64
        with self.assertRaisesRegex(ValueError, 'package_identity|manifest'):
            (self.root / 'capture2').mkdir(exist_ok=True)
            Capture(self.root / 'capture2').fetch_pages(broken, self._transport(self.files))

    def _transport(self, files, inventory=None):
        value = PackageTransport(files)
        value.inventory = inventory or self.inventory
        return value


class AdmissionTests(unittest.TestCase):
    def setUp(self):
        self.release = SyntheticRelease()

    def test_matching_admission_and_cross_target_refusal(self):
        admitted = self.release.admit()
        self.assertEqual(admitted['plan'], self.release.document['plan'])
        windows = self.release.assignment()
        with self.assertRaisesRegex(ValueError, 'inventory'):
            r.admit(windows['publisher'], windows, spki_der(self.release.root_key),
                    self.release.origin, NOW,
                    files=self.release.files('screen-android'),
                    expected_group_id=self.release.group,
                    expected_device_id='screen-windows', expected_profile=PROFILE,
                    expected_destination='windows-pages-v1',
                    **self.release.renderer_args(windows))

    def test_wrong_local_identity_renderer_and_target(self):
        windows = self.release.assignment()
        files = self.release.files()
        pin = page_view.renderer_pin()
        with self.assertRaisesRegex(ValueError, 'local_identity'):
            r.admit(windows['publisher'], windows, spki_der(self.release.root_key),
                    self.release.origin, NOW, files=files,
                    expected_group_id=self.release.group,
                    expected_device_id='screen-android', expected_profile=PROFILE,
                    expected_destination='windows-pages-v1',
                    expected_js_sha256=pin['js_sha256'],
                    expected_css_sha256=pin['css_sha256'])
        with self.assertRaisesRegex(ValueError, 'local_identity'):
            r.admit(windows['publisher'], windows, spki_der(self.release.root_key),
                    self.release.origin, NOW, files=files,
                    expected_group_id=self.release.group,
                    expected_device_id='screen-windows', expected_profile=PROFILE,
                    expected_destination='android-pages-v1',
                    expected_js_sha256=pin['js_sha256'],
                    expected_css_sha256=pin['css_sha256'])
        with self.assertRaisesRegex(ValueError, 'renderer_mismatch'):
            r.admit(windows['publisher'], windows, spki_der(self.release.root_key),
                    self.release.origin, NOW, files=files,
                    expected_group_id=self.release.group,
                    expected_device_id='screen-windows', expected_profile=PROFILE,
                    expected_destination='windows-pages-v1',
                    expected_js_sha256='0' * 64,
                    expected_css_sha256=pin['css_sha256'])
        swapped = copy.deepcopy(windows)
        swapped['projection'] = 'tv-portrait'
        with self.assertRaisesRegex(ValueError, 'substitution'):
            r.admit(swapped['publisher'], swapped, spki_der(self.release.root_key),
                    self.release.origin, NOW, files=files,
                    expected_group_id=self.release.group,
                    expected_device_id='screen-windows', expected_profile=PROFILE,
                    expected_destination='windows-pages-v1',
                    expected_js_sha256=pin['js_sha256'],
                    expected_css_sha256=pin['css_sha256'])

    def test_v1_and_v3_assignments_are_refused_on_the_page_path(self):
        windows = self.release.assignment()
        files = self.release.files()
        pin = page_view.renderer_pin()
        for version in (1, 3):
            changed = copy.deepcopy(windows)
            changed['version'] = version
            with self.subTest(version=version), self.assertRaisesRegex(
                    ValueError, 'assignment_version|proof_substitution'):
                r.admit(changed['publisher'], changed, spki_der(self.release.root_key),
                        self.release.origin, NOW, files=files,
                        expected_group_id=self.release.group,
                        expected_device_id='screen-windows', expected_profile=PROFILE,
                        expected_destination='windows-pages-v1',
                        expected_js_sha256=pin['js_sha256'],
                        expected_css_sha256=pin['css_sha256'])


class NativeStateTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.release = SyntheticRelease()
        self.now = NOW
        self.clock = patch('kiosk.display.delivery_authority.time.time',
                           return_value=self.now)
        self.clock.start()
        self.addCleanup(self.clock.stop)
        (self.root / 'private').mkdir()
        self.state = PrivateState(self.root / 'private')
        self.state.data.update(
            bootstrap={'group_id': self.release.group, 'origin': self.release.origin},
            binding={'device_id': 'screen-windows', 'profile': PROFILE},
            credential={'expires_at': self.now + 1000},
            trust={'expires_at': self.now + 1000,
                   'payload_sha256': sha(encode({}))},
            publisher_anchor={'root_spki_base64': spki(self.release.root_key),
                              'policy_floor': 1, 'heads': []})
        self.state.confirm_time(self.now)
        self.assignment = self._assignment()

    def _assignment(self):
        assignment = self.release.assignment()
        assignment['group_id'] = self.release.group
        assignment['device_id'] = 'screen-windows'
        # Re-sign the plan for the local display expectation is unnecessary: the
        # signed target remains the same and the local identity is checked here.
        return assignment

    def test_page_assignment_binding_floor_and_accept(self):
        identity = self.state.validate_page_assignment(self.assignment)
        self.assertEqual(len(identity), 64)
        self.state.accept_page(self.assignment)
        package = self.assignment['metadata']['publication']['package_id']
        accepted = self.state.accepted(package)
        self.assertEqual(accepted['kind'], 'pages')
        self.assertEqual(accepted['display']['mode'], 'tv')
        reopened = PrivateState(self.root / 'private')
        self.assertEqual(reopened.accepted(package)['projection'], 'tv-landscape')
        for field, value in (('device_id', 'screen-android'), ('group_id', 'other'),
                             ('profile', 'other'), ('destination', 'android-pages-v1')):
            changed = copy.deepcopy(self.assignment)
            changed[field] = value
            changed['generation'] = 2
            with self.subTest(field=field), self.assertRaisesRegex(
                    Exception, 'binding|approval|local'):
                self.state.validate_page_assignment(changed)

    def test_generation_rollback_and_conflict(self):
        second = copy.deepcopy(self.assignment)
        second['generation'] = 2
        self.state.accept_page(second)
        rollback = copy.deepcopy(second)
        rollback['generation'] = 1
        with self.assertRaisesRegex(Exception, 'rollback_or_conflict'):
            self.state.validate_page_assignment(rollback)
        conflict = copy.deepcopy(second)
        conflict['projection'] = 'tv-portrait'
        with self.assertRaisesRegex(Exception, 'publisher_approval_refused|rollback_or_conflict'):
            self.state.validate_page_assignment(conflict)

    def test_v1_events_assignment_remains_accepted(self):
        (self.root / 'v1-private').mkdir()
        state = PrivateState(self.root / 'v1-private')
        state.data.update(bootstrap={'group_id': self.release.group,
                                     'origin': self.release.origin},
                          binding={'device_id': 'screen-windows', 'profile': PROFILE},
                          credential={'expires_at': self.now + 1000},
                          trust={'expires_at': self.now + 1000,
                                 'payload_sha256': sha(encode({}))})
        state.confirm_time(self.now)
        publication = {'package_id': 'c' * 64}
        legacy = {'version': 1, 'group_id': self.release.group,
                  'device_id': 'screen-windows', 'profile': PROFILE, 'generation': 1,
                  'metadata_sha256': sha(encode(publication)), 'publication': publication}
        state.validate_assignment(legacy)
        self.assertEqual(state.data['assignment_highest']['generation'], 1)


@unittest.skipUnless(os.name == 'nt', 'Windows DPAPI publisher boundary')
class PublisherPageTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        (self.root / 'keys').mkdir()
        self.publisher = LocalPublisher(self.root / 'keys')
        self.publisher.create()
        state, key = self.publisher._read()
        self.key = key
        self.root_key = generate_private_key()
        self.group, self.origin = 'group', 'https://kiosk.example:20443'
        policy = dict(group_id=self.group, origin=self.origin, version=1,
                      issued=NOW - 100, expires=NOW + 86400,
                      revoked_devices=[], revoked_users=[])
        grant = dict(group_id=self.group, origin=self.origin, user_id='user1',
                     role='user', device_key=spki(key), issued=NOW - 100,
                     expires=NOW + 3600, can_delegate=False)
        state.update(root_spki=spki(self.root_key),
                     policy=a.signed(self.root_key, 'policy', policy),
                     chain=[a.signed(self.root_key, 'device', grant)],
                     group_id=self.group, origin=self.origin, device_id=key_id(key),
                     policy_floor=1, publication_heads=[])
        _atomic_write(self.publisher.file, protect(encode(state)))
        self.release = SyntheticRelease()
        self.document = self._document()
        self.packages = {'screen-windows': write_package(
            self.root / 'package', self.release.files('screen-windows'))}

    def _document(self):
        authorization = dict(group_id=self.group, origin=self.origin, user_id='user1',
                             device_id=key_id(self.key), policy_version=1,
                             issued=NOW, expires=NOW + 600)
        target = dict(self.release.windows)
        return r.prepare_release(revision=self.release.revision,
                                 authorization=authorization, targets=[target])['document']

    def _assignment(self):
        target = next(item for item in self.document['targets']
                      if item['device_id'] == 'screen-windows')
        return {'version': 4, 'group_id': self.group, 'device_id': 'screen-windows',
                'profile': PROFILE, 'generation': 1,
                'revision_sha256': self.document['plan']['revision_sha256'],
                'destination': 'windows-pages-v1', 'projection': target['projection'],
                'metadata_sha256': sha(encode(target['metadata'])),
                'metadata': target['metadata'], 'display': target['configuration']}

    def test_review_then_publish_v2_domain_and_target_bytes(self):
        ticket = self.publisher.review_page(self.document, self.packages, NOW)
        result = self.publisher.publish_page(ticket, NOW)
        assignment = self._assignment()
        assignment['publisher'] = result
        plan, target, _policy = a.page_assignment(
            result, assignment, spki_der(self.root_key), self.origin, NOW)
        self.assertEqual(plan, self.document['plan'])
        self.assertEqual(target['device_id'], 'screen-windows')
        self.assertEqual(a.page_verified(result['approval'], spki_der(self.key)),
                         self.document['plan'])
        with self.assertRaises(ValueError):
            a.verified(result['approval'], spki_der(self.key), 'publication')
        self.assertEqual(self.publisher.pending_approval()['id'],
                         self.document['plan']['id'])

    def test_tampered_target_bytes_and_changed_review_are_refused(self):
        (self.packages['screen-windows'] / r.PAGE_ENTRYPOINT).write_bytes(b'{}')
        with self.assertRaises(ValueError):
            self.publisher.review_page(self.document, self.packages, NOW)
        self.assertEqual(self.publisher.pending, {})

        self.packages['screen-windows'] = write_package(
            self.root / 'package2', self.release.files('screen-windows'))
        ticket = self.publisher.review_page(self.document, self.packages, NOW)
        (self.packages['screen-windows'] / r.PAGE_ENTRYPOINT).write_bytes(b'{}')
        with self.assertRaises(ValueError):
            self.publisher.publish_page(ticket, NOW)
        self.assertIsNone(self.publisher.pending_approval())

    def test_scope_refusal_keeps_no_ticket(self):
        document = copy.deepcopy(self.document)
        document['plan']['user_id'] = 'mallory'
        document['plan']['id'] = sha(a.PAGE_PLAN_DOMAIN + encode(
            {key: value for key, value in document['plan'].items() if key != 'id'}))
        with self.assertRaisesRegex(ValueError, 'scope_refused'):
            self.publisher.review_page(document, self.packages, NOW)
        self.assertEqual(self.publisher.pending, {})


class MaintenanceTransport:
    """Synthetic trusted Maintenance host with strict Bearer page routes."""

    def __init__(self, document, package, *, approve_error=None, tamper=None,
                 open_document=None):
        self.document = document
        self.package = Path(package)
        self.approve_error = approve_error
        self.tamper = tamper
        self.open_document = open_document or document
        self.token = None
        self.calls, self.approvals, self.responses = [], [], 0

    def json(self, path, *, body=None, authenticated=True):
        assert authenticated is True
        assert self.token is not None and self.token not in path
        self.calls.append((path, body))
        if path == PAGE_OPEN_PATH:
            return {'version': 1, 'document': decode(encode(self.open_document))}
        if path == PAGE_APPROVE_PATH:
            if self.approve_error is not None:
                raise self.approve_error
            self.approvals.append(body)
            return {'version': 1, 'state': 'approved',
                    'distribution': {'state': 'ready', 'targets': 1}}
        raise AssertionError('unexpected route ' + path)

    @contextlib.contextmanager
    def response(self, path, headers=None, *, authenticated=True):
        assert authenticated is True
        assert self.token is not None and self.token not in path
        self.responses += 1
        prefix = PAGE_PACKAGE_PATH + 'screen-windows/package/'
        assert path.startswith(prefix), path
        name = path[len(prefix):]
        payload = (self.package / name).read_bytes()
        if self.tamper == name:
            payload = bytes([payload[0] ^ 0xFF]) + payload[1:]
        target = self.document['targets'][0]
        entry = next(item for item in target['metadata']['publication']['package']['files']
                     if item['path'] == name)
        yield FakeResponse(payload, entry)


class CandidateOnlyTransport:
    def __init__(self, document):
        self.document = document

    def json(self, path, *, body=None, authenticated=True):
        assert path == CANDIDATE_PATH + self.document['plan']['id']
        return decode(encode(self.document))


@unittest.skipUnless(os.name == 'nt', 'Windows DPAPI publisher boundary')
class NativeMaintenanceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        (self.root / 'keys').mkdir()
        self.publisher = LocalPublisher(self.root / 'keys')
        self.publisher.create()
        state, self.key = self.publisher._read()
        self.root_key = generate_private_key()
        self.group, self.origin = 'group', 'https://kiosk.example:20443'
        self.maintenance = 'https://maint.example:20444'
        self.token = 'a' * 64
        policy = dict(group_id=self.group, origin=self.origin, version=1,
                      issued=NOW - 100, expires=NOW + 86400,
                      revoked_devices=[], revoked_users=[])
        grant = dict(group_id=self.group, origin=self.origin, user_id='user1',
                     role='user', device_key=spki(self.key), issued=NOW - 100,
                     expires=NOW + 3600, can_delegate=False)
        state.update(root_spki=spki(self.root_key),
                     policy=a.signed(self.root_key, 'policy', policy),
                     chain=[a.signed(self.root_key, 'device', grant)],
                     group_id=self.group, origin=self.origin, device_id=key_id(self.key),
                     policy_floor=1, publication_heads=[])
        _atomic_write(self.publisher.file, protect(encode(state)))
        self.release = SyntheticRelease()
        authorization = dict(group_id=self.group, origin=self.origin, user_id='user1',
                             device_id=key_id(self.key), policy_version=1,
                             issued=NOW, expires=NOW + 600)
        prepared = r.prepare_release(revision=self.release.revision,
                                     authorization=authorization,
                                     targets=[self.release.windows])
        self.document = prepared['document']
        self.package = write_package(self.root / 'package',
                                     prepared['artifacts']['screen-windows']['files'])

    def link(self, **overrides):
        fields = {'version': '1', 'token': self.token, 'expires': NOW + 600,
                  'content_origin': self.origin, 'maintenance_origin': self.maintenance}
        fields.update(overrides)
        return 'kiosk://roaming/page#' + urlencode(fields)

    def _factory(self, transport):
        def factory(token):
            transport.token = token
            return transport
        return factory

    def bridge(self, transport):
        return PublisherBridge(self.publisher, object(), self.publisher.root,
                               lambda: NOW, maintenance_origin=self.maintenance,
                               maintenance_factory=self._factory(transport))

    def test_open_approval_binds_exact_token_hash_and_origins(self):
        result = self.publisher.page_open_approval(
            self.token, self.origin, self.maintenance, NOW)
        self.assertEqual(a.verified(result['approval'], spki_der(self.key),
                                    'page-review-open'),
                         {'token_sha256': sha(self.token.encode('ascii')),
                          'content_origin': self.origin,
                          'maintenance_origin': self.maintenance})
        with self.assertRaisesRegex(ValueError, 'content_origin_refused'):
            self.publisher.page_open_approval(
                self.token, 'https://attacker.example', self.maintenance, NOW)
        with self.assertRaisesRegex(ValueError, 'native_ticket_refused'):
            self.publisher.page_open_approval('b' * 63, self.origin,
                                              self.maintenance, NOW)

    def test_open_review_publish_uses_exact_bearer_paths(self):
        transport = MaintenanceTransport(self.document, self.package)
        bridge = self.bridge(transport)
        candidate = bridge.open_page(self.link(), confirm=True)
        facts = bridge.summarize(candidate)
        self.assertEqual(facts['targets'][0]['device'], 'screen-windows')
        self.assertEqual(facts['targets'][0]['renderer'], page_view.renderer_pin()['build_id'])
        self.assertGreater(transport.responses, 0)
        self.assertTrue(all(self.token not in path for path, _ in transport.calls))
        response = bridge.publish_page(candidate)
        self.assertEqual(response['state'], 'approved')
        self.assertEqual(set(transport.approvals[0]), {'id', 'approval', 'chain'})
        self.assertEqual(transport.approvals[0]['id'], self.document['plan']['id'])
        self.assertEqual(a.page_verified(transport.approvals[0]['approval'],
                                         spki_der(self.key)), self.document['plan'])
        self.assertIsNone(self.publisher.pending_approval())
        self.assertEqual(self.publisher._read()[0]['publication_heads'],
                         [self.document['plan']['id']])

    def test_open_requires_consent_and_refuses_origin_override(self):
        transport = MaintenanceTransport(self.document, self.package)
        bridge = self.bridge(transport)
        with self.assertRaisesRegex(ValueError, 'confirmation_required'):
            bridge.open_page(self.link())
        replaced = self.link(content_origin='https://attacker.example')
        with self.assertRaisesRegex(ValueError, 'content_origin_refused'):
            bridge.open_page(replaced, confirm=True)
        replaced = self.link(maintenance_origin='https://attacker.example')
        with self.assertRaisesRegex(ValueError, 'maintenance_origin_refused'):
            bridge.open_page(replaced, confirm=True)
        self.assertEqual(transport.calls, [])

    def test_page_link_contract_is_exact_and_rejects_expiry_preflight(self):
        transport = MaintenanceTransport(self.document, self.package)
        bridge = self.bridge(transport)
        with self.assertRaisesRegex(ValueError, 'link_expired'):
            bridge.open_page(self.link(expires=NOW), confirm=True)
        with self.assertRaisesRegex(ValueError, 'link_expired'):
            bridge.open_page(self.link(expires=NOW - 5), confirm=True)
        base = {'version': '1', 'token': self.token, 'expires': NOW + 600,
                'content_origin': self.origin, 'maintenance_origin': self.maintenance}
        missing = {key: value for key, value in base.items() if key != 'expires'}
        duplicate = urlencode([
            ('version', '1'), ('token', self.token), ('token', self.token),
            ('expires', NOW + 600), ('content_origin', self.origin),
            ('maintenance_origin', self.maintenance)])
        bad = [
            'kiosk://roaming/page#' + urlencode(missing),
            'kiosk://roaming/page#' + urlencode(dict(base, unknown='x')),
            'kiosk://roaming/pages#' + urlencode(base),
            'kiosk://roaming/page?x=1#' + urlencode(base),
            self.link(version='2'),
            self.link(expires='soon'),
            'kiosk://roaming/page#' + duplicate,
        ]
        for value in bad:
            with self.subTest(value=value), self.assertRaisesRegex(
                    ValueError, 'link_refused'):
                bridge.open_page(value, confirm=True)
        self.assertEqual(transport.calls, [])
        self.assertEqual(transport.responses, 0)

    def test_retryable_approve_statuses_preserve_durable_pending(self):
        plan_id = self.document['plan']['id']
        for status in (408, 425, 429, 0):
            with self.subTest(status=status):
                self.publisher.discard_pending(plan_id)
                transport = MaintenanceTransport(
                    self.document, self.package,
                    approve_error=TransportError('retry', status))
                bridge = self.bridge(transport)
                candidate = bridge.open_page(self.link(), confirm=True)
                with self.assertRaises(TransportError):
                    bridge.publish_page(candidate)
                pending = LocalPublisher(self.publisher.root).pending_approval()
                self.assertIsNotNone(pending)
                self.assertEqual(pending['id'], plan_id)
                self.assertEqual(pending['token'], self.token)
                self.assertEqual(self.publisher._read()[0]['publication_heads'], [])
        retry_transport = MaintenanceTransport(self.document, self.package)
        response = self.bridge(retry_transport).retry()
        self.assertEqual(response['state'], 'approved')
        self.assertEqual(retry_transport.approvals[0]['id'], plan_id)
        self.assertIsNone(LocalPublisher(self.publisher.root).pending_approval())

    def test_definitive_approve_refusals_discard_pending(self):
        plan_id = self.document['plan']['id']
        for status in (400, 401, 403, 404, 410, 422):
            with self.subTest(status=status):
                self.publisher.discard_pending(plan_id)
                transport = MaintenanceTransport(
                    self.document, self.package,
                    approve_error=TransportError('refused', status))
                bridge = self.bridge(transport)
                candidate = bridge.open_page(self.link(), confirm=True)
                with self.assertRaisesRegex(ValueError, 'approval_refused'):
                    bridge.publish_page(candidate)
                self.assertIsNone(LocalPublisher(self.publisher.root).pending_approval())
                self.assertEqual(self.publisher._read()[0]['publication_heads'], [])

    def test_tampered_bytes_and_wrong_renderer_pin_are_refused(self):
        transport = MaintenanceTransport(self.document, self.package,
                                         tamper=r.PAGE_ENTRYPOINT)
        bridge = self.bridge(transport)
        with self.assertRaises(ValueError):
            bridge.open_page(self.link(), confirm=True)
        self.assertEqual(self.publisher.pending, {})
        self.assertIsNone(self.publisher.pending_approval())
        self.assertEqual(transport.approvals, [])
        bad_pin = {'js_sha256': '0' * 64, 'css_sha256': '1' * 64, 'build_id': '2' * 64}
        with patch.object(page_view, 'renderer_pin', return_value=bad_pin):
            with self.assertRaisesRegex(ValueError, 'renderer_mismatch'):
                self.bridge(MaintenanceTransport(self.document, self.package)) \
                    .open_page(self.link(), confirm=True)

    def test_foreign_user_plan_is_refused_before_download(self):
        document = copy.deepcopy(self.document)
        document['plan']['user_id'] = 'mallory'
        document['plan']['id'] = sha(a.PAGE_PLAN_DOMAIN + encode(
            {key: value for key, value in document['plan'].items() if key != 'id'}))
        transport = MaintenanceTransport(self.document, self.package,
                                         open_document=document)
        with self.assertRaisesRegex(ValueError, 'scope_refused'):
            self.bridge(transport).open_page(self.link(), confirm=True)
        self.assertEqual(transport.responses, 0)

    def test_changed_plan_409_clears_pending_and_needs_a_new_ticket(self):
        transport = MaintenanceTransport(self.document, self.package,
                                         approve_error=TransportError('plan_changed', 409))
        bridge = self.bridge(transport)
        candidate = bridge.open_page(self.link(), confirm=True)
        with self.assertRaisesRegex(ValueError, 'review_changed'):
            bridge.publish_page(candidate)
        self.assertIsNone(self.publisher.pending_approval())
        replacement = MaintenanceTransport(self.document, self.package)
        candidate = self.bridge(replacement).open_page(self.link(), confirm=True)
        response = self.bridge(replacement).publish_page(candidate)
        self.assertEqual(response['distribution']['state'], 'ready')

    def test_lost_response_retries_exact_approval_with_maintenance_token(self):
        failing = MaintenanceTransport(self.document, self.package,
                                       approve_error=TransportError('network_unavailable', 0))
        candidate = self.bridge(failing).open_page(self.link(), confirm=True)
        with self.assertRaises(TransportError):
            self.bridge(failing).publish_page(candidate)
        pending = LocalPublisher(self.publisher.root).pending_approval()
        self.assertEqual(pending['id'], self.document['plan']['id'])
        self.assertEqual(pending['token'], self.token)
        self.assertEqual(self.publisher._read()[0]['publication_heads'], [])
        retry_transport = MaintenanceTransport(self.document, self.package)
        response = self.bridge(retry_transport).retry()
        self.assertEqual(response['state'], 'approved')
        self.assertEqual(retry_transport.approvals[0], {
            'id': pending['id'], 'approval': pending['approval'], 'chain': pending['chain']})
        self.assertTrue(all(self.token not in path for path, _ in retry_transport.calls))
        self.assertIsNone(LocalPublisher(self.publisher.root).pending_approval())
        self.assertEqual(LocalPublisher(self.publisher.root)._read()[0]['publication_heads'],
                         [self.document['plan']['id']])

    def test_events_candidate_endpoint_refuses_page_document(self):
        transport = MaintenanceTransport(self.document, self.package)
        bridge = PublisherBridge(self.publisher, CandidateOnlyTransport(self.document),
                                 self.publisher.root, lambda: NOW,
                                 maintenance_origin=self.maintenance,
                                 maintenance_factory=self._factory(transport))
        with self.assertRaisesRegex(ValueError, 'maintenance_ticket'):
            bridge.open(self.document['plan']['id'])
        self.assertIsNone(self.publisher.pending_approval())
        self.assertEqual(transport.approvals, [])


class CapabilityHandshakeTests(unittest.TestCase):
    """The shipped Windows capability body must satisfy the server validator."""

    class Native:
        def __init__(self):
            self.validated = None

        def now(self):
            return NOW

        def validate_assignment(self, value):
            self.validated = value

    class Client:
        def __init__(self):
            self.native = CapabilityHandshakeTests.Native()
            self.progress_target = None

    def transport(self, assignment):
        from urllib.parse import parse_qs, urlsplit
        from kiosk.delivery.profiles import capability

        class FakeTransport:
            def __init__(self):
                self.calls, self.body, self.query = [], None, None

            def json(self, path, body=None):
                self.calls.append(path)
                if path == '/api/v2/client/capabilities':
                    capability(body)
                    self.body = body
                    return {'version': 1, 'state': 'recorded'}
                assert path.startswith('/api/v2/client/assignment?')
                self.query = parse_qs(urlsplit(path).query)
                return assignment

        return FakeTransport()

    def test_seven_key_capability_and_v2_assignment(self):
        transport = self.transport({'version': 4, 'device_id': 'screen-windows',
                                    'group_id': 'group', 'generation': 1,
                                    'metadata': {'publication': {'package_id': 'a' * 64}}})
        client = self.Client()
        with patch.object(delivery_client, 'check_page_assignment') as checked:
            result = delivery_client.Client.assignment(client, transport)
        self.assertEqual(result['version'], 4)
        self.assertEqual(set(transport.body), {
            'version', 'platform', 'modes', 'content', 'resource_profile',
            'renderer', 'pages_renderer'})
        self.assertEqual(transport.body['content'], ['events'])
        self.assertEqual(transport.query['display_protocol'], ['display-profile-v2'])
        self.assertEqual(transport.query['pages_renderer'],
                         [page_view.renderer_pin()['build_id']])
        self.assertEqual(transport.query['resource_profile'], [PROFILE])
        checked.assert_called_once()
        self.assertEqual(client.progress_target['device_id'], 'screen-windows')

    def test_capability_handshake_keeps_v1_events_assignment(self):
        assignment = {'version': 1, 'group_id': 'group', 'device_id': 'device',
                      'generation': 1, 'profile': PROFILE,
                      'publication': {'package_id': 'a' * 64}}
        transport = self.transport(assignment)
        client = self.Client()
        with patch.object(delivery_client, 'validate_metadata') as metadata:
            result = delivery_client.Client.assignment(client, transport)
        self.assertEqual(result, assignment)
        self.assertIs(client.native.validated, assignment)
        metadata.assert_called_once()

if __name__ == '__main__':
    unittest.main()
