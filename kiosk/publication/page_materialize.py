"""Deterministic data-only page packages for exact display targets.

The package contains only ``data/page-release.json`` and the uploaded images
that the frozen Events projection actually references. No server-supplied
HTML, script, stylesheet, template or second JSON file is part of a page
publication. A candidate is written to an immutable delivery catalog before
review; no assignment pointer changes here.
"""
from __future__ import annotations

from pathlib import Path

from kiosk.delivery.protocol import LIMITS, PROFILE, digest, encode, sha, text
from . import authority, page_release
from .exporter import PackageError, _read_stable

PAGE_ENTRYPOINT = page_release.PAGE_ENTRYPOINT
MAX_PAGE_FILES = 10001
MAX_PAGE_FILE_BYTES = 64 * 1024 * 1024
MAX_PAGE_BYTES = 192 * 1024 * 1024

_KIOSK_ROOT = Path(__file__).resolve().parents[1]
PAGE_ASSETS = _KIOSK_ROOT / 'static' / 'js'


class PageMaterializeError(ValueError):
    """Stable materialization refusal without draft text or host paths."""

    def __init__(self, code):
        self.code = code
        super().__init__(code)


def _fail(code):
    raise PageMaterializeError(code)


def renderer_identity():
    """The page renderer identity pinned by both Content and native clients."""
    js = (PAGE_ASSETS / 'page_display.js').read_bytes()
    css = (_KIOSK_ROOT / 'static' / 'css' / 'page_display.css').read_bytes()
    js_sha256, css_sha256 = sha(js), sha(css)
    return {'build_id': authority.page_renderer_build_id(js_sha256, css_sha256),
            'js_sha256': js_sha256, 'css_sha256': css_sha256}


def _image_bytes(uploads_dir, name):
    if not name.startswith('static/uploads/'):
        _fail('page_release_image_reference')
    relative = name.removeprefix('static/uploads/')
    try:
        payload, _ = _read_stable(Path(uploads_dir), relative)
    except PackageError:
        raise PageMaterializeError('page_release_image_inventory') from None
    if len(payload) > MAX_PAGE_FILE_BYTES:
        _fail('page_release_image_inventory')
    return payload


def materialize(content, revision_sha256, uploads_dir):
    """Build and independently re-verify one target's closed package byte set."""
    digest(revision_sha256)
    content_bytes = encode(content)
    if len(content_bytes) > page_release.MAX_DOCUMENT_BYTES:
        _fail('page_release_document_limit')
    references = page_release._image_paths(content)
    package_files = {PAGE_ENTRYPOINT: content_bytes}
    total = len(content_bytes)
    for name in sorted(references):
        payload = _image_bytes(uploads_dir, name)
        total += len(payload)
        if total > MAX_PAGE_BYTES:
            _fail('page_release_package_inventory')
        package_files[name] = payload
    if len(package_files) + 1 > MAX_PAGE_FILES:
        _fail('page_release_package_inventory')
    files = []
    for name in sorted(package_files):
        payload = package_files[name]
        if len(payload) > MAX_PAGE_FILE_BYTES:
            _fail('page_release_package_inventory')
        files.append({'path': name, 'size': len(payload), 'sha256': sha(payload)})
    manifest = {
        'schema_version': authority.PAGE_MANIFEST_VERSION,
        'kind': 'pages',
        'revision': revision_sha256,
        'renderer': authority.PAGE_RENDERER,
        'resource_contract': 1,
        'files': files,
        'entrypoints': [PAGE_ENTRYPOINT],
    }
    raw_manifest = encode(manifest)
    package_files['manifest.json'] = raw_manifest
    renderer = renderer_identity()
    publication = {
        'version': authority.PAGE_PLAN_VERSION,
        'package_id': sha(raw_manifest),
        'revision': revision_sha256,
        'raw_manifest_sha256': sha(raw_manifest),
        'renderer': renderer,
        'resource_profile': PROFILE,
        'limits': LIMITS,
        'windows_images': {},
        'package': {'files': [
            {'path': 'manifest.json', 'size': len(raw_manifest), 'sha256': sha(raw_manifest)},
            *files,
        ]},
        'kiosk': {'files': []},
        'tv': {'files': []},
    }
    transport = {'package': package_files, 'kiosk': {}, 'tv': {}}
    page_release.verify_inventory(publication, transport)
    return {'content': content_bytes, 'files': transport, 'publication': publication}


def prepare_page_publication(workspace, state, secret, targets, parents, uploads_dir):
    """Freeze the current page plan and materialize every exact target variant.

    Target selection is server-managed delivery configuration, not request-provided
    IDs or projections. The returned document is unsigned; the trusted
    Maintenance key signs only after independent review.
    """
    context = workspace.page_release_context(secret, parents)
    requests = []
    seen = set()
    for target in targets:
        if not isinstance(target, dict):
            raise PageMaterializeError('page_release_target_fields')
        device_id = text(target.get('device_id'))
        if device_id in seen:
            raise PageMaterializeError('page_release_target_ambiguity')
        seen.add(device_id)
        configuration = target.get('configuration')
        if not isinstance(configuration, dict):
            raise PageMaterializeError('page_release_configuration')
        if (target.get('profile_id') != configuration.get('profile_id')
                or target.get('profile_version') != configuration.get('revision')
                or target.get('mode') != configuration.get('mode')
                or target.get('configuration_sha256') != sha(encode(configuration))):
            raise PageMaterializeError('page_release_configuration_substitution')
        projection = target.get('projection')
        if (projection not in authority.PAGE_PROJECTIONS
                or projection.split('-', 1)[0] != configuration['mode']):
            raise PageMaterializeError('page_release_projection')
        destination = target.get('destination')
        if destination not in authority.PAGE_DESTINATIONS:
            raise PageMaterializeError('page_release_destination')
        content = page_release.project_target(context['revision'], device_id, projection)
        artifact = materialize(content, page_release.revision_sha256(context['revision']),
                               uploads_dir)
        requests.append({
            'device_id': device_id,
            'projection': projection,
            'destination': destination,
            'configuration': configuration,
            'publication': artifact['publication'],
            'files': artifact['files'],
        })
    prepared = page_release.prepare_release(
        revision=context['revision'], authorization=context['authorization'],
        targets=requests, parents=context['parents'], ancestry=context['ancestry'],
        known_heads=context['known_heads'])
    from kiosk.delivery.publication import publish_page
    document = prepared['document']
    for target in document['targets']:
        artifact = prepared['artifacts'][target['device_id']]
        publish_page(state, target['metadata'], artifact['files'])
    workspace.store_page_candidate(secret, document)
    return document


def load_candidate_files(state, document, *, device_ids=None):
    """Re-read every exact catalog byte for independent review or recheck."""
    from kiosk.delivery.publication import page_catalog
    result = {}
    selected = None if device_ids is None else set(device_ids)
    for target in document['targets']:
        device_id = target['device_id']
        if selected is not None and device_id not in selected:
            continue
        metadata = target['metadata']
        publication = authority.validate_page_metadata(metadata)
        root = page_catalog(state, metadata)
        try:
            package = {}
            for entry in publication['package']['files']:
                payload, _ = _read_stable(root / 'package', entry['path'])
                package[entry['path']] = payload
            files = {'package': package, 'kiosk': {}, 'tv': {}}
            page_release.verify_inventory(publication, files)
            content = page_release._entrypoint(metadata, files)
        except (OSError, PackageError, page_release.PageReleaseError):
            raise PageMaterializeError('page_release_package_inventory') from None
        if content['page'].get('target') != target['projection']:
            _fail('page_release_content_substitution')
        result[device_id] = files
    return result
