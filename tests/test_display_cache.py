import json
import subprocess
import sys
import unittest
from unittest.mock import patch

from kiosk.display import cache
from kiosk.publication import renderer
from kiosk.publication.exporter import PackageError
from tests import test_display_session as sessions


class DisplayCacheTests(unittest.TestCase):
    def setUp(self):
        sessions.DisplaySessionTests.setUp(self)
        self.store.install(self.fixture.destination)
        self.cache_root = self.fixture.root / 'views'

    def prepare(self, **kwargs):
        return cache.prepare_cached_view(self.store.root, self.cache_root, **kwargs)

    def test_reopen_reuses_verified_artifact_without_build(self):
        path = self.prepare()
        original_pointer = (self.store.root / 'active.json').read_bytes()
        with patch.object(renderer, 'build_view', side_effect=AssertionError('must reuse')):
            self.assertEqual(self.prepare(), path)
        self.assertEqual((self.store.root / 'active.json').read_bytes(), original_pointer)

    def test_new_revision_and_modes_keep_previous_view(self):
        first = self.prepare()
        self.assertNotEqual(self.prepare(mode='tv'), first)
        from tests import test_publication_export as fixtures
        with fixtures.connection(self.fixture.db) as db:
            db.execute("UPDATE settings SET value='8' WHERE key='content_version'")
        source = self.fixture.root / 'next-package'
        self.fixture.export(source)
        current = self.store.install(source)
        second = self.prepare()
        self.assertNotEqual(first, second)
        self.assertTrue(first.is_file())
        (current / 'data/events.json').write_bytes(b'broken')
        self.assertEqual(self.prepare(), first)

    def test_damaged_cache_is_refused_without_overwrite(self):
        path = self.prepare()
        path.write_bytes(b'corrupt')
        with self.assertRaisesRegex(PackageError, 'cached_view_integrity'):
            self.prepare()
        self.assertEqual(path.read_bytes(), b'corrupt')

    def test_rehashed_renderer_and_extra_file_are_refused(self):
        path = self.prepare()
        folder = path.parent
        descriptor = json.loads((folder / 'view.json').read_bytes())
        import hashlib
        (folder / 'events.js').write_bytes(b'changed')
        for entry in descriptor['files']:
            if entry['path'] == 'events.js':
                entry.update(size=7, sha256=hashlib.sha256(b'changed').hexdigest())
        (folder / 'view.json').write_text(json.dumps(descriptor))
        with self.assertRaisesRegex(PackageError, 'cached_renderer_mismatch'):
            self.prepare()
        (folder / 'events.js').write_bytes((renderer.ASSETS / 'events.js').read_bytes())
        (folder / 'extra').write_bytes(b'x')
        # Rebuild inventory from a fresh artifact rather than hiding the earlier mismatch.
        other = self.prepare(mode='tv').parent
        (other / 'extra').write_bytes(b'x')
        with self.assertRaisesRegex(PackageError, 'invalid_cached_view'):
            self.prepare(mode='tv')

    def test_capacity_and_abandoned_staging_preserve_old_view(self):
        path = self.prepare()
        orphan = self.cache_root / '.events-view-abandoned'
        orphan.mkdir()
        (orphan / 'partial').write_bytes(b'x' * 4096)
        with self.assertRaisesRegex(PackageError, 'view_cache_limit'):
            self.prepare(max_bytes=65537)
        self.assertTrue(path.is_file())
        self.assertTrue((orphan / 'partial').is_file())
        with self.assertRaisesRegex(PackageError, 'view_limit'):
            self.prepare(mode='tv', max_bytes=128 * 1024)
        self.assertTrue(path.is_file())
        self.assertEqual(len(list(self.cache_root.glob('.events-view-*'))), 1)

    def test_build_identity_and_competing_writer(self):
        first = self.prepare()
        with patch.object(cache, 'renderer_identity', return_value='new-build'):
            self.assertNotEqual(self.prepare(), first)
        with cache.PublicationStore(self.cache_root)._lease():
            with self.assertRaisesRegex(PackageError, 'store_busy'):
                self.prepare()

    def test_no_free_disk_and_cancelled_build_leave_old_view(self):
        first = self.prepare()
        with patch.object(renderer.shutil, 'disk_usage') as usage:
            usage.return_value.free = 0
            with self.assertRaisesRegex(PackageError, 'view_disk_full'):
                self.prepare(mode='tv')
        original = renderer._stream_stable
        def cancel(root, name, output=None):
            if output is not None:
                raise KeyboardInterrupt
            return original(root, name, output)
        with patch.object(renderer, '_stream_stable', side_effect=cancel):
            with self.assertRaises(KeyboardInterrupt):
                self.prepare(mode='tv')
        self.assertEqual(self.prepare(), first)
        self.assertFalse(list(self.cache_root.glob('.events-view-*')))

    def test_separate_process_reopens_cache_through_cli(self):
        path = self.prepare(mode='tv')
        before = {item.relative_to(self.cache_root): item.read_bytes()
                  for item in self.cache_root.rglob('*') if item.is_file()}
        result = subprocess.run([sys.executable, '-m', 'kiosk.display', '--store', str(self.store.root),
                                 '--cache', str(self.cache_root), '--mode', 'tv'],
                                capture_output=True, timeout=30)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout), {'result': 'prepared', 'mode': 'tv'})
        after = {item.relative_to(self.cache_root): item.read_bytes()
                 for item in self.cache_root.rglob('*') if item.is_file()}
        self.assertEqual(before, after)
        self.assertTrue(path.is_file())

