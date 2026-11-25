"""Build and verify a local pages-v1 view from pinned assets and a data-only package.

The renderer code is always the shipped canonical ``page_display.js/css``; the
verified data-only package contributes only immutable data. Packages never add
HTML, scripts, styles or templates. The view descriptor is the local pointer that
the native shell rehashes before every activation.
"""
import json
import os
from pathlib import Path
import shutil
import tempfile

from kiosk.delivery.protocol import decode, encode, sha
from kiosk.publication import authority, page_release
from kiosk.publication.exporter import PackageError, _is_link, _json, _plain_path
from kiosk.publication.store import (
    DEFAULT_STORE_BYTES, POINTER_RESERVE_BYTES, PublicationStore, _atomic_write, _directory)

PAGE_RENDERER_NAME = 'pages-v1'
PAGE_BOOTSTRAP = 'page_bootstrap.js'
# Canonical cross-platform LF bytes. A CRLF checkout must fail closed instead of
# deriving a different renderer identity from platform-dependent line endings.
PAGE_JS_SHA256 = '3528358ae2bb2f8a85d2c5f58fed6ba8b1c98ea37d842931460657e6f063e20d'
PAGE_CSS_SHA256 = 'd3fd8af903cacb3e5e5d33df69663002bfb3a9157f432997e448c8d8266a54cf'
PAGE_ASSETS = Path(__file__).resolve().parents[1] / 'static'
PAGE_JS = PAGE_ASSETS / 'js/page_display.js'
PAGE_CSS = PAGE_ASSETS / 'css/page_display.css'
MAX_VIEW_BYTES = 128 * 1024 * 1024
DESCRIPTOR_RESERVE_BYTES = 2 * 1024 * 1024


def _asset_bytes(path):
    try:
        return path.read_bytes()
    except OSError:
        raise PackageError('page_renderer_assets_missing') from None


def renderer_pin():
    """Exact local page-renderer asset hashes; never derived from a response."""
    js = sha(_asset_bytes(PAGE_JS))
    css = sha(_asset_bytes(PAGE_CSS))
    if js != PAGE_JS_SHA256 or css != PAGE_CSS_SHA256:
        raise PackageError('page_renderer_asset_pin')
    return {'js_sha256': js, 'css_sha256': css,
            'build_id': authority.page_renderer_build_id(js, css)}


def page_renderer_identity():
    return renderer_pin()['build_id']


def view_kind(view):
    """Read the renderer kind from a prepared view descriptor."""
    descriptor = json.loads(_plain_path(Path(view).parent, 'view.json').read_bytes())
    renderer = descriptor.get('renderer') if isinstance(descriptor, dict) else None
    if renderer == PAGE_RENDERER_NAME:
        return 'pages'
    if renderer == 'events-v1':
        return 'events'
    raise PackageError('invalid_cached_view')


def read_package_tree(directory):
    """Read a closed package tree as exact bytes, rejecting links and extras."""
    root = Path(directory).absolute()
    files = {}
    total = 0
    for parent, directories, names in os.walk(root, followlinks=False):
        for name in directories:
            if _is_link((Path(parent) / name).lstat()):
                raise PackageError('unsafe_package_tree')
        for name in names:
            item = Path(parent) / name
            if _is_link(item.lstat()):
                raise PackageError('unsafe_package_tree')
            relative = item.relative_to(root).as_posix()
            payload = _plain_path(root, relative).read_bytes()
            total += len(payload)
            if total > authority.MAX_PAGE_METADATA_BYTES + authority.MAX_METADATA_BYTES:
                raise PackageError('page_package_limit')
            files[relative] = payload
    return files


def verify_page_package(directory, metadata):
    """Verify the data-only package against its signed target metadata."""
    publication = authority.validate_page_metadata(metadata)
    files = read_package_tree(directory)
    page_release.verify_inventory(publication, {'package': files, 'kiosk': {}, 'tv': {}})
    manifest = decode(files['manifest.json'])
    content = files[page_release.PAGE_ENTRYPOINT]
    return manifest, content, files


def _escape_json_bytes(payload):
    # Valid JSON that cannot terminate the surrounding <script> element.
    return payload.replace(b'<', b'\\u003c')


def _bootstrap_source():
    return (
        '(() => {\n'
        '  "use strict";\n'
        '  function read(id) {\n'
        '    const node = document.getElementById(id);\n'
        '    return node ? JSON.parse(node.textContent) : null;\n'
        '  }\n'
        '  function boot() {\n'
        '    try {\n'
        '      const data = read("kiosk-page-data");\n'
        '      const media = read("kiosk-media") || {};\n'
        '      if (!window.KioskPageDisplay || !data || !data.page) { throw new Error("renderer"); }\n'
        '      window.KioskPageDisplay.mount(document.getElementById("kiosk-page"), {\n'
        '        page: data.page, events: data.events, tags: data.tags, media: media,\n'
        '        mode: document.documentElement.getAttribute("data-mode")\n'
        '      });\n'
        '      document.body.setAttribute("data-kiosk-ready", "1");\n'
        '    } catch (error) {\n'
        '      document.body.setAttribute("data-kiosk-failed", "1");\n'
        '    }\n'
        '  }\n'
        '  if (document.readyState === "loading") {\n'
        '    document.addEventListener("DOMContentLoaded", boot);\n'
        '  } else { boot(); }\n'
        '})();\n').encode('utf-8')


def _index_html(mode, content_bytes, media):
    data = _escape_json_bytes(content_bytes)
    media_bytes = _escape_json_bytes(_json(media))
    return (b'<!doctype html>\n<html lang="en" data-mode="' + mode.encode('ascii') + b'">\n'
            b'<head>\n<meta charset="utf-8">\n'
            b'<meta http-equiv="Content-Security-Policy" content="default-src \'none\'; '
            b'script-src \'self\'; style-src \'self\'; img-src \'self\'; connect-src \'none\'; '
            b'object-src \'none\'; base-uri \'none\'; form-action \'none\'">\n'
            b'<meta name="viewport" content="width=device-width, initial-scale=1">\n'
            b'<title>Kiosk</title>\n'
            b'<link rel="stylesheet" href="page_display.css">\n'
            b'<script src="page_display.js" defer></script>\n'
            b'<script src="page_bootstrap.js" defer></script>\n'
            b'</head>\n<body>\n<main id="kiosk-page"></main>\n'
            b'<script type="application/json" id="kiosk-page-data">' + data + b'</script>\n'
            b'<script type="application/json" id="kiosk-media">' + media_bytes + b'</script>\n'
            b'</body>\n</html>\n')


def build_page_view(package, destination, *, mode, max_bytes=MAX_VIEW_BYTES, metadata=None):
    """Build a new pages-v1 view; never executes or copies package code."""
    if mode not in ('tv', 'kiosk'):
        raise PackageError('unsupported_display_mode')
    if type(max_bytes) is not int or max_bytes <= 0:
        raise ValueError('Invalid view bound')
    destination = Path(destination).absolute()
    staging = None
    try:
        if destination.exists() or destination.is_symlink():
            raise PackageError('destination_exists')
        if metadata is None:
            raise PackageError('page_target_metadata_required')
        manifest, content_bytes, files = verify_page_package(package, metadata)
        content = decode(content_bytes)
        page = content.get('page') if isinstance(content, dict) else None
        target = page.get('target') if isinstance(page, dict) else None
        if not isinstance(target, str) or target.split('-', 1)[0] != mode:
            raise PackageError('page_view_mode')
        media = {'/' + name: name for name in files if name.startswith('static/uploads/')}
        assets = {'page_display.js': _asset_bytes(PAGE_JS),
                  'page_display.css': _asset_bytes(PAGE_CSS),
                  PAGE_BOOTSTRAP: _bootstrap_source()}
        html_bytes = _index_html(mode, content_bytes, media)
        needed = sum(map(len, files.values())) + sum(map(len, assets.values()))
        if needed + len(html_bytes) + DESCRIPTOR_RESERVE_BYTES > max_bytes:
            raise PackageError('view_limit')
        _directory(destination.parent)
        if shutil.disk_usage(destination.parent).free < needed + len(html_bytes) + DESCRIPTOR_RESERVE_BYTES:
            raise PackageError('view_disk_full')
        staging = Path(tempfile.mkdtemp(prefix='.pages-view-', dir=destination.parent))
        for name, payload in files.items():
            if name in ('manifest.json', page_release.PAGE_ENTRYPOINT):
                continue
            target_path = staging / name
            target_path.parent.mkdir(parents=True, exist_ok=True)
            target_path.write_bytes(payload)
        for name, payload in assets.items():
            (staging / name).write_bytes(payload)
        (staging / 'index.html').write_bytes(html_bytes)
        inventory = []
        for path in sorted(staging.rglob('*')):
            if path.is_file():
                name = path.relative_to(staging).as_posix()
                payload = path.read_bytes()
                inventory.append({'path': name, 'size': len(payload), 'sha256': sha(payload)})
        descriptor = _json({'schema_version': 1, 'revision': manifest['revision'],
                            'renderer': PAGE_RENDERER_NAME, 'mode': mode,
                            'files': inventory, 'package_sha256': sha(encode(manifest))})
        if len(descriptor) > DESCRIPTOR_RESERVE_BYTES:
            raise PackageError('view_limit')
        (staging / 'view.json').write_bytes(descriptor)
        staging.rename(destination)
        staging = None
        return destination / 'index.html'
    except PackageError:
        raise
    except (OSError, ValueError, KeyError, TypeError, RecursionError):
        raise PackageError('page_view_failed') from None
    finally:
        if staging is not None:
            shutil.rmtree(staging, ignore_errors=True)


def verify_page_view(root, *, package_identity, mode):
    """Rehash every pages-v1 view artifact before activation or reuse."""
    try:
        root = Path(root).absolute()
        payload = _plain_path(root, 'view.json').read_bytes()
        if len(payload) > DESCRIPTOR_RESERVE_BYTES:
            raise PackageError('invalid_cached_view')
        descriptor = json.loads(payload)
        if (not isinstance(descriptor, dict) or type(descriptor.get('schema_version')) is not int
                or descriptor['schema_version'] != 1
                or descriptor.get('renderer') != PAGE_RENDERER_NAME
                or descriptor.get('package_sha256') != package_identity
                or descriptor.get('mode') != mode):
            raise PackageError('invalid_cached_view')
        files = descriptor.get('files')
        if not isinstance(files, list) or not 4 <= len(files) <= 10004:
            raise PackageError('invalid_cached_view')
        names = set()
        pin = renderer_pin()
        for entry in files:
            if not isinstance(entry, dict) or set(entry) != {'path', 'size', 'sha256'}:
                raise PackageError('invalid_cached_view')
            name = entry['path']
            if (not isinstance(name, str) or name in names or
                    type(entry['size']) is not int or entry['size'] < 0):
                raise PackageError('invalid_cached_view')
            actual = _plain_path(root, name).read_bytes()
            if len(actual) != entry['size'] or sha(actual) != entry['sha256']:
                raise PackageError('cached_view_integrity')
            if name == 'page_display.js' and sha(actual) != pin['js_sha256']:
                raise PackageError('cached_renderer_mismatch')
            if name == 'page_display.css' and sha(actual) != pin['css_sha256']:
                raise PackageError('cached_renderer_mismatch')
            if not (name in ('index.html', 'page_display.js', 'page_display.css', PAGE_BOOTSTRAP)
                    or name.startswith('static/uploads/')):
                raise PackageError('invalid_cached_view')
            names.add(name)
        required = {'index.html', 'page_display.js', 'page_display.css', PAGE_BOOTSTRAP}
        if not required <= names:
            raise PackageError('invalid_cached_view')
        actual = set()
        for parent, directories, filenames in os.walk(root, followlinks=False):
            for name in directories:
                if _is_link((Path(parent) / name).lstat()):
                    raise PackageError('cached_view_integrity')
            for name in filenames:
                relative = (Path(parent) / name).relative_to(root).as_posix()
                _plain_path(root, relative)
                actual.add(relative)
        if actual != names | {'view.json'}:
            raise PackageError('invalid_cached_view')
        return root / 'index.html'
    except PackageError:
        raise
    except (OSError, ValueError, KeyError, TypeError, RecursionError):
        raise PackageError('invalid_cached_view') from None


def _view_key(package_id, mode):
    return sha(encode([package_id, mode, page_renderer_identity()]))


def _page_root(store_root):
    return Path(store_root).absolute() / 'pages'


def _read_pointer(store_root):
    path = _page_root(store_root) / 'active.json'
    if not path.exists():
        return None
    pointer = json.loads(_plain_path(_page_root(store_root), 'active.json').read_bytes())
    if (not isinstance(pointer, dict) or set(pointer) != {'schema_version', 'current', 'previous'}
            or type(pointer['schema_version']) is not int or pointer['schema_version'] != 1):
        raise PackageError('invalid_page_pointer')
    for name in ('current', 'previous'):
        value = pointer[name]
        if value is None and name == 'previous':
            continue
        if not isinstance(value, str) or len(value) != 64 or any(c not in '0123456789abcdef' for c in value):
            raise PackageError('invalid_page_pointer')
    return pointer


def active_kind(store_root):
    root = Path(store_root).absolute()
    path = root / 'active-kind.json'
    if not path.exists():
        return 'events'
    try:
        value = json.loads(_plain_path(root, 'active-kind.json').read_bytes())
        if (not isinstance(value, dict) or set(value) != {'schema_version', 'kind', 'package_id'}
                or value['schema_version'] != 1 or value['kind'] not in ('events', 'pages')):
            return 'events'
        return value['kind']
    except (OSError, ValueError, TypeError, PackageError):
        return 'events'


def set_active_kind(store_root, kind, package_id):
    _directory(Path(store_root).absolute())
    _atomic_write(Path(store_root).absolute() / 'active-kind.json',
                  _json({'schema_version': 1, 'kind': kind, 'package_id': package_id}))


def _metadata_path(store_root, package_id):
    return _page_root(store_root) / 'metadata' / (package_id + '.json')


def _page_revision(store_root, package_id):
    return _page_root(store_root) / 'revisions' / package_id


def active_page_package(store_root):
    """Verified active pages package id, or None when no valid pages pointer exists."""
    try:
        pointer = _read_pointer(store_root)
        if pointer is None:
            return None
        package_id = pointer['current']
        metadata = decode(_plain_path(_page_root(store_root) / 'metadata',
                                      package_id + '.json').read_bytes())
        verify_page_package(_page_revision(store_root, package_id), metadata)
        return package_id
    except (PackageError, OSError, ValueError, KeyError, TypeError):
        return None


def prepare_cached_page_view(store_root, cache_root, *, mode='tv', max_bytes=DEFAULT_STORE_BYTES):
    """Resolve, verify or build the active pages view; never trust a cached pointer."""
    if mode not in ('tv', 'kiosk'):
        raise PackageError('unsupported_display_mode')
    package_id = active_page_package(store_root)
    if package_id is None:
        raise PackageError('no_page_publication')
    metadata = decode(_plain_path(_page_root(store_root) / 'metadata',
                                  package_id + '.json').read_bytes())
    revision = _page_revision(store_root, package_id)
    verify_page_package(revision, metadata)
    return _prepare_page_view(store_root, cache_root, package_id, metadata, revision,
                              mode=mode, max_bytes=max_bytes)


def _prepare_page_view(store_root, cache_root, package_id, metadata, revision, *, mode,
                       max_bytes=DEFAULT_STORE_BYTES):
    """Build or re-verify one exact package view without reading the active pointer."""
    cache_root = Path(cache_root).absolute()
    key = _view_key(package_id, mode)
    guard = PublicationStore(cache_root, max_bytes=max_bytes)
    try:
        with guard._lease():
            destination = cache_root / 'pages' / key
            usage = guard._usage()
            if usage + POINTER_RESERVE_BYTES > max_bytes:
                raise PackageError('view_cache_limit')
            if destination.exists():
                return verify_page_view(destination, package_identity=package_id, mode=mode)
            available = max_bytes - usage - POINTER_RESERVE_BYTES
            if available <= 0:
                raise PackageError('view_cache_limit')
            build_page_view(revision, destination, mode=mode,
                            max_bytes=min(available, MAX_VIEW_BYTES), metadata=metadata)
            return verify_page_view(destination, package_identity=package_id, mode=mode)
    except PackageError:
        raise
    except (OSError, ValueError):
        raise PackageError('page_view_failed') from None


def install_page_for_display(source, metadata, store_root, cache_root, *, mode,
                             max_bytes=DEFAULT_STORE_BYTES):
    """Install the verified package and prepare its view before switching the pointer."""
    store_root = Path(store_root).absolute()
    cache_root = Path(cache_root).absolute()
    if store_root == cache_root or store_root in cache_root.parents or cache_root in store_root.parents:
        raise PackageError('overlapping_display_storage')
    manifest, content, files = verify_page_package(source, metadata)
    package_id = sha(encode(manifest))
    if package_id != metadata['publication']['package_id']:
        raise PackageError('page_package_identity')
    staging = None
    try:
        with PublicationStore(store_root)._lease():
            pages = _directory(_page_root(store_root))
            revisions = _directory(pages / 'revisions')
            _directory(pages / 'metadata')
            destination = revisions / package_id
            previous = _read_pointer(store_root)
            if destination.exists():
                verify_page_package(destination, metadata)
            else:
                store = PublicationStore(store_root)
                needed = sum(len(payload) for payload in files.values())
                if store._usage() + needed + POINTER_RESERVE_BYTES > store.max_bytes:
                    raise PackageError('store_limit')
                if shutil.disk_usage(store_root).free < needed + POINTER_RESERVE_BYTES:
                    raise PackageError('store_disk_full')
                staging = Path(tempfile.mkdtemp(prefix='.pages-incoming-', dir=store_root))
                for name, payload in files.items():
                    target = staging / name
                    target.parent.mkdir(parents=True, exist_ok=True)
                    target.write_bytes(payload)
                staging.rename(destination)
                staging = None
            _atomic_write(_metadata_path(store_root, package_id), encode(metadata))
            view = _prepare_page_view(store_root, cache_root, package_id, metadata, destination,
                                      mode=mode, max_bytes=max_bytes)
            pointer = {'schema_version': 1, 'current': package_id,
                       'previous': previous['current'] if previous else None}
            _atomic_write(pages / 'active.json', _json(pointer))
            set_active_kind(store_root, 'pages', package_id)
            return view
    except PackageError:
        raise
    except (OSError, ValueError, KeyError, TypeError):
        raise PackageError('page_store_failed') from None
    finally:
        if staging is not None:
            shutil.rmtree(staging, ignore_errors=True)
