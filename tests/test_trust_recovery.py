"""Offline recovery backup, authority re-issue and server-key-loss recovery.

These checks use a disposable installation under a temporary directory. They never
read or write the retained pilot material, the production CA or any installed
configuration.
"""
import base64
import json
import os
import tempfile
import shutil
import time
import unittest
from contextlib import redirect_stdout, redirect_stderr
from io import StringIO
from pathlib import Path
from unittest.mock import patch

from kiosk.trust.recovery import (
    BUNDLE_FORMAT,
    RecoveryError,
    create_backup,
    group_trust_envelope,
    open_bundle,
    public_spki,
    restore_bundle,
    verify_envelope,
)
from kiosk.trust.crypto import key_id, load_private, spki_der
from kiosk.trust.roles import make_delegation, verify_delegation
from tools import lan_trust_admin


PASSWORD = 'disposable-test-password-1'


def run(function, args):
    out, err = StringIO(), StringIO()
    with redirect_stdout(out), redirect_stderr(err):
        try:
            code = function(args)
        except (lan_trust_admin.AdminError, ValueError, KeyError, OSError) as error:
            return 1, out.getvalue(), str(error)
    return (0 if code is None else code), out.getvalue(), err.getvalue()


def parse_args(argv):
    parser = lan_trust_admin.argparse.ArgumentParser()
    sub = parser.add_subparsers(dest='command', required=True)
    # Reuse the real parser shapes instead of duplicating option names.
    backup_p = sub.add_parser('backup')
    backup_p.add_argument('--root', type=Path)
    backup_p.add_argument('--output', type=Path)
    lan_trust_admin._add_password_args(backup_p)
    restore_p = sub.add_parser('restore')
    restore_p.add_argument('--bundle', type=Path)
    restore_p.add_argument('--root', type=Path)
    restore_p.add_argument('--key-password-file', type=Path)
    lan_trust_admin._add_password_args(restore_p)
    reauth = sub.add_parser('reauthorize')
    reauth.add_argument('--root', type=Path)
    reauth.add_argument('--trust-days', type=int, default=365)
    reauth.add_argument('--confirm', action='store_true')
    reauth.add_argument('--previous-authority-isolated', action='store_true')
    lan_trust_admin._add_password_args(reauth)
    rebuild = sub.add_parser('rebuild-server')
    rebuild.add_argument('--root', type=Path)
    rebuild.add_argument('--address')
    rebuild.add_argument('--port', type=int, default=8443)
    rebuild.add_argument('--backend-port', type=int, default=8765)
    rebuild.add_argument('--online-password-file', type=Path)
    rebuild.add_argument('--max-tls-days', type=int, default=30)
    rebuild.add_argument('--delegation-days', type=int, default=90)
    rebuild.add_argument('--issuer-days', type=int, default=90)
    rebuild.add_argument('--tls-days', type=int, default=7)
    rebuild.add_argument('--trust-days', type=int, default=365)
    rebuild.add_argument('--confirm', action='store_true')
    rebuild.add_argument('--previous-authority-isolated', action='store_true')
    lan_trust_admin._add_password_args(rebuild)
    return parser.parse_args(argv)


class DisposableInstallation:
    def __init__(self, root):
        self.root = Path(root)
        argv = ['init', '--root', str(self.root), '--address', '127.0.0.1', '--port', '19443',
                '--backend-port', '18765', '--password', PASSWORD,
                '--trust-days', '7', '--bootstrap-days', '1']
        parser = lan_trust_admin.argparse.ArgumentParser()
        sub = parser.add_subparsers(dest='command', required=True)
        init_p = sub.add_parser('init')
        init_p.add_argument('--root', type=Path)
        init_p.add_argument('--address', default='192.168.1.165')
        init_p.add_argument('--port', type=int, default=8443)
        init_p.add_argument('--backend-port', type=int, default=8765)
        init_p.add_argument('--group-id')
        init_p.add_argument('--server-id')
        init_p.add_argument('--max-tls-days', type=int, default=30)
        init_p.add_argument('--delegation-days', type=int, default=90)
        init_p.add_argument('--issuer-days', type=int, default=90)
        init_p.add_argument('--tls-days', type=int, default=7)
        init_p.add_argument('--trust-days', type=int, default=7)
        init_p.add_argument('--bootstrap-days', type=int, default=1)
        lan_trust_admin._add_password_args(init_p)
        args = parser.parse_args(argv)
        code, out, err = run(lan_trust_admin.init, args)
        if code not in (0, None):
            raise AssertionError(err or out)
        self.bootstrap = json.loads((self.root / 'public/bootstrap.json').read_text(encoding='utf-8'))
        self.trust = json.loads((self.root / 'public/trust.json').read_text(encoding='utf-8'))
        self.delegation = json.loads((self.root / 'server/delegation.json').read_text(encoding='utf-8'))


class RecoveryBackupTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temporary = tempfile.TemporaryDirectory()
        cls.source = DisposableInstallation(Path(cls.temporary.name) / 'source')

    @classmethod
    def tearDownClass(cls):
        cls.temporary.cleanup()

    def bundle(self):
        return create_backup(self.source.root, PASSWORD)

    def test_bounded_input_and_exact_material_names(self):
        bundle = self.bundle()
        bundle['manifest']['files']['../unexpected'] = 'a' * 64
        with self.assertRaisesRegex(RecoveryError, 'manifest'):
            open_bundle(bundle, PASSWORD)
        with self.assertRaisesRegex(RecoveryError, 'format'):
            open_bundle({'padding': 'x' * (128 * 1024)}, PASSWORD)
        with self.assertRaisesRegex(RecoveryError, 'password'):
            open_bundle(self.bundle(), '')

    def test_automatic_prepared_windows_need_no_online_root_and_keep_scope(self):
        from kiosk.trust.prepared import prepare, advance
        root = Path(self.temporary.name) / 'prepared'
        shutil.copytree(self.source.root, root)
        initial = lan_trust_admin._current_trust(root)
        now = initial['issued_at']
        result = prepare(root, PASSWORD, now)
        self.assertGreater(result['windows'], 1)
        self.assertFalse(result['online_signing_keys_added'])
        shutil.rmtree(root / 'admin-private')
        self.assertEqual('current', advance(root, now))
        self.assertEqual('advanced', advance(root, now + 6 * 86400))
        updated = lan_trust_admin._current_trust(root)
        self.assertEqual(initial['servers'], updated['servers'])
        self.assertGreater(updated['generation'], initial['generation'])
        self.assertLessEqual(updated['expires_at'], result['horizon'])
        self.assertEqual('current', advance(root, now + 6 * 86400))
        self.assertEqual('exhausted', advance(root, result['horizon']))

    def test_prepared_tamper_preserves_committed_authority(self):
        from kiosk.trust.prepared import prepare, advance
        root = Path(self.temporary.name) / 'prepared-tamper'
        shutil.copytree(self.source.root, root)
        now = lan_trust_admin._current_trust(root)['issued_at']
        prepare(root, PASSWORD, now)
        path = root / 'server/prepared-trust.json'
        plan = json.loads(path.read_text())
        plan['envelopes'][0]['signature_base64'] = base64.b64encode(b'x' * 384).decode()
        path.write_text(json.dumps(plan))
        before = (root / 'server/public.json').read_bytes()
        with self.assertRaises(Exception):
            advance(root, now + 6 * 86400)
        self.assertEqual(before, (root / 'server/public.json').read_bytes())

    def test_interrupted_restore_never_exposes_partial_target(self):
        target = Path(self.temporary.name) / 'interrupted'
        original = Path.write_text
        def failing(path, *args, **kwargs):
            if path.name == 'trust.json':
                raise OSError('injected write interruption')
            return original(path, *args, **kwargs)
        with patch.object(Path, 'write_text', failing):
            with self.assertRaisesRegex(OSError, 'interruption'):
                restore_bundle(self.bundle(), target, PASSWORD, extract_password=PASSWORD)
        self.assertFalse(target.exists())
        self.assertEqual([], list(target.parent.glob('.kiosk-recovery-*')))

    def test_backup_is_encrypted_authenticated_and_password_protected(self):
        bundle = self.bundle()
        self.assertEqual(BUNDLE_FORMAT, bundle['format'])
        self.assertNotIn(PASSWORD, json.dumps(bundle))
        text = json.dumps(bundle)
        for marker in ('BEGIN PRIVATE KEY', 'BEGIN CERTIFICATE'):
            self.assertNotIn(marker, text)
        payload, manifest = open_bundle(bundle, PASSWORD)
        self.assertEqual(self.source.bootstrap['group_id'], manifest['group_id'])
        self.assertEqual(self.source.bootstrap['group_key_id'], manifest['group_key_id'])
        self.assertIn('group-key.pem', payload['files'])
        with self.assertRaisesRegex(RecoveryError, 'authentication'):
            open_bundle(bundle, 'wrong-password')
        tampered = json.loads(json.dumps(bundle))
        tampered['manifest']['server_id'] = 'another-server'
        with self.assertRaises(RecoveryError):
            open_bundle(tampered, PASSWORD)
        corrupted = json.loads(json.dumps(bundle))
        corrupted['ciphertext_base64'] = corrupted['ciphertext_base64'][:-8] + 'AAAAAAAA'
        with self.assertRaises(RecoveryError):
            open_bundle(corrupted, PASSWORD)

    def test_restore_requires_new_root_and_preserves_identity(self):
        bundle = self.bundle()
        target = Path(self.temporary.name) / 'restored'
        result = restore_bundle(bundle, target, PASSWORD, extract_password=PASSWORD)
        self.assertEqual('restored', result['status'])
        restored_bootstrap = json.loads((target / 'public/bootstrap.json').read_text(encoding='utf-8'))
        self.assertEqual(self.source.bootstrap['group_id'], restored_bootstrap['group_id'])
        self.assertEqual(self.source.bootstrap['server_id'], restored_bootstrap['server_id'])
        self.assertEqual(self.source.bootstrap['origin'], restored_bootstrap['origin'])
        self.assertEqual(self.source.bootstrap['group_key_id'], restored_bootstrap['group_key_id'])
        for name in ('root-ca-key.pem', 'group-key.pem', 'recovery-key.pem'):
            self.assertTrue((target / 'admin-private' / name).is_file())
        # A second restore into the same root must never overwrite material.
        with self.assertRaisesRegex(RecoveryError, 'existing_root'):
            restore_bundle(bundle, target, PASSWORD, extract_password=PASSWORD)

    def test_reauthorize_advances_generation_and_expiry_for_same_identity(self):
        root = Path(self.temporary.name) / 'reauth'
        restore_bundle(self.bundle(), root, PASSWORD, extract_password=PASSWORD)
        before = json.loads(base64.b64decode(
            json.loads((root / 'public/trust.json').read_text(encoding='utf-8'))['payload_base64']))
        args = parse_args(['reauthorize', '--root', str(root), '--trust-days', '365',
                           '--confirm', '--previous-authority-isolated', '--password', PASSWORD])
        code, out, err = run(lan_trust_admin.reauthorize, args)
        self.assertEqual(0, code, err)
        after = json.loads(base64.b64decode(
            json.loads((root / 'public/trust.json').read_text(encoding='utf-8'))['payload_base64']))
        self.assertEqual(before['generation'] + 1, after['generation'])
        self.assertGreater(after['expires_at'], before['expires_at'])
        self.assertEqual(before['group_id'], after['group_id'])
        self.assertEqual(before['servers'], after['servers'])
        self.assertEqual(before['servers'][0]['tls_issuer_spki_sha256'],
                         after['servers'][0]['tls_issuer_spki_sha256'])
        config = json.loads((root / 'server/public.json').read_text(encoding='utf-8'))
        self.assertEqual(after['generation'], json.loads(
            base64.b64decode(config['trust']['payload_base64']))['generation'])
        # The previous generation is retained as evidence.
        self.assertTrue((root / 'public/trust-gen1.json').is_file())
        group_key = load_private((root / 'admin-private/group-key.pem').read_text(encoding='ascii'), PASSWORD)
        verified = verify_envelope(config['trust'], group_key)
        self.assertEqual(after, verified)
        # Without --confirm no authority is changed.
        args = parse_args(['reauthorize', '--root', str(root), '--password', PASSWORD])
        code, _, err = run(lan_trust_admin.reauthorize, args)
        self.assertEqual(1, code)
        self.assertIn('--confirm', err)

    def test_rebuilt_server_uses_new_issuer_at_higher_generation(self):
        root = Path(self.temporary.name) / 'rebuild'
        restore_bundle(self.bundle(), root, PASSWORD, extract_password=PASSWORD)
        old_delegation = json.loads((root / 'server/delegation.json').read_text(encoding='utf-8'))
        online_password_file = Path(self.temporary.name) / 'online-password.txt'
        online_password_file.write_text('online-disposable-password', encoding='utf-8')
        args = parse_args(['rebuild-server', '--root', str(root), '--address', '127.0.0.1',
                           '--port', '19443', '--backend-port', '18765',
                           '--online-password-file', str(online_password_file),
                           '--trust-days', '365', '--confirm', '--previous-authority-isolated', '--password', PASSWORD])
        args.previous_authority_isolated = False
        code, _, err = run(lan_trust_admin.rebuild_server, args)
        self.assertEqual(1, code)
        self.assertIn('previous-authority-isolated', err)
        self.assertFalse((root / 'server/intermediate-key.pem').exists())
        args.previous_authority_isolated = True
        code, out, err = run(lan_trust_admin.rebuild_server, args)
        self.assertEqual(0, code, err)
        config = json.loads((root / 'server/public.json').read_text(encoding='utf-8'))
        payload = json.loads(base64.b64decode(config['trust']['payload_base64']))
        self.assertEqual(2, payload['generation'])
        new_delegation = json.loads((root / 'server/delegation.json').read_text(encoding='utf-8'))
        self.assertNotEqual(old_delegation['issuer_key_id'], new_delegation['issuer_key_id'])
        self.assertEqual(new_delegation['issuer_key_id'],
                         payload['servers'][0]['tls_issuer_spki_sha256'])
        self.assertEqual(self.source.bootstrap['group_id'], new_delegation['group_id'])
        self.assertEqual(self.source.bootstrap['server_id'], new_delegation['server_id'])
        group_key = load_private((root / 'admin-private/group-key.pem').read_text(encoding='ascii'), PASSWORD)
        target = make_delegation(
            group_id=new_delegation['group_id'], server_id=new_delegation['server_id'],
            origin=new_delegation['origin'], permitted_ip=new_delegation['permitted_ip'],
            permitted_dns=new_delegation['permitted_dns'],
            issuer_key_id=new_delegation['issuer_key_id'],
            issuer_spki_base64=new_delegation['issuer_spki_base64'],
            max_tls_validity_days=new_delegation['max_tls_validity_days'],
            issued_at=new_delegation['issued_at'], expires_at=new_delegation['expires_at'])
        verify_delegation(public_spki(group_key), target,
                          base64.b64decode(new_delegation['signature_base64']))
        self.assertTrue((root / 'server/pre-rebuild-delegation.json').is_file())
        # Running it again must not replace the now-serving material.
        code, _, err = run(lan_trust_admin.rebuild_server, args)
        self.assertEqual(1, code)
        self.assertIn('already exists', err)

    def test_interrupted_rebuild_is_inert_and_refuses_loading(self):
        root = Path(self.temporary.name) / 'interrupted-rebuild'
        restore_bundle(self.bundle(), root, PASSWORD, extract_password=PASSWORD)
        online = Path(self.temporary.name) / 'interrupted-online-password.txt'
        online.write_text('disposable-online-password', encoding='utf-8')
        args = parse_args(['rebuild-server', '--root', str(root), '--address', '127.0.0.1',
                          '--port', '19443', '--online-password-file', str(online),
                          '--confirm', '--previous-authority-isolated', '--password', PASSWORD])
        with patch.object(lan_trust_admin.OnlineIssuer, 'renew_tls_leaf', side_effect=OSError('injected')):
            code, _, err = run(lan_trust_admin.rebuild_server, args)
        self.assertEqual(1, code)
        self.assertTrue((root / 'state/rebuild-incomplete.json').is_file())
        with self.assertRaisesRegex(lan_trust_admin.AdminError, 'Interrupted rebuild'):
            lan_trust_admin._load_server(root, PASSWORD)
        self.assertFalse((root / 'server/public.json').exists())


if __name__ == '__main__':
    unittest.main()
