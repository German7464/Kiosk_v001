"""Isolated Events export. No client activation or network access."""
from contextlib import closing
import hashlib
import json
import io
import os
from pathlib import Path
import re
import shutil
import sqlite3
import stat
import tempfile

from PIL import Image

from . import validate_manifest
from .compatibility import EVENTS_RUNTIME

MAX_FILE_BYTES = 256 * 1024 * 1024
MAX_PACKAGE_BYTES = 64 * 1024 * 1024
COPY_BLOCK_BYTES = 256 * 1024
SETTINGS = ('site_title', 'interface_language', 'site_icon', 'tv_slide_duration',
            'kiosk_label', 'kiosk_heading', 'kiosk_description')
RESOURCES = (
    'static/css/base.css', 'static/js/kiosk_home.js', 'static/js/kiosk_events.js',
    'static/js/tv.js', 'static/js/admin_flash.js', 'static/img/site_icon.png',
    'templates/base.html', 'templates/kiosk_home.html', 'templates/kiosk_events.html',
    'templates/tv.html', 'translations/en.json', 'translations/ru.json', 'translations/de.json',
)
EVENT_FIELDS = ('id', 'title', 'short_description', 'full_description', 'event_date',
                'place', 'image_kiosk', 'image_tv', 'image_thumb', 'sort_order')


class PackageError(ValueError):
    """Safe diagnostic code; never contains source paths or source data."""


def _json(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode('utf-8')


def _path_name(name):
    try:
        validate_manifest({'schema_version': 1, 'revision': 'validation', 'renderer': 'events-v1',
                           'files': [{'path': name, 'size': 0, 'sha256': '0' * 64}]})
    except (ValueError, TypeError):
        raise PackageError('unsafe_path') from None
    return name


def _plain_path(root, name):
    _path_name(name)
    root = Path(root).absolute()
    # Reject reparse points even when they happen to resolve within the root.
    for path in (root, *root.parents):
        if path.exists() and _is_link(path.lstat()):
            raise PackageError('unsafe_source')
    path = root
    for part in name.split('/'):
        path = path / part
        info = path.lstat()
        if _is_link(info):
            raise PackageError('unsafe_source')
    if not stat.S_ISREG(info.st_mode):
        raise PackageError('not_regular_file')
    return path


def _is_link(info):
    return stat.S_ISLNK(info.st_mode) or bool(getattr(info, 'st_file_attributes', 0) & 0x400)


def _signature(info):
    return info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns


def _stream_stable(root, name, output=None):
    path = _plain_path(root, name)
    before = path.lstat()
    if before.st_size > MAX_FILE_BYTES:
        raise PackageError('file_too_large')
    digest = hashlib.sha256()
    size = 0
    with path.open('rb') as source:
        if _signature(os.fstat(source.fileno())) != _signature(before):
            raise PackageError('source_changed')
        while block := source.read(COPY_BLOCK_BYTES):
            size += len(block)
            if size > MAX_FILE_BYTES or size > before.st_size:
                raise PackageError('source_changed')
            digest.update(block)
            if output is not None:
                output.write(block)
        after = os.fstat(source.fileno())
    if size != before.st_size or _signature(before) != _signature(after) or _signature(before) != _signature(path.lstat()):
        raise PackageError('source_changed')
    return size, (root, name, _signature(after), digest.hexdigest())


def _read_stable(root, name):
    output = io.BytesIO()
    _, witness = _stream_stable(root, name, output)
    return output.getvalue(), witness


def _snapshot(database_path):
    with closing(sqlite3.connect(Path(database_path).resolve().as_uri() + '?mode=ro', uri=True)) as db:
        db.row_factory = sqlite3.Row
        db.execute('BEGIN')
        settings = {row['key']: row['value'] for row in db.execute(
            'SELECT key,value FROM settings WHERE key IN (' + ','.join('?' for _ in SETTINGS) + ')', SETTINGS)}
        version = db.execute("SELECT value FROM settings WHERE key='content_version'").fetchone()
        if version is None or not str(version[0]).isdigit() or int(version[0]) < 1:
            raise PackageError('invalid_content_version')
        events = [dict(row) for row in db.execute('SELECT ' + ','.join(EVENT_FIELDS) +
                    " FROM events WHERE status='active' ORDER BY sort_order,event_date,id")]
        tags = [dict(row) for row in db.execute('SELECT id,name FROM tags ORDER BY name,id')]
        known_tags = {row['id'] for row in tags}
        links = db.execute("SELECT event_tags.event_id,event_tags.tag_id FROM event_tags JOIN events ON events.id=event_tags.event_id WHERE events.status='active'").fetchall()
        by_event = {event['id']: [] for event in events}
        for link in links:
            if link['tag_id'] not in known_tags:
                raise PackageError('missing_tag')
            by_event[link['event_id']].append(link['tag_id'])
        for event in events:
            event['tag_ids'] = sorted(by_event[event['id']])
        return {'content_version': int(version[0]), 'events': events, 'tags': tags, 'settings': settings}


def _validate_data(data):
    if not isinstance(data, dict) or set(data) != {'content_version', 'events', 'tags', 'settings'}:
        raise PackageError('invalid_public_data')
    if type(data['content_version']) is not int or data['content_version'] < 1:
        raise PackageError('invalid_public_data')
    if not isinstance(data['settings'], dict) or set(data['settings']) - set(SETTINGS) or not all(isinstance(v, str) for v in data['settings'].values()):
        raise PackageError('invalid_public_data')
    if not isinstance(data['events'], list) or not isinstance(data['tags'], list):
        raise PackageError('invalid_public_data')
    tags = set()
    for tag in data['tags']:
        if not isinstance(tag, dict) or set(tag) != {'id', 'name'} or type(tag['id']) is not int or tag['id'] < 1 or not isinstance(tag['name'], str) or tag['id'] in tags:
            raise PackageError('invalid_public_data')
        tags.add(tag['id'])
    events = set()
    for event in data['events']:
        if not isinstance(event, dict) or set(event) != set(EVENT_FIELDS) | {'tag_ids'}:
            raise PackageError('invalid_public_data')
        if type(event['id']) is not int or event['id'] < 1 or event['id'] in events or type(event['sort_order']) is not int:
            raise PackageError('invalid_public_data')
        events.add(event['id'])
        if not all(isinstance(event[field], str) for field in ('title', 'short_description', 'full_description', 'place')):
            raise PackageError('invalid_public_data')
        if not all(event[field] is None or isinstance(event[field], str) for field in ('event_date', 'image_kiosk', 'image_tv', 'image_thumb')):
            raise PackageError('invalid_public_data')
        links = event['tag_ids']
        if not isinstance(links, list) or any(type(link) is not int or link not in tags for link in links) or len(set(links)) != len(links):
            raise PackageError('invalid_public_data')


def _validate_image(payload):
    try:
        with Image.open(io.BytesIO(payload)) as image:
            image.verify()
    except (OSError, ValueError, SyntaxError, Image.DecompressionBombError):
        raise PackageError('invalid_image') from None


def _validate_image_path(path):
    try:
        with Image.open(path) as image:
            image.verify()
    except (OSError, ValueError, SyntaxError, Image.DecompressionBombError):
        raise PackageError('invalid_image') from None


def _references(data):
    references = set()
    for event in data['events']:
        for field in ('image_kiosk', 'image_tv', 'image_thumb'):
            value = event.get(field)
            if value:
                references.add(value)
    if data['settings'].get('site_icon'):
        references.add(data['settings']['site_icon'])
    for value in references:
        if not isinstance(value, str) or not value.startswith('/static/uploads/'):
            raise PackageError('unsupported_media_reference')
        _path_name(value[1:])
    return references


def _check_resources(payloads):
    # Current renderer has no CSS imports; refuse untracked future dependencies.
    for name, payload in payloads.items():
        if name == 'resources/static/img/site_icon.png':
            _validate_image(payload)
        if name.startswith('resources/translations/'):
            translations = json.loads(payload)
            if not isinstance(translations, dict) or not all(isinstance(k, str) and isinstance(v, str) for k, v in translations.items()):
                raise PackageError('invalid_translation_resource')
        if name.endswith('.css'):
            text = payload.decode('utf-8-sig')
            if re.search(r'@import|url\s*\(', text, re.I):
                raise PackageError('unsupported_css_dependency')
        if name.endswith('.js') and re.search(rb'\bimport\s*(?:\(|[\w*{])|\brequire\s*\(', payload):
            raise PackageError('unsupported_script_dependency')
        if name.startswith('resources/templates/'):
            for template in re.findall(r"{%\s*(?:extends|include)\s+['\"]([^'\"]+)['\"]", payload.decode('utf-8-sig')):
                if 'resources/templates/' + template not in payloads:
                    raise PackageError('missing_display_template')
            for dependency in re.findall(r"filename=['\"]([^'\"]+)['\"]", payload.decode('utf-8-sig')):
                if 'resources/static/' + dependency not in payloads:
                    raise PackageError('missing_display_resource')


def export_events_package(database_path, public_upload_dir, resource_dir, destination):
    """Export to a NEW directory. Existing destinations are never overwritten."""
    destination = Path(destination).absolute()
    parent = destination.parent
    staging = None
    try:
        if destination.exists() or destination.is_symlink():
            raise PackageError('destination_exists')
        if not parent.is_dir() or any(_is_link(p.lstat()) for p in (parent, *parent.parents)):
            raise PackageError('unsafe_destination')
        data = _snapshot(database_path)
        _validate_data(data)
        payloads = {'data/events.json': _json(data)}
        witnesses = []
        files = []
        total = len(payloads['data/events.json'])
        if total > MAX_PACKAGE_BYTES:
            raise PackageError('package_too_large')
        staging = Path(tempfile.mkdtemp(prefix='.events-export-', dir=parent))

        def copy_budgeted(root, name, target_name):
            nonlocal total
            size = _plain_path(root, name).stat().st_size
            if size > MAX_PACKAGE_BYTES - total:
                raise PackageError('package_too_large')
            target = staging / target_name
            target.parent.mkdir(parents=True, exist_ok=True)
            with target.open('xb') as output:
                size, witness = _stream_stable(root, name, output)
            total += size
            if total > MAX_PACKAGE_BYTES:
                raise PackageError('package_too_large')
            witnesses.append(witness)
            files.append({'path': target_name, 'size': size, 'sha256': witness[3]})
            return target

        for reference in sorted(_references(data)):
            target = copy_budgeted(public_upload_dir, reference.removeprefix('/static/uploads/'), reference[1:])
            _validate_image_path(target)
        for name in RESOURCES:
            copy_budgeted(resource_dir, name, 'resources/' + name)
            payloads['resources/' + name], _ = _read_stable(staging, 'resources/' + name)
        _check_resources(payloads)
        target = staging / 'data/events.json'
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(payloads['data/events.json'])
        files.append({'path': 'data/events.json', 'size': len(payloads['data/events.json']),
                      'sha256': hashlib.sha256(payloads['data/events.json']).hexdigest()})
        manifest = {'schema_version': 1, 'kind': 'events', 'revision': str(data['content_version']),
                    'renderer': 'events-v1', 'files': sorted(files, key=lambda entry: entry['path']),
                    'entrypoints': ['data/events.json'], 'resource_contract': 1}
        validate_manifest(manifest)
        (staging / 'manifest.json').write_bytes(_json(manifest))
        verify_package(staging)
        for root, name, signature, digest in witnesses:
            _, current = _stream_stable(root, name)
            if current[2:] != (signature, digest):
                raise PackageError('source_changed')
        # Windows rename fails if the target already exists. Explicit no-overwrite check also covers POSIX.
        if destination.exists():
            raise PackageError('destination_exists')
        staging.rename(destination)
        staging = None
        return manifest
    except PackageError:
        raise
    except (OSError, sqlite3.Error, ValueError, KeyError, TypeError, UnicodeError):
        raise PackageError('export_failed') from None
    finally:
        if staging is not None and staging.parent == parent and staging.name.startswith('.events-export-'):
            try:
                shutil.rmtree(staging)
            except OSError:
                # Keep diagnostics safe even when an owned staging tree needs later cleanup.
                raise PackageError('staging_cleanup_failed') from None


def verify_package(directory, *, runtime=EVENTS_RUNTIME):
    """Independently re-read inventory and validate public-data reference closure."""
    root = Path(directory).absolute()
    try:
        if _plain_path(root, 'manifest.json').stat().st_size > 2 * 1024 * 1024:
            raise PackageError('manifest_too_large')
        manifest_payload, _ = _read_stable(root, 'manifest.json')
        manifest = json.loads(manifest_payload)
        validate_manifest(manifest)
        if not runtime.accepts(manifest):
            raise PackageError('unsupported_client_contract')
        if manifest.get('entrypoints') != ['data/events.json']:
            raise PackageError('unsupported_package_contract')
        expected = {entry['path'] for entry in manifest['files']}
        actual = set()
        for parent, dirs, files in os.walk(root, followlinks=False):
            for name in dirs + files:
                if _is_link((Path(parent) / name).lstat()):
                    raise PackageError('unsafe_package_tree')
            actual.update((Path(parent) / name).relative_to(root).as_posix() for name in files)
        if actual != expected | {'manifest.json'}:
            raise PackageError('inventory_mismatch')
        if sum(entry['size'] for entry in manifest['files']) > MAX_PACKAGE_BYTES:
            raise PackageError('package_too_large')
        payloads = {}
        for entry in manifest['files']:
            if _plain_path(root, entry['path']).stat().st_size != entry['size']:
                raise PackageError('integrity_failure')
            size, witness = _stream_stable(root, entry['path'])
            if size != entry['size'] or witness[3] != entry['sha256']:
                raise PackageError('integrity_failure')
            if entry['path'] == 'data/events.json' or entry['path'].startswith('resources/'):
                payload, reread = _read_stable(root, entry['path'])
                if reread != witness:
                    raise PackageError('source_changed')
                payloads[entry['path']] = payload
        data = json.loads(payloads['data/events.json'])
        _validate_data(data)
        if str(data['content_version']) != manifest['revision']:
            raise PackageError('revision_mismatch')
        for reference in _references(data):
            _validate_image_path(_plain_path(root, reference[1:]))
        required = {'data/events.json'} | {'resources/' + name for name in RESOURCES} | {name[1:] for name in _references(data)}
        if required != expected:
            raise PackageError('reference_closure_failure')
        _check_resources(payloads)
        return manifest
    except PackageError:
        raise
    except (OSError, ValueError, KeyError, TypeError, UnicodeError):
        raise PackageError('invalid_package') from None
