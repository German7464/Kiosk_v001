import io
import json
import subprocess
import sys
from contextlib import redirect_stdout
from unittest.mock import patch
import unittest

from kiosk.display.__main__ import main
from kiosk.display.session import install_for_display, prepare_active_view
from kiosk.publication.exporter import PackageError
from kiosk.publication.store import PublicationStore
from tests import test_publication_export as fixtures


class DisplaySessionTests(unittest.TestCase):
    def setUp(self):
        self.fixture = fixtures.ExportTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.fixture.export()
        self.store = PublicationStore(self.fixture.root / 'store')
        self.destination = self.fixture.root / 'native-view'

    def test_prepare_current_without_changing_activation(self):
        active = self.store.install(self.fixture.destination)
        original = (self.store.root / 'active.json').read_bytes()
        path = prepare_active_view(self.store.root, self.destination, mode='tv')
        descriptor = json.loads((path.parent / 'view.json').read_bytes())
        self.assertEqual(descriptor['package_sha256'], active.name)
        self.assertEqual(descriptor['mode'], 'tv')
        self.assertEqual((self.store.root / 'active.json').read_bytes(), original)
        self.assertEqual({item['path'] for item in descriptor['files']},
                         {'index.html', 'events.js', 'events.css', 'static/uploads/card.jpg'})

    def test_first_start_and_safe_cli_diagnostic(self):
        with self.assertRaisesRegex(PackageError, '^no_publication$'):
            prepare_active_view(self.store.root, self.destination)
        output = io.StringIO()
        with patch('sys.argv', ['display', '--store', str(self.store.root), '--destination', str(self.destination)]), redirect_stdout(output):
            self.assertEqual(main(), 1)
        self.assertEqual(json.loads(output.getvalue()), {'result': 'error', 'code': 'no_publication'})
        self.assertNotIn(str(self.fixture.root), output.getvalue())

    def test_prepare_uses_verified_previous_after_corruption(self):
        first = self.store.install(self.fixture.destination)
        with fixtures.connection(self.fixture.db) as db:
            db.execute("UPDATE settings SET value='8' WHERE key='content_version'")
        candidate = self.fixture.root / 'next'
        self.fixture.export(candidate)
        current = self.store.install(candidate)
        (current / 'data/events.json').write_bytes(b'broken')
        prepare_active_view(self.store.root, self.destination)
        descriptor = json.loads((self.destination / 'view.json').read_bytes())
        self.assertEqual(descriptor['revision'], '7')
        self.assertEqual(descriptor['package_sha256'], first.name)

    def next_package(self):
        with fixtures.connection(self.fixture.db) as db:
            db.execute("UPDATE settings SET value='8' WHERE key='content_version'")
        destination = self.fixture.root / 'next'
        self.fixture.export(destination)
        return destination

    def test_display_preflight_failure_preserves_publication_and_old_view(self):
        cache = self.fixture.root / 'views'
        first = install_for_display(self.fixture.destination, self.store.root, cache)
        pointer = (self.store.root / 'active.json').read_bytes()
        source = self.next_package()
        with self.assertRaisesRegex(PackageError, 'view_limit'):
            install_for_display(source, self.store.root, cache, max_cache_bytes=128 * 1024)
        self.assertEqual((self.store.root / 'active.json').read_bytes(), pointer)
        self.assertTrue(first.is_file())
        second = install_for_display(source, self.store.root, cache)
        self.assertNotEqual(first, second)
        self.assertEqual(json.loads((second.parent / 'view.json').read_bytes())['revision'], '8')
        self.assertEqual(install_for_display(source, self.store.root, cache), second)

    def test_first_publication_never_activates_without_view(self):
        cache = self.fixture.root / 'views'
        with self.assertRaisesRegex(PackageError, 'view_limit'):
            install_for_display(self.fixture.destination, self.store.root, cache, max_cache_bytes=128 * 1024)
        self.assertIsNone(self.store.active())
        with self.assertRaisesRegex(PackageError, 'overlapping_display_storage'):
            install_for_display(self.fixture.destination, self.store.root, self.store.root / 'views')
        self.assertIsNone(self.store.active())

    def test_process_crash_after_view_preflight_before_activation_and_retry(self):
        cache = self.fixture.root / 'views'
        first = install_for_display(self.fixture.destination, self.store.root, cache, mode='tv')
        pointer = (self.store.root / 'active.json').read_bytes()
        source = self.next_package()
        script = (
            "import os,sys; from kiosk.publication.store import PublicationStore; "
            "from kiosk.display.cache import prepare_package_view; "
            "PublicationStore(sys.argv[2]).install(sys.argv[1], pre_activate="
            "lambda package: (prepare_package_view(package,sys.argv[3],mode='tv'),os._exit(74)))")
        result = subprocess.run([sys.executable, '-c', script, str(source), str(self.store.root), str(cache)],
                                capture_output=True, timeout=30)
        self.assertEqual(result.returncode, 74, result.stderr)
        self.assertEqual((self.store.root / 'active.json').read_bytes(), pointer)
        self.assertTrue(first.is_file())
        second = install_for_display(source, self.store.root, cache, mode='tv')
        self.assertNotEqual(first, second)
        self.assertEqual(json.loads((second.parent / 'view.json').read_bytes())['revision'], '8')

    def test_changed_candidate_during_preflight_never_activates(self):
        self.store.install(self.fixture.destination)
        pointer = (self.store.root / 'active.json').read_bytes()
        source = self.next_package()
        def damage(package):
            (package / 'data/events.json').write_bytes(b'broken')
        with self.assertRaises(PackageError):
            self.store.install(source, pre_activate=damage)
        self.assertEqual((self.store.root / 'active.json').read_bytes(), pointer)

    def test_cli_installs_only_after_preparing_view(self):
        output = io.StringIO()
        cache = self.fixture.root / 'views'
        with patch('sys.argv', ['display', '--store', str(self.store.root), '--cache', str(cache),
                                '--package', str(self.fixture.destination), '--mode', 'tv']), redirect_stdout(output):
            self.assertEqual(main(), 0)
        self.assertEqual(json.loads(output.getvalue()), {'result': 'prepared', 'mode': 'tv'})
        package = self.store.active()
        self.assertIsNotNone(package)
        views = list(cache.glob('*/view.json'))
        self.assertEqual(len(views), 1)
        self.assertEqual(json.loads(views[0].read_bytes())['package_sha256'], package.name)
