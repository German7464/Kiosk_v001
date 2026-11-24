import base64
import tempfile
import unittest
from pathlib import Path

from kiosk.delivery.protocol import encode
from kiosk.publication import authority as a
from kiosk.trust.crypto import load_private, spki_der
from tools import publisher_authority as admin


class RenewalTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / 'authority'
        self.password = 'test-only-recovery-password'
        self.now = 1_800_000_000
        self.public = admin.init(self.root, 'group', 'https://127.0.0.1:28443',
                                 self.password, self.now)
        self.key = load_private((self.root / 'authority-key.pem').read_text(), self.password)
        self.spki = spki_der(self.key)

    def test_expired_policy_renewal_preserves_root_and_revocations(self):
        old = a.policy(admin.read(self.root / 'policy.json'), self.spki, 'group',
                       self.public['origin'], self.now)
        old['revoked_users'] = ['blocked']
        old['revoked_devices'] = ['a' * 64]
        (self.root / 'policy.json').write_bytes(encode(a.signed(self.key, 'policy', old)))
        expired = old['expires'] + 1
        with self.assertRaises(ValueError):
            admin.load(self.root, self.password, expired)
        policy = admin.renew(self.root, self.password, expired, 'RENEW')
        key, public, renewed = admin.load(self.root, self.password, expired)
        self.assertEqual(public, self.public)
        self.assertEqual(spki_der(key), self.spki)
        self.assertEqual(renewed['version'], old['version'] + 1)
        self.assertEqual(renewed['expires'], expired + 104 * 86400)
        self.assertEqual(renewed['revoked_users'], old['revoked_users'])
        self.assertEqual(renewed['revoked_devices'], old['revoked_devices'])
        self.assertEqual(policy, admin.read(self.root / 'policy.json'))
        grant = dict(group_id='group', origin=public['origin'], user_id='user', role='user',
                     device_key=base64.b64encode(self.spki).decode(), issued=self.now,
                     expires=old['expires'], can_delegate=False)
        with self.assertRaises(ValueError):
            a.permission([a.signed(self.key, 'device', grant)], self.spki, renewed, expired)

    def test_refusals_preserve_policy_bytes(self):
        before = (self.root / 'policy.json').read_bytes()
        for password, now, confirm in [(self.password, self.now, ''),
                                       ('wrong-password', self.now, 'RENEW'),
                                       (self.password, self.now - 1, 'RENEW')]:
            with self.subTest(now=now, confirm=confirm):
                with self.assertRaises(ValueError):
                    admin.renew(self.root, password, now, confirm)
                self.assertEqual((self.root / 'policy.json').read_bytes(), before)

    def test_tampered_policy_is_not_recovered(self):
        envelope = admin.read(self.root / 'policy.json')
        first = 'B' if envelope['signature'][0] == 'A' else 'A'
        envelope['signature'] = first + envelope['signature'][1:]
        (self.root / 'policy.json').write_bytes(encode(envelope))
        before = (self.root / 'policy.json').read_bytes()
        with self.assertRaises(ValueError):
            admin.renew(self.root, self.password, self.now + 91 * 86400, 'RENEW')
        self.assertEqual((self.root / 'policy.json').read_bytes(), before)


if __name__ == '__main__':
    unittest.main()
