"""Deterministic v2 page-release preparation and independent review.

This module never holds a private key and never offers a generic signing API.
It prepares exact transport inputs, re-derives the allowed target payload from
the frozen page graph and verifies the closed outer and inner package
inventories that a native reviewer signs. Admission requires caller-pinned
renderer asset hashes. The accepted v1 Events path remains in ``authority``.
"""
from __future__ import annotations

from kiosk.delivery.protocol import MAX_METADATA_BYTES, decode, digest, encode, fields, sha, text
from kiosk.features.events import derive
from kiosk.features.events.payload import validate_payload
from . import authority, pages, validate_manifest

VERSION = authority.PAGE_PLAN_VERSION
PAGE_ENTRYPOINT = 'data/page-release.json'
MAX_DOCUMENT_BYTES = MAX_METADATA_BYTES
MAX_REVISION_OBJECTS = 1000


class PageReleaseError(ValueError):
    """A stable review/preparation error that does not echo draft content."""

    def __init__(self, code):
        self.code = code
        super().__init__(code)


def _fail(code):
    raise PageReleaseError(code)


def _exact(value, names, code):
    if not isinstance(value, dict) or set(value) != set(names.split()):
        _fail(code)
    return value


def _version(value):
    if type(value) is not int or not 1 <= value < 2**63:
        _fail('page_release_version')
    return value


def _author(value):
    try:
        return text(value)
    except (TypeError, ValueError):
        _fail('page_release_author')


def _objects_map(value):
    if not isinstance(value, dict) or not 1 <= len(value) <= MAX_REVISION_OBJECTS:
        _fail('page_release_object_limit')
    return value


def validate_revision(value):
    """Validate one frozen page-plan snapshot without trusting its draft text."""
    _exact(value, 'plan objects', 'page_release_revision_fields')
    plan = _exact(value['plan'], 'included excluded', 'page_release_plan_fields')
    objects = _objects_map(value['objects'])
    for group, name in ((plan['included'], 'included'), (plan['excluded'], 'excluded')):
        if not isinstance(group, list) or len(group) > MAX_REVISION_OBJECTS:
            _fail('page_release_plan_fields')
        for entry in group:
            expected = 'id version author' + (' reason' if name == 'excluded' else '')
            _exact(entry, expected, 'page_release_plan_entry')
            try:
                pages.kind(entry['id'])
            except pages.PageError:
                _fail('page_release_object_identity')
            _version(entry['version'])
            _author(entry['author'])
            if name == 'excluded':
                try:
                    text(entry['reason'], 64)
                except (TypeError, ValueError):
                    _fail('page_release_excluded_reason')
    included = plan['included']
    excluded = plan['excluded']
    listed = [entry['id'] for entry in included + excluded]
    if len(set(listed)) != len(listed):
        _fail('page_release_plan_ambiguity')

    normalized = {}
    for identity, entry in objects.items():
        _exact(entry, 'version payload dependencies author', 'page_release_object_fields')
        try:
            object_kind = pages.kind(identity)
        except pages.PageError:
            _fail('page_release_object_identity')
        _version(entry['version'])
        _author(entry['author'])
        if not isinstance(entry['payload'], dict) or not isinstance(entry['dependencies'], dict):
            _fail('page_release_object_fields')
        try:
            if object_kind == 'event':
                validate_payload(entry['payload'])
                references = []
            else:
                references = pages.validate(identity, entry['payload'])
                if object_kind == 'page':
                    layout_payloads = {}
                    for dependency in references:
                        if dependency not in objects:
                            _fail('page_release_dependency_missing')
                        layout_payloads[dependency] = objects[dependency]['payload']
                    pages.validate_layout_targets(entry['payload'], layout_payloads)
        except PageReleaseError:
            raise
        except (pages.PageError, ValueError):
            _fail('page_release_object_payload')
        dependencies = entry['dependencies']
        if set(dependencies) != set(references):
            _fail('page_release_dependency_mismatch')
        for dependency, version in dependencies.items():
            _version(version)
            target = objects.get(dependency)
            if target is None:
                _fail('page_release_dependency_missing')
            try:
                pages.kind(dependency)
            except pages.PageError:
                _fail('page_release_object_identity')
            if target['version'] != version:
                _fail('page_release_dependency_version')
        normalized[identity] = entry

    for entry in included:
        target = objects.get(entry['id'])
        if target is None or target['version'] != entry['version'] or target['author'] != entry['author']:
            _fail('page_release_plan_entry')
    # An exclusion names the current working row. The active snapshot may omit
    # a new row or retain only its older published version and author.
    for entry in excluded:
        target = objects.get(entry['id'])
        if target is not None and target['version'] >= entry['version']:
            _fail('page_release_plan_entry')
    if len(encode(value)) > MAX_DOCUMENT_BYTES:
        _fail('page_release_document_limit')
    return value


def revision_sha256(value):
    validate_revision(value)
    return sha(encode({'plan': value['plan'], 'objects': value['objects']}))


def project_target(value, device_id, projection):
    """The exact preview payload for one frozen revision and target profile."""
    try:
        text(device_id)
    except (TypeError, ValueError):
        _fail('page_release_target')
    if projection not in authority.PAGE_PROJECTIONS:
        _fail('page_release_projection')
    try:
        projected, selected_events = pages.target_content(value['objects'], device_id, projection)
        public = derive(selected_events, {}, 1) if selected_events else {'events': [], 'tags': []}
    except (pages.PageError, ValueError, KeyError):
        _fail('page_release_projection_unavailable')
    return {'page': projected, 'events': public['events'], 'tags': public['tags']}


def target_metadata(destination, revision_sha, content_sha, publication):
    if destination not in authority.PAGE_DESTINATIONS:
        _fail('page_release_destination')
    digest(revision_sha)
    digest(content_sha)
    if not isinstance(publication, dict) or publication.get('revision') != revision_sha:
        _fail('page_release_revision')
    metadata = {'version': VERSION, 'destination': destination,
                'revision_sha256': revision_sha, 'content_sha256': content_sha,
                'publication': publication}
    try:
        authority.validate_page_metadata(metadata)
    except (TypeError, ValueError):
        _fail('page_release_metadata')
    return metadata


def _group_files(value, group):
    if not isinstance(value, dict) or not value:
        _fail('page_release_inventory')
    result = {}
    for name, payload in value.items():
        if not isinstance(name, str) or not isinstance(payload, bytes):
            _fail('page_release_inventory')
        result[name] = payload
    return result


def _verify_group(entries, files, code):
    if not isinstance(entries, list):
        _fail(code)
    expected = {}
    for entry in entries:
        expected[entry['path']] = entry
    if set(files) != set(expected):
        _fail(code)
    for name, entry in expected.items():
        payload = files[name]
        if len(payload) != entry['size'] or sha(payload) != entry['sha256']:
            _fail(code)


def _manifest_group(publication, files):
    raw = files['manifest.json']
    try:
        manifest = decode(raw)
        if encode(manifest) != raw:
            _fail('page_release_manifest_canonical')
        _exact(manifest, 'schema_version kind revision renderer resource_contract '
                         'files entrypoints', 'page_release_manifest_fields')
        if (type(manifest['schema_version']) is not int
                or manifest['schema_version'] != authority.PAGE_MANIFEST_VERSION
                or manifest['kind'] != 'pages'
                or manifest['renderer'] != authority.PAGE_RENDERER
                or type(manifest['resource_contract']) is not int
                or manifest['resource_contract'] != 1
                or manifest['entrypoints'] != [PAGE_ENTRYPOINT]):
            _fail('page_release_manifest_contract')
        digest(manifest['revision'])
        validate_manifest({'schema_version': 1, 'revision': manifest['revision'],
                           'renderer': 'events-v1', 'files': manifest['files']})
    except PageReleaseError:
        raise
    except (TypeError, ValueError):
        _fail('page_release_manifest')
    required = {'manifest.json'} | {entry['path'] for entry in manifest['files']}
    if set(files) != required:
        _fail('page_release_package_inventory')
    for entry in manifest['files']:
        if not isinstance(entry, dict) or set(entry) != {'path', 'size', 'sha256'}:
            _fail('page_release_package_inventory')
        name = entry['path']
        if name not in files or len(files[name]) != entry['size'] \
                or sha(files[name]) != entry['sha256']:
            _fail('page_release_package_inventory')
    if sha(encode(manifest)) != publication['package_id']:
        _fail('page_release_package_identity')
    if sha(raw) != publication['raw_manifest_sha256']:
        _fail('page_release_manifest_identity')
    if manifest['revision'] != publication['revision']:
        _fail('page_release_revision')
    for entry in manifest['files']:
        name = entry['path']
        if name == PAGE_ENTRYPOINT:
            continue
        suffix = name.rsplit('.', 1)[-1].casefold() if '.' in name else ''
        if (not name.startswith('static/uploads/') or suffix not in
                ('png', 'jpg', 'jpeg', 'webp', 'gif')):
            _fail('page_release_data_only')
    return manifest


def _decode_content(payload):
    try:
        content = decode(payload)
        if encode(content) != payload:
            _fail('page_release_content_canonical')
        _exact(content, 'page events tags', 'page_release_content_fields')
        if not isinstance(content['page'], dict) or not isinstance(content['events'], list) \
                or not isinstance(content['tags'], list):
            _fail('page_release_content_fields')
    except PageReleaseError:
        raise
    except (TypeError, ValueError):
        _fail('page_release_content')
    return content


def _image_paths(content):
    references = set()
    for event in content['events']:
        if not isinstance(event, dict):
            _fail('page_release_content')
        for field in ('image_kiosk', 'image_tv', 'image_thumb'):
            value = event.get(field)
            if value is None:
                continue
            if not isinstance(value, str) or not value.startswith('/static/uploads/'):
                _fail('page_release_image_reference')
            name = value[1:]
            suffix = name.rsplit('.', 1)[-1].casefold() if '.' in name else ''
            if suffix not in ('png', 'jpg', 'jpeg', 'webp', 'gif'):
                _fail('page_release_image_reference')
            references.add(name)
    return references


def _check_data_only(manifest, files, content):
    expected = {PAGE_ENTRYPOINT} | _image_paths(content)
    if {entry['path'] for entry in manifest['files']} != expected:
        _fail('page_release_image_inventory')
    if set(files['package']) != {'manifest.json'} | expected:
        _fail('page_release_package_inventory')


def verify_inventory(publication, files):
    """Verify a data-only pages package; kiosk/tv transport views stay empty."""
    _exact(files, 'package kiosk tv', 'page_release_inventory_groups')
    package = _group_files(files['package'], 'package')
    if files['kiosk'] != {} or files['tv'] != {}:
        _fail('page_release_transport_view')
    groups = {'package': package}
    try:
        authority.validate_page_metadata(
            {'version': VERSION, 'destination': authority.PAGE_DESTINATIONS[0],
             'revision_sha256': '0' * 64, 'content_sha256': '0' * 64,
             'publication': publication})
    except (TypeError, ValueError):
        _fail('page_release_metadata')
    _verify_group(publication['package']['files'], groups['package'],
                  'page_release_inventory')
    manifest = _manifest_group(publication, groups['package'])
    if PAGE_ENTRYPOINT not in groups['package']:
        _fail('page_release_entrypoint')
    content = _decode_content(groups['package'][PAGE_ENTRYPOINT])
    _check_data_only(manifest, groups, content)
    return manifest


def _entrypoint(metadata, files):
    package = files['package']
    entry = next((item for item in metadata['publication']['package']['files']
                  if item['path'] == PAGE_ENTRYPOINT), None)
    if entry is None or PAGE_ENTRYPOINT not in package:
        _fail('page_release_entrypoint')
    payload = package[PAGE_ENTRYPOINT]
    if len(payload) != entry['size'] or sha(payload) != entry['sha256']:
        _fail('page_release_entrypoint')
    if sha(payload) != metadata['content_sha256']:
        _fail('page_release_content_substitution')
    content = _decode_content(payload)
    manifest = _manifest_group(metadata['publication'], package)
    _check_data_only(manifest, files, content)
    return content


def _configuration(value):
    _exact(value, 'version profile_id revision mode', 'page_release_configuration')
    if (type(value['version']) is not int or value['version'] != 1
            or type(value['revision']) is not int or value['revision'] < 1):
        _fail('page_release_configuration')
    try:
        text(value['profile_id'], 64)
    except (TypeError, ValueError):
        _fail('page_release_configuration')
    if value['mode'] not in ('tv', 'kiosk'):
        _fail('page_release_mode')
    return value


def _check_local_renderer(metadata, js_sha256, css_sha256):
    try:
        digest(js_sha256)
        digest(css_sha256)
    except (TypeError, ValueError):
        _fail('page_release_local_renderer')
    renderer = metadata['publication']['renderer']
    if (renderer['js_sha256'] != js_sha256
            or renderer['css_sha256'] != css_sha256
            or renderer['build_id'] != authority.page_renderer_build_id(js_sha256, css_sha256)):
        _fail('page_release_renderer_mismatch')


def _validate_target(target, plan_target, revision, revision_hash):
    _exact(target, 'device_id projection destination configuration metadata',
           'page_release_target_fields')
    try:
        text(target['device_id'])
    except (TypeError, ValueError):
        _fail('page_release_target')
    if target['device_id'] != plan_target['device_id']:
        _fail('page_release_target_substitution')
    configuration = _configuration(target['configuration'])
    if (configuration['profile_id'] != plan_target['profile_id']
            or configuration['revision'] != plan_target['profile_version']
            or configuration['mode'] != plan_target['mode']
            or sha(encode(configuration)) != plan_target['configuration_sha256']):
        _fail('page_release_configuration_substitution')
    if (target['destination'] not in authority.PAGE_DESTINATIONS
            or target['destination'] != plan_target['destination']
            or target['projection'] not in authority.PAGE_PROJECTIONS
            or target['projection'] != plan_target['projection']
            or target['projection'].split('-', 1)[0] != configuration['mode']):
        _fail('page_release_target_substitution')
    metadata = target['metadata']
    try:
        publication = authority.validate_page_metadata(metadata)
    except (TypeError, ValueError):
        _fail('page_release_metadata')
    if (metadata['destination'] != plan_target['destination']
            or metadata['revision_sha256'] != revision_hash
            or sha(encode(metadata)) != plan_target['metadata_sha256']
            or publication['renderer']['build_id'] != plan_target['renderer']):
        _fail('page_release_metadata_substitution')
    content = project_target(revision, target['device_id'], target['projection'])
    if (content['page'].get('target') != target['projection']
            or sha(encode(content)) != metadata['content_sha256']):
        _fail('page_release_content_substitution')
    return content


def validate_document(value, *, now, known_heads=(), files=None):
    """Validate a transport document and, when supplied, every exact byte."""
    _exact(value, 'version plan revision targets ancestry', 'page_release_document_fields')
    if type(value['version']) is not int or value['version'] != VERSION:
        _fail('page_release_document_version')
    revision = validate_revision(value['revision'])
    revision_hash = revision_sha256(revision)
    if len(encode(value)) > MAX_DOCUMENT_BYTES:
        _fail('page_release_document_limit')
    try:
        plan = authority.validate_group_plan(value['plan'], now=now)
    except (TypeError, ValueError):
        _fail('page_release_plan')
    if (plan['revision_sha256'] != revision_hash
            or plan['dependencies_sha256'] != sha(encode(revision['objects']))):
        _fail('page_release_revision_substitution')
    if not isinstance(value['ancestry'], list):
        _fail('page_release_ancestry')
    try:
        authority.check_ancestry(plan, known_heads, value['ancestry'])
    except (TypeError, ValueError):
        _fail('page_release_ancestry')
    targets = value['targets']
    if not isinstance(targets, list) or not targets:
        _fail('page_release_target_limit')
    identities = []
    for target in targets:
        _exact(target, 'device_id projection destination configuration metadata',
               'page_release_target_fields')
        identities.append(target['device_id'])
    if identities != sorted(set(identities)):
        _fail('page_release_target_ambiguity')
    plan_targets = {target['device_id']: target for target in plan['targets']}
    if set(plan_targets) != set(identities):
        _fail('page_release_target_set')
    for target in targets:
        _validate_target(target, plan_targets[target['device_id']], revision, revision_hash)
    if files is not None:
        _exact(files, ' '.join(identities), 'page_release_files')
        for target in targets:
            metadata = target['metadata']
            verify_inventory(metadata['publication'], files[target['device_id']])
            content = _entrypoint(metadata, files[target['device_id']])
            expected = project_target(revision, target['device_id'], target['projection'])
            if encode(content) != encode(expected):
                _fail('page_release_content_substitution')
    return value


def prepare_release(*, revision, authorization, targets, parents=(), ancestry=(),
                    known_heads=()):
    """Return deterministic transport inputs; signing remains a native decision."""
    revision = validate_revision(revision)
    revision_hash = revision_sha256(revision)
    _exact(authorization, 'group_id origin user_id device_id policy_version issued expires',
           'page_release_authorization')
    if not isinstance(targets, list) or not targets:
        _fail('page_release_target_limit')
    artifacts = {}
    approved = {}
    prepared_targets = {}
    for request in targets:
        if not isinstance(request, dict) or set(request) != {
                'device_id', 'projection', 'destination', 'configuration', 'publication', 'files'}:
            _fail('page_release_target_fields')
        try:
            device_id = text(request['device_id'])
        except (TypeError, ValueError):
            _fail('page_release_target')
        if device_id in approved:
            _fail('page_release_target_ambiguity')
        configuration = _configuration(request['configuration'])
        if request['projection'] not in authority.PAGE_PROJECTIONS:
            _fail('page_release_projection')
        if request['projection'].split('-', 1)[0] != configuration['mode']:
            _fail('page_release_projection')
        content = project_target(revision, device_id, request['projection'])
        content_bytes = encode(content)
        metadata = target_metadata(request['destination'], revision_hash,
                                   sha(content_bytes), request['publication'])
        verify_inventory(metadata['publication'], request['files'])
        if _entrypoint(metadata, request['files']) != content:
            _fail('page_release_content_substitution')
        target = {
            'device_id': device_id,
            'profile_id': configuration['profile_id'],
            'profile_version': configuration['revision'],
            'mode': configuration['mode'],
            'configuration_sha256': sha(encode(configuration)),
            'projection': request['projection'],
            'destination': request['destination'],
            'renderer': metadata['publication']['renderer']['build_id'],
            'metadata_sha256': sha(encode(metadata)),
        }
        approved[device_id] = target
        artifacts[device_id] = {'content': content_bytes, 'files': request['files']}
        prepared_targets[device_id] = {
            'device_id': device_id,
            'projection': request['projection'],
            'destination': request['destination'],
            'configuration': configuration,
            'metadata': metadata,
        }
    if not isinstance(parents, (list, tuple)):
        _fail('page_release_parent_limit')
    if not isinstance(ancestry, (list, tuple)):
        _fail('page_release_ancestry')
    plan = {
        'version': VERSION,
        'group_id': authorization['group_id'],
        'origin': authorization['origin'],
        'user_id': authorization['user_id'],
        'device_id': authorization['device_id'],
        'policy_version': authorization['policy_version'],
        'issued': authorization['issued'],
        'expires': authorization['expires'],
        'revision_sha256': revision_hash,
        'dependencies_sha256': sha(encode(revision['objects'])),
        'targets': [approved[identity] for identity in sorted(approved)],
        'parents': sorted(set(parents)),
    }
    try:
        plan['id'] = sha(authority.PAGE_PLAN_DOMAIN
                         + encode({key: value for key, value in plan.items() if key != 'id'}))
        authority.validate_group_plan(plan, now=authorization['issued'])
        authority.check_ancestry(plan, known_heads, list(ancestry))
    except (TypeError, ValueError):
        _fail('page_release_plan')
    document = {'version': VERSION, 'plan': plan, 'revision': revision,
                'targets': [prepared_targets[identity] for identity in sorted(prepared_targets)],
                'ancestry': list(ancestry)}
    if len(encode(document)) > MAX_DOCUMENT_BYTES:
        _fail('page_release_document_limit')
    validate_document(document, now=authorization['issued'], known_heads=known_heads)
    return {'document': document,
            'artifacts': {identity: artifacts[identity] for identity in sorted(artifacts)}}


def review(document, *, now, known_heads=(), files):
    """Independently re-derive every target before a native signature exists."""
    validate_document(document, now=now, known_heads=known_heads, files=files)
    return document


def review_target(document, *, device_id, now, known_heads=(), files):
    """Review exact bytes for one target without requiring all targets in memory."""
    validate_document(document, now=now, known_heads=known_heads)
    try:
        text(device_id)
    except (TypeError, ValueError):
        _fail('page_release_target_substitution')
    matches = [target for target in document['targets']
               if target['device_id'] == device_id]
    if len(matches) != 1:
        _fail('page_release_target_substitution')
    target = matches[0]
    metadata = target['metadata']
    verify_inventory(metadata['publication'], files)
    content = _entrypoint(metadata, files)
    expected = project_target(document['revision'], device_id, target['projection'])
    if encode(content) != encode(expected):
        _fail('page_release_content_substitution')
    return {'document': document, 'target': target, 'content': content}


def admit(proof, assignment, root_spki, trusted_origin, now, *, files,
          expected_group_id, expected_device_id, expected_profile,
          expected_destination, expected_js_sha256, expected_css_sha256,
          policy_floor=0, known_heads=()):
    """Admit a signed v2 assignment after proof, renderer and exact byte checks."""
    if not isinstance(assignment, dict) or assignment.get('publisher') != proof:
        _fail('page_release_proof_substitution')
    try:
        text(expected_group_id)
        text(expected_device_id)
        text(expected_profile, 64)
    except (TypeError, ValueError):
        _fail('page_release_local_identity')
    if expected_profile != authority.PROFILE or expected_destination not in \
            authority.PAGE_DESTINATIONS:
        _fail('page_release_local_identity')
    if (assignment.get('group_id') != expected_group_id
            or assignment.get('device_id') != expected_device_id
            or assignment.get('profile') != expected_profile
            or assignment.get('destination') != expected_destination):
        _fail('page_release_local_identity')
    try:
        plan, target, current = authority.page_assignment(
            proof, assignment, root_spki, trusted_origin, now,
            policy_floor=policy_floor, known_heads=known_heads)
    except (TypeError, KeyError):
        _fail('page_release_assignment')
    except ValueError:
        raise
    metadata = assignment['metadata']
    _check_local_renderer(metadata, expected_js_sha256, expected_css_sha256)
    verify_inventory(metadata['publication'], files)
    content = _entrypoint(metadata, files)
    if content['page'].get('target') != assignment['projection']:
        _fail('page_release_content_substitution')
    return {'plan': plan, 'target': target, 'policy': current, 'content': content}
