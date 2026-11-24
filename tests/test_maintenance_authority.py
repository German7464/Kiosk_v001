import base64
import json
import tempfile
import time
import unittest
from pathlib import Path

from kiosk.delivery.protocol import encode, sha
from kiosk.maintenance import accounts, keystore
from kiosk.maintenance.authority import MaintenanceAuthority
from kiosk.maintenance.store import MaintenanceError, MaintenanceStore
from kiosk.publication import authority as publication
from kiosk.trust.crypto import (generate_private_key, key_id, load_private, private_pem,
                                spki_der)
from tools.publisher_authority import init as init_authority

PASSWORD = 'correct-horse-battery-staple'
ORIGIN = 'https://127.0.0.1:24443'
GROUP = 'group-lab'
CLOCK = 1_800_000_000


class AuthorityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory()
        cls.root = Path(cls.temp.name)
        authority_dir = cls.root / 'authority'
        cls.public = init_authority(authority_dir, GROUP, ORIGIN, 'authority-password-12', CLOCK)
        cls.root_key = load_private((authority_dir / 'authority-key.pem').read_text(),
                                    'authority-password-12')
        cls.policy = json.loads((authority_dir / 'policy.json').read_text())
        cls.public_raw = cls.public
        cls.policy_raw = cls.policy

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        root = Path(self.temp.name)
        self.store = MaintenanceStore(root / 'maintenance.sqlite', clock=lambda: CLOCK)
        self.secrets = root / 'secrets'
        self.authority = MaintenanceAuthority(self.store, self.secrets,
                                              self.public_raw, self.policy_raw,
                                              clock=lambda: CLOCK)
        with self.store.connection() as db:
            accounts.create_user(db, 'admin', PASSWORD, 'administrator', now=CLOCK)
            accounts.create_user(db, 'alice', PASSWORD, 'user', now=CLOCK)
            accounts.create_user(db, 'bob', PASSWORD, 'user', now=CLOCK)
            row, key = self.authority.ensure_key(db, 'admin')
            grant = dict(group_id=GROUP, origin=ORIGIN, user_id='admin',
                         role='administrator',
                         device_key=base64.b64encode(spki_der(key)).decode('ascii'),
                         issued=CLOCK, expires=CLOCK + 90 * 86400, can_delegate=True)
            self.admin_key = key
            self.admin_chain = [publication.signed(self.root_key, 'device', grant)]
            self.authority.install_grant(db, 'admin', self.admin_chain, self.policy)

    def recovery_bundle(self):
        now = publication.verified(self.policy, spki_der(self.root_key), 'policy')['expires'] + 1
        self.authority.clock = lambda: now
        old = publication.verified(self.policy, spki_der(self.root_key), 'policy')
        current = dict(old, version=2, issued=now, expires=now + 90 * 86400)
        policy = publication.signed(self.root_key, 'policy', current)
        grant = publication.verified(self.admin_chain[0], spki_der(self.root_key), 'device')
        chain = [publication.signed(self.root_key, 'device',
                                    dict(grant, issued=now, expires=current['expires']))]
        return policy, chain

    def test_expired_same_key_recovery_persists_without_replacing_key(self):
        policy, chain = self.recovery_bundle()
        with self.store.connection() as db:
            protected = bytes(self.authority._row(db, 'admin')['protected'])
            with self.assertRaises(ValueError):
                self.authority.grant(db, 'admin')
            request = self.authority.recovery_request(db, 'admin')
            self.assertEqual(publication.verified(request['proof'], spki_der(self.admin_key),
                                                 'device-request'), request['request'])
            result = self.authority.recover_grant(db, 'admin', chain, policy,
                root_pin=self.public['root_sha256'], confirm=True)
            self.assertEqual(result['device_id'], key_id(self.admin_key))
            self.assertEqual(bytes(self.authority._row(db, 'admin')['protected']), protected)
        restarted = MaintenanceAuthority(self.store, self.secrets, self.public, policy,
                                         clock=self.authority.clock)
        with self.store.connection() as db:
            self.assertEqual(restarted.grant(db, 'admin')['grant']['user_id'], 'admin')
            retried = restarted.recover_grant(db, 'admin', chain, policy,
                root_pin=self.public['root_sha256'], confirm=True)
            self.assertTrue(retried['already_current'])
            with self.assertRaises(ValueError):
                restarted.recover_grant(db, 'admin', self.admin_chain, self.policy,
                    root_pin=self.public['root_sha256'], confirm=True)

    def test_recovery_wrong_pin_unconfirmed_and_other_key_preserve_grant(self):
        policy, chain = self.recovery_bundle()
        with self.store.connection() as db:
            before = bytes(self.authority._row(db, 'admin')['chain'])
            for pin, confirm in [('0' * 64, True), (self.public['root_sha256'], False)]:
                with self.assertRaises(MaintenanceError):
                    self.authority.recover_grant(db, 'admin', chain, policy,
                                                root_pin=pin, confirm=confirm)
            grant = publication.verified(chain[0], spki_der(self.root_key), 'device')
            wrong = [publication.signed(self.root_key, 'device',
                       dict(grant, device_key=base64.b64encode(spki_der(generate_private_key())).decode()))]
            with self.assertRaises(MaintenanceError):
                self.authority.recover_grant(db, 'admin', wrong, policy,
                    root_pin=self.public['root_sha256'], confirm=True)
            self.assertEqual(bytes(self.authority._row(db, 'admin')['chain']), before)

    def test_recovery_cannot_restore_a_blocked_account_or_revoked_key(self):
        policy, chain = self.recovery_bundle()
        with self.store.connection() as db:
            db.execute("UPDATE users SET blocked=1 WHERE id='admin'")
            with self.assertRaises(MaintenanceError):
                self.authority.recover_grant(db, 'admin', chain, policy,
                    root_pin=self.public['root_sha256'], confirm=True)
            db.execute("UPDATE users SET blocked=0 WHERE id='admin'")
            value = publication.verified(policy, spki_der(self.root_key), 'policy')
            revoked = publication.signed(self.root_key, 'policy',
                dict(value, revoked_devices=[key_id(self.admin_key)]))
            with self.assertRaises(ValueError):
                self.authority.recover_grant(db, 'admin', chain, revoked,
                    root_pin=self.public['root_sha256'], confirm=True)

    def enroll(self, user='alice', targets=('displayA',), groups=(GROUP,)):
        with self.store.connection() as db:
            return self.authority.enroll(db, 'admin', user, role='user', groups=list(groups),
                                         targets=list(targets))

    def plan(self, user='alice', device_id=None, targets=('displayA',), issued=CLOCK,
             expires=CLOCK + 3600, policy_version=1):
        value = dict(group_id=GROUP, origin=ORIGIN, user_id=user,
                     device_id=device_id or 'f' * 64, policy_version=policy_version,
                     issued=issued, expires=expires,
                     publication_sha256=sha(b'publication'),
                     dependencies_sha256=sha(b'dependencies'), renderer='2' * 64,
                     targets=[dict(device_id=item, profile_id='events-lab-tv',
                                   profile_version=3, mode='tv',
                                   configuration_sha256='3' * 64) for item in targets],
                     parents=[])
        value['id'] = sha(encode({key: item for key, item in value.items() if key != 'id'}))
        return value

    def test_admin_can_enroll_scoped_user_but_not_self(self):
        bundle = self.enroll()
        self.assertEqual(bundle['scope']['targets'], ['displayA'])
        self.assertEqual(len(bundle['chain']), 2)
        with self.store.connection() as db:
            with self.assertRaises(MaintenanceError) as caught:
                self.authority.enroll(db, 'admin', 'admin', role='user',
                                      groups=[GROUP], targets=['displayA'])
            self.assertEqual(caught.exception.code, 'self_enrollment_refused')
            with self.assertRaises(MaintenanceError) as caught:
                self.authority.enroll(db, 'admin', 'alice', role='user',
                                      groups=[GROUP], targets=['displayA'])
            self.assertEqual(caught.exception.code, 'retained_enrollment_exists')

    def test_child_scope_cannot_exceed_admin_scope(self):
        # A scoped delegated administrator may enroll only within its own scope.
        bundle = self.enroll(user='bob')
        # bob's grant is a non-delegating child, so it cannot enroll at all.
        with self.store.connection() as db:
            with self.assertRaises(MaintenanceError) as caught:
                self.authority.enroll(db, 'bob', 'alice', role='user', groups=[GROUP],
                                      targets=['displayA'])
            self.assertEqual(caught.exception.code, 'administrator_enrollment_required')
        self.assertEqual(bundle['scope']['targets'], ['displayA'])

    def alice_key(self):
        with self.store.connection(write=False) as db:
            row = db.execute("SELECT protected FROM keys WHERE user_id='alice'").fetchone()
        pem = keystore.protect(bytes(row['protected']), self.secrets, decrypt=True)
        return load_private(pem.decode('ascii'))

    def test_display_verifier_enforces_signed_scope(self):
        bundle = self.enroll(targets=('displayA',))
        chain = bundle['chain']
        allowed = self.plan(device_id=bundle['device_id'], targets=('displayA',))
        approval = publication.signed(self.alice_key(), 'publication', allowed)
        publication.approval(approval, chain, self.policy, base64.b64decode(
            self.public_raw['root_spki']), GROUP, ORIGIN, CLOCK)
        outside = self.plan(device_id=bundle['device_id'], targets=('displayA', 'displayB'))
        signed = publication.signed(self.alice_key(), 'publication', outside)
        with self.assertRaises(ValueError) as caught:
            publication.approval(signed, chain, self.policy, base64.b64decode(
                self.public_raw['root_spki']), GROUP, ORIGIN, CLOCK)
        self.assertEqual(str(caught.exception), 'publisher_scope_refused')

    def test_signing_rechecks_scope_targets_policy_and_expiry(self):
        bundle = self.enroll(targets=('displayA',))
        with self.store.connection() as db:
            with self.assertRaises(MaintenanceError) as caught:
                self.authority.sign_publication(
                    db, 'alice', self.plan(device_id=bundle['device_id'],
                                           targets=('displayB',)), None)
            self.assertEqual(caught.exception.code, 'publication_targets_outside_scope')
            with self.assertRaises(MaintenanceError) as caught:
                self.authority.sign_publication(
                    db, 'alice', self.plan(device_id=bundle['device_id'],
                                           policy_version=99), None)
            self.assertEqual(caught.exception.code, 'publication_policy_changed')
            with self.assertRaises(MaintenanceError) as caught:
                self.authority.sign_publication(
                    db, 'alice', self.plan(device_id=bundle['device_id'],
                                           issued=CLOCK - 10), None)
            self.assertEqual(caught.exception.code, 'publication_authority_expired')
            signed = self.authority.sign_publication(
                db, 'alice', self.plan(device_id=bundle['device_id']), None)
            self.assertIn('approval', signed)
            self.assertEqual(len(signed['chain']), 2)

    def test_acceptance_receipt_is_independent_and_tamper_evident(self):
        plan = self.plan(device_id='f' * 64)
        approval = {'payload': 'x' * 4, 'signature': 'y' * 4}
        receipt = self.authority.sign_receipt(plan, approval, 1, 'a' * 64)
        value = self.authority.verify_receipt(receipt['receipt'])
        self.assertEqual(value['plan_id'], plan['id'])
        self.assertEqual(value['targets_sha256'],
                         sha(encode(plan['targets'])))
        tampered = dict(receipt['receipt'])
        tampered['payload'] = tampered['payload'][:-2] + 'AA'
        with self.assertRaises(ValueError):
            self.authority.verify_receipt(tampered)


if __name__ == '__main__':
    unittest.main()
