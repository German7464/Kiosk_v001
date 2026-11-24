import base64
import hashlib
import hmac
import ipaddress
import json
import secrets
import tempfile
import unittest
from pathlib import Path

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.x509.oid import NameOID

from kiosk.maintenance.store import MaintenanceError, MaintenanceStore
from kiosk.maintenance.tls import PATH, SERVICE_ID, TLSAuthority, provision
from kiosk.trust.crypto import generate_private_key, spki_der
from kiosk.trust.roles import delegation_payload
from kiosk.trust.state import LifecycleError
from tests.test_trust_lifecycle import _Crypto


class InstalledIssuerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.crypto = _Crypto()
        cls.key = generate_private_key()

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        root = Path(self.temp.name)
        self.now = self.crypto.base
        self.store = MaintenanceStore(root / 'maintenance.sqlite', clock=lambda: self.now)
        self.store.configure_placement('combined', 'maintenance', 'n1', 'https://192.168.1.166:29443')
        self.secret = secrets.token_hex(32)
        delegate = dict(payload=json.loads(delegation_payload(self.crypto.delegation)),
                        signature=base64.b64encode(self.crypto.delegation_sig).decode())
        config = dict(issuer_certificate=self.crypto.intermediate_pem,
                      client_secret=self.secret, delegations=dict(content=delegate))
        provision(self.store, root / 'secrets', self.crypto.intermediate_key_pem, config)
        self.authority = TLSAuthority(self.store, root / 'secrets',
                                      base64.b64encode(self.crypto.root_spki).decode())

    def csr(self, ip='192.168.1.165'):
        return (x509.CertificateSigningRequestBuilder()
                .subject_name(x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, 'untrusted subject')]))
                .add_extension(x509.SubjectAlternativeName([x509.IPAddress(ipaddress.ip_address(ip)),
                                                          x509.DNSName('localhost')]), critical=False)
                .sign(self.key, hashes.SHA256()).public_bytes(serialization.Encoding.PEM).decode())

    def headers(self, raw=b'{}', path=PATH):
        nonce, stamp = secrets.token_hex(32), str(self.now)
        digest = hashlib.sha256(raw).hexdigest()
        message = '\n'.join((SERVICE_ID, 'POST', path, stamp, nonce, digest)).encode()
        return {'X-Kiosk-Service-Id': SERVICE_ID, 'X-Kiosk-Time': stamp,
                'X-Kiosk-Nonce': nonce, 'X-Kiosk-Body-SHA256': digest,
                'X-Kiosk-Signature': hmac.new(self.secret.encode(), message, hashlib.sha256).hexdigest()}

    def test_server_local_key_is_certified_and_no_private_key_transferred(self):
        result = self.authority.issue('content', self.csr())
        cert = x509.load_pem_x509_certificate(result['chain_pem'].encode())
        self.assertEqual(spki_der(cert.public_key()), spki_der(self.key))
        self.assertNotIn('PRIVATE KEY', json.dumps(result))
        self.assertNotIn('leaf_key_pem', result)
        self.assertEqual(cert.subject.rfc4514_string(), 'CN=lab-server')
        self.assertEqual(result['not_after'], self.now + 7 * 86400)
        with self.assertRaises(MaintenanceError) as throttled:
            self.authority.issue('content', self.csr())
        self.assertEqual(throttled.exception.status, 429)

    def test_cross_origin_csr_fenced_authority_and_expiry_are_refused(self):
        with self.assertRaises(ValueError):
            self.authority.issue('content', self.csr('192.168.1.166'))
        self.store.fence('test', handoff=True)
        with self.assertRaises(MaintenanceError):
            self.authority.issue('content', self.csr())

    def test_mac_body_path_replay_and_persistent_clock_floor(self):
        headers = self.headers()
        self.authority.authenticate(headers, b'{}', 'POST', PATH)
        with self.assertRaises(MaintenanceError):
            self.authority.authenticate(headers, b'{}', 'POST', PATH)
        with self.assertRaises(MaintenanceError):
            self.authority.authenticate(self.headers(), b'{"changed":true}', 'POST', PATH)
        with self.assertRaises(MaintenanceError):
            self.authority.authenticate(self.headers(path='/api/maintenance/authority'), b'{}', 'POST', '/api/maintenance/authority')
        restarted = TLSAuthority(self.store, Path(self.temp.name) / 'secrets',
                                  base64.b64encode(self.crypto.root_spki).decode())
        self.now -= 1
        with self.assertRaises(LifecycleError):
            restarted.authenticate(self.headers(), b'{}', 'POST', PATH)

    def test_encrypted_fenced_transfer_rewraps_issuer_and_preserves_floor(self):
        from kiosk.maintenance.relocation import export_maintenance, import_maintenance
        from kiosk.maintenance import keystore
        result = self.authority.issue('content', self.csr())
        with self.store.connection() as db:
            self.authority.state.advance_floor(db, self.now)
        self.store.fence('move', handoff=True)
        root = Path(self.temp.name)
        bundle = root / 'issuer.bundle'
        exported = export_maintenance(self.store, root / 'secrets', bundle, 'test-transfer-password')
        self.assertNotIn(b'PRIVATE KEY', bundle.read_bytes())
        destination = MaintenanceStore(root / 'destination.sqlite', clock=lambda: self.now)
        imported = import_maintenance(bundle, destination, root / 'destination-secrets',
            'test-transfer-password', node='destination', origin='https://192.168.1.166:29443')
        target = TLSAuthority(destination, root / 'destination-secrets',
                              base64.b64encode(self.crypto.root_spki).decode())
        self.assertEqual(target.state.time_floor(), self.now)
        self.assertEqual(target.state.current_tls()['spki_sha256'], result['tls_spki_sha256'])
        with self.assertRaises(MaintenanceError):
            target.issue('content', self.csr())
        self.store.redeem_transfer(imported['transfer'], imported['cutover_secret'], 'https://192.168.1.166:29443')
        destination.claim_transfer(imported['transfer'], 'https://192.168.1.166:29443')
        destination.activate(imported['generation'], imported['fence'],
                             'https://192.168.1.166:29443', transfer=imported['transfer'])
        self.now += 31
        renewed = target.issue('content', self.csr())
        self.assertGreater(renewed['generation'], result['generation'])
        with self.assertRaises(MaintenanceError):
            self.authority.issue('content', self.csr())
