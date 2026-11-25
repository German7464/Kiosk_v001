"""Prepare immutable transport artifacts using the existing Windows verifier/renderer."""
import os
from pathlib import Path
import shutil
import tempfile

from PIL import Image

from kiosk.display.cache import renderer_identity, renderer_compatible
from kiosk.publication.exporter import (_json, _plain_path, _read_stable, _references,
                                        _stream_stable, verify_package)
from kiosk.publication.renderer import ASSETS, build_view
from kiosk.publication.store import _ExpectedFileWriter
from .protocol import (DeliveryError, LIMITS, MAX_METADATA_BYTES, PROFILE, decode, digest,
                       encode, sha)

MAX_PUBLICATION_BYTES = 192 * 1024 * 1024
MAX_CATALOG_BYTES = 512 * 1024 * 1024


def inventory(root):
    entries = []
    for path in sorted(root.rglob('*')):
        if path.is_file():
            name = path.relative_to(root).as_posix()
            size, witness = _stream_stable(root, name)
            entries.append({'path': name, 'size': size, 'sha256': witness[3]})
    return entries


def publish(state, source):
    """No assignment changes until every artifact is verified and promoted."""
    # Serialize catalog writers with the same isolated SQLite lease as assignments.
    with state.connection() as db:
        return _publish(state, source, db)


def _page_tree(root, publication):
    from kiosk.publication import page_release
    package = {}
    for entry in publication['package']['files']:
        payload, _ = _read_stable(root / 'package', entry['path'])
        package[entry['path']] = payload
    files = {'package': package, 'kiosk': {}, 'tv': {}}
    page_release.verify_inventory(publication, files)
    return files


def _same_tree(left, right):
    """Compare exact transport trees without JSON-encoding binary payloads."""
    if set(left) != set(right):
        return False
    for group in ('package', 'kiosk', 'tv'):
        if not isinstance(left.get(group), dict) or set(left[group]) != set(right[group]):
            return False
        for name, payload in left[group].items():
            if not isinstance(payload, bytes) or right[group][name] != payload:
                return False
    return True


def page_wrapper_name(metadata):
    """Explicit per-target wrapper inside one shared package catalog."""
    # Keep the immutable catalog path comfortably below the Windows legacy
    # MAX_PATH limit while still binding the wrapper to the full metadata hash
    # that is verified from the file bytes on every lookup.
    return 'page-' + sha(encode(metadata))[:40] + '.json'


def page_catalog(state, metadata):
    """Resolve one exact reviewed variant without guessing a publication ID.

    Two platforms can share identical data-only package bytes and therefore the
    same canonical ``package_id`` while their signed target metadata differs by
    destination or projection. Keep the package immutable and shared, and retain
    every exact wrapper under a metadata-derived name. ``delivery.json`` remains
    for the accepted v1 catalog and as a legacy single-variant wrapper.
    """
    from kiosk.publication import authority
    publication = authority.validate_page_metadata(metadata)
    root = state.root / 'publications' / publication['package_id']
    raw = encode(metadata)
    for name in (page_wrapper_name(metadata), 'delivery.json'):
        path = root / name
        try:
            if path.read_bytes() == raw:
                return root
        except OSError:
            continue
    raise DeliveryError('publication_integrity', 503)


def page_variant(state, package_id, metadata_hash):
    """Load the exact wrapper named by an authenticated assignment row."""
    digest(package_id)
    digest(metadata_hash)
    root = state.root / 'publications' / package_id
    for name in ('page-' + metadata_hash[:40] + '.json', 'delivery.json'):
        path = root / name
        try:
            raw = path.read_bytes()
        except OSError:
            continue
        if sha(raw) == metadata_hash:
            return root, decode(raw)
    raise DeliveryError('publication_integrity', 503)


def _write_wrapper(path, raw):
    """Content-addressed wrapper creation with no rename window.

    The wrapper name already encodes the exact target metadata, so an existing
    file can only be the same bytes. Exclusive create keeps concurrent previews
    and retries from replacing a reviewed variant in place.
    """
    try:
        with path.open('xb') as outgoing:
            outgoing.write(raw)
            outgoing.flush()
            os.fsync(outgoing.fileno())
    except FileExistsError:
        pass
    if path.read_bytes() != raw:
        raise DeliveryError('publication_identity_conflict', 409)


def publish_page(state, metadata, files):
    """Immutable per-target v2 catalog write; assignment pointers stay untouched."""
    from kiosk.publication import authority, page_release
    publication = authority.validate_page_metadata(metadata)
    page_release.verify_inventory(publication, files)
    with state.connection() as db:
        return _publish_page(state, metadata, files, db)


def _publish_page(state, metadata, files, db):
    from kiosk.publication import authority, page_release
    publication = authority.validate_page_metadata(metadata)
    page_release.verify_inventory(publication, files)
    identity = publication['package_id']
    root = state.root / 'publications'
    root.mkdir(exist_ok=True)
    target = root / identity
    raw = encode(metadata)
    wrapper = target / page_wrapper_name(metadata)
    if target.exists():
        retained = _page_tree(target, publication)
        if not _same_tree(retained, files):
            raise DeliveryError('publication_integrity', 503)
        legacy = target / 'delivery.json'
        try:
            legacy_raw = legacy.read_bytes()
        except OSError:
            legacy_raw = None
        if legacy_raw is None:
            raise DeliveryError('publication_integrity', 503)
        # ``delivery.json`` stays the accepted v1/first variant. Every v4
        # variant lives under its metadata-derived name so two platforms that
        # share data-only package bytes keep distinct signed wrappers.
        _write_wrapper(wrapper, raw)
        if wrapper.read_bytes() != raw:
            raise DeliveryError('publication_integrity', 503)
        return metadata
    stage = Path(tempfile.mkdtemp(prefix='.page-', dir=root))
    try:
        package = stage / 'package'
        package.mkdir()
        for name, payload in sorted(files['package'].items()):
            destination = package / name
            destination.parent.mkdir(parents=True, exist_ok=True)
            with destination.open('xb') as outgoing:
                outgoing.write(payload)
                outgoing.flush()
                os.fsync(outgoing.fileno())
        staged = _page_tree(stage, publication)
        if not _same_tree(staged, files):
            raise DeliveryError('source_changed', 409)
        (stage / 'delivery.json').write_bytes(raw)
        (stage / page_wrapper_name(metadata)).write_bytes(raw)
        if target.exists():
            retained = _page_tree(target, publication)
            if not _same_tree(retained, files):
                raise DeliveryError('publication_identity_conflict', 409)
            existing = target / page_wrapper_name(metadata)
            if existing.exists():
                if existing.read_bytes() != raw:
                    raise DeliveryError('publication_identity_conflict', 409)
            else:
                _write_wrapper(existing, raw)
            return metadata
        stage.rename(target)
        stage = None
        if not _same_tree(_page_tree(target, publication), files):
            raise DeliveryError('publication_integrity', 503)
        return metadata
    finally:
        if stage is not None:
            shutil.rmtree(stage, ignore_errors=True)


def _publish(state, source, db):
    source = Path(source)
    manifest = verify_package(source)
    identity = sha(_json(manifest))
    root = state.root / 'publications'
    root.mkdir(exist_ok=True)
    target = root / identity
    # Reusing an immutable identity still revalidates its retained inventories.
    if target.exists():
        payload = (target / 'delivery.json').read_bytes()
        previous = db.execute('SELECT metadata_hash FROM assignment_history WHERE package_id=? LIMIT 1', (identity,)).fetchone()
        if previous and sha(payload) != previous['metadata_hash']:
            raise DeliveryError('publication_integrity', 503)
        metadata = decode(payload)
        if metadata['package_id'] != identity or not renderer_compatible(metadata['renderer']['build_id']):
            raise DeliveryError('publication_identity_conflict', 409)
        for group in ('package', 'kiosk', 'tv'):
            if inventory(target / group) != metadata[group]['files']:
                raise DeliveryError('publication_integrity', 503)
        if sha(_json(verify_package(target / 'package'))) != identity:
            raise DeliveryError('publication_integrity', 503)
        return metadata
    stage = Path(tempfile.mkdtemp(prefix='.delivery-', dir=root))
    try:
        package = stage / 'package'
        package.mkdir()
        raw_manifest = (source / 'manifest.json').read_bytes()
        manifest_entry = {'path': 'manifest.json', 'size': len(raw_manifest), 'sha256': sha(raw_manifest)}
        for entry in [manifest_entry, *manifest['files']]:
            destination = package / entry['path']
            destination.parent.mkdir(parents=True, exist_ok=True)
            with destination.open('xb') as outgoing:
                size, witness = _stream_stable(source, entry['path'], _ExpectedFileWriter(outgoing, entry['size']))
                if size != entry['size'] or witness[3] != entry['sha256']:
                    raise DeliveryError('source_changed', 409)
                outgoing.flush()
                os.fsync(outgoing.fileno())
        verify_package(package)
        if sha(_json(verify_package(package))) != identity:
            raise DeliveryError('source_changed', 409)
        for mode in ('kiosk', 'tv'):
            build_view(package, stage / mode, mode=mode)
        data = decode((package / 'data/events.json').read_bytes())
        images = {}
        for name in sorted({value[1:] for value in _references(data)} | {'resources/static/img/site_icon.png'}):
            path = _plain_path(package, name)
            with Image.open(path) as image:
                width, height = image.size
                if image.format not in ('PNG', 'JPEG') or getattr(image, 'n_frames', 1) != 1:
                    raise DeliveryError('unsupported_media', 409)
                if width * height > LIMITS['max_pixels'] or path.stat().st_size + width * height * 8 > LIMITS['max_live_bytes']:
                    raise DeliveryError('unsupported_resource_profile', 409)
                image.verify()
            images[name] = {'sha256': _stream_stable(package, name)[1][3], 'result': 'VERIFIED'}
        metadata = {
            'version': 1, 'package_id': identity, 'revision': manifest['revision'],
            'raw_manifest_sha256': sha((package / 'manifest.json').read_bytes()),
            'renderer': {'build_id': renderer_identity(),
                         'js_sha256': sha((ASSETS / 'events.js').read_bytes()),
                         'css_sha256': sha((ASSETS / 'events.css').read_bytes())},
            'resource_profile': PROFILE, 'limits': LIMITS,
            'windows_images': images,
        }
        for group in ('package', 'kiosk', 'tv'):
            metadata[group] = {'files': inventory(stage / group)}
        size = sum(item['size'] for group in ('package', 'kiosk', 'tv') for item in metadata[group]['files'])
        payload = encode(metadata)
        if size > MAX_PUBLICATION_BYTES or len(payload) > MAX_METADATA_BYTES:
            raise DeliveryError('publication_limit', 413)
        # Retained active/recovery/staging artifacts count; never delete an old package for room.
        retained = sum(path.stat().st_size for path in root.rglob('*') if path.is_file())
        if retained + len(payload) > MAX_CATALOG_BYTES or shutil.disk_usage(root).free < LIMITS['min_free_bytes']:
            raise DeliveryError('catalog_full', 507)
        with (stage / 'delivery.json').open('xb') as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        stage.rename(target)
        stage = None
        return metadata
    finally:
        if stage is not None:
            shutil.rmtree(stage)
