"""Trust-lifecycle pilot: role separation, delegated-boundary issuance, credential renewal.

Covers: key-role disjointness, delegation scope and target binding (origin/name
expansion refusal), constrained TLS issuance (chain + issuer bounds), generation
monotonicity, revocation, expired/backward-clock refusal, tampered-delegation
refusal, interrupted-write recovery, recovery-grant replay, and device-credential
renewal (valid/idempotent, revoked, expired, trust-expired, backward-clock,
unknown-secret, HTTP route).
"""
import base64
import json
import secrets
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from cryptography import x509

from kiosk.delivery.protocol import DeliveryError, PROFILE, encode, sha
from kiosk.delivery.state import DeliveryState
from kiosk.publication.exporter import PackageError
from kiosk.trust.crypto import (
    ALGORITHM,
    cert_not_after_utc,
    issue_intermediate_ca,
    issue_root_ca,
    key_id,
    leaf_spki_sha256,
    load_private,
    private_pem,
    sign,
    spki_der,
)
from kiosk.trust.lifecycle import OnlineIssuer
from kiosk.trust.roles import (
    Delegation,
    RoleError,
    check_key_role_disjointness,
    make_delegation,
    sign_delegation,
    validate_delegation_scope,
)
from kiosk.trust.state import LifecycleError, LifecycleState

NOW = 1_800_000_000
ORIGIN = "https://192.168.1.165:8443"


def _fresh_pem():
    return private_pem(__import__("kiosk.trust.crypto", fromlist=["generate_private_key"]).generate_private_key())


class _Crypto:
    """In-process root/intermediate/delegation fixture (no files, no private-key leaks)."""

    def __init__(self, *, group_id="lab-group", server_id="lab-server", max_tls_days=7,
                 origin=ORIGIN, permitted_ip=("192.168.1.165",), permitted_dns=("localhost",),
                 delegation_days=30):
        self.base = int(time.time())
        self.group_id = group_id
        self.server_id = server_id
        self.origin = origin
        self.permitted_ip = permitted_ip
        self.permitted_dns = permitted_dns
        self.root_ca_pem, self.root_ca_key_pem = issue_root_ca("root", validity_days=730, now=self.base)
        self.intermediate_pem, self.intermediate_key_pem = issue_intermediate_ca(
            "issuer", self.root_ca_pem, self.root_ca_key_pem, validity_days=90, now=self.base,
        )
        self.group_key_pem = _fresh_pem()
        self.recovery_key_pem = _fresh_pem()
        self.issuer_key_id = key_id(load_private(self.intermediate_key_pem))
        self.delegation = make_delegation(
            group_id=group_id, server_id=server_id, origin=origin,
            permitted_ip=list(permitted_ip), permitted_dns=list(permitted_dns),
            issuer_key_id=self.issuer_key_id,
            issuer_spki_base64=base64.b64encode(spki_der(load_private(self.intermediate_key_pem))).decode("ascii"),
            max_tls_validity_days=max_tls_days, issued_at=self.base - 100,
            expires_at=self.base + delegation_days * 86400,
        )
        self.delegation_sig = sign_delegation(self.group_key_pem, self.delegation)
        self.root_spki = spki_der(load_private(self.group_key_pem))

    def issuer(self, state):
        return OnlineIssuer(state, self.root_spki, self.delegation, self.delegation_sig)

    def role_ids(self):
        return {
            "root": key_id(load_private(self.group_key_pem)),
            "issuer": self.issuer_key_id,
            "recovery": key_id(load_private(self.recovery_key_pem)),
            "update": "ed25519-update-key-is-separate-and-never-reused",
        }


def _leaf_sans(leaf_pem):
    import ipaddress

    cert = x509.load_pem_x509_certificate(leaf_pem.encode("ascii"))
    ext = cert.extensions.get_extension_for_class(x509.SubjectAlternativeName)
    names = set()
    for item in ext.value:
        if isinstance(item.value, ipaddress.IPv4Address):
            names.add("ip:" + str(item.value))
        elif isinstance(item.value, str):
            names.add("dns:" + item.value)
    return names


class RoleTests(unittest.TestCase):
    def setUp(self):
        self.c = _Crypto()

    def test_key_role_disjointness_refuses_shared_key(self):
        ids = self.c.role_ids()
        ids["recovery"] = ids["root"]
        with self.assertRaises(RoleError):
            check_key_role_disjointness(ids)

    def test_key_role_disjointness_accepts_distinct(self):
        check_key_role_disjointness(self.c.role_ids())

    def test_delegation_scope_refuses_non_issuer_scope(self):
        with self.assertRaises(RoleError):
            validate_delegation_scope(["sign_group_trust"], max_tls_days=7)

    def test_delegation_scope_bounds_tls_validity(self):
        with self.assertRaises(RoleError):
            validate_delegation_scope(["issue_tls_leaf"], max_tls_days=31)
        self.assertEqual(validate_delegation_scope(["issue_tls_leaf"], max_tls_days=30), ("issue_tls_leaf",))

    def test_delegation_origin_host_must_be_permitted(self):
        with self.assertRaises(RoleError):
            make_delegation(group_id="g", server_id="s", origin="https://10.9.9.9:8443",
                            permitted_ip=["192.168.1.165"], permitted_dns=[], issuer_key_id="0" * 64,
                            issuer_spki_base64="x", max_tls_validity_days=7, issued_at=1, expires_at=2)

    def test_delegation_refuses_reserved_or_wildcard_names(self):
        with self.assertRaises(RoleError):
            make_delegation(group_id="g", server_id="s", origin=ORIGIN,
                            permitted_ip=["127.0.0.1"], permitted_dns=[], issuer_key_id="0" * 64,
                            issuer_spki_base64="x", max_tls_validity_days=7, issued_at=1, expires_at=2)
        with self.assertRaises(RoleError):
            make_delegation(group_id="g", server_id="s", origin=ORIGIN,
                            permitted_ip=["192.168.1.165"], permitted_dns=["*.example.com"],
                            issuer_key_id="0" * 64, issuer_spki_base64="x",
                            max_tls_validity_days=7, issued_at=1, expires_at=2)


class IssuanceTests(unittest.TestCase):
    def setUp(self):
        self.c = _Crypto(max_tls_days=7)
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.state = LifecycleState(Path(self.tmp.name) / "state", clock=lambda: self.c.base)

    def _issue(self, now=None, **overrides):
        issuer = self.c.issuer(self.state)
        if now is None:
            now = self.c.base
        return issuer.renew_tls_leaf(
            self.c.intermediate_pem, self.c.intermediate_key_pem,
            validity_days=overrides.pop("days", 7), now=now, **overrides,
        )

    def test_issue_tls_leaf_and_verify_chain(self):
        result = self._issue()
        self.assertEqual(result["generation"], 1)
        self.assertEqual(self.state.current_tls()["spki_sha256"], result["tls_spki_sha256"])
        self.assertEqual(leaf_spki_sha256(result["leaf_pem"]), result["tls_spki_sha256"])
        blocks = [b for b in result["chain_pem"].split("-----BEGIN CERTIFICATE-----") if b.strip()]
        self.assertEqual(len(blocks), 2)
        self.assertTrue(result["not_after"] > result["not_before"])

    def test_leaf_is_bound_to_delegated_target_and_names(self):
        result = self._issue()
        # The leaf CN is the delegated server_id, and its SAN is exactly the
        # delegation's permitted names (no expansion).
        cert = x509.load_pem_x509_certificate(result["leaf_pem"].encode("ascii"))
        cn = cert.subject.get_attributes_for_oid(x509.NameOID.COMMON_NAME)[0].value
        self.assertEqual(cn, self.c.server_id)
        expected = {"ip:192.168.1.165", "dns:localhost"}
        self.assertEqual(_leaf_sans(result["leaf_pem"]), expected)

    def test_issuer_cannot_mint_for_another_server_or_group(self):
        # A different delegation (root-signed for a different server/group) has a
        # signature that does not verify against this delegation's payload; the
        # issuer is bound to its own server_id and mints only that CN.
        other = _Crypto(server_id="other-server", group_id="other-group")
        result = self._issue()
        self.assertEqual(result["server_id"], self.c.server_id)
        self.assertNotEqual(self.c.server_id, other.server_id)

    def test_issue_tls_exceeding_delegation_refused(self):
        with self.assertRaisesRegex(ValueError, "tls_validity_exceeds_delegation"):
            self._issue(days=8)

    def test_issue_tls_wrong_issuer_key_refused(self):
        other = _Crypto().intermediate_key_pem
        issuer = self.c.issuer(self.state)
        with self.assertRaisesRegex(ValueError, "issuer_key_mismatch"):
            issuer.renew_tls_leaf(self.c.intermediate_pem, other, validity_days=7, now=self.c.base)

    def test_issue_tls_revoked_server_refused(self):
        self.state.revoke(self.c.server_id, "test")
        with self.assertRaisesRegex(ValueError, "server_revoked"):
            self._issue()

    def test_issue_tls_expired_delegation_refused(self):
        with self.assertRaisesRegex(ValueError, "delegation_expired"):
            self._issue(now=self.c.base + 31 * 86400)

    def test_issue_tls_backward_time_refused(self):
        self._issue(now=self.c.base)
        with self.assertRaisesRegex(ValueError, "time_backward"):
            self._issue(now=self.c.base - 50)

    def test_issue_tls_generation_monotonic(self):
        first = self._issue(now=self.c.base)
        second = self._issue(now=self.c.base + 10)
        self.assertEqual(second["generation"], first["generation"] + 1)
        self.assertNotEqual(first["tls_spki_sha256"], second["tls_spki_sha256"])

    def test_issue_tls_leaf_outliving_delegation_refused(self):
        # delegation expires at base + 1 day; a 7-day leaf would outlive it.
        short = _Crypto(delegation_days=1)
        with tempfile.TemporaryDirectory() as tmp:
            state = LifecycleState(Path(tmp) / "state", clock=lambda: short.base)
            issuer = short.issuer(state)
            with self.assertRaisesRegex(ValueError, "leaf_would_outlive_issuer_or_delegation"):
                issuer.renew_tls_leaf(short.intermediate_pem, short.intermediate_key_pem,
                                      validity_days=7, now=short.base)

    def test_delegation_signature_tamper_refused(self):
        tampered = Delegation(
            version=1, group_id=self.c.group_id, server_id=self.c.server_id, origin=self.c.origin,
            permitted_ip=self.c.permitted_ip, permitted_dns=self.c.permitted_dns,
            issuer_key_id=self.c.issuer_key_id,
            issuer_spki_base64=self.c.delegation.issuer_spki_base64,
            scopes=("issue_tls_leaf",), max_tls_validity_days=7,
            issued_at=self.c.base - 100, expires_at=self.c.base + 86400 * 365,
        )
        issuer = OnlineIssuer(self.state, self.c.root_spki, tampered, self.c.delegation_sig)
        with self.assertRaises(ValueError):
            issuer.renew_tls_leaf(self.c.intermediate_pem, self.c.intermediate_key_pem,
                                  validity_days=7, now=self.c.base)

    def test_interrupted_tls_issue_rolls_back(self):
        with self.assertRaises(LifecycleError):
            self._issue(fail_at="after_tls")
        self.assertIsNone(self.state.current_tls())


class ActivationTests(unittest.TestCase):
    def setUp(self):
        self.c = _Crypto(max_tls_days=7)
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.state = LifecycleState(Path(self.tmp.name) / "state", clock=lambda: self.c.base)

    def test_activate_monotonic_and_rollback_refused(self):
        issuer = self.c.issuer(self.state)
        first = issuer.renew_tls_leaf(self.c.intermediate_pem, self.c.intermediate_key_pem,
                                      validity_days=7, now=self.c.base)
        second = issuer.renew_tls_leaf(self.c.intermediate_pem, self.c.intermediate_key_pem,
                                       validity_days=7, now=self.c.base + 10)
        self.assertIsNone(self.state.serving_generation())
        issuer.activate(second["generation"], self.c.base + 10)
        self.assertEqual(self.state.serving_generation(), second["generation"])
        with self.assertRaisesRegex(LifecycleError, "activation_rollback"):
            issuer.activate(first["generation"], now=self.c.base + 20)

    def test_activate_interrupted_rolls_back(self):
        issuer = self.c.issuer(self.state)
        result = issuer.renew_tls_leaf(self.c.intermediate_pem, self.c.intermediate_key_pem,
                                       validity_days=7, now=self.c.base)
        with self.assertRaises(LifecycleError):
            self.state.activate(result["generation"], now=self.c.base, fail_at="after_activate")
        self.assertIsNone(self.state.serving_generation())


class RecoveryStateTests(unittest.TestCase):
    def test_time_floor_never_decreases(self):
        with tempfile.TemporaryDirectory() as tmp:
            state = LifecycleState(Path(tmp))
            self.assertEqual(state.time_floor(), 0)
            state.revoke("server-1", "test")
            self.assertGreater(state.time_floor(), 0)

    def test_recovery_grant_replay_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            state = LifecycleState(Path(tmp))
            state.consume_grant("grant-1")
            with self.assertRaises(LifecycleError):
                state.consume_grant("grant-1")


class RenewalTests(unittest.TestCase):
    """Automatic device-credential renewal without re-enrollment (DeliveryState.renew)."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.now = NOW
        self.state = DeliveryState(Path(self.tmp.name) / "delivery", clock=lambda: self.now)
        trust_payload = {"version": 1, "group_id": "lab-group", "generation": 1,
                         "issued_at": NOW - 100, "expires_at": NOW + 30 * 86400, "servers": []}
        self.config = {
            "version": 1, "group_id": "lab-group", "server_id": "lab-server",
            "origin": "https://localhost:8443",
            "bootstrap": {},
            "trust": {"version": 1, "key_id": "0" * 64, "algorithm": ALGORITHM,
                      "payload_base64": base64.b64encode(encode(trust_payload)).decode("ascii"),
                      "signature_base64": ""},
        }
        (self.state.root / "public.json").write_bytes(encode(self.config))
        self.secret = secrets.token_hex(32)
        self.binding = {"version": 1, "request_id": secrets.token_hex(16), "device_id": "phone-1",
                        "group_id": "lab-group", "profile": PROFILE, "origin": self.config["origin"],
                        "nonce": secrets.token_hex(16), "secret_verifier": sha(bytes.fromhex(self.secret))}

    def _enroll(self):
        pending = self.state.begin(self.binding)
        self.state.approve(self.binding["request_id"], {
            "user_code": pending["user_code"], "binding_sha256": sha(encode(self.binding)),
            "decision": "approve"})
        return self.state.authenticate(self.secret)

    def test_renewal_extends_expiry_idempotently(self):
        device = self._enroll()
        original_expiry = device["expires"]
        self.now = original_expiry - 100
        renewed = self.state.renew(self.secret)
        self.assertEqual(renewed["state"], "renewed")
        self.assertEqual(renewed["credential_id"], device["credential_id"])
        self.assertGreater(renewed["expires_at"], original_expiry)
        again = self.state.renew(self.secret)
        self.assertEqual(again["credential_id"], renewed["credential_id"])
        with self.state.connection() as db:
            count = db.execute("SELECT count(*) FROM devices").fetchone()[0]
        self.assertEqual(count, 1)

    def test_renewal_revoked_refused(self):
        self._enroll()
        self.state.revoke("phone-1")
        with self.assertRaisesRegex(DeliveryError, "invalid_credential"):
            self.state.renew(self.secret)

    def test_renewal_expired_refused_no_silent_grace(self):
        self._enroll()
        # An expired credential is never silently extended.
        self.now += 7 * 86400 + 60
        with self.assertRaisesRegex(DeliveryError, "credential_expired"):
            self.state.renew(self.secret)

    def test_renewal_trust_expired_refused(self):
        self._enroll()
        trust_payload = {"version": 1, "group_id": "lab-group", "generation": 1,
                         "issued_at": NOW - 100, "expires_at": NOW + 2 * 86400, "servers": []}
        self.config["trust"]["payload_base64"] = base64.b64encode(encode(trust_payload)).decode("ascii")
        (self.state.root / "public.json").write_bytes(encode(self.config))
        self.now = NOW + 2 * 86400 + 100
        with self.assertRaisesRegex(DeliveryError, "admission_authority_expired"):
            self.state.renew(self.secret)

    def test_renewal_backward_time_refused(self):
        self._enroll()
        self.state.renew(self.secret)
        self.now -= 100
        with self.assertRaisesRegex(DeliveryError, "uncertain_time"):
            self.state.renew(self.secret)

    def test_renewal_unknown_secret_refused(self):
        self._enroll()
        with self.assertRaisesRegex(DeliveryError, "invalid_credential"):
            self.state.renew(secrets.token_hex(32))

    def _app(self):
        from kiosk.app import create_app

        base = Path(self.tmp.name) / "app"
        app = create_app({"TESTING": True, "SECRET_KEY": "disposable-test-key",
                          "INSTANCE_DIR": base / "instance", "DATABASE_PATH": base / "instance/kiosk.sqlite",
                          "PRIVATE_UPLOAD_DIR": base / "private", "PUBLIC_UPLOAD_DIR": base / "public",
                          "STATIC_FOLDER": base / "static", "DEVICE_DELIVERY_ROOT": self.state.root})
        app.extensions["device_delivery"] = self.state
        return app

    def test_http_renewal_route(self):
        origin = self.config["origin"]
        self._enroll()
        self.now = NOW + 7 * 86400 - 100
        client = self._app().test_client()
        self.assertEqual(client.post("/api/v2/device/renew", json={}, base_url=origin).status_code, 401)
        response = client.post("/api/v2/device/renew", json={}, base_url=origin,
                               headers={"Authorization": "Bearer " + self.secret})
        self.assertEqual(response.status_code, 200)
        body = response.get_json()
        self.assertEqual(body["state"], "renewed")
        self.assertEqual(body["device_id"], "phone-1")
        self.assertGreater(body["expires_at"], NOW + 7 * 86400 - 100)


class ClientTrustContinuityTests(unittest.TestCase):
    """The native client accepts a legitimate new TLS issuer pin and keeps strict
    validation + signed rollback protection (Windows CNG verification)."""

    def setUp(self):
        from kiosk.display.delivery_authority import PrivateState

        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.now = int(time.time())
        self.clock = patch('kiosk.display.delivery_authority.time.time', return_value=self.now)
        self.clock.start()
        self.addCleanup(self.clock.stop)
        group_key_pem = _fresh_pem()
        group_key = load_private(group_key_pem)
        self.group_spki = spki_der(group_key)
        self.group_key_id = key_id(group_key)
        self.group_key_pem = group_key_pem
        self.server_id = "server-1"
        self.origin = ORIGIN
        self.state = PrivateState(self.root)
        self.state.data['bootstrap'] = {
            'version': 1, 'bootstrap_id': 'b', 'group_id': 'lab-group', 'server_id': self.server_id,
            'origin': self.origin, 'tls_ca_pem': 'x', 'group_key_id': self.group_key_id,
            'group_spki_base64': base64.b64encode(self.group_spki).decode('ascii'),
            'issued_at': self.now - 60, 'expires_at': self.now + 86400,
        }
        self.state.confirm_time(self.now)

    def _envelope(self, *, issuer_pin=None, leaf_pin=None):
        version = 2 if issuer_pin is not None else 1
        payload = {'version': version, 'group_id': 'lab-group', 'generation': 1,
                   'issued_at': self.now - 60, 'expires_at': self.now + 86400,
                   'servers': [{'server_id': self.server_id, 'origin': self.origin, 'roles': ['publisher']}]}
        if issuer_pin is not None:
            payload['servers'][0]['tls_issuer_spki_sha256'] = issuer_pin
        else:
            payload['servers'][0]['tls_spki_sha256'] = leaf_pin
        raw = json.dumps(payload, sort_keys=True, separators=(',', ':')).encode('ascii')
        sig = sign(load_private(self.group_key_pem), ("Kiosk/GroupTrust/v%d\0" % version).encode(), raw)
        return {'version': version, 'key_id': self.group_key_id, 'algorithm': 'RSA3072-SHA256-PKCS1-v1_5',
                'payload_base64': base64.b64encode(raw).decode('ascii'),
                'signature_base64': base64.b64encode(sig).decode('ascii')}

    def test_accepts_issuer_pin_and_stores_kind(self):
        issuer_pin = 'a' * 64
        self.state.verify_trust(self._envelope(issuer_pin=issuer_pin), 'b' * 64, issuer_pin)
        self.assertEqual(self.state.data['trust']['pin_kind'], 'issuer')
        self.assertEqual(self.state.data['trust']['tls_pin'], issuer_pin)

    def test_issuer_pin_cannot_be_smuggled_into_v1(self):
        envelope = self._envelope(issuer_pin='a' * 64)
        envelope['version'] = 1
        with self.assertRaises(ValueError):
            self.state.verify_trust(envelope, 'b' * 64, 'a' * 64)

    def test_rejects_mismatched_issuer_pin(self):
        with self.assertRaises(PackageError):
            self.state.verify_trust(self._envelope(issuer_pin='a' * 64), 'b' * 64, 'c' * 64)

    def test_leaf_pin_legacy_path_still_enforced(self):
        leaf_pin = 'd' * 64
        self.state.verify_trust(self._envelope(leaf_pin=leaf_pin), leaf_pin)
        self.assertEqual(self.state.data['trust']['pin_kind'], 'leaf')
        with self.assertRaises(PackageError):
            self.state.verify_trust(self._envelope(leaf_pin=leaf_pin), 'e' * 64)


class ClientRecoveryTests(unittest.TestCase):
    """The Windows client uses the server's own fixed refusal label, never a guess."""

    def _client(self, expires_at):
        from unittest.mock import Mock

        from kiosk.display.delivery_client import Client

        client = Client.__new__(Client)
        client.native = Mock()
        client.native.data = {'credential': {'expires_at': expires_at}}
        client.native.now.return_value = 200
        return client

    def test_expired_credential_is_recorded_as_expiry_not_revocation(self):
        client = self._client(100)  # expired at now=200
        client._record_refusal(PackageError('credential_expired'))
        self.assertNotIn('revoked', client.native.data)
        self.assertEqual('expired', client.native.data['recovery']['state'])
        self.assertEqual('credential_expired', client.native.data['recovery']['code'])

    def test_server_revocation_is_a_durable_recovery_state(self):
        client = self._client(300)  # still valid at now=200
        client._record_refusal(PackageError('invalid_credential'))
        self.assertTrue(client.native.data['revoked'])
        self.assertEqual('revoked_or_replaced', client.native.data['recovery']['state'])

    def test_expired_signed_authority_is_distinct_and_recoverable(self):
        client = self._client(300)
        client._record_refusal(PackageError('admission_authority_expired'))
        self.assertNotIn('revoked', client.native.data)
        self.assertEqual('authority_expired', client.native.data['recovery']['state'])

    def test_unknown_401_reason_is_not_invented(self):
        client = self._client(300)
        client._record_refusal(PackageError('native_http_refused'))
        self.assertNotIn('recovery', client.native.data)
        self.assertNotIn('revoked', client.native.data)
        client.native.save.assert_not_called()

    def test_refusal_state_helper_returns_only_known_states(self):
        client = self._client(300)
        client.native.data['recovery'] = {'state': 'unknown_value', 'code': 'x'}
        self.assertIsNone(client.recovery())
        client.native.data['recovery'] = {'state': 'authority_expired', 'code': 'admission_authority_expired'}
        self.assertEqual('authority_expired', client.recovery()['state'])


class RefusalTransportTests(unittest.TestCase):
    """Only the server's exact guarded error object becomes a client reason."""

    @staticmethod
    def _response(payload):
        import io

        class Response(io.BytesIO):
            def __init__(self, value):
                super().__init__(value)

        return Response(payload)

    def test_exact_fixed_error_is_extracted(self):
        from kiosk.display.delivery_transport import refusal_reason

        self.assertEqual('credential_expired',
                         refusal_reason(self._response(b'{"version":1,"error":"credential_expired"}')))
        self.assertEqual('invalid_credential',
                         refusal_reason(self._response(b'{"version":1,"error":"invalid_credential"}')))

    def test_free_text_or_extra_fields_are_not_used(self):
        from kiosk.display.delivery_transport import refusal_reason

        for body in (b'', b'not json', b'{"version":1,"error":"Credential expired"}',
                     b'{"version":1,"error":"x","detail":"leak"}', b'{"version":2,"error":"x"}',
                     b'{"error":"x"}', b'{"version":1,"error":"a/b"}'):
            self.assertIsNone(refusal_reason(self._response(body)), body)

    def test_ui_status_uses_reason_before_http_status(self):
        from kiosk.display.connect import error_status
        from kiosk.display.delivery_transport import TransportError

        self.assertEqual('expired', error_status(TransportError('credential_expired', 401)))
        self.assertEqual('access_refused', error_status(TransportError('invalid_credential', 401)))
        self.assertEqual('authority_expired', error_status(TransportError('admission_authority_expired', 403)))
        self.assertEqual('access_refused', error_status(TransportError('native_http_refused', 401)))


if __name__ == "__main__":
    unittest.main()
