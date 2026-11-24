"""LAN-only constrained TLS signer on the trusted Maintenance side.

Content sends a PKCS#10 request, never a private key. Its distinct service secret
permits only its configured origin; it cannot request the Maintenance leaf. The
offline group root signs both bounded delegations. Root keys are never loaded by
this runtime. The existing issuer, DPAPI custody and persistent lifecycle floor
are reused, with state in the fenced/transferred Maintenance database.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import threading
from pathlib import Path
from urllib.parse import urlsplit

from kiosk.delivery.protocol import decode, encode, fields
from kiosk.trust.crypto import load_private, private_pem, spki_der, key_id
from kiosk.trust.lifecycle import OnlineIssuer, delegation_from_payload, verify_group_window
from kiosk.trust.state import LifecycleState
from . import keystore
from .store import MaintenanceError

SERVICE_ID = 'kiosk-content-tls-v1'
PATH = '/api/tls/renew'


def provision(store, secrets_dir, key_pem, configuration):
    """Setup only, under the installation administrator's identity."""
    key = load_private(key_pem)
    protected = keystore.protect(private_pem(key).encode('ascii'), secrets_dir)
    with store.connection() as db:
        if db.execute('SELECT 1 FROM tls_issuer').fetchone():
            raise MaintenanceError('tls_issuer_exists', 409)
        db.execute('INSERT INTO tls_issuer VALUES (1,?,?)', (protected, encode(configuration)))
    LifecycleState(store.path.parent, database=store.path)


class TLSAuthority:
    def __init__(self, store, secrets_dir, root_spki, *, maintenance_origin=None, maintenance_override=None):
        self.store, self.secrets_dir = store, secrets_dir
        self.root_spki = base64.b64decode(root_spki, validate=True)
        self.state = LifecycleState(store.path.parent, database=store.path)
        self.issue_lock = threading.Lock()
        self.maintenance_origin = maintenance_origin
        self.maintenance_override = maintenance_override

    def public_configuration(self, config):
        """Use the verified destination delegation in exported recovery context."""
        from kiosk.trust.roles import verify_delegation
        delegated = config['delegations']['maintenance']
        if self.maintenance_override and delegated['payload']['origin'] != self.maintenance_origin:
            replacement = decode(Path(self.maintenance_override).read_bytes())
            fields(replacement, 'payload signature')
            old, new = delegated['payload'], replacement['payload']
            unchanged = ('group_id', 'server_id', 'issuer_key_id', 'issuer_spki_base64',
                         'scopes', 'max_tls_validity_days', 'issued_at', 'expires_at', 'version')
            if (any(new[name] != old[name] for name in unchanged)
                    or new['origin'] != self.maintenance_origin or new['permitted_dns'] != []
                    or new['permitted_ip'] != [urlsplit(self.maintenance_origin).hostname]):
                raise MaintenanceError('tls_relocation_scope_refused', 403)
            verify_delegation(self.root_spki, delegation_from_payload(new),
                              base64.b64decode(replacement['signature'], validate=True))
            config = dict(config, delegations=dict(config['delegations'], maintenance=replacement))
        return config

    def current_group(self):
        with self.store.connection(write=False) as db:
            row = db.execute('SELECT configuration FROM tls_issuer WHERE singleton=1').fetchone()
        if row is None:
            raise MaintenanceError('tls_issuer_unconfigured', 503)
        config = decode(bytes(row['configuration']))
        value = verify_group_window(config['group_trust'], self.root_spki)
        target = config['delegations']['content']['payload']
        if (value['group_id'] != target['group_id'] or value['servers'] != [dict(
                server_id=target['server_id'], origin=target['origin'],
                tls_issuer_spki_sha256=target['issuer_key_id'], roles=['publisher'])]):
            raise MaintenanceError('lan_authority_scope_refused', 403)
        return value

    def require_current(self):
        value = self.current_group()
        if not value['issued_at'] <= self.store.now() < value['expires_at']:
            raise MaintenanceError('lan_authority_expired', 403)

    def recovery_configuration(self, db, bundle, ca_file):
        """Validate public same-key renewal; caller commits with the reviewer grant.

        Offline signatures, not the browser password, extend group/delegation
        authority. The online issuer key, roots, target identities and client MAC
        remain unchanged. Exact retries are idempotent; conflicts fail closed.
        """
        from cryptography import x509
        from cryptography.hazmat.primitives import serialization
        from cryptography.hazmat.primitives.asymmetric import rsa
        from kiosk.trust.roles import verify_delegation
        fields(bundle, 'issuer_certificate group_trust delegations')
        fields(bundle['delegations'], 'content maintenance')
        row = db.execute('SELECT configuration FROM tls_issuer WHERE singleton=1').fetchone()
        if row is None:
            raise MaintenanceError('tls_issuer_unconfigured', 503)
        old = decode(bytes(row['configuration']))
        replacement = dict(old, **bundle)
        if encode(replacement) == encode(old):
            self.require_group_value_current(bundle['group_trust'])
            return replacement
        now = self.store.now()
        trust = verify_group_window(bundle['group_trust'], self.root_spki)
        previous = verify_group_window(old['group_trust'], self.root_spki)
        if (trust['generation'] <= previous['generation'] or trust['group_id'] != previous['group_id']
                or trust['servers'] != previous['servers']
                or not trust['issued_at'] <= now < trust['expires_at']
                or trust['expires_at'] < now + 97 * 86400):
            raise MaintenanceError('lan_recovery_window_refused', 409)
        proposed = bundle['issuer_certificate']
        if not isinstance(proposed, str) or len(proposed) > 16384:
            raise MaintenanceError('issuer_certificate_refused', 403)
        certificate = x509.load_pem_x509_certificate(proposed.encode('ascii'))
        if proposed.strip().encode('ascii') + b'\n' != certificate.public_bytes(serialization.Encoding.PEM):
            raise MaintenanceError('issuer_certificate_refused', 403)
        original = x509.load_pem_x509_certificate(old['issuer_certificate'].encode('ascii'))
        root = x509.load_pem_x509_certificate(Path(ca_file).read_bytes())
        if not isinstance(root.public_key(), rsa.RSAPublicKey):
            raise MaintenanceError('issuer_certificate_refused', 403)
        from cryptography.exceptions import InvalidSignature
        try:
            root.public_key().verify(certificate.signature, certificate.tbs_certificate_bytes,
                                     certificate.signature_algorithm_parameters, certificate.signature_hash_algorithm)
        except InvalidSignature:
            raise MaintenanceError('issuer_certificate_refused', 403) from None
        constraints = certificate.extensions.get_extension_for_class(x509.BasicConstraints).value
        usage = certificate.extensions.get_extension_for_class(x509.KeyUsage).value
        expires = int(certificate.not_valid_after_utc.timestamp())
        if (spki_der(certificate.public_key()) != spki_der(original.public_key())
                or certificate.issuer != root.subject or certificate.subject != original.subject
                or not constraints.ca or constraints.path_length != 0 or not usage.key_cert_sign
                or not int(certificate.not_valid_before_utc.timestamp()) <= now < expires
                or not int(root.not_valid_before_utc.timestamp()) <= now < int(root.not_valid_after_utc.timestamp())
                or expires > min(int(root.not_valid_after_utc.timestamp()), now + 180 * 86400)):
            raise MaintenanceError('issuer_certificate_refused', 403)
        for side in ('content', 'maintenance'):
            delegated = bundle['delegations'][side]
            fields(delegated, 'payload signature')
            item = delegation_from_payload(delegated['payload'])
            verify_delegation(self.root_spki, item, base64.b64decode(delegated['signature'], validate=True))
            prior = old['delegations'][side]['payload']
            origin = self.maintenance_origin if side == 'maintenance' and self.maintenance_origin else prior['origin']
            if (item.group_id != prior['group_id'] or item.server_id != prior['server_id']
                    or item.origin != origin or item.permitted_ip != (urlsplit(origin).hostname,)
                    or item.permitted_dns or item.issuer_key_id != key_id(certificate.public_key())
                    or item.issuer_spki_base64 != prior['issuer_spki_base64']
                    or item.scopes != ('issue_tls_leaf',) or item.max_tls_validity_days != 7
                    or not item.issued_at <= now < item.expires_at
                    or item.expires_at - item.issued_at > 111 * 86400
                    or not trust['expires_at'] + 7 * 86400 <= item.expires_at <= expires):
                raise MaintenanceError('lan_recovery_delegation_refused', 403)
        return replacement

    def require_group_value_current(self, envelope):
        value = verify_group_window(envelope, self.root_spki)
        if not value['issued_at'] <= self.store.now() < value['expires_at']:
            raise MaintenanceError('lan_authority_expired', 403)
        return value

    def authenticate(self, headers, raw, method, path):
        """Dedicated domain/credential, exact body/path, bounded single-use nonce."""
        with self.store.connection(write=False) as db:
            row = db.execute('SELECT configuration FROM tls_issuer WHERE singleton=1').fetchone()
        if row is None:
            raise MaintenanceError('tls_issuer_unconfigured', 503)
        config = decode(bytes(row['configuration']))
        identity = headers.get('X-Kiosk-Service-Id', '')
        stamp = headers.get('X-Kiosk-Time', '')
        nonce = headers.get('X-Kiosk-Nonce', '')
        digest = headers.get('X-Kiosk-Body-SHA256', '')
        now = self.store.now()
        if (method != 'POST' or path != PATH or identity != SERVICE_ID
                or not stamp.isascii() or not stamp.isdecimal()
                or abs(now - int(stamp)) > 60 or len(nonce) != 64
                or any(c not in '0123456789abcdef' for c in nonce)
                or not hmac.compare_digest(hashlib.sha256(raw).hexdigest(), digest)):
            raise MaintenanceError('tls_service_refused', 403)
        message = '\n'.join((identity, method, path, stamp, nonce, digest)).encode()
        expected = hmac.new(config['client_secret'].encode(), message, hashlib.sha256).hexdigest()
        if not hmac.compare_digest(expected, headers.get('X-Kiosk-Signature', '')):
            raise MaintenanceError('tls_service_refused', 403)
        with self.store.connection() as db:
            self.state.checked_now(db, now)
            db.execute("DELETE FROM nonces WHERE value LIKE 'tls:%' AND seen<?", (now - 120,))
            value = 'tls:' + nonce
            if db.execute('SELECT 1 FROM nonces WHERE value=?', (value,)).fetchone():
                raise MaintenanceError('tls_service_replayed', 409)
            db.execute('INSERT INTO nonces VALUES (?,?)', (value, now))
            self.state.advance_floor(db, now)

    def issue(self, side, csr):
        with self.issue_lock:
            return self._issue(side, csr)

    def _issue(self, side, csr):
        if side not in ('content', 'maintenance'):
            raise MaintenanceError('tls_target_refused', 403)
        if self.store.placement() is None or self.store.fenced():
            raise MaintenanceError('service_fenced', 409)
        with self.store.connection(write=False) as db:
            row = db.execute('SELECT * FROM tls_issuer WHERE singleton=1').fetchone()
            last = db.execute('SELECT value FROM meta WHERE key=?', ('tls_last_' + side,)).fetchone()
        if last is not None and self.store.now() - last['value'] < 30:
            raise MaintenanceError('tls_renewal_throttled', 429)
        if row is None:
            raise MaintenanceError('tls_issuer_unconfigured', 503)
        config = decode(bytes(row['configuration']))
        delegated = config['delegations'][side]
        if (side == 'maintenance' and self.maintenance_override
                and delegated['payload']['origin'] != self.maintenance_origin):
            with Path(self.maintenance_override).open('rb') as stream:
                replacement = decode(stream.read(32769))
            old, new = delegated['payload'], replacement['payload']
            unchanged = ('group_id', 'server_id', 'issuer_key_id', 'issuer_spki_base64',
                         'scopes', 'max_tls_validity_days', 'issued_at', 'expires_at', 'version')
            if (any(new[name] != old[name] for name in unchanged)
                    or new['origin'] != self.maintenance_origin or new['permitted_dns'] != []
                    or new['permitted_ip'] != [urlsplit(self.maintenance_origin).hostname]):
                raise MaintenanceError('tls_relocation_scope_refused', 403)
            delegated = replacement
        if side == 'maintenance' and self.maintenance_origin and delegated['payload']['origin'] != self.maintenance_origin:
            raise MaintenanceError('tls_relocation_delegation_required', 503)
        issuer = OnlineIssuer(self.state, self.root_spki,
                              delegation_from_payload(delegated['payload']),
                              base64.b64decode(delegated['signature'], validate=True))
        # Only this trusted side can decrypt the issuer. Serving keys remain on
        # their own hosts; a CSR's requested subject is never copied into a leaf.
        key_pem = keystore.protect(bytes(row['protected']), self.secrets_dir, decrypt=True).decode('ascii')
        result = issuer.renew_tls_leaf(config['issuer_certificate'], key_pem,
                                      validity_days=7, now=self.store.now(), csr_pem=csr)
        if result['leaf_key_pem'] is not None:
            raise MaintenanceError('tls_private_key_transport_refused', 503)
        with self.store.connection() as db:
            db.execute('INSERT INTO meta(key,value) VALUES (?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value',
                       ('tls_last_' + side, self.store.now()))
        return {name: result[name] for name in ('generation', 'chain_pem',
                                               'tls_spki_sha256', 'not_before', 'not_after')}
