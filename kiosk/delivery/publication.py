"""Prepare immutable transport artifacts using the existing Windows verifier/renderer."""
import os
from pathlib import Path
import shutil
import tempfile

from PIL import Image

from kiosk.display.cache import renderer_identity
from kiosk.publication.exporter import _json, _plain_path, _references, _stream_stable, verify_package
from kiosk.publication.renderer import ASSETS, build_view
from kiosk.publication.store import _ExpectedFileWriter
from .protocol import DeliveryError, LIMITS, MAX_METADATA_BYTES, PROFILE, decode, encode, sha

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
        if metadata['package_id'] != identity or metadata['renderer']['build_id'] != renderer_identity():
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
