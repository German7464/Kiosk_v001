"""Constrained online signing component and the TLS/credential renewal policy.

The online issuer holds only the intermediate CA key (``path_length=0``, can sign
end-entity leaves) plus a root-signed delegation that names its exact scope AND its
single permitted target. Every issuance re-verifies that delegation and the
persisted monotonic time floor, derives the issuance target exclusively from the
delegation (never from the caller), and refuses revoked targets, cross-server /
cross-group / name expansion, and any leaf that would outlive the issuer or the
delegation. The offline root key is never available here.
"""
from __future__ import annotations

import base64
import json
from urllib.parse import urlsplit

from kiosk.trust.crypto import (
    ALGORITHM,
    cert_chain,
    cert_not_after_utc,
    cert_not_before_utc,
    issue_tls_leaf,
    key_id,
    leaf_spki_sha256,
    load_private,
    load_public_spki,
    spki_der,
    verify,
)
from kiosk.trust.roles import Delegation, delegation_payload, verify_delegation
from kiosk.trust.state import LifecycleError, LifecycleState


class IssuanceError(ValueError):
    def __init__(self, code):
        super().__init__(code)
        self.code = code


class OnlineIssuer:
    """The constrained online signing component for one group/server."""

    def __init__(self, state: LifecycleState, root_spki_der: bytes, delegation: Delegation,
                 delegation_signature: bytes):
        self.state = state
        self.root_spki_der = root_spki_der
        self.delegation = delegation
        self.delegation_signature = delegation_signature

    def _authorize(self, scope, now):
        # The delegation is re-verified against the offline root on every use; a
        # stale or altered delegation never extends authority.
        verify_delegation(self.root_spki_der, self.delegation, self.delegation_signature)
        if scope not in self.delegation.scopes:
            raise IssuanceError("scope_not_delegated")
        if not self.delegation.issued_at <= now < self.delegation.expires_at:
            raise IssuanceError("delegation_expired")
        with self.state.connection() as db:
            self.state.checked_now(db, now)
        return now

    def _origin_host(self):
        parsed = urlsplit(self.delegation.origin)
        return parsed.hostname, parsed.port

    def renew_tls_leaf(
        self,
        intermediate_cert_pem: str,
        intermediate_key_pem: str,
        *,
        validity_days: int,
        now: int,
        intermediate_key_password=None,
        fail_at: str | None = None,
        csr_pem: str | None = None,
    ) -> dict:
        """Issue (and durably record) a short-lived TLS leaf for the delegated target.

        The issuance target — ``server_id``, ``group_id``, ``origin``, IP/DNS names —
        is read only from the root-signed delegation. A caller cannot request a
        different server, group or name set: any attempt to expand names beyond the
        delegation is refused at construction (see ``make_delegation``), and the leaf
        is minted strictly from ``delegation.permitted_ip`` / ``delegation.permitted_dns``.
        """
        now = self._authorize("issue_tls_leaf", now)
        if validity_days < 1 or validity_days > self.delegation.max_tls_validity_days:
            raise IssuanceError("tls_validity_exceeds_delegation")
        if self.state.revoked(self.delegation.server_id):
            raise IssuanceError("server_revoked")
        # The intermediate must be the exact key named by the delegation.
        issuer_key = load_private(intermediate_key_pem, intermediate_key_password)
        if key_id(issuer_key) != self.delegation.issuer_key_id:
            raise IssuanceError("issuer_key_mismatch")
        # The issuer certificate must be a CA (path_length=0) whose subject the
        # delegation actually names; a mismatch would let a different CA mint leaves.
        intermediate_not_after = cert_not_after_utc(intermediate_cert_pem)
        if cert_not_before_utc(intermediate_cert_pem) > now or intermediate_not_after <= now:
            raise IssuanceError("issuer_certificate_expired")
        # Bound the leaf so it never outlives the issuer certificate or the delegation.
        leaf_not_after = now + validity_days * 86400
        if leaf_not_after > intermediate_not_after or leaf_not_after > self.delegation.expires_at:
            raise IssuanceError("leaf_would_outlive_issuer_or_delegation")

        public_key = None
        if csr_pem is not None:
            # PKCS#10 proves possession of a server-local key. Never transport a
            # serving private key to/from the separate signing service.
            from cryptography import x509
            from cryptography.hazmat.primitives.asymmetric import rsa
            if not isinstance(csr_pem, str) or len(csr_pem) > 16384:
                raise IssuanceError('csr_refused')
            try:
                csr = x509.load_pem_x509_csr(csr_pem.encode('ascii'))
                public_key = csr.public_key()
                names = csr.extensions.get_extension_for_class(x509.SubjectAlternativeName).value
                ips = tuple(str(value) for value in names.get_values_for_type(x509.IPAddress))
                dns = tuple(names.get_values_for_type(x509.DNSName))
                if (not csr.is_signature_valid or not isinstance(public_key, rsa.RSAPublicKey)
                        or public_key.key_size != 3072 or len(csr.extensions) != 1
                        or len(names) != len(ips) + len(dns)
                        or sorted(ips) != sorted(self.delegation.permitted_ip)
                        or sorted(dns) != sorted(self.delegation.permitted_dns)):
                    raise ValueError('csr_scope')
            except (ValueError, TypeError, UnicodeError, x509.ExtensionNotFound):
                raise IssuanceError('csr_refused') from None

        host, _port = self._origin_host()
        leaf_pem, leaf_key_pem = issue_tls_leaf(
            self.delegation.server_id, intermediate_cert_pem, intermediate_key_pem,
            san_ips=list(self.delegation.permitted_ip), san_dns=list(self.delegation.permitted_dns),
            validity_days=validity_days, now=now, issuer_key_password=intermediate_key_password,
            public_key=public_key,
        )
        not_before = cert_not_before_utc(leaf_pem)
        not_after = cert_not_after_utc(leaf_pem)
        spki = leaf_spki_sha256(leaf_pem)
        generation = self.state.record_tls(spki, not_before, not_after, now=now, fail_at=fail_at)
        return {
            "generation": generation,
            "leaf_pem": leaf_pem,
            "leaf_key_pem": leaf_key_pem,
            "chain_pem": cert_chain(leaf_pem, intermediate_cert_pem),
            "tls_spki_sha256": spki,
            "not_before": not_before,
            "not_after": not_after,
            "server_id": self.delegation.server_id,
            "group_id": self.delegation.group_id,
            "origin": self.delegation.origin,
            "issuer_spki_sha256": key_id(issuer_key),
        }

    def activate(self, generation: int, now: int, fail_at: str | None = None) -> dict:
        """Mark a recorded TLS generation as the serving leaf (atomic, monotonic)."""
        self._authorize("issue_tls_leaf", now)
        generation = self.state.activate(generation, now=now, fail_at=fail_at)
        record = self.state.tls_record(generation)
        return {"generation": generation, "serving_spki_sha256": record["spki_sha256"],
                "not_after": record["not_after"]}


def verify_delegation_envelope(root_spki_der: bytes, delegation: Delegation, signature: bytes) -> None:
    verify_delegation(root_spki_der, delegation, signature)


def verify_group_window(envelope, root_spki_der):
    """Bounded canonical v2 window for the installed ninety-day workflow.

    Historical inspection is allowed here; callers decide whether current time
    permits admission. Root replacement and extra server roles are not inferred.
    """
    from kiosk.delivery.protocol import fields
    fields(envelope, 'version key_id algorithm payload_base64 signature_base64')
    if type(envelope['version']) is not int or envelope['version'] != 2 or envelope['algorithm'] != ALGORITHM:
        raise IssuanceError('group_authority_refused')
    raw = base64.b64decode(envelope['payload_base64'], validate=True)
    if len(raw) > 16384:
        raise IssuanceError('group_authority_refused')
    if envelope['key_id'] != key_id(root_spki_der):
        raise IssuanceError('group_authority_refused')
    verify(root_spki_der, b'Kiosk/GroupTrust/v2\0', raw,
           base64.b64decode(envelope['signature_base64'], validate=True))
    value = json.loads(raw)
    fields(value, 'version group_id generation issued_at expires_at servers')
    if (raw != json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=True).encode('ascii')
            or type(value['version']) is not int or value['version'] != 2
            or any(type(value[name]) is not int for name in ('generation', 'issued_at', 'expires_at'))
            or value['generation'] < 1 or value['issued_at'] < 0
            or not 0 < value['expires_at'] - value['issued_at'] <= 104 * 86400
            or not isinstance(value['servers'], list) or len(value['servers']) != 1):
        raise IssuanceError('group_authority_refused')
    item = value['servers'][0]
    fields(item, 'server_id origin tls_issuer_spki_sha256 roles')
    if item['roles'] != ['publisher']:
        raise IssuanceError('group_authority_refused')
    return value


def delegation_from_payload(payload: dict) -> Delegation:
    """Build a validated Delegation from a parsed public payload."""
    try:
        return Delegation(
            version=payload["version"],
            group_id=payload["group_id"],
            server_id=payload["server_id"],
            origin=payload["origin"],
            permitted_ip=tuple(payload["permitted_ip"]),
            permitted_dns=tuple(payload["permitted_dns"]),
            issuer_key_id=payload["issuer_key_id"],
            issuer_spki_base64=payload["issuer_spki_base64"],
            scopes=tuple(payload["scopes"]),
            max_tls_validity_days=payload["max_tls_validity_days"],
            issued_at=payload["issued_at"],
            expires_at=payload["expires_at"],
        )
    except KeyError as error:
        raise IssuanceError("delegation_schema_refused") from error
