"""Server-private Events publication and historical recipient accounting."""
from datetime import datetime, timezone
from functools import wraps
from pathlib import Path
import sqlite3
import tempfile
import secrets

from flask import current_app, redirect, render_template, request, url_for

from kiosk.features.admin.routes import admin_required
from kiosk.publication.exporter import PackageError, export_events_package
from .protocol import DeliveryError, LIMITS, PROFILE, decode, encode, sha, text
from .publication import MAX_CATALOG_BYTES, MAX_PUBLICATION_BYTES, _publish
from .progress import STALE_SECONDS


def publish_current_events(app, operation_id):
    """Serialize snapshot, verified promotion and frozen assignment as one operation."""
    state = app.extensions['device_delivery']
    text(operation_id)
    state.configuration()  # An explicitly configured root is required; never provision trust.
    with state.connection() as db:
        previous = db.execute('SELECT generation FROM operator_publications WHERE operation_id=?',
                              (operation_id,)).fetchone()
        if previous:
            return previous['generation']
        with tempfile.TemporaryDirectory(prefix='.operator-export-', dir=state.root) as folder:
            source = Path(folder) / 'package'
            export_events_package(app.config['DATABASE_PATH'], app.config['PUBLIC_UPLOAD_DIR'],
                                  app.config['RESOURCE_DIR'] / 'kiosk', source)
            metadata = _publish(state, source, db)
        # Even export cleanup must succeed before changing the assignment.
        generation = state._assign(db, PROFILE, metadata['package_id'], sha(encode(metadata)), metadata['revision'], renderer=metadata['renderer']['build_id'])
        db.execute('INSERT INTO operator_publications VALUES (?,?,?)', (operation_id, PROFILE, generation))
    return generation


def eligibility(device, now):
    if device is None:
        return 'absent'
    if device['profile'] != PROFILE:
        return 'other_profile'
    if device['revoked']:
        return 'revoked'
    if device['expires'] <= now:
        return 'expired'
    return 'eligible'


def distribution(state, generation=None, before=None):
    """One consistent read; presence of a cohort distinguishes known-empty from unknown."""
    with state.connection(write=False) as db:
        now = int(state.clock())
        history = [dict(row) for row in db.execute('''SELECT h.*,c.revision,c.created
            FROM assignment_history h LEFT JOIN assignment_cohorts c
            ON c.profile=h.profile AND c.generation=h.generation
            WHERE h.profile=? AND (? IS NULL OR h.generation<?)
            ORDER BY h.generation DESC LIMIT 26''', (PROFILE, before, before))]
        more = len(history) > 25
        history = history[:25]
        current = db.execute('SELECT generation FROM assignments WHERE profile=?', (PROFILE,)).fetchone()
        if generation is None:
            generation = current['generation'] if current else None
        selected = None
        if generation is not None:
            row = db.execute('''SELECT h.*,c.revision,c.created FROM assignment_history h
                LEFT JOIN assignment_cohorts c ON c.profile=h.profile AND c.generation=h.generation
                WHERE h.profile=? AND h.generation=?''', (PROFILE, generation)).fetchone()
            if row is None:
                raise DeliveryError('publication_not_found', 404)
            selected = dict(row)
            selected['current'] = current is not None and current['generation'] == generation
        # Only non-secret public device fields enter the view model.
        devices = {row['device_id']: dict(row) for row in db.execute(
            'SELECT device_id,profile,revoked,expires FROM devices ORDER BY device_id')}
        members = [{'device_id': key, 'eligibility': eligibility(value, now)} for key, value in devices.items()]
        contacts = {row['device_id']: row['last_contact'] for row in db.execute('SELECT * FROM device_contacts')}
        progress = {row['device_id']: (decode(bytes(row['body'])), row['received'])
                    for row in db.execute('SELECT * FROM device_progress')}
        def monitoring(device_id):
            contact = contacts.get(device_id)
            entry = progress.get(device_id)
            transfer = None
            if entry and selected and entry[0]['generation'] == generation and entry[0]['package_id'] == selected['package_id']:
                transfer = {**entry[0], 'received': utc(entry[1])}
            return {'transfer': transfer, 'last_contact': utc(contact) if contact is not None else None,
                    'stale': contact is not None and now - contact >= STALE_SECONDS}
        if selected:
            known = selected['created'] is not None
            ids = [row['device_id'] for row in db.execute('''SELECT device_id FROM assignment_targets
                WHERE profile=? AND generation=? ORDER BY device_id''', (PROFILE, generation))] if known else []
            reports = {}
            for row in db.execute('SELECT device_id,body,received FROM receipts ORDER BY device_id,received'):
                body = decode(bytes(row['body']))
                if (body['generation'] != generation or body['package_id'] != selected['package_id']
                        or body['result'] != 'ready'):
                    continue
                report = reports.setdefault(row['device_id'], {'modes': set(), 'received': row['received']})
                report['modes'].add(body['mode'])
                report['received'] = max(report['received'], row['received'])
            targets = []
            for device_id in ids:
                report = reports.get(device_id)
                targets.append({'device_id': device_id, 'eligibility': eligibility(devices.get(device_id), now),
                                'ready': bool(report), 'modes': sorted(report['modes']) if report else [],
                                'received': utc(report['received']) if report else None,
                                **monitoring(device_id)})
            for member in members:
                member.update(monitoring(member['device_id']))
            ready = sum(target['ready'] for target in targets)
            selected.update(targets=targets if known else None, ready=ready if known else None,
                            outstanding=len(targets) - ready if known else None,
                            other_reports=[{'device_id': key, 'modes': sorted(value['modes']),
                                            'received': utc(value['received'])}
                                           for key, value in sorted(reports.items()) if key not in ids],
                            later_members=[member for member in members if member['device_id'] not in ids],
                            created=utc(selected['created']) if known else None)
    return {'history': history, 'more': more, 'selected': selected, 'members': members,
            'current_generation': current['generation'] if current else None}


def utc(value):
    return datetime.fromtimestamp(value, timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')


def register_operator_routes(app):
    @app.context_processor
    def delivery_navigation():
        return {'delivery_enabled': True}

    def page_guard(function):
        @wraps(function)
        def call(*args, **kwargs):
            if not request.is_secure:
                return page(error='https_required'), 403
            try:
                return function(*args, **kwargs)
            except DeliveryError as error:
                return page(error=error.code), error.status
            except PackageError:
                return page(error='snapshot_refused'), 409
            except (OSError, sqlite3.Error, ValueError, KeyError):
                return page(error='delivery_unavailable'), 503
        return call

    def page(generation=None, error=None, before=None):
        # Rendering an error must not retry a failed read or leak an exception/path.
        model = distribution(app.extensions['device_delivery'], generation, before) if error is None else None
        return render_template('admin_delivery.html', model=model, error=error, profile=PROFILE,
                               limits=LIMITS, publication_bytes=MAX_PUBLICATION_BYTES,
                               catalog_bytes=MAX_CATALOG_BYTES, publish_id=secrets.token_hex(16))

    @app.get('/admin/delivery', endpoint='admin.delivery_home')
    @app.get('/admin/delivery/<int:generation>', endpoint='admin.delivery_view')
    @admin_required
    @page_guard
    def home(generation=None):
        before = request.args.get('before')
        if before is not None:
            if not before.isascii() or not before.isdecimal() or not 0 < int(before) < 2**63:
                raise DeliveryError('invalid_history_cursor')
            before = int(before)
        return page(generation, before=before)

    @app.post('/admin/delivery/publish', endpoint='admin.delivery_publish')
    @admin_required
    @page_guard
    def publish():
        generation = publish_current_events(current_app, request.form.get('operation_id'))
        return redirect(url_for('admin.delivery_view', generation=generation), code=303)
