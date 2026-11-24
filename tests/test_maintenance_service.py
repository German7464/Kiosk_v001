import base64
import hashlib
import hmac
import json
import secrets
import tempfile
import time
import unittest
from pathlib import Path

from flask import current_app

from kiosk.delivery.protocol import encode, sha
from kiosk.maintenance import accounts, cycle, permissions, sessions
from kiosk.maintenance.authority import MaintenanceAuthority
from kiosk.maintenance.relocation import (RelocationError, export_maintenance,
                                          import_maintenance)
from kiosk.maintenance.store import MaintenanceError, MaintenanceStore
from kiosk.publication import authority as publication
from kiosk.publication.workspace import Workspace, WorkspaceError
from kiosk.trust.crypto import load_private, spki_der
from tools.publisher_authority import init as init_authority

PASSWORD = 'correct-horse-battery-staple'
ORIGIN = 'https://127.0.0.1:24443'
GROUP = 'group-lab'
CLOCK = 1_800_000_000


class Fixture:
    """Minimal independent root + maintenance authority for relocation tests."""

    def __init__(self, root):
        self.root = Path(root)
        authority_dir = self.root / 'authority'
        self.public = init_authority(authority_dir, GROUP, ORIGIN, 'authority-password-12', CLOCK)
        self.root_key = load_private((authority_dir / 'authority-key.pem').read_text(),
                                     'authority-password-12')
        self.policy = json.loads((authority_dir / 'policy.json').read_text())

    def store(self, name='maintenance.sqlite'):
        store = MaintenanceStore(self.root / name, clock=lambda: CLOCK)
        return store

    def authority(self, store):
        return MaintenanceAuthority(store, self.root / 'secrets', self.public, self.policy,
                                    clock=lambda: CLOCK)

    def populate(self, store, authority, user='admin'):
        store.configure_placement('combined', 'maintenance', 'n1', ORIGIN,
                                  counterpart='https://127.0.0.1:25443')
        with store.connection() as db:
            accounts.create_user(db, user, PASSWORD, 'administrator', now=CLOCK)
            db.execute("INSERT INTO grants (subject_type,subject_id,bundle,groups,created_by,"
                       "created) VALUES ('user',?,?,?,?,?)",
                       (user, 'system-administrator', json.dumps([GROUP]), user, CLOCK))
            row, key = authority.ensure_key(db, user)
            grant = dict(group_id=GROUP, origin=ORIGIN, user_id=user, role='administrator',
                         device_key=base64.b64encode(spki_der(key)).decode('ascii'),
                         issued=CLOCK, expires=CLOCK + 90 * 86400, can_delegate=True)
            chain = [publication.signed(self.root_key, 'device', grant)]
            authority.install_grant(db, user, chain, self.policy)


class ServiceAuthTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from kiosk.maintenance.setup import create_lab
        cls.temp = tempfile.TemporaryDirectory()
        root = Path(cls.temp.name) / 'lab'
        cls.created = create_lab(root, mode='combined',
                                 content_origin='https://127.0.0.1:24443',
                                 maintenance_origin='https://127.0.0.1:25443',
                                 group_id=GROUP, admin_user='admin',
                                 admin_password=PASSWORD)
        from tools.kiosk_maintenance_lab import content_application, maintenance_application
        cls.content = content_application(cls.created['content_config'])
        cls.maintenance = maintenance_application(cls.created['maintenance_config'])

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def test_public_authority_delivery_requires_mac_and_rejects_scope_change(self):
        from kiosk.publication import service_api
        state = self.content.extensions['device_delivery']
        config = self.content.config['MAINTENANCE_SERVICE']
        root = Path(self.created['root'])
        policy = json.loads((root / 'authority/policy.json').read_text())
        trust = state.configuration()['trust']

        def deliver(value, authenticated=True):
            raw = encode(value)
            path = '/service/v1/authority'
            stamp, nonce = str(int(time.time())), secrets.token_hex(32)
            digest = sha(raw)
            message = '\n'.join((config['service_id'], 'POST', path, stamp, nonce, digest))
            headers = {'Content-Type': 'application/json'}
            if authenticated:
                headers.update({'X-Kiosk-Service-Id': config['service_id'], 'X-Kiosk-Time': stamp,
                                'X-Kiosk-Nonce': nonce, 'X-Kiosk-Body-SHA256': digest,
                                'X-Kiosk-Signature': hmac.new(config['secret'].encode(), message.encode(), hashlib.sha256).hexdigest()})
            return self.content.test_client().post(path, data=raw, headers=headers, base_url=ORIGIN)

        self.assertEqual(deliver(dict(policy=policy, trust=trust), False).status_code, 403)
        self.assertEqual(deliver(dict(policy=policy, trust=trust)).status_code, 200)
        self.assertEqual(deliver(dict(policy=policy, trust=trust)).status_code, 200)
        tampered = dict(trust, signature_base64=base64.b64encode(bytes(384)).decode())
        self.assertEqual(deliver(dict(policy=policy, trust=tampered)).status_code, 503)
        self.assertEqual(state.configuration()['trust'], trust)

    def test_signed_request_time_replay_and_body_binding(self):
        from kiosk.publication import service_api
        store = self.content.extensions['roaming_workspace']
        config = self.content.config['MAINTENANCE_SERVICE']
        body = encode({'user_id': 'admin', 'chain': []})
        path = '/service/v1/session'

        def headers(nonce, stamp, digest, signature):
            return {'X-Kiosk-Service-Id': config['service_id'], 'X-Kiosk-Time': str(stamp),
                    'X-Kiosk-Nonce': nonce, 'X-Kiosk-Body-SHA256': digest,
                    'X-Kiosk-Signature': signature, 'Content-Type': 'application/json'}

        def sign(nonce, stamp, digest):
            message = '\n'.join((config['service_id'], 'POST', path, str(stamp), nonce, digest))
            return hmac.new(config['secret'].encode(), message.encode(),
                            hashlib.sha256).hexdigest()

        now = store.now()
        digest = hashlib.sha256(body).hexdigest()
        nonce = secrets.token_hex(32)
        with self.content.test_request_context(path, method='POST', data=body,
                                               base_url=ORIGIN, headers=headers(
                                                   nonce, now, digest, sign(nonce, now, digest))):
            self.assertEqual(service_api.authenticate()['service_id'], config['service_id'])
        nonce2 = secrets.token_hex(32)
        with self.content.test_request_context(path, method='POST', data=body,
                                               base_url=ORIGIN, headers=headers(
                                                   nonce2, now, digest,
                                                   sign(nonce2, now, digest))):
            service_api.authenticate()
            with self.assertRaises(WorkspaceError) as caught:
                service_api.authenticate()
            self.assertEqual(caught.exception.code, 'service_replay_refused')
        stale = now - 3600
        nonce3 = secrets.token_hex(32)
        with self.content.test_request_context(path, method='POST', data=body,
                                               base_url=ORIGIN, headers=headers(
                                                   nonce3, stale, digest,
                                                   sign(nonce3, stale, digest))):
            with self.assertRaises(WorkspaceError) as caught:
                service_api.authenticate()
            self.assertEqual(caught.exception.code, 'service_time_refused')
        nonce4 = secrets.token_hex(32)
        with self.content.test_request_context(path, method='POST', data=body,
                                               base_url=ORIGIN, headers=headers(
                                                   nonce4, now, digest,
                                                   sign(nonce4, now, digest)[:-2] + '00')):
            with self.assertRaises(WorkspaceError) as caught:
                service_api.authenticate()
            self.assertEqual(caught.exception.code, 'service_signature_refused')

    def test_fenced_content_refuses_privileged_routes(self):
        store = self.content.extensions['roaming_workspace']
        store.fence('test')
        try:
            with self.content.test_request_context('/service/v1/session', method='POST',
                                                   data=encode({'user_id': 'admin',
                                                                'chain': []}),
                                                   base_url=ORIGIN):
                from kiosk.publication import service_api
                with self.assertRaises(WorkspaceError) as caught:
                    service_api.require_active()
                self.assertEqual(caught.exception.code, 'service_fenced')
        finally:
            store.configure_placement('combined', ORIGIN)

    def test_combined_setup_has_distinct_origins_data_and_secrets(self):
        content = json.loads(Path(self.created['content_config']).read_text())
        maintenance = json.loads(Path(self.created['maintenance_config']).read_text())
        self.assertNotEqual(content['ROAMING_WORKSPACE']['origin'],
                            maintenance['MAINTENANCE_ORIGIN'])
        self.assertNotEqual(content['ROAMING_WORKSPACE']['database'],
                            maintenance['MAINTENANCE_DATABASE'])
        self.assertNotEqual(content['SECRET_KEY'], maintenance['SECRET_KEY'])
        self.assertNotIn('TV', maintenance)
        self.assertNotIn('KIOSK', maintenance)
        self.assertEqual(maintenance['MAINTENANCE_PLACEMENT']['mode'], 'combined')


class Browser:
    """Smallest real HTTP browser stand-in: cookie jar plus CSRF handling."""

    def __init__(self, app, origin):
        self.client = app.test_client()
        self.origin = origin
        self.csrf = ''

    def request(self, method, path, payload=None, *, status=200):
        if self.csrf == '' and method != 'GET':
            self.get('/api/state')
        headers = {'Accept': 'application/json'}
        if payload is not None:
            headers['Content-Type'] = 'application/json'
            headers['X-CSRF-Token'] = self.csrf
        response = self.client.open(path, method=method, json=payload, headers=headers,
                                    base_url=self.origin)
        value = response.get_json(silent=True) or {}
        if isinstance(value.get('csrf'), str):
            self.csrf = value['csrf']
        if response.status_code != status:
            raise AssertionError(f'{path} returned {response.status_code}, expected {status}: '
                                 f'{value}')
        return value

    def get(self, path, payload=None, status=200):
        return self.request('GET', path, None, status=status)

    def post(self, path, payload, status=200):
        return self.request('POST', path, payload, status=status)


class BrowserApiTests(unittest.TestCase):
    """Blockers reproduced through the public Maintenance HTTP API."""

    def setUp(self):
        from kiosk.maintenance.setup import create_lab
        from tools.kiosk_maintenance_lab import maintenance_application
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        root = Path(self.temp.name) / 'lab'
        self.created = create_lab(root, mode='combined',
                                  content_origin='https://127.0.0.1:24443',
                                  maintenance_origin='https://127.0.0.1:25443',
                                  group_id=GROUP, admin_user='admin',
                                  admin_password=PASSWORD)
        self.app = maintenance_application(self.created['maintenance_config'])
        from kiosk.core.request_security import AuthenticationLimiter
        self.app.extensions['maintenance_limiter'] = AuthenticationLimiter(
            account_limit=10000, source_limit=10000)

    def browser(self):
        return Browser(self.app, 'https://127.0.0.1:25443')

    def test_lan_csr_route_requires_dedicated_mac_and_refuses_fenced_issuer(self):
        import ipaddress
        from cryptography import x509
        from cryptography.hazmat.primitives import hashes, serialization
        from cryptography.x509.oid import NameOID
        from kiosk.maintenance.tls import SERVICE_ID, PATH
        from kiosk.trust.crypto import generate_private_key
        key = generate_private_key()
        csr = (x509.CertificateSigningRequestBuilder()
               .subject_name(x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, 'requested')]))
               .add_extension(x509.SubjectAlternativeName([x509.IPAddress(ipaddress.ip_address('127.0.0.1'))]), False)
               .sign(key, hashes.SHA256()).public_bytes(serialization.Encoding.PEM).decode())
        payload = encode(dict(csr=csr))
        store = self.app.extensions['maintenance_store']
        with store.connection(write=False) as db:
            config = json.loads(bytes(db.execute('SELECT configuration FROM tls_issuer').fetchone()[0]))
        client = self.app.test_client()

        def request(headers=None):
            return client.post(PATH, data=payload, headers=dict({'Content-Type': 'application/json'}, **(headers or {})),
                               base_url='https://127.0.0.1:25443')

        def authorization():
            stamp, nonce = str(store.now()), secrets.token_hex(32)
            digest = sha(payload)
            message = '\n'.join((SERVICE_ID, 'POST', PATH, stamp, nonce, digest)).encode()
            return {'X-Kiosk-Service-Id': SERVICE_ID, 'X-Kiosk-Time': stamp, 'X-Kiosk-Nonce': nonce,
                    'X-Kiosk-Body-SHA256': digest,
                    'X-Kiosk-Signature': hmac.new(config['client_secret'].encode(), message, hashlib.sha256).hexdigest()}

        self.assertEqual(request().status_code, 403)
        headers = authorization()
        response = request(headers)
        self.assertEqual(response.status_code, 200)
        leaf = x509.load_pem_x509_certificate(response.json['chain_pem'].encode())
        self.assertEqual(spki_der(leaf.public_key()), spki_der(key))
        self.assertNotIn('PRIVATE KEY', response.get_data(as_text=True))
        self.assertEqual(request(headers).status_code, 409)
        store.fence('transfer', handoff=True)
        self.assertEqual(request(authorization()).status_code, 409)

    def test_local_expiry_diagnostics_are_available_after_login(self):
        browser = self.browser()
        self.assertNotIn('authority_lifecycle', browser.get('/api/state'))
        self.login(browser)
        value = browser.get('/api/state')['authority_lifecycle']
        self.assertFalse(value['unattended_interval_proven'])
        self.assertEqual(value['unavailable'], [])
        self.assertIn('publisher_policy', [item['name'] for item in value['deadlines']])
        self.assertNotIn('key.pem', json.dumps(value))

    def test_administrator_recovers_retained_maintenance_key_through_http(self):
        browser = self.browser()
        self.login(browser)
        authority = self.app.extensions['maintenance_authority']
        store = self.app.extensions['maintenance_store']
        root = Path(self.created['root'])
        password = (root / 'authority-password.txt').read_text().strip()
        key = load_private((root / 'authority/authority-key.pem').read_text(), password)
        prior = publication.verified(authority.policy, spki_der(key), 'policy')
        now = prior['expires'] + 1
        authority.clock = lambda: now
        request = browser.get('/api/maintenance/authority/request')['request']
        policy = publication.signed(key, 'policy',
            dict(prior, version=2, issued=now, expires=now + 90 * 86400))
        grant = dict(group_id=GROUP, origin=authority.origin, user_id='admin', role='administrator',
                     device_key=request['device_key'], issued=now, expires=now + 90 * 86400,
                     can_delegate=True)
        bundle = dict(user='admin', chain=[publication.signed(key, 'device', grant)],
                      policy=policy, root_pin=authority.public['root_sha256'], confirm=True)
        browser.post('/api/maintenance/authority', dict(bundle, confirm=False), status=400)
        browser.post('/api/maintenance/authority', dict(bundle, root_pin='0' * 64), status=403)
        browser.post('/api/maintenance/authority', bundle, status=202)
        with store.connection() as db:
            restored = authority.grant(db, 'admin')
            self.assertEqual(restored['row']['device_id'], request['device_id'])
        self.assertTrue(browser.post('/api/maintenance/authority', bundle, status=202)['recovered']['already_current'])

    def login(self, browser, user='admin', password=PASSWORD):
        result = browser.post('/api/login', {'user': user, 'password': password})
        self.assertEqual(result['authenticated'], True)
        return result

    def terminal_for(self, browser):
        return browser.get('/api/state')['terminal']

    def trust_terminal(self, admin, browser, user, groups):
        terminal = self.terminal_for(browser)
        result = admin.post('/api/terminal/approve',
                            {'name': 'Desk', 'users': [user], 'groups': groups,
                             'terminal': terminal})
        self.assertEqual(result['state'], 'approved')

    def test_membership_escalation_and_out_of_scope_administration_refused(self):
        admin = self.browser()
        self.login(admin)
        admin.post('/api/users', {'user': 'carol', 'password': PASSWORD, 'role': 'user'})
        admin.post('/api/teams', {'team': 'platform-admins', 'name': 'Platform'})
        admin.post('/api/grants', {'subject_type': 'team', 'subject': 'platform-admins',
                                   'bundle': 'system-administrator', 'groups': [GROUP]})
        admin.post('/api/grants', {'subject_type': 'user', 'subject': 'carol',
                                   'bundle': 'group-administrator', 'groups': [GROUP]})
        carol = self.browser()
        self.login(carol, 'carol')
        self.assertFalse(carol.get('/api/state')['trusted'])
        # Complete retained-terminal approval: request, one approval by code, poll.
        request = carol.post('/api/connection/start', {
            'kind': 'terminal', 'summary': 'carol desk', 'target_user': 'carol',
            'document': {'name': 'Carol desk', 'users': ['carol'], 'groups': [GROUP]}})
        self.assertEqual(admin.post('/api/connection/approve',
                                    {'code': request['code']})['state'], 'approved')
        self.assertEqual(carol.post('/api/connection/poll',
                                    {'code': request['code']})['state'], 'accepted')
        self.login(carol, 'carol')
        self.assertTrue(carol.get('/api/state')['trusted'])
        # The exact reported escalation is refused through the HTTP route.
        error = carol.post('/api/memberships', {'team': 'platform-admins',
                                               'user': 'carol'}, status=403)
        self.assertEqual(error['error'], 'delegation_exceeds_scope')
        self.assertNotIn('service.relocate', carol.get('/api/state')['permissions'])
        self.assertEqual(carol.post('/api/grants', {
            'subject_type': 'user', 'subject': 'carol', 'bundle': 'system-administrator',
            'groups': [GROUP]}, status=403)['error'], 'delegation_exceeds_scope')
        self.assertEqual(carol.post('/api/users', {
            'user': 'second-admin', 'password': PASSWORD, 'role': 'administrator'},
            status=403)['error'], 'delegation_exceeds_scope')
        self.assertEqual(carol.post('/api/users/block', {'user': 'admin'},
                                    status=403)['error'], 'delegation_exceeds_scope')
        # Legitimate delegated work in its own scope still succeeds.
        self.assertEqual(carol.post('/api/grants', {
            'subject_type': 'user', 'subject': 'carol', 'bundle': 'publisher',
            'groups': [GROUP]})['state'], 'assigned')
        self.assertEqual(carol.post('/api/users', {
            'user': 'assistant', 'password': PASSWORD, 'role': 'user'})['state'], 'created')

    def test_login_connection_requires_same_account_and_dies_with_rotated_parent(self):
        admin = self.browser()
        self.login(admin)
        admin.post('/api/users', {'user': 'alice', 'password': PASSWORD, 'role': 'user'})
        admin.post('/api/users', {'user': 'bob', 'password': PASSWORD, 'role': 'user'})
        alice = self.browser()
        self.login(alice, 'alice')
        self.trust_terminal(admin, alice, 'alice', [GROUP])
        self.login(alice, 'alice')
        self.assertTrue(alice.get('/api/state')['trusted'])
        other = self.browser()
        self.login(other, 'alice')
        request = other.post('/api/connection/start', {
            'kind': 'login', 'summary': 'second browser', 'requested_user': 'alice'})
        # Another account's session may not approve this request.
        bob = self.browser()
        self.login(bob, 'bob')
        self.trust_terminal(admin, bob, 'bob', [GROUP])
        self.login(bob, 'bob')
        self.assertTrue(bob.get('/api/state')['trusted'])
        self.assertEqual(bob.post('/api/connection/approve', {'code': request['code']},
                                  status=403)['error'], 'connection_user_mismatch')
        reviewed = alice.post('/api/connection/review', {'code': request['code']})
        self.assertEqual(reviewed['connection']['requested_user'], 'alice')
        self.assertEqual(alice.post('/api/connection/approve',
                                    {'code': request['code']})['state'], 'approved')
        accepted = other.post('/api/connection/poll', {'code': request['code']})
        self.assertEqual(accepted['state'], 'accepted')
        self.assertTrue(accepted['trusted'])
        self.assertTrue(other.get('/api/state')['authenticated'])
        alice.post('/api/rotate', {})
        alice.post('/api/logout', {})
        self.assertFalse(other.get('/api/state')['authenticated'])
        self.assertIn(other.get('/api/drafts', None, status=401)['error'],
                      {'session_required', 'session_ended', 'session_expired'})

    def test_device_request_enrolls_with_signed_scope(self):
        admin = self.browser()
        self.login(admin)
        admin.post('/api/users', {'user': 'bob', 'password': PASSWORD, 'role': 'user'})
        device = self.browser()
        self.login(device, 'bob')
        request = device.post('/api/connection/start', {
            'kind': 'device', 'summary': 'kiosk display bob', 'target_user': 'bob',
            'document': {'name': 'bob display', 'groups': [GROUP],
                         'targets': ['display-1'], 'permissions': ['publish']}})
        approved = admin.post('/api/connection/approve', {'code': request['code']})
        self.assertEqual(approved['state'], 'approved')
        self.assertEqual(approved['bundle']['scope']['targets'], ['display-1'])
        polled = device.post('/api/connection/poll', {'code': request['code']})
        self.assertEqual(polled['state'], 'approved')
        self.assertEqual(polled['result']['user'], 'bob')

    def test_suspend_switch_and_password_only_return(self):
        admin = self.browser()
        self.login(admin)
        admin.post('/api/users', {'user': 'alice', 'password': PASSWORD, 'role': 'user'})
        alice = self.browser()
        self.login(alice, 'alice')
        self.trust_terminal(admin, alice, 'alice', [GROUP])
        self.login(alice, 'alice')
        self.assertEqual(alice.post('/api/suspend', {})['state'], 'suspended')
        state = alice.get('/api/state')
        self.assertFalse(state['authenticated'])
        self.assertEqual([item['user_id'] for item in state['suspended']], ['alice'])
        # A wrong account cannot reopen the suspended administrator/workspace.
        self.assertEqual(alice.post('/api/resume', {'user': 'alice', 'password': 'nope-passphrase'},
                                    status=401)['error'], 'invalid_credentials')
        self.assertFalse(alice.get('/api/state')['authenticated'])
        resumed = alice.post('/api/resume', {'user': 'alice', 'password': PASSWORD})
        self.assertEqual(resumed['state'], 'active')
        state = alice.get('/api/state')
        self.assertTrue(state['authenticated'])
        self.assertEqual(state['state'], 'active')

    def test_lock_keeps_cookie_but_hides_privileged_work(self):
        admin = self.browser()
        self.login(admin)
        self.assertEqual(admin.post('/api/lock', {})['state'], 'locked')
        state = admin.get('/api/state')
        self.assertTrue(state['authenticated'])
        self.assertEqual(state['state'], 'locked')
        self.assertEqual(admin.get('/api/drafts', status=403)['error'], 'session_locked')
        self.assertEqual(admin.post('/api/resume', {'user': 'admin',
                                                    'password': PASSWORD})['state'], 'active')


class RelocationTests(unittest.TestCase):
    def test_export_import_activate_and_old_side_fenced(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        fixture = Fixture(Path(temp.name))
        source = fixture.store('source.sqlite')
        authority = fixture.authority(source)
        fixture.populate(source, authority)
        source.fence('acceptance', handoff=True)
        with self.assertRaises(RelocationError):
            export_maintenance(source, fixture.root / 'secrets', Path(temp.name) / 'bad.bundle',
                               'short')
        bundle = Path(temp.name) / 'transfer.bundle'
        exported = export_maintenance(source, fixture.root / 'secrets', bundle,
                                      'relocation-passphrase-2026')
        self.assertEqual(exported['counts']['users'], 1)
        with self.assertRaises(RelocationError):
            import_maintenance(bundle, fixture.store('wrong.sqlite'),
                               fixture.root / 'secrets', 'wrong-passphrase-2026',
                               node='n2', origin='https://127.0.0.1:26443')
        raw = bundle.read_bytes()
        corrupted = Path(temp.name) / 'corrupted.bundle'
        corrupted.write_bytes(raw[:-8] + b'00000000')
        with self.assertRaises(RelocationError):
            import_maintenance(corrupted, fixture.store('corrupt.sqlite'),
                               fixture.root / 'secrets', 'relocation-passphrase-2026',
                               node='n2', origin='https://127.0.0.1:26443')
        destination = fixture.store('destination.sqlite')
        imported = import_maintenance(bundle, destination, fixture.root / 'secrets',
                                      'relocation-passphrase-2026', node='n2',
                                      origin='https://127.0.0.1:26443')
        with destination.connection() as db:
            row = accounts.authenticate(db, 'admin', PASSWORD)
            self.assertIsNotNone(row)
            self.assertEqual(permissions.groups_for(db, 'admin'), {GROUP})
        # Activation is refused until the fenced source grants the single-use claim.
        with self.assertRaises(MaintenanceError) as caught:
            destination.activate(imported['generation'], imported['fence'],
                                 'https://127.0.0.1:26443', transfer=imported['transfer'])
        self.assertEqual(caught.exception.code, 'placement_transfer_unredeemed')
        # The source itself issues exactly one claim, and only for this destination.
        self.assertEqual(source.redeem_transfer(imported['transfer'], imported['cutover_secret'],
                                                'https://127.0.0.1:26443')['state'], 'claimed')
        with self.assertRaises(MaintenanceError) as caught:
            source.redeem_transfer(imported['transfer'], imported['cutover_secret'],
                                   'https://127.0.0.1:26444')
        self.assertEqual(caught.exception.code, 'cutover_already_claimed')
        destination.claim_transfer(imported['transfer'], 'https://127.0.0.1:26443')
        destination.activate(imported['generation'], imported['fence'],
                             'https://127.0.0.1:26443', transfer=imported['transfer'])
        self.assertFalse(destination.fenced())
        self.assertEqual(destination.placement()['generation'], 2)
        with self.assertRaises(MaintenanceError) as caught:
            destination.activate(imported['generation'], imported['fence'],
                                 'https://127.0.0.1:26443', transfer=imported['transfer'])
        self.assertEqual(caught.exception.code, 'placement_generation_conflict')
        # A second destination that imported the same bundle cannot win the claim.
        second = fixture.store('second.sqlite')
        second_import = import_maintenance(bundle, second, fixture.root / 'secrets',
                                           'relocation-passphrase-2026', node='n3',
                                           origin='https://127.0.0.1:26444')
        with self.assertRaises(MaintenanceError) as caught:
            source.redeem_transfer(second_import['transfer'],
                                   second_import['cutover_secret'],
                                   'https://127.0.0.1:26444')
        self.assertEqual(caught.exception.code, 'cutover_already_claimed')
        with self.assertRaises(MaintenanceError) as caught:
            second.activate(second_import['generation'], second_import['fence'],
                            'https://127.0.0.1:26444', transfer=second_import['transfer'])
        self.assertEqual(caught.exception.code, 'placement_transfer_unredeemed')
        # The old side has completed a handoff and can never be reactivated.
        with self.assertRaises(MaintenanceError) as caught:
            source.activate(imported['generation'], imported['fence'],
                            'https://127.0.0.1:26443', transfer=imported['transfer'])
        self.assertEqual(caught.exception.code, 'placement_handoff_complete')

    def test_content_workspace_fence_and_handoff(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        fixture = Fixture(Path(temp.name))
        workspace = Workspace(Path(temp.name) / 'workspace.sqlite',
                              base64.b64decode(fixture.public['root_spki']), GROUP, ORIGIN,
                              clock=lambda: CLOCK)
        workspace.install_policy(fixture.policy)
        workspace.configure_placement('combined', ORIGIN)
        fence = workspace.fence('move')
        self.assertTrue(workspace.fenced())
        workspace.activate(1, fence, ORIGIN)
        self.assertFalse(workspace.fenced())
        self.assertEqual(workspace.placement()['generation'], 2)

    def test_content_export_import_preserves_files(self):
        from kiosk.maintenance.relocation import export_content, import_content
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        source_root = Path(temp.name) / 'content'
        (source_root / 'delivery' / 'publications' / 'package-1').mkdir(parents=True)
        (source_root / 'delivery' / 'publications' / 'package-1' / 'delivery.json').write_text('{}')
        (source_root / 'delivery' / 'public.json').write_text('{}')
        fixture = Fixture(Path(temp.name) / 'fixture')
        workspace = Workspace(source_root / 'workspace.sqlite',
                              base64.b64decode(fixture.public['root_spki']), GROUP, ORIGIN,
                              clock=lambda: CLOCK)
        workspace.install_policy(fixture.policy)
        workspace.configure_placement('combined', ORIGIN)
        workspace.fence('move', handoff=True)
        bundle = Path(temp.name) / 'content.bundle'
        exported = export_content(workspace, source_root, bundle,
                                  'relocation-passphrase-2026')
        self.assertGreaterEqual(exported['files'], 3)
        destination = Path(temp.name) / 'destination'
        imported = import_content(bundle, destination, 'relocation-passphrase-2026',
                                  origin=ORIGIN, counterpart='https://127.0.0.1:25443',
                                  root_spki=base64.b64decode(fixture.public['root_spki']),
                                  group_id=GROUP)
        self.assertEqual(imported['history'], 0)
        self.assertTrue((destination / 'delivery' / 'publications' / 'package-1' /
                         'delivery.json').exists())
        moved = Workspace(destination / 'workspace.sqlite',
                          base64.b64decode(fixture.public['root_spki']), GROUP, ORIGIN,
                          clock=lambda: CLOCK)
        moved.activate(imported['generation'], imported['fence'], ORIGIN)
        self.assertFalse(moved.fenced())
        with self.assertRaises(WorkspaceError) as caught:
            workspace.activate(imported['generation'], imported['fence'], ORIGIN)
        self.assertEqual(caught.exception.code, 'placement_handoff_complete')


class RuntimePlacementTests(unittest.TestCase):
    def test_caddy_edge_accepts_a_literal_lan_address(self):
        from kiosk.maintenance.serve import caddyfile
        text = caddyfile('https://192.168.1.125:29443', 'cert.pem', 'key.pem', 5000, 'store')
        self.assertIn('https://192.168.1.125:29443 {', text)
        self.assertIn('bind 192.168.1.125', text)
        self.assertIn('reverse_proxy 127.0.0.1:5000', text)
        with self.assertRaises(Exception) as caught:
            caddyfile('https://kiosk.example:29443', 'cert.pem', 'key.pem', 5000, 'store')
        self.assertEqual(getattr(caught.exception, 'args', ('',))[0], 'origin_host_refused')
        with self.assertRaises(Exception):
            caddyfile('https://0.0.0.0:29443', 'cert.pem', 'key.pem', 5000, 'store')

    def test_stage_remote_writes_destination_config_and_own_leaf(self):
        from types import SimpleNamespace
        from kiosk.maintenance.host import stage_remote
        from kiosk.trust.crypto import issue_intermediate_ca, issue_root_ca
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        source = Path(temp.name) / 'source'
        destination = Path(temp.name) / 'destination'
        root_ca, root_key = issue_root_ca('stage test root', validity_days=30)
        issuer, issuer_key = issue_intermediate_ca('stage test issuer', root_ca, root_key,
                                                   validity_days=30)
        ca_dir = source / 'work' / 'lab' / 'ca'
        ca_dir.mkdir(parents=True)
        (ca_dir / 'issuer.pem').write_text(issuer)
        (ca_dir / 'issuer-key.pem').write_text(issuer_key)
        (source / 'public').mkdir()
        (source / 'public' / 'root-ca.pem').write_text(root_ca)
        (source / 'public' / 'publisher-public.json').write_text('{}')
        (source / 'public' / 'publisher-policy.json').write_text('{}')
        (source / 'public' / 'bootstrap.json').write_text('{}')
        (source / 'maintenance' / 'config').mkdir(parents=True)
        (source / 'maintenance' / 'config' / 'maintenance.json').write_text(json.dumps(dict(
            SECRET_KEY='source-secret', CONTENT_SERVICE_ID='service-id',
            CONTENT_SERVICE_SECRET='service-secret')))
        (source / 'install.json').write_text(json.dumps(dict(
            group_id=GROUP, admin='admin', content_origin='https://192.168.1.124:28443',
            content_identity='LocalService', maintenance_identity='NetworkService',
            content_service='KioskContentReloc', maintenance_service='KioskMaintReloc')))
        result = stage_remote(SimpleNamespace(
            root=str(source), destination_root=str(destination),
            maintenance_origin='https://192.168.1.125:29443', content_origin=None,
            dest_node='n2', destination_id='pc5-n2'))
        self.assertEqual(result['origin'], 'https://192.168.1.125:29443')
        self.assertFalse(result['executable_present'])
        config = json.loads((destination / 'maintenance' / 'config' /
                             'maintenance.json').read_text())
        self.assertEqual(config['MAINTENANCE_PLACEMENT']['mode'], 'separated')
        self.assertEqual(config['MAINTENANCE_PLACEMENT']['counterpart'],
                         'https://192.168.1.124:28443')
        self.assertEqual(config['CONTENT_SERVICE_SECRET'], 'service-secret')
        self.assertNotEqual(config['SECRET_KEY'], 'source-secret')
        record = json.loads((destination / 'install.json').read_text())
        self.assertEqual(record['node'], 'n2')
        self.assertEqual(record['destination_id'], 'pc5-n2')
        with self.assertRaises(Exception):
            stage_remote(SimpleNamespace(
                root=str(source), destination_root=str(destination),
                maintenance_origin='https://kiosk.example:29443', content_origin=None,
                dest_node='n2', destination_id='pc5-n2'))


class SchemaTests(unittest.TestCase):
    def test_legacy_connection_kind_table_is_migrated(self):
        import sqlite3
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        path = Path(temp.name) / 'maintenance.sqlite'
        legacy = sqlite3.connect(path)
        legacy.executescript('''
        CREATE TABLE connections (
            id TEXT PRIMARY KEY,
            kind TEXT NOT NULL CHECK(kind IN ('login','enroll')),
            code TEXT NOT NULL, browser TEXT NOT NULL, terminal_id TEXT NOT NULL,
            requested_user TEXT NOT NULL DEFAULT '', target_user TEXT NOT NULL DEFAULT '',
            summary TEXT NOT NULL, origin TEXT NOT NULL, issued INTEGER NOT NULL,
            expires INTEGER NOT NULL, approved INTEGER NOT NULL DEFAULT 0, approved_by TEXT,
            consumed INTEGER NOT NULL DEFAULT 0, attempts INTEGER NOT NULL DEFAULT 0,
            document BLOB NOT NULL);
        INSERT INTO connections VALUES ('legacy-1','enroll','ABCDEFGH','b','t','','u','s',
            'https://127.0.0.1:25443',1,2,0,NULL,0,0,X'7b7d');
        ''')
        legacy.commit()
        legacy.close()
        store = MaintenanceStore(path, clock=lambda: CLOCK)
        with store.connection() as db:
            row = db.execute('SELECT kind FROM connections WHERE id=?',
                             ('legacy-1',)).fetchone()
            self.assertEqual(row['kind'], 'device')
            identity, record = sessions.create_connection(
                store, db, 'terminal', 'a' * 32, 'c' * 64, 'shared desk',
                target_user='admin', document={'name': 'Desk', 'users': ['admin'],
                                               'groups': [GROUP]})
            self.assertTrue(identity)
            identity, record = sessions.create_connection(
                store, db, 'device', 'a' * 32, 'c' * 64, 'display',
                target_user='admin', document={'name': 'Display', 'groups': [GROUP],
                                               'targets': ['d1']})
            self.assertTrue(identity)
            self.assertEqual(record['kind'], 'device')
            # The terminal approval path records the account, not the session id.
            sessions.register_terminal(db, 'a' * 32, 'Desk')
            accounts.create_user(db, 'approver', PASSWORD, 'administrator', now=CLOCK)
            db.execute("INSERT INTO grants (subject_type,subject_id,bundle,groups,created_by,"
                       "created) VALUES ('user','approver','system-administrator',?,"
                       "'approver',?)", (json.dumps([GROUP]), CLOCK))
            secret, created = sessions.start_password_session(
                store, db, 'approver', PASSWORD, 'e' * 32)
            sessions.approve_terminal(db, 'approver', 'a' * 32, 'Desk', ['approver'], [GROUP],
                                      now=CLOCK)
        self.assertTrue(created['trusted'])

    def test_review_strings_are_bounded_and_plain(self):
        from kiosk.maintenance import review
        self.assertEqual(review._strings(None, 8, 2), [])
        self.assertEqual(review._strings(['a', 'b'], 8, 2), ['a', 'b'])
        with self.assertRaises(MaintenanceError):
            review._strings(['a', 'b', 'c'], 8, 2)
        with self.assertRaises(MaintenanceError):
            review._strings('<b>x</b>' * 3, 4, 2)
        with self.assertRaises(MaintenanceError):
            review._settings({'site_title': 'x' * 1000})


class CycleTests(unittest.TestCase):
    def test_authority_deadline_survives_calendar_acknowledgement(self):
        from kiosk.trust.crypto import issue_root_ca, issue_intermediate_ca, issue_tls_leaf
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        root = Path(temp.name)
        fixture = Fixture(root)
        store = fixture.store()
        store.configure_schedule(CLOCK, 90)
        ca, ca_key = issue_root_ca('root', validity_days=365, now=CLOCK)
        issuer, issuer_key = issue_intermediate_ca('issuer', ca, ca_key,
                                                   validity_days=120, now=CLOCK)
        leaf, _ = issue_tls_leaf('maintenance', issuer, issuer_key,
                                 san_ips=['127.0.0.1'], san_dns=[],
                                 validity_days=7, now=CLOCK)
        (root / 'chain.pem').write_text(leaf + issuer)
        (root / 'ca.pem').write_text(ca)
        settings = dict(TLS=dict(cert=str(root / 'chain.pem'), ca=str(root / 'ca.pem')),
                        MAINTENANCE_ROOT_PUBLIC=str(root / 'authority/public.json'),
                        MAINTENANCE_ROOT_POLICY=str(root / 'authority/policy.json'))
        before = cycle.authority_status(store, settings, CLOCK + 6 * 86400)
        cycle.record(store, CLOCK + 6 * 86400)
        after = cycle.authority_status(store, settings, CLOCK + 6 * 86400)
        self.assertEqual(before['effective_due'], CLOCK + 7 * 86400)
        self.assertEqual(after['effective_due'], before['effective_due'])
        self.assertEqual(len(after['deadlines']), 4)
        self.assertEqual(after['deadlines'][0]['state'], 'warning')
        self.assertFalse(after['unattended_interval_proven'])
        expired = cycle.authority_status(store, settings, CLOCK + 105 * 86400)
        self.assertEqual(next(x for x in expired['deadlines']
                              if x['name'] == 'publisher_policy')['state'], 'expired')
        # Signature failure cannot turn an untrusted expiry into a green result.
        (root / 'authority/policy.json').write_text('{}')
        damaged = cycle.authority_status(store, settings, CLOCK)
        self.assertIn('publisher_policy', damaged['unavailable'])
        self.assertNotIn('publisher_policy', [x['name'] for x in damaged['deadlines']])

    def test_missing_inputs_are_unknown_and_paths_are_not_disclosed(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        store = MaintenanceStore(Path(temp.name) / 'maintenance.sqlite', clock=lambda: CLOCK)
        store.configure_schedule(CLOCK, 90)
        result = cycle.authority_status(store, {}, CLOCK)
        self.assertEqual(result['unavailable'], ['maintenance_tls', 'tls_root', 'publisher_policy'])
        self.assertFalse(result['unattended_interval_proven'])
        self.assertIn('group_trust', result['unobserved'])
        self.assertNotIn(temp.name, json.dumps(result))

    def test_ninety_day_warnings_and_recovery_generation(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        store = MaintenanceStore(Path(temp.name) / 'maintenance.sqlite', clock=lambda: CLOCK)
        store.configure_schedule(CLOCK, 90)
        self.assertEqual(cycle.status(store, CLOCK)['state'], 'scheduled')
        self.assertEqual(cycle.status(store, CLOCK + 90 * 86400)['state'], 'due')
        warned = cycle.status(store, CLOCK + 90 * 86400 - 7 * 86400)
        self.assertTrue(any(item['days'] == 7 for item in warned['warnings']))
        cycle.record(store, CLOCK)
        self.assertEqual(cycle.status(store, CLOCK)['last_maintenance'], CLOCK)
        mark = cycle.mark_recovery(store, 'required', {'reason': 'restart'}, generation=1)
        self.assertEqual(mark['generation'], 1)
        with self.assertRaises(MaintenanceError):
            cycle.mark_recovery(store, 'none', {}, generation=0)


if __name__ == '__main__':
    unittest.main()
