import hashlib
from html.parser import HTMLParser
import json
from pathlib import Path
import unittest
from unittest.mock import patch

from kiosk.publication import renderer
from kiosk.publication.exporter import PackageError
from tests import test_publication_export as fixtures


class BootstrapParser(HTMLParser):
    def __init__(self, html):
        super().__init__()
        self.inside = False
        self.payload = ''
        self.scripts = []
        self.feed(html)

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == 'script':
            self.scripts.append(attrs)
            self.inside = attrs.get('id') == 'bootstrap'

    def handle_endtag(self, tag):
        if tag == 'script':
            self.inside = False

    def handle_data(self, text):
        if self.inside:
            self.payload += text


class RendererTests(unittest.TestCase):
    def setUp(self):
        self.fixture = fixtures.ExportTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.destination = self.fixture.root / 'view'

    def build(self, **kwargs):
        self.fixture.export()
        return renderer.build_view(self.fixture.destination, self.destination, **kwargs)

    def test_local_view_complete_for_both_modes(self):
        self.fixture.export()
        for mode in ('tv', 'kiosk'):
            path = renderer.build_view(self.fixture.destination, self.fixture.root / mode, mode=mode)
            html = path.read_text(encoding='utf-8')
            parsed = BootstrapParser(html)
            bootstrap = json.loads(parsed.payload)
            self.assertEqual(bootstrap['mode'], mode)
            self.assertEqual(bootstrap['data']['content_version'], 7)
            self.assertEqual(bootstrap['media']['/static/uploads/card.jpg'], 'static/uploads/card.jpg')
            self.assertTrue((path.parent / 'static/uploads/card.jpg').is_file())
            self.assertEqual((path.parent / 'events.js').read_bytes(), (renderer.ASSETS / 'events.js').read_bytes())
            self.assertIn("connect-src 'none'", html)
            self.assertNotIn('/api/', html)
            self.assertEqual(len(parsed.scripts), 2)

    def test_content_is_json_not_executable_markup(self):
        attack = '</script><script>alert(1)</script><img src=x onerror=alert(1)>'
        with fixtures.connection(self.fixture.db) as db:
            db.execute('UPDATE events SET title=? WHERE id=1', (attack,))
            db.execute('UPDATE settings SET value=? WHERE key=\'site_title\'', (attack,))
        path = self.build()
        html = path.read_text(encoding='utf-8')
        parsed = BootstrapParser(html)
        self.assertEqual(len(parsed.scripts), 2)
        self.assertNotIn('<script>alert', html)
        self.assertEqual(json.loads(parsed.payload)['data']['events'][0]['title'], attack)

    def test_packaged_code_never_becomes_renderer(self):
        self.fixture.export()
        package = self.fixture.destination
        name = 'resources/static/js/kiosk_events.js'
        payload = b'globalThis.PACKAGE_ATTACK = true;'
        (package / name).write_bytes(payload)
        manifest = json.loads((package / 'manifest.json').read_bytes())
        entry = next(entry for entry in manifest['files'] if entry['path'] == name)
        entry.update(size=len(payload), sha256=hashlib.sha256(payload).hexdigest())
        (package / 'manifest.json').write_text(json.dumps(manifest))
        renderer.build_view(package, self.destination)
        self.assertNotIn('PACKAGE_ATTACK', (self.destination / 'events.js').read_text())
        self.assertFalse((self.destination / 'resources').exists())

    def test_language_and_missing_translation_fallback(self):
        with fixtures.connection(self.fixture.db) as db:
            db.execute("INSERT INTO settings VALUES ('interface_language','ru')")
        path = self.build()
        bootstrap = json.loads(BootstrapParser(path.read_text(encoding='utf-8')).payload)
        self.assertIn('lang="ru"', path.read_text(encoding='utf-8'))
        shipped = json.loads((renderer.TRANSLATIONS / 'ru.json').read_text(encoding='utf-8'))
        self.assertEqual(bootstrap['labels']['common.next'], shipped['common.next'])
        self.assertNotEqual(bootstrap['labels']['common.next'], 'Next')

    def test_failure_cleanup_and_existing_destination_preserved(self):
        self.fixture.export()
        with patch.object(renderer, '_stream_stable', side_effect=OSError('synthetic disk full')):
            with self.assertRaisesRegex(PackageError, 'view_build_failed'):
                renderer.build_view(self.fixture.destination, self.destination)
        self.assertFalse(self.destination.exists())
        self.assertFalse(list(self.destination.parent.glob('.events-view-*')))
        renderer.build_view(self.fixture.destination, self.destination)
        original = (self.destination / 'index.html').read_bytes()
        with self.assertRaisesRegex(PackageError, 'destination_exists'):
            renderer.build_view(self.fixture.destination, self.destination)
        self.assertEqual((self.destination / 'index.html').read_bytes(), original)
        with self.assertRaisesRegex(PackageError, 'unsupported_display_mode'):
            renderer.build_view(self.fixture.destination, self.fixture.root / 'invalid', mode='admin')

    def test_translation_fallback_and_interrupted_build(self):
        with fixtures.connection(self.fixture.db) as db:
            db.execute("INSERT INTO settings VALUES ('interface_language','de')")
        self.fixture.export()
        original = Path.read_text
        def missing_translation(path, *args, **kwargs):
            return '{}' if path == renderer.TRANSLATIONS / 'de.json' else original(path, *args, **kwargs)
        with patch.object(Path, 'read_text', missing_translation):
            path = renderer.build_view(self.fixture.destination, self.destination)
        bootstrap = json.loads(BootstrapParser(path.read_text(encoding='utf-8')).payload)
        self.assertEqual(bootstrap['labels']['common.next'], 'Next')
        with patch.object(renderer, '_stream_stable', side_effect=KeyboardInterrupt):
            with self.assertRaises(KeyboardInterrupt):
                renderer.build_view(self.fixture.destination, self.fixture.root / 'cancelled')
        self.assertFalse((self.fixture.root / 'cancelled').exists())
        self.assertFalse(list(self.fixture.root.glob('.events-view-*')))

    def test_changed_media_cannot_enter_view(self):
        self.fixture.export()
        original = renderer._stream_stable
        def mutate(root, name, output=None):
            with (Path(root) / name).open('ab') as source:
                source.write(b'extra')
            return original(root, name, output)
        with patch.object(renderer, '_stream_stable', side_effect=mutate):
            with self.assertRaisesRegex(PackageError, '^source_changed$'):
                renderer.build_view(self.fixture.destination, self.destination)
        self.assertFalse(self.destination.exists())
        self.assertFalse(list(self.fixture.root.glob('.events-view-*')))
