"""Explicit fixture-only seed from a verified public Events package.

Never activates a package or rewrites the legacy Events database. Unsupported
legacy representations are refused rather than silently losing image variants.
"""
import json
from pathlib import Path

from kiosk.delivery.protocol import encode, sha
from .exporter import verify_package, _read_stable
from .mapping import IMAGE_FIELDS, _images, settings
from .workspace import WorkspaceError, _payload


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
        _payload(payload)
        objects.append((str(event['id']), encode(payload)))
    display = settings(data['settings'])
    with workspace.db() as db:
        db.execute('CREATE TABLE IF NOT EXISTS baseline (singleton INTEGER PRIMARY KEY CHECK(singleton=1), '
                   'package TEXT NOT NULL, manifest BLOB NOT NULL, public_data BLOB NOT NULL)')
        for table in ('objects', 'revisions', 'plans', 'heads', 'settings', 'sequence', 'staged', 'baseline'):
            if db.execute('SELECT 1 FROM ' + table + ' LIMIT 1').fetchone():
                raise WorkspaceError('baseline_workspace_not_empty', 409)
        for identity, payload in objects:
            db.execute('INSERT INTO objects VALUES (?,1,?,?,?,1,1)', (identity, payload, 'baseline-import', encode({})))
            db.execute('INSERT INTO revisions VALUES (?,1,?,?,?)', (identity, payload, 'baseline-import', encode({})))
        db.execute('INSERT INTO settings VALUES (1,1,?)', (encode(display),))
        db.execute('INSERT INTO sequence VALUES (1,?)', (data['content_version'],))
        db.execute('INSERT INTO baseline VALUES (1,?,?,?)', (expected_package, encode(manifest), raw))
    return dict(package=expected_package, objects=len(objects), content_version=data['content_version'], activated=False)
