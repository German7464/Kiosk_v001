"""RSA3072 signing and bounded X.509 issuance built on the maintained ``cryptography`` package.

This module owns no cryptographic primitives: it reuses ``cryptography`` (pinned in
``requirements.txt``) for RSA key generation, PKCS#1 v1.5/SHA-256 signatures, X.509
certificate construction and password-based private-key encryption. Signing-domain
prefixes keep the trust-lifecycle envelopes distinct from the frozen
``device-delivery-v1`` ``Kiosk/GroupTrust/v1`` domain and from the stage7 Ed25519
update domain.

Key custody: every long-lived private key (offline root CA, offline group root,
offline recovery and the online intermediate) is serialised with
``BestAvailableEncryption`` (PBKDF2 + a maintained AEAD/block cipher) when a password
is supplied. ``NoEncryption`` remains only for the short-lived serving leaf, whose
key is rotated with the certificate and lives on the server for the TLS engine.
"""
from __future__ import annotations

import datetime
import hashlib
import ipaddress
import re

from cryptography import x509
from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa
from cryptography.x509.oid import ExtendedKeyUsageOID, NameOID

# Same algorithm family as the frozen group-trust contract, but with a new domain
# so a trust-lifecycle envelope can never be replayed as a group-trust envelope.
ALGORITHM = "RSA3072-SHA256-PKCS1-v1_5"
TRUST_DOMAIN = b"Kiosk/LanTrust/v1\0"

KEY_SIZE = 3072
PUBLIC_EXPONENT = 65537
SIGNATURE_BYTES = 384  # RSA3072 PKCS1 v1.5 output length

_UTC = datetime.timezone.utc


def generate_private_key() -> rsa.RSAPrivateKey:
    return rsa.generate_private_key(public_exponent=PUBLIC_EXPONENT, key_size=KEY_SIZE)


def _encryption(password):
    if password is None:
        return serialization.NoEncryption()
    if not isinstance(password, (str, bytes)) or not password:
        raise ValueError("A non-empty key password is required.")
    if isinstance(password, str):
        password = password.encode("utf-8")
    return serialization.BestAvailableEncryption(password)


def private_pem(key: rsa.RSAPrivateKey, password=None) -> str:
    """Return PKCS#8 PEM. Encrypted with BestAvailableEncryption when a password is given.

    Long-lived offline keys (root CA, group root, recovery) and the online
    intermediate are always written encrypted; only the short-lived serving leaf key
    uses NoEncryption because the TLS engine must read it without a prompt.
    """
    return key.private_bytes(
        serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
        _encryption(password),
    ).decode("ascii")


def public_pem(key: rsa.RSAPrivateKey | rsa.RSAPublicKey) -> str:
    public = key.public_key() if isinstance(key, rsa.RSAPrivateKey) else key
    return public.public_bytes(
        serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo,
    ).decode("ascii")


def spki_der(key: rsa.RSAPrivateKey | rsa.RSAPublicKey) -> bytes:
    public = key.public_key() if isinstance(key, rsa.RSAPrivateKey) else key
    return public.public_bytes(
        serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo,
    )


def key_id(key_or_spki) -> str:
    """Stable lowercase SHA-256 hex identity of a subject public key (SPKI DER)."""
    if isinstance(key_or_spki, (rsa.RSAPrivateKey, rsa.RSAPublicKey)):
        raw = spki_der(key_or_spki)
    else:
        raw = bytes(key_or_spki)
    return hashlib.sha256(raw).hexdigest()


def load_public_spki(pem: str) -> bytes:
    if not isinstance(pem, str) or len(pem) > 4096:
        raise ValueError("The trust public key is too large.")
    key = serialization.load_pem_public_key(pem.encode("ascii"))
    if not isinstance(key, rsa.RSAPublicKey):
        raise ValueError("The trust public key is not RSA.")
    return key.public_bytes(
        serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo,
    )


def load_private(pem: str, password=None) -> rsa.RSAPrivateKey:
    if not isinstance(pem, str) or len(pem) > 16384:
        raise ValueError("The trust private key is too large.")
    secret = None
    if password is not None:
        secret = password.encode("utf-8") if isinstance(password, str) else password
    key = serialization.load_pem_private_key(pem.encode("ascii"), password=secret)
    if not isinstance(key, rsa.RSAPrivateKey):
        raise ValueError("The trust private key is not RSA.")
    if key.key_size != KEY_SIZE:
        raise ValueError("The trust key must be RSA3072.")
    return key


def sign(private: rsa.RSAPrivateKey, domain: bytes, payload: bytes) -> bytes:
    if not isinstance(payload, bytes) or len(payload) > 32768:
        raise ValueError("The trust payload to sign is too large.")
    return private.sign(domain + payload, padding.PKCS1v15(), hashes.SHA256())


def verify(spki: bytes, domain: bytes, payload: bytes, signature: bytes) -> None:
    """Raise ``ValueError`` when the signature is not valid for the exact input."""
    if len(signature) != SIGNATURE_BYTES:
        raise ValueError("The trust signature has an unsupported length.")
    key = serialization.load_der_public_key(spki)
    if not isinstance(key, rsa.RSAPublicKey):
        raise ValueError("The trust public key is not RSA.")
    try:
        key.verify(signature, domain + payload, padding.PKCS1v15(), hashes.SHA256())
    except InvalidSignature as error:
        raise ValueError("The trust signature is not valid for its payload.") from error


def _subject(name: str) -> x509.Name:
    return x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, name)])


def _serial() -> int:
    return x509.random_serial_number()


def _utc_now(now):
    if now is None:
        return datetime.datetime.now(_UTC)
    return datetime.datetime.fromtimestamp(int(now), _UTC)


def _not_before(now=None) -> datetime.datetime:
    return _utc_now(now) - datetime.timedelta(minutes=5)


def _not_after(days: int, now=None) -> datetime.datetime:
    return _utc_now(now) + datetime.timedelta(days=days)


def issue_root_ca(name: str, *, validity_days: int, password=None, now=None) -> tuple[str, str]:
    """Return (cert_pem, key_pem) for a self-signed offline root CA."""
    key = generate_private_key()
    subject = _subject(name)
    cert = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(subject)
        .public_key(key.public_key())
        .serial_number(_serial())
        .not_valid_before(_not_before(now))
        .not_valid_after(_not_after(validity_days, now))
        .add_extension(x509.BasicConstraints(ca=True, path_length=1), critical=True)
        .add_extension(
            x509.KeyUsage(
                digital_signature=False, content_commitment=False, key_encipherment=False,
                data_encipherment=False, key_agreement=False, key_cert_sign=True,
                crl_sign=True, encipher_only=False, decipher_only=False,
            ),
            critical=True,
        )
        .add_extension(x509.SubjectKeyIdentifier.from_public_key(key.public_key()), critical=False)
        .sign(key, hashes.SHA256())
    )
    return cert.public_bytes(serialization.Encoding.PEM).decode("ascii"), private_pem(key, password)


def issue_intermediate_ca(
    name: str,
    root_cert_pem: str,
    root_key_pem: str,
    *,
    validity_days: int,
    password=None,
    root_key_password=None,
    now=None,
    public_key=None,
) -> tuple[str, str | None]:
    """Return (cert_pem, key_pem) for an intermediate CA issued by the offline root.

    The intermediate is the constrained online signing component: ``path_length=0``
    means it can sign end-entity leaves only and can never mint a further CA. Its
    private key lives on the online signer (encrypted at rest); the root key stays
    offline.
    """
    root_cert = x509.load_pem_x509_certificate(root_cert_pem.encode("ascii"))
    root_key = load_private(root_key_pem, root_key_password)
    key = generate_private_key() if public_key is None else None
    issuer_public = key.public_key() if key is not None else public_key
    if not isinstance(issuer_public, rsa.RSAPublicKey) or issuer_public.key_size != KEY_SIZE:
        raise ValueError('The issuer key must be RSA3072.')
    subject = _subject(name)
    cert = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(root_cert.subject)
        .public_key(issuer_public)
        .serial_number(_serial())
        .not_valid_before(_not_before(now))
        .not_valid_after(_not_after(validity_days, now))
        .add_extension(x509.BasicConstraints(ca=True, path_length=0), critical=True)
        .add_extension(
            x509.KeyUsage(
                digital_signature=False, content_commitment=False, key_encipherment=False,
                data_encipherment=False, key_agreement=False, key_cert_sign=True,
                crl_sign=True, encipher_only=False, decipher_only=False,
            ),
            critical=True,
        )
        .add_extension(x509.SubjectKeyIdentifier.from_public_key(issuer_public), critical=False)
        .add_extension(x509.AuthorityKeyIdentifier.from_issuer_public_key(root_key.public_key()), critical=False)
        .sign(root_key, hashes.SHA256())
    )
    return cert.public_bytes(serialization.Encoding.PEM).decode("ascii"), (private_pem(key, password) if key is not None else None)


def _san_names(san_ips, san_dns):
    names = [x509.IPAddress(ipaddress.IPv4Address(value)) for value in san_ips]
    names += [x509.DNSName(value) for value in san_dns]
    return names


def validate_leaf_identity(san_ips: list[str], san_dns: list[str]) -> None:
    if not san_ips and not san_dns:
        raise ValueError("A TLS leaf requires at least one identity.")
    for value in san_ips:
        address = ipaddress.IPv4Address(value)
        if address.is_unspecified or address.is_multicast or address.is_reserved:
            raise ValueError("Unicast IPv4 is required for TLS leaf names.")
    for value in san_dns:
        if (not isinstance(value, str) or value != value.lower()
                or not re.fullmatch(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?", value)
                or len(value) > 253):
            raise ValueError("Explicit lowercase DNS names are required for TLS leaf names.")


def issue_tls_leaf(
    name: str,
    issuer_cert_pem: str,
    issuer_key_pem: str,
    *,
    san_ips: list[str],
    san_dns: list[str],
    validity_days: int,
    now=None,
    issuer_key_password=None,
    public_key=None,
) -> tuple[str, str | None]:
    """Return (cert_pem, key_pem) for a short-lived server TLS leaf.

    The online intermediate issues leaves for the server's own origin only; the
    caller binds ``san_ips``/``san_dns`` to the configured server address. The leaf
    key is unencrypted so the TLS engine can load it without a prompt; it rotates
    with the leaf.
    """
    validate_leaf_identity(san_ips, san_dns)
    issuer_cert = x509.load_pem_x509_certificate(issuer_cert_pem.encode("ascii"))
    issuer_key = load_private(issuer_key_pem, issuer_key_password)
    key = generate_private_key() if public_key is None else None
    leaf_public = key.public_key() if key is not None else public_key
    if not isinstance(leaf_public, rsa.RSAPublicKey) or leaf_public.key_size != KEY_SIZE:
        raise ValueError('TLS public key must be RSA3072')
    subject = _subject(name)
    cert = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(issuer_cert.subject)
        .public_key(leaf_public)
        .serial_number(_serial())
        .not_valid_before(_not_before(now))
        .not_valid_after(_not_after(validity_days, now))
        .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
        .add_extension(
            x509.KeyUsage(
                digital_signature=True, content_commitment=False, key_encipherment=True,
                data_encipherment=False, key_agreement=False, key_cert_sign=False,
                crl_sign=False, encipher_only=False, decipher_only=False,
            ),
            critical=True,
        )
        .add_extension(x509.SubjectAlternativeName(_san_names(san_ips, san_dns)), critical=False)
        .add_extension(x509.ExtendedKeyUsage([ExtendedKeyUsageOID.SERVER_AUTH]), critical=False)
        .add_extension(x509.SubjectKeyIdentifier.from_public_key(leaf_public), critical=False)
        .add_extension(x509.AuthorityKeyIdentifier.from_issuer_public_key(issuer_key.public_key()), critical=False)
        .sign(issuer_key, hashes.SHA256())
    )
    return cert.public_bytes(serialization.Encoding.PEM).decode("ascii"), private_pem(key) if key is not None else None


def cert_chain(leaf_pem: str, intermediate_pem: str) -> str:
    """Return the leaf + issuer PEM chain used by the HTTPS proxy."""
    return leaf_pem.rstrip("\n") + "\n" + intermediate_pem.rstrip("\n") + "\n"


def leaf_spki_sha256(leaf_pem: str) -> str:
    cert = x509.load_pem_x509_certificate(leaf_pem.encode("ascii"))
    spki = cert.public_key().public_bytes(
        serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo,
    )
    return hashlib.sha256(spki).hexdigest()


def cert_spki_sha256(cert_pem: str) -> str:
    cert = x509.load_pem_x509_certificate(cert_pem.encode("ascii"))
    spki = cert.public_key().public_bytes(
        serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo,
    )
    return hashlib.sha256(spki).hexdigest()


def cert_not_before_utc(cert_pem: str) -> int:
    return int(x509.load_pem_x509_certificate(cert_pem.encode("ascii")).not_valid_before_utc.timestamp())


def cert_not_after_utc(cert_pem: str) -> int:
    return int(x509.load_pem_x509_certificate(cert_pem.encode("ascii")).not_valid_after_utc.timestamp())


def split_cert_chain(pem: str) -> list[str]:
    """Split a PEM bundle into individual certificate PEM blocks (no keys)."""
    blocks, current = [], []
    for line in pem.splitlines():
        if line.startswith("-----BEGIN CERTIFICATE-----"):
            current = [line]
        elif current:
            current.append(line)
            if line.startswith("-----END CERTIFICATE-----"):
                blocks.append("\n".join(current) + "\n")
                current = []
    if current:
        raise ValueError("Unterminated certificate PEM block.")
    return blocks
