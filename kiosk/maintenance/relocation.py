"""Explicit, fenced relocation of one service side.

A relocation is a supported maintenance operation, never a live replication:

1. the source enters a fenced handoff state (privileged writes refused) and
   produces a one-time fence token;
2. a consistent snapshot is exported, encrypted and hash-manifested;
3. the destination verifies every digest and imports into a fresh root;
4. the fence token activates the destination exactly once; the old side refuses
   activation forever, so two independent active authorities cannot both resume.

Reviewer private keys are explicitly re-wrapped: DPAPI blobs are not portable and
are never copied. Human sessions are not migrated; renewed login is acceptable.
"""
from __future__ import annotations

import base64
import hashlib
import http.client
import io
import json
import os
import secrets
import shutil
import sqlite3
import ssl
import tarfile
import tempfile
import time
from pathlib import Path

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC

from kiosk.delivery.protocol import decode, encode, sha
from kiosk.publication.workspace import Workspace
from . import keystore
from .store import MaintenanceError, MaintenanceStore

MAGIC = b'KIOSKRELOC1'
ITERATIONS = 200_000
AAD = b'kiosk-relocation-v1'


class RelocationError(ValueError):
    pass


def _key(passphrase, salt):
    if not isinstance(passphrase, str) or len(passphrase) < 12:
        raise RelocationError('relocation_passphrase_required')
    return PBKDF2HMAC(algorithm=hashes.SHA256(), length=32, salt=salt,
                      iterations=ITERATIONS).derive(passphrase.encode('utf-8'))


def _pack(value):
    """Tag bytes so the encrypted bundle is plain JSON on both sides."""
    if isinstance(value, (bytes, bytearray)):
        return {'__bytes__': base64.b64encode(bytes(value)).decode('ascii')}
    if isinstance(value, dict):
        return {key: _pack(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_pack(item) for item in value]
    return value


def _unpack(value):
    if isinstance(value, dict):
        if set(value) == {'__bytes__'}:
            return base64.b64decode(value['__bytes__'], validate=True)
        return {key: _unpack(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_unpack(item) for item in value]
    return value


def _write_bundle(path, payload, passphrase):
    if Path(path).exists():
        raise RelocationError('relocation_destination_exists')
    salt, nonce = os.urandom(16), os.urandom(12)
    planted = encode(_pack(payload))
    body = AESGCM(_key(passphrase, salt)).encrypt(nonce, planted, AAD)
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_bytes(MAGIC + salt + nonce + body)
    return sha(planted), len(planted)


def _read_bundle(path, passphrase=None, *, limit=256 * 1024 * 1024):
    raw = Path(path).read_bytes()
    if len(raw) > limit or not raw.startswith(MAGIC):
        raise RelocationError('relocation_bundle_refused')
    salt, nonce, body = (raw[len(MAGIC):len(MAGIC) + 16],
                         raw[len(MAGIC) + 16:len(MAGIC) + 28],
                         raw[len(MAGIC) + 28:])
    if passphrase is None:
        raise RelocationError('relocation_passphrase_required')
    try:
        planted = AESGCM(_key(passphrase, salt)).decrypt(nonce, body, AAD)
    except Exception:
        raise RelocationError('relocation_bundle_refused') from None
    return planted, _unpack(decode(planted))


def _sqlite_backup(source, destination):
    source = Path(source)
    if not source.exists():
        raise RelocationError('relocation_source_missing')
    connection = sqlite3.connect(f'file:{source}?mode=ro', uri=True)
    try:
        target = sqlite3.connect(destination)
        try:
            connection.backup(target)
        finally:
            target.close()
    finally:
        connection.close()
    return Path(destination)


def _files(root, names):
    result = []
    root = Path(root)
    for name in names:
        path = root / name
        if not path.exists():
            continue
        if path.is_dir():
            for item in sorted(path.rglob('*')):
                if item.is_file():
                    result.append(item)
        else:
            result.append(path)
    return result


def _collect(root, paths):
    entries = []
    for path in paths:
        data = Path(path).read_bytes()
        entries.append(dict(path=str(Path(path).relative_to(root)).replace('\\', '/'),
                            size=len(data),
                            sha256=sha(data), b64=base64.b64encode(data).decode('ascii')))
    return entries


def export_maintenance(store, secrets_dir, bundle_path, passphrase, *, now=None,
                       transfer=None, cutover_secret=None):
    placement = store.placement()
    if placement is None or not store.fenced() or not placement['handoff']:
        raise MaintenanceError('relocation_fence_required', 409)
    now = int(now or time.time())
    with store.connection(write=False) as db:
        users = [dict(row) for row in db.execute('SELECT * FROM users')]
        grants = [dict(row) for row in db.execute('SELECT * FROM grants')]
        teams = [dict(row) for row in db.execute('SELECT * FROM teams')]
        memberships = [dict(row) for row in db.execute('SELECT * FROM memberships')]
        terminals = [dict(row) for row in db.execute('SELECT * FROM terminals')]
        keys = [dict(row) for row in db.execute('SELECT * FROM keys')]
        reviews = [dict(row) for row in db.execute('SELECT * FROM reviews')]
        receipts = [dict(row) for row in db.execute('SELECT * FROM receipts')]
        schedule = db.execute('SELECT * FROM schedule WHERE singleton=1').fetchone()
        recovery = db.execute('SELECT * FROM recovery WHERE singleton=1').fetchone()
        publisher_policy = db.execute('SELECT * FROM publisher_policy WHERE singleton=1').fetchone()
        authority_delivery = db.execute('SELECT body FROM authority_delivery WHERE singleton=1').fetchone()
    wrapped = []
    for row in keys:
        pem = keystore.protect(bytes(row['protected']), secrets_dir, decrypt=True)
        wrapped.append(dict(user_id=row['user_id'], spki=row['spki'],
                            device_id=row['device_id'], role=row['role'],
                            chain=row['chain'], policy=row['policy'],
                            group_id=row['group_id'], origin=row['origin'],
                            scope=row['scope'], issued=row['issued'],
                            expires=row['expires'],
                            private_pem=pem.decode('ascii')))
    cutover_secret = cutover_secret or secrets.token_hex(32)
    transfer = transfer or secrets.token_hex(32)
    store.issue_transfer(transfer, hashlib.sha256(cutover_secret.encode()).hexdigest(), now)
    payload = dict(version=1, side='maintenance', created=now,
                   origin=placement['origin'], generation=placement['generation'],
                   fence=placement['fence'], mode='separated',
                   transfer=dict(id=transfer, secret=cutover_secret),
                   data=dict(users=users, grants=grants, teams=teams,
                             memberships=memberships, terminals=terminals,
                             keys=wrapped, reviews=reviews, receipts=receipts,
                             schedule=dict(schedule) if schedule else None,
                            recovery=dict(recovery) if recovery else None,
                            publisher_policy=dict(publisher_policy) if publisher_policy else None,
                            authority_delivery=bytes(authority_delivery['body']) if authority_delivery else None))
    acceptance_path = Path(secrets_dir) / 'acceptance.key'
    if acceptance_path.exists():
        raw = keystore.protect(acceptance_path.read_bytes(), secrets_dir, decrypt=True)
        payload['acceptance_pem'] = raw.decode('ascii')
    with store.connection(write=False) as db:
        issuer = db.execute('SELECT * FROM tls_issuer WHERE singleton=1').fetchone()
        if issuer is not None:
            tables = ('meta', 'tls_issue', 'revoked', 'used_grants')
            state = {name: [dict(row) for row in db.execute('SELECT * FROM ' + name)] for name in tables}
            payload['tls_issuer'] = dict(
                private_pem=keystore.protect(bytes(issuer['protected']), secrets_dir, decrypt=True).decode('ascii'),
                configuration=bytes(issuer['configuration']), state=state)
    digest, size = _write_bundle(bundle_path, payload, passphrase)
    return dict(side='maintenance', digest=digest, size=size,
                counts={name: len(payload['data'][name]) for name in
                        ('users', 'grants', 'keys', 'reviews', 'receipts')},
                generation=placement['generation'], transfer=transfer)


def import_maintenance(bundle_path, store, secrets_dir, passphrase, *, node, origin,
                       counterpart='', mode='separated'):
    _, payload = _read_bundle(bundle_path, passphrase)
    if payload.get('side') != 'maintenance' or payload.get('version') != 1:
        raise RelocationError('relocation_bundle_refused')
    data = payload['data']
    tls = payload.get('tls_issuer')
    if tls is not None:
        from kiosk.trust.state import LifecycleState
        LifecycleState(store.path.parent, database=store.path)
    with store.connection() as db:
        if db.execute('SELECT COUNT(*) FROM users').fetchone()[0]:
            raise RelocationError('relocation_destination_not_empty')
        if payload.get('acceptance_pem'):
            from kiosk.trust.crypto import load_private, spki_der
            acceptance = Path(secrets_dir) / 'acceptance.key'
            proposed = load_private(payload['acceptance_pem'])
            if acceptance.exists():
                retained = keystore.protect(acceptance.read_bytes(), secrets_dir, decrypt=True).decode('ascii')
                if spki_der(load_private(retained)) != spki_der(proposed):
                    raise RelocationError('relocation_acceptance_key_conflict')
            else:
                acceptance.parent.mkdir(parents=True, exist_ok=True)
                protected_acceptance = keystore.protect(payload['acceptance_pem'].encode('ascii'), secrets_dir)
                with acceptance.open('xb') as stream:
                    stream.write(protected_acceptance); stream.flush(); os.fsync(stream.fileno())
            # Written before the DB commit. An interrupted import can re-use
            # this exact key; a different pre-existing key never gets overwritten.
        if data.get('authority_delivery') is not None:
            db.execute('INSERT INTO authority_delivery VALUES (1,?)', (data['authority_delivery'],))
        if data.get('publisher_policy') is not None:
            if db.execute('SELECT 1 FROM publisher_policy').fetchone():
                raise RelocationError('relocation_destination_not_empty')
            policy = data['publisher_policy']
            db.execute('INSERT INTO publisher_policy VALUES (1,?,?)', (policy['version'], policy['envelope']))
        if tls is not None:
            if db.execute('SELECT 1 FROM tls_issuer').fetchone():
                raise RelocationError('relocation_destination_not_empty')
            from kiosk.trust.crypto import load_private
            load_private(tls['private_pem'])
            protected = keystore.protect(tls['private_pem'].encode('ascii'), secrets_dir)
            db.execute('INSERT INTO tls_issuer VALUES (1,?,?)', (protected, tls['configuration']))
            for table, columns in (
                    ('meta', ('key', 'value')),
                    ('tls_issue', ('generation', 'spki_sha256', 'not_before', 'not_after', 'recorded')),
                    ('revoked', ('target', 'reason', 'at')),
                    ('used_grants', ('grant_id', 'at'))):
                if db.execute('SELECT 1 FROM ' + table).fetchone():
                    raise RelocationError('relocation_destination_not_empty')
                for record in tls['state'][table]:
                    if set(record) != set(columns):
                        raise RelocationError('relocation_bundle_refused')
                    db.execute('INSERT INTO ' + table + ' (' + ','.join(columns) + ') VALUES ('
                               + ','.join('?' for _ in columns) + ')', tuple(record[name] for name in columns))
        for row in data['users']:
            db.execute('INSERT INTO users VALUES (?,?,?,?,?,?,?,?)',
                       (row['id'], row['password_hash'], row['display_name'], row['role'],
                        row['blocked'], row['auth_epoch'], row['created'], row['updated']))
        for row in data['teams']:
            db.execute('INSERT INTO teams VALUES (?,?,?)', (row['id'], row['name'], row['created']))
        for row in data['memberships']:
            db.execute('INSERT INTO memberships VALUES (?,?)', (row['user_id'], row['team_id']))
        for row in data['grants']:
            db.execute('INSERT INTO grants (subject_type,subject_id,bundle,groups,created_by,created) '
                       'VALUES (?,?,?,?,?,?)',
                       (row['subject_type'], row['subject_id'], row['bundle'], row['groups'],
                        row['created_by'], row['created']))
        for row in data['terminals']:
            db.execute('INSERT INTO terminals VALUES (?,?,?,?,?,?,?)',
                       (row['id'], row['name'], row['approved'], row['retained'],
                        row['approved_by'], row['approved_at'], row['policy']))
        for row in data['keys']:
            protected = keystore.protect(row['private_pem'].encode('ascii'), secrets_dir)
            db.execute('INSERT INTO keys VALUES (?,?,?,?,?,?,?,?,?,?,?,?)',
                       (row['user_id'], protected, row['spki'], row['device_id'], row['role'],
                        row['chain'], row['policy'], row['group_id'], row['origin'],
                        row['scope'], row['issued'], row['expires']))
        for row in data['reviews']:
            db.execute('INSERT INTO reviews VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)',
                       (row['id'], row['session_id'], row['user_id'], row['plan_id'],
                        row['digest'], row['body'], row['targets'], row['created'],
                        row['expires'], row['state'], row['approval'], row['receipt'],
                        row['commit_reference']))
        for row in data['receipts']:
            db.execute('INSERT INTO receipts VALUES (?,?,?)',
                       (row['plan_id'], row['body'], row['created']))
        db.execute('DELETE FROM schedule')
        if data['schedule']:
            db.execute('INSERT INTO schedule VALUES (1,?,?,?,?)',
                       (data['schedule']['anchor'], data['schedule']['interval_days'],
                        data['schedule']['last_maintenance'], data['schedule']['detail']))
        db.execute('DELETE FROM recovery')
        if data['recovery']:
            db.execute('INSERT INTO recovery VALUES (1,?,?,?)',
                       (data['recovery']['generation'], data['recovery']['state'],
                        data['recovery']['detail']))
        db.execute('DELETE FROM sessions')
        db.execute('DELETE FROM connections')
        db.execute('DELETE FROM placements')
        db.execute('INSERT INTO placements VALUES (1,?,?,?,?,?,?,?,?,?,?)',
                   (mode if mode in ('combined', 'separated') else 'separated',
                    'maintenance', node, origin, int(payload['generation']), 0,
                    payload['fence'], 0, counterpart, int(time.time())))
    transfer = payload.get('transfer') or {}
    if transfer.get('id') and transfer.get('secret'):
        store.import_transfer(transfer['id'], hashlib.sha256(
            transfer['secret'].encode()).hexdigest(), origin)
    return dict(side='maintenance', generation=int(payload['generation']),
                fence=payload['fence'], origin=origin,
                transfer=transfer.get('id'), cutover_secret=transfer.get('secret'),
                acceptance_key=_acceptance_spki(payload))


def peek_transfer(bundle_path, passphrase):
    """Read only the cutover identity from an encrypted bundle."""
    _, payload = _read_bundle(bundle_path, passphrase)
    transfer = payload.get('transfer') or {}
    return dict(id=transfer.get('id'), secret=transfer.get('secret'),
                generation=payload.get('generation'), fence=payload.get('fence'))


def redeem_remote(origin, ca_file, transfer, secret, destination, *, timeout=20):
    """Ask the fenced source for the exclusive single-use cutover claim."""
    from urllib.parse import urlsplit
    parsed = urlsplit(origin)
    if parsed.scheme != 'https' or not parsed.hostname or parsed.port is None:
        raise RelocationError('relocation_source_refused')
    body = encode({'transfer': transfer, 'secret': secret, 'destination': destination})
    context = ssl.create_default_context(cafile=str(ca_file))
    context.minimum_version = ssl.TLSVersion.TLSv1_2
    connection = http.client.HTTPSConnection(parsed.hostname, parsed.port, context=context,
                                             timeout=timeout)
    try:
        connection.request('POST', '/api/relocate/redeem', body=body,
                           headers={'Content-Type': 'application/json'})
        response = connection.getresponse()
        raw = response.read(65536)
        value = decode(raw) if raw else {}
        if response.status != 200:
            code = value.get('error') if isinstance(value, dict) else None
            raise RelocationError(code or 'cutover_refused')
        return value
    except (OSError, http.client.HTTPException):
        raise RelocationError('relocation_source_unavailable') from None
    finally:
        connection.close()


def export_content(workspace, content_root, bundle_path, passphrase, *, uploads_dirs=(),
                   now=None):
    """Consistent snapshot of drafts, media, publications and delivery history."""
    content_root = Path(content_root)
    placement = workspace.placement()
    if placement is None or not workspace.fenced() or not placement['handoff']:
        raise MaintenanceError('relocation_fence_required', 409)
    now = int(now or time.time())
    with tempfile.TemporaryDirectory(prefix='.relocation-') as folder:
        folder = Path(folder)
        entries = []
        workspace_copy = _sqlite_backup(workspace.path, folder / 'workspace.sqlite')
        for name, path in (('workspace.sqlite', workspace_copy),
                           ('instance/kiosk.sqlite', content_root / 'instance' / 'kiosk.sqlite')):
            if not path.exists():
                continue
            data = path.read_bytes()
            entries.append(dict(path=name, size=len(data), sha256=sha(data),
                                b64=base64.b64encode(data).decode('ascii')))
        delivery_db = content_root / 'delivery' / 'delivery.sqlite'
        if delivery_db.exists():
            copy = _sqlite_backup(delivery_db, folder / 'delivery.sqlite')
            data = copy.read_bytes()
            entries.append(dict(path='delivery/delivery.sqlite', size=len(data),
                                sha256=sha(data), b64=base64.b64encode(data).decode('ascii')))
        for path in _files(content_root, ['delivery/public.json', 'delivery/publications',
                                          'instance/uploads', 'static/uploads']):
            name = str(path.relative_to(content_root)).replace('\\', '/')
            data = path.read_bytes()
            entries.append(dict(path=name, size=len(data), sha256=sha(data),
                                b64=base64.b64encode(data).decode('ascii')))
    payload = dict(version=1, side='content', created=now, origin=placement['origin'],
                   generation=placement['generation'], fence=placement['fence'],
                   mode='separated',
                   data=dict(placement=placement, history=workspace.history(500),
                             preserve=workspace.preserve_report()),
                   files=entries)
    digest, size = _write_bundle(bundle_path, payload, passphrase)
    return dict(side='content', digest=digest, size=size, generation=placement['generation'],
                files=len(entries), history=len(payload['data']['history']))


def import_content(bundle_path, destination_root, passphrase, *, origin, counterpart='',
                   root_spki=None, group_id=None):
    _, payload = _read_bundle(bundle_path, passphrase)
    if payload.get('side') != 'content' or payload.get('version') != 1:
        raise RelocationError('relocation_bundle_refused')
    destination_root = Path(destination_root)
    if destination_root.exists() and any(destination_root.iterdir()):
        raise RelocationError('relocation_destination_not_empty')
    for entry in payload['files']:
        name = entry['path']
        if name.startswith('/') or '..' in Path(name).parts:
            raise RelocationError('relocation_path_refused')
        data = base64.b64decode(entry['b64'], validate=True)
        if len(data) != entry['size'] or sha(data) != entry['sha256']:
            raise RelocationError('relocation_digest_refused')
        target = destination_root / name
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.exists():
            raise RelocationError('relocation_destination_not_empty')
        target.write_bytes(data)
    if root_spki is None or group_id is None:
        raise RelocationError('relocation_trust_required')
    workspace = Workspace(destination_root / 'workspace.sqlite', root_spki, group_id, origin)
    placement = payload['data']['placement']
    workspace.configure_placement('separated', origin, generation=placement['generation'],
                                  active=0, fence=payload['fence'], handoff=0,
                                  counterpart=counterpart)
    if [item['id'] for item in workspace.history(500)] != [
            item['id'] for item in payload['data']['history']]:
        raise RelocationError('relocation_history_mismatch')
    if workspace.preserve_report() != payload['data']['preserve']:
        raise RelocationError('relocation_counts_mismatch')
    return dict(side='content', generation=placement['generation'], fence=payload['fence'],
                origin=origin, history=len(payload['data']['history']))


def activate_workspace(workspace, generation, fence, origin):
    workspace.activate(generation, fence, origin)
    return dict(state='active', generation=workspace.placement()['generation'])


def _acceptance_spki(payload):
    if not payload.get('acceptance_pem'):
        return None
    from kiosk.trust.crypto import load_private, spki_der
    return base64.b64encode(spki_der(load_private(payload['acceptance_pem']))).decode('ascii')
