"""Role separation and bounded delegation for the LAN trust lifecycle.

Each role is a distinct RSA3072 key. The model enforces key-role disjointness and
the delegation scope of the constrained online signer:

* ``root``     - offline. Signs the group trust list and the issuer delegation.
* ``issuer``   - online. Issues short-lived TLS leaves for its own origin only.
* ``recovery`` - offline. Single-use emergency grants.
* ``update``   - a separate Ed25519 key; referenced here only to forbid reuse.

The delegation is a root-signed statement that binds the online issuer to one
specific ``server_id``, one ``origin`` and a fixed, non-expanding set of permitted
TLS names (IP SANs and DNS SANs). ``OnlineIssuer`` derives its issuance target
exclusively from this delegation, so a caller can never ask the issuer to mint a
leaf for a different server, group or name.
"""
from __future__ import annotations

import ipaddress
import json
from dataclasses import dataclass
from urllib.parse import urlsplit

from kiosk.trust.crypto import ALGORITHM, load_private, sign, verify

ROLES = ("root", "issuer", "recovery", "update")
# The constrained online signer is allowed only this scope: short-lived TLS leaf
# issuance for the server's own origin. Device-credential renewal is NOT a signer
# scope: it is the server's own operation, gated by the root-signed group trust
# (see kiosk.delivery.state.DeliveryState.renew) and never authorized by the issuer
# key. A valid TLS leaf therefore grants no group membership, publishing or
# device-credential authority.
ISSUER_SCOPES = ("issue_tls_leaf",)
DELEGATION_DOMAIN = b"Kiosk/LanTrust/v1/delegation\0"


class RoleError(ValueError):
    pass


@dataclass(frozen=True)
class Delegation:
    """A root-signed statement naming the online issuer, its target and its exact scope."""

    version: int
    group_id: str
    server_id: str
    origin: str
    permitted_ip: tuple[str, ...]
    permitted_dns: tuple[str, ...]
    issuer_key_id: str
    issuer_spki_base64: str
    scopes: tuple[str, ...]
    max_tls_validity_days: int
    issued_at: int
    expires_at: int


def delegation_payload(d: Delegation) -> bytes:
    obj = {
        "version": d.version,
        "group_id": d.group_id,
        "server_id": d.server_id,
        "origin": d.origin,
        "permitted_ip": list(d.permitted_ip),
        "permitted_dns": list(d.permitted_dns),
        "issuer_key_id": d.issuer_key_id,
        "issuer_spki_base64": d.issuer_spki_base64,
        "scopes": list(d.scopes),
        "max_tls_validity_days": d.max_tls_validity_days,
        "issued_at": d.issued_at,
        "expires_at": d.expires_at,
    }
    return json.dumps(obj, sort_keys=True, separators=(",", ":")).encode("ascii")


def _parse_origin(origin: str) -> tuple[str, int]:
    if not isinstance(origin, str):
        raise RoleError("Delegation origin must be a string.")
    try:
        parsed = urlsplit(origin)
    except ValueError as error:
        raise RoleError("Delegation origin is invalid.") from error
    if (parsed.scheme != "https" or not parsed.hostname or parsed.port is None or
            parsed.username is not None or parsed.password is not None or
            parsed.path or parsed.query or parsed.fragment or
            parsed.netloc != origin[len("https://"):] or
            any(c.isspace() or c in "%\\" or ord(c) > 127 for c in origin)):
        raise RoleError("Delegation origin must be a bare https://host:port origin.")
    return parsed.hostname, parsed.port


def _validate_permitted(permitted_ip, permitted_dns, origin_host) -> None:
    if not isinstance(permitted_ip, (list, tuple)) or not permitted_ip:
        raise RoleError("Delegation must permit at least one unicast IPv4 name.")
    if not isinstance(permitted_dns, (list, tuple)):
        raise RoleError("Delegation permitted DNS names must be a list.")
    ips = []
    for value in permitted_ip:
        try:
            address = ipaddress.IPv4Address(value)
        except ipaddress.AddressValueError as error:
            raise RoleError("Delegation permitted_ip must be IPv4.") from error
        if address.is_unspecified or address.is_multicast or address.is_reserved:
            raise RoleError("Delegation permitted_ip must be unicast IPv4.")
        ips.append(str(address))
    if len(set(ips)) != len(ips):
        raise RoleError("Duplicate permitted IP names are not allowed.")
    dns = list(permitted_dns)
    for value in dns:
        if (not isinstance(value, str) or value != value.lower() or
                not __import__("re").fullmatch(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?", value) or len(value) > 253):
            raise RoleError("Delegation permitted_dns must be explicit lowercase DNS names.")
    if len(set(dns)) != len(dns):
        raise RoleError("Duplicate permitted DNS names are not allowed.")
    # The origin host must be one of the permitted IP names (the pilot uses an IP
    # origin; a hostname origin would be listed in permitted_dns).
    if origin_host not in ips:
        raise RoleError("Delegation origin host must be among the permitted names.")


def make_delegation(
    *,
    group_id: str,
    server_id: str,
    origin: str,
    permitted_ip,
    permitted_dns,
    issuer_key_id: str,
    issuer_spki_base64: str,
    max_tls_validity_days: int,
    issued_at: int,
    expires_at: int,
) -> Delegation:
    """Validate and build a Delegation with all target/bound checks applied."""
    if not isinstance(group_id, str) or not group_id or not isinstance(server_id, str) or not server_id:
        raise RoleError("Delegation group_id and server_id are required.")
    host, _port = _parse_origin(origin)
    _validate_permitted(permitted_ip, permitted_dns, host)
    if not isinstance(issuer_key_id, str) or len(issuer_key_id) != 64:
        raise RoleError("Delegation issuer_key_id must be 64 hex characters.")
    if not isinstance(issuer_spki_base64, str) or not issuer_spki_base64:
        raise RoleError("Delegation issuer_spki_base64 is required.")
    scopes = validate_delegation_scope([ISSUER_SCOPES[0]], max_tls_days=max_tls_validity_days)
    if not isinstance(issued_at, int) or not isinstance(expires_at, int) or issued_at < 0 or expires_at <= issued_at:
        raise RoleError("Delegation validity window is invalid.")
    return Delegation(
        version=1, group_id=group_id, server_id=server_id, origin=origin,
        permitted_ip=tuple(permitted_ip), permitted_dns=tuple(permitted_dns),
        issuer_key_id=issuer_key_id, issuer_spki_base64=issuer_spki_base64,
        scopes=scopes, max_tls_validity_days=max_tls_validity_days,
        issued_at=issued_at, expires_at=expires_at,
    )


def sign_delegation(root_private_pem: str, d: Delegation, *, password=None) -> bytes:
    root_key = load_private(root_private_pem, password)
    return sign(root_key, DELEGATION_DOMAIN, delegation_payload(d))


def verify_delegation(root_spki_der: bytes, d: Delegation, signature: bytes) -> None:
    verify(root_spki_der, DELEGATION_DOMAIN, delegation_payload(d), signature)


def validate_delegation_scope(scopes, *, max_tls_days: int) -> tuple[str, ...]:
    if not isinstance(scopes, (list, tuple)) or not scopes:
        raise RoleError("Delegation must list at least one scope.")
    normalized = tuple(scopes)
    if set(normalized) - set(ISSUER_SCOPES):
        raise RoleError("Delegation scope exceeds the constrained online issuer.")
    if len(set(normalized)) != len(normalized):
        raise RoleError("Duplicate delegation scopes are not allowed.")
    if max_tls_days < 1 or max_tls_days > 30:
        raise RoleError("TLS leaf validity is bounded to 1..30 days.")
    return normalized


def check_key_role_disjointness(roles: dict[str, str]) -> None:
    """Refuse any key shared between roles; RSA role ids must be distinct 64-hex.

    ``update`` is an Ed25519 key (a different key type) and is inherently disjoint
    from the RSA3072 root/issuer/recovery keys; it is checked only for presence.
    """
    if set(roles) != set(ROLES):
        raise RoleError("Exactly the four trust roles must be supplied.")
    ids = {}
    for name in ("root", "issuer", "recovery"):
        key_id = roles[name]
        if not isinstance(key_id, str) or len(key_id) != 64:
            raise RoleError("Invalid RSA key id for role %r." % name)
        ids[name] = key_id
    if roles["update"] in ids.values() or len(set(ids.values())) != 3:
        raise RoleError("The same key must never serve more than one trust role.")
