"""Reviewer keys, scoped enrollment and acceptance receipts (Maintenance side).

Reviewer private keys live at this approving endpoint, never on the content
server. Enrollment of another account's device requires a root-authorized
scoped administrator grant and produces one non-delegating child; the signed
scope is what a display enforces. Acceptance receipts are signed by a separate
key held here, so the content server cannot manufacture historical authorization
after a later revocation.
"""
from __future__ import annotations

import base64
import time
from pathlib import Path

from kiosk.delivery.protocol import decode, digest, encode, text, sha
from kiosk.publication import authority as a
from kiosk.trust.crypto import (generate_private_key, key_id, load_private, private_pem,
                                spki_der)
from . import keystore
from .store import MaintenanceError

MAX_SCOPE_GROUPS = 64
MAX_SCOPE_TARGETS = 64


def _b64(value):
    return base64.b64encode(value).decode('ascii')


class MaintenanceAuthority:
    def __init__(self, store, secrets_dir, public, policy, *, clock=time.time):
        self.store, self.secrets_dir = store, Path(secrets_dir)
        self.secrets_dir.mkdir(parents=True, exist_ok=True)
        self.public = dict(public)
        self.policy = policy
        self.root = base64.b64decode(self.public['root_spki'], validate=True)
        self.group_id = text(self.public['group_id'], 64)
        self.origin = a.origin(self.public['origin'])
        self.clock = clock
        # Older installations stored a policy with each endpoint grant. Retain
        # the highest authenticated policy globally, so recovery/revocation of
        # one endpoint cannot leave another signing under an older revocation set.
        with store.connection() as db:
            candidates = [policy]
            saved = db.execute('SELECT envelope FROM publisher_policy').fetchone()
            if saved is not None:
                candidates.append(decode(bytes(saved['envelope'])))
            candidates += [decode(bytes(item['policy'])) for item in db.execute(
                'SELECT policy FROM keys WHERE policy IS NOT NULL')]
            selected, selected_value = None, None
            for envelope in candidates:
                value = a.verified(envelope, self.root, 'policy')
                value = a.policy(envelope, self.root, self.group_id, self.origin, value['issued'])
                if selected_value is None or value['version'] > selected_value['version']:
                    selected, selected_value = envelope, value
                elif value['version'] == selected_value['version'] and encode(envelope) != encode(selected):
                    raise MaintenanceError('publisher_policy_conflict', 409)
            db.execute('INSERT OR REPLACE INTO publisher_policy VALUES (1,?,?)',
                       (selected_value['version'], encode(selected)))

    def _advance_policy(self, db, envelope):
        old = db.execute('SELECT * FROM publisher_policy').fetchone()
        value = a.policy(envelope, self.root, self.group_id, self.origin, self.now(),
                         floor=old['version'] if old else 0)
        raw = encode(envelope)
        if old is not None and old['version'] == value['version'] and bytes(old['envelope']) != raw:
            raise MaintenanceError('publisher_policy_conflict', 409)
        db.execute('INSERT OR REPLACE INTO publisher_policy VALUES (1,?,?)', (value['version'], raw))
        return value

    def now(self):
        return int(self.clock())

    # -- key material --------------------------------------------------------
    def _row(self, db, user_id):
        return db.execute('SELECT * FROM keys WHERE user_id=?', (user_id,)).fetchone()

    def _key(self, db, user_id):
        row = self._row(db, user_id)
        if row is None:
            return None, None
        raw = keystore.protect(bytes(row['protected']), self.secrets_dir, decrypt=True)
        key = load_private(raw.decode('ascii'))
        if key_id(key) != row['device_id'] or _b64(spki_der(key)) != row['spki']:
            raise MaintenanceError('key_identity_refused', 503)
        return row, key

    def ensure_key(self, db, user_id):
        """Create this account's endpoint key once; never replace a failed one."""
        row, key = self._key(db, user_id)
        if key is not None:
            return row, key
        key = generate_private_key()
        now = self.now()
        protected = keystore.protect(private_pem(key).encode('ascii'), self.secrets_dir)
        db.execute('INSERT INTO keys VALUES (?,?,?,?,?,NULL,NULL,?,?,?,?,?)',
                   (user_id, protected, _b64(spki_der(key)), key_id(key), 'user',
                    self.group_id, self.origin, '{}', now, 0))
        return self._row(db, user_id), key

    def identity(self, db, user_id):
        row, key = self._key(db, user_id)
        if key is None:
            raise MaintenanceError('reviewer_key_missing', 404)
        return dict(device_id=row['device_id'], device_key=row['spki'],
                    role=row['role'], granted=row['chain'] is not None,
                    expires=row['expires'])

    def install_grant(self, db, user_id, chain, policy_envelope, *, scope=None):
        """Bind one externally authorized (root-signed) grant to the local key."""
        row, key = self.ensure_key(db, user_id)
        current = a.policy(policy_envelope, self.root, self.group_id, self.origin, self.now())
        grant, signer = a.permission(chain, self.root, current, self.now())
        if signer != spki_der(key) or grant['user_id'] != user_id:
            raise MaintenanceError('grant_for_other_key', 409)
        self._store_grant(db, user_id, chain, policy_envelope, grant)
        return grant

    def recover_grant(self, db, user_id, chain, policy_envelope, *, root_pin, confirm):
        """Explicit root-authorized recovery of this endpoint's existing key.

        The old grant may be expired. It is never used to issue a replacement:
        the imported chain and higher policy must independently verify under the
        already pinned root. No key generation, root replacement or history reset.
        """
        from . import accounts
        if confirm is not True:
            raise MaintenanceError('confirmation_required')
        if root_pin != a.sha(self.root):
            raise MaintenanceError('publisher_root_confirmation_required', 403)
        account = accounts.find(db, user_id)
        row, key = self._key(db, user_id)
        if account is None or account['blocked'] or row is None or row['chain'] is None:
            raise MaintenanceError('retained_publisher_required', 409)
        old_envelope = decode(bytes(row['policy']))
        old = a.verified(old_envelope, self.root, 'policy')
        latest = db.execute('SELECT version FROM publisher_policy').fetchone()
        same = encode(policy_envelope) == bytes(row['policy']) and encode(chain) == bytes(row['chain'])
        current = a.policy(policy_envelope, self.root, self.group_id, self.origin,
                           self.now(), floor=max(old['version'] + (0 if same else 1), latest['version']))
        configured = a.verified(self.policy, self.root, 'policy')
        if current['version'] < configured['version']:
            raise MaintenanceError('publisher_policy_rollback', 409)
        grant, signer = a.permission(chain, self.root, current, self.now())
        if (signer != spki_der(key) or grant['user_id'] != user_id
                or grant['role'] != account['role']):
            raise MaintenanceError('grant_for_other_key', 409)
        self._store_grant(db, user_id, chain, policy_envelope, grant)
        self.store.audit(db, 'publisher_recovered', user_id, row['device_id'])
        return dict(device_id=row['device_id'], policy_version=current['version'],
                    expires=grant['expires'], root_replaced=False, already_current=same)

    def recovery_request(self, db, user_id, *, lan=None):
        import secrets
        row, key = self._key(db, user_id)
        if row is None or row['chain'] is None:
            raise MaintenanceError('retained_publisher_required', 409)
        now = self.now()
        document = dict(device_key=row['spki'], device_id=row['device_id'],
                        group_id=self.group_id, origin=self.origin, user_id=user_id,
                        action='add-device', nonce=secrets.token_hex(32), issued=now, expires=now + 90)
        result = dict(request=document, proof=a.signed(key, 'device-request', document))
        if lan is not None:
            current = decode(bytes(db.execute('SELECT envelope FROM publisher_policy').fetchone()['envelope']))
            import json
            result.update(lan=lan, policy=current, chain=json.loads(row['chain']))
            binding = dict(request_sha256=sha(encode(document)), lan_sha256=sha(encode(lan)),
                           policy_sha256=sha(encode(current)), chain_sha256=sha(encode(result['chain'])))
            result['lan_proof'] = a.signed(key, 'lan-maintenance-request', binding)
        return result

    def _store_grant(self, db, user_id, chain, policy_envelope, grant):
        self._advance_policy(db, policy_envelope)
        db.execute('UPDATE keys SET chain=?, policy=?, role=?, expires=?, scope=? WHERE user_id=?',
                   (encode(chain), encode(policy_envelope), grant['role'], grant['expires'],
                    encode(grant.get('scope') or {}), user_id))

    def grant(self, db, user_id):
        row, key = self._key(db, user_id)
        if row is None or row['chain'] is None:
            raise MaintenanceError('publisher_authority_missing', 403)
        import json
        raw = row['chain']
        chain = json.loads(raw if isinstance(raw, str) else bytes(raw).decode('utf-8'))
        latest = db.execute('SELECT * FROM publisher_policy').fetchone()
        envelope = decode(bytes(latest['envelope']))
        current = a.policy(envelope, self.root, self.group_id,
                           self.origin, self.now(), floor=latest['version'])
        grant, signer = a.permission(chain, self.root, current, self.now())
        if signer != spki_der(key):
            raise MaintenanceError('publisher_authority_refused', 403)
        return dict(chain=chain, policy=envelope, grant=grant, key=key,
                    row=row)

    def scope(self, db, user_id):
        row = self._row(db, user_id)
        if row is None:
            return None
        return decode(bytes(row['scope'])) if row['scope'] else None

    # -- scoped enrollment ---------------------------------------------------
    def enroll(self, db, actor_user, target_user, *, role, groups, targets, permissions=None,
               policy_envelope=None):
        """Administrator-only retained device enrollment within the actor's scope.

        The target account's key is created here and stays here. Only public
        permission material (`chain`, `policy`) is exported for the device/display.
        """
        text(target_user, 64)
        if role not in ('administrator', 'user'):
            raise MaintenanceError('account_role_refused')
        groups = sorted({text(item, 64) for item in groups})
        targets = sorted({text(item, 128) for item in targets})
        if not groups or len(groups) > MAX_SCOPE_GROUPS:
            raise MaintenanceError('scope_refused')
        if not targets or len(targets) > MAX_SCOPE_TARGETS:
            raise MaintenanceError('scope_refused')
        permissions = sorted(set(permissions or ('publish',)))
        if permissions != ['publish']:
            # Only publication authority is delegated to a display-verifiable grant.
            raise MaintenanceError('scope_refused')
        actor = self.grant(db, actor_user)
        parent = actor['grant']
        if parent['role'] != 'administrator' or not parent['can_delegate']:
            raise MaintenanceError('administrator_enrollment_required', 403)
        parent_scope = parent.get('scope')
        if parent_scope is not None:
            if (not set(groups) <= set(parent_scope['groups']) or
                    not set(targets) <= set(parent_scope['targets']) or
                    not set(permissions) <= set(parent_scope['permissions'])):
                raise MaintenanceError('delegation_exceeds_scope', 403)
        row, key = self.ensure_key(db, target_user)
        if target_user == actor_user:
            # The approval endpoint holds exactly one key per account; adding a
            # further same-account endpoint is the native device flow, not this one.
            raise MaintenanceError('self_enrollment_refused', 409)
        if row['chain'] is not None:
            raise MaintenanceError('retained_enrollment_exists', 409)
        now = self.now()
        policy_envelope = policy_envelope or actor['policy']
        current = a.policy(policy_envelope, self.root, self.group_id, self.origin, now)
        child = dict(group_id=self.group_id, origin=self.origin, user_id=target_user,
                     role=role, device_key=_b64(spki_der(key)), issued=now,
                     expires=min(parent['expires'], current['expires'],
                                 now + a.MAX_AUTHORITY_SECONDS),
                     can_delegate=False,
                     scope=dict(version=1, groups=groups, targets=targets,
                                permissions=permissions))
        if target_user == actor_user:
            raise MaintenanceError('self_enrollment_refused', 409)
        chain = a.signed(actor['key'], 'device', child)
        full = [actor['chain'][0], chain]
        grant, signer = a.permission(full, self.root, current, now)
        if signer != spki_der(key):
            raise MaintenanceError('grant_for_other_key', 409)
        self._store_grant(db, target_user, full, policy_envelope, grant)
        return dict(user_id=target_user, device_id=key_id(key), chain=full,
                    policy=policy_envelope, scope=grant['scope'], role=role,
                    expires=grant['expires'])

    # -- explicit publication signing ---------------------------------------
    def authorize_plan(self, db, user_id, plan, targets, now=None):
        """Recheck the exact frozen plan against the current signed grant."""
        now = self.now() if now is None else int(now)
        granted = self.grant(db, user_id)
        grant = granted['grant']
        if (plan['group_id'] != self.group_id or plan['origin'] != self.origin or
                plan['user_id'] != user_id or
                plan['device_id'] != key_id(granted['key'])):
            raise MaintenanceError('publication_scope_refused', 403)
        if plan['policy_version'] != a.policy(granted['policy'], self.root, self.group_id,
                                              self.origin, now)['version']:
            raise MaintenanceError('publication_policy_changed', 409)
        if plan['issued'] < grant['issued'] or plan['expires'] > grant['expires']:
            raise MaintenanceError('publication_authority_expired', 403)
        a.validate_plan(plan, now=now)
        scope = grant.get('scope')
        if scope is not None:
            if plan['group_id'] not in scope['groups']:
                raise MaintenanceError('publication_scope_refused', 403)
            if not {target['device_id'] for target in plan['targets']} <= set(scope['targets']):
                raise MaintenanceError('publication_targets_outside_scope', 403)
        if targets is not None and [t['device_id'] for t in targets] != [t['device_id'] for t in plan['targets']]:
            raise MaintenanceError('publication_targets_changed', 409)
        return granted

    def sign_publication(self, db, user_id, plan, targets, now=None):
        granted = self.authorize_plan(db, user_id, plan, targets, now)
        return dict(approval=a.signed(granted['key'], 'publication', plan),
                    chain=granted['chain'])

    # -- acceptance receipts -------------------------------------------------
    def _acceptance_key(self):
        path = self.secrets_dir / 'acceptance.key'
        if not path.exists():
            key = generate_private_key()
            path.write_bytes(keystore.protect(private_pem(key).encode('ascii'), self.secrets_dir))
            return key
        raw = keystore.protect(path.read_bytes(), self.secrets_dir, decrypt=True)
        return load_private(raw.decode('ascii'))

    def acceptance_identity(self):
        return _b64(spki_der(self._acceptance_key()))

    def sign_receipt(self, plan, approval, policy_version, commit_nonce, now=None):
        now = self.now() if now is None else int(now)
        key = self._acceptance_key()
        value = dict(version=1, plan_id=plan['id'],
                     publication_sha256=plan['publication_sha256'],
                     dependencies_sha256=plan['dependencies_sha256'],
                     targets_sha256=hashlib_targets(plan['targets']),
                     approver_user=plan['user_id'], approver_device=plan['device_id'],
                     policy_version=int(policy_version),
                     approval_sha256=a_text_sha(approval), commit_nonce=commit_nonce,
                     issued=now)
        return dict(receipt=a.signed(key, 'acceptance', value), value=value,
                    acceptance_key=_b64(spki_der(key)))

    def verify_receipt(self, envelope):
        return a.verified(envelope, spki_der(self._acceptance_key()), 'acceptance')


def hashlib_targets(targets):
    import hashlib
    return hashlib.sha256(encode(targets)).hexdigest()


def a_text_sha(value):
    import hashlib
    return hashlib.sha256(encode(value)).hexdigest()
