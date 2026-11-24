"""Focused Stage 6 checks for the internal Events feature and fixture seed."""
import hashlib
import json
from pathlib import Path
import shutil
import sqlite3
import tempfile
import unittest
from contextlib import closing

from PIL import Image

from kiosk.delivery.protocol import decode, encode, sha
from kiosk.features import events
from kiosk.features.events import payload as event_payload
from kiosk.publication import mapping as legacy_mapping
from kiosk.publication.baseline import seed
from kiosk.publication.exporter import RESOURCES, PackageError, export_events_package, verify_package
from kiosk.publication.workspace import Workspace, WorkspaceError
from kiosk.version import VERSION


def event(title='Event', *, status='active', images=(), tags=(), event_date='2026-11-25', sort_order=0):
    return dict(title=title, short_description='Short', full_description='Full',
                event_date=event_date, place='Hall', sort_order=sort_order, status=status,
                images=list(images), tags=list(tags))


class EventsFixture(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.database = self.root / 'source.sqlite'
        self.uploads = self.root / 'uploads'
        self.uploads.mkdir()
        for name, color in (('kiosk.jpg', 'red'), ('tv.jpg', 'green'), ('thumb.jpg', 'blue')):
            Image.new('RGB', (4, 4), color).save(self.uploads / name)
        with closing(sqlite3.connect(self.database)) as db, db:
            db.executescript('''
                CREATE TABLE events (id INTEGER,title TEXT,short_description TEXT,full_description TEXT,event_date TEXT,
                    place TEXT,image_kiosk TEXT,image_tv TEXT,image_thumb TEXT,sort_order INTEGER,status TEXT,image_original TEXT);
                CREATE TABLE tags (id INTEGER,name TEXT);
                CREATE TABLE event_tags (event_id INTEGER,tag_id INTEGER);
                CREATE TABLE settings (key TEXT,value TEXT);
                INSERT INTO events VALUES (1,'Three variants','Short','Full','2026-11-25','Hall',
                    '/static/uploads/kiosk.jpg','/static/uploads/tv.jpg','/static/uploads/thumb.jpg',0,'active','private-a');
                INSERT INTO events VALUES (2,'No variants','','',NULL,'',NULL,NULL,NULL,1,'active','private-b');
                INSERT INTO events VALUES (3,'Hidden','','',NULL,'',NULL,NULL,NULL,2,'hidden','private-c');
                INSERT INTO tags VALUES (1,'Alpha');
                INSERT INTO tags VALUES (2,'Beta');
                INSERT INTO event_tags VALUES (1,2);
                INSERT INTO event_tags VALUES (1,1);
                INSERT INTO event_tags VALUES (2,2);
                INSERT INTO settings VALUES ('content_version','11');
                INSERT INTO settings VALUES ('site_title','Synthetic Events');
                INSERT INTO settings VALUES ('interface_language','en');
                INSERT INTO settings VALUES ('password','must-not-export');
            ''')
        self.package = self.root / 'package'
        export_events_package(self.database, self.uploads, Path('kiosk'), self.package)
        self.manifest = verify_package(self.package)
        self.identity = sha(encode(self.manifest))
        self.workspace = Workspace(self.root / 'workspace.sqlite', b'R' * 32,
                                   'group', 'https://kiosk.example')

    def second_package(self):
        with closing(sqlite3.connect(self.database)) as db, db:
            db.execute("UPDATE settings SET value='12' WHERE key='content_version'")
        destination = self.root / 'package-12'
        export_events_package(self.database, self.uploads, Path('kiosk'), destination)
        manifest = verify_package(destination)
        return destination, sha(encode(manifest))

    def seed(self):
        return seed(self.workspace, self.package, self.identity, confirm_disposable=True)

    def rows(self, query):
        with self.workspace.db() as db:
            return [tuple(row) for row in db.execute(query)]

    def state(self):
        return {
            'objects': self.rows('SELECT * FROM objects ORDER BY id'),
            'revisions': self.rows('SELECT * FROM revisions ORDER BY id,version'),
            'settings': self.rows('SELECT * FROM settings'),
            'sequence': self.rows('SELECT * FROM sequence'),
            'staged': self.rows('SELECT * FROM staged ORDER BY id'),
            'plans': self.rows('SELECT * FROM plans ORDER BY id'),
            'heads': self.rows('SELECT * FROM heads ORDER BY id'),
            'baseline': self.rows('SELECT * FROM baseline'),
        }

    def package_files(self):
        return {path.relative_to(self.package).as_posix(): path.read_bytes()
                for path in self.package.rglob('*') if path.is_file()}


class MetadataTests(unittest.TestCase):
    def test_static_metadata_and_health(self):
        metadata = events.METADATA
        self.assertEqual(metadata['id'], 'events')
        self.assertEqual(metadata['version'], 1)
        self.assertEqual(metadata['contract_version'], 1)
        self.assertEqual(metadata['data_version'], 1)
        self.assertEqual(metadata['core_version'], {'min': VERSION, 'max_exclusive': '4.0.0'})
        self.assertEqual(metadata['dependencies'], ())
        self.assertEqual(metadata['health_check'], 'kiosk.features.events.health')
        self.assertIn('events.snapshot-mapping-v1', metadata['capabilities'])
        self.assertIn('data/events.json', metadata['resources'])
        self.assertIn('resources/templates/kiosk_events.html', metadata['resources'])
        self.assertEqual(set(metadata['resources']),
                         {'data/events.json'} | {'resources/' + name for name in RESOURCES})
        self.assertEqual(events.health()['status'], 'ok')
        self.assertEqual(events.health()['contract_version'], 1)

    def test_mapping_facade_is_byte_identical_to_feature(self):
        objects = {
            '1': {'version': 1, 'payload': event(images=('/static/uploads/a.jpg', '/static/uploads/b.jpg',
                                                         '/static/uploads/c.jpg'), tags=('Beta', 'Alpha'))},
            '2': {'version': 1, 'payload': event('Hidden', status='hidden')},
        }
        settings = {'site_title': 'Kiosk', 'interface_language': 'en'}
        expected = legacy_mapping.public_bytes(objects, settings, 9)
        self.assertEqual(events.public_bytes(objects, settings, 9), expected)
        self.assertEqual(hashlib.sha256(expected).hexdigest(),
                         'ce7f8792055fafa63bc00088a11fdb08be0420dd0a27e165eaf0927ecdd4dda7')
        self.assertEqual(events.derive(objects, settings, 9), legacy_mapping.derive(objects, settings, 9))

    def test_legacy_mapping_image_variants_are_unchanged(self):
        self.assertEqual(legacy_mapping._images([]), (None, None, None))
        self.assertEqual(legacy_mapping._images(['a']), ('a', 'a', 'a'))
        self.assertEqual(legacy_mapping._images(['a', 'b']), ('a', 'b', 'a'))
        self.assertEqual(legacy_mapping._images(['a', 'b', 'c']), ('a', 'b', 'c'))


class PayloadTests(unittest.TestCase):
    def assert_code(self, value, code, status=400):
        with self.assertRaises(event_payload.PayloadError) as caught:
            event_payload.validate_payload(value)
        self.assertEqual((caught.exception.code, caught.exception.status), (code, status))

    def test_valid_payload_and_existing_workspace_error_contract(self):
        value = event(images=('/static/uploads/a.jpg', None, None), tags=('Alpha',))
        self.assertIs(event_payload.validate_payload(value), value)
        with self.assertRaises(WorkspaceError) as caught:
            event_payload.validate_payload(dict(value, sort_order=True), WorkspaceError)
        self.assertEqual((caught.exception.code, caught.exception.status), ('invalid_event_order', 400))

    def test_payload_error_codes_and_statuses_are_preserved(self):
        valid = event()
        self.assert_code([], 'draft_limit', 413)
        self.assert_code(dict(valid, extra=True), 'invalid_event_fields')
        self.assert_code(dict(valid, title='   '), 'invalid_event')
        self.assert_code(dict(valid, event_date=1), 'invalid_event_text')
        self.assert_code(dict(valid, sort_order=True), 'invalid_event_order')
        self.assert_code(dict(valid, images=['relative.jpg']), 'invalid_event_references')
        self.assert_code(dict(valid, tags=['Alpha', 'Alpha']), 'invalid_event_references')


class SeedTests(EventsFixture):
    def test_fixture_preserves_data_tags_and_all_image_variants(self):
        public_before = json.loads((self.package / 'data/events.json').read_text(encoding='utf-8'))
        package_before = self.package_files()
        source_before = self.database.read_bytes()
        result = self.seed()
        self.assertEqual(result, dict(package=self.identity, objects=2, content_version=11,
                                      activated=False))
        objects = self.rows('SELECT id,payload FROM objects ORDER BY id')
        payloads = {identity: decode(payload) for identity, payload in objects}
        self.assertEqual(payloads['1']['images'], ['/static/uploads/kiosk.jpg', '/static/uploads/tv.jpg',
                                                   '/static/uploads/thumb.jpg'])
        self.assertEqual(payloads['1']['tags'], ['Alpha', 'Beta'])
        self.assertEqual(payloads['2']['images'], [])
        self.assertIsNone(payloads['2']['event_date'])
        settings = decode(self.rows('SELECT body FROM settings')[0][0])
        snapshot = {identity: dict(version=1, payload=value) for identity, value in payloads.items()}
        self.assertEqual(events.derive(snapshot, settings, 11), public_before)
        self.assertEqual(self.package_files(), package_before)
        self.assertEqual(self.database.read_bytes(), source_before)

    def test_exact_replay_is_idempotent_and_does_not_rewrite_rows(self):
        first = self.seed()
        state = self.state()
        package = self.package_files()
        workspace_file = self.workspace.path.read_bytes()
        with self.workspace.db() as db:
            count = db.execute('SELECT COUNT(*) FROM revisions').fetchone()[0]
        second = self.seed()
        self.assertEqual(second, first)
        self.assertEqual(self.state(), state)
        self.assertEqual(self.package_files(), package)
        self.assertEqual(self.workspace.path.read_bytes(), workspace_file)
        with self.workspace.db() as db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM revisions').fetchone()[0], count)

    def test_modified_workspace_is_refused_without_changes(self):
        self.seed()
        with self.workspace.db() as db:
            db.execute('UPDATE sequence SET content=12')
        state = self.state()
        with self.assertRaisesRegex(WorkspaceError, 'baseline_workspace_not_empty'):
            self.seed()
        self.assertEqual(self.state(), state)

    def test_wrong_and_corrupt_packages_are_refused_without_changes(self):
        self.seed()
        state = self.state()
        other, other_identity = self.second_package()
        with self.assertRaisesRegex(WorkspaceError, 'baseline_workspace_not_empty'):
            seed(self.workspace, other, other_identity, confirm_disposable=True)
        with self.assertRaisesRegex(WorkspaceError, 'baseline_package_refused'):
            seed(self.workspace, self.package, '0' * 64, confirm_disposable=True)
        corrupt = self.root / 'corrupt-package'
        shutil.copytree(self.package, corrupt)
        (corrupt / 'data/events.json').write_text('{}', encoding='utf-8')
        with self.assertRaises(PackageError):
            seed(self.workspace, corrupt, self.identity, confirm_disposable=True)
        with self.assertRaisesRegex(WorkspaceError, 'disposable_confirmation_required'):
            seed(self.workspace, self.package, self.identity)
        self.assertEqual(self.state(), state)


if __name__ == '__main__':
    unittest.main()
