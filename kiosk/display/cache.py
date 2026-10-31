"""Bounded, restart-safe reuse of locally generated renderer artifacts."""
import hashlib
import json
import os
from pathlib import Path

from kiosk.publication.exporter import PackageError, _is_link, _json, _plain_path, _stream_stable, verify_package
from kiosk.publication import renderer
from kiosk.publication.store import PublicationStore, POINTER_RESERVE_BYTES

DEFAULT_CACHE_BYTES = 256 * 1024 * 1024


def renderer_identity():
    """Invalidate generated artifacts when shipped code, templates or labels change."""
    files = [Path(renderer.__file__), *sorted(renderer.ASSETS.glob('*')),
             *(renderer.TRANSLATIONS / (language + '.json') for language in ('en', 'ru', 'de'))]
    return hashlib.sha256(_json([hashlib.sha256(path.read_bytes()).hexdigest()
                                 for path in files if path.is_file()])).hexdigest()


def verify_cached_view(root, *, package_identity, mode):
    """Rehash every artifact on reuse; do not repair or overwrite a damaged view."""
    try:
        root = Path(root).absolute()
        path = _plain_path(root, 'view.json')
        with path.open('rb') as stream:
            payload = stream.read(2 * 1024 * 1024 + 1)
        if len(payload) > 2 * 1024 * 1024:
            raise PackageError('invalid_cached_view')
        descriptor = json.loads(payload)
        if (not isinstance(descriptor, dict) or type(descriptor.get('schema_version')) is not int or
                descriptor['schema_version'] != 1 or descriptor.get('renderer') != 'events-v1' or
                descriptor.get('package_sha256') != package_identity or descriptor.get('mode') != mode):
            raise PackageError('invalid_cached_view')
        files = descriptor.get('files')
        if not isinstance(files, list) or not 3 <= len(files) <= 10000:
            raise PackageError('invalid_cached_view')
        names = set()
        for entry in files:
            if not isinstance(entry, dict) or set(entry) != {'path', 'size', 'sha256'}:
                raise PackageError('invalid_cached_view')
            name = entry['path']
            if (not isinstance(name, str) or name in names or
                    (name not in ('index.html', 'events.js', 'events.css') and not name.startswith('static/uploads/')) or
                    type(entry['size']) is not int or entry['size'] < 0):
                raise PackageError('invalid_cached_view')
            size, witness = _stream_stable(root, name)
            if size != entry['size'] or witness[3] != entry['sha256']:
                raise PackageError('cached_view_integrity')
            if name in ('events.js', 'events.css') and witness[3] != hashlib.sha256((renderer.ASSETS / name).read_bytes()).hexdigest():
                raise PackageError('cached_renderer_mismatch')
            names.add(name)
        if not {'index.html', 'events.js', 'events.css'} <= names:
            raise PackageError('invalid_cached_view')
        actual = set()
        for parent, directories, filenames in os.walk(root, followlinks=False):
            for name in directories:
                if _is_link((Path(parent) / name).lstat()):
                    raise PackageError('unsafe_source')
            for name in filenames:
                relative = (Path(parent) / name).relative_to(root).as_posix()
                _plain_path(root, relative)
            actual.update((Path(parent) / name).relative_to(root).as_posix() for name in filenames)
        if actual != names | {'view.json'}:
            raise PackageError('invalid_cached_view')
        return root / 'index.html'
    except PackageError:
        raise
    except (OSError, ValueError, KeyError, TypeError, RecursionError):
        raise PackageError('invalid_cached_view') from None


def prepare_cached_view(store_root, cache_root, *, mode='kiosk', max_bytes=DEFAULT_CACHE_BYTES):
    """Resolve the authoritative publication each start; cache has no active pointer."""
    if mode not in ('kiosk', 'tv'):
        raise PackageError('unsupported_display_mode')
    package = PublicationStore(store_root).active()
    if package is None:
        raise PackageError('no_publication')
    return prepare_package_view(package, cache_root, mode=mode, max_bytes=max_bytes)


def prepare_package_view(package, cache_root, *, mode='kiosk', max_bytes=DEFAULT_CACHE_BYTES):
    """Prepare a verified immutable candidate without reading any active pointer."""
    if mode not in ('kiosk', 'tv'):
        raise PackageError('unsupported_display_mode')
    package_identity = hashlib.sha256(_json(verify_package(package))).hexdigest()
    key = hashlib.sha256(_json([package_identity, mode, renderer_identity()])).hexdigest()
    # Reuse the Windows writer lease and reparse-aware accounting for a separate cache root.
    guard = PublicationStore(cache_root, max_bytes=max_bytes)
    try:
        with guard._lease():
            destination = guard.root / key
            usage = guard._usage()
            if usage + POINTER_RESERVE_BYTES > max_bytes:
                raise PackageError('view_cache_limit')
            if destination.exists():
                return verify_cached_view(destination, package_identity=package_identity, mode=mode)
            available = max_bytes - usage - POINTER_RESERVE_BYTES
            if available <= 0:
                raise PackageError('view_cache_limit')
            renderer.build_view(package, destination, mode=mode, max_bytes=min(available, 128 * 1024 * 1024))
            return verify_cached_view(destination, package_identity=package_identity, mode=mode)
    except PackageError:
        raise
    except (OSError, ValueError):
        raise PackageError('view_cache_failed') from None
