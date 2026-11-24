"""At-rest protection for reviewer/acceptance keys owned by the Maintenance side.

On Windows the existing DPAPI wrapper is used. On other platforms a local
AES-GCM master-key file with owner-only permissions is used; this is weaker (a
file read is enough) and is reported as such. DPAPI blobs are not portable, so
relocation re-wraps private keys through the encrypted transfer bundle rather
than copying the platform blob.
"""
from __future__ import annotations

import base64
import os
from pathlib import Path

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from .store import MaintenanceError

AAD = b'kiosk-maintenance-key-v1'


def _master(secrets_dir):
    secrets_dir = Path(secrets_dir)
    key_path = secrets_dir / 'keymaster.bin'
    secrets_dir.mkdir(parents=True, exist_ok=True)
    if not key_path.exists():
        key_path.write_bytes(os.urandom(32))
        try:
            os.chmod(key_path, 0o600)
        except OSError:
            pass
    key = key_path.read_bytes()
    if len(key) != 32:
        raise MaintenanceError('key_protection_refused', 503)
    return key


def protect(raw, secrets_dir, *, decrypt=False):
    if not isinstance(raw, (bytes, bytearray)):
        raise MaintenanceError('key_protection_refused', 503)
    if os.name == 'nt':
        from kiosk.display.native_crypto import protect as dpapi
        from kiosk.publication.exporter import PackageError
        try:
            return dpapi(bytes(raw), decrypt=decrypt)
        except PackageError:
            raise MaintenanceError('key_protection_refused', 503) from None
    key = _master(secrets_dir)
    if decrypt:
        try:
            if not raw.startswith(b'v1.'):
                raise ValueError()
            blob = base64.b64decode(bytes(raw)[3:], validate=True)
            nonce, body = blob[:12], blob[12:]
            return AESGCM(key).decrypt(nonce, body, AAD)
        except (ValueError, TypeError):
            raise MaintenanceError('key_protection_refused', 503) from None
    nonce = os.urandom(12)
    body = AESGCM(key).encrypt(nonce, bytes(raw), AAD)
    return b'v1.' + base64.b64encode(nonce + body)
