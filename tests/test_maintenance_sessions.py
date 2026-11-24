import tempfile
import unittest
from pathlib import Path

from kiosk.maintenance import accounts, permissions, sessions
from kiosk.maintenance.store import MaintenanceError, MaintenanceStore

PASSWORD = 'correct-horse-battery-staple'


class Clock:
    def __init__(self, now=1_800_000_000):
        self.now = now

    def __call__(self):
        return self.now


class Base(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.clock = Clock()
        self.store = MaintenanceStore(Path(self.temp.name) / 'maintenance.sqlite',
                                      clock=self.clock)
        with self.store.connection() as db:
            for user in ('admin', 'alice', 'bob', 'carol', 'dave'):
                accounts.create_user(db, user, PASSWORD,
                                     'administrator' if user == 'admin' else 'user',
                                     now=self.clock.now)
            db.execute("INSERT INTO grants (subject_type,subject_id,bundle,groups,created_by,"
                       "created) VALUES ('user','admin','system-administrator',?,'admin',?)",
                       ('["group-1","group-2"]', self.clock.now))


class PermissionTests(Base):
    def grant(self, actor, subject, bundle, groups, subject_type='user'):
        with self.store.connection() as db:
            return permissions.assign(db, actor, subject_type, subject, bundle, groups,
                                      self.clock.now)

    def test_viewer_editor_publisher_bundles_are_distinct(self):
        self.grant('admin', 'dave', 'viewer', ['group-1'])
        self.grant('admin', 'bob', 'editor', ['group-1'])
        self.grant('admin', 'alice', 'publisher', ['group-1'])
        with self.store.connection(write=False) as db:
            self.assertEqual(permissions.permissions_for(db, 'dave'),
                             {permissions.CONTENT_READ})
            self.assertIn(permissions.CONTENT_EDIT, permissions.permissions_for(db, 'bob'))
            self.assertNotIn(permissions.CONTENT_PUBLISH,
                             permissions.permissions_for(db, 'bob'))
            self.assertIn(permissions.CONTENT_PUBLISH,
                          permissions.permissions_for(db, 'alice'))
            with self.assertRaises(MaintenanceError) as caught:
                permissions.require(db, 'bob', permissions.CONTENT_PUBLISH)
            self.assertEqual(caught.exception.code, 'permission_required')
            with self.assertRaises(MaintenanceError):
                permissions.require(db, 'dave', permissions.CONTENT_EDIT, 'group-2')

    def test_delegated_administrator_cannot_exceed_own_scope(self):
        self.grant('admin', 'carol', 'group-administrator', ['group-1'])
        self.grant('carol', 'alice', 'publisher', ['group-1'])
        with self.assertRaises(MaintenanceError) as caught:
            self.grant('carol', 'dave', 'publisher', ['group-2'])
        self.assertEqual(caught.exception.code, 'delegation_exceeds_scope')
        with self.assertRaises(MaintenanceError):
            self.grant('carol', 'dave', 'system-administrator', ['group-1'])
        with self.assertRaises(MaintenanceError):
            self.grant('alice', 'dave', 'publisher', ['group-1'])

    def test_team_membership_resolves_without_nested_groups(self):
        with self.store.connection() as db:
            accounts.add_team(db, 'editors', 'Editors', self.clock.now)
            accounts.add_membership(db, 'admin', 'editors', 'bob', self.clock.now)
        self.grant('admin', 'editors', 'editor', ['group-1'], subject_type='team')
        with self.store.connection(write=False) as db:
            self.assertIn(permissions.CONTENT_EDIT, permissions.permissions_for(db, 'bob'))
            self.assertNotIn(permissions.CONTENT_PUBLISH,
                             permissions.permissions_for(db, 'bob'))

    def test_blocking_ends_sessions_but_keeps_grants(self):
        self.grant('admin', 'alice', 'publisher', ['group-1'])
        with self.store.connection() as db:
            secret, _ = sessions.start_password_session(
                self.store, db, 'alice', PASSWORD, 'a' * 32)
        with self.store.connection() as db:
            accounts.block(db, 'admin', 'alice', self.clock.now)
            self.assertEqual(db.execute('SELECT blocked FROM users WHERE id=?',
                                        ('alice',)).fetchone()[0], 1)
            self.assertEqual(db.execute('SELECT COUNT(*) FROM grants WHERE subject_id=?',
                                        ('alice',)).fetchone()[0], 1)
            with self.assertRaises(MaintenanceError):
                sessions.lookup(self.store, db, secret)
            accounts.unblock(db, 'admin', 'alice', self.clock.now)
            self.assertEqual(permissions.groups_for(db, 'alice'), {'group-1'})
            with self.assertRaises(MaintenanceError):
                sessions.lookup(self.store, db, secret)


class SessionTests(Base):
    def test_terminal_approval_makes_password_login_trusted(self):
        with self.store.connection() as db:
            secret, row = sessions.start_password_session(
                self.store, db, 'alice', PASSWORD, 'a' * 32)
            self.assertFalse(row['trusted'])
            sessions.approve_terminal(db, 'admin', 'a' * 32, 'Desk', ['alice'], ['group-1'],
                                      now=self.clock.now)
        with self.store.connection() as db:
            secret, row = sessions.start_password_session(
                self.store, db, 'alice', PASSWORD, 'a' * 32)
            self.assertTrue(row['trusted'])

    def test_lock_resume_and_rotation_invalidate_old_cookie(self):
        with self.store.connection() as db:
            secret, _ = sessions.start_password_session(
                self.store, db, 'alice', PASSWORD, 'a' * 32)
            sessions.lock(self.store, db, secret)
            self.assertEqual(sessions.lookup(self.store, db, secret, touch=False)['state'],
                             'locked')
        # Lock keeps the row but refuses activity; resume needs the password.
        with self.store.connection() as db:
            with self.assertRaises(MaintenanceError) as caught:
                sessions.resume(self.store, db, secret, 'alice', 'wrong-password')
            self.assertEqual(caught.exception.code, 'invalid_credentials')
            new, row = sessions.resume(self.store, db, secret, 'alice', PASSWORD)
        with self.store.connection() as db:
            with self.assertRaises(MaintenanceError):
                sessions.lookup(self.store, db, secret)
            self.assertEqual(sessions.lookup(self.store, db, new)['state'], 'active')
        with self.store.connection() as db:
            rotated, _ = sessions.rotate(self.store, db, new)
        with self.store.connection() as db:
            with self.assertRaises(MaintenanceError):
                sessions.lookup(self.store, db, new)
            self.assertTrue(sessions.lookup(self.store, db, rotated))

    def test_idle_and_absolute_expiry(self):
        with self.store.connection() as db:
            secret, _ = sessions.start_password_session(
                self.store, db, 'alice', PASSWORD, 'a' * 32)
        self.clock.now += sessions.IDLE_SECONDS + 1
        with self.store.connection() as db:
            with self.assertRaises(MaintenanceError) as caught:
                sessions.lookup(self.store, db, secret)
            self.assertEqual(caught.exception.code, 'session_expired')
        with self.store.connection() as db:
            secret, _ = sessions.start_password_session(
                self.store, db, 'alice', PASSWORD, 'b' * 32)
        self.clock.now += sessions.ABSOLUTE_SECONDS + 1
        with self.store.connection() as db:
            with self.assertRaises(MaintenanceError):
                sessions.lookup(self.store, db, secret)

    def test_terminate_all_my_sessions_includes_locked(self):
        with self.store.connection() as db:
            first, _ = sessions.start_password_session(
                self.store, db, 'alice', PASSWORD, 'a' * 32)
            second, _ = sessions.start_password_session(
                self.store, db, 'alice', PASSWORD, 'a' * 32)
            sessions.lock(self.store, db, second)
            self.assertEqual(sessions.terminate_user_on_terminal(
                self.store, db, 'alice', 'a' * 32), 2)
            for secret in (first, second):
                with self.assertRaises(MaintenanceError):
                    sessions.lookup(self.store, db, secret)

    def test_temporary_connection_is_single_use_and_cascades(self):
        with self.store.connection() as db:
            sessions.approve_terminal(db, 'admin', 'a' * 32, 'Desk', ['alice'], ['group-1'],
                                      now=self.clock.now)
            approver, _ = sessions.start_password_session(
                self.store, db, 'alice', PASSWORD, 'a' * 32)
            identity, record = sessions.create_connection(
                self.store, db, 'login', 'b' * 32, 'c' * 64, 'second browser',
                requested_user='alice')
            with self.assertRaises(MaintenanceError) as caught:
                sessions.approve_connection(self.store, db, approver, identity, 'BADCODE1')
            self.assertEqual(caught.exception.code, 'connection_code_refused')
            sessions.approve_connection(self.store, db, approver, identity, record['code'])
            with self.assertRaises(MaintenanceError) as caught:
                sessions.approve_connection(self.store, db, approver, identity, record['code'])
            self.assertEqual(caught.exception.code, 'connection_already_approved')
            child, created = sessions.consume_login(self.store, db, identity, 'c' * 64)
            self.assertTrue(created['temporary'])
            with self.assertRaises(MaintenanceError) as caught:
                sessions.consume_login(self.store, db, identity, 'c' * 64)
            self.assertEqual(caught.exception.code, 'connection_already_consumed')
            self.assertEqual(sessions.end(self.store, db, approver), True)
            with self.assertRaises(MaintenanceError):
                sessions.lookup(self.store, db, child)

    def test_connection_cannot_be_reused_for_another_account(self):
        with self.store.connection() as db:
            sessions.approve_terminal(db, 'admin', 'a' * 32, 'Desk', ['alice'], ['group-1'],
                                      now=self.clock.now)
            approver, _ = sessions.start_password_session(
                self.store, db, 'alice', PASSWORD, 'a' * 32)
            identity, record = sessions.create_connection(
                self.store, db, 'login', 'b' * 32, 'c' * 64, 'bob browser',
                requested_user='bob')
            with self.assertRaises(MaintenanceError) as caught:
                sessions.approve_connection(self.store, db, approver, identity, record['code'])
            self.assertEqual(caught.exception.code, 'connection_user_mismatch')

    def test_temporary_chain_is_bounded_and_fully_cascaded(self):
        with self.store.connection() as db:
            sessions.approve_terminal(db, 'admin', 'a' * 32, 'Desk', ['alice'], ['group-1'],
                                      now=self.clock.now)
            approver, _ = sessions.start_password_session(
                self.store, db, 'alice', PASSWORD, 'a' * 32)
        def child(binding, summary, parent_secret):
            with self.store.connection() as db:
                identity, record = sessions.create_connection(
                    self.store, db, 'login', binding, 'c' * 64, summary,
                    requested_user='alice')
                sessions.approve_connection(self.store, db, parent_secret, identity,
                                            record['code'])
                secret, created = sessions.consume_login(self.store, db, identity,
                                                         'c' * 64)
                self.assertTrue(created['temporary'])
                return secret
        first = child('b' * 32, 'first child', approver)
        second = child('d' * 32, 'second child', first)
        with self.store.connection() as db:
            self.assertTrue(sessions.lookup(self.store, db, second))
            sessions.end(self.store, db, approver)
            for secret in (first, second):
                with self.assertRaises(MaintenanceError):
                    sessions.lookup(self.store, db, secret)

    def test_expired_and_wrong_binding_connections_are_refused(self):
        with self.store.connection() as db:
            identity, record = sessions.create_connection(
                self.store, db, 'login', 'b' * 32, 'c' * 64, 'browser',
                requested_user='alice')
            with self.assertRaises(MaintenanceError) as caught:
                sessions.consume_connection(self.store, db, identity, 'd' * 64)
            self.assertEqual(caught.exception.code, 'browser_binding_refused')
        self.clock.now += sessions.CONNECTION_SECONDS + 1
        with self.store.connection() as db:
            with self.assertRaises(MaintenanceError) as caught:
                sessions.consume_connection(self.store, db, identity, 'c' * 64)
            self.assertEqual(caught.exception.code, 'connection_expired')


class RotationRevocationTests(Base):
    """Regression: rotating or resuming a parent must keep its children revocable."""

    def trusted_alice(self, terminal='a' * 32):
        with self.store.connection() as db:
            sessions.approve_terminal(db, 'admin', terminal, 'Desk', ['alice'], ['group-1'],
                                      now=self.clock.now)
            secret, _ = sessions.start_password_session(
                self.store, db, 'alice', PASSWORD, terminal)
            return secret

    def temporary_child(self, parent, terminal='b' * 32, binding='c' * 64):
        with self.store.connection() as db:
            identity, record = sessions.create_connection(
                self.store, db, 'login', terminal, binding, 'second browser',
                requested_user='alice')
            sessions.approve_connection(self.store, db, parent, identity, record['code'])
            secret, created = sessions.consume_login(self.store, db, identity, binding)
        self.assertTrue(created['temporary'])
        return secret

    def test_rotate_then_logout_ends_the_temporary_child(self):
        parent = self.trusted_alice()
        child = self.temporary_child(parent)
        with self.store.connection() as db:
            rotated, identity = sessions.rotate(self.store, db, parent)
            self.assertTrue(sessions.lookup(self.store, db, child))
            self.assertFalse(sessions.end(self.store, db, parent))
            self.assertTrue(sessions.end(self.store, db, rotated))
            with self.assertRaises(MaintenanceError):
                sessions.lookup(self.store, db, child)
        with self.store.connection() as db:
            row = db.execute('SELECT parent FROM sessions WHERE secret_sha256=?',
                             (hashlib_digest(child),)).fetchone()
        self.assertEqual(row['parent'], identity)

    def test_resume_then_logout_ends_the_temporary_child(self):
        parent = self.trusted_alice()
        child = self.temporary_child(parent)
        with self.store.connection() as db:
            sessions.lock(self.store, db, parent)
            resumed, row = sessions.resume(self.store, db, parent, 'alice', PASSWORD)
            self.assertTrue(sessions.lookup(self.store, db, child))
            self.assertTrue(sessions.end(self.store, db, resumed))
            with self.assertRaises(MaintenanceError):
                sessions.lookup(self.store, db, child)

    def test_rotated_parent_can_terminate_its_child(self):
        parent = self.trusted_alice()
        child = self.temporary_child(parent)
        with self.store.connection() as db:
            rotated, identity = sessions.rotate(self.store, db, parent)
            sessions.terminate(self.store, db, 'alice', identity)
            with self.assertRaises(MaintenanceError):
                sessions.lookup(self.store, db, child)

    def test_parent_idle_expiry_and_block_cascade_without_a_request(self):
        parent = self.trusted_alice()
        child = self.temporary_child(parent)
        self.clock.now += sessions.IDLE_SECONDS + 1
        with self.store.connection() as db:
            with self.assertRaises(MaintenanceError):
                sessions.lookup(self.store, db, child)
        parent = self.trusted_alice()
        child = self.temporary_child(parent)
        with self.store.connection() as db:
            accounts.block(db, 'admin', 'alice', self.clock.now)
            with self.assertRaises(MaintenanceError):
                sessions.lookup(self.store, db, child)

    def test_suspended_workspace_needs_password_on_the_same_terminal(self):
        parent = self.trusted_alice('q' * 32)
        with self.store.connection() as db:
            sessions.suspend(self.store, db, parent)
            self.assertEqual([item['user_id'] for item in sessions.suspended(
                self.store, db, 'q' * 32)], ['alice'])
            with self.assertRaises(MaintenanceError) as caught:
                sessions.resume_suspended(self.store, db, 'q' * 32, 'alice', 'wrong-password')
            self.assertEqual(caught.exception.code, 'invalid_credentials')
            with self.assertRaises(MaintenanceError) as caught:
                sessions.resume_suspended(self.store, db, 'z' * 32, 'alice', PASSWORD)
            self.assertEqual(caught.exception.code, 'suspended_workspace_missing')
            secret, row = sessions.resume_suspended(self.store, db, 'q' * 32, 'alice', PASSWORD)
            self.assertEqual(sessions.lookup(self.store, db, secret)['id'], row['id'])
            with self.assertRaises(MaintenanceError):
                sessions.resume_suspended(self.store, db, 'q' * 32, 'alice', PASSWORD)


class DelegationTests(Base):
    def grant(self, actor, subject, bundle, groups, subject_type='user'):
        with self.store.connection() as db:
            return permissions.assign(db, actor, subject_type, subject, bundle, groups,
                                      self.clock.now)

    def test_team_membership_cannot_widen_a_delegated_scope(self):
        self.grant('admin', 'carol', 'group-administrator', ['group-1'])
        with self.store.connection() as db:
            accounts.add_team(db, 'platform-admins', 'Platform administrators',
                              self.clock.now)
        self.grant('admin', 'platform-admins', 'system-administrator',
                   ['group-1'], subject_type='team')
        with self.store.connection() as db:
            with self.assertRaises(MaintenanceError) as caught:
                accounts.add_membership(db, 'carol', 'platform-admins', 'carol',
                                        self.clock.now)
            self.assertEqual(caught.exception.code, 'delegation_exceeds_scope')
            self.assertEqual(permissions.groups_for(db, 'carol'), {'group-1'})
            self.assertNotIn(permissions.SERVICE_RELOCATE,
                             permissions.permissions_for(db, 'carol'))
        # A team the actor could itself grant is legitimate.
        with self.store.connection() as db:
            accounts.add_team(db, 'group-1-editors', 'Group 1 editors', self.clock.now)
        self.grant('admin', 'group-1-editors', 'editor', ['group-1'], subject_type='team')
        with self.store.connection() as db:
            self.assertTrue(accounts.add_membership(db, 'carol', 'group-1-editors', 'bob',
                                                    self.clock.now))
        # Even a group-scoped system-administrator row carries the service-wide
        # relocation permission, so a group administrator can never grant it.
        with self.store.connection() as db:
            with self.assertRaises(MaintenanceError):
                permissions.assign(db, 'carol', 'user', 'bob', 'system-administrator',
                                   ['group-1'], self.clock.now)

    def test_cross_scope_block_and_session_moderation_are_refused(self):
        self.grant('admin', 'carol', 'group-administrator', ['group-1'])
        self.grant('admin', 'bob', 'publisher', ['group-1'])
        self.grant('admin', 'dave', 'group-administrator', ['group-2'])
        with self.store.connection() as db:
            sessions.approve_terminal(db, 'admin', 'd' * 32, 'Desk', ['dave'], ['group-2'],
                                      now=self.clock.now)
            dave_secret, _ = sessions.start_password_session(
                self.store, db, 'dave', PASSWORD, 'd' * 32)
            dave_id = sessions.lookup(self.store, db, dave_secret)['id']
        with self.store.connection() as db:
            with self.assertRaises(MaintenanceError) as caught:
                accounts.block(db, 'carol', 'dave', self.clock.now)
            self.assertEqual(caught.exception.code, 'delegation_exceeds_scope')
            with self.assertRaises(MaintenanceError) as caught:
                sessions.terminate(self.store, db, 'carol', dave_id)
            self.assertEqual(caught.exception.code, 'delegation_exceeds_scope')
            # Inside the actor's own scope the same operations succeed.
            accounts.block(db, 'carol', 'bob', self.clock.now)
            accounts.unblock(db, 'carol', 'bob', self.clock.now)
            self.assertTrue(sessions.lookup(self.store, db, dave_secret))

    def test_grant_replacement_cannot_withdraw_or_widen_outside_scope(self):
        self.grant('admin', 'carol', 'group-administrator', ['group-1'])
        self.grant('admin', 'bob', 'publisher', ['group-1', 'group-2'])
        with self.store.connection() as db:
            with self.assertRaises(MaintenanceError) as caught:
                permissions.assign(db, 'carol', 'user', 'bob', 'publisher', ['group-1'],
                                   self.clock.now)
            self.assertEqual(caught.exception.code, 'delegation_exceeds_scope')
            self.assertEqual(permissions.groups_for(db, 'bob'), {'group-1', 'group-2'})

    def test_delegated_administrator_cannot_create_an_administrator(self):
        self.grant('admin', 'carol', 'group-administrator', ['group-1'])
        with self.store.connection() as db:
            with self.assertRaises(MaintenanceError) as caught:
                accounts.create_user(db, 'new-admin', PASSWORD, 'administrator',
                                     now=self.clock.now, actor='carol')
            self.assertEqual(caught.exception.code, 'delegation_exceeds_scope')
            accounts.create_user(db, 'new-user', PASSWORD, 'user', now=self.clock.now,
                                 actor='carol')


def hashlib_digest(secret):
    import hashlib
    return hashlib.sha256(secret.encode('ascii')).hexdigest()


if __name__ == '__main__':
    unittest.main()
