"""Regression tests for the update transaction and recovery findings.

These cover the coordinator findings at the unit level (pure logic + mocked
Windows boundaries): exclusive ownership, operation-specific artifacts, prior
service-state restoration, interrupted directory-transition recovery, snapshot
re-verification, and data-schema compatibility. Installed A->B acceptance is
performed separately on the retained VMs.
"""
import json
import os
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from kiosk.core.update import verify_package, verify_snapshot
from kiosk.core.update_crypto import generate_key, public_key_id, sign

import kiosk.launcher.updater as server_updater
from kiosk.launcher.storage import Storage


def _make_package(root, product="kiosk-server", version="3.0.1", data_schema=1):
    private, public = generate_key()
    import hashlib

    manifest = {
        "schema_version": 1, "product": product, "platform": "win-x64", "version": version,
        "min_compatible": "2.0.0", "data_schema": data_schema,
        "key_id": public_key_id(public),
        "files": {"installer.exe": hashlib.sha256(b"payload").hexdigest()},
    }
    (root / "installer.exe").write_bytes(b"payload")
    manifest_bytes = json.dumps(manifest).encode("utf-8")
    (root / "manifest.json").write_bytes(manifest_bytes)
    (root / "manifest.json.sig").write_bytes(sign(private, manifest_bytes))
    return public, manifest


class SnapshotTests(unittest.TestCase):
    def test_snapshot_reverifies_executed_bytes(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            package = root / "pkg"
            package.mkdir()
            public, manifest = _make_package(package)
            snapshot = root / "snap"
            snapshot.mkdir()
            shutil.copy2(package / "installer.exe", snapshot / "installer.exe")
            self.assertEqual(verify_snapshot(snapshot, manifest), snapshot)
            # Tampering the snapshot after copy must be rejected (bytes executed).
            (snapshot / "installer.exe").write_bytes(b"tampered")
            with self.assertRaises(ValueError):
                verify_snapshot(snapshot, manifest)

    def test_snapshot_rejects_extra_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            package = root / "pkg"
            package.mkdir()
            public, manifest = _make_package(package)
            snapshot = root / "snap"
            snapshot.mkdir()
            shutil.copy2(package / "installer.exe", snapshot / "installer.exe")
            (snapshot / "evil.dll").write_bytes(b"x")
            with self.assertRaises(ValueError):
                verify_snapshot(snapshot, manifest)


class DataSchemaTests(unittest.TestCase):
    def test_invalid_data_schema_in_manifest_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            package = Path(tmp) / "pkg"
            package.mkdir()
            private, public = generate_key()
            import hashlib

            manifest = {
                "schema_version": 1, "product": "kiosk-server", "platform": "win-x64",
                "version": "3.0.1", "min_compatible": "2.0.0", "data_schema": "oops",
                "key_id": public_key_id(public),
                "files": {"installer.exe": hashlib.sha256(b"payload").hexdigest()},
            }
            (package / "installer.exe").write_bytes(b"payload")
            manifest_bytes = json.dumps(manifest).encode("utf-8")
            (package / "manifest.json").write_bytes(manifest_bytes)
            (package / "manifest.json.sig").write_bytes(sign(private, manifest_bytes))
            with self.assertRaises(ValueError):
                verify_package(package, public, product="kiosk-server")

    def test_schema_mismatch_rejected(self):
        storage = Storage(Path(tempfile.mkdtemp()))
        with mock.patch.object(server_updater, "data_schema", return_value=1):
            server_updater._check_data_schema(storage, {"data_schema": 1})  # ok
            with self.assertRaises(ValueError):
                server_updater._check_data_schema(storage, {"data_schema": 2})
        with mock.patch.object(server_updater, "data_schema", return_value=0):
            server_updater._check_data_schema(storage, {"data_schema": 9})  # fresh, no data -> allowed


class TransactionSafetyTests(unittest.TestCase):
    def setUp(self):
        from kiosk.core import update_owner
        self.owner = update_owner
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.storage = Storage(self.root / "data")
        self.storage.directory("updates").mkdir(parents=True)
        self.lock = server_updater._lock_path(self.storage)
        self.addCleanup(lambda: update_owner.release(self.lock))

    def test_preparation_live_pid_no_task_cannot_be_recovered(self):
        import subprocess, sys
        tx = server_updater._acquire_lock(self.storage)
        server_updater._write_journal(self.storage, tx, {"state": "prepared"})
        before = self.lock.read_bytes()
        code = "from kiosk.launcher.updater import _acquire_lock; from kiosk.launcher.storage import Storage; from pathlib import Path; _acquire_lock(Storage(Path(__import__('sys').argv[1])))"
        child = subprocess.run([sys.executable, "-c", code, str(self.storage.root)], capture_output=True, text=True, timeout=10)
        self.assertNotEqual(child.returncode, 0)
        self.assertIn("already in progress", child.stderr)
        self.assertEqual(self.lock.read_bytes(), before)
        with self.assertRaisesRegex(RuntimeError, "already in progress"):
            server_updater._recover_interrupted(self.storage)
        self.assertEqual(server_updater.upgrade_status(self.storage)["state"], "pending")
        self.assertEqual(self.lock.read_bytes(), before)

    def test_corrupt_metadata_is_preserved(self):
        self.lock.write_bytes(b"corrupt")
        prior = {'state': 'committed', 'transaction_id': 'previous', 'from_version': '1.0', 'to_version': '2.0'}
        self.lock.with_suffix('.last.json').write_text(json.dumps(prior))
        with self.assertRaisesRegex(RuntimeError, "recovery-required"):
            server_updater._acquire_lock(self.storage)
        self.assertEqual(self.lock.read_bytes(), b"corrupt")
        self.assertEqual(server_updater.upgrade_status(self.storage)['state'], 'recovery-required')
        from kiosk.display import updater as client
        with mock.patch.object(client, 'data_root', return_value=self.root):
            client._lock_path().write_bytes(b'corrupt')
            client._lock_path().with_suffix('.last.json').write_text(json.dumps(prior))
            self.assertEqual(client.upgrade_status()['state'], 'recovery-required')

    def test_error_result_preserves_every_recovery_copy_server_and_client(self):
        from kiosk.display import updater as client
        from contextlib import ExitStack
        for module in (server_updater, client):
            with self.subTest(module=module.__name__), ExitStack() as stack:
                root = self.root / module.PRODUCT
                root.mkdir()
                if module is client:
                    stack.enter_context(mock.patch.object(client, "data_root", return_value=root))
                    args = ()
                else:
                    args = (Storage(root),)
                    (root / "updates").mkdir()
                lock = module._lock_path(*args)
                lock.write_text(json.dumps({"transaction_id": "deadbeef"}))
                module._write_journal(*args, "deadbeef", {"state": "staged", "from_version": "1.0", "to_version": "2.0"})
                result = module._tx_path(*args, "deadbeef", "result")
                result.write_text("error: rollback incomplete")
                copies = []
                for kind in ("helper_dir", "snapshot_dir"):
                    folder = module._tx_path(*args, "deadbeef", kind)
                    folder.mkdir()
                    f = folder / "sentinel"; f.write_bytes(b"recovery"); copies.append(f)
                for name in ("staging", "bad", "backup", "journal"):
                    f = root / name; f.write_bytes(b"original"); copies.append(f)
                status = module.upgrade_status(*args)
                self.assertEqual(status["state"], "recovery-required")
                with self.assertRaisesRegex(RuntimeError, "recovery-required"):
                    module._recover_interrupted(*args)
                self.assertTrue(lock.exists())
                self.assertEqual(result.read_text(), "error: rollback incomplete")
                self.assertTrue(all(f.is_file() for f in copies))

    def test_rollback_restores_running_service_and_checks_health(self):
        live = self.root / "Kiosk"; live.mkdir(); (live / "x").write_text("new")
        old = self.root / "Kiosk.old"; old.mkdir(); (old / "x").write_text("old")
        journal = {"handoff_prepared": True, "backup_bin": str(old)}
        with mock.patch.object(server_updater, "binary_directory", return_value=live), mock.patch.object(server_updater, "control_service") as control, mock.patch.object(server_updater, "_restored", return_value=True) as check:
            server_updater._rollback(self.storage, "t", journal, "running")
        self.assertEqual((live / "x").read_text(), "old")
        self.assertTrue((self.root / "Kiosk.bad.t" / "x").is_file())
        self.assertEqual(control.call_args_list, [mock.call("stop"), mock.call("start")])
        check.assert_called_once()

    def test_failed_service_restart_never_finalizes_rollback(self):
        with mock.patch.object(server_updater, "control_service", side_effect=RuntimeError("start failed")):
            with self.assertRaisesRegex(RuntimeError, "start failed"):
                server_updater._rollback(self.storage, "t", {}, "running")

    def test_unverified_rollback_keeps_journal_and_lock(self):
        self.lock.write_text(json.dumps({"transaction_id": "deadbeef"}))
        with mock.patch.object(server_updater, "_restored", return_value=False):
            with self.assertRaisesRegex(RuntimeError, "recovery-required"):
                server_updater._finalize(self.storage, "deadbeef", {}, "rolled_back")
        self.assertTrue(self.lock.exists())
        self.assertEqual(server_updater._read_journal(self.storage, "deadbeef")["state"], "recovery-required")

    def test_prior_version_marker_cannot_hide_changed_rollback_tree(self):
        from kiosk.display import updater as client
        live = self.root / 'client'
        live.mkdir()
        (live / 'version.json').write_text('{"version":"3.0.15"}')
        (live / 'payload').write_bytes(b'previous executable')
        journal = {'from_version': '3.0.15', 'prior_digest': self.owner.tree_digest(live)}
        with mock.patch.object(client, 'app_root', return_value=live):
            self.assertTrue(client._restored(journal))
            (live / 'payload').write_bytes(b'broken executable')
            self.assertFalse(client._restored(journal))

    def test_missing_helper_result_does_not_infer_success_from_trees(self):
        self.lock.write_text(json.dumps({"transaction_id": "deadbeef"}))
        server_updater._write_journal(self.storage, "deadbeef", {"state": "staged"})
        with self.assertRaisesRegex(RuntimeError, "recovery-required"):
            server_updater._recover_interrupted(self.storage)
        self.assertTrue(self.lock.exists())

    def test_server_verify_failure_releases_kernel_and_metadata(self):
        with mock.patch.object(server_updater, "require_administrator"), mock.patch("sys.frozen", True, create=True), mock.patch.object(server_updater, "verify_and_read", side_effect=ValueError("bad package")):
            with self.assertRaises(ValueError):
                server_updater.upgrade(self.storage, self.root)
        self.assertFalse(self.lock.exists())
        self.owner.acquire(self.lock)


class DeploymentBoundaryTests(unittest.TestCase):
    def test_client_version_marker_is_not_application_readiness(self):
        from tools import build_windows_update as workflow
        self.assertFalse(workflow._client_healthy({'version': '3.0.16', 'staging': False, 'tasks': 0}))
        self.assertFalse(workflow._client_healthy({'version': '3.0.16', 'native': {'renderer_ready': True}}))

    def test_remote_invocation_keeps_session_until_terminal_status(self):
        from tools import build_windows_update as workflow
        for name in ('pc4', 'pc5'):
            with self.subTest(target=name):
                captured = {}
                def transfer(local, target, remote):
                    captured['script'] = Path(local).read_text(encoding='utf-8-sig')
                    captured['remote'] = remote
                with mock.patch.object(workflow, 'scp_file', side_effect=transfer), mock.patch.object(workflow, 'ssh', return_value='committed') as ssh:
                    workflow._upgrade(workflow.TARGETS[name], 'C:/fixture/package')
                self.assertIn('upgrade-status', captured['script'])
                self.assertIn('recovery-required', captured['script'])
                self.assertIn('-File', ssh.call_args.args[1])
                self.assertNotIn('-Command -', ssh.call_args.args[1])
                self.assertNotIn('SYSTEM', captured['script'])
                self.assertTrue(captured['remote'].startswith('C:/ProgramData/Kiosk/updates/' if name == 'pc4' else 'C:/Users/Work/AppData/Local/KioskConnect/'))

    def test_old_commit_cannot_confirm_requested_update(self):
        from tools import build_windows_update as workflow
        with mock.patch.object(workflow, '_status', return_value={'state': 'committed', 'version': '3.0.15'}):
            result = workflow._wait_and_verify(workflow.TARGETS['pc4'], '3.0.16')
        self.assertEqual(result['state'], 'failed')

    def test_recovery_required_is_terminal_failure(self):
        from tools import build_windows_update as workflow
        with mock.patch.object(workflow, '_status', return_value={'state': 'recovery-required'}):
            result = workflow._wait_and_verify(workflow.TARGETS['pc4'], '3.0.16')
        self.assertEqual(result['state'], 'recovery-required')


if __name__ == "__main__":
    unittest.main()
