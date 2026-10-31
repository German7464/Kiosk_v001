from contextlib import contextmanager, closing
import hashlib
import json
from pathlib import Path
import shutil
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from PIL import Image

from kiosk.publication.exporter import PackageError, export_events_package, verify_package


@contextmanager
def connection(path):
    with closing(sqlite3.connect(path)) as db:
        with db:
            yield db


class ExportTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.db = self.root / 'source.sqlite'
        self.uploads = self.root / 'uploads'
        self.uploads.mkdir()
        Image.new('RGB', (4, 4), 'red').save(self.uploads / 'card.jpg')
        self.resources = Path('kiosk').resolve()
        self.destination = self.root / 'package'
        with connection(self.db) as db:
            db.executescript('''
                CREATE TABLE events (id INTEGER,title TEXT,short_description TEXT,full_description TEXT,event_date TEXT,place TEXT,image_kiosk TEXT,image_tv TEXT,image_thumb TEXT,sort_order INTEGER,status TEXT,image_original TEXT);
                CREATE TABLE tags (id INTEGER,name TEXT);
                CREATE TABLE event_tags (event_id INTEGER,tag_id INTEGER);
                CREATE TABLE settings (key TEXT,value TEXT);
                INSERT INTO events VALUES (1,'Card','','',NULL,'Hall','/static/uploads/card.jpg','/static/uploads/card.jpg',NULL,0,'active','PRIVATE-ORIGINAL');
                INSERT INTO events VALUES (2,'HIDDEN','','',NULL,'',NULL,NULL,NULL,0,'hidden','SECRET');
                INSERT INTO tags VALUES (1,'Tag');
                INSERT INTO event_tags VALUES (1,1);
                INSERT INTO settings VALUES ('content_version','7');
                INSERT INTO settings VALUES ('site_title','Synthetic');
                INSERT INTO settings VALUES ('password','SECRET-PASSWORD');
            ''')

    def export(self, destination=None):
        return export_events_package(self.db, self.uploads, self.resources, destination or self.destination)

    def test_complete_export_excludes_secrets(self):
        self.export()
        manifest = verify_package(self.destination)
        self.assertEqual(manifest['revision'], '7')
        content = (self.destination / 'data/events.json').read_text()
        self.assertNotIn('SECRET', content)
        self.assertNotIn('PRIVATE', content)
        self.assertNotIn('HIDDEN', content)
        self.assertEqual(len(json.loads(content)['events']), 1)
        self.assertTrue((self.destination / 'static/uploads/card.jpg').is_file())
        with self.assertRaisesRegex(PackageError, 'destination_exists'):
            self.export()

    def test_empty_public_events(self):
        with connection(self.db) as db:
            db.execute("UPDATE events SET status='hidden'")
        self.export()
        self.assertEqual(json.loads((self.destination / 'data/events.json').read_text())['events'], [])

    def test_missing_corrupt_and_unsafe_media_preserve_previous(self):
        self.export()
        previous = (self.destination / 'manifest.json').read_bytes()
        for value in ('/static/uploads/missing.jpg', '/static/uploads/../source.sqlite', 'https://example.invalid/image'):
            with connection(self.db) as db:
                db.execute('UPDATE events SET image_kiosk=? WHERE id=1', (value,))
            with self.subTest(value=value), self.assertRaises(PackageError):
                self.export(self.root / 'new')
            self.assertFalse((self.root / 'new').exists())
            self.assertEqual((self.destination / 'manifest.json').read_bytes(), previous)
        with connection(self.db) as db:
            db.execute("UPDATE events SET image_kiosk='/static/uploads/card.jpg' WHERE id=1")
        (self.uploads / 'card.jpg').write_bytes(b'not image')
        with self.assertRaisesRegex(PackageError, 'invalid_image'):
            self.export(self.root / 'new')

    def test_verifier_rejects_corruption_and_extra_file(self):
        self.export()
        path = self.destination / 'data/events.json'
        original = path.read_bytes()
        path.write_bytes(b'[]')
        with self.assertRaisesRegex(PackageError, 'integrity_failure'):
            verify_package(self.destination)
        path.write_bytes(original)
        (self.destination / 'extra.txt').write_text('extra')
        with self.assertRaisesRegex(PackageError, 'inventory_mismatch'):
            verify_package(self.destination)

    def test_changed_source_and_disk_failure(self):
        from kiosk.publication import exporter
        original = exporter._stream_stable
        calls = 0
        def changed(root, name, output=None):
            nonlocal calls
            result = original(root, name, output)
            if root == self.uploads:
                calls += 1
                if calls == 2:
                    return result[0], (*result[1][:3], '0' * 64)
            return result
        with patch.object(exporter, '_stream_stable', side_effect=changed):
            with self.assertRaisesRegex(PackageError, 'source_changed'):
                self.export()
        self.assertFalse(self.destination.exists())
        self.assertFalse(list(self.root.glob('.events-export-*')))
        with patch.object(Path, 'write_bytes', side_effect=OSError('synthetic disk full')):
            with self.assertRaisesRegex(PackageError, 'export_failed'):
                self.export()
        self.assertFalse(self.destination.exists())
        self.assertFalse(list(self.root.glob('.events-export-*')))

    def test_rename_failure_and_missing_resource(self):
        with patch.object(Path, 'rename', side_effect=PermissionError('synthetic')):
            with self.assertRaisesRegex(PackageError, 'export_failed'):
                self.export()
        self.assertFalse(self.destination.exists())
        self.assertFalse(list(self.root.glob('.events-export-*')))
        self.resources = self.root / 'missing-resources'
        with self.assertRaisesRegex(PackageError, 'export_failed'):
            self.export()

    def rewrite_data(self, change):
        path = self.destination / 'data/events.json'
        value = json.loads(path.read_text())
        change(value)
        payload = json.dumps(value).encode()
        path.write_bytes(payload)
        mpath = self.destination / 'manifest.json'
        manifest = json.loads(mpath.read_text())
        entry = next(e for e in manifest['files'] if e['path'] == 'data/events.json')
        entry.update(size=len(payload), sha256=hashlib.sha256(payload).hexdigest())
        mpath.write_text(json.dumps(manifest))

    def test_independent_public_data_validation(self):
        self.export()
        original = (self.destination / 'data/events.json').read_bytes()
        manifest = (self.destination / 'manifest.json').read_bytes()
        changes = (
            lambda d: d.update(content_version=99),
            lambda d: d['tags'][0].update(password='secret'),
            lambda d: d['events'][0].update(image_original='private'),
            lambda d: d['events'][0].update(tag_ids=[999]),
            lambda d: d['settings'].update(session_key='secret'),
        )
        for change in changes:
            self.rewrite_data(change)
            with self.assertRaises(PackageError):
                verify_package(self.destination)
            (self.destination / 'data/events.json').write_bytes(original)
            (self.destination / 'manifest.json').write_bytes(manifest)

    def test_aggregate_bound_before_reading_large_resource(self):
        from kiosk.publication import exporter
        with patch.object(exporter, 'MAX_PACKAGE_BYTES', 1024):
            with self.assertRaisesRegex(PackageError, 'package_too_large'):
                self.export()
        self.assertFalse(self.destination.exists())

    def test_deep_json_has_safe_diagnostics_and_preserves_previous(self):
        from contextlib import redirect_stdout
        import io
        from kiosk.publication import exporter
        from kiosk.publication.__main__ import main

        self.export()
        previous = {p.relative_to(self.destination): p.read_bytes()
                    for p in self.destination.rglob('*') if p.is_file()}
        malformed = self.root / 'malformed'
        malformed.mkdir()
        nested = '[' * 1200 + '0' + ']' * 1200
        (malformed / 'manifest.json').write_text(nested)
        output = io.StringIO()
        with patch('sys.argv', ['publication', 'verify', str(malformed)]), redirect_stdout(output):
            self.assertEqual(main(), 1)
        self.assertEqual(json.loads(output.getvalue()), {'result': 'error', 'code': 'invalid_package'})

        resources = self.root / 'resources'
        for name in exporter.RESOURCES:
            target = resources / name
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(self.resources / name, target)
        (resources / 'translations/en.json').write_text(nested)
        candidate = self.root / 'candidate'
        with self.assertRaisesRegex(PackageError, '^invalid_translation_resource$'):
            export_events_package(self.db, self.uploads, resources, candidate)
        self.assertFalse(candidate.exists())
        self.assertFalse(list(self.root.glob('.events-export-*')))
        self.assertEqual(previous, {p.relative_to(self.destination): p.read_bytes()
                                   for p in self.destination.rglob('*') if p.is_file()})

    def test_reparse_source_rejected(self):
        from kiosk.publication import exporter
        original = exporter._is_link
        with patch.object(exporter, '_is_link', side_effect=lambda info: original(info) or info.st_size == (self.uploads / 'card.jpg').stat().st_size):
            with self.assertRaises(PackageError):
                self.export()
        self.assertFalse(self.destination.exists())

    def test_snapshot_is_consistent_during_concurrent_commit(self):
        from kiosk.publication import exporter
        with connection(self.db) as writer:
            writer.execute('PRAGMA journal_mode=WAL')
        connect = sqlite3.connect
        changed = False
        def reader(*args, **kwargs):
            db = connect(*args, **kwargs)
            def trace(sql):
                nonlocal changed
                if sql.startswith('SELECT value') and not changed:
                    changed = True
                    with closing(connect(self.db)) as writer, writer:
                        writer.execute("UPDATE events SET title='Later' WHERE id=1")
                        writer.execute("UPDATE settings SET value='8' WHERE key='content_version'")
            db.set_trace_callback(trace)
            return db
        with patch.object(exporter.sqlite3, 'connect', side_effect=reader):
            snapshot = exporter._snapshot(self.db)
        self.assertTrue(changed)
        self.assertEqual(snapshot['content_version'], 7)
        self.assertEqual(snapshot['events'][0]['title'], 'Card')

    def test_cli_safe_diagnostics(self):
        import io
        from contextlib import redirect_stdout
        from kiosk.publication.__main__ import main
        self.export()
        output = io.StringIO()
        with patch('sys.argv', ['publication', 'verify', str(self.destination)]), redirect_stdout(output):
            self.assertEqual(main(), 0)
        self.assertEqual(json.loads(output.getvalue())['result'], 'verified')
        (self.destination / 'extra.txt').write_text('SYNTHETIC-PRIVATE')
        output = io.StringIO()
        with patch('sys.argv', ['publication', 'verify', str(self.destination)]), redirect_stdout(output):
            self.assertEqual(main(), 1)
        self.assertEqual(json.loads(output.getvalue()), {'result': 'error', 'code': 'inventory_mismatch'})
        self.assertNotIn(str(self.root), output.getvalue())
        self.assertNotIn('SYNTHETIC-PRIVATE', output.getvalue())

    def test_destination_inspection_and_cleanup_errors_are_safe(self):
        import io
        from contextlib import redirect_stdout
        from kiosk.publication.__main__ import main
        from kiosk.publication import exporter
        arguments = ['publication', 'export', '--database', str(self.db), '--uploads', str(self.uploads),
                     '--resources', str(self.resources), '--destination', str(self.destination)]
        cases = (
            patch.object(Path, 'is_dir', side_effect=PermissionError(str(self.root))),
            patch.object(exporter.shutil, 'rmtree', side_effect=PermissionError(str(self.root))),
        )
        for index, failure in enumerate(cases):
            output = io.StringIO()
            with self.subTest(index=index), patch('sys.argv', arguments), redirect_stdout(output), failure:
                if index == 1:
                    with patch.object(Path, 'rename', side_effect=PermissionError(str(self.root))):
                        self.assertEqual(main(), 1)
                else:
                    self.assertEqual(main(), 1)
            self.assertNotIn(str(self.root), output.getvalue())
            self.assertEqual(json.loads(output.getvalue())['code'],
                             'export_failed' if index == 0 else 'staging_cleanup_failed')
            self.assertFalse(self.destination.exists())

    def test_large_media_streaming_memory_and_integrity(self):
        import tracemalloc
        from kiosk.publication import exporter
        # JPEG trailing bytes are legal; allocate before measuring the pipeline.
        media = self.uploads / 'card.jpg'
        with media.open('ab') as output:
            for _ in range(48):
                output.write(b'x' * (256 * 1024))
        original = exporter._read_stable
        def metadata_only(root, name):
            if name.endswith('card.jpg'):
                self.fail('Media must not be buffered')
            return original(root, name)
        tracemalloc.start()
        try:
            with patch.object(exporter, '_read_stable', side_effect=metadata_only):
                self.export()
                verify_package(self.destination)
            _, peak = tracemalloc.get_traced_memory()
        finally:
            tracemalloc.stop()
        self.assertLess(peak, 8 * 1024 * 1024)
        self.assertEqual(media.stat().st_size, (self.destination / 'static/uploads/card.jpg').stat().st_size)
        with (self.destination / 'static/uploads/card.jpg').open('r+b') as output:
            output.seek(-1, 2)
            output.write(b'z')
        with self.assertRaisesRegex(PackageError, 'integrity_failure'):
            verify_package(self.destination)

    def test_stream_interruption_preserves_previous_and_cleans_staging(self):
        from kiosk.publication import exporter
        self.export()
        previous = (self.destination / 'manifest.json').read_bytes()
        original = exporter._stream_stable
        for failure in (KeyboardInterrupt(), OSError('synthetic ENOSPC')):
            def interrupted(root, name, output=None):
                if root == self.uploads and output is not None:
                    output.write(b'partial')
                    raise failure
                return original(root, name, output)
            with self.subTest(failure=type(failure).__name__), patch.object(exporter, '_stream_stable', side_effect=interrupted):
                with self.assertRaises(KeyboardInterrupt if isinstance(failure, KeyboardInterrupt) else PackageError):
                    self.export(self.root / 'candidate')
            self.assertFalse((self.root / 'candidate').exists())
            self.assertFalse(list(self.root.glob('.events-export-*')))
            self.assertEqual((self.destination / 'manifest.json').read_bytes(), previous)

    def test_real_source_change_before_commit_is_rejected(self):
        from kiosk.publication import exporter
        verify = exporter.verify_package
        def mutate_after_verify(directory):
            result = verify(directory)
            with (self.uploads / 'card.jpg').open('ab') as output:
                output.write(b'changed')
            return result
        with patch.object(exporter, 'verify_package', side_effect=mutate_after_verify):
            with self.assertRaisesRegex(PackageError, 'source_changed'):
                self.export()
        self.assertFalse(self.destination.exists())
        self.assertFalse(list(self.root.glob('.events-export-*')))

    def test_client_runtime_rejects_before_payload_processing(self):
        from kiosk.publication import exporter
        from kiosk.publication.compatibility import ClientRuntime
        self.export()
        with patch.object(exporter, '_validate_data', side_effect=AssertionError('payload must not be processed')):
            with self.assertRaisesRegex(PackageError, '^unsupported_client_contract$'):
                verify_package(self.destination, runtime=ClientRuntime(frozenset()))
        self.assertEqual(verify_package(self.destination)['revision'], '7')

    def test_client_contract_requires_exact_version_types(self):
        self.export()
        path = self.destination / 'manifest.json'
        original = path.read_bytes()
        manifest = json.loads(original)
        for version in (True, 1.0, '1', None, 2, [], {}):
            with self.subTest(version=version):
                value = dict(manifest, resource_contract=version)
                path.write_text(json.dumps(value))
                with self.assertRaisesRegex(PackageError, '^unsupported_client_contract$'):
                    verify_package(self.destination)
        path.write_bytes(original)
        verify_package(self.destination)
