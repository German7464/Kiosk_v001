"""Exact frozen-draft -> package mapping and signed distribution (source fixtures)."""
import base64
import copy
import json
import tempfile
import unittest
from pathlib import Path

from kiosk.delivery.protocol import PROFILE, decode, encode, sha
from kiosk.delivery.publication import publish
from kiosk.delivery.state import DeliveryState
from kiosk.publication import authority as a
from kiosk.publication import mapping
from kiosk.publication.exporter import PackageError, export_events_package, verify_package
from kiosk.publication.publisher import LocalPublisher
from kiosk.publication.workspace import Workspace, WorkspaceError
from kiosk.trust.crypto import generate_private_key, key_id, spki_der


def event(title='Event', sort_order=0, images=(), tags=(), status='active'):
    return dict(title=title, short_description='S', full_description='F', event_date='2026-11-16',
                place='Hall', sort_order=sort_order, status=status, images=list(images), tags=list(tags))


class MappingTests(unittest.TestCase):
    def objects(self):
        return {'2': dict(version=1, payload=event('Second', 2, ['/static/uploads/b.jpg'], ['Zeta'])),
                '1': dict(version=1, payload=event('First', 1, ['/static/uploads/a.jpg', '/static/uploads/b.jpg'], ['Alpha', 'Zeta'])),
                '3': dict(version=1, payload=event('Hidden', 0, [], [], 'hidden'))}

    def test_deterministic_public_mapping(self):
        first = mapping.derive(self.objects(), {'site_title': 'Kiosk'}, 7)
        self.assertEqual(first, mapping.derive(self.objects(), {'site_title': 'Kiosk'}, 7))
        self.assertEqual([item['id'] for item in first['events']], [1, 2])
        self.assertEqual(first['tags'], [{'id': 1, 'name': 'Alpha'}, {'id': 2, 'name': 'Zeta'}])
        self.assertEqual(first['events'][0]['tag_ids'], [1, 2])
        self.assertEqual(first['events'][0]['image_kiosk'], '/static/uploads/a.jpg')
        self.assertEqual(first['events'][0]['image_tv'], '/static/uploads/b.jpg')
        self.assertEqual(first['events'][0]['image_thumb'], '/static/uploads/a.jpg')
        self.assertEqual(first['content_version'], 7)

    def test_mapping_refuses_identity_media_and_substitution(self):
        objects = self.objects()
        for identity in ('01', 'x', '0', '2147483648', ''):
            changed = {'1': objects['1']}
            changed[identity] = objects['2']
            with self.assertRaises(mapping.MappingError):
                mapping.derive(changed, {}, 1)
        for images in (['/static/uploads/../x.jpg'], ['relative.jpg'], ['\\x']):
            changed = copy.deepcopy(objects)
            changed['1']['payload']['images'] = images
            with self.assertRaises(mapping.MappingError):
                mapping.derive(changed, {}, 1)
        data = mapping.derive(objects, {}, 3)
        substituted = copy.deepcopy(data)
        substituted['events'][0]['title'] = 'Changed'
        with self.assertRaises(mapping.MappingError):
            mapping.verify(substituted, objects, {}, 3)


class WorkspaceMappingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.root, cls.key = generate_private_key(), generate_private_key()

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.folder = Path(self.tmp.name)
        self.now = 2_000_000_000
        self.origin = 'https://kiosk.example:20443'
        self.store = Workspace(self.folder / 'workspace.sqlite', spki_der(self.root), 'group',
                               self.origin, clock=lambda: self.now)
        self.policy = dict(group_id='group', origin=self.origin, version=1, issued=self.now - 100,
                           expires=self.now + 86400, revoked_devices=[], revoked_users=[])
        self.store.install_policy(a.signed(self.root, 'policy', self.policy))
        self.grant = dict(group_id='group', origin=self.origin, user_id='alice', role='administrator',
                          issued=self.now - 100, expires=self.now + 86400, can_delegate=True,
                          device_key=base64.b64encode(spki_der(self.key)).decode())
        self.chain = [a.signed(self.root, 'device', self.grant)]
        browser = 'b' * 64
        token, document = self.store.create_login(browser, 'Chrome')
        self.store.accept_login(token, a.signed(self.key, 'login', document), self.chain)
        self.secret = self.store.consume_login(token, browser)[0]
        self.uploads = self.folder / 'uploads'
        self.uploads.mkdir()
        self.resources = Path('kiosk')

    def delivery(self):
        state = DeliveryState(self.folder / 'delivery', clock=lambda: self.now)
        config = dict(version=1, group_id='group', server_id='server', origin=self.origin,
                      bootstrap={}, trust={})
        (state.root / 'public.json').write_bytes(encode(config))
        from kiosk.display.cache import renderer_identity
        capabilities = dict(version=1, platform='windows', modes=['tv'], content=['events'],
                            resource_profile=PROFILE, renderer=renderer_identity())
        with state.connection() as db:
            db.execute("INSERT OR REPLACE INTO display_profiles VALUES ('events-tv','Events TV','tv',3)")
            db.execute("INSERT OR REPLACE INTO device_profiles VALUES ('display1','events-tv')")
            db.execute("INSERT OR REPLACE INTO device_capabilities VALUES ('display1',?)",
                       (encode(capabilities),))
            db.execute('INSERT OR REPLACE INTO devices VALUES (?,?,?,?,?,0)',
                       ('display1', PROFILE, 'c' * 64, 'v' * 64, self.now + 86400))
        return state

    def ready_draft(self, title='Event'):
        self.store.save(self.secret, '1', 0, event(title), {})
        self.store.ready(self.secret, '1', 1)

    def test_stage_freeze_is_single_use_and_binds_exact_package(self):
        state = self.delivery()
        self.store.update_settings(self.secret, 0, {'site_title': 'Museum'})
        self.ready_draft()
        frozen = self.store.freeze(self.secret, {'1': 1})
        data = mapping.derive(frozen['objects'], frozen['settings'], frozen['content_version'])
        package = self.folder / 'package'
        export_events_package(None, self.uploads, self.resources, package, data=data)
        metadata = publish(state, package)
        self.assertEqual(decode((package / 'data/events.json').read_bytes())['settings']['site_title'], 'Museum')
        targets = state.publisher_targets(metadata['renderer']['build_id'])
        document = self.store.prepare(self.secret, {'1': 1}, metadata, targets, [], stage=frozen['stage'])
        self.assertEqual(document['content_version'], 1)
        self.assertEqual(mapping.derive(document['objects'], document['settings'], 1)['events'][0]['title'], 'Event')
        with self.assertRaises(WorkspaceError):
            self.store.prepare(self.secret, {'1': 1}, metadata, targets, [], stage=frozen['stage'])

    def test_substituted_package_is_refused_before_plan_freeze(self):
        state = self.delivery()
        self.ready_draft()
        frozen = self.store.freeze(self.secret, {'1': 1})
        wrong = mapping.derive(frozen['objects'], frozen['settings'], frozen['content_version'])
        wrong['events'][0]['title'] = 'Substituted'
        package = self.folder / 'package'
        export_events_package(None, self.uploads, self.resources, package, data=wrong)
        metadata = publish(state, package)
        targets = state.publisher_targets(metadata['renderer']['build_id'])
        with self.assertRaisesRegex(WorkspaceError, 'plan_content_mapping'):
            self.store.prepare(self.secret, {'1': 1}, metadata, targets, [], stage=frozen['stage'])
        # The failed review keeps its unguessable stage until expiry; nothing was signed.
        self.assertEqual(self.store.staged(frozen['stage'])['content_version'],
                         frozen['content_version'])

    def test_approved_plan_promotes_signed_assignment_for_exact_target(self):
        from kiosk.publication.distribution import promote
        from kiosk.publication.materialize import prepare_publication
        state = self.delivery()
        self.ready_draft()
        targets = state.publisher_targets()
        document = prepare_publication(self.store, self.secret, {'1': 1}, targets, [], state,
                                       self.uploads, self.resources)
        plan = document['plan']
        self.store.approve(plan['id'], a.signed(self.key, 'publication', plan), self.chain)
        result = promote(self.store, state, plan['id'], self.now)
        assignment = state.assignment({'device_id': 'display1', 'profile': PROFILE},
                                      document['publication']['renderer']['build_id'],
                                      PROFILE, 'display-profile-v1')
        self.assertEqual(assignment['version'], 3)
        self.assertEqual(assignment['generation'], result['generation'])
        verified, policy = a.assignment(assignment['publisher'], assignment, spki_der(self.root),
                                        self.origin, self.now)
        self.assertEqual(verified['id'], plan['id'])
        canonical = mapping.derive(document['objects'], document['settings'], document['content_version'])
        self.assertEqual(sha(encode(canonical)),
                         next(item['sha256'] for item in document['publication']['package']['files']
                              if item['path'] == 'data/events.json'))
        # An unsigned client cannot receive an approved roaming publication.
        with self.assertRaises(Exception):
            state.assignment({'device_id': 'display1', 'profile': PROFILE},
                             document['publication']['renderer']['build_id'], PROFILE)
        # A newly enrolled display outside the signed target set is refused, not
        # served broader unsigned content.
        with state.connection() as db:
            db.execute('INSERT OR REPLACE INTO devices VALUES (?,?,?,?,?,0)',
                       ('display2', PROFILE, 'd' * 64, 'w' * 64, self.now + 86400))
        with self.assertRaisesRegex(Exception, 'publisher_target_not_approved'):
            state.assignment({'device_id': 'display2', 'profile': PROFILE},
                             document['publication']['renderer']['build_id'], PROFILE,
                             'display-profile-v1')

    def test_target_mismatch_and_revoked_display_refuse_distribution(self):
        from kiosk.publication.distribution import promote
        from kiosk.publication.materialize import prepare_publication
        state = self.delivery()
        self.ready_draft()
        targets = state.publisher_targets()
        changed = copy.deepcopy(targets)
        changed[0]['configuration_sha256'] = '0' * 64
        document = prepare_publication(self.store, self.secret, {'1': 1}, changed, [], state,
                                       self.uploads, self.resources)
        self.store.approve(document['plan']['id'],
                           a.signed(self.key, 'publication', document['plan']), self.chain)
        with self.assertRaises(Exception):
            promote(self.store, state, document['plan']['id'], self.now)

    def test_failed_promotion_leaves_assignment_history_and_proofs_unchanged(self):
        from kiosk.delivery.protocol import DeliveryError
        from kiosk.publication.distribution import promote
        from kiosk.publication.materialize import prepare_publication
        state = self.delivery()
        self.ready_draft()
        targets = state.publisher_targets()
        first = prepare_publication(self.store, self.secret, {'1': 1}, targets, [], state,
                                    self.uploads, self.resources)
        self.store.approve(first['plan']['id'],
                           a.signed(self.key, 'publication', first['plan']), self.chain)
        generation = promote(self.store, state, first['plan']['id'], self.now)['generation']
        with state.connection(write=False) as db:
            baseline = {table: [tuple(row) for row in db.execute('SELECT * FROM ' + table)]
                        for table in ('assignments', 'assignment_history', 'assignment_cohorts',
                                      'assignment_targets', 'publisher_proofs',
                                      'publication_config_sets', 'publication_configs')}
        wrong = copy.deepcopy(targets)
        wrong[0]['mode'] = 'kiosk'
        second = prepare_publication(self.store, self.secret, {'1': 1}, wrong, [], state,
                                     self.uploads, self.resources)
        self.store.approve(second['plan']['id'],
                           a.signed(self.key, 'publication', second['plan']), self.chain)
        with self.assertRaises(DeliveryError):
            promote(self.store, state, second['plan']['id'], self.now)
        with state.connection(write=False) as db:
            after = {table: [tuple(row) for row in db.execute('SELECT * FROM ' + table)]
                     for table in baseline}
        self.assertEqual(after, baseline)
        assignment = state.assignment({'device_id': 'display1', 'profile': PROFILE},
                                      first['publication']['renderer']['build_id'],
                                      PROFILE, 'display-profile-v1')
        self.assertEqual(assignment['generation'], generation)
        self.assertEqual(assignment['metadata_sha256'], first['plan']['publication_sha256'])

    def test_interrupted_promotion_rolls_back_assignment_and_proofs(self):
        from unittest.mock import patch
        from kiosk.delivery.state import DeliveryState
        from kiosk.publication.distribution import promote
        from kiosk.publication.materialize import prepare_publication
        state = self.delivery()
        self.ready_draft()
        document = prepare_publication(self.store, self.secret, {'1': 1},
                                       state.publisher_targets(), [], state,
                                       self.uploads, self.resources)
        self.store.approve(document['plan']['id'],
                           a.signed(self.key, 'publication', document['plan']), self.chain)

        def interrupted(self, db, *args, **kwargs):
            db.execute("INSERT INTO assignments VALUES ('events-phone-lab-v1',1,?,?)",
                       ('a' * 64, 'b' * 64))
            raise RuntimeError('interrupted after partial write')

        with patch.object(DeliveryState, '_assign', interrupted):
            with self.assertRaises(RuntimeError):
                promote(self.store, state, document['plan']['id'], self.now)
        with state.connection(write=False) as db:
            for table in ('assignments', 'assignment_history', 'assignment_cohorts',
                          'assignment_targets', 'publisher_proofs', 'publication_config_sets'):
                self.assertEqual(db.execute('SELECT COUNT(*) FROM ' + table).fetchone()[0], 0,
                                 table)

    def test_concurrent_promotions_commit_one_coherent_distribution(self):
        import threading
        from kiosk.publication.distribution import promote
        from kiosk.publication.materialize import prepare_publication
        state = self.delivery()
        self.ready_draft()
        targets = state.publisher_targets()
        first = prepare_publication(self.store, self.secret, {'1': 1}, targets, [], state,
                                    self.uploads, self.resources)
        self.store.approve(first['plan']['id'],
                           a.signed(self.key, 'publication', first['plan']), self.chain)
        second = prepare_publication(self.store, self.secret, {'1': 1}, targets, [], state,
                                     self.uploads, self.resources)
        self.store.approve(second['plan']['id'],
                           a.signed(self.key, 'publication', second['plan']), self.chain)
        results, errors = [], []

        def run(plan):
            try:
                results.append(promote(self.store, state, plan, self.now))
            except Exception as error:  # a locked writer must not corrupt state
                errors.append(error)

        threads = [threading.Thread(target=run, args=(plan['plan']['id'],))
                   for plan in (first, second)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        assignment = state.assignment({'device_id': 'display1', 'profile': PROFILE},
                                      second['publication']['renderer']['build_id'],
                                      PROFILE, 'display-profile-v1')
        proof = assignment['publisher']
        verified, _ = a.assignment(proof, assignment, spki_der(self.root), self.origin, self.now)
        self.assertIn(verified['publication_sha256'],
                      {first['plan']['publication_sha256'], second['plan']['publication_sha256']})
        with state.connection(write=False) as db:
            rows = [tuple(row) for row in db.execute('SELECT generation FROM assignments')]
            self.assertEqual(len(rows), 1)
            generation = rows[0][0]
            proofs = db.execute('SELECT device_id FROM publisher_proofs WHERE generation=?',
                                (generation,)).fetchall()
            self.assertEqual([row[0] for row in proofs], ['display1'])
            targets_now = db.execute('SELECT device_id FROM assignment_targets WHERE generation=?',
                                     (generation,)).fetchall()
            self.assertEqual([row[0] for row in targets_now], ['display1'])

    def test_second_publication_references_every_approved_head(self):
        from kiosk.publication.materialize import prepare_publication
        state = self.delivery()
        self.ready_draft()
        targets = state.publisher_targets()
        first = prepare_publication(self.store, self.secret, {'1': 1}, targets, [], state,
                                    self.uploads, self.resources)
        self.store.approve(first['plan']['id'],
                           a.signed(self.key, 'publication', first['plan']), self.chain)
        second = prepare_publication(self.store, self.secret, {'1': 1}, targets, [], state,
                                     self.uploads, self.resources)
        self.assertEqual(second['plan']['parents'], [first['plan']['id']])
        self.assertIn(first['plan']['id'], {node['id'] for node in second['ancestry']})
        a.check_ancestry(second['plan'], [first['plan']['id']], second['ancestry'])

    def test_publisher_review_refuses_substituted_mapping(self):
        from kiosk.publication.materialize import prepare_publication
        from kiosk.publication.publisher import verify_mapping
        state = self.delivery()
        self.ready_draft()
        document = prepare_publication(self.store, self.secret, {'1': 1},
                                       state.publisher_targets(), [], state, self.uploads, self.resources)
        captured = self.folder / 'captured'
        (captured / 'package').mkdir(parents=True)
        source = state.root / 'publications' / document['publication']['package_id'] / 'package'
        for path in source.rglob('*'):
            if path.is_file():
                target = captured / 'package' / path.relative_to(source)
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(path.read_bytes())
        self.assertEqual(verify_mapping(document, captured)['content_version'],
                         document['content_version'])
        tampered = decode(encode(document))
        tampered['objects']['1']['payload']['title'] = 'Substituted'
        with self.assertRaisesRegex(ValueError, 'publisher_review_snapshot_substitution'):
            verify_mapping(tampered, captured)
        changed = decode((captured / 'package/data/events.json').read_bytes())
        changed['events'][0]['title'] = 'Substituted'
        (captured / 'package/data/events.json').write_bytes(encode(changed))
        with self.assertRaisesRegex(ValueError, 'publisher_review_snapshot_substitution'):
            verify_mapping(document, captured)


if __name__ == '__main__':
    unittest.main()
