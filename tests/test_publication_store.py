import json
from pathlib import Path
import unittest
from unittest.mock import patch

from kiosk.publication.compatibility import ClientRuntime
from kiosk.publication.exporter import PackageError
from kiosk.publication.store import POINTER_RESERVE_BYTES, PublicationStore
from tests import test_publication_export as fixtures


class StoreTests(unittest.TestCase):
    def setUp(self):
        fixture = fixtures.ExportTests()
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        self.fixture = fixture
        fixture.export()
        self.source = fixture.destination
        self.root = fixture.root / 'client-store'
        self.store = PublicationStore(self.root)

    def next_package(self):
        with fixtures.connection(self.fixture.db) as db:
            db.execute("UPDATE settings SET value='8' WHERE key='content_version'")
            db.execute("UPDATE events SET title='Next generation' WHERE id=1")
        path = self.fixture.root / 'next-package'
        self.fixture.export(path)
        return path

    def test_install_restart_idempotence_and_previous_retention(self):
        self.assertIsNone(self.store.active())
        first = self.store.install(self.source)
        self.assertEqual(PublicationStore(self.root).active(), first)
        state = (self.root / 'active.json').read_bytes()
        self.assertEqual(self.store.install(self.source), first)
        self.assertEqual((self.root / 'active.json').read_bytes(), state)
        second = self.store.install(self.next_package())
        self.assertNotEqual(first, second)
        self.assertTrue(first.is_dir())
        self.assertEqual(PublicationStore(self.root).active(), second)

    def test_corrupt_update_and_incompatible_runtime_leave_active(self):
        active = self.store.install(self.source)
        candidate = self.next_package()
        (candidate / 'static/uploads/card.jpg').write_bytes(b'corrupt')
        with self.assertRaises(PackageError):
            self.store.install(candidate)
        self.assertEqual(self.store.active(), active)
        with self.assertRaises(PackageError):
            PublicationStore(self.root, runtime=ClientRuntime(frozenset())).install(self.source)
        self.assertEqual(self.store.active(), active)

    def test_pointer_and_active_corruption_fall_back_after_restart(self):
        previous = self.store.install(self.source)
        current = self.store.install(self.next_package())
        (current / 'data/events.json').write_bytes(b'broken')
        self.assertEqual(PublicationStore(self.root).active(), previous)
        (self.root / 'active.json').write_bytes(b'broken')
        self.assertEqual(PublicationStore(self.root).active(), previous)
        (previous / 'data/events.json').write_bytes(b'broken')
        with self.assertRaisesRegex(PackageError, 'no_valid_publication'):
            self.store.active()

    def test_interrupted_pointer_switch_keeps_previous(self):
        from kiosk.publication import store
        previous = self.store.install(self.source)
        candidate = self.next_package()
        replace = store.os.replace
        def interrupt(source, target):
            if Path(target).name == 'active.json':
                raise KeyboardInterrupt()
            return replace(source, target)
        with patch.object(store.os, 'replace', side_effect=interrupt):
            with self.assertRaises(KeyboardInterrupt):
                self.store.install(candidate)
        self.assertEqual(PublicationStore(self.root).active(), previous)
        self.assertFalse(list(self.root.glob('.pointer-*')))
        installed = self.store.install(candidate)
        self.assertEqual(self.store.active(), installed)

    def test_partial_copy_disk_error_and_cancellation_cleanup(self):
        from kiosk.publication import store
        previous = self.store.install(self.source)
        candidate = self.next_package()
        original = store._stream_stable
        for failure in (OSError('synthetic disk full'), KeyboardInterrupt()):
            def fail(root, name, output=None):
                if output is not None:
                    output.write(b'partial')
                    raise failure
                return original(root, name, output)
            with self.subTest(failure=type(failure).__name__), patch.object(store, '_stream_stable', side_effect=fail):
                with self.assertRaises(KeyboardInterrupt if isinstance(failure, KeyboardInterrupt) else PackageError):
                    self.store.install(candidate)
            self.assertFalse(list(self.root.glob('.incoming-*')))
            self.assertEqual(self.store.active(), previous)

    def test_quota_disk_preflight_and_writer_lock(self):
        from kiosk.publication import store
        previous = self.store.install(self.source)
        candidate = self.next_package()
        with self.assertRaisesRegex(PackageError, 'store_limit'):
            PublicationStore(self.root, max_bytes=POINTER_RESERVE_BYTES + 1).install(candidate)
        disk = store.shutil.disk_usage(self.root)._replace(free=0)
        with patch.object(store.shutil, 'disk_usage', return_value=disk):
            with self.assertRaisesRegex(PackageError, 'store_disk_full'):
                self.store.install(candidate)
        with self.store._lease():
            with self.assertRaisesRegex(PackageError, 'store_busy'):
                PublicationStore(self.root).install(candidate)
        self.assertEqual(self.store.active(), previous)

    def test_pointer_cannot_escape_store(self):
        self.store.install(self.source)
        (self.root / 'active.json').write_text(json.dumps(
            {'schema_version': 1, 'current': '../source', 'previous': None}))
        with self.assertRaisesRegex(PackageError, 'no_valid_publication'):
            self.store.active()

    def test_deep_and_oversized_pointer_have_safe_failure(self):
        self.store.install(self.source)
        for payload in (b'[' * 1200 + b'0' + b']' * 1200, b'x' * 5000):
            (self.root / 'active.json').write_bytes(payload)
            with self.assertRaisesRegex(PackageError, '^no_valid_publication$'):
                self.store.active()

    def test_store_reparse_guard_and_pointer_commit_failure(self):
        from kiosk.publication import store
        previous = self.store.install(self.source)
        with patch.object(store, '_is_link', return_value=True):
            with self.assertRaisesRegex(PackageError, 'unsafe_store'):
                self.store.active()
        candidate = self.next_package()
        replace = store.os.replace
        def disk_full(source, target):
            if Path(target).name == 'active.json':
                raise OSError('synthetic pointer disk failure')
            return replace(source, target)
        with patch.object(store.os, 'replace', side_effect=disk_full):
            with self.assertRaisesRegex(PackageError, 'store_failed'):
                self.store.install(candidate)
        self.assertEqual(PublicationStore(self.root).active(), previous)
        self.assertFalse(list(self.root.glob('.pointer-*')))

    def test_source_changes_during_copy_never_activate(self):
        from kiosk.publication import store
        previous = self.store.install(self.source)
        candidate = self.next_package()
        original = store._stream_stable
        def mutate(root, name, output=None):
            if output is not None and name == 'data/events.json':
                with (candidate / name).open('ab') as stream:
                    stream.write(b' ')
            return original(root, name, output)
        with patch.object(store, '_stream_stable', side_effect=mutate):
            with self.assertRaisesRegex(PackageError, 'source_changed'):
                self.store.install(candidate)
        self.assertEqual(self.store.active(), previous)
        self.assertFalse(list(self.root.glob('.incoming-*')))

    def test_abrupt_process_exit_before_pointer_commit(self):
        import subprocess
        import sys
        previous = self.store.install(self.source)
        candidate = self.next_package()
        script = """
import os, sys
from unittest.mock import patch
from kiosk.publication import store
original = store._atomic_write
def crash(path, payload):
    if path.name == 'active.json':
        os._exit(73)
    return original(path, payload)
with patch.object(store, '_atomic_write', side_effect=crash):
    store.PublicationStore(sys.argv[1]).install(sys.argv[2])
"""
        result = subprocess.run([sys.executable, '-c', script, str(self.root), str(candidate)],
                                capture_output=True, timeout=20)
        self.assertEqual(result.returncode, 73, result.stderr.decode(errors='replace'))
        self.assertEqual(PublicationStore(self.root).active(), previous)
        current = self.store.install(candidate)
        self.assertNotEqual(current, previous)
        self.assertEqual(PublicationStore(self.root).active(), current)
