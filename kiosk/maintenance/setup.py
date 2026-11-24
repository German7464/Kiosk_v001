"""Disposable Combined/Separated provisioning for the Maintenance workflow.

The setup creates two independent services with distinct origins, data, secrets
and TLS leaves. ``combined`` places them on one OS; ``separated`` prepares one
side per root with an explicit authenticated counterpart. The same service
contract is used in both placements. This tool never touches retained
installations, the OS clock or existing trust; it writes only under an empty
destination directory.
"""
from __future__ import annotations

import base64
import json
import os
import secrets
import sqlite3
import time
from pathlib import Path
from urllib.parse import urlsplit

from kiosk.publication import authority as publication_authority
from kiosk.publication.workspace import Workspace
from kiosk.trust.crypto import (issue_intermediate_ca, issue_root_ca, issue_tls_leaf,
                                key_id, load_private, private_pem, sign, spki_der)
from . import accounts, permissions
from .authority import MaintenanceAuthority
from .store import MaintenanceStore

GROUP_DOMAIN = b'Kiosk/GroupTrust/v2\0'
ALGORITHM = 'RSA3072-SHA256-PKCS1-v1_5'
DAY = 86400
SERVICE_ID = 'kiosk-maintenance-service'


class SetupError(ValueError):
    pass


def _write(path, payload, mode=0o600):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        raise SetupError('setup_destination_exists')
    if isinstance(payload, str):
        payload = payload.encode('utf-8')
    path.write_bytes(payload)
    try:
        os.chmod(path, mode)
    except OSError:
        pass
    return path


def _json(path, value):
    return _write(path, json.dumps(value, sort_keys=True, indent=2).encode('utf-8'))


def _tls_material(root, name, origin):
    from urllib.parse import urlsplit
    parsed = urlsplit(origin)
    ca_cert = (root / 'ca' / 'root-ca.pem').read_text()
    ca_key = (root / 'ca' / 'root-ca-key.pem').read_text()
    issuer_cert = (root / 'ca' / 'issuer.pem').read_text()
    issuer_key = (root / 'ca' / 'issuer-key.pem').read_text()
    cert, key = issue_tls_leaf('Kiosk ' + name, issuer_cert, issuer_key,
                               san_ips=[parsed.hostname] if _is_ip(parsed.hostname) else [],
                               san_dns=[] if _is_ip(parsed.hostname) else [parsed.hostname],
                               validity_days=7)
    _write(root / name / 'tls' / 'cert.pem', cert)
    _write(root / name / 'tls' / 'key.pem', key)
    chain = (root / 'ca' / 'issuer.pem').read_text()
    _write(root / name / 'tls' / 'chain.pem', cert.rstrip() + '\n' + chain.rstrip() + '\n')
    return dict(cert=str(root / name / 'tls' / 'chain.pem'),
                key=str(root / name / 'tls' / 'key.pem'))


def _is_ip(value):
    import ipaddress
    try:
        ipaddress.IPv4Address(value)
        return True
    except ValueError:
        return False


def _group_trust(group_key, group_id, server_id, origin, issuer_pin, now, days=104):
    payload = dict(version=2, group_id=group_id, generation=1,
                   issued_at=now, expires_at=now + days * DAY,
                   servers=[dict(server_id=server_id, origin=origin,
                                 tls_issuer_spki_sha256=issuer_pin, roles=['publisher'])])
    raw = json.dumps(payload, sort_keys=True, separators=(',', ':')).encode('ascii')
    return dict(version=2, key_id=key_id(group_key), algorithm=ALGORITHM,
                payload_base64=base64.b64encode(raw).decode('ascii'),
                signature_base64=base64.b64encode(
                    sign(group_key, GROUP_DOMAIN, raw)).decode('ascii')), payload


def _bootstrap(group_key, group_id, server_id, origin, ca_pem, now, days=90):
    return dict(version=1, bootstrap_id=secrets.token_hex(16), group_id=group_id,
                server_id=server_id, origin=origin, tls_ca_pem=ca_pem,
                group_key_id=key_id(group_key),
                group_spki_base64=base64.b64encode(spki_der(group_key)).decode('ascii'),
                issued_at=now, expires_at=now + days * DAY)


def create_lab(root, *, mode='combined', content_origin, maintenance_origin, group_id,
               admin_user='admin', admin_password, maintenance_node='n1',
               content_node='n1', counterpart='', bootstrap_days=104,
               tls_material=None):
    """Create both sides under one empty root and return their config paths.

    ``tls_material`` lets a supported installation reuse an already trusted lab
    CA: pass ``{'content': {'cert':..., 'key':...}, 'maintenance': {...},
    'ca': path}`` and no CA private key is generated or copied here.
    """
    if mode not in ('combined', 'separated'):
        raise SetupError('placement_mode_refused')
    root = Path(root).absolute()
    if root.exists() and any(root.iterdir()):
        raise SetupError('setup_destination_exists')
    root.mkdir(parents=True, exist_ok=True)
    now = int(time.time())
    publication_authority.origin(content_origin)
    publication_authority.origin(maintenance_origin)

    # --- TLS: either a supplied trusted CA or one disposable root.
    if tls_material:
        ca_public = Path(tls_material['ca']).read_bytes()
        ca_text = ca_public.decode('utf-8')
        _write(root / 'ca' / 'root-ca.pem', ca_public, 0o644)
        content_tls = dict(cert=str(Path(tls_material['content']['cert']).absolute()),
                           key=str(Path(tls_material['content']['key']).absolute()),
                           ca=str((root / 'ca' / 'root-ca.pem').absolute()),
                           chain=str(Path(tls_material['content']['cert']).absolute()))
        maintenance_tls = dict(
            cert=str(Path(tls_material['maintenance']['cert']).absolute()),
            key=str(Path(tls_material['maintenance']['key']).absolute()),
            ca=str((root / 'ca' / 'root-ca.pem').absolute()),
            chain=str(Path(tls_material['maintenance']['cert']).absolute()))
        issuer_spki = _issuer_spki(ca_public.decode('utf-8'))
    else:
        root_ca, root_ca_key = issue_root_ca('Kiosk maintenance lab root CA',
                                             validity_days=365)
        issuer_cert, issuer_key = issue_intermediate_ca(
            'Kiosk maintenance lab issuer', root_ca, root_ca_key, validity_days=180)
        _write(root / 'ca' / 'root-ca.pem', root_ca, 0o644)
        ca_text = root_ca
        _write(root / 'ca' / 'root-ca-key.pem', root_ca_key)
        _write(root / 'ca' / 'issuer.pem', issuer_cert, 0o644)
        _write(root / 'ca' / 'issuer-key.pem', issuer_key)
        issuer_spki = _issuer_spki(issuer_cert)
        content_tls = _tls_material(root, 'content', content_origin)
        maintenance_tls = _tls_material(root, 'maintenance', maintenance_origin)
        for item in (content_tls, maintenance_tls):
            item['ca'] = str((root / 'ca' / 'root-ca.pem').absolute())

    # --- independent publisher root (outside the content server's own state).
    authority_dir = root / 'authority'
    from tools.publisher_authority import init as init_authority, load as load_authority
    authority_password = secrets.token_urlsafe(32)
    public = init_authority(authority_dir, group_id, content_origin, authority_password, now)
    _write(root / 'authority-password.txt', authority_password)
    root_key, public, policy = load_authority(authority_dir, authority_password, now)
    public_raw = (authority_dir / 'public.json').read_bytes()
    policy_raw = (authority_dir / 'policy.json').read_bytes()

    # --- display trust lab (optional but generated for native acceptance).
    from kiosk.trust.crypto import generate_private_key
    group_key = generate_private_key()
    _write(root / 'group' / 'group-key.pem', private_pem(group_key))
    server_id = secrets.token_hex(16)
    trust, _ = _group_trust(group_key, group_id, server_id, content_origin, issuer_spki, now)
    bootstrap = _bootstrap(group_key, group_id, server_id, content_origin, ca_text, now,
                           days=bootstrap_days)
    _write(root / 'group' / 'bootstrap.json',
           json.dumps(bootstrap, sort_keys=True).encode('utf-8'), 0o644)

    # --- service identity and data roots.
    service_secret = secrets.token_hex(32)
    content_root = root / 'content'
    maintenance_root = root / 'maintenance'
    delivery_root = content_root / 'delivery'
    (delivery_root / 'publications').mkdir(parents=True, exist_ok=True)
    public_upload = content_root / 'static' / 'uploads'
    public_upload.mkdir(parents=True, exist_ok=True)
    (content_root / 'instance').mkdir(parents=True, exist_ok=True)
    (maintenance_root / 'secrets').mkdir(parents=True, exist_ok=True)
    _json(delivery_root / 'public.json', dict(
        version=1, group_id=group_id, server_id=server_id, origin=content_origin,
        bootstrap=bootstrap, trust=trust))

    content_config = dict(
        SECRET_KEY=secrets.token_hex(32),
        INSTANCE_DIR=str(content_root / 'instance'),
        DATABASE_PATH=str(content_root / 'instance' / 'kiosk.sqlite'),
        PUBLIC_UPLOAD_DIR=str(public_upload),
        PRIVATE_UPLOAD_DIR=str(content_root / 'instance' / 'uploads'),
        DEVICE_DELIVERY_ROOT=str(delivery_root),
        ROAMING_WORKSPACE=dict(
            database=str(content_root / 'workspace.sqlite'),
            root_spki=public['root_spki'], group_id=group_id, origin=content_origin,
            policy=str(authority_dir / 'policy.json')),
        MAINTENANCE_SERVICE=dict(service_id=SERVICE_ID, secret=service_secret),
        TLS=content_tls,
    )

    maintenance_config = dict(
        SECRET_KEY=secrets.token_hex(32),
        MAINTENANCE_DATABASE=str(maintenance_root / 'maintenance.sqlite'),
        MAINTENANCE_SECRETS_DIR=str(maintenance_root / 'secrets'),
        MAINTENANCE_ROOT_PUBLIC=str(authority_dir / 'public.json'),
        MAINTENANCE_ROOT_POLICY=str(authority_dir / 'policy.json'),
        MAINTENANCE_ORIGIN=maintenance_origin,
        CONTENT_ORIGIN=content_origin,
        CONTENT_CA_FILE=str(root / 'ca' / 'root-ca.pem'),
        CONTENT_SERVICE_ID=SERVICE_ID,
        CONTENT_SERVICE_SECRET=service_secret,
        MAINTENANCE_PLACEMENT=dict(
            mode=mode, side='maintenance', node=maintenance_node or 'n1',
            origin=maintenance_origin, counterpart=counterpart or content_origin,
            generation=1),
        TLS=maintenance_tls,
    )

    # --- content-side placement record (same fence/generation semantics).
    workspace = Workspace(content_config['ROAMING_WORKSPACE']['database'],
                          base64.b64decode(public['root_spki'], validate=True),
                          group_id, content_origin)
    workspace.install_policy(public_authority_policy(policy_raw))
    workspace.configure_placement(mode, content_origin, generation=1,
                                  counterpart=counterpart or maintenance_origin)

    # --- maintenance accounts, reviewer key and a root-signed admin grant.
    store = MaintenanceStore(maintenance_config['MAINTENANCE_DATABASE'])
    authority = MaintenanceAuthority(store, maintenance_config['MAINTENANCE_SECRETS_DIR'],
                                     json.loads(public_raw), json.loads(policy_raw))
    with store.connection() as db:
        accounts.create_user(db, admin_user, admin_password, 'administrator', now=now)
        db.execute('INSERT INTO grants (subject_type,subject_id,bundle,groups,created_by,created) '
                   'VALUES (?,?,?,?,?,?)',
                   ('user', admin_user, 'system-administrator',
                    json.dumps([group_id]), admin_user, now))
        row, key = authority.ensure_key(db, admin_user)
        grant = dict(group_id=group_id, origin=content_origin, user_id=admin_user,
                     role='administrator', device_key=base64.b64encode(spki_der(key)).decode('ascii'),
                     issued=now, expires=min(policy['expires'], now + publication_authority.MAX_AUTHORITY_SECONDS),
                     can_delegate=True)
        chain = [publication_authority.signed(root_key, 'device', grant)]
        authority.install_grant(db, admin_user, chain, public_authority_policy(policy_raw))
    # The content service receives only the public acceptance key; it can verify
    # the trusted side's automatic acceptance evidence but cannot mint it.
    content_config['MAINTENANCE_ACCEPTANCE_KEY'] = authority.acceptance_identity()
    store.configure_placement(mode, 'maintenance', maintenance_node or 'n1',
                              maintenance_origin, counterpart=counterpart or content_origin,
                              generation=1)
    store.configure_schedule(now, 90)

    if (not tls_material and _is_ip(urlsplit(content_origin).hostname)
            and _is_ip(urlsplit(maintenance_origin).hostname)):
        # Only the trusted Maintenance identity receives this online issuer.
        # The content side holds its own leaf key and a content-only request MAC.
        from kiosk.trust.roles import make_delegation, sign_delegation, delegation_payload
        from .tls import provision
        tls_secret = secrets.token_hex(32)
        delegated = {}
        for side, endpoint, identity in (('content', content_origin, server_id),
                                         ('maintenance', maintenance_origin, server_id + '-maintenance')):
            item = make_delegation(group_id=group_id, server_id=identity, origin=endpoint,
                permitted_ip=[urlsplit(endpoint).hostname], permitted_dns=[],
                issuer_key_id=issuer_spki,
                issuer_spki_base64=base64.b64encode(spki_der(load_private(issuer_key))).decode('ascii'),
                # One full leaf lifetime beyond the fourteen-day authority
                # overlap prevents a full-seven-day issuance bound shortening it.
                max_tls_validity_days=7, issued_at=now, expires_at=now + 111 * DAY)
            delegated[side] = dict(payload=json.loads(delegation_payload(item)),
                                   signature=base64.b64encode(sign_delegation(private_pem(group_key), item)).decode('ascii'))
        provision(store, maintenance_root / 'secrets', issuer_key,
                  dict(issuer_certificate=issuer_cert, delegations=delegated, client_secret=tls_secret,
                       group_trust=trust))
        maintenance_config['LAN_TLS_ROOT_SPKI'] = base64.b64encode(spki_der(group_key)).decode('ascii')
        maintenance_config['TLS_RENEWAL'] = dict(issuer_spki_sha256=issuer_spki)
        content_config['TLS_RENEWAL'] = dict(authority_origin=maintenance_origin,
                                            secret=tls_secret, issuer_spki_sha256=issuer_spki)

    _json(root / 'content-config.json', content_config)
    _json(root / 'maintenance-config.json', maintenance_config)
    _json(root / 'lab.json', dict(
        version=1, mode=mode, group_id=group_id, content_origin=content_origin,
        maintenance_origin=maintenance_origin, admin_user=admin_user,
        server_id=server_id, created=now, bootstrap_days=bootstrap_days,
        placement_generation=1, service_id=SERVICE_ID,
        root_ca_sha256=_sha_file(root / 'ca' / 'root-ca.pem'),
        publisher_root_sha256=public['root_sha256'],
        group_key_id=key_id(group_key),
        bootstrap_sha256=_sha_file(root / 'group' / 'bootstrap.json')))
    return dict(root=str(root), content_config=str(root / 'content-config.json'),
                maintenance_config=str(root / 'maintenance-config.json'),
                lab=str(root / 'lab.json'))


def public_authority_policy(raw):
    from kiosk.delivery.protocol import decode
    return decode(raw)


def _issuer_spki(cert_pem):
    from kiosk.trust.crypto import cert_spki_sha256
    return cert_spki_sha256(cert_pem)


def _sha_file(path):
    import hashlib
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()
