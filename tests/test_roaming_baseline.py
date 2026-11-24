import copy
import json
import unittest

from kiosk.delivery.protocol import encode, sha
from kiosk.publication.baseline import seed
from kiosk.publication.exporter import verify_package, PackageError
from kiosk.publication.mapping import derive
from kiosk.publication.workspace import WorkspaceError
from tests.test_publication_export import ExportTests
from tests.test_roaming_workspace import WorkspaceTests


class BaselineTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        WorkspaceTests.setUpClass()

    def setUp(self):
        self.export = ExportTests('test_complete_export_excludes_secrets')
        self.export.setUp()
        self.addCleanup(self.export.doCleanups)
        self.export.export()
        self.fixture = WorkspaceTests('test_login_replay_session_binding_and_fixation')
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.store = self.fixture.store
        self.manifest = verify_package(self.export.destination)
        self.identity = sha(encode(self.manifest))

    def seed(self):
        return seed(self.store, self.export.destination, self.identity, confirm_disposable=True)

    def test_preserves_existing_package_and_nullable_event_images_then_versions_draft(self):
        before = {p.relative_to(self.export.destination).as_posix(): p.read_bytes()
                  for p in self.export.destination.rglob('*') if p.is_file()}
        source = self.export.db.read_bytes()
        result = self.seed()
        self.assertFalse(result['activated'])
        rows = self.store.objects(self.fixture.secret)
        self.assertEqual(len(rows), 1)
        self.assertEqual((rows[0]['version'], rows[0]['published_version']), (1, 1))
        old = json.loads(before['data/events.json'])
        snapshot = {r['id']: r for r in rows}
        self.assertEqual(derive(snapshot, old['settings'], 7), old)
        changed = copy.deepcopy(rows[0]['payload']); changed['title'] = 'Distinct draft'
        self.assertEqual(self.store.save(self.fixture.secret, '1', 1, changed, {}), 2)
        self.assertEqual(self.store.objects(self.fixture.secret)[0]['published_version'], 1)
        self.assertEqual(before, {p.relative_to(self.export.destination).as_posix(): p.read_bytes()
                                 for p in self.export.destination.rglob('*') if p.is_file()})
        self.assertEqual(self.export.db.read_bytes(), source)
        self.assertEqual(verify_package(self.export.destination), self.manifest)
        with self.assertRaisesRegex(WorkspaceError, 'not_empty'):
            self.seed()

    def test_confirmation_identity_and_tamper_refused_without_partial_rows(self):
        with self.assertRaises(WorkspaceError):
            seed(self.store, self.export.destination, self.identity)
        with self.assertRaises(WorkspaceError):
            seed(self.store, self.export.destination, '0' * 64, confirm_disposable=True)
        (self.export.destination / 'data/events.json').write_text('{}')
        with self.assertRaises(PackageError):
            self.seed()
        with self.store.db() as db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM objects').fetchone()[0], 0)
