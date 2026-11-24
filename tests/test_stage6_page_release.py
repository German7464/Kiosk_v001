import copy
import unittest

from kiosk.delivery.protocol import LIMITS, PROFILE, decode, encode, sha
from kiosk.publication import authority as a
from kiosk.publication import page_release as r, validate_manifest
from kiosk.trust.crypto import generate_private_key, key_id, spki_der


def object_id(kind, number=1):
    return f'{kind}-{number:032x}'


class PageReleaseTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.root, cls.device, cls.attacker = [generate_private_key() for _ in range(3)]

    def setUp(self):
        self.now = 2_000_000_000
        self.group, self.origin = 'group', 'https://kiosk.example:20443'
        self.policy = dict(group_id=self.group, origin=self.origin, version=1,
                           issued=self.now - 100, expires=self.now + 86400,
                           revoked_devices=[], revoked_users=[])
        self.grant = dict(group_id=self.group, origin=self.origin, user_id='user1',
                          role='user', device_key=self._spki(self.device),
                          issued=self.now - 100, expires=self.now + 3600,
                          can_delegate=False)
        self.chain = [a.signed(self.root, 'device', self.grant)]
        self.policy_envelope = a.signed(self.root, 'policy', self.policy)
        self.authorization = dict(group_id=self.group, origin=self.origin, user_id='user1',
                                  device_id=key_id(self.device), policy_version=1,
                                  issued=self.now, expires=self.now + 600)
        self.revision = self._revision()
        self.windows = self._target('screen-windows', 'tv-landscape', 'windows-pages-v1',
                                    'a', 'tv')
        self.android = self._target('screen-android', 'kiosk-portrait', 'android-pages-v1',
                                    'b', 'kiosk')
        self.prepared = r.prepare_release(revision=self.revision,
                                          authorization=self.authorization,
                                          targets=[self.windows, self.android])
        self.document = self.prepared['document']
        self.proof = self._proof(self.document['plan'])

    @staticmethod
    def _spki(key):
        import base64
        return base64.b64encode(spki_der(key)).decode('ascii')

    def _revision(self):
        event, hidden, unseen, independent = '1001', '1002', '1003', '1004'
        dataset, block, layout, page = [object_id(name) for name in
                                        ('dataset', 'block', 'layout', 'page')]
        profile = object_id('profile')
        windows, android = object_id('assignment', 1), object_id('assignment', 2)
        objects = {
            event: dict(version=1, author='alice', dependencies={}, payload={
                'title': 'Notice', 'short_description': 'Short', 'full_description': 'Full',
                'event_date': None, 'place': 'Hall', 'sort_order': 1, 'status': 'active',
                'images': [], 'tags': []}),
            hidden: dict(version=1, author='alice', dependencies={}, payload={
                'title': 'Hidden', 'short_description': '', 'full_description': '',
                'event_date': None, 'place': '', 'sort_order': 2, 'status': 'hidden',
                'images': [], 'tags': []}),
            independent: dict(version=1, author='bob', dependencies={}, payload={
                'title': 'Independent ready', 'short_description': '', 'full_description': '',
                'event_date': None, 'place': '', 'sort_order': 3, 'status': 'hidden',
                'images': [], 'tags': []}),
            dataset: dict(version=1, author='alice', dependencies={event: 1}, payload={
                'schema': 1, 'name': 'Events', 'module': 'events', 'events': [event]}),
            block: dict(version=1, author='alice', dependencies={dataset: 1}, payload={
                'schema': 1, 'name': 'Cards', 'dataset': dataset, 'tags': [], 'limit': 3,
                'appearance': 'cards'}),
            layout: dict(version=1, author='alice', dependencies={block: 1}, payload={
                'schema': 1, 'target': 'tv-landscape', 'columns': 4, 'rows': 3,
                'placements': [dict(block=block, x=0, y=0, w=2, h=3)]}),
            page: dict(version=1, author='alice', dependencies={layout: 1}, payload={
                'schema': 1, 'name': 'Notice board', 'order': 0,
                'layouts': {'tv-landscape': layout}, 'fallback': 'tv-landscape'}),
            profile: dict(version=1, author='admin', dependencies={page: 1}, payload={
                'schema': 1, 'name': 'Shared', 'selection': {
                    'pages': [page], 'start_page': page, 'transition_seconds': 15}}),
            windows: dict(version=1, author='admin', dependencies={profile: 1}, payload={
                'schema': 1, 'device': 'screen-windows', 'profile': profile,
                'selection': None}),
            android: dict(version=1, author='admin', dependencies={profile: 1}, payload={
                'schema': 1, 'device': 'screen-android', 'profile': profile,
                'selection': None}),
        }
        included = [dict(id=identity, version=entry['version'], author=entry['author'])
                    for identity, entry in objects.items() if identity != hidden]
        excluded = [dict(id=hidden, version=2, author='alice', reason='working'),
                    dict(id=unseen, version=1, author='alice', reason='working')]
        return {'plan': {'included': included, 'excluded': excluded}, 'objects': objects}

    def _target(self, device, projection, destination, renderer, mode):
        content = encode(r.project_target(self.revision, device, projection))
        publication, files = self._publication(destination, renderer, content)
        return {
            'device_id': device,
            'projection': projection,
            'destination': destination,
            'configuration': {'version': 1, 'profile_id': f'{mode}-profile', 'revision': 1,
                              'mode': mode},
            'publication': publication,
            'files': files,
        }

    def _publication(self, destination, renderer, content, extras=None):
        revision = r.revision_sha256(self.revision)
        files = [{'path': r.PAGE_ENTRYPOINT, 'size': len(content), 'sha256': sha(content)}]
        for name, payload in (extras or {}).items():
            files.append({'path': name, 'size': len(payload), 'sha256': sha(payload)})
        manifest = {'schema_version': 2, 'kind': 'pages', 'revision': revision,
                    'renderer': 'pages-v1', 'resource_contract': 1, 'files': files,
                    'entrypoints': [r.PAGE_ENTRYPOINT]}
        raw_manifest = encode(manifest)
        package_id = sha(raw_manifest)
        package = {'manifest.json': raw_manifest, r.PAGE_ENTRYPOINT: content,
                   **(extras or {})}
        inventory = [{'path': 'manifest.json', 'size': len(raw_manifest),
                      'sha256': package_id}, *files]
        js_sha256 = sha(f'pages-js-{renderer}'.encode('ascii'))
        css_sha256 = sha(f'pages-css-{renderer}'.encode('ascii'))
        publication = {
            'version': 2, 'package_id': package_id, 'revision': revision,
            'raw_manifest_sha256': package_id,
            'renderer': {'build_id': a.page_renderer_build_id(js_sha256, css_sha256),
                         'js_sha256': js_sha256, 'css_sha256': css_sha256},
            'resource_profile': PROFILE, 'limits': dict(LIMITS), 'windows_images': {},
            'package': {'files': inventory},
            'kiosk': {'files': []}, 'tv': {'files': []},
        }
        return publication, {'package': package, 'kiosk': {}, 'tv': {}}

    def _proof(self, plan):
        return {'approval': a.page_signed(self.device, plan), 'chain': self.chain,
                'policy': self.policy_envelope}

    def _assignment(self, prepared, device, generation=1):
        target = next(item for item in prepared['document']['targets']
                      if item['device_id'] == device)
        return {
            'version': 4, 'group_id': self.group, 'device_id': device, 'profile': PROFILE,
            'generation': generation,
            'revision_sha256': prepared['document']['plan']['revision_sha256'],
            'destination': target['destination'], 'projection': target['projection'],
            'metadata_sha256': sha(encode(target['metadata'])), 'metadata': target['metadata'],
            'display': target['configuration'],
            'publisher': self._proof(prepared['document']['plan']),
        }

    def _approve(self, assignment):
        return a.page_assignment(assignment['publisher'], assignment, spki_der(self.root),
                                 self.origin, self.now)

    @staticmethod
    def _renderer_args(assignment):
        renderer = assignment['metadata']['publication']['renderer']
        return {'expected_js_sha256': renderer['js_sha256'],
                'expected_css_sha256': renderer['css_sha256']}

    @staticmethod
    def _reidentify(plan):
        plan['id'] = sha(a.PAGE_PLAN_DOMAIN + encode(
            {key: value for key, value in plan.items() if key != 'id'}))
        return plan

    def test_two_targets_real_signature_review_and_matching_admission(self):
        self.assertEqual([item['device_id'] for item in self.document['targets']],
                         ['screen-android', 'screen-windows'])
        first, second = [sha(encode(item['metadata'])) for item in self.document['targets']]
        self.assertNotEqual(first, second)
        plan, policy = a.page_approval(
            self.proof['approval'], self.proof['chain'], self.proof['policy'],
            spki_der(self.root), self.group, self.origin, now=self.now)
        self.assertEqual(plan, self.document['plan'])
        self.assertEqual(policy['version'], 1)
        files = {identity: artifact['files']
                 for identity, artifact in self.prepared['artifacts'].items()}
        self.assertEqual(r.review(self.document, now=self.now, files=files), self.document)
        reviewed = r.review_target(self.document, device_id='screen-windows', now=self.now,
                                   files=files['screen-windows'])
        self.assertEqual(reviewed['content'], r.project_target(
            self.revision, 'screen-windows', 'tv-landscape'))

        for device in ('screen-windows', 'screen-android'):
            assignment = self._assignment(self.prepared, device)
            target, current = self._approve(assignment)[1:]
            self.assertEqual(current['version'], 1)
            admitted = r.admit(assignment['publisher'], assignment, spki_der(self.root),
                               self.origin, self.now, files=files[device],
                               expected_group_id=self.group, expected_device_id=device,
                               expected_profile=PROFILE,
                               expected_destination=assignment['destination'],
                               **self._renderer_args(assignment))
            self.assertEqual(admitted['target'], target)
            expected = r.project_target(self.revision, device, assignment['projection'])
            self.assertEqual(admitted['content'], expected)

        windows = self._assignment(self.prepared, 'screen-windows')
        with self.assertRaisesRegex(ValueError, 'inventory'):
            r.admit(windows['publisher'], windows, spki_der(self.root), self.origin,
                    self.now, files=files['screen-android'],
                    expected_group_id=self.group, expected_device_id='screen-windows',
                    expected_profile=PROFILE, expected_destination='windows-pages-v1',
                    **self._renderer_args(windows))
        renderer = windows['metadata']['publication']['renderer']
        with self.assertRaisesRegex(ValueError, 'renderer_mismatch'):
            r.admit(windows['publisher'], windows, spki_der(self.root), self.origin,
                    self.now, files=files['screen-windows'],
                    expected_group_id=self.group, expected_device_id='screen-windows',
                    expected_profile=PROFILE, expected_destination='windows-pages-v1',
                    expected_js_sha256='0' * 64,
                    expected_css_sha256=renderer['css_sha256'])
        changed = copy.deepcopy(windows)
        changed['publisher'] = self._proof(self._v1_plan())
        with self.assertRaisesRegex(ValueError, 'proof_substitution'):
            a.page_assignment(windows['publisher'], changed, spki_der(self.root),
                              self.origin, self.now)
        android_target = next(item for item in self.document['targets']
                              if item['device_id'] == 'screen-android')
        swapped = copy.deepcopy(windows)
        swapped['metadata'] = android_target['metadata']
        swapped['metadata_sha256'] = sha(encode(android_target['metadata']))
        with self.assertRaisesRegex(ValueError, 'substitution'):
            self._approve(swapped)

    def test_mutations_configuration_revision_renderer_and_projection(self):
        windows = self._assignment(self.prepared, 'screen-windows')
        for field, value, code in (
                ('mode', 'kiosk', 'configuration'),
                ('profile_id', 'other-profile', 'configuration'),
                ('revision', 2, 'configuration')):
            changed = copy.deepcopy(windows)
            changed['display'][field] = value
            with self.subTest(field=field), self.assertRaisesRegex(ValueError, code):
                self._approve(changed)
        for field, value, code in (
                ('profile', 'other', 'configuration'),
                ('revision_sha256', 'f' * 64, 'content'),
                ('projection', 'tv-portrait', 'substitution'),
                ('destination', 'android-pages-v1', 'substitution')):
            changed = copy.deepcopy(windows)
            changed[field] = value
            with self.subTest(field=field), self.assertRaisesRegex(ValueError, code):
                self._approve(changed)

        plan = copy.deepcopy(self.document['plan'])
        plan['targets'][1]['renderer'] = 'f' * 64
        self._reidentify(plan)
        changed = copy.deepcopy(windows)
        changed['publisher'] = self._proof(plan)
        with self.assertRaisesRegex(ValueError, 'renderer'):
            a.page_assignment(changed['publisher'], changed, spki_der(self.root),
                              self.origin, self.now)

        changed = copy.deepcopy(self.document)
        changed['revision']['objects']['1001']['payload']['title'] = 'Changed'
        with self.assertRaisesRegex(ValueError, 'revision'):
            r.review(changed, now=self.now,
                     files={identity: artifact['files']
                            for identity, artifact in self.prepared['artifacts'].items()})

        changed = copy.deepcopy(self.document)
        changed['revision']['plan']['included'][0]['author'] = 'mallory'
        with self.assertRaisesRegex(ValueError, 'plan_entry'):
            r.review(changed, now=self.now,
                     files={identity: artifact['files']
                            for identity, artifact in self.prepared['artifacts'].items()})

    def test_file_dependency_duplicate_and_ancestry_mutations_are_refused(self):
        files = copy.deepcopy(self.prepared['artifacts']['screen-windows']['files'])
        files['package'][r.PAGE_ENTRYPOINT] = b'{}'
        windows = self._assignment(self.prepared, 'screen-windows')
        with self.assertRaisesRegex(ValueError, 'inventory'):
            r.admit(windows['publisher'], windows, spki_der(self.root), self.origin,
                    self.now, files=files, expected_group_id=self.group,
                    expected_device_id='screen-windows', expected_profile=PROFILE,
                    expected_destination='windows-pages-v1',
                    **self._renderer_args(windows))

        revision = copy.deepcopy(self.revision)
        dataset = next(identity for identity in revision['objects']
                       if identity.startswith('dataset-'))
        revision['objects'][dataset]['dependencies']['1001'] = 2
        with self.assertRaisesRegex(ValueError, 'dependency_version'):
            r.validate_revision(revision)
        revision = copy.deepcopy(self.revision)
        revision['plan']['excluded'][0]['reason'] = 'draft text with spaces'
        with self.assertRaisesRegex(ValueError, 'excluded_reason'):
            r.validate_revision(revision)

        duplicate = copy.deepcopy(self.windows)
        with self.assertRaisesRegex(ValueError, 'ambiguity'):
            r.prepare_release(revision=self.revision, authorization=self.authorization,
                              targets=[self.windows, duplicate])
        wrong = copy.deepcopy(self.windows)
        wrong['projection'] = 'kiosk-landscape'
        with self.assertRaisesRegex(ValueError, 'projection'):
            r.prepare_release(revision=self.revision, authorization=self.authorization,
                              targets=[wrong])
        with self.assertRaisesRegex(ValueError, 'plan'):
            r.prepare_release(revision=self.revision, authorization=self.authorization,
                              targets=[self.windows], parents=['5' * 64],
                              known_heads=['6' * 64])
        with self.assertRaisesRegex(ValueError, 'ancestry'):
            a.check_ancestry(self.document['plan'], (), [self._v1_plan()])

    def _v1_plan(self):
        target = next(item for item in self.document['plan']['targets']
                      if item['device_id'] == 'screen-windows')
        plan = {
            'group_id': self.group, 'origin': self.origin, 'user_id': 'user1',
            'device_id': key_id(self.device), 'policy_version': 1,
            'issued': self.now, 'expires': self.now + 600,
            'publication_sha256': '1' * 64, 'dependencies_sha256': '2' * 64,
            'renderer': '3' * 64,
            'targets': [{'device_id': target['device_id'],
                         'profile_id': target['profile_id'],
                         'profile_version': target['profile_version'],
                         'mode': target['mode'],
                         'configuration_sha256': target['configuration_sha256']}],
            'parents': [],
        }
        plan['id'] = sha(encode(plan))
        return plan

    def test_exclusion_forms_and_independent_ready_item(self):
        objects = self.revision['objects']
        self.assertIn('1004', {entry['id'] for entry in self.revision['plan']['included']})
        self.assertNotIn('1003', objects)
        self.assertEqual(objects['1002']['version'], 1)
        self.assertEqual(self.revision['plan']['excluded'], [
            {'id': '1002', 'version': 2, 'author': 'alice', 'reason': 'working'},
            {'id': '1003', 'version': 1, 'author': 'alice', 'reason': 'working'}])
        self.assertEqual(r.validate_revision(self.revision), self.revision)
        changed = copy.deepcopy(self.revision)
        changed['objects']['1002']['version'] = 2
        with self.assertRaisesRegex(ValueError, 'plan_entry'):
            r.validate_revision(changed)

    def test_data_only_package_parser_renderer_and_local_identity(self):
        content = encode(r.project_target(self.revision, 'screen-windows', 'tv-landscape'))
        publication, files = self._publication('windows-pages-v1', 'z', content,
                                               {'app.js': b'alert(1)'})
        with self.assertRaisesRegex(ValueError, 'data_only'):
            r.verify_inventory(publication, files)
        publication, files = self._publication('windows-pages-v1', 'z',
                                               b'x' * (r.MAX_DOCUMENT_BYTES + 1))
        with self.assertRaisesRegex(ValueError, 'content'):
            r.verify_inventory(publication, files)

        target = next(item for item in self.document['targets']
                      if item['device_id'] == 'screen-windows')
        metadata = copy.deepcopy(target['metadata'])
        metadata['publication']['renderer']['js_sha256'] = 'f' * 64
        with self.assertRaisesRegex(ValueError, 'renderer'):
            a.validate_page_metadata(metadata)
        with self.assertRaises(ValueError):
            validate_manifest({'schema_version': 2, 'kind': 'pages', 'revision': '7',
                               'renderer': 'pages-v1', 'resource_contract': 1,
                               'files': [], 'entrypoints': [r.PAGE_ENTRYPOINT]})
        windows = self._assignment(self.prepared, 'screen-windows')
        with self.assertRaisesRegex(ValueError, 'local_identity'):
            r.admit(windows['publisher'], windows, spki_der(self.root), self.origin,
                    self.now, files=self.prepared['artifacts']['screen-windows']['files'],
                    expected_group_id=self.group, expected_device_id='screen-android',
                    expected_profile=PROFILE, expected_destination='windows-pages-v1',
                    **self._renderer_args(windows))

    def test_inner_manifest_hash_size_and_entry_shape_are_verified(self):
        content = encode(r.project_target(self.revision, 'screen-windows', 'tv-landscape'))
        for field, value in (('sha256', 'f' * 64), ('size', len(content) + 1),
                             ('extra', 'x')):
            publication, files = self._publication('windows-pages-v1', 'z', content)
            manifest = decode(files['package']['manifest.json'])
            entry = next(item for item in manifest['files']
                         if item['path'] == r.PAGE_ENTRYPOINT)
            entry[field] = value
            raw = encode(manifest)
            files['package']['manifest.json'] = raw
            publication['package_id'] = sha(raw)
            publication['raw_manifest_sha256'] = sha(raw)
            outer = next(item for item in publication['package']['files']
                         if item['path'] == 'manifest.json')
            outer['size'] = len(raw)
            outer['sha256'] = sha(raw)
            with self.subTest(field=field), self.assertRaisesRegex(
                    ValueError, 'package_inventory'):
                r.verify_inventory(publication, files)

    def test_package_inventory_row_bound_matches_contract(self):
        target = next(item for item in self.document['targets']
                      if item['device_id'] == 'screen-windows')
        metadata = copy.deepcopy(target['metadata'])
        inventory = [{'path': 'manifest.json', 'size': 0, 'sha256': '0' * 64}]
        inventory.extend({'path': f'file-{number}.dat', 'size': 0, 'sha256': '0' * 64}
                         for number in range(10000))
        metadata['publication']['package']['files'] = inventory
        self.assertEqual(a.validate_page_metadata(metadata)['package']['files'], inventory)
        inventory.append({'path': 'file-10000.dat', 'size': 0, 'sha256': '0' * 64})
        with self.assertRaisesRegex(ValueError, 'inventory'):
            a.validate_page_metadata(metadata)

    def test_v1_remains_accepted_and_v2_has_no_unsigned_fallback(self):
        plan = self._v1_plan()
        self.assertEqual(a.validate_plan(plan, now=self.now), plan)
        self.assertEqual(a.approval(a.signed(self.device, 'publication', plan), self.chain,
                                    self.policy_envelope, spki_der(self.root), self.group,
                                    self.origin, self.now)[0], plan)
        with self.assertRaises(ValueError):
            a.validate_plan(self.document['plan'], now=self.now)
        with self.assertRaises(ValueError):
            a.page_verified(a.signed(self.device, 'publication', plan), spki_der(self.device))
        with self.assertRaises(ValueError):
            a.verified(self.proof['approval'], spki_der(self.device), 'publication')
        for version in (1, 3):
            changed = self._assignment(self.prepared, 'screen-windows')
            changed['version'] = version
            with self.assertRaisesRegex(ValueError, 'assignment_version'):
                self._approve(changed)
        unsigned = self._assignment(self.prepared, 'screen-windows')
        unsigned.pop('publisher')
        with self.assertRaisesRegex(ValueError, 'proof'):
            r.admit({}, unsigned, spki_der(self.root), self.origin, self.now,
                    files=self.prepared['artifacts']['screen-windows']['files'],
                    expected_group_id=self.group, expected_device_id='screen-windows',
                    expected_profile=PROFILE, expected_destination='windows-pages-v1',
                    **self._renderer_args(unsigned))


if __name__ == '__main__':
    unittest.main()
