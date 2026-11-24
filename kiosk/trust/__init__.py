"""Isolated LAN trust-lifecycle pilot: role-separated issuance and renewal.

This package is additive to the frozen :mod:`kiosk.delivery` enrollment contract
(``device-delivery-v1``). It introduces the versioned public contract
``lan-trust-lifecycle-v1``: a separately protected offline root and a constrained
online signing component for routine TLS renewal over a local network, with no
Internet dependency, no mandatory SaaS/ACME/public DNS and no silent operating-system
trust installation.

Role separation (each role is a distinct RSA3072 key; a key is never reused across
roles):

* ``root``      - offline group root. Signs the group trust list and the issuer
  delegation (which names the online issuer and binds it to one server/origin and a
  fixed set of permitted TLS names). Never present on the server or client.
* ``root-ca``   - offline TLS trust anchor (self-signed CA) that issues the issuer.
* ``issuer``    - online (server). An intermediate CA (``path_length=0``) that signs
  short-lived TLS leaves strictly for the delegated target. It cannot change group
  membership, revoke a server, sign group trust, or mint device credentials.
* ``recovery``  - offline. Single-use emergency grants; separate from the root.
* ``update``    - separate Ed25519 key (the existing stage7 updater key); never
  reused for trust, TLS or device-credential purposes.

A valid TLS certificate alone grants transport confidentiality/authentication of
the server to the client; it grants no group membership and no publishing or
administration authority. Device credentials grant only ``read_assignment`` /
``submit_receipt``. See :mod:`kiosk.trust.roles` and :mod:`kiosk.trust.lifecycle`.
"""
from __future__ import annotations

from kiosk.trust.crypto import (
    ALGORITHM,
    TRUST_DOMAIN,
    generate_private_key,
    key_id,
    public_pem,
    sign,
    spki_der,
    verify,
)

__all__ = [
    "ALGORITHM",
    "TRUST_DOMAIN",
    "generate_private_key",
    "key_id",
    "public_pem",
    "sign",
    "spki_der",
    "verify",
]
