"""Password-protected single-administrator recovery backup and offline re-issue.

This module implements the owner-approved recovery behaviour for the isolated
LAN trust lifecycle without adding a new cryptographic protocol:

* one authenticated-encryption container (PBKDF2-HMAC-SHA256 + AES-256-GCM from the
  maintained ``cryptography`` package) protects the offline root/group/recovery
  material under a separate recovery password;
* the manifest is authenticated as additional data, so a modified or truncated
  container is refused rather than partially restored;
* restore only writes into a NEW (nonexistent) root and never migrates a retained
  installation, matching the approved rule that existing groups keep their keys;
* ``reauthorize`` re-signs the group trust list at the next generation with a fresh
  validity window using the same group identity, so long-disconnected clients resume
  admission automatically after the operator renews authority;
* ``rebuild-server`` issues a new constrained online issuer and delegation for the
  same group/server identity after the online key is lost: clients accept the new
  issuer only through a higher-generation signed trust list, never by reusing an
  old issuer pin.

Device-bound operating-system keys (Android Keystore, Windows DPAPI) remain
device-bound. The software keys here are the group/CA keys, not a device
credential: a restored copy can sign authority, so it must never become a second
concurrently active authority. Restore therefore refuses an existing root and the
caller must stop the previous installation before re-issuing.
"""
from __future__ import annotations

import base64
import hashlib
import json
import os
import shutil
import tempfile
import time
from pathlib import Path

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC

from kiosk.trust.crypto import cert_spki_sha256, key_id, load_private, sign, verify
from kiosk.trust.roles import (
    check_key_role_disjointness,
    make_delegation,
    verify_delegation,
)

BUNDLE_FORMAT = "kiosk-lan-trust-recovery-v1"
KDF_ITERATIONS = 600000
SALT_BYTES = 16
NONCE_BYTES = 12
MAX_BUNDLE_BYTES = 128 * 1024
GROUP_TRUST_DOMAIN = b"Kiosk/GroupTrust/v2\0"
MATERIAL_NAMES = frozenset({"root-ca.pem", "root-ca-key.pem", "group-key.pem",
    "recovery-key.pem", "delegation.json", "bootstrap.json", "manifest.json", "trust.json"})


class RecoveryError(ValueError):
    pass


def _canonical(value) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode("ascii")


def _b64(value: bytes) -> str:
    return base64.b64encode(value).decode("ascii")


def _unb64(value, *, limit=MAX_BUNDLE_BYTES) -> bytes:
    if not isinstance(value, str) or len(value) > (limit + 2) // 3 * 4:
        raise RecoveryError("bundle_field_invalid")
    try:
        raw = base64.b64decode(value, validate=True)
    except (ValueError, TypeError) as error:
        raise RecoveryError("bundle_field_invalid") from error
    if len(raw) > limit:
        raise RecoveryError("bundle_field_invalid")
    return raw


def _derive(password, salt: bytes):
    if not isinstance(password, str) or not password:
        raise RecoveryError("recovery_password_required")
    key = PBKDF2HMAC(algorithm=hashes.SHA256(), length=32, salt=salt, iterations=KDF_ITERATIONS)
    return key.derive(password.encode("utf-8"))


def _private(path: Path) -> str:
    try:
        return path.read_text(encoding="ascii")
    except OSError as error:
        raise RecoveryError("offline_material_missing") from error


def create_backup(root, password) -> dict:
    """Encrypt the offline root/group/recovery material into a single bundle."""
    root = Path(root).absolute()
    private = root / "admin-private"
    material = {
        "root-ca.pem": _private(root / "public/root-ca.pem"),
        "root-ca-key.pem": _private(private / "root-ca-key.pem"),
        "group-key.pem": _private(private / "group-key.pem"),
        "recovery-key.pem": _private(private / "recovery-key.pem"),
        "delegation.json": _private(root / "server/delegation.json"),
        "bootstrap.json": _private(root / "public/bootstrap.json"),
        "manifest.json": _private(root / "public/manifest.json"),
        "trust.json": _private(root / "public/trust.json"),
    }
    # public.json is the atomic serving commit point. A crash after committing it
    # must not make the recovery backup silently capture the older mirror.
    serving = root / "server/public.json"
    if serving.is_file():
        material["trust.json"] = json.dumps(json.loads(_private(serving))["trust"], indent=2) + "\n"
    manifest = json.loads(_private(root / "public/manifest.json"))
    bootstrap = json.loads(_private(root / "public/bootstrap.json"))

    group_key = load_private(material["group-key.pem"], password)
    root_key = load_private(material["root-ca-key.pem"], password)
    recovery_key = load_private(material["recovery-key.pem"], password)
    check_key_role_disjointness({
        "root": key_id(group_key), "issuer": manifest["roles"]["issuer"],
        "recovery": key_id(recovery_key), "update": manifest["roles"]["update"],
    })
    if key_id(group_key) != bootstrap["group_key_id"]:
        raise RecoveryError("group_key_mismatch")
    if cert_spki_sha256(material["root-ca.pem"]) != key_id(root_key.public_key()):
        raise RecoveryError("root_certificate_key_mismatch")

    delegation = json.loads(material["delegation.json"])
    target = make_delegation(
        group_id=delegation["group_id"], server_id=delegation["server_id"],
        origin=delegation["origin"], permitted_ip=delegation["permitted_ip"],
        permitted_dns=delegation["permitted_dns"], issuer_key_id=delegation["issuer_key_id"],
        issuer_spki_base64=delegation["issuer_spki_base64"],
        max_tls_validity_days=delegation["max_tls_validity_days"],
        issued_at=delegation["issued_at"], expires_at=delegation["expires_at"],
    )
    verify_delegation(public_spki(group_key), target,
                      base64.b64decode(delegation["signature_base64"]))

    payload = _canonical({
        "version": 1,
        "group_id": bootstrap["group_id"], "server_id": bootstrap["server_id"],
        "origin": bootstrap["origin"], "files": material,
    })
    metadata = {
        "format": BUNDLE_FORMAT, "created_at": int(time.time()),
        "group_id": bootstrap["group_id"], "server_id": bootstrap["server_id"],
        "origin": bootstrap["origin"], "group_key_id": key_id(group_key),
        "root_ca_spki_sha256": cert_spki_sha256(material["root-ca.pem"]),
        "recovery_key_id": key_id(recovery_key),
        "files": {name: hashlib.sha256(value.encode("ascii")).hexdigest()
                  for name, value in material.items()},
    }
    aad = _canonical(metadata)
    salt, nonce = os.urandom(SALT_BYTES), os.urandom(NONCE_BYTES)
    ciphertext = AESGCM(_derive(password, salt)).encrypt(nonce, payload, aad)
    return {
        "format": BUNDLE_FORMAT,
        "kdf": {"name": "pbkdf2-hmac-sha256", "iterations": KDF_ITERATIONS, "salt_base64": _b64(salt)},
        "cipher": {"name": "aes-256-gcm", "nonce_base64": _b64(nonce)},
        "ciphertext_base64": _b64(ciphertext),
        "manifest": metadata,
    }


def public_spki(key) -> bytes:
    """DER SPKI of a public or private key (used for signature verification)."""
    public = key.public_key() if hasattr(key, "public_key") else key
    return public.public_bytes(serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo)


def open_bundle(bundle, password) -> tuple[dict, dict]:
    """Decrypt and integrity-check a bundle. Wrong password/tampering is refused."""
    if not isinstance(password, str) or not 1 <= len(password.encode("utf-8")) <= 4096:
        raise RecoveryError("recovery_password_required")
    if not isinstance(bundle, dict) or len(_canonical(bundle)) > MAX_BUNDLE_BYTES or set(bundle) != {"format", "kdf", "cipher", "ciphertext_base64", "manifest"}:
        raise RecoveryError("bundle_format_invalid")
    if bundle["format"] != BUNDLE_FORMAT:
        raise RecoveryError("bundle_format_invalid")
    kdf, cipher, metadata = bundle["kdf"], bundle["cipher"], bundle["manifest"]
    if (not isinstance(kdf, dict) or kdf.get("name") != "pbkdf2-hmac-sha256" or
            type(kdf.get("iterations")) is not int or not 100000 <= kdf["iterations"] <= 2000000):
        raise RecoveryError("bundle_kdf_invalid")
    if not isinstance(cipher, dict) or cipher.get("name") != "aes-256-gcm":
        raise RecoveryError("bundle_cipher_invalid")
    salt, nonce = _unb64(kdf.get("salt_base64"), limit=SALT_BYTES), _unb64(cipher.get("nonce_base64"), limit=NONCE_BYTES)
    if len(salt) != SALT_BYTES or len(nonce) != NONCE_BYTES:
        raise RecoveryError("bundle_field_invalid")
    if (not isinstance(metadata, dict) or metadata.get("format") != BUNDLE_FORMAT
            or not isinstance(metadata.get("files"), dict)
            or set(metadata["files"]) != MATERIAL_NAMES):
        raise RecoveryError("bundle_manifest_invalid")
    try:
        # The declared iteration count is authenticated by the manifest? No: it is
        # input to the KDF. It is bounded above and the GCM tag still authenticates
        # the plaintext+manifest, so a lowered count only makes decryption fail.
        key = PBKDF2HMAC(algorithm=hashes.SHA256(), length=32, salt=salt,
                         iterations=kdf["iterations"]).derive(password.encode("utf-8"))
        raw = AESGCM(key).decrypt(nonce, _unb64(bundle.get("ciphertext_base64")), _canonical(metadata))
    except RecoveryError:
        raise
    except Exception:
        raise RecoveryError("recovery_authentication_failed") from None
    try:
        payload = json.loads(raw.decode("ascii"))
    except (UnicodeDecodeError, ValueError):
        raise RecoveryError("bundle_manifest_invalid") from None
    if (not isinstance(payload, dict) or payload.get("version") != 1 or
            payload.get("group_id") != metadata.get("group_id") or
            payload.get("server_id") != metadata.get("server_id") or
            payload.get("origin") != metadata.get("origin") or
            not isinstance(payload.get("files"), dict) or
            set(payload["files"]) != MATERIAL_NAMES):
        raise RecoveryError("bundle_manifest_invalid")
    for name, value in payload["files"].items():
        if not isinstance(value, str) or len(value) > 32768:
            raise RecoveryError("bundle_material_invalid")
        if hashlib.sha256(value.encode("ascii")).hexdigest() != metadata["files"][name]:
            raise RecoveryError("bundle_material_changed")
    return payload, metadata


def restore_bundle(bundle, root, password, *, extract_password) -> dict:
    """Restore offline material into a NEW root. Never migrates an existing one."""
    root = Path(root).absolute()
    if root.exists():
        raise RecoveryError("existing_root_preserved")
    payload, metadata = open_bundle(bundle, password)
    files = payload["files"]
    group_key = load_private(files["group-key.pem"], extract_password)
    root_key = load_private(files["root-ca-key.pem"], extract_password)
    recovery_key = load_private(files["recovery-key.pem"], extract_password)
    if key_id(group_key) != metadata["group_key_id"]:
        raise RecoveryError("group_key_mismatch")
    if cert_spki_sha256(files["root-ca.pem"]) != key_id(root_key.public_key()):
        raise RecoveryError("root_certificate_key_mismatch")
    if metadata.get("recovery_key_id") != key_id(recovery_key):
        raise RecoveryError("recovery_key_mismatch")
    delegation = json.loads(files["delegation.json"])
    target = make_delegation(
        group_id=delegation["group_id"], server_id=delegation["server_id"],
        origin=delegation["origin"], permitted_ip=delegation["permitted_ip"],
        permitted_dns=delegation["permitted_dns"], issuer_key_id=delegation["issuer_key_id"],
        issuer_spki_base64=delegation["issuer_spki_base64"],
        max_tls_validity_days=delegation["max_tls_validity_days"],
        issued_at=delegation["issued_at"], expires_at=delegation["expires_at"],
    )
    verify_delegation(public_spki(group_key), target,
                      base64.b64decode(delegation["signature_base64"]))
    bootstrap = json.loads(files["bootstrap.json"])
    manifest = json.loads(files["manifest.json"])
    trust = verify_envelope(json.loads(files["trust.json"]), group_key)
    for field in ("group_id", "server_id", "origin"):
        if bootstrap.get(field) != metadata.get(field) or delegation.get(field) != metadata.get(field):
            raise RecoveryError("bundle_identity_mismatch")
    if (bootstrap.get("group_key_id") != key_id(group_key)
            or bootstrap.get("tls_ca_pem") != files["root-ca.pem"]
            or trust.get("group_id") != metadata["group_id"]
            or manifest.get("roles", {}).get("issuer") != delegation["issuer_key_id"]):
        raise RecoveryError("bundle_reference_mismatch")
    if (bootstrap.get("group_spki_base64") != _b64(public_spki(group_key))
            or manifest.get("group_spki_base64") != bootstrap["group_spki_base64"]
            or any(manifest.get(f) != metadata[f] for f in ("group_id", "server_id"))
            or trust.get("servers") != [{"server_id": metadata["server_id"],
                "origin": metadata["origin"], "tls_issuer_spki_sha256": delegation["issuer_key_id"],
                "roles": ["publisher"]}]):
        raise RecoveryError("bundle_reference_mismatch")
    check_key_role_disjointness(manifest["roles"])
    if (manifest["roles"].get("root") != key_id(group_key)
            or manifest["roles"].get("recovery") != key_id(recovery_key)
            or key_id(root_key) in manifest["roles"].values()):
        raise RecoveryError("bundle_key_role_mismatch")

    # Publish one complete tree on the same filesystem. Interrupted staging is
    # inert (no online issuer or service) and never masquerades as a restore.
    root.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix=".kiosk-recovery-", dir=root.parent))
    try:
        (staging / "admin-private").mkdir()
        (staging / "public").mkdir()
        (staging / "public/root-ca.pem").write_text(files["root-ca.pem"], encoding="ascii")
        (staging / "admin-private/root-ca-key.pem").write_text(files["root-ca-key.pem"], encoding="ascii")
        (staging / "admin-private/group-key.pem").write_text(files["group-key.pem"], encoding="ascii")
        (staging / "admin-private/recovery-key.pem").write_text(files["recovery-key.pem"], encoding="ascii")
        (staging / "public/bootstrap.json").write_text(files["bootstrap.json"], encoding="ascii")
        (staging / "public/manifest.json").write_text(files["manifest.json"], encoding="ascii")
        (staging / "public/trust.json").write_text(files["trust.json"], encoding="ascii")
        (staging / "server").mkdir()
        (staging / "server/delegation.json").write_text(files["delegation.json"], encoding="ascii")
        (staging / "restored.json").write_text(json.dumps({
            "format": BUNDLE_FORMAT, "restored_at": int(time.time()),
            "group_id": metadata["group_id"], "server_id": metadata["server_id"],
            "origin": metadata["origin"], "group_key_id": metadata["group_key_id"],
            "root_ca_spki_sha256": metadata["root_ca_spki_sha256"],
        }, indent=2) + "\n", encoding="ascii")
        os.rename(staging, root)
    except BaseException:
        # Only this invocation's uniquely created staging tree is removed.
        shutil.rmtree(staging)
        raise
    return {"status": "restored", "root": str(root), "group_id": metadata["group_id"],
            "server_id": metadata["server_id"], "origin": metadata["origin"],
            "group_key_id": metadata["group_key_id"],
            "offline_files": ["root-ca-key.pem", "group-key.pem", "recovery-key.pem"]}


def group_trust_envelope(group_key, *, group_id, server_id, origin, issuer_spki_sha256,
                         generation, issued_at, expires_at) -> dict:
    """Sign one group-trust generation; identity stays, only validity advances."""
    payload = {
        "version": 2, "group_id": group_id, "generation": generation,
        "issued_at": issued_at, "expires_at": expires_at,
        "servers": [{"server_id": server_id, "origin": origin,
                     "tls_issuer_spki_sha256": issuer_spki_sha256, "roles": ["publisher"]}],
    }
    raw = _canonical(payload)
    return {
        "version": 2, "key_id": key_id(group_key), "algorithm": "RSA3072-SHA256-PKCS1-v1_5",
        "payload_base64": _b64(raw), "signature_base64": _b64(sign(group_key, GROUP_TRUST_DOMAIN, raw)),
    }


def trust_issuer_sha256(envelope) -> str:
    payload = json.loads(base64.b64decode(envelope["payload_base64"]))
    servers = payload.get("servers")
    if not isinstance(servers, list) or len(servers) != 1:
        raise RecoveryError("trust_server_refused")
    return servers[0]["tls_issuer_spki_sha256"]


def verify_envelope(envelope, group_key) -> dict:
    """Verify our own freshly signed envelope before writing it anywhere."""
    from kiosk.trust.crypto import verify

    raw = base64.b64decode(envelope["payload_base64"])
    verify(public_spki(group_key), GROUP_TRUST_DOMAIN, raw,
           base64.b64decode(envelope["signature_base64"]))
    if key_id(group_key) != envelope["key_id"]:
        raise RecoveryError("group_key_mismatch")
    return json.loads(raw)


def next_generation(previous: dict, *, now: int, trust_days: int) -> dict:
    """A fresh validity window at generation+1 for the same identity and server."""
    if type(trust_days) is not int or not 1 <= trust_days <= 3650:
        raise RecoveryError("trust_days_out_of_range")
    generation = previous.get("generation")
    if type(generation) is not int or generation < 1:
        raise RecoveryError("trust_envelope_invalid")
    expires_at = now + trust_days * 86400
    if expires_at <= now:
        raise RecoveryError("trust_days_out_of_range")
    return {"generation": generation + 1, "issued_at": now, "expires_at": expires_at}
