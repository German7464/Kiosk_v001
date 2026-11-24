import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from kiosk.publication import pages
from kiosk.publication.workspace import Workspace, WorkspaceError


def object_id(kind, value=1):
    return f'{kind}-{value:032x}'


class PageWorkspaceTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.store = Workspace(Path(directory.name) / 'workspace.sqlite', b'fixture-only',
                               'group', 'https://kiosk.example', stage6_pages=True)
        self.sessions = {
            'alice': dict(role='user', user_id='alice'),
            'bob': dict(role='user', user_id='bob'),
            'admin': dict(role='administrator', user_id='admin'),
            'publish-only': dict(role='user', user_id='publisher',
                                 scope=dict(permissions=['publish'], targets=['screen-1'])),
        }
        # Only the identity issuance is replaced. Persistence, permissions
        # and all draft version checks run through the actual workspace.
        auth = patch.object(self.store, '_session',
                            side_effect=lambda db, user: (self.sessions[user], None))
        auth.start()
        self.addCleanup(auth.stop)
        self.dataset = object_id('dataset')
        self.block = object_id('block')
        self.layout = object_id('layout')
        self.page = object_id('page')
        self.target = 'tv-landscape'
        self.layout_body = dict(schema=1, target=self.target, columns=4, rows=3,
                                placements=[dict(block=self.block, x=0, y=0, w=2, h=3)])
        self.page_body = dict(schema=1, name='Notice board', order=0,
                              layouts={self.target: self.layout}, fallback=self.target)

    def draft(self, identity, payload, dependencies, author='alice', version=0, ready=True):
        saved = self.store.save_page(author, identity, version, payload, dependencies)
        if ready:
            self.store.ready_page(author, identity, saved)
        return saved

    def seed(self):
        self.draft(self.dataset, dict(schema=1, name='Events', module='events', events=[]), {})
        self.draft(self.block, dict(schema=1, name='Cards', dataset=self.dataset, tags=[],
                                    limit=3, appearance='cards'), {self.dataset: 1})
        self.draft(self.layout, self.layout_body, {self.block: 1})
        self.draft(self.page, self.page_body, {self.layout: 1})

    def test_shared_dataset_independent_settings_and_verified_grid_fallback(self):
        self.seed()
        second = object_id('block', 2)
        self.draft(second, dict(schema=1, name='Only featured', dataset=self.dataset,
                              tags=['featured'], limit=1, appearance='list'), {self.dataset: 1})
        layout = dict(self.layout_body, placements=[
            *self.layout_body['placements'], dict(block=second, x=2, y=0, w=2, h=3)])
        self.draft(self.layout, layout, {self.block: 1, second: 1}, version=1)
        fallback = pages.layout_for(self.page_body, {self.layout: layout}, 'kiosk-portrait')
        self.assertEqual(pages.validate(self.layout, fallback), [self.block, second])
        self.assertEqual([item['y'] for item in fallback['placements']], [0, 1])
        current = {row['id']: row for row in self.store.page_objects('alice')}
        self.assertEqual(current[self.block]['payload']['limit'], 3)
        self.assertEqual(current[second]['payload']['limit'], 1)
        self.assertEqual(current[second]['dependencies'], {self.dataset: 1})
        self.assertFalse(current[self.page]['ready'])

    def test_concurrent_draft_versions_and_transitive_dependency_invalidation(self):
        self.seed()
        self.draft(self.page, dict(self.page_body, name='Alice saved'), {self.layout: 1},
                   version=1)
        unsaved = dict(self.page_body, name='Bob unsaved input')
        with self.assertRaisesRegex(WorkspaceError, 'draft_version_conflict'):
            self.draft(self.page, unsaved, {self.layout: 1}, author='bob', version=1)
        self.assertEqual(unsaved['name'], 'Bob unsaved input')
        self.draft(self.dataset, dict(schema=1, name='Events revised', module='events', events=[]),
                   {}, version=1, ready=False)
        other = object_id('dataset', 2)
        self.draft(other, dict(schema=1, name='Independent', module='events', events=[]), {})
        plan = self.store.page_plan('bob')
        self.assertEqual(plan['included'], [dict(id=other, version=1, author='alice')])
        self.assertEqual({item['id'] for item in plan['excluded']},
                         {self.dataset, self.block, self.layout, self.page})
        with self.assertRaisesRegex(WorkspaceError, 'dependency_not_ready'):
            self.store.ready_page('bob', self.page, 2)
        current = {row['id']: row for row in self.store.page_objects('bob')}
        self.assertEqual(current[self.page]['payload']['name'], 'Alice saved')
        self.assertEqual(current[self.page]['published_version'], 0)

    def test_overlap_mismatched_layout_target_and_assignment_authority(self):
        self.seed()
        extra = dict(block=object_id('block', 2), x=1, y=0, w=2, h=1)
        overlapping = dict(self.layout_body, placements=[*self.layout_body['placements'], extra])
        with self.assertRaisesRegex(WorkspaceError, 'layout_overlap'):
            self.draft(self.layout, overlapping, {}, version=1)
        invalid_page = dict(self.page_body, layouts={'tv-portrait': self.layout},
                            fallback='tv-portrait')
        self.draft(self.page, invalid_page, {self.layout: 1}, version=1, ready=False)
        with self.assertRaisesRegex(WorkspaceError, 'incompatible_layout_target'):
            self.store.ready_page('alice', self.page, 2)
        profile = object_id('profile')
        body = dict(schema=1, name='Shared', selection=dict(
            pages=[self.page], start_page=self.page, transition_seconds=15))
        with self.assertRaisesRegex(WorkspaceError, 'administrator_required'):
            self.draft(profile, body, {self.page: 2})
        self.draft(profile, body, {self.page: 2}, author='admin', ready=False)
        with self.assertRaisesRegex(WorkspaceError, 'edit_permission_required'):
            self.draft(self.page, self.page_body, {self.layout: 1}, author='publish-only', version=2)

    def test_published_dependants_keep_old_pins_and_legacy_plan_cannot_publish_pages(self):
        self.seed()
        with self.store.db() as db:
            db.execute('UPDATE objects SET published_version=version')
        self.draft(self.dataset, dict(schema=1, name='Changed', module='events', events=[]),
                   {}, version=1)
        plan = self.store.page_plan('alice')
        self.assertEqual(plan['included'], [])
        self.assertEqual(plan['excluded'], [
            dict(id=self.dataset, version=2, author='alice', reason='published_dependant_pinned')])
        with self.assertRaisesRegex(WorkspaceError, 'page_publication_required'):
            self.store.freeze('alice', {self.dataset: 2})

    def test_target_projection_shared_profile_and_stale_plan_refusal(self):
        self.seed()
        profile = object_id('profile')
        selection = dict(pages=[self.page], start_page=self.page, transition_seconds=15)
        self.draft(profile, dict(schema=1, name='Shared', selection=selection),
                   {self.page: 1}, author='admin')
        self.draft(object_id('assignment'), dict(schema=1, device='screen-1',
                                               profile=profile, selection=None),
                   {profile: 1}, author='admin')
        self.draft(object_id('assignment', 2), dict(schema=1, device='screen-2',
                                                  profile=None, selection=selection),
                   {self.page: 1}, author='admin')
        unrelated = object_id('dataset', 2)
        self.draft(unrelated, dict(schema=1, name='Unrelated', module='events', events=[]), {})
        revision = self.store.page_plan('alice')['revision_sha256']
        first = self.store.page_target_preview('alice', 'screen-1', 'kiosk-portrait', revision)
        second = self.store.page_target_preview('alice', 'screen-2', 'kiosk-portrait', revision)
        self.assertEqual(first, second)
        self.assertEqual(set(first['page']['datasets']), {self.dataset})
        self.assertEqual(first['page']['pages'][0]['columns'], 1)
        with self.assertRaisesRegex(WorkspaceError, 'publisher_scope_refused'):
            self.store.page_target_preview('publish-only', 'screen-2', 'kiosk-portrait', revision)
        self.draft(unrelated, dict(schema=1, name='New unrelated draft', module='events', events=[]),
                   {}, version=1)
        with self.assertRaisesRegex(WorkspaceError, 'prepared_snapshot_changed'):
            self.store.page_target_preview('alice', 'screen-1', 'kiosk-portrait', revision)

    def test_manual_disable_and_fault_preserve_published_rows_and_allow_page_drafts(self):
        self.seed()
        with self.store.db() as db:
            db.execute('UPDATE objects SET published_version=version')
        self.assertEqual(self.store.dataset_dependants('alice', self.dataset), dict(
            working=[self.block], published=[self.block], deletion='stage7_recycle_bin_required'))
        with self.assertRaisesRegex(WorkspaceError, 'administrator_required'):
            self.store.set_events_enabled('alice', 0, False)
        self.assertEqual(self.store.set_events_enabled('admin', 0, False)['state'], 'disabled')
        self.assertEqual(self.store.module_status('alice')['state'], 'disabled')
        with self.assertRaisesRegex(WorkspaceError, 'events_module_unavailable'):
            self.draft(self.dataset, dict(schema=1, name='Changed', module='events', events=[]),
                       {}, version=1)
        page = self.draft(self.page, dict(self.page_body, name='Page changed'), {self.layout: 1},
                          version=1)
        self.assertEqual(page, 2)
        self.assertEqual(self.store.module_status('admin')['state'], 'disabled')
        self.assertEqual(self.store.set_events_enabled('admin', 1, True)['state'], 'ready')
        with patch('kiosk.features.events.health', side_effect=RuntimeError('fixture fault')):
            self.assertEqual(self.store.module_status('alice')['state'], 'faulted')
            plan = self.store.page_plan('alice')
            self.assertEqual(plan['included'], [dict(id=self.page, version=2, author='alice')])
        current = {row['id']: row for row in self.store.page_objects('alice')}
        self.assertEqual(current[self.dataset]['published_version'], 1)
        self.assertEqual(current[self.block]['dependencies'], {self.dataset: 1})

    def test_fenced_content_refuses_draft_and_module_writes(self):
        self.seed()
        self.store.configure_placement('separated', 'https://maintenance.example', active=False)
        with self.assertRaisesRegex(WorkspaceError, 'service_fenced'):
            self.draft(self.page, dict(self.page_body, name='Refused'), {self.layout: 1}, version=1)
        with self.assertRaisesRegex(WorkspaceError, 'service_fenced'):
            self.store.set_events_enabled('admin', 0, False)
        self.assertEqual(self.store.module_status('alice')['state'], 'ready')
        page = next(item for item in self.store.page_objects('bob') if item['id'] == self.page)
        self.assertEqual(page['version'], 1)


if __name__ == '__main__':
    unittest.main()
