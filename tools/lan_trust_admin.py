"""LAN trust-lifecycle administration: offline root, constrained online issuer, supervised TLS renewal.

This is the supported setup and maintenance flow for the isolated pilot. It
separates five authorities — the offline root CA, the offline group root (signs
group trust + delegation), the online issuer (intermediate CA), the offline recovery
key and the separate stage7 update key — and gives the online server only the
intermediate CA key plus a root-signed delegation binding it to one server, one
origin and a fixed set of permitted TLS names.

Commands
--------
    init          create a fresh installation (offline root + issuer + delegation +
                  group trust envelope + bootstrap + first serving leaf + Caddyfile)
    renew-serve   issue a new serving leaf through the constrained issuer, activate
                  it, and write the new serving certificate/key (then reload Caddy)
    status        show roles, serving generation, time floor and delegation

Key custody: every long-lived private key is serialised with ``BestAvailableEncryption``
(PBKDF2 + a maintained cipher) using the operator password supplied via ``--password``,
``--password-file`` or ``KIOSK_TRUST_PASSWORD``. Only the short-lived serving leaf key
is unencrypted, because the TLS engine must load it. The offline root/group/recovery
keys live only under ``admin-private/`` (ACL-restricted to the current user) and are
never written to the server directory or any public artifact.
"""
from __future__ import annotations

import argparse
import base64
import ipaddress
import json
import os
import secrets
import subprocess
import sys
import time
import uuid
from pathlib import Path

from kiosk.trust.crypto import (
    ALGORITHM,
    cert_chain,
    cert_not_after_utc,
    generate_private_key,
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
    check_key_role_disjointness,
    make_delegation,
    sign_delegation,
)
from kiosk.trust.state import LifecycleState

SCHEMA = "lan-trust-lifecycle-v2"
GROUP_TRUST_DOMAIN = b"Kiosk/GroupTrust/v2\0"
UPDATE_ROLE_ID = "ed25519-update-key-is-separate-and-never-reused"


class AdminError(ValueError):
    pass


def _now():
    return int(time.time())


def _password(args):
    if getattr(args, "password", None):
        return args.password
    if getattr(args, "password_file", None):
        value = Path(args.password_file).read_text(encoding="utf-8").strip()
        if not value:
            raise AdminError("The password file is empty.")
        return value
    value = os.environ.get("KIOSK_TRUST_PASSWORD")
    if not value:
        raise AdminError("Provide --password, --password-file or KIOSK_TRUST_PASSWORD.")
    return value


def _ip(value):
    try:
        address = ipaddress.IPv4Address(value)
    except ipaddress.AddressValueError as error:
        raise AdminError("Use a unicast IPv4 address.") from error
    if address.is_unspecified or address.is_multicast or address.is_reserved:
        raise AdminError("Use a unicast IPv4 address.")
    return str(address)


def _write_new(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        raise AdminError("Refusing to overwrite existing material at " + str(path) + ".")
    with path.open("x", encoding="utf-8", newline="\n") as stream:
        stream.write(value)
        stream.flush()


def _write_json_new(path, value):
    _write_new(path, json.dumps(value, indent=2) + "\n")


def _atomic_replace(path, value):
    import tempfile

    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix=".tls-", dir=path.parent)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as stream:
            stream.write(value)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        Path(temporary).unlink(missing_ok=True)


def _restrict_acl(path):
    """Restrict a directory to the current user (offline custody). Fail closed on Windows."""
    if os.name != "nt":
        return
    user = subprocess.run(["whoami"], capture_output=True, text=True, check=False).stdout.strip() or None
    if not user:
        raise AdminError("Cannot determine custody identity")
    subprocess.run(
        ["icacls", str(Path(path)), "/inheritance:r", "/grant:r", user + ":(OI)(CI)F", "/q"],
        capture_output=True, check=True,
    )


def _group_trust_envelope(group_key_pem, password, group_id, server_id, origin,
                          issuer_spki_sha256, issued_at, expires_at):
    group_key = load_private(group_key_pem, password)
    payload = {"version": 2, "group_id": group_id, "generation": 1,
               "issued_at": issued_at, "expires_at": expires_at,
               "servers": [{"server_id": server_id, "origin": origin,
                            "tls_issuer_spki_sha256": issuer_spki_sha256, "roles": ["publisher"]}]}
    payload_bytes = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("ascii")
    signature = sign(group_key, GROUP_TRUST_DOMAIN, payload_bytes)
    return {
        "version": 2,
        "key_id": key_id(group_key),
        "algorithm": ALGORITHM,
        "payload_base64": base64.b64encode(payload_bytes).decode("ascii"),
        "signature_base64": base64.b64encode(signature).decode("ascii"),
    }


def _bootstrap(group_id, server_id, origin, tls_ca_pem, group_key_pem, password, issued_at, expires_at):
    group_key = load_private(group_key_pem, password)
    return {
        "version": 1, "bootstrap_id": str(uuid.uuid4()), "group_id": group_id, "server_id": server_id,
        "origin": origin, "tls_ca_pem": tls_ca_pem, "group_key_id": key_id(group_key),
        "group_spki_base64": base64.b64encode(spki_der(group_key)).decode("ascii"),
        "issued_at": issued_at, "expires_at": expires_at,
    }


def _caddyfile(origin, address, backend_port, cert_path, key_path, storage_path):
    portable = str(Path(storage_path)).replace("\\", "/")
    return (
        "{\n"
        "    admin off\n"
        "    persist_config off\n"
        "    auto_https off\n"
        "    storage file_system {\n"
        f"        root {portable}\n"
        "    }\n"
        "    servers {\n"
        "        protocols h1 h2\n"
        "    }\n"
        "}\n"
        f"{origin} {{\n"
        f"    bind {address} 127.0.0.1\n"
        f"    tls {cert_path} {key_path}\n"
        "    request_header -X-Forwarded-*\n"
        "    request_header -X-Real-IP\n"
        f"    reverse_proxy 127.0.0.1:{backend_port}\n"
        "}\n"
    )


def init(args):
    root = Path(args.root).absolute()
    if root.exists():
        raise AdminError("Use a new root; existing identities are never overwritten.")
    password = _password(args)
    address = _ip(args.address)
    group_id = args.group_id or str(uuid.uuid4())
    server_id = args.server_id or str(uuid.uuid4())
    origin = "https://" + address + ":" + str(args.port)
    root.mkdir(parents=True)
    _restrict_acl(root)
    online_password = secrets.token_urlsafe(48)

    now = _now()
    # Offline root CA -> online intermediate (issuer) -> serving leaf.
    root_ca_pem, root_ca_key_pem = issue_root_ca("Kiosk offline root CA", validity_days=730, password=password, now=now)
    intermediate_pem, intermediate_key_pem = issue_intermediate_ca(
        "Kiosk online issuer", root_ca_pem, root_ca_key_pem, validity_days=args.issuer_days,
        password=password, root_key_password=password, now=now,
    )
    # Offline signing keys (group root + recovery); encrypted, never leave admin-private.
    group_private_pem = private_pem(generate_private_key(), password)
    recovery_private_pem = private_pem(generate_private_key(), password)
    issuer_key_id = key_id(load_private(intermediate_key_pem, password))

    role_ids = {
        "root": key_id(load_private(group_private_pem, password)),
        "issuer": issuer_key_id,
        "recovery": key_id(load_private(recovery_private_pem, password)),
        "update": UPDATE_ROLE_ID,
    }
    check_key_role_disjointness(role_ids)

    delegation = make_delegation(
        group_id=group_id, server_id=server_id, origin=origin,
        permitted_ip=[address], permitted_dns=["localhost"],
        issuer_key_id=issuer_key_id,
        issuer_spki_base64=base64.b64encode(spki_der(load_private(intermediate_key_pem, password))).decode("ascii"),
        max_tls_validity_days=args.max_tls_days, issued_at=now,
        expires_at=now + args.delegation_days * 86400,
    )
    delegation_sig = sign_delegation(group_private_pem, delegation, password=password)

    # Issue + activate the first serving leaf through the constrained issuer.
    state = LifecycleState(root / "state")
    issuer = OnlineIssuer(state, spki_der(load_private(group_private_pem, password)), delegation, delegation_sig)
    result = issuer.renew_tls_leaf(
        intermediate_pem, intermediate_key_pem, validity_days=args.tls_days,
        now=now, intermediate_key_password=password,
    )

    trust_envelope = _group_trust_envelope(
        group_private_pem, password, group_id, server_id, origin,
        result["issuer_spki_sha256"], now, now + args.trust_days * 86400,
    )
    bootstrap = _bootstrap(
        group_id, server_id, origin, root_ca_pem, group_private_pem, password,
        now, now + args.bootstrap_days * 86400,
    )

    # Offline custody (root CA, group root, recovery) — encrypted + ACL-restricted.
    _write_new(root / "admin-private/root-ca-key.pem", root_ca_key_pem)
    _write_new(root / "admin-private/group-key.pem", group_private_pem)
    _write_new(root / "admin-private/recovery-key.pem", recovery_private_pem)
    _restrict_acl(root / "admin-private")
    # Only a DPAPI-bound online unlock secret is deployed; offline passwords are not.
    from kiosk.display.native_crypto import protect
    (root / "server").mkdir(exist_ok=True)
    (root / "server/online-unlock.dpapi").write_bytes(protect(online_password.encode("utf-8")))
    intermediate_key_pem = private_pem(load_private(intermediate_key_pem, password), online_password)
    # Online server material: intermediate (encrypted) + delegation + serving leaf.
    _write_new(root / "server/intermediate.pem", intermediate_pem)
    _write_new(root / "server/intermediate-key.pem", intermediate_key_pem)
    _write_json_new(root / "server/delegation.json", {
        "schema": SCHEMA, "algorithm": ALGORITHM,
        "group_id": group_id, "server_id": server_id, "origin": origin,
        "permitted_ip": list(delegation.permitted_ip), "permitted_dns": list(delegation.permitted_dns),
        "issuer_key_id": delegation.issuer_key_id, "issuer_spki_base64": delegation.issuer_spki_base64,
        "scopes": list(delegation.scopes), "max_tls_validity_days": delegation.max_tls_validity_days,
        "issued_at": delegation.issued_at, "expires_at": delegation.expires_at,
        "signature_base64": base64.b64encode(delegation_sig).decode("ascii"),
    })
    _write_new(root / "server/tls-cert.pem", result["chain_pem"])
    _write_new(root / "server/tls-key.pem", result["leaf_key_pem"])
    _write_json_new(root / "server/public.json", {
        "version": 1, "group_id": group_id, "server_id": server_id, "origin": origin,
        "bootstrap": bootstrap, "trust": trust_envelope,
    })
    # Public verification material only (no private keys, no passwords).
    _write_new(root / "public/root-ca.pem", root_ca_pem)
    _write_new(root / "public/intermediate.pem", intermediate_pem)
    _write_new(root / "public/bootstrap.json", json.dumps(bootstrap, indent=2) + "\n")
    _write_new(root / "public/trust.json", json.dumps(trust_envelope, indent=2) + "\n")
    _write_new(root / "public/lab-ca.pem", root_ca_pem)
    _write_json_new(root / "public/manifest.json", {
        "schema": SCHEMA, "group_id": group_id, "server_id": server_id,
        "address": address, "port": args.port, "roles": role_ids, "algorithm": ALGORITHM,
        "group_spki_base64": bootstrap["group_spki_base64"],
        "tls_issuer_spki_sha256": result["issuer_spki_sha256"],
        "serving": {"generation": result["generation"], "tls_spki_sha256": result["tls_spki_sha256"],
                    "not_before": result["not_before"], "not_after": result["not_after"]},
    })
    cert_path = str((root / "server/tls-cert.pem").as_posix())
    key_path = str((root / "server/tls-key.pem").as_posix())
    _write_new(root / "Caddyfile", _caddyfile(origin, address, args.backend_port, cert_path, key_path,
                                              root / "caddy-storage"))
    print(json.dumps({"status": "initialized", "root": str(root), "group_id": group_id,
                      "server_id": server_id, "origin": origin, "roles": role_ids,
                      "staged_generation": result["generation"],
                      "tls_issuer_spki_sha256": result["issuer_spki_sha256"]}))


def _load_server(root, password):
    if (Path(root) / "state/rebuild-incomplete.json").exists():
        raise AdminError("Interrupted rebuild: keep this tree offline, preserve diagnostics, and restore the verified backup to a fresh root before retrying.")
    manifest = json.loads((root / "public/manifest.json").read_text(encoding="utf-8"))
    server = json.loads((root / "server/delegation.json").read_text(encoding="utf-8"))
    delegation = make_delegation(
        group_id=server["group_id"], server_id=server["server_id"], origin=server["origin"],
        permitted_ip=server["permitted_ip"], permitted_dns=server["permitted_dns"],
        issuer_key_id=server["issuer_key_id"], issuer_spki_base64=server["issuer_spki_base64"],
        max_tls_validity_days=server["max_tls_validity_days"],
        issued_at=server["issued_at"], expires_at=server["expires_at"],
    )
    signature = base64.b64decode(server["signature_base64"])
    group_spki = base64.b64decode(manifest["group_spki_base64"], validate=True)
    return delegation, signature, group_spki, manifest


def renew_serve(args):
    # Serving changes require a running supervisor that owns the TLS process.
    root = Path(args.root).absolute()
    _atomic_replace(root / "server/renew.request", str(_now()))
    print(json.dumps({"status": "renewal_requested", "completion": "inspect supervisor-status.json"}))


def status(args):
    root = Path(args.root).absolute()
    manifest = json.loads((root / "public/manifest.json").read_text(encoding="utf-8"))
    state = LifecycleState(root / "state")
    serving = state.serving_tls()
    trust = _current_trust(root)
    print(json.dumps({
        "schema": SCHEMA, "group_id": manifest["group_id"], "server_id": manifest["server_id"],
        "roles": manifest["roles"], "time_floor": state.time_floor(),
        "serving_generation": state.serving_generation(),
        "serving_tls": serving,
        "delegation_expires_at": json.loads((root / "server/delegation.json").read_text(encoding="utf-8"))["expires_at"],
        "trust_generation": trust["generation"], "trust_issued_at": trust["issued_at"],
        "trust_expires_at": trust["expires_at"], "now": _now(),
        "next_action": ("reauthorize" if _now() >= trust["expires_at"] - 7 * 86400 else "none"),
    }, indent=2))


def _current_trust(root):
    """The currently served signed group trust payload (public.json is authoritative)."""
    public = root / "server/public.json"
    source = public if public.is_file() else root / "public/trust.json"
    value = json.loads(source.read_text(encoding="utf-8"))
    envelope = value["trust"] if "trust" in value else value
    return json.loads(base64.b64decode(envelope["payload_base64"]))


def _envelope(root):
    public = root / "server/public.json"
    source = public if public.is_file() else root / "public/trust.json"
    value = json.loads(source.read_text(encoding="utf-8"))
    return value["trust"] if "trust" in value else value


def backup(args):
    from kiosk.trust.recovery import create_backup

    root = Path(args.root).absolute()
    password = _password(args)
    bundle = create_backup(root, password)
    output = Path(args.output).absolute()
    _write_json_new(output, bundle)
    _restrict_acl(output.parent)
    print(json.dumps({"status": "backup_created", "output": str(output),
                      "format": bundle["format"], "group_id": bundle["manifest"]["group_id"],
                      "server_id": bundle["manifest"]["server_id"],
                      "group_key_id": bundle["manifest"]["group_key_id"],
                      "bytes": output.stat().st_size, "secrets": "encrypted; keep offline"}, indent=2))


def restore(args):
    from kiosk.trust.recovery import restore_bundle

    root = Path(args.root).absolute()
    if root.exists():
        raise AdminError("Restore requires a NEW root; existing material is never overwritten.")
    from kiosk.trust.recovery import MAX_BUNDLE_BYTES
    with Path(args.bundle).open("rb") as stream:
        raw = stream.read(MAX_BUNDLE_BYTES + 1)
    if len(raw) > MAX_BUNDLE_BYTES:
        raise AdminError("Recovery bundle exceeds the input limit.")
    bundle = json.loads(raw)
    password = _password(args)
    key_password = (Path(args.key_password_file).read_text(encoding="utf-8").strip()
                    if args.key_password_file else password)
    result = restore_bundle(bundle, root, password, extract_password=key_password)
    _restrict_acl(root / "admin-private")
    print(json.dumps(result, indent=2))


def reauthorize(args):
    from kiosk.trust.crypto import load_private
    from kiosk.trust.recovery import (group_trust_envelope, next_generation,
                                      trust_issuer_sha256, verify_envelope)

    root = Path(args.root).absolute()
    if not args.confirm:
        raise AdminError("Re-signing authority requires --confirm.")
    if (root / "restored.json").exists() and not getattr(args, "previous_authority_isolated", False):
        raise AdminError("Recovered signing requires --previous-authority-isolated after verified shutdown, startup disablement and key/snapshot quarantine of the old authority; a new directory is not fencing.")
    password = _password(args)
    now = _now()
    previous = _current_trust(root)
    window = next_generation(previous, now=now, trust_days=args.trust_days)
    group_key = load_private((root / "admin-private/group-key.pem").read_text(encoding="ascii"), password)
    bootstrap = json.loads((root / "public/bootstrap.json").read_text(encoding="utf-8"))
    if key_id(group_key) != bootstrap["group_key_id"]:
        raise AdminError("The loaded group key does not match the installed bootstrap.")
    envelope = group_trust_envelope(
        group_key, group_id=bootstrap["group_id"], server_id=bootstrap["server_id"],
        origin=bootstrap["origin"], issuer_spki_sha256=trust_issuer_sha256(_envelope(root)),
        generation=window["generation"], issued_at=window["issued_at"], expires_at=window["expires_at"],
    )
    verified = verify_envelope(envelope, group_key)
    if verified["generation"] != window["generation"] or verified["expires_at"] != window["expires_at"]:
        raise AdminError("Signed authority verification failed.")
    # Keep the previous envelope and the whole previous public.json as evidence.
    public = root / "server/public.json"
    if public.is_file():
        import shutil

        shutil.copy2(public, root / ("server/public-gen%d.json" % previous["generation"]))
        config = json.loads(public.read_text(encoding="utf-8"))
    else:
        # A restored root has no server directory material; build a complete
        # deployable public configuration from the restored bootstrap.
        config = {"version": 1, "group_id": bootstrap["group_id"],
                  "server_id": bootstrap["server_id"], "origin": bootstrap["origin"],
                  "bootstrap": bootstrap}
    config["trust"] = envelope
    _atomic_replace(public, json.dumps(config, indent=2) + "\n")
    _atomic_replace(root / ("public/trust-gen%d.json" % previous["generation"]),
                    (root / "public/trust.json").read_text(encoding="utf-8"))
    _atomic_replace(root / "public/trust.json", json.dumps(envelope, indent=2) + "\n")
    print(json.dumps({"status": "reauthorized", "generation": window["generation"],
                      "issued_at": window["issued_at"], "expires_at": window["expires_at"],
                      "group_id": bootstrap["group_id"], "server_id": bootstrap["server_id"],
                      "restart_required": "no; the server re-reads public.json per request"}, indent=2))


def rebuild_server(args):
    from kiosk.trust.crypto import load_private, private_pem, spki_der
    from kiosk.trust.recovery import group_trust_envelope, next_generation, verify_envelope

    root = Path(args.root).absolute()
    if not args.confirm:
        raise AdminError("Rebuilding a server identity requires --confirm.")
    if not (root / "restored.json").is_file():
        raise AdminError("Run restore first; rebuilding only from restored offline material is supported.")
    if not getattr(args, "previous_authority_isolated", False):
        raise AdminError("Rebuild requires --previous-authority-isolated after verified shutdown, startup disablement and key/snapshot quarantine of the old authority; this operator attestation is not automatic fencing.")
    for name in ("intermediate.pem", "intermediate-key.pem", "tls-cert.pem", "tls-key.pem", "public.json"):
        if (root / "server" / name).exists():
            raise AdminError("Server material already exists; preserve it instead of rebuilding.")
    password = _password(args)
    online_password = Path(args.online_password_file).read_text(encoding="utf-8").strip()
    if not online_password:
        raise AdminError("The online key password file is empty.")
    now = _now()
    bootstrap = json.loads((root / "public/bootstrap.json").read_text(encoding="utf-8"))
    if args.address != bootstrap["origin"].split("://", 1)[1].rsplit(":", 1)[0]:
        raise AdminError("The rebuild address must equal the installed group/server origin host.")
    previous = _current_trust(root)
    old_manifest = json.loads((root / "public/manifest.json").read_text(encoding="utf-8"))
    root_ca_cert = (root / "public/root-ca.pem").read_text(encoding="ascii")
    root_ca_key = (root / "admin-private/root-ca-key.pem").read_text(encoding="ascii")
    group_key = load_private((root / "admin-private/group-key.pem").read_text(encoding="ascii"), password)
    intermediate_pem, intermediate_key_pem = issue_intermediate_ca(
        "Kiosk online issuer", root_ca_cert, root_ca_key, validity_days=args.issuer_days,
        password=online_password, root_key_password=password, now=now,
    )
    issuer_key_id = key_id(load_private(intermediate_key_pem, online_password))
    delegation = make_delegation(
        group_id=bootstrap["group_id"], server_id=bootstrap["server_id"], origin=bootstrap["origin"],
        permitted_ip=[args.address], permitted_dns=["localhost"],
        issuer_key_id=issuer_key_id,
        issuer_spki_base64=base64.b64encode(spki_der(load_private(intermediate_key_pem, online_password))).decode("ascii"),
        max_tls_validity_days=args.max_tls_days, issued_at=now,
        expires_at=now + args.delegation_days * 86400,
    )
    delegation_sig = sign_delegation((root / "admin-private/group-key.pem").read_text(encoding="ascii"),
                                     delegation, password=password)
    _write_json_new(root / "state/rebuild-incomplete.json", {
        "version": 1, "group_id": bootstrap["group_id"], "server_id": bootstrap["server_id"],
        "started_at": now, "status": "do_not_serve_until_complete"})
    delegation_key_path = root / "server/delegation.json"
    for name in ("delegation.json",):
        if (root / "server" / name).exists():
            (root / "server" / ("pre-rebuild-" + name)).write_text(
                (root / "server" / name).read_text(encoding="utf-8"), encoding="utf-8")
            (root / "server" / name).unlink()
    state = LifecycleState(root / "state")
    issuer = OnlineIssuer(state, spki_der(group_key), delegation, delegation_sig)
    result = issuer.renew_tls_leaf(intermediate_pem, intermediate_key_pem, validity_days=args.tls_days,
                                   now=now, intermediate_key_password=online_password)
    window = next_generation(previous, now=now, trust_days=args.trust_days)
    envelope = group_trust_envelope(
        group_key, group_id=bootstrap["group_id"], server_id=bootstrap["server_id"],
        origin=bootstrap["origin"], issuer_spki_sha256=result["issuer_spki_sha256"],
        generation=window["generation"], issued_at=window["issued_at"], expires_at=window["expires_at"],
    )
    verify_envelope(envelope, group_key)
    _write_new(delegation_key_path, json.dumps({
        "schema": SCHEMA, "algorithm": ALGORITHM,
        "group_id": delegation.group_id, "server_id": delegation.server_id, "origin": delegation.origin,
        "permitted_ip": list(delegation.permitted_ip), "permitted_dns": list(delegation.permitted_dns),
        "issuer_key_id": delegation.issuer_key_id, "issuer_spki_base64": delegation.issuer_spki_base64,
        "scopes": list(delegation.scopes), "max_tls_validity_days": delegation.max_tls_validity_days,
        "issued_at": delegation.issued_at, "expires_at": delegation.expires_at,
        "signature_base64": base64.b64encode(delegation_sig).decode("ascii"),
    }, indent=2) + "\n")
    _write_new(root / "server/intermediate.pem", intermediate_pem)
    _write_new(root / "server/intermediate-key.pem", intermediate_key_pem)
    _write_new(root / "server/tls-cert.pem", result["chain_pem"])
    _write_new(root / "server/tls-key.pem", result["leaf_key_pem"])
    _write_new(root / "server/public.json", json.dumps({
        "version": 1, "group_id": bootstrap["group_id"], "server_id": bootstrap["server_id"],
        "origin": bootstrap["origin"], "bootstrap": bootstrap, "trust": envelope,
    }, indent=2) + "\n")
    _atomic_replace(root / "public/trust.json", json.dumps(envelope, indent=2) + "\n")
    import shutil

    shutil.copy2(root / "public/manifest.json", root / "public/manifest-pre-rebuild.json")
    _atomic_replace(root / "public/manifest.json", json.dumps({
        "schema": SCHEMA, "group_id": bootstrap["group_id"], "server_id": bootstrap["server_id"],
        "address": args.address, "port": args.port,
        "roles": {"root": bootstrap["group_key_id"], "issuer": issuer_key_id,
                  "recovery": old_manifest["roles"]["recovery"],
                  "update": old_manifest["roles"]["update"]},
        "algorithm": ALGORITHM, "group_spki_base64": bootstrap["group_spki_base64"],
        "tls_issuer_spki_sha256": result["issuer_spki_sha256"],
        "serving": {"generation": result["generation"], "tls_spki_sha256": result["tls_spki_sha256"],
                    "not_before": result["not_before"], "not_after": result["not_after"]},
    }, indent=2) + "\n")
    root_cert_path = str((root / "public/root-ca.pem").as_posix())
    _write_new(root / "Caddyfile", _caddyfile(bootstrap["origin"], args.address, args.backend_port,
                                              str((root / "server/tls-cert.pem").as_posix()),
                                              str((root / "server/tls-key.pem").as_posix()),
                                              root / "caddy-storage"))
    (root / "state/rebuild-incomplete.json").unlink()
    print(json.dumps({"status": "server_rebuilt", "generation": window["generation"],
                      "trust_expires_at": window["expires_at"], "issuer_key_id": issuer_key_id,
                      "tls_spki_sha256": result["tls_spki_sha256"],
                      "deploy": "server/, state/ and public/root|trust|bootstrap|manifest only; "
                                "provision the online password on the target with --provision-online",
                      "root_ca": root_cert_path}, indent=2))



def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    init_p = sub.add_parser("init")
    init_p.add_argument("--root", required=True, type=Path)
    init_p.add_argument("--address", default="192.168.1.165")
    init_p.add_argument("--port", type=int, default=8443)
    init_p.add_argument("--backend-port", type=int, default=8765)
    init_p.add_argument("--group-id")
    init_p.add_argument("--server-id")
    init_p.add_argument("--max-tls-days", type=int, default=30)
    init_p.add_argument("--delegation-days", type=int, default=90)
    init_p.add_argument("--issuer-days", type=int, default=90)
    init_p.add_argument("--tls-days", type=int, default=7)
    init_p.add_argument("--trust-days", type=int, default=7)
    init_p.add_argument("--bootstrap-days", type=int, default=1)
    _add_password_args(init_p)

    renew_p = sub.add_parser("renew-serve")
    renew_p.add_argument("--root", required=True, type=Path)
    renew_p.add_argument("--days", type=int, default=7)
    renew_p.add_argument("--reload", action="store_true")
    _add_password_args(renew_p)

    status_p = sub.add_parser("status")
    status_p.add_argument("--root", required=True, type=Path)

    backup_p = sub.add_parser("backup")
    backup_p.add_argument("--root", required=True, type=Path)
    backup_p.add_argument("--output", required=True, type=Path)
    _add_password_args(backup_p)

    restore_p = sub.add_parser("restore")
    restore_p.add_argument("--bundle", required=True, type=Path)
    restore_p.add_argument("--root", required=True, type=Path)
    restore_p.add_argument("--key-password-file", type=Path)
    _add_password_args(restore_p)

    reauthorize_p = sub.add_parser("reauthorize")
    reauthorize_p.add_argument("--root", required=True, type=Path)
    reauthorize_p.add_argument("--trust-days", type=int, default=365)
    reauthorize_p.add_argument("--previous-authority-isolated", action="store_true")
    reauthorize_p.add_argument("--confirm", action="store_true")
    _add_password_args(reauthorize_p)

    rebuild_p = sub.add_parser("rebuild-server")
    rebuild_p.add_argument("--root", required=True, type=Path)
    rebuild_p.add_argument("--address", required=True)
    rebuild_p.add_argument("--port", type=int, default=8443)
    rebuild_p.add_argument("--backend-port", type=int, default=8765)
    rebuild_p.add_argument("--online-password-file", required=True, type=Path)
    rebuild_p.add_argument("--max-tls-days", type=int, default=30)
    rebuild_p.add_argument("--delegation-days", type=int, default=90)
    rebuild_p.add_argument("--issuer-days", type=int, default=90)
    rebuild_p.add_argument("--tls-days", type=int, default=7)
    rebuild_p.add_argument("--trust-days", type=int, default=365)
    rebuild_p.add_argument("--confirm", action="store_true")
    rebuild_p.add_argument("--previous-authority-isolated", action="store_true")
    _add_password_args(rebuild_p)
    prepared_p = sub.add_parser("prepare-trust-renewals")
    prepared_p.add_argument("--root", required=True, type=Path)
    prepared_p.add_argument("--previous-authority-isolated", action="store_true")
    _add_password_args(prepared_p)

    args = parser.parse_args(argv)
    try:
        if args.command == "init":
            return init(args)
        if args.command == "renew-serve":
            return renew_serve(args)
        if args.command == "status":
            return status(args)
        if args.command == "backup":
            return backup(args)
        if args.command == "restore":
            return restore(args)
        if args.command == "prepare-trust-renewals":
            from kiosk.trust.prepared import prepare
            if (args.root / "restored.json").exists() and not args.previous_authority_isolated:
                raise AdminError("Recovered signing requires --previous-authority-isolated; a new directory is not fencing.")
            print(json.dumps(prepare(args.root, _password(args), _now())))
            return 0
        if args.command == "reauthorize":
            return reauthorize(args)
        if args.command == "rebuild-server":
            return rebuild_server(args)
    except (AdminError, ValueError, KeyError, OSError) as error:
        print(str(error), file=sys.stderr)
        return 1
    return 0


def _add_password_args(parser):
    parser.add_argument("--password", help="Key password (prefer env/--password-file).")
    parser.add_argument("--password-file", type=Path)


if __name__ == "__main__":
    raise SystemExit(main())
