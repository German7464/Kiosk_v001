"""Explicit fixture-only seed from a verified public Events package.

Never activates a package or rewrites the legacy Events database. Unsupported
legacy representations are refused rather than silently losing image variants.
"""
import json
from pathlib import Path
import sqlite3

from kiosk.delivery.protocol import encode, sha
from kiosk.features.events.mapping import IMAGE_FIELDS, _images, settings
from kiosk.features.events.payload import validate_payload
from .exporter import verify_package, _read_stable
from .workspace import WorkspaceError

SEED_TABLES = ('objects', 'revisions', 'plans', 'heads', 'settings', 'sequence', 'staged', 'baseline')


def _table_exists(db, name):
    return db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,)).fetchone() is not None


def _rows(db, query, arguments=()):
    return [tuple(row) for row in db.execute(query, arguments)]


def _matches_baseline(db, objects, display, data, manifest, expected_package, raw):
    try:
        if any(not _table_exists(db, name) for name in SEED_TABLES):
            return False
        empty = encode({})
        expected_objects = sorted((identity, 1, payload, 'baseline-import', empty, 1, 1)
                                  for identity, payload in objects)
        expected_revisions = sorted((identity, 1, payload, 'baseline-import', empty)
                                    for identity, payload in objects)
        if _rows(db, 'SELECT id,version,payload,author,dependencies,ready,published_version '
                     'FROM objects ORDER BY id') != expected_objects:
            return False
        if _rows(db, 'SELECT id,version,payload,author,dependencies FROM revisions ORDER BY id,version') != expected_revisions:
            return False
        if _rows(db, 'SELECT singleton,version,body FROM settings') != [(1, 1, encode(display))]:
            return False
        if _rows(db, 'SELECT singleton,content FROM sequence') != [(1, data['content_version'])]:
            return False
        if _rows(db, 'SELECT singleton,package,manifest,public_data FROM baseline') != [
                (1, expected_package, encode(manifest), raw)]:
            return False
        return not any(db.execute('SELECT 1 FROM ' + name + ' LIMIT 1').fetchone()
                       for name in ('plans', 'heads', 'staged'))
    except sqlite3.Error:
        return False


def seed(workspace, package, expected_package, *, confirm_disposable=False):
    if confirm_disposable is not True:
        raise WorkspaceError('disposable_confirmation_required', 403)
    package = Path(package)
    manifest = verify_package(package)
    if sha(encode(manifest)) != expected_package:
        raise WorkspaceError('baseline_package_refused', 409)
    raw, _ = _read_stable(package, 'data/events.json')
    data = json.loads(raw)
    entry = next(item for item in manifest['files'] if item['path'] == 'data/events.json')
    if len(raw) != entry['size'] or sha(raw) != entry['sha256']:
        raise WorkspaceError('baseline_package_changed', 409)
    tags = {item['id']: item['name'] for item in data['tags']}
    objects = []
    for event in data['events']:
        variants = tuple(event[name] for name in IMAGE_FIELDS)
        images = [] if variants == (None, None, None) else list(variants)
        payload = {name: event[name] for name in ('title', 'short_description', 'full_description',
                                                'event_date', 'place', 'sort_order')}
        payload.update(status='active', images=images, tags=[tags[tag] for tag in event['tag_ids']])
        validate_payload(payload, WorkspaceError)
        objects.append((str(event['id']), encode(payload)))
    display = settings(data['settings'])
    with workspace.db() as db:
        occupied = any(_table_exists(db, table) and db.execute('SELECT 1 FROM ' + table + ' LIMIT 1').fetchone()
                       for table in SEED_TABLES)
        if occupied:
            if _matches_baseline(db, objects, display, data, manifest, expected_package, raw):
                return dict(package=expected_package, objects=len(objects),
                            content_version=data['content_version'], activated=False)
            raise WorkspaceError('baseline_workspace_not_empty', 409)
        db.execute('CREATE TABLE IF NOT EXISTS baseline (singleton INTEGER PRIMARY KEY CHECK(singleton=1), '
                   'package TEXT NOT NULL, manifest BLOB NOT NULL, public_data BLOB NOT NULL)')
        for identity, payload in objects:
            db.execute('INSERT INTO objects VALUES (?,1,?,?,?,1,1)', (identity, payload, 'baseline-import', encode({})))
            db.execute('INSERT INTO revisions VALUES (?,1,?,?,?)', (identity, payload, 'baseline-import', encode({})))
        db.execute('INSERT INTO settings VALUES (1,1,?)', (encode(display),))
        db.execute('INSERT INTO sequence VALUES (1,?)', (data['content_version'],))
        db.execute('INSERT INTO baseline VALUES (1,?,?,?)', (expected_package, encode(manifest), raw))
    return dict(package=expected_package, objects=len(objects), content_version=data['content_version'], activated=False)
