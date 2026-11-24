"""Browser sessions, lock/switch, temporary connections and revocation.

One server-side session registry is authoritative. A copied cookie, a cached tab
or the browser Back button cannot revive a terminated session, and a lock is not
an extension of expiry. Only an explicitly trusted session may perform privileged
or signing actions; trust comes from an administrator-approved retained terminal
or from a single-use approval by an already trusted session of the same user.
"""
from __future__ import annotations

import hashlib
import secrets

from kiosk.delivery.protocol import decode, encode, text
from . import accounts, permissions
from .store import MaintenanceError

IDLE_SECONDS = 20 * 60
ABSOLUTE_SECONDS = 8 * 3600
TEMPORARY_SECONDS = 4 * 3600
CONNECTION_SECONDS = 300
CONNECTION_ATTEMPTS = 5
MAX_TERMINAL_SESSIONS = 64
CODE_ALPHABET = 'ABCDEFGHJKLMNPQRSTUVWXYZ23456789'
CODE_LENGTH = 8


def _secret():
    return secrets.token_hex(32)


def _digest(value):
    if not isinstance(value, str) or len(value) != 64 or not value.isascii():
        raise MaintenanceError('session_required', 401)
    return hashlib.sha256(value.encode('ascii')).hexdigest()


def _code(db, now):
    for _ in range(64):
        value = ''.join(secrets.choice(CODE_ALPHABET) for _ in range(CODE_LENGTH))
        row = db.execute('SELECT 1 FROM connections WHERE code=? AND expires>?', (value, now)).fetchone()
        if row is None:
            return value
    raise MaintenanceError('connection_capacity', 429)


def _terminal(db, terminal_id, now):
    if not isinstance(terminal_id, str) or len(terminal_id) != 32 or not terminal_id.isascii():
        raise MaintenanceError('terminal_binding_required')
    row = db.execute('SELECT * FROM terminals WHERE id=?', (terminal_id,)).fetchone()
    return dict(row) if row else None


def terminal_session_allowed(terminal, user_id, group_id=None):
    """Password trust on a retained terminal is limited to its approved policy."""
    if not terminal or not terminal['approved'] or not terminal['retained']:
        return False
    try:
        policy = decode(terminal['policy'].encode('utf-8')) if isinstance(terminal['policy'], str) else {}
    except ValueError:
        return False
    users = policy.get('users') or []
    groups = policy.get('groups') or []
    if users and user_id not in users:
        return False
    if group_id is not None and groups and group_id not in groups:
        return False
    return True


def approve_terminal(db, actor, terminal_id, name, users, groups, retained=True, now=0):
    """Administrator-only retained terminal enrollment (also used by local setup)."""
    if not isinstance(terminal_id, str) or len(terminal_id) != 32 or not terminal_id.isascii():
        raise MaintenanceError('terminal_binding_required')
    if actor is not None:
        permissions.require(db, actor, permissions.DEVICE_ENROLL)
    if not isinstance(users, list) or not users or len(users) > 64:
        raise MaintenanceError('terminal_policy_refused')
    if not isinstance(groups, list) or not groups or len(groups) > permissions.MAX_GROUPS:
        raise MaintenanceError('terminal_policy_refused')
    if actor is not None and not set(groups) <= set(permissions.admin_scope(db, actor)):
        raise MaintenanceError('delegation_exceeds_scope', 403)
    for item in users:
        text(item, 64)
        if db.execute('SELECT 1 FROM users WHERE id=?', (item,)).fetchone() is None:
            raise MaintenanceError('account_not_found', 404)
    for item in groups:
        text(item, 64)
    policy = encode({'users': sorted(set(users)), 'groups': sorted(set(groups))})
    db.execute('INSERT INTO terminals VALUES (?,?,1,?,?,?,?) '
               'ON CONFLICT(id) DO UPDATE SET name=excluded.name,approved=1,retained=excluded.retained,'
               'approved_by=excluded.approved_by,approved_at=excluded.approved_at,policy=excluded.policy',
               (terminal_id, name[:120], int(retained), actor, now, policy))
    return terminal_id


def register_terminal(db, terminal_id, name=''):
    if not isinstance(terminal_id, str) or len(terminal_id) != 32 or not terminal_id.isascii():
        raise MaintenanceError('terminal_binding_required')
    db.execute('INSERT OR IGNORE INTO terminals VALUES (?,?,0,0,NULL,NULL,?)',
               (terminal_id, name[:120], '{}'))


def start_password_session(store, db, user_id, password, terminal_id, *, remote='', agent='',
                           now=None, group_id=None):
    now = store.now() if now is None else int(now)
    row = accounts.authenticate(db, user_id, password)
    if row is None:
        raise MaintenanceError('invalid_credentials', 401)
    terminal = _terminal(db, terminal_id, now)
    if terminal is None:
        register_terminal(db, terminal_id)
        terminal = _terminal(db, terminal_id, now)
    trusted = terminal_session_allowed(terminal, user_id, group_id)
    if not trusted and row['role'] == 'administrator':
        # Installation-administrator bootstrap: the account that owns the
        # retained trust configuration may administer from a new terminal.
        # Ordinary accounts (and every shared-terminal switch) still require the
        # administrator-approved terminal policy or an explicit QR/code approval.
        trusted = permissions.BUNDLES['system-administrator'] <= permissions.permissions_for(
            db, user_id)
    return _create(db, row, terminal_id, now, 'password', trusted, temporary=not trusted,
                   parent=None, connection=None, remote=remote, agent=agent)


def _create(db, row, terminal_id, now, method, trusted, *, temporary, parent, connection,
            remote, agent, lifetime=None):
    total = int(lifetime or (TEMPORARY_SECONDS if temporary else ABSOLUTE_SECONDS))
    count = db.execute("SELECT COUNT(*) FROM sessions WHERE terminal_id=? AND state!='ended'",
                       (terminal_id,)).fetchone()[0]
    if count >= MAX_TERMINAL_SESSIONS:
        raise MaintenanceError('terminal_session_capacity', 429)
    secret = _secret()
    # The primary key is a stable, random identity. It is never the cookie digest,
    # so rotating or resuming a session cannot orphan its children, approvals or
    # review tickets. Only secret_sha256 changes on rotation.
    identity = secrets.token_hex(32)
    db.execute('INSERT INTO sessions VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)',
               (identity, row['id'], terminal_id, _digest(secret), now, now, now + total,
                now + IDLE_SECONDS, 'active', method, int(trusted), int(temporary), parent,
                connection, row['auth_epoch'], remote[:64], agent[:160], now, ''))
    return secret, dict(id=identity, user_id=row['id'], trusted=bool(trusted),
                        temporary=bool(temporary))


def _invalid(db, row, now):
    """Return an end reason when this stored session may no longer act."""
    if row['state'] == 'ended':
        return 'ended'
    if now < row['issued'] or now >= row['expires'] or now >= row['idle_deadline']:
        return 'expired'
    user = db.execute('SELECT blocked, auth_epoch FROM users WHERE id=?',
                      (row['user_id'],)).fetchone()
    if user is None or user['blocked'] or user['auth_epoch'] != row['epoch']:
        return 'authority_changed'
    return None


def _end(db, identity, reason):
    db.execute("UPDATE sessions SET state='ended', ended_reason=? WHERE id=?",
               (reason, identity))
    _cascade(db, identity, 'parent_ended')


def _ancestors_valid(db, row, now):
    """Validate the approval chain, not only the presented cookie.

    A temporary session is only as good as the trusted session that approved it,
    so an idle/absolute expiry, logout, block or password change of any ancestor
    ends the descendant instead of leaving it alive until its own deadline.
    """
    parent, seen = row['parent'], {row['id']}
    while parent:
        if parent in seen or len(seen) > 32:
            return False
        seen.add(parent)
        ancestor = db.execute('SELECT * FROM sessions WHERE id=?', (parent,)).fetchone()
        if ancestor is None or _invalid(db, ancestor, now):
            return False
        parent = ancestor['parent']
    return True


def lookup(store, db, secret, *, now=None, touch=True):
    """Return the live session row; expire it in place when a limit is reached."""
    now = store.now() if now is None else int(now)
    row = db.execute('SELECT * FROM sessions WHERE secret_sha256=?',
                     (_digest(secret),)).fetchone()
    if row is None:
        raise MaintenanceError('session_required', 401)
    reason = _invalid(db, row, now)
    if reason is not None:
        _end(db, row['id'], 'expired' if reason == 'expired' else
             ('authority_changed' if reason == 'authority_changed' else 'ended'))
        raise MaintenanceError('session_ended' if reason == 'ended' else 'session_expired',
                               401)
    if not _ancestors_valid(db, row, now):
        _end(db, row['id'], 'parent_ended')
        raise MaintenanceError('session_expired', 401)
    if touch:
        db.execute('UPDATE sessions SET touched=?, last_contact=?, idle_deadline=? WHERE id=?',
                   (now, now, now + IDLE_SECONDS, row['id']))
        row = db.execute('SELECT * FROM sessions WHERE id=?', (row['id'],)).fetchone()
    return row


def _cascade(db, session_id, reason):
    """End every descendant temporary session and its unused approvals."""
    rows = db.execute(
        'WITH RECURSIVE children(id) AS ('
        ' SELECT id FROM sessions WHERE parent=?'
        ' UNION ALL SELECT s.id FROM sessions s JOIN children c ON s.parent=c.id)'
        ' SELECT id FROM children', (session_id,)).fetchall()
    identifiers = [row['id'] for row in rows]
    for identity in identifiers:
        db.execute("UPDATE sessions SET state='ended', ended_reason=? WHERE id=?",
                   (reason, identity))
    for identity in [session_id, *identifiers]:
        db.execute('DELETE FROM connections WHERE approved_by=? AND consumed=0',
                   (identity,))


def lock(store, db, secret, now=None):
    row = lookup(store, db, secret, now=now, touch=False)
    if row['state'] != 'active':
        raise MaintenanceError('session_not_active', 409)
    # Lock must not extend the idle deadline: keep touched/idle_deadline unchanged.
    db.execute("UPDATE sessions SET state='locked' WHERE id=?", (row['id'],))
    return dict(id=row['id'], state='locked', user_id=row['user_id'])


def suspend(store, db, secret, *, now=None):
    """Suspend a workspace for switching: lock it and hide its content."""
    return lock(store, db, secret, now=now)


def _reopen(store, db, row, user_id, account, now, remote, agent):
    new_secret = _secret()
    db.execute('UPDATE sessions SET secret_sha256=?, state=?, touched=?, idle_deadline=?, '
               'last_contact=?, remote=?, agent=?, epoch=? WHERE id=?',
               (_digest(new_secret), 'active', now, now + IDLE_SECONDS, now, remote[:64],
                agent[:160], account['auth_epoch'], row['id']))
    return new_secret, dict(id=row['id'], user_id=user_id, state='active',
                            trusted=bool(row['trusted']), temporary=bool(row['temporary']))


def resume(store, db, secret, user_id, password, *, now=None, remote='', agent=''):
    """Credential-checked return that rotates the session secret in place."""
    now = store.now() if now is None else int(now)
    row = db.execute('SELECT * FROM sessions WHERE secret_sha256=?',
                     (_digest(secret),)).fetchone()
    if row is None or row['state'] == 'ended':
        raise MaintenanceError('session_expired', 401)
    if row['user_id'] != user_id:
        raise MaintenanceError('session_binding_refused', 403)
    if _invalid(db, row, now) is not None or not _ancestors_valid(db, row, now):
        _end(db, row['id'], 'expired')
        raise MaintenanceError('session_expired', 401)
    account = accounts.authenticate(db, user_id, password)
    if account is None:
        raise MaintenanceError('invalid_credentials', 401)
    return _reopen(store, db, row, user_id, account, now, remote, agent)


def resume_suspended(store, db, terminal_id, user_id, password, *, now=None, remote='',
                     agent=''):
    """Return to a suspended workspace: identify it by terminal and account.

    The browser never stores another account's session secret. Only a session
    already locked on this exact terminal can be reopened, and only with that
    account's password; an administrator session is never resumed silently.
    """
    now = store.now() if now is None else int(now)
    rows = db.execute("SELECT * FROM sessions WHERE terminal_id=? AND user_id=? "
                      "AND state='locked' ORDER BY issued DESC LIMIT 8",
                      (terminal_id, user_id)).fetchall()
    for row in rows:
        if _invalid(db, row, now) is not None or not _ancestors_valid(db, row, now):
            _end(db, row['id'], 'expired')
            continue
        account = accounts.authenticate(db, user_id, password)
        if account is None:
            raise MaintenanceError('invalid_credentials', 401)
        return _reopen(store, db, row, user_id, account, now, remote, agent)
    raise MaintenanceError('suspended_workspace_missing', 404)


def suspended(store, db, terminal_id, *, now=None):
    """Locked workspaces on this terminal, for the switch/return interface."""
    now = store.now() if now is None else int(now)
    result = []
    for row in db.execute("SELECT * FROM sessions "
                          "WHERE terminal_id=? AND state='locked' ORDER BY issued DESC",
                          (terminal_id,)).fetchall():
        if _invalid(db, row, now) is not None or not _ancestors_valid(db, row, now):
            continue
        result.append(dict(id=row['id'], user_id=row['user_id'], expires=row['expires']))
    return result


def rotate(store, db, secret, *, now=None):
    """Rotate the session secret so an old refresh path/cookie copy is invalid.

    The stable primary key is preserved, so descendants, approval references and
    review tickets keep pointing at the same session.
    """
    row = lookup(store, db, secret, now=now)
    new_secret = _secret()
    db.execute('UPDATE sessions SET secret_sha256=? WHERE id=?',
               (_digest(new_secret), row['id']))
    return new_secret, row['id']


def end(store, db, secret, reason='signed_out', now=None):
    row = db.execute('SELECT * FROM sessions WHERE secret_sha256=?',
                     (_digest(secret),)).fetchone()
    if row is None:
        return False
    db.execute("UPDATE sessions SET state='ended', ended_reason=? WHERE id=?",
               (reason, row['id']))
    _cascade(db, row['id'], 'parent_ended')
    return True


def terminate(store, db, actor_id, session_id, now=None):
    row = db.execute('SELECT * FROM sessions WHERE id=?', (session_id,)).fetchone()
    if row is None:
        raise MaintenanceError('session_not_found', 404)
    if row['user_id'] != actor_id:
        permissions.require(db, actor_id, permissions.CONNECTIONS_MODERATE)
        # Moderating another account's session is an authority change; it is
        # limited to accounts whose authority the actor could itself confer.
        permissions.require_account_authority(db, actor_id, row['user_id'])
    db.execute("UPDATE sessions SET state='ended', ended_reason='terminated' WHERE id=?",
               (session_id,))
    _cascade(db, session_id, 'terminated')
    return True


def terminate_user_on_terminal(store, db, actor_id, terminal_id, now=None):
    """End every session this account has on the exact terminal, including locked."""
    rows = db.execute("SELECT id FROM sessions WHERE user_id=? AND terminal_id=? AND state!='ended'",
                      (actor_id, terminal_id)).fetchall()
    for row in rows:
        db.execute("UPDATE sessions SET state='ended', ended_reason='all_terminated' WHERE id=?",
                   (row['id'],))
        _cascade(db, row['id'], 'all_terminated')
    return len(rows)


def list_sessions(store, db, user_id, *, now=None, all_users=False):
    now = store.now() if now is None else int(now)
    query = ('SELECT id,user_id,terminal_id,issued,touched,expires,idle_deadline,state,auth_method,'
             'trusted,temporary,last_contact,remote,agent,ended_reason FROM sessions ')
    rows = db.execute(query + ('ORDER BY last_contact DESC LIMIT 200' if all_users else
                              'WHERE user_id=? ORDER BY last_contact DESC LIMIT 100'),
                      () if all_users else (user_id,)).fetchall()
    result = []
    for row in rows:
        item = dict(row)
        item['trusted'] = bool(item['trusted'])
        item['temporary'] = bool(item['temporary'])
        item['expired'] = item['state'] == 'ended' or now >= item['expires'] or now >= item['idle_deadline']
        result.append(item)
    return result


# -- single-use connection requests -----------------------------------------

def create_connection(store, db, kind, terminal_id, browser_secret, summary, *,
                      requested_user='', target_user='', document=None, now=None):
    if kind not in ('login', 'terminal', 'device'):
        raise MaintenanceError('connection_kind_refused')
    now = store.now() if now is None else int(now)
    if not isinstance(browser_secret, str) or len(browser_secret) != 64:
        raise MaintenanceError('browser_binding_required')
    if not isinstance(summary, str) or not 1 <= len(summary) <= 120:
        raise MaintenanceError('browser_summary_refused')
    if requested_user:
        text(requested_user, 64)
    if target_user:
        text(target_user, 64)
    _terminal(db, terminal_id, now)
    db.execute('DELETE FROM connections WHERE expires<=?', (now,))
    pending = db.execute('SELECT COUNT(*) FROM connections WHERE terminal_id=? AND approved=0',
                         (terminal_id,)).fetchone()[0]
    if pending >= 5 or db.execute('SELECT COUNT(*) FROM connections').fetchone()[0] >= 512:
        raise MaintenanceError('connection_capacity', 429)
    identity = secrets.token_hex(32)
    code = _code(db, now)
    record = dict(version=1, kind=kind, id=identity, code=code, origin='', terminal=terminal_id,
                  summary=summary, requested_user=requested_user, target_user=target_user,
                  issued=now, expires=now + CONNECTION_SECONDS)
    db.execute('INSERT INTO connections VALUES (?,?,?,?,?,?,?,?,?,?,?,0,NULL,0,0,?)',
               (identity, kind, code, hashlib.sha256(browser_secret.encode()).hexdigest(),
                terminal_id, requested_user, target_user, summary, '', now,
                now + CONNECTION_SECONDS, encode(record if document is None else
                                                 {**record, 'document': document})))
    return identity, record


def set_origin(db, identity, origin):
    row = db.execute('SELECT document FROM connections WHERE id=?', (identity,)).fetchone()
    if row is None:
        raise MaintenanceError('connection_not_found', 404)
    record = decode(row['document'])
    record['origin'] = origin
    db.execute('UPDATE connections SET origin=?, document=? WHERE id=?',
               (origin, encode(record), identity))
    return record


def connection(store, db, identity):
    row = db.execute('SELECT * FROM connections WHERE id=?', (identity,)).fetchone()
    if row is None:
        raise MaintenanceError('connection_not_found', 404)
    return row


def _policy_document(document):
    """Validate the policy a terminal/device request asks an administrator to bind."""
    if document is None:
        return {}
    if not isinstance(document, dict):
        raise MaintenanceError('connection_document_refused')
    groups = document.get('groups') or []
    users = document.get('users') or []
    targets = document.get('targets') or []
    if (not isinstance(groups, list) or len(groups) > permissions.MAX_GROUPS or
            any(not isinstance(item, str) for item in groups)):
        raise MaintenanceError('connection_document_refused')
    if (not isinstance(users, list) or len(users) > 64 or
            any(not isinstance(item, str) for item in users)):
        raise MaintenanceError('connection_document_refused')
    if (not isinstance(targets, list) or len(targets) > 64 or
            any(not isinstance(item, str) for item in targets)):
        raise MaintenanceError('connection_document_refused')
    return dict(name=str(document.get('name') or '')[:120], users=users, groups=groups,
                targets=targets, role=document.get('role', 'user'),
                permissions=document.get('permissions'))


def approve_connection(store, db, approver_secret, identity, code, *, now=None):
    """One explicit approval from an already trusted session.

    A temporary browser connection may only be approved for the approver's own
    account; approving somebody else's login from an existing session is exactly
    the bypass the policy forbids. Retained terminal/device enrollment requires
    the enrollment permission instead, and the requested policy must itself stay
    inside the approver's scope.
    """
    now = store.now() if now is None else int(now)
    session = lookup(store, db, approver_secret, now=now, touch=False)
    if session['state'] != 'active':
        raise MaintenanceError('session_locked', 403)
    if not session['trusted']:
        raise MaintenanceError('trusted_session_required', 403)
    row = connection(store, db, identity)
    if row['expires'] <= now:
        raise MaintenanceError('connection_expired', 410)
    if row['approved']:
        raise MaintenanceError('connection_already_approved', 409)
    if row['attempts'] >= CONNECTION_ATTEMPTS:
        raise MaintenanceError('connection_attempt_limit', 429)
    if not isinstance(code, str) or len(code) != CODE_LENGTH or not secrets.compare_digest(code, row['code']):
        db.execute('UPDATE connections SET attempts=attempts+1 WHERE id=?', (identity,))
        raise MaintenanceError('connection_code_refused', 403)
    if row['kind'] == 'login':
        if row['requested_user'] != session['user_id']:
            raise MaintenanceError('connection_user_mismatch', 403)
    elif row['kind'] == 'terminal':
        permissions.require(db, session['user_id'], permissions.DEVICE_ENROLL)
        if not row['target_user']:
            raise MaintenanceError('connection_target_required')
    else:
        permissions.require(db, session['user_id'], permissions.DEVICE_ENROLL)
    if row['kind'] in ('terminal', 'device'):
        document = _policy_document(decode(row['document']).get('document'))
        if row['kind'] == 'terminal' and document['users']:
            # A retained terminal only lets named accounts log in; the approver
            # must be able to manage each of them.
            for user in document['users']:
                permissions.require_account_authority(db, session['user_id'], user)
        admin_groups = set(permissions.admin_scope(db, session['user_id']))
        if document['groups'] and not set(document['groups']) <= admin_groups:
            raise MaintenanceError('delegation_exceeds_scope', 403)
    db.execute('UPDATE connections SET approved=1, approved_by=? WHERE id=?',
               (session['id'], identity))
    return dict(row=row, approver=session['user_id'], approver_session=session['id'])


def find_connection(store, db, code, *, now=None):
    """Resolve one pending request from its manual code (no internal id needed)."""
    now = store.now() if now is None else int(now)
    if not isinstance(code, str):
        raise MaintenanceError('connection_code_refused', 403)
    normalized = code.strip().upper()
    if len(normalized) != CODE_LENGTH:
        raise MaintenanceError('connection_code_refused', 403)
    rows = db.execute('SELECT * FROM connections WHERE code=? AND expires>? AND consumed=0 '
                      'ORDER BY issued DESC LIMIT 2', (normalized, now)).fetchall()
    if not rows:
        raise MaintenanceError('connection_not_found', 404)
    if len(rows) > 1:
        raise MaintenanceError('connection_code_ambiguous', 409)
    return rows[0]


def consume_connection(store, db, identity, browser_secret, *, now=None):
    now = store.now() if now is None else int(now)
    row = connection(store, db, identity)
    if row['expires'] <= now:
        raise MaintenanceError('connection_expired', 410)
    if hashlib.sha256(browser_secret.encode()).hexdigest() != row['browser']:
        raise MaintenanceError('browser_binding_refused', 403)
    if row['consumed']:
        raise MaintenanceError('connection_already_consumed', 409)
    if not row['approved']:
        return None
    return row


def consume_login(store, db, identity, browser_secret, *, remote='', agent='', now=None):
    """Create the temporary browser session for an approved login request."""
    now = store.now() if now is None else int(now)
    row = consume_connection(store, db, identity, browser_secret, now=now)
    if row is None:
        return None
    if row['kind'] != 'login':
        raise MaintenanceError('connection_kind_refused')
    approver = db.execute('SELECT * FROM sessions WHERE id=?', (row['approved_by'],)).fetchone()
    # Recheck the approving session itself, not only its stored row: it may have
    # been blocked, logged out or idle-expired after the single approval click.
    if (approver is None or approver['state'] != 'active' or
            _invalid(db, approver, now) is not None or
            not _ancestors_valid(db, approver, now)):
        raise MaintenanceError('approval_expired', 410)
    user = db.execute('SELECT * FROM users WHERE id=?', (row['requested_user'],)).fetchone()
    if user is None or user['blocked']:
        raise MaintenanceError('account_unavailable', 403)
    lifetime = min(TEMPORARY_SECONDS, max(0, approver['expires'] - now))
    if lifetime <= 0:
        raise MaintenanceError('approval_expired', 410)
    secret, session = _create(db, user, row['terminal_id'], now, 'approved', True,
                              temporary=True, parent=approver['id'], connection=row['id'],
                              remote=remote, agent=agent, lifetime=lifetime)
    db.execute('UPDATE connections SET consumed=1 WHERE id=?', (row['id'],))
    return secret, session


def consume_terminal(store, db, identity, browser_secret, *, now=None):
    """Record the approved retained-terminal policy on the requesting terminal."""
    now = store.now() if now is None else int(now)
    row = consume_connection(store, db, identity, browser_secret, now=now)
    if row is None:
        return None
    if row['kind'] != 'terminal':
        raise MaintenanceError('connection_kind_refused')
    approver = db.execute('SELECT * FROM sessions WHERE id=?', (row['approved_by'],)).fetchone()
    if (approver is None or approver['state'] != 'active' or
            _invalid(db, approver, now) is not None or
            not _ancestors_valid(db, approver, now)):
        raise MaintenanceError('approval_expired', 410)
    document = _policy_document(decode(row['document']).get('document'))
    groups = document['groups']
    users = document['users'] or [row['target_user']]
    if not users or not groups:
        raise MaintenanceError('terminal_policy_refused')
    # approve_terminal records the approving account, not the session identity.
    admin_groups = set(permissions.admin_scope(db, approver['user_id']))
    if not set(groups) <= admin_groups:
        raise MaintenanceError('delegation_exceeds_scope', 403)
    approve_terminal(db, approver['user_id'], row['terminal_id'],
                     document['name'] or 'Shared terminal', users, groups,
                     retained=True, now=now)
    db.execute('UPDATE connections SET consumed=1 WHERE id=?', (row['id'],))
    return dict(terminal=row['terminal_id'], users=users, groups=groups)


def connection_summary(store, db, row, *, now=None):
    """Human-readable binding for one explicit approval decision."""
    now = store.now() if now is None else int(now)
    document = _policy_document(decode(row['document']).get('document'))
    return dict(id=row['id'], code=row['code'], kind=row['kind'],
                terminal=row['terminal_id'], summary=row['summary'],
                requested_user=row['requested_user'], target_user=row['target_user'],
                origin=row['origin'], issued=row['issued'], expires=row['expires'],
                approved=bool(row['approved']), document=document)


def pending_connections(store, db, user_id, *, now=None):
    now = store.now() if now is None else int(now)
    rows = db.execute('SELECT * FROM connections WHERE expires>? AND consumed=0 '
                      'ORDER BY issued DESC LIMIT 50', (now,)).fetchall()
    result = []
    for row in rows:
        try:
            document = connection_summary(store, db, row, now=now)
        except MaintenanceError:
            continue
        result.append(document)
    return result
