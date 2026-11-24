"""Installed-service TLS renewal: local CSR key, strict activation, durable pointer.

Uses the already pinned Caddy and admin-off supervision model. No ACME Internet,
trust-store write, root key, clock override or new service is introduced.
"""
from __future__ import annotations

import hashlib
import ipaddress
import json
import re
import socket
import ssl
import threading
import time
from pathlib import Path
from urllib.parse import urlsplit

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.x509.oid import NameOID

from kiosk.delivery.protocol import decode, encode
from kiosk.publication.store import _atomic_write
from kiosk.trust.crypto import generate_private_key, private_pem, spki_der
from .content import ContentClient
from .tls import PATH, SERVICE_ID

RENEW_BEFORE = 2 * 86400


def expiry(path):
    return int(x509.load_pem_x509_certificate(Path(path).read_bytes()).not_valid_after_utc.timestamp())


def verify_serving(origin, ca, expected, timeout=10):
    target = urlsplit(origin)
    context = ssl.create_default_context(cafile=str(ca))
    context.minimum_version = ssl.TLSVersion.TLSv1_2
    deadline = time.monotonic() + timeout
    while True:
        try:
            with socket.create_connection((target.hostname, target.port), timeout=2) as raw:
                with context.wrap_socket(raw, server_hostname=target.hostname) as tls:
                    cert = x509.load_der_x509_certificate(tls.getpeercert(binary_form=True))
                    if hashlib.sha256(spki_der(cert.public_key())).hexdigest() != expected:
                        raise ValueError('serving_identity_mismatch')
                    return
        except (OSError, ValueError):
            if time.monotonic() >= deadline:
                raise ValueError('strict_tls_activation_failed') from None
            time.sleep(.1)


class TLSRuntime:
    def __init__(self, runtime, app):
        self.runtime, self.app = runtime, app
        self.root = Path(runtime.tls['cert']).parent
        self.pointer = self.root / 'active.json'
        self.status_path = self.root / 'renewal-status.json'
        self.pending = None
        self.thread = None
        self.status = dict(state='starting', next_expiry=None)
        self.base = dict(runtime.tls)
        if self.pointer.exists():
            record = json.loads(self.pointer.read_text())
            slot = record.get('slot', '')
            if not re.fullmatch('[a-f0-9]{64}', slot):
                raise ValueError('tls_pointer_refused')
            folder = self.root / slot
            if folder.is_symlink():
                raise ValueError('tls_pointer_refused')
            runtime.tls = dict(self.base, cert=str(folder / 'chain.pem'), key=str(folder / 'key.pem'))
        app.extensions['tls_runtime'] = self

    def candidate(self):
        runtime = self.runtime
        key = generate_private_key()
        host = urlsplit(runtime.origin).hostname
        try:
            name = x509.IPAddress(ipaddress.ip_address(host))
        except ValueError:
            name = x509.DNSName(host)
        csr = (x509.CertificateSigningRequestBuilder()
               .subject_name(x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, 'Kiosk serving key')]))
               .add_extension(x509.SubjectAlternativeName([name]), critical=False)
               .sign(key, hashes.SHA256()).public_bytes(serialization.Encoding.PEM).decode())
        if runtime.side == 'maintenance':
            result = self.app.extensions['maintenance_tls_authority'].issue('maintenance', csr)
        else:
            config = runtime.value['TLS_RENEWAL']
            from .tls_binding import current_origin
            origin = current_origin(self.app, config['authority_origin'])
            client = ContentClient(origin, runtime.tls['ca'],
                                   SERVICE_ID, config['secret'], timeout=10)
            result = client._request('POST', PATH, dict(csr=csr))
        certificates = x509.load_pem_x509_certificates(result['chain_pem'].encode('ascii'))
        if (len(certificates) != 2 or hashlib.sha256(spki_der(certificates[1].public_key())).hexdigest()
                != runtime.value['TLS_RENEWAL']['issuer_spki_sha256']):
            raise ValueError('renewed_tls_issuer_refused')
        cert = certificates[0]
        now = int(time.time())
        if (spki_der(cert.public_key()) != spki_der(key)
                or not int(cert.not_valid_before_utc.timestamp()) <= now < int(cert.not_valid_after_utc.timestamp())
                or int(cert.not_valid_after_utc.timestamp()) > now + 7 * 86400 + 5):
            raise ValueError('renewed_tls_key_or_validity_refused')
        slot = hashlib.sha256(spki_der(key)).hexdigest()
        folder = self.root / slot
        folder.mkdir(exist_ok=False)
        _atomic_write(folder / 'chain.pem', result['chain_pem'].encode('ascii'))
        _atomic_write(folder / 'key.pem', private_pem(key).encode('ascii'))
        return dict(slot=slot, generation=result['generation'],
                    not_after=int(cert.not_valid_after_utc.timestamp()), spki=slot)

    def select(self, record):
        folder = self.root / record['slot']
        return dict(self.base, cert=str(folder / 'chain.pem'), key=str(folder / 'key.pem'))

    def prepare_start(self):
        # Maintenance can renew its own expired leaf without depending on the
        # old HTTPS edge. Content reaches only the authenticated LAN endpoint.
        if expiry(self.runtime.tls['cert']) - int(time.time()) <= RENEW_BEFORE:
            try:
                self.pending = self.candidate()
                self.runtime.tls = self.select(self.pending)
            except Exception as error:
                self.write_status('renewal_pending', type(error).__name__)

    def commit(self, record):
        verify_serving(self.runtime.origin, self.runtime.tls['ca'], record['spki'])
        _atomic_write(self.pointer, encode(record))
        self.write_status('renewed')

    def write_status(self, state, error=None):
        self.app.config['TLS'] = dict(self.runtime.tls)
        self.status = dict(state=state, observed=int(time.time()),
                           next_expiry=expiry(self.runtime.tls['cert']), error=error)
        _atomic_write(self.status_path, encode(self.status))

    def started(self):
        if self.pending is not None:
            self.commit(self.pending)
            self.pending = None
        else:
            self.write_status('scheduled')
        self.announce()
        self.thread = threading.Thread(target=self.loop, name='lan-tls-renewal', daemon=True)
        self.thread.start()

    def announce(self):
        if self.runtime.side != 'maintenance':
            return
        issuer = self.app.extensions['maintenance_tls_authority']
        if not issuer.maintenance_override or issuer.store.fenced():
            return
        try:
            with issuer.store.connection(write=False) as db:
                row = db.execute('SELECT configuration FROM tls_issuer WHERE singleton=1').fetchone()
            configuration = issuer.public_configuration(decode(bytes(row['configuration'])))
            delegation = configuration['delegations']['maintenance']
            self.app.extensions['maintenance_content']._request('POST', '/service/v1/tls-authority',
                dict(generation=issuer.store.placement()['generation'], delegation=delegation))
        except Exception:
            self.app.logger.warning('TLS authority relocation notification pending')

    def loop(self):
        while not self.runtime.stopped.wait(30):
            self.announce()
            if self.runtime.side == 'maintenance':
                from .authority_delivery import flush
                try:
                    flush(self.app.extensions['maintenance_store'], self.app.extensions['maintenance_content'])
                except Exception:
                    # Persisted public bundle is retried; never report recovery
                    # complete merely because the local transaction succeeded.
                    self.app.logger.warning('public authority delivery pending')
            if expiry(self.runtime.tls['cert']) - int(time.time()) > RENEW_BEFORE:
                self.write_status('scheduled' if self.status['state'] != 'renewed' else 'renewed')
                continue
            try:
                record = self.candidate()
                previous = dict(self.runtime.tls)
                try:
                    self.runtime.rotate_edge(self.select(record), record['spki'])
                    self.commit(record)
                except Exception:
                    self.runtime.rotate_edge(previous)
                    raise
            except Exception as error:
                self.write_status('renewal_pending', type(error).__name__)
