"""Single-administrator offline renewal using an encrypted recovery backup.

Reuses the existing authenticated encrypted bundle and signing primitives. Only
public certificates, policy and permissions are returned to the installation.
The online issuer's private key never leaves its own service identity.
"""
import base64
import json
from pathlib import Path
from urllib.parse import urlsplit

from cryptography import x509
from cryptography.hazmat.primitives import serialization
from kiosk.delivery.protocol import decode, encode, fields, sha, digest
from kiosk.publication import authority as a
from kiosk.trust.crypto import (load_private, spki_der, key_id, sign, ALGORITHM,
                                issue_intermediate_ca)
from kiosk.trust.lifecycle import verify_group_window, delegation_from_payload
from kiosk.trust.roles import make_delegation, sign_delegation, delegation_payload, verify_delegation
from .relocation import _read_bundle, _write_bundle

DAY = 86400


def export_request(app, user, *, require_lan=False):
    """Export a signed request without using a live HTTPS listener."""
    from . import accounts
    from .store import MaintenanceError

    store = app.extensions['maintenance_store']
    if store.fenced():
        raise MaintenanceError('service_fenced', 409)
    issuer = app.extensions.get('maintenance_tls_authority')
    with store.connection() as db:
        if require_lan:
            account = accounts.find(db, user)
            if account is None or account['blocked'] or account['role'] != 'administrator':
                raise MaintenanceError('retained_administrator_required', 403)
        row = db.execute('SELECT configuration FROM tls_issuer WHERE singleton=1').fetchone()
        if require_lan and (row is None or issuer is None):
            raise MaintenanceError('tls_issuer_unconfigured', 503)
        lan = None
        if row is not None:
            configuration = decode(bytes(row['configuration']))
            if issuer is not None:
                configuration = issuer.public_configuration(configuration)
            lan = {key: configuration[key] for key in ('issuer_certificate', 'group_trust', 'delegations')}
        return app.extensions['maintenance_authority'].recovery_request(db, user, lan=lan)


def apply_public(app, user, bundle, *, root_pin, confirm, actor='installation-administrator'):
    """Same-key recovery usable before HTTPS restarts after transport expiry.

    The CLI runs under the existing service identity, using an OS administrator's
    explicit one-shot invocation. It receives public signed material only.
    """
    from .store import MaintenanceError
    store = app.extensions['maintenance_store']
    authority = app.extensions['maintenance_authority']
    if store.fenced():
        raise MaintenanceError('service_fenced', 409)
    fields(bundle, 'chain policy' + (' lan' if isinstance(bundle, dict) and 'lan' in bundle else ''))
    with store.connection() as db:
        result = authority.recover_grant(db, user, bundle['chain'], bundle['policy'], root_pin=root_pin, confirm=confirm)
        public = dict(policy=bundle['policy'])
        if 'lan' in bundle:
            policy = a.verified(bundle['policy'], authority.root, 'policy')
            if min(result['expires'], policy['expires']) < authority.now() + 97*DAY:
                raise MaintenanceError('lan_recovery_window_refused', 409)
            issuer = app.extensions.get('maintenance_tls_authority')
            if issuer is None:
                raise MaintenanceError('tls_issuer_unconfigured', 503)
            configuration = issuer.recovery_configuration(db, bundle['lan'], app.config['TLS']['ca'])
            db.execute('UPDATE tls_issuer SET configuration=? WHERE singleton=1', (encode(configuration),))
            public['trust'] = configuration['group_trust']
        db.execute('INSERT OR REPLACE INTO authority_delivery VALUES (1,?)', (encode(public),))
        store.audit(db, 'publisher_recovery_import', actor, user)
    return result


def backup(staged_lab, destination, password):
    """Read only fresh setup staging; caller separately verifies external custody."""
    root = Path(staged_lab)
    public = decode((root / 'authority/public.json').read_bytes())
    material = dict(version=1, root_ca=(root / 'ca/root-ca.pem').read_text(),
                    root_key=(root / 'ca/root-ca-key.pem').read_text(),
                    group_key=(root / 'group/group-key.pem').read_text(),
                    publisher_key=(root / 'authority/authority-key.pem').read_text(),
                    publisher_password=(root / 'authority-password.txt').read_text().strip(),
                    publisher_public=public, publisher_policy=decode((root / 'authority/policy.json').read_bytes()))
    root_key = load_private(material['root_key'])
    certificate = x509.load_pem_x509_certificate(material['root_ca'].encode('ascii'))
    if spki_der(root_key) != spki_der(certificate.public_key()):
        raise ValueError('offline_root_mismatch')
    publisher = load_private(material['publisher_key'], material['publisher_password'])
    if base64.b64encode(spki_der(publisher)).decode() != public['root_spki']:
        raise ValueError('offline_publisher_mismatch')
    bootstrap = decode((root / 'group/bootstrap.json').read_bytes())
    if key_id(load_private(material['group_key'])) != bootstrap['group_key_id']:
        raise ValueError('offline_group_mismatch')
    material['bootstrap'] = bootstrap
    _write_bundle(destination, material, password)
    # Verify the written backup before reporting success. No staged file removed.
    _, restored = _read_bundle(destination, password)
    if restored != material:
        raise ValueError('offline_backup_verification_failed')
    return dict(verified=True, backup_sha256=sha(Path(destination).read_bytes()),
                publisher_root_sha256=public['root_sha256'], group_key_id=bootstrap['group_key_id'])


def renew(backup_file, password, request, now, *, confirm=False):
    if confirm is not True:
        raise ValueError('administrator_confirmation_required')
    _, material = _read_bundle(backup_file, password, limit=131072)
    fields(request, 'request proof lan policy chain lan_proof')
    document = request['request']
    fields(document, 'device_key device_id group_id origin user_id action nonce issued expires')
    device = base64.b64decode(document['device_key'], validate=True)
    if (a.verified(request['proof'], device, 'device-request') != document
            or document['device_id'] != key_id(device) or document['action'] != 'add-device'
            or type(document['issued']) is not int or type(document['expires']) is not int
            or not 0 < document['expires'] - document['issued'] <= 90):
        raise ValueError('offline_request_refused')
    binding = dict(request_sha256=sha(encode(document)), lan_sha256=sha(encode(request['lan'])),
                   policy_sha256=sha(encode(request['policy'])), chain_sha256=sha(encode(request['chain'])))
    if a.verified(request['lan_proof'], device, 'lan-maintenance-request') != binding:
        raise ValueError('offline_request_refused')
    public = material['publisher_public']
    if document['group_id'] != public['group_id'] or document['origin'] != public['origin']:
        raise ValueError('offline_scope_refused')
    publisher = load_private(material['publisher_key'], material['publisher_password'])
    digest(document['nonce'])
    receipt_dir = Path(str(backup_file) + '.receipts')
    receipt = receipt_dir / (document['nonce'] + '.json')
    request_digest = sha(encode(request))
    if receipt.exists():
        cached = a.verified(decode(receipt.read_bytes()), spki_der(publisher), 'lan-maintenance-result')
        if cached['request_sha256'] != request_digest:
            raise ValueError('offline_request_conflict')
        return cached['result']
    if not document['issued'] <= now < document['expires']:
        raise ValueError('offline_request_expired')
    policies = []
    for envelope in (material['publisher_policy'], request['policy']):
        value = a.verified(envelope, spki_der(publisher), 'policy')
        policies.append(a.policy(envelope, spki_der(publisher), public['group_id'], public['origin'], value['issued']))
    previous = max(policies, key=lambda p: p['version'])
    grant_raw = a.verified(request['chain'][0], spki_der(publisher), 'device')
    # This workflow recovers a retained directly root-authorized administrator.
    # Delegated/mobile user recovery continues through the existing explicit path.
    grant, signer = a.permission(request['chain'], spki_der(publisher), previous, grant_raw['issued'])
    revoked_devices = sorted(set().union(*(set(p['revoked_devices']) for p in policies)))
    revoked_users = sorted(set().union(*(set(p['revoked_users']) for p in policies)))
    if (signer != device or grant['user_id'] != document['user_id'] or grant['role'] != 'administrator'
            or document['device_id'] in revoked_devices or document['user_id'] in revoked_users
            or now < max(p['issued'] for p in policies)):
        raise ValueError('offline_grant_refused')
    group_key = load_private(material['group_key'])
    lan = request['lan']; fields(lan, 'issuer_certificate group_trust delegations')
    trust = verify_group_window(lan['group_trust'], spki_der(group_key))
    bootstrap = material['bootstrap']
    if (trust['group_id'] != bootstrap['group_id'] or trust['servers'][0]['origin'] != bootstrap['origin']
            or trust['servers'][0]['server_id'] != bootstrap['server_id'] or now < trust['issued_at']):
        raise ValueError('offline_group_refused')
    issuer = x509.load_pem_x509_certificate(lan['issuer_certificate'].encode('ascii'))
    if key_id(issuer.public_key()) != trust['servers'][0]['tls_issuer_spki_sha256']:
        raise ValueError('offline_issuer_refused')
    root = x509.load_pem_x509_certificate(material['root_ca'].encode('ascii'))
    root_end = int(root.not_valid_after_utc.timestamp())
    if not int(root.not_valid_before_utc.timestamp()) <= now or now + 111 * DAY > root_end:
        raise ValueError('offline_root_repair_required')
    # Recertify the *public* online issuer key; never import its private key.
    issuer_cert, private = issue_intermediate_ca(issuer.subject.get_attributes_for_oid(x509.oid.NameOID.COMMON_NAME)[0].value,
        material['root_ca'], material['root_key'], validity_days=min(180, (root_end-now)//DAY),
        now=now, public_key=issuer.public_key())
    if private is not None:
        raise ValueError('offline_private_key_transport_refused')
    delegated = {}
    for side in ('content', 'maintenance'):
        old = lan['delegations'][side]
        item = delegation_from_payload(old['payload'])
        verify_delegation(spki_der(group_key), item, base64.b64decode(old['signature'], validate=True))
        if (item.group_id != trust['group_id'] or item.issuer_key_id != key_id(issuer.public_key())
                or (side == 'content' and (item.origin != document['origin'] or item.server_id != bootstrap['server_id']))):
            raise ValueError('offline_delegation_refused')
        payload = dict(old['payload'], issued_at=now, expires_at=now+111*DAY)
        replacement = delegation_from_payload(payload)
        delegated[side] = dict(payload=payload, signature=base64.b64encode(sign_delegation(material['group_key'], replacement)).decode())
    trust = dict(trust, generation=trust['generation']+1, issued_at=now, expires_at=now+104*DAY)
    raw = encode(trust)
    envelope = dict(version=2, algorithm=ALGORITHM, key_id=key_id(group_key),
                    payload_base64=base64.b64encode(raw).decode(),
                    signature_base64=base64.b64encode(sign(group_key, b'Kiosk/GroupTrust/v2\0', raw)).decode())
    policy = dict(previous, version=previous['version']+1, issued=now, expires=now+104*DAY,
                  revoked_devices=revoked_devices, revoked_users=revoked_users)
    grant = dict(grant, issued=now, expires=now+104*DAY)
    result = dict(chain=[a.signed(publisher, 'device', grant)], policy=a.signed(publisher, 'policy', policy),
                lan=dict(issuer_certificate=issuer_cert, group_trust=envelope, delegations=delegated))
    receipt_dir.mkdir(exist_ok=True)
    if len(list(receipt_dir.glob('*.json'))) >= 1024:
        raise ValueError('offline_request_capacity')
    cached = a.signed(publisher, 'lan-maintenance-result', dict(request_sha256=request_digest, result=result))
    import os
    with receipt.open('xb') as stream:
        stream.write(encode(cached)); stream.flush(); os.fsync(stream.fileno())
    return result
