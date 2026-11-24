"""Small centralized permission model: named bundles plus explicit group scopes.

Deliberately not a general ACL or nested-group engine. A staff team is unrelated
to a display device group; both happen to be identified by stable strings. The
only authority is the explicit grant rows, so a role label on an account never
widens access by itself and a delegated administrator can never grant more than
it holds.
"""
from __future__ import annotations

import json

from kiosk.delivery.protocol import encode, text
from .store import MaintenanceError

CONTENT_READ = 'content.read'
CONTENT_EDIT = 'content.edit'
CONTENT_PUBLISH = 'content.publish'
ACCOUNT_GRANT = 'account.grant'
DEVICE_ENROLL = 'device.enroll'
CONNECTIONS_MODERATE = 'connections.moderate'
SERVICE_RELOCATE = 'service.relocate'

PERMISSIONS = frozenset({
    CONTENT_READ, CONTENT_EDIT, CONTENT_PUBLISH,
    ACCOUNT_GRANT, DEVICE_ENROLL, CONNECTIONS_MODERATE, SERVICE_RELOCATE,
})

BUNDLES = {
    'viewer': frozenset({CONTENT_READ}),
    'editor': frozenset({CONTENT_READ, CONTENT_EDIT}),
    'publisher': frozenset({CONTENT_READ, CONTENT_EDIT, CONTENT_PUBLISH}),
    'group-administrator': frozenset({
        CONTENT_READ, CONTENT_EDIT, CONTENT_PUBLISH,
        ACCOUNT_GRANT, DEVICE_ENROLL, CONNECTIONS_MODERATE,
    }),
    'system-administrator': frozenset(PERMISSIONS),
}

# Bundles whose holders may approve retained device enrollment / relocation.
ADMIN_BUNDLES = ('group-administrator', 'system-administrator')
MAX_GROUPS = 32


def _groups(value):
    if not isinstance(value, (list, tuple)) or not value or len(value) > MAX_GROUPS:
        raise MaintenanceError('scope_refused')
    cleaned = []
    for item in value:
        cleaned.append(text(item, 64))
    if len(set(cleaned)) != len(cleaned):
        raise MaintenanceError('scope_refused')
    return sorted(cleaned)


def bundle_permissions(bundle):
    try:
        return BUNDLES[bundle]
    except KeyError:
        raise MaintenanceError('permission_bundle_unknown') from None


def _rows(db, user_id):
    return db.execute(
        '''SELECT g.bundle, g.groups FROM grants g
           LEFT JOIN memberships m ON g.subject_type='team' AND m.team_id=g.subject_id
           WHERE (g.subject_type='user' AND g.subject_id=?)
              OR (g.subject_type='team' AND m.user_id=?)''',
        (user_id, user_id)).fetchall()


def grants_for(db, user_id):
    """Return (bundle, sorted groups) pairs after normalizing every row."""
    result = []
    for row in _rows(db, user_id):
        raw = row['groups']
        try:
            groups = json.loads(raw if isinstance(raw, str) else raw.decode('utf-8'))
            if (not isinstance(groups, list) or not groups or len(groups) > MAX_GROUPS or
                    any(not isinstance(item, str) for item in groups)):
                continue
            result.append((row['bundle'], tuple(groups)))
        except (ValueError, AttributeError):
            continue
    return result


def permissions_for(db, user_id, group_id=None):
    found = set()
    for bundle, groups in grants_for(db, user_id):
        if bundle not in BUNDLES:
            continue
        if group_id is not None and group_id not in groups:
            continue
        found |= BUNDLES[bundle]
    return found


def groups_for(db, user_id):
    found = set()
    for bundle, groups in grants_for(db, user_id):
        if bundle in BUNDLES:
            found |= set(groups)
    return found


def require(db, user_id, permission, group_id=None):
    if permission not in PERMISSIONS:
        raise MaintenanceError('permission_unknown')
    if permission not in permissions_for(db, user_id, group_id):
        raise MaintenanceError('permission_required', 403)
    return True


def grantable(db, actor, bundle, groups):
    """True when ``actor`` may confer this bundle in every one of ``groups``."""
    try:
        bundle_permissions(bundle)
    except MaintenanceError:
        return False
    for group in groups:
        held = permissions_for(db, actor, group)
        if ACCOUNT_GRANT not in held or not bundle_permissions(bundle) <= held:
            return False
    return True


def require_grantable_rows(db, actor, rows):
    """Refuse when any stored grant would let the actor widen its own scope.

    A membership change or an account block is an authority change for every
    grant the affected account can exercise, including indirect team grants.
    Delegated administration is therefore limited to the exact bundles and
    groups the actor could itself grant; otherwise a narrow administrator could
    join a broader team or block a broader administrator.
    """
    for row in rows:
        raw = row['groups']
        try:
            groups = json.loads(raw if isinstance(raw, str) else bytes(raw).decode('utf-8'))
        except (ValueError, TypeError):
            raise MaintenanceError('delegation_exceeds_scope', 403) from None
        if (not isinstance(groups, list) or not groups or len(groups) > MAX_GROUPS or
                any(not isinstance(item, str) for item in groups)):
            raise MaintenanceError('delegation_exceeds_scope', 403)
        if not grantable(db, actor, row['bundle'], groups):
            raise MaintenanceError('delegation_exceeds_scope', 403)
    return True


def require_account_authority(db, actor, target):
    """A delegated administrator may only change accounts inside its own scope."""
    if actor == target:
        return True
    if db.execute('SELECT 1 FROM users WHERE id=?', (target,)).fetchone() is None:
        raise MaintenanceError('account_not_found', 404)
    return require_grantable_rows(db, actor, _rows(db, target))


def require_membership_authority(db, actor, team_id):
    rows = db.execute("SELECT bundle, groups FROM grants WHERE subject_type='team' "
                      "AND subject_id=?", (team_id,)).fetchall()
    return require_grantable_rows(db, actor, rows)


def assign(db, actor, subject_type, subject_id, bundle, groups, now):
    """Create or replace one grant after delegation checks.

    The actor must hold every permission it grants in each target group and the
    ``account.grant`` permission there. Scope can only narrow.
    """
    if subject_type not in ('user', 'team'):
        raise MaintenanceError('grant_subject_refused')
    text(subject_id, 64)
    permissions = bundle_permissions(bundle)
    scope = _groups(groups)
    actor_permissions = permissions_for(db, actor)
    if ACCOUNT_GRANT not in actor_permissions:
        raise MaintenanceError('delegated_administrator_required', 403)
    for group in scope:
        held = permissions_for(db, actor, group)
        if ACCOUNT_GRANT not in held or not permissions <= held:
            raise MaintenanceError('delegation_exceeds_scope', 403)
    # Replacing a wider existing grant would silently withdraw authority the
    # actor cannot confer, so the previous row must also be inside its scope.
    require_grantable_rows(db, actor, db.execute(
        "SELECT bundle, groups FROM grants WHERE subject_type=? AND subject_id=? "
        "AND bundle=?", (subject_type, subject_id, bundle)).fetchall())
    raw = encode(scope)
    db.execute('DELETE FROM grants WHERE subject_type=? AND subject_id=? AND bundle=?',
               (subject_type, subject_id, bundle))
    db.execute('INSERT INTO grants (subject_type,subject_id,bundle,groups,created_by,created) '
               'VALUES (?,?,?,?,?,?)',
               (subject_type, subject_id, bundle, raw, actor, now))
    return scope


def revoke(db, actor, subject_type, subject_id, bundle, groups, now):
    """Remove exactly one grant; refused when the actor could not have granted it."""
    scope = _groups(groups)
    if ACCOUNT_GRANT not in permissions_for(db, actor):
        raise MaintenanceError('delegated_administrator_required', 403)
    for group in scope:
        if not bundle_permissions(bundle) <= permissions_for(db, actor, group):
            raise MaintenanceError('delegation_exceeds_scope', 403)
    cursor = db.execute(
        'DELETE FROM grants WHERE subject_type=? AND subject_id=? AND bundle=? AND groups=?',
        (subject_type, subject_id, bundle, encode(scope)))
    if cursor.rowcount != 1:
        raise MaintenanceError('grant_not_found', 404)
    return True


def admin_scope(db, user_id):
    """Union of groups in which this account holds retention/enrollment rights."""
    scope = set()
    for group in groups_for(db, user_id):
        if DEVICE_ENROLL in permissions_for(db, user_id, group):
            scope.add(group)
    return sorted(scope)


def listing(db, subject_type, subject_id):
    """Stored grants for one subject, for the administrative interface."""
    result = []
    for row in db.execute('SELECT bundle, groups FROM grants WHERE subject_type=? '
                          'AND subject_id=? ORDER BY bundle', (subject_type, subject_id)):
        try:
            groups = json.loads(row['groups'] if isinstance(row['groups'], str)
                                else bytes(row['groups']).decode('utf-8'))
        except (ValueError, TypeError):
            continue
        result.append(dict(bundle=row['bundle'], groups=groups))
    return result
