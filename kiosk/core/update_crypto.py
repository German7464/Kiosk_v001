"""Ed25519 update-signing primitives built on the maintained ``cryptography`` package.

The update-signing key is a dedicated, separate Ed25519 key. It is never the
HTTPS/group key, the bootstrap key or an administrator credential. Signing happens
only on the build machine (PC1); the installed server and client hold only the
public verification key and call :func:`verify_signature`. A public key is 32 raw
bytes (64 hex); its identifier is the first 16 hex characters and binds a manifest
to a specific key, so a rotated key stays rejected until its new public key is
trusted out of band.
"""
from __future__ import annotations

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey

PUBLIC_KEY_BYTES = 32
SIGNATURE_BYTES = 64
ALGORITHM = "ed25519"


def generate_key() -> tuple[str, str]:
    """Return (private_pem, public_pem) for a fresh key. Build machine only."""
    private = Ed25519PrivateKey.generate()
    private_pem = private.private_bytes(
        serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()
    ).decode("ascii")
    public_pem = private.public_key().public_bytes(
        serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo
    ).decode("ascii")
    return private_pem, public_pem


def load_public_key(pem: str | bytes) -> Ed25519PublicKey:
    if isinstance(pem, str):
        pem = pem.encode("ascii")
    if len(pem) > 4096:
        raise ValueError("The update verification key is too large.")
    key = serialization.load_pem_public_key(pem)
    if not isinstance(key, Ed25519PublicKey):
        raise ValueError("The update verification key is not Ed25519.")
    return key


def load_private_key(pem: str | bytes) -> Ed25519PrivateKey:
    if isinstance(pem, str):
        pem = pem.encode("ascii")
    if len(pem) > 4096:
        raise ValueError("The update signing key is too large.")
    key = serialization.load_pem_private_key(pem, password=None)
    if not isinstance(key, Ed25519PrivateKey):
        raise ValueError("The update signing key is not Ed25519.")
    return key


def raw_public_key(key: Ed25519PublicKey) -> bytes:
    return key.public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)


def public_key_id(key_or_pem: Ed25519PublicKey | str | bytes) -> str:
    """Stable 16-hex identifier of the public key, used to bind manifests."""
    if isinstance(key_or_pem, Ed25519PublicKey):
        raw = raw_public_key(key_or_pem)
    else:
        raw = raw_public_key(load_public_key(key_or_pem))
    return raw.hex()[:16]


def sign(private_pem: str | bytes, data: bytes) -> bytes:
    if len(data) > 1024 * 1024:
        raise ValueError("The data to sign is too large.")
    return load_private_key(private_pem).sign(data)


def verify_signature(key_or_pem: Ed25519PublicKey | str | bytes, data: bytes, signature: bytes) -> None:
    """Raise ``ValueError`` when the signature is not valid for ``data``."""
    if len(signature) != SIGNATURE_BYTES:
        raise ValueError("The update signature has an unsupported length.")
    if isinstance(key_or_pem, Ed25519PublicKey):
        key = key_or_pem
    else:
        key = load_public_key(key_or_pem)
    try:
        key.verify(signature, data)
    except InvalidSignature as error:
        raise ValueError("The update package signature is not valid for its manifest.") from error
