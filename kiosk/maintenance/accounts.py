"""Maintenance accounts: password verifiers, blocking and authentication epochs."""
from __future__ import annotations

from werkzeug.security import check_password_hash, generate_password_hash

from kiosk.core.credentials import validate_password
from kiosk.delivery.protocol import text
from .store import MaintenanceError
from . import permissions


def create_user(db, user_id, password, role='user', display_name='', now=0, actor=None):
    text(user_id, 64)
    if role not in ('administrator', 'user'):
        raise MaintenanceError('account_role_refused')
    if actor is not None and role == 'administrator':
        # Only a full system administrator may create another administrator role.
        actor_permissions = permissions.permissions_for(db, actor)
        if not permissions.BUNDLES['system-administrator'] <= actor_permissions:
            raise MaintenanceError('delegation_exceeds_scope', 403)
    validate_password(password)
    if db.execute('SELECT 1 FROM users WHERE id=?', (user_id,)).fetchone():
        raise MaintenanceError('account_exists', 409)
    db.execute('INSERT INTO users (id,password_hash,display_name,role,blocked,auth_epoch,'
               'created,updated) VALUES (?,?,?,?,0,0,?,?)',
               (user_id, generate_password_hash(password), display_name[:120], role, now, now))
    return {'user_id': user_id, 'role': role}


def authenticate(db, user_id, password):
    """Return the account row for a correct password; no session is created here."""
    if not isinstance(user_id, str) or not isinstance(password, str):
        return None
    try:
        text(user_id, 64)
    except ValueError:
        return None
    row = db.execute('SELECT * FROM users WHERE id=?', (user_id,)).fetchone()
    if row is None or row['blocked']:
        return None
    if not check_password_hash(row['password_hash'], password):
        return None
    return row


def find(db, user_id):
    row = db.execute('SELECT * FROM users WHERE id=?', (user_id,)).fetchone()
    return dict(row) if row else None


def list_users(db):
    return [dict(row) for row in db.execute(
        'SELECT id,display_name,role,blocked,created,updated FROM users ORDER BY id')]


def set_password(db, actor, user_id, password, now):
    if actor != user_id:
        permissions.require(db, actor, permissions.ACCOUNT_GRANT)
        permissions.require_account_authority(db, actor, user_id)
    validate_password(password)
    cursor = db.execute(
        'UPDATE users SET password_hash=?, auth_epoch=auth_epoch+1, updated=? WHERE id=?',
        (generate_password_hash(password), now, user_id))
    if cursor.rowcount != 1:
        raise MaintenanceError('account_not_found', 404)
    # Password replacement invalidates every session and refresh path for the user.
    db.execute("UPDATE sessions SET state='ended', ended_reason='password_changed' "
               "WHERE user_id=? AND state!='ended'", (user_id,))
    return True


def block(db, actor, user_id, now):
    """Blocking is reversible and never deletes work or accepted publications."""
    permissions.require(db, actor, permissions.ACCOUNT_GRANT)
    permissions.require_account_authority(db, actor, user_id)
    if actor == user_id:
        raise MaintenanceError('self_block_refused')
    cursor = db.execute(
        'UPDATE users SET blocked=1, auth_epoch=auth_epoch+1, updated=? WHERE id=?',
        (now, user_id))
    if cursor.rowcount != 1:
        raise MaintenanceError('account_not_found', 404)
    db.execute("UPDATE sessions SET state='ended', ended_reason='account_blocked' "
               "WHERE user_id=? AND state!='ended'", (user_id,))
    return True


def unblock(db, actor, user_id, now):
    permissions.require(db, actor, permissions.ACCOUNT_GRANT)
    permissions.require_account_authority(db, actor, user_id)
    cursor = db.execute('UPDATE users SET blocked=0, updated=? WHERE id=?', (now, user_id))
    if cursor.rowcount != 1:
        raise MaintenanceError('account_not_found', 404)
    return True


def add_team(db, team_id, name, now):
    text(team_id, 64)
    if db.execute('SELECT 1 FROM teams WHERE id=?', (team_id,)).fetchone():
        raise MaintenanceError('team_exists', 409)
    db.execute('INSERT INTO teams VALUES (?,?,?)', (team_id, name[:120], now))
    return {'team_id': team_id}


def add_membership(db, actor, team_id, user_id, now):
    permissions.require(db, actor, permissions.ACCOUNT_GRANT)
    if db.execute('SELECT 1 FROM teams WHERE id=?', (team_id,)).fetchone() is None:
        raise MaintenanceError('team_not_found', 404)
    if db.execute('SELECT 1 FROM users WHERE id=?', (user_id,)).fetchone() is None:
        raise MaintenanceError('account_not_found', 404)
    # Joining a team confers every grant that team holds, including to the actor
    # itself. The actor must already be able to grant each of them.
    permissions.require_membership_authority(db, actor, team_id)
    db.execute('INSERT OR IGNORE INTO memberships VALUES (?,?)', (user_id, team_id))
    return True


def remove_membership(db, actor, team_id, user_id, now):
    permissions.require(db, actor, permissions.ACCOUNT_GRANT)
    # Leaving a team withdraws the same scope, so it is limited the same way.
    permissions.require_membership_authority(db, actor, team_id)
    db.execute('DELETE FROM memberships WHERE user_id=? AND team_id=?', (user_id, team_id))
    return True
