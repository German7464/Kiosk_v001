"""Stage 6 server release: v2 page materialization, trusted review and v4 delivery.

Synthetic two-target lab only. The test uses the real Maintenance reviewer and
acceptance keys over the authenticated Content service contract, exact on-disk
data-only catalogs, per-device v4 variants, device activation receipts and
repeat-safe retries. No retained installation, real lab, SSH, ADB or network is
used.
"""
import base64
import hashlib
import hmac
import secrets
import tempfile
import time
import unittest
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from kiosk.delivery.profiles import capability
from kiosk.delivery.protocol import PROFILE, decode, encode, sha
from kiosk.display.cache import renderer_identity
from kiosk.maintenance.content import ContentRefused
from kiosk.maintenance import review as review_module
from kiosk.maintenance.setup import create_lab
from kiosk.publication import authority as publisher_authority, page_materialize
from kiosk.trust.crypto import generate_private_key, key_id, spki_der
from tools.publisher_authority import load as load_authority
from tools.kiosk_maintenance_lab import content_application, maintenance_application

GROUP = 'group-stage6-release'
CONTENT_ORIGIN = 'https://127.0.0.1:31443'
MAINTENANCE_ORIGIN = 'https://127.0.0.1:32443'
ADMIN = 'admin'
PASSWORD = 'correct-horse-battery-staple'
PNG = base64.b64decode(
    'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+M8A'
    'AAMBAQDJ/pLvAAAAAElFTkSuQmCC')


def object_id(kind, number=1):
    return f'{kind}-{number:032x}'


def event_payload(title, sort_order, images=None, status='active'):
    return {'title': title, 'short_description': 'Short', 'full_description': 'Full',
            'event_date': None, 'place': 'Hall', 'sort_order': sort_order,
            'status': status, 'images': list(images or []), 'tags': []}


class InProcessContent:
    """Exercise the real Content service contract without opening a socket."""

    def __init__(self, test):
        self.test = test
        self.fail_after_commit = False

    def _call(self, method, path, payload=None, session=None):
        response = self.test._service(method, path, payload, session)
        if response.status_code >= 400:
            try:
                code = response.get_json()['error']
            except (TypeError, KeyError, ValueError):
                code = 'content_refused'
            raise ContentRefused(code, response.status_code)
        return response

    def session(self, user_id, chain):
        return self._call('POST', '/service/v1/session',
                          {'user_id': user_id, 'chain': chain}).get_json()['secret']

    def targets(self, secret):
        return self._call('GET', '/service/v1/targets',
                          session=secret).get_json()['targets']

    def prepare(self, secret, selected, targets, parents):
        return self._call('POST', '/service/v1/prepare', {
            'secret': secret, 'selected': selected, 'targets': targets,
            'parents': list(parents or [])}).get_json()

    def approve(self, identity, approval, chain, receipt, acceptance_key):
        return self._call('POST', '/service/v1/approve', {
            'id': identity, 'approval': approval, 'chain': chain,
            'receipt': receipt, 'acceptance_key': acceptance_key}).get_json()

    def page_targets(self, secret):
        return self._call('GET', '/service/v1/page/targets',
                          session=secret).get_json()['targets']

    def page_prepare(self, secret, parents=None):
        return self._call('POST', '/service/v1/page/prepare',
                          {'secret': secret, 'parents': list(parents or [])}).get_json()

    def page_candidate(self, secret, identity):
        return self._call('GET', f'/service/v1/page/candidate/{identity}',
                          session=secret).get_json()['document']

    def page_artifact(self, secret, identity, device_id, name):
        return self._call(
            'GET', f'/service/v1/page/package/{identity}/{device_id}/{name}',
            session=secret).data

    def page_approve(self, secret, identity, approval, chain, receipt, acceptance_key):
        response = self._call('POST', '/service/v1/page/approve', {
            'secret': secret, 'id': identity, 'approval': approval, 'chain': chain,
            'receipt': receipt, 'acceptance_key': acceptance_key})
        result = response.get_json()
        if self.fail_after_commit:
            # The Content commit is real; only the response is lost.
            self.fail_after_commit = False
            raise ContentRefused('content_unavailable')
        return result

    def page_status(self, secret, identity):
        return self._call('GET', f'/service/v1/page/status/{identity}',
                          session=secret).get_json()


class Stage6ServerReleaseTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name) / 'lab'
        self.created = create_lab(
            self.root, mode='combined', content_origin=CONTENT_ORIGIN,
            maintenance_origin=MAINTENANCE_ORIGIN, group_id=GROUP,
            admin_user=ADMIN, admin_password=PASSWORD)
        self.content = content_application(self.created['content_config'])
        self.maintenance = maintenance_application(self.created['maintenance_config'])
        self.workspace = self.content.extensions['roaming_workspace']
        # The disposable lab does not opt into Stage 6 drafts; this test owns the
        # exact server-side flag and never touches retained installations.
        self.workspace.stage6_pages = True
        self.state = self.content.extensions['device_delivery']
        self.store = self.maintenance.extensions['maintenance_store']
        self.authority = self.maintenance.extensions['maintenance_authority']
        self.inprocess = InProcessContent(self)
        self.maintenance.extensions['maintenance_content'] = self.inprocess
        self.now = int(time.time())
        self.upload = Path(self.content.config['PUBLIC_UPLOAD_DIR']) / 'notice.png'
        self.upload.parent.mkdir(parents=True, exist_ok=True)
        self.upload.write_bytes(PNG)

    def tearDown(self):
        self.temp.cleanup()

    # -- fixtures -----------------------------------------------------------
    def _chain(self):
        with self.store.connection() as db:
            granted = self.authority.grant(db, ADMIN)
        return granted['chain']

    def _devices(self):
        pages_renderer = page_materialize.renderer_identity()['build_id']
        events_renderer = renderer_identity()
        self.state.save_profile('tv-profile', 'TV landscape', 'tv', 0, 'landscape')
        self.state.save_profile('kiosk-profile', 'Kiosk portrait', 'kiosk', 0, 'portrait')
        self.state.save_profile('extra-profile', 'Extra landscape', 'tv', 0, 'landscape')
        rows = {
            'screen-windows': ('tv-profile', secrets.token_hex(32), 'windows', ['tv']),
            'screen-android': ('kiosk-profile', secrets.token_hex(32), 'android', ['kiosk']),
        }
        with self.state.connection() as db:
            for device_id, (profile, secret, platform, modes) in rows.items():
                db.execute('INSERT INTO devices VALUES (?,?,?,?,?,0)',
                           (device_id, PROFILE, 'credential-' + device_id,
                            sha(bytes.fromhex(secret)), self.now + 86400))
                body = capability({
                    'version': 1, 'platform': platform, 'modes': modes,
                    'content': ['events'], 'resource_profile': PROFILE,
                    'renderer': events_renderer, 'pages_renderer': pages_renderer})
                db.execute('INSERT INTO device_capabilities VALUES (?,?)',
                           (device_id, encode(body)))
        self.state.select_profile('screen-windows', 'tv-profile')
        self.state.select_profile('screen-android', 'kiosk-profile')
        return {device_id: secret for device_id, (_, secret, _, _) in rows.items()}

    def _ready(self, identity, version):
        self.workspace.ready_page(self.secret, identity, version)

    def _save_page(self, identity, payload, dependencies):
        version = self.workspace.save_page(self.secret, identity, 0, payload, dependencies)
        self._ready(identity, version)
        return version

    def _save_event(self, identity, payload, ready=True):
        version = self.workspace.save(self.secret, identity, 0, payload, {})
        if ready:
            self.workspace.ready(self.secret, identity, version)
        return version

    def _graph(self):
        self.secret = self.workspace.create_service_session(ADMIN, self._chain())
        dataset, block = object_id('dataset'), object_id('block')
        layout_tv, layout_kiosk = object_id('layout', 1), object_id('layout', 2)
        page, profile = object_id('page'), object_id('profile')
        assign_w, assign_a = object_id('assignment', 1), object_id('assignment', 2)
        self._save_event('1001', event_payload('Notice', 1, ['/static/uploads/notice.png']))
        self._save_event('1002', event_payload('Working draft', 2), ready=False)
        self._save_event('1003', event_payload('Independent ready', 3, status='hidden'))
        self._save_page(dataset, {'schema': 1, 'name': 'Events', 'module': 'events',
                                  'events': ['1001']}, {'1001': 1})
        self._save_page(block, {'schema': 1, 'name': 'Cards', 'dataset': dataset,
                                'tags': [], 'limit': 3, 'appearance': 'cards'},
                        {dataset: 1})
        self._save_page(layout_tv, {'schema': 1, 'target': 'tv-landscape', 'columns': 4,
                                    'rows': 3, 'placements': [
                                        {'block': block, 'x': 0, 'y': 0, 'w': 2, 'h': 3}]},
                        {block: 1})
        self._save_page(layout_kiosk, {'schema': 1, 'target': 'kiosk-portrait', 'columns': 2,
                                       'rows': 4, 'placements': [
                                           {'block': block, 'x': 0, 'y': 0, 'w': 2, 'h': 2}]},
                        {block: 1})
        self._save_page(page, {'schema': 1, 'name': 'Notice board', 'order': 0,
                               'layouts': {'tv-landscape': layout_tv,
                                           'kiosk-portrait': layout_kiosk},
                               'fallback': 'tv-landscape'}, {layout_tv: 1, layout_kiosk: 1})
        self._save_page(profile, {'schema': 1, 'name': 'Shared', 'selection': {
            'pages': [page], 'start_page': page, 'transition_seconds': 15}}, {page: 1})
        self._save_page(assign_w, {'schema': 1, 'device': 'screen-windows',
                                   'profile': profile, 'selection': None}, {profile: 1})
        self._save_page(assign_a, {'schema': 1, 'device': 'screen-android',
                                   'profile': profile, 'selection': None}, {profile: 1})

    # -- service helpers ----------------------------------------------------
    def _service(self, method, path, payload=None, session=None):
        config = self.content.config['MAINTENANCE_SERVICE']
        body = b'' if payload is None else encode(payload)
        stamp = str(int(time.time()))
        nonce = secrets.token_hex(32)
        digest = sha(body)
        message = '\n'.join((config['service_id'], method, path, stamp, nonce, digest))
        headers = {
            'X-Kiosk-Service-Id': config['service_id'], 'X-Kiosk-Time': stamp,
            'X-Kiosk-Nonce': nonce, 'X-Kiosk-Body-SHA256': digest,
            'X-Kiosk-Signature': hmac.new(config['secret'].encode(),
                                          message.encode(), hashlib.sha256).hexdigest(),
        }
        if session:
            headers['X-Kiosk-Content-Session'] = session
        if payload is not None:
            headers['Content-Type'] = 'application/json'
        return self.content.test_client().open(
            path, method=method, data=body or None, headers=headers, base_url=CONTENT_ORIGIN)

    def _device(self, method, path, secret, payload=None):
        headers = {'Authorization': 'Bearer ' + secret}
        if payload is not None:
            headers['Content-Type'] = 'application/json'
        return self.content.test_client().open(
            path, method=method, data=None if payload is None else encode(payload),
            headers=headers, base_url=CONTENT_ORIGIN)

    def _prepare(self):
        response = self._service('POST', '/service/v1/page/prepare',
                                 {'secret': self.secret, 'parents': []}, self.secret)
        self.assertEqual(response.status_code, 200, response.get_data(as_text=True))
        return response.get_json()

    def _files(self, document):
        files = {}
        for target in document['targets']:
            package = {}
            for entry in target['metadata']['publication']['package']['files']:
                response = self._service(
                    'GET', f"/service/v1/page/package/{document['plan']['id']}/"
                           f"{target['device_id']}/{entry['path']}", session=self.secret)
                self.assertEqual(response.status_code, 200)
                package[entry['path']] = response.data
            files[target['device_id']] = {'package': package, 'kiosk': {}, 'tv': {}}
        return files

    def _sign(self, document, targets):
        with self.store.connection() as db:
            signed = self.authority.sign_page_publication(
                db, ADMIN, document['plan'], targets, self.workspace.now())
        receipt = self.authority.sign_page_receipt(
            document['plan'], signed['approval'], document['plan']['policy_version'],
            secrets.token_hex(32), self.workspace.now())
        return signed, receipt

    def _approve(self, document, signed, receipt):
        return self._service('POST', '/service/v1/page/approve', {
            'secret': self.secret, 'id': document['plan']['id'],
            'approval': signed['approval'], 'chain': signed['chain'],
            'receipt': receipt['receipt'], 'acceptance_key': receipt['acceptance_key'],
        }, self.secret)

    # -- native Maintenance helpers -----------------------------------------
    def _browser(self):
        client = self.maintenance.test_client()
        state = client.get('/api/state', base_url=MAINTENANCE_ORIGIN)
        self.assertEqual(state.status_code, 200, state.get_data(as_text=True))
        csrf = state.get_json()['csrf']
        login = client.post('/api/login', json={'user': ADMIN, 'password': PASSWORD},
                            headers={'X-CSRF-Token': csrf},
                            base_url=MAINTENANCE_ORIGIN)
        self.assertEqual(login.status_code, 200, login.get_data(as_text=True))
        self.assertTrue(login.get_json()['trusted'])
        return client, login.get_json()['csrf']

    def _root_grant(self, native_key, user_id=ADMIN):
        root = Path(self.created['root'])
        password = (root / 'authority-password.txt').read_text(encoding='utf-8').strip()
        root_key, public, policy = load_authority(root / 'authority', password,
                                                   self.workspace.now())
        grant = dict(group_id=GROUP, origin=CONTENT_ORIGIN, user_id=user_id,
                     role='administrator',
                     device_key=base64.b64encode(spki_der(native_key)).decode('ascii'),
                     issued=self.workspace.now(), expires=policy['expires'],
                     can_delegate=False)
        return [publisher_authority.signed(root_key, 'device', grant)], public, policy

    def _native_ticket(self, client, csrf, parents=None):
        response = client.post('/api/page/native-ticket',
                               json={'parents': list(parents or [])},
                               headers={'X-CSRF-Token': csrf},
                               base_url=MAINTENANCE_ORIGIN)
        self.assertEqual(response.status_code, 200, response.get_data(as_text=True))
        return response.get_json()

    def _native_call(self, method, path, token, payload=None):
        headers = {'Authorization': 'Bearer ' + token}
        data = None if payload is None else encode(payload)
        if payload is not None:
            headers['Content-Type'] = 'application/json'
        response = self.maintenance.test_client().open(
            path, method=method, data=data, headers=headers,
            base_url=MAINTENANCE_ORIGIN)
        return response

    def _native_open(self, token, native_key, chain):
        value = {'token_sha256': hashlib.sha256(token.encode('ascii')).hexdigest(),
                 'content_origin': CONTENT_ORIGIN,
                 'maintenance_origin': MAINTENANCE_ORIGIN}
        approval = publisher_authority.signed(native_key, 'page-review-open', value)
        response = self._native_call('POST', '/api/page/native/open', token,
                                     {'approval': approval, 'chain': chain})
        self.assertEqual(response.status_code, 200, response.get_data(as_text=True))
        return response.get_json()['document']

    def _set_clock(self, value):
        self.workspace.clock = lambda: value
        self.state.clock = lambda: value
        self.store.clock = lambda: value
        self.authority.clock = lambda: value
        self.maintenance.extensions['maintenance_clock'] = lambda: value

    # -- tests --------------------------------------------------------------
    def test_two_target_trusted_release_and_activation(self):
        secrets_map = self._devices()
        self._graph()
        targets = self.state.page_targets()
        self.assertEqual([item['device_id'] for item in targets],
                         ['screen-android', 'screen-windows'])
        self.assertEqual(targets[0]['projection'], 'kiosk-portrait')
        self.assertEqual(targets[0]['destination'], 'android-pages-v1')
        self.assertEqual(targets[1]['projection'], 'tv-landscape')
        self.assertEqual(targets[1]['destination'], 'windows-pages-v1')

        prepared = self._prepare()
        document = prepared['document']
        files = self._files(document)
        view = review_module.validate_page(
            document, targets=prepared['targets'], user_id=ADMIN, group_id=GROUP,
            origin=CONTENT_ORIGIN, now=self.workspace.now(), files=files,
            settings_version=prepared['settings_version'])
        self.assertEqual(view['target_count'], 2)
        self.assertEqual(view['renderer'],
                         page_materialize.renderer_identity()['build_id'])
        self.assertIn('1003', [item['id'] for item in view['included']])
        self.assertEqual([item['id'] for item in view['excluded']], ['1002'])
        self.assertEqual(view['excluded'][0]['reason'], 'working')
        packages = {item['device_id']: item['package_id'] for item in view['targets']}
        self.assertNotEqual(packages['screen-android'], packages['screen-windows'])
        for item in view['targets']:
            self.assertEqual(item['file_count'], 3)
            self.assertEqual(item['page_target'], item['projection'])
            self.assertGreater(item['event_count'], 0)

        signed, receipt = self._sign(document, prepared['targets'])
        # A wrong acceptance key is refused before any pointer changes.
        wrong = self.authority.sign_page_receipt(
            document['plan'], signed['approval'], document['plan']['policy_version'],
            secrets.token_hex(32), self.workspace.now())
        wrong_key = base64.b64encode(spki_der(self._wrong_key())).decode()
        wrong['acceptance_key'] = wrong_key
        refused = self._approve(document, signed, wrong)
        self.assertEqual(refused.status_code, 403)
        self.assertEqual(refused.get_json()['error'], 'acceptance_key_mismatch')
        tampered = dict(receipt)
        envelope = dict(receipt['receipt'])
        signature = bytearray(base64.b64decode(envelope['signature']))
        signature[0] ^= 0x01
        envelope['signature'] = base64.b64encode(bytes(signature)).decode()
        tampered['receipt'] = envelope
        corrupted = self._approve(document, signed, tampered)
        self.assertEqual(corrupted.status_code, 403)
        self.assertEqual(corrupted.get_json()['error'], 'acceptance_receipt_refused')
        self.assertIsNone(self.state.page_activation(document['plan']['id']))
        with self.state.connection(write=False) as db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM page_assignments').fetchone()[0], 0)

        response = self._approve(document, signed, receipt)
        self.assertEqual(response.status_code, 200, response.get_data(as_text=True))
        result = response.get_json()
        self.assertEqual(result['distribution']['generation'], 1)
        self.assertEqual(result['distribution']['targets'], 2)
        activation = self.state.page_activation(document['plan']['id'])
        self.assertEqual((activation['targets'], activation['activated']), (2, 0))
        with self.state.connection(write=False) as db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM assignments').fetchone()[0], 0)
            self.assertEqual(db.execute('SELECT COUNT(*) FROM acceptance_receipts').fetchone()[0], 0)

        renderer = page_materialize.renderer_identity()['build_id']
        windows = self._device(
            'GET', '/api/v2/client/assignment?display_protocol=display-profile-v2'
                   f'&pages_renderer={renderer}&resource_profile={PROFILE}',
            secrets_map['screen-windows']).get_json()
        self.assertEqual(windows['version'], 4)
        self.assertEqual(windows['destination'], 'windows-pages-v1')
        self.assertEqual(windows['projection'], 'tv-landscape')
        self.assertEqual(windows['generation'], 1)
        self.assertEqual(windows['publisher']['approval'], signed['approval'])
        android = self._device(
            'GET', '/api/v2/client/assignment?display_protocol=display-profile-v2'
                   f'&pages_renderer={renderer}&resource_profile={PROFILE}',
            secrets_map['screen-android']).get_json()
        self.assertEqual(android['projection'], 'kiosk-portrait')
        self.assertEqual(android['destination'], 'android-pages-v1')

        wrong_renderer = self._device(
            'GET', '/api/v2/client/assignment?display_protocol=display-profile-v2'
                   f'&pages_renderer={"0" * 64}&resource_profile={PROFILE}',
            secrets_map['screen-windows'])
        self.assertEqual(wrong_renderer.status_code, 409)
        self.assertEqual(wrong_renderer.get_json()['error'], 'requires_update')
        legacy = self._device('GET', '/api/v2/client/assignment?renderer='
                                     + renderer_identity(), secrets_map['screen-windows'])
        self.assertEqual(legacy.status_code, 404)
        self.assertEqual(legacy.get_json()['error'], 'no_assignment')

        android_pkg = packages['screen-android']
        windows_pkg = packages['screen-windows']
        cross = self._device(
            'GET', f'/api/v2/publications/{android_pkg}/package/data/page-release.json',
            secrets_map['screen-windows'])
        self.assertEqual(cross.status_code, 409)
        own = self._device(
            'GET', f'/api/v2/publications/{windows_pkg}/package/data/page-release.json',
            secrets_map['screen-windows'])
        self.assertEqual(own.status_code, 200)
        self.assertEqual(own.data, files['screen-windows']['package']['data/page-release.json'])
        view_group = self._device(
            'GET', f'/api/v2/publications/{windows_pkg}/kiosk/data/events.json',
            secrets_map['screen-windows'])
        self.assertEqual(view_group.status_code, 404)

        receipt_body = {'version': 1, 'receipt_id': 'windows-1', 'group_id': GROUP,
                        'device_id': 'screen-windows', 'generation': 1,
                        'package_id': windows_pkg, 'mode': 'tv', 'session': 'session-1',
                        'result': 'ready'}
        first = self._device('POST', '/api/v2/client/receipts', secrets_map['screen-windows'],
                             receipt_body)
        self.assertEqual(first.status_code, 200, first.get_data(as_text=True))
        again = self._device('POST', '/api/v2/client/receipts', secrets_map['screen-windows'],
                             receipt_body)
        self.assertEqual(again.status_code, 200)
        self.assertEqual(self.state.page_activation(document['plan']['id'])['activated'], 1)
        android_receipt = dict(receipt_body, receipt_id='android-1', device_id='screen-android',
                               package_id=android_pkg, mode='kiosk', session='session-2')
        self.assertEqual(self._device('POST', '/api/v2/client/receipts',
                                      secrets_map['screen-android'], android_receipt).status_code,
                         200)
        self.assertEqual(self.state.page_activation(document['plan']['id'])['activated'], 2)
        cross_receipt = dict(receipt_body, receipt_id='cross-1', package_id=android_pkg)
        refused_receipt = self._device('POST', '/api/v2/client/receipts',
                                       secrets_map['screen-windows'], cross_receipt)
        self.assertEqual(refused_receipt.status_code, 409)
        self.assertEqual(refused_receipt.get_json()['error'], 'unknown_assignment')

        retry = self._approve(document, signed, receipt)
        self.assertEqual(retry.status_code, 200)
        self.assertEqual(retry.get_json()['distribution']['generation'], 1)
        self.assertEqual(self.state.page_activation(document['plan']['id'])['activated'], 2)

    def test_changed_target_refusal_and_legacy_retention(self):
        secrets_map = self._devices()
        self._graph()
        first = self._prepare()
        signed, receipt = self._sign(first['document'], first['targets'])
        response = self._approve(first['document'], signed, receipt)
        self.assertEqual(response.status_code, 200, response.get_data(as_text=True))
        first_packages = {item['device_id']: item['package_id']
                          for item in review_module.validate_page(
                              first['document'], targets=first['targets'], user_id=ADMIN,
                              group_id=GROUP, origin=CONTENT_ORIGIN,
                              now=self.workspace.now(), files=self._files(first['document'])
                          )['targets']}

        # Android becomes legacy/local; a new device joins. The second plan
        # therefore targets windows + extra, not the retained android row.
        self.state.select_profile('screen-android', 'events-default')
        with self.state.connection() as db:
            db.execute('INSERT INTO devices VALUES (?,?,?,?,?,0)',
                       ('screen-extra', PROFILE, 'credential-screen-extra',
                        sha(bytes.fromhex(secrets.token_hex(32))), self.now + 86400))
            body = capability({
                'version': 1, 'platform': 'windows', 'modes': ['tv'],
                'content': ['events'], 'resource_profile': PROFILE,
                'renderer': renderer_identity(),
                'pages_renderer': page_materialize.renderer_identity()['build_id']})
            db.execute('INSERT INTO device_capabilities VALUES (?,?)',
                       ('screen-extra', encode(body)))
        self.state.select_profile('screen-extra', 'extra-profile')
        self._save_event('1004', event_payload('Independent second', 4, status='hidden'))
        self._save_page(object_id('assignment', 3),
                        {'schema': 1, 'device': 'screen-extra',
                         'profile': object_id('profile'), 'selection': None},
                        {object_id('profile'): 1})

        second = self._prepare()
        self.assertEqual([item['device_id'] for item in second['targets']],
                         ['screen-extra', 'screen-windows'])
        signed2, receipt2 = self._sign(second['document'], second['targets'])
        # The exact server-managed set changes before commit: refuse without
        # storing approval, heads or assignments. The signed approval is not
        # consumed and a fresh confirmation is required for a changed plan.
        self.state.select_profile('screen-extra', 'events-default')
        changed = self._approve(second['document'], signed2, receipt2)
        self.assertEqual(changed.status_code, 409)
        self.assertEqual(changed.get_json()['error'], 'page_targets_changed')
        self.assertFalse(self.workspace.plan_state(second['document']['plan']['id'])['approved'])
        with self.state.connection(write=False) as db:
            self.assertIsNone(db.execute(
                'SELECT * FROM page_plan_commits WHERE plan_id=?',
                (second['document']['plan']['id'],)).fetchone())
        self.assertEqual(self.state.page_assignment(
            {'device_id': 'screen-windows', 'profile': PROFILE},
            'display-profile-v2', page_materialize.renderer_identity()['build_id'],
            PROFILE)['generation'], 1)

        # Restore the exact target configuration and retry the same signed plan.
        self.state.select_profile('screen-extra', 'extra-profile')
        retried = self._approve(second['document'], signed2, receipt2)
        self.assertEqual(retried.status_code, 200, retried.get_data(as_text=True))
        self.assertEqual(retried.get_json()['distribution']['generation'], 2)
        self.assertEqual(self.state.page_assignment(
            {'device_id': 'screen-windows', 'profile': PROFILE},
            'display-profile-v2', page_materialize.renderer_identity()['build_id'],
            PROFILE)['generation'], 2)
        legacy = self.state.page_assignment(
            {'device_id': 'screen-android', 'profile': PROFILE},
            'display-profile-v2', page_materialize.renderer_identity()['build_id'],
            PROFILE)
        self.assertEqual(legacy['generation'], 1)
        self.assertEqual(legacy['metadata']['publication']['package_id'],
                         first_packages['screen-android'])
        with self.state.connection(write=False) as db:
            current = db.execute('SELECT generation,package_id FROM page_assignments '
                                 'WHERE device_id=?', ('screen-android',)).fetchone()
            self.assertEqual(current['generation'], 1)
            self.assertEqual(current['package_id'], first_packages['screen-android'])
            history = db.execute('SELECT COUNT(*) FROM page_assignment_history '
                                 'WHERE device_id=?', ('screen-android',)).fetchone()[0]
            self.assertEqual(history, 1)
        repeat = self._approve(second['document'], signed2, receipt2)
        self.assertEqual(repeat.status_code, 200)
        self.assertEqual(repeat.get_json()['distribution']['generation'], 2)

    def test_native_shared_interface_journey_and_refusals(self):
        secrets_map = self._devices()
        self._graph()
        client, csrf = self._browser()
        ticket = self._native_ticket(client, csrf)
        token = ticket['token']
        self.assertEqual(ticket['version'], 1)
        # Both shipped native clients consume this exact fragment field set.
        parsed = urlsplit(ticket['handoff'])
        self.assertEqual((parsed.scheme, parsed.netloc, parsed.path),
                         ('kiosk', 'roaming', '/page'))
        fields = parse_qs(parsed.fragment)
        self.assertEqual(set(fields), {'version', 'token', 'expires',
                                       'content_origin', 'maintenance_origin'})
        self.assertEqual(fields['version'], ['1'])
        self.assertEqual(fields['token'], [token])
        self.assertEqual(fields['content_origin'], [CONTENT_ORIGIN])
        self.assertEqual(fields['maintenance_origin'], [MAINTENANCE_ORIGIN])
        with self.store.connection(write=False) as db:
            stored = db.execute('SELECT * FROM page_native_tickets').fetchone()
            self.assertEqual(stored['token_sha256'],
                             hashlib.sha256(token.encode('ascii')).hexdigest())
            self.assertNotIn(token, ' '.join(str(value) for value in tuple(stored)))

        native_key = generate_private_key()
        chain, _, _ = self._root_grant(native_key)
        refused = self._native_call('POST', '/api/page/native/open', 'ab' * 32, {
            'approval': publisher_authority.signed(native_key, 'page-review-open', {}),
            'chain': chain})
        self.assertEqual(refused.status_code, 401)
        self.assertEqual(refused.get_json()['error'], 'native_ticket_required')
        foreign_chain, _, _ = self._root_grant(native_key, user_id='other')
        foreign = self._native_call(
            'POST', '/api/page/native/open', token,
            {'approval': publisher_authority.signed(native_key, 'page-review-open', {
                'token_sha256': hashlib.sha256(token.encode('ascii')).hexdigest(),
                'content_origin': CONTENT_ORIGIN,
                'maintenance_origin': MAINTENANCE_ORIGIN}), 'chain': foreign_chain})
        self.assertEqual(foreign.status_code, 403)
        self.assertEqual(foreign.get_json()['error'], 'native_user_refused')
        wrong_open = self._native_call(
            'POST', '/api/page/native/open', token,
            {'approval': publisher_authority.signed(
                self._wrong_key(), 'page-review-open', {
                    'token_sha256': hashlib.sha256(token.encode('ascii')).hexdigest(),
                    'content_origin': CONTENT_ORIGIN,
                    'maintenance_origin': MAINTENANCE_ORIGIN}), 'chain': chain})
        self.assertEqual(wrong_open.status_code, 403)
        self.assertEqual(wrong_open.get_json()['error'], 'native_open_refused')

        document = self._native_open(token, native_key, chain)
        self.assertEqual(document['plan']['device_id'], key_id(spki_der(native_key)))
        files = self._files(document)
        for target in document['targets']:
            for entry in target['metadata']['publication']['package']['files']:
                fetched = self._native_call(
                    'GET', f"/api/page/native/package/{target['device_id']}/{entry['path']}",
                    token)
                self.assertEqual(fetched.status_code, 200)
                self.assertEqual(fetched.data, files[target['device_id']]['package'][entry['path']])

        plan = document['plan']
        wrong_approval = publisher_authority.page_signed(self._wrong_key(), plan)
        wrong = self._native_call('POST', '/api/page/native/approve', token, {
            'id': plan['id'], 'approval': wrong_approval, 'chain': chain})
        self.assertEqual(wrong.status_code, 403)
        self.assertEqual(wrong.get_json()['error'], 'native_approval_refused')

        browser_only = client.post('/api/page/publish', json={'id': plan['id'],
                                                              'confirm': True},
                                   headers={'X-CSRF-Token': csrf},
                                   base_url=MAINTENANCE_ORIGIN)
        self.assertEqual(browser_only.status_code, 409)
        self.assertEqual(browser_only.get_json()['error'], 'native_approval_required')

        approval = publisher_authority.page_signed(native_key, plan)
        approved = self._native_call('POST', '/api/page/native/approve', token, {
            'id': plan['id'], 'approval': approval, 'chain': chain})
        self.assertEqual(approved.status_code, 200, approved.get_data(as_text=True))
        distribution = approved.get_json()['distribution']
        self.assertEqual((distribution['generation'], distribution['targets']), (1, 2))
        renderer = page_materialize.renderer_identity()['build_id']
        for device_id in ('screen-windows', 'screen-android'):
            served = self._device(
                'GET', '/api/v2/client/assignment?display_protocol=display-profile-v2'
                       f'&pages_renderer={renderer}&resource_profile={PROFILE}',
                secrets_map[device_id]).get_json()
            self.assertEqual(served['version'], 4)
            self.assertEqual(served['publisher']['approval'], approval)
            self.assertEqual(served['publisher']['chain'], chain)
        self.assertEqual(self.state.page_activation(plan['id'])['activated'], 0)
        for device_id, mode in (('screen-windows', 'tv'), ('screen-android', 'kiosk')):
            target = next(item for item in document['targets']
                          if item['device_id'] == device_id)
            receipt = self._device('POST', '/api/v2/client/receipts', secrets_map[device_id], {
                'version': 1, 'receipt_id': device_id + '-1', 'group_id': GROUP,
                'device_id': device_id, 'generation': 1,
                'package_id': target['metadata']['publication']['package_id'],
                'mode': mode, 'session': 'native', 'result': 'ready'})
            self.assertEqual(receipt.status_code, 200, receipt.get_data(as_text=True))
        self.assertEqual(self.state.page_activation(plan['id'])['activated'], 2)
        repeat = self._native_call('POST', '/api/page/native/approve', token, {
            'id': plan['id'], 'approval': approval, 'chain': chain})
        self.assertEqual(repeat.status_code, 200)
        self.assertEqual(repeat.get_json()['distribution']['generation'], 1)
        self.assertEqual(self.state.page_activation(plan['id'])['activated'], 2)

    def test_native_lost_response_reuses_receipt_and_changed_approval_refused(self):
        self._devices()
        self._graph()
        client, csrf = self._browser()
        token = self._native_ticket(client, csrf)['token']
        native_key = generate_private_key()
        chain, _, _ = self._root_grant(native_key)
        document = self._native_open(token, native_key, chain)
        plan = document['plan']
        approval = publisher_authority.page_signed(native_key, plan)
        value = {'id': plan['id'], 'approval': approval, 'chain': chain}
        self.inprocess.fail_after_commit = True
        lost = self._native_call('POST', '/api/page/native/approve', token, value)
        self.assertEqual(lost.status_code, 502)
        self.assertEqual(lost.get_json()['error'], 'content_unavailable')
        # Content committed; Maintenance only lost the response. The exact
        # receipt is already durable and state is not finished.
        self.assertTrue(self.workspace.plan_state(plan['id'])['approved'])
        self.assertEqual(self.state.page_assignment(
            {'device_id': 'screen-windows', 'profile': PROFILE},
            'display-profile-v2', page_materialize.renderer_identity()['build_id'],
            PROFILE)['generation'], 1)
        digest = hashlib.sha256(token.encode('ascii')).hexdigest()
        with self.store.connection(write=False) as db:
            ticket = db.execute('SELECT * FROM page_native_tickets WHERE token_sha256=?',
                                (digest,)).fetchone()
            self.assertEqual(ticket['state'], 'committing')
            self.assertIsNotNone(ticket['receipt'])
            self.assertIsNotNone(ticket['acceptance_key'])
        retried = self._native_call('POST', '/api/page/native/approve', token, value)
        self.assertEqual(retried.status_code, 200, retried.get_data(as_text=True))
        self.assertEqual(retried.get_json()['distribution']['generation'], 1)
        with self.state.connection(write=False) as db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM page_plan_commits'
                                        ).fetchone()[0], 1)
            self.assertEqual(db.execute('SELECT COUNT(*) FROM page_assignment_history'
                                        ).fetchone()[0], 2)
        changed_approval = publisher_authority.page_signed(
            native_key, dict(plan, expires=plan['expires'] - 1))
        changed = self._native_call('POST', '/api/page/native/approve', token, {
            'id': plan['id'], 'approval': changed_approval, 'chain': chain})
        self.assertEqual(changed.status_code, 409)
        self.assertEqual(changed.get_json()['error'], 'native_approval_changed')
        different = self._native_call('POST', '/api/page/native/approve', token, {
            'id': 'f' * 64, 'approval': approval, 'chain': chain})
        self.assertEqual(different.status_code, 409)
        self.assertEqual(different.get_json()['error'], 'native_ticket_required')

    def test_native_stale_review_refused_without_commit(self):
        self._devices()
        self._graph()
        client, csrf = self._browser()
        token = self._native_ticket(client, csrf)['token']
        native_key = generate_private_key()
        chain, _, _ = self._root_grant(native_key)
        document = self._native_open(token, native_key, chain)
        plan = document['plan']
        approval = publisher_authority.page_signed(native_key, plan)
        self._save_event('1005', event_payload('Late ready', 5, status='hidden'))
        stale = self._native_call('POST', '/api/page/native/approve', token, {
            'id': plan['id'], 'approval': approval, 'chain': chain})
        self.assertEqual(stale.status_code, 409, stale.get_data(as_text=True))
        self.assertEqual(stale.get_json()['error'], 'native_plan_changed')
        self.assertFalse(self.workspace.plan_state(plan['id'])['approved'])
        self.assertIsNone(self.state.page_activation(plan['id']))
        with self.state.connection(write=False) as db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM page_plan_commits'
                                        ).fetchone()[0], 0)

    def test_historical_excluded_edit_refused_while_independent_ready_proceeds(self):
        self._devices()
        self._graph()
        first = self._prepare()
        signed, receipt = self._sign(first['document'], first['targets'])
        approved = self._approve(first['document'], signed, receipt)
        self.assertEqual(approved.status_code, 200, approved.get_data(as_text=True))
        self.assertEqual(approved.get_json()['distribution']['generation'], 1)

        version = self.workspace.save(self.secret, '1003', 1,
                                      event_payload('Independent ready two', 3,
                                                    status='hidden'), {})
        self.workspace.ready(self.secret, '1003', version)
        second = self._prepare()
        second_ids = {item['id']: item['version']
                      for item in second['document']['revision']['plan']['included']}
        self.assertEqual(second_ids.get('1003'), 2)
        signed2, receipt2 = self._sign(second['document'], second['targets'])
        independent = self._approve(second['document'], signed2, receipt2)
        self.assertEqual(independent.status_code, 200, independent.get_data(as_text=True))
        self.assertEqual(independent.get_json()['distribution']['generation'], 2)

        # A newer excluded draft of already-published data must invalidate the
        # frozen plan even when another, independent ready change is included.
        self.workspace.save(self.secret, '1001', 1,
                            event_payload('Edited old notice', 1,
                                          ['/static/uploads/notice.png']), {})
        version = self.workspace.save(self.secret, '1004', 0,
                                      event_payload('Independent three', 4,
                                                    status='hidden'), {})
        self.workspace.ready(self.secret, '1004', version)
        third = self._prepare()
        plan = third['document']['revision']['plan']
        self.assertIn('1004', {item['id'] for item in plan['included']})
        self.assertEqual({item['id']: item['reason'] for item in plan['excluded']}
                         .get('1001'), 'working')
        self.assertEqual(third['document']['revision']['objects']['1001']['version'], 1)
        signed3, receipt3 = self._sign(third['document'], third['targets'])
        refused = self._approve(third['document'], signed3, receipt3)
        self.assertEqual(refused.status_code, 409, refused.get_data(as_text=True))
        self.assertEqual(refused.get_json()['error'], 'prepared_revision_changed')
        self.assertFalse(self.workspace.plan_state(third['document']['plan']['id'])['approved'])
        with self.state.connection(write=False) as db:
            self.assertIsNone(db.execute(
                'SELECT * FROM page_plan_commits WHERE plan_id=?',
                (third['document']['plan']['id'],)).fetchone())
            self.assertEqual(db.execute('SELECT max(generation) FROM page_plan_commits'
                                        ).fetchone()[0], 2)
        repeat = self._approve(third['document'], signed3, receipt3)
        self.assertEqual(repeat.status_code, 409)
        self.assertEqual(repeat.get_json()['error'], 'prepared_revision_changed')

    def test_same_page_bytes_keep_distinct_platform_wrappers(self):
        secrets_map = self._devices()
        android_tv_secret = secrets.token_hex(32)
        with self.state.connection() as db:
            db.execute('INSERT INTO devices VALUES (?,?,?,?,?,0)',
                       ('screen-android-tv', PROFILE, 'credential-android-tv',
                        sha(bytes.fromhex(android_tv_secret)), self.now + 86400))
            body = capability({
                'version': 1, 'platform': 'android', 'modes': ['tv'],
                'content': ['events'], 'resource_profile': PROFILE,
                'renderer': renderer_identity(),
                'pages_renderer': page_materialize.renderer_identity()['build_id']})
            db.execute('INSERT INTO device_capabilities VALUES (?,?)',
                       ('screen-android-tv', encode(body)))
        self.state.select_profile('screen-android-tv', 'tv-profile')
        self._graph()
        self._save_page(object_id('assignment', 4),
                        {'schema': 1, 'device': 'screen-android-tv',
                         'profile': object_id('profile'), 'selection': None},
                        {object_id('profile'): 1})
        secrets_map['screen-android-tv'] = android_tv_secret
        prepared = self._prepare()
        packages = {item['device_id']: item['package_id']
                    for item in review_module.validate_page(
                        prepared['document'], targets=prepared['targets'],
                        user_id=ADMIN, group_id=GROUP, origin=CONTENT_ORIGIN,
                        now=self.workspace.now(),
                        files=self._files(prepared['document']))['targets']}
        self.assertEqual(packages['screen-windows'], packages['screen-android-tv'])
        self.assertNotEqual(packages['screen-windows'], packages['screen-android'])
        signed, receipt = self._sign(prepared['document'], prepared['targets'])
        approved = self._approve(prepared['document'], signed, receipt)
        self.assertEqual(approved.status_code, 200, approved.get_data(as_text=True))
        root = self.state.root / 'publications' / packages['screen-windows']
        names = sorted(path.name for path in root.iterdir())
        self.assertIn('delivery.json', names)
        self.assertEqual(len([name for name in names if name.startswith('page-')
                              and name.endswith('.json')]), 2)
        renderer = page_materialize.renderer_identity()['build_id']
        served = {}
        for device_id in ('screen-windows', 'screen-android-tv'):
            value = self._device(
                'GET', '/api/v2/client/assignment?display_protocol=display-profile-v2'
                       f'&pages_renderer={renderer}&resource_profile={PROFILE}',
                secrets_map[device_id]).get_json()
            served[device_id] = value
            self.assertEqual(value['metadata']['publication']['package_id'],
                             packages['screen-windows'])
        self.assertEqual(served['screen-windows']['destination'], 'windows-pages-v1')
        self.assertEqual(served['screen-android-tv']['destination'], 'android-pages-v1')
        self.assertNotEqual(served['screen-windows']['metadata_sha256'],
                            served['screen-android-tv']['metadata_sha256'])
        for device_id in ('screen-windows', 'screen-android-tv'):
            response = self._device(
                'GET', f"/api/v2/publications/{packages['screen-windows']}/package/"
                       f"data/page-release.json", secrets_map[device_id])
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.data,
                             self._files(prepared['document'])[device_id]['package'][
                                 'data/page-release.json'])

    def test_v1_publish_route_still_operates(self):
        self._devices()
        self.workspace.stage6_pages = False
        with self.store.connection() as db:
            granted = self.authority.grant(db, ADMIN)
        self.secret = self.workspace.create_service_session(ADMIN, granted['chain'])
        version = self.workspace.save(self.secret, '1', 0, {
            'title': 'Version one event', 'short_description': '', 'full_description': '',
            'event_date': '2026-11-16', 'place': 'Hall', 'sort_order': 0,
            'status': 'active', 'images': [], 'tags': []}, {})
        self.workspace.ready(self.secret, '1', version)
        client, csrf = self._browser()
        review = client.post('/api/review',
                             json={'selected': {'1': version}, 'parents': []},
                             headers={'X-CSRF-Token': csrf},
                             base_url=MAINTENANCE_ORIGIN)
        self.assertEqual(review.status_code, 200, review.get_data(as_text=True))
        identity = review.get_json()['id']
        published = client.post('/api/publish',
                                json={'id': identity, 'confirm': True},
                                headers={'X-CSRF-Token': review.get_json()['csrf']},
                                base_url=MAINTENANCE_ORIGIN)
        self.assertEqual(published.status_code, 200, published.get_data(as_text=True))
        self.assertEqual(published.get_json()['state'], 'committed')
        self.assertEqual(published.get_json()['distribution']['targets'], 2)

    def test_native_session_lock_and_permission_loss_refused(self):
        self._devices()
        self._graph()
        client, csrf = self._browser()
        token = self._native_ticket(client, csrf)['token']
        native_key = generate_private_key()
        chain, _, _ = self._root_grant(native_key)
        document = self._native_open(token, native_key, chain)
        approval = publisher_authority.page_signed(native_key, document['plan'])
        locked = client.post('/api/lock', json={},
                             headers={'X-CSRF-Token': csrf},
                             base_url=MAINTENANCE_ORIGIN)
        self.assertEqual(locked.status_code, 200, locked.get_data(as_text=True))
        refused = self._native_call('POST', '/api/page/native/approve', token, {
            'id': document['plan']['id'], 'approval': approval, 'chain': chain})
        self.assertEqual(refused.status_code, 401)
        self.assertEqual(refused.get_json()['error'], 'native_session_required')

        client, csrf = self._browser()
        token = self._native_ticket(client, csrf)['token']
        document = self._native_open(token, native_key, chain)
        approval = publisher_authority.page_signed(native_key, document['plan'])
        with self.store.connection() as db:
            db.execute("DELETE FROM grants WHERE subject_type='user' AND subject_id=?",
                       (ADMIN,))
        refused = self._native_call('POST', '/api/page/native/approve', token, {
            'id': document['plan']['id'], 'approval': approval, 'chain': chain})
        self.assertEqual(refused.status_code, 403)
        self.assertEqual(refused.get_json()['error'], 'permission_required')
        self.assertFalse(self.workspace.plan_state(document['plan']['id'])['approved'])

    def test_native_ticket_expiry_refuses_confirmation(self):
        self._devices()
        self._graph()
        now = int(self.workspace.now())
        self._set_clock(now)
        client, csrf = self._browser()
        token = self._native_ticket(client, csrf)['token']
        native_key = generate_private_key()
        chain, _, _ = self._root_grant(native_key)
        document = self._native_open(token, native_key, chain)
        approval = publisher_authority.page_signed(native_key, document['plan'])
        self._set_clock(now + 6 * 60)
        refused = self._native_call('POST', '/api/page/native/approve', token, {
            'id': document['plan']['id'], 'approval': approval, 'chain': chain})
        self.assertEqual(refused.status_code, 410)
        self.assertEqual(refused.get_json()['error'], 'native_ticket_expired')
        self.assertFalse(self.workspace.plan_state(document['plan']['id'])['approved'])

    def test_released_assignment_admitted_after_review_window(self):
        secrets_map = self._devices()
        self._graph()
        now = int(self.workspace.now())
        self._set_clock(now)
        prepared = self._prepare()
        signed, receipt = self._sign(prepared['document'], prepared['targets'])
        approved = self._approve(prepared['document'], signed, receipt)
        self.assertEqual(approved.status_code, 200, approved.get_data(as_text=True))
        renderer = page_materialize.renderer_identity()['build_id']
        value = self._device(
            'GET', '/api/v2/client/assignment?display_protocol=display-profile-v2'
                   f'&pages_renderer={renderer}&resource_profile={PROFILE}',
            secrets_map['screen-windows']).get_json()
        plan = self.workspace.approved(prepared['document']['plan']['id'])[0]['plan']
        later = now + 16 * 60
        self.assertGreater(plan['expires'], later)
        self._set_clock(later)
        publisher_authority.page_assignment(
            value['publisher'], value, self.authority.root, CONTENT_ORIGIN, later)

    def _wrong_key(self):
        from kiosk.trust.crypto import generate_private_key
        return generate_private_key()


if __name__ == '__main__':
    unittest.main()
