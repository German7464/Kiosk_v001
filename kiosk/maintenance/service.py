"""Trusted Maintenance web service: login, QR/code approval, switching, publication.

Separate process, database, secrets, cookie scope and origin from the content
service. Reviewer private keys live here. The content service is only reachable
through the authenticated HTTPS contract in ``content.py``; there is no shared live
database or localhost trust shortcut in either Combined or Separated placement.
"""
from __future__ import annotations

import hashlib
import hmac
import secrets
import time
from functools import wraps
from pathlib import Path
from urllib.parse import quote

from flask import Flask, Response, current_app, g, jsonify, render_template, request, session

from kiosk.core.request_security import AuthenticationLimiter
from kiosk.delivery.protocol import DeliveryError, decode, encode, fields, sha, text
from kiosk.display.qr_pairing import qr_png_bytes
from . import accounts, authority as authority_module, cycle, keystore, permissions, review as review_module, sessions
from .content import ContentClient, ContentRefused
from .store import MaintenanceError, MaintenanceStore
from kiosk.publication import authority as publisher_authority

MAX_JSON = 1024 * 1024
EXEMPT_CSRF = {'service.page', 'service.health', 'service.relocate_redeem', 'service.tls_renew',
               'service.page_native_open', 'service.page_native_package',
               'service.page_native_approve'}
NATIVE_TICKET_SECONDS = 5 * 60
MAX_NATIVE_TICKETS = 64
MAX_NATIVE_TICKETS_USER = 8
NATIVE_TICKET_SCHEMA = '''
CREATE TABLE IF NOT EXISTS page_native_tickets (
    token_sha256 TEXT PRIMARY KEY,
    session_id TEXT NOT NULL,
    user_id TEXT NOT NULL,
    parents BLOB NOT NULL,
    created INTEGER NOT NULL,
    expires INTEGER NOT NULL,
    state TEXT NOT NULL,
    device_id TEXT,
    chain BLOB,
    chain_sha256 TEXT,
    plan_id TEXT,
    approval_sha256 TEXT,
    receipt BLOB,
    acceptance_key TEXT,
    distribution BLOB,
    updated INTEGER NOT NULL
);
'''


def _now():
    return int(current_app.extensions['maintenance_clock']())


def _store():
    return current_app.extensions['maintenance_store']


def _authority():
    return current_app.extensions['maintenance_authority']


def _content():
    return current_app.extensions['maintenance_content']


def csrf_token():
    token = session.get('csrf_token')
    if not isinstance(token, str) or len(token) != 64 or not token.isascii():
        token = secrets.token_hex(32)
        session['csrf_token'] = token
    return token


def body(limit=MAX_JSON):
    if request.mimetype != 'application/json':
        raise MaintenanceError('json_required', 415)
    raw = request.get_data(cache=True)
    if len(raw) > limit:
        raise MaintenanceError('request_limit', 413)
    return decode(raw)


def _json_list(value):
    import json
    if isinstance(value, bytes):
        value = value.decode('utf-8')
    result = json.loads(value)
    if not isinstance(result, list):
        raise MaintenanceError('review_targets_refused', 409)
    return result


def terminal_id():
    value = getattr(g, 'terminal', None)
    if value:
        return value
    value = request.cookies.get('maintenance_terminal', '')
    if not (isinstance(value, str) and len(value) == 32 and value.isascii()):
        value = secrets.token_hex(16)
        g.new_terminal = True
    g.terminal = value
    return value


def session_row(*, touch=True):
    row = getattr(g, 'session_row', None)
    if row is not None:
        return row
    secret = session.get('maintenance_secret')
    if not isinstance(secret, str):
        raise MaintenanceError('session_required', 401)
    with _store().connection() as db:
        row = sessions.lookup(_store(), db, secret, touch=touch)
    g.session_row = row
    g.session_secret = secret
    return row


def require(permission=None, *, trusted=True, group=None):
    row = session_row()
    if row['state'] != 'active':
        raise MaintenanceError('session_locked', 403)
    if trusted and not row['trusted']:
        raise MaintenanceError('trusted_session_required', 403)
    if permission is not None:
        with _store().connection() as db:
            permissions.require(db, row['user_id'], permission, group)
        issuer = current_app.extensions.get('maintenance_tls_authority')
        if issuer is not None and permission != permissions.SERVICE_RELOCATE:
            issuer.require_current()
        if permission != permissions.SERVICE_RELOCATE:
            from .authority_delivery import pending
            if pending(_store()):
                raise MaintenanceError('authority_delivery_pending', 503)
    return row


def _native_token():
    header = request.headers.get('Authorization', '')
    if not header.startswith('Bearer '):
        raise MaintenanceError('native_credential_required', 401)
    token = header[7:]
    if (len(token) != 64 or not token.isascii()
            or any(char not in '0123456789abcdef' for char in token)):
        raise MaintenanceError('native_credential_required', 401)
    return token


def _native_token_sha(token):
    return hashlib.sha256(token.encode('ascii')).hexdigest()


def _native_ticket(db, token, now):
    digest = _native_token_sha(token)
    row = db.execute('SELECT * FROM page_native_tickets WHERE token_sha256=?',
                     (digest,)).fetchone()
    if row is not None:
        if row['expires'] <= now:
            raise MaintenanceError('native_ticket_expired', 410)
        return row
    raise MaintenanceError('native_ticket_required', 401)


def _native_session(db, ticket, now):
    row = db.execute('SELECT * FROM sessions WHERE id=?',
                     (ticket['session_id'],)).fetchone()
    if (row is None or row['state'] != 'active' or row['user_id'] != ticket['user_id']
            or sessions._invalid(db, row, now) is not None
            or not sessions._ancestors_valid(db, row, now)):
        raise MaintenanceError('native_session_required', 401)
    if not row['trusted']:
        raise MaintenanceError('trusted_session_required', 403)
    permissions.require(db, ticket['user_id'], permissions.CONTENT_PUBLISH,
                        _authority().group_id)
    # Preserve the existing browser require() authority gates for native work.
    issuer = current_app.extensions.get('maintenance_tls_authority')
    if issuer is not None:
        issuer.require_current()
    from .authority_delivery import pending
    if pending(_store()):
        raise MaintenanceError('authority_delivery_pending', 503)


def _native_parents(value):
    if not isinstance(value, list) or len(value) > 32:
        raise MaintenanceError('page_release_parent_limit', 400)
    result = []
    for item in value:
        if (not isinstance(item, str) or len(item) != 64 or not item.isascii()
                or any(char not in '0123456789abcdef' for char in item)):
            raise MaintenanceError('page_release_parent_limit', 400)
        result.append(item)
    if len(set(result)) != len(result):
        raise MaintenanceError('page_release_parent_ambiguity', 409)
    return result


def _publisher_chain(db, chain, user_id):
    """Verify a native chain and leaf possession against the independent root."""
    row = db.execute('SELECT * FROM publisher_policy').fetchone()
    if row is None:
        raise MaintenanceError('publisher_policy_missing', 503)
    envelope = decode(bytes(row['envelope']))
    now = _now()
    try:
        current = publisher_authority.policy(
            envelope, _authority().root, _authority().group_id,
            _authority().origin, now, floor=row['version'])
        grant, signer = publisher_authority.permission(
            chain, _authority().root, current, now)
    except (TypeError, KeyError, ValueError):
        raise MaintenanceError('native_chain_refused', 403) from None
    if grant['user_id'] != user_id:
        raise MaintenanceError('native_user_refused', 403)
    return envelope, current, grant, signer


def _guard(function):
    @wraps(function)
    def call(*args, **kwargs):
        try:
            return function(*args, **kwargs)
        except MaintenanceError as error:
            response = jsonify(version=1, error=error.code)
            response.status_code = error.status
        except DeliveryError as error:
            response = jsonify(version=1, error=error.code)
            response.status_code = getattr(error, 'status', 400) or 400
        except ContentRefused as error:
            response = jsonify(version=1, error=error.code, source='content')
            response.status_code = error.status or 502
        except (OSError, KeyError, ValueError, TypeError):
            response = jsonify(version=1, error='maintenance_unavailable')
            response.status_code = 503
        response.headers['Cache-Control'] = 'no-store'
        return response
    return call


def create_maintenance_app(settings):
    app = Flask('kiosk.maintenance',
                template_folder=str(Path(__file__).resolve().parent / 'templates'),
                static_folder=str(Path(__file__).resolve().parent / 'static'))
    app.config.update(settings)
    if not app.config.get('SECRET_KEY'):
        raise RuntimeError('Maintenance service requires an explicit SECRET_KEY.')
    app.config['SESSION_COOKIE_NAME'] = 'maintenance_session'
    app.config['SESSION_COOKIE_SECURE'] = True
    app.config['SESSION_COOKIE_HTTPONLY'] = True
    app.config['SESSION_COOKIE_SAMESITE'] = 'Strict'
    app.config['MAX_CONTENT_LENGTH'] = MAX_JSON
    clock = app.config.get('CLOCK') or time.time
    store = MaintenanceStore(app.config['MAINTENANCE_DATABASE'], clock=clock)
    # The reviewed allowlist keeps store.py unchanged; this additive table is
    # created once through the same protected connection and contains no secret.
    with store.connection() as db:
        db.execute(NATIVE_TICKET_SCHEMA)
        columns = {row['name'] for row in db.execute(
            'PRAGMA table_info(page_native_tickets)')}
        for name, declaration in (('receipt', 'BLOB'), ('acceptance_key', 'TEXT')):
            if name not in columns:
                db.execute('ALTER TABLE page_native_tickets ADD COLUMN '
                           + name + ' ' + declaration)
    public = decode(Path(app.config['MAINTENANCE_ROOT_PUBLIC']).read_bytes())
    policy = decode(Path(app.config['MAINTENANCE_ROOT_POLICY']).read_bytes())
    app.extensions['maintenance_clock'] = clock
    app.extensions['maintenance_store'] = store
    app.extensions['maintenance_authority'] = authority_module.MaintenanceAuthority(
        store, Path(app.config['MAINTENANCE_SECRETS_DIR']), public, policy, clock=clock)
    app.extensions['maintenance_content'] = ContentClient(
        app.config['CONTENT_ORIGIN'], app.config['CONTENT_CA_FILE'],
        app.config['CONTENT_SERVICE_ID'], app.config['CONTENT_SERVICE_SECRET'])
    app.extensions['maintenance_limiter'] = AuthenticationLimiter(account_limit=120,
                                                                  source_limit=600, window=60)
    app.extensions['maintenance_content_sessions'] = {}
    if app.config.get('LAN_TLS_ROOT_SPKI'):
        from .tls import TLSAuthority
        app.extensions['maintenance_tls_authority'] = TLSAuthority(
            store, app.config['MAINTENANCE_SECRETS_DIR'], app.config['LAN_TLS_ROOT_SPKI'],
            maintenance_origin=app.config['MAINTENANCE_ORIGIN'],
            maintenance_override=app.config.get('LAN_TLS_DELEGATION_OVERRIDE'))

    placement = store.placement()
    if placement is None and app.config.get('MAINTENANCE_PLACEMENT'):
        record = app.config['MAINTENANCE_PLACEMENT']
        store.configure_placement(record['mode'], record['side'], record['node'],
                                  record['origin'],
                                  counterpart=record.get('counterpart', ''),
                                  generation=record.get('generation', 1))
    if store.schedule() is None:
        # Setup runs without a request context, so use the configured clock
        # directly rather than the request-scoped _now() helper.
        store.configure_schedule(int(clock()), int(app.config.get('MAINTENANCE_INTERVAL_DAYS', 90)))

    @app.before_request
    def protect():
        if request.endpoint == 'static':
            return None
        if not request.is_secure:
            return jsonify(version=1, error='https_required'), 403
        if request.host_url.rstrip('/') != app.config['MAINTENANCE_ORIGIN']:
            return jsonify(version=1, error='trusted_origin_required'), 403
        wait = app.extensions['maintenance_limiter'].reserve(
            request.remote_addr or 'unknown', request.endpoint or 'unknown')
        if wait:
            response = jsonify(version=1, error='request_limit')
            response.status_code = 429
            response.headers['Retry-After'] = str(wait)
            return response
        terminal_id()
        if request.method not in ('GET', 'HEAD', 'OPTIONS') and request.endpoint not in EXEMPT_CSRF:
            expected = session.get('csrf_token')
            supplied = request.headers.get('X-CSRF-Token')
            if (not isinstance(expected, str) or not isinstance(supplied, str) or
                    len(supplied) != 64 or not supplied.isascii() or
                    not hmac.compare_digest(expected, supplied)):
                return jsonify(version=1, error='csrf_refused'), 403
        if store.fenced() and request.endpoint not in {
                'service.relocate_activate', 'service.health', 'service.page',
                'service.state', 'service.relocate_manifest', 'service.relocate_redeem'}:
            return jsonify(version=1, error='service_fenced'), 409
        return None

    @app.after_request
    def finish(response):
        response.headers['Cache-Control'] = 'no-store'
        response.headers['Referrer-Policy'] = 'no-referrer'
        response.headers['X-Content-Type-Options'] = 'nosniff'
        response.headers['Content-Security-Policy'] = (
            "default-src 'none'; script-src 'self'; style-src 'self'; img-src 'self' data:; "
            "connect-src 'self'; form-action 'self'; frame-ancestors 'none'; base-uri 'none'")
        if getattr(g, 'new_terminal', False):
            response.set_cookie('maintenance_terminal', g.terminal, secure=True,
                                httponly=True, samesite='Strict', max_age=365 * 86400)
        return response

    @app.errorhandler(413)
    def too_large(error):
        return jsonify(version=1, error='request_limit'), 413

    # -- page ---------------------------------------------------------------
    @app.get('/', endpoint='service.page')
    def page():
        return render_template('maintenance.html', csrf=csrf_token())

    @app.get('/api/health', endpoint='service.health')
    def health():
        placement = store.placement()
        return jsonify(version=1, state='fenced' if store.fenced() else 'ready',
                       placement=placement, maintenance=cycle.status(store),
                       recovery=cycle.recovery(store),
                       tls_renewal=(app.extensions['tls_runtime'].status
                                    if 'tls_runtime' in app.extensions else {'state': 'not_configured'}))

    @app.get('/api/state', endpoint='service.state')
    @_guard
    def state():
        placement = store.placement()
        result = dict(version=1, csrf=csrf_token(), authenticated=False,
                      placement=placement, maintenance=cycle.status(store),
                      recovery=cycle.recovery(store), terminal=terminal_id())
        try:
            row = session_row(touch=False)
        except MaintenanceError:
            row = None
        with store.connection() as db:
            result['suspended'] = sessions.suspended(store, db, terminal_id())
            if row is not None:
                user = accounts.find(db, row['user_id'])
                if user:
                    user = {name: user[name] for name in ('id', 'display_name', 'role', 'blocked',
                                                          'created', 'updated')}
                held = sorted(permissions.permissions_for(db, row['user_id']))
                result.update(authenticated=True, state=row['state'], trusted=bool(row['trusted']),
                              temporary=bool(row['temporary']), user=user, permissions=held,
                              groups=sorted(permissions.groups_for(db, row['user_id'])),
                              admin_scope=permissions.admin_scope(db, row['user_id']),
                              admin=permissions.ACCOUNT_GRANT in held,
                              publisher=permissions.CONTENT_PUBLISH in held,
                              editor=permissions.CONTENT_EDIT in held,
                              sessions=sessions.list_sessions(store, db, row['user_id']),
                              connections=sessions.pending_connections(store, db, row['user_id']))
        if row is not None:
            result['authority_lifecycle'] = cycle.authority_status(store, app.config)
        result['csrf'] = csrf_token()
        return jsonify(**result)

    # -- authentication ------------------------------------------------------
    @app.post('/api/login', endpoint='service.login')
    @_guard
    def login():
        value = body()
        fields(value, 'user password')
        with store.connection() as db:
            secret, row = sessions.start_password_session(
                store, db, value['user'], value['password'], terminal_id(),
                remote=request.remote_addr or '', agent=request.user_agent.string or '')
        session.clear()
        session['maintenance_secret'] = secret
        session['csrf_token'] = secrets.token_hex(32)
        app.extensions['maintenance_content_sessions'].pop(row['id'], None)
        return jsonify(version=1, authenticated=True, trusted=row['trusted'],
                       temporary=row['temporary'], user=row['user_id'],
                       csrf=csrf_token(), state='active')

    @app.post('/api/lock', endpoint='service.lock')
    @_guard
    def lock():
        row = session_row()
        with store.connection() as db:
            sessions.lock(store, db, g.session_secret)
        return jsonify(version=1, state='locked', user=row['user_id'])

    @app.post('/api/suspend', endpoint='service.suspend')
    @_guard
    def suspend():
        """Switch away: lock the workspace and drop its cookie from this browser.

        The locked row stays server-side and is only reachable again with that
        account's password on this same terminal, so no other account's bearer
        secret ever lives in the page or a second cookie.
        """
        row = session_row()
        with store.connection() as db:
            sessions.suspend(store, db, g.session_secret)
        session.clear()
        response = jsonify(version=1, state='suspended', user=row['user_id'],
                           csrf=csrf_token())
        response.delete_cookie(app.config['SESSION_COOKIE_NAME'], secure=True,
                               httponly=True, samesite='Strict')
        return response

    @app.post('/api/resume', endpoint='service.resume')
    @_guard
    def resume():
        value = body()
        fields(value, 'user password')
        current = session.get('maintenance_secret')
        try:
            with store.connection() as db:
                if isinstance(current, str):
                    secret, row = sessions.resume(
                        store, db, current, value['user'], value['password'],
                        remote=request.remote_addr or '',
                        agent=request.user_agent.string or '')
                else:
                    secret, row = sessions.resume_suspended(
                        store, db, terminal_id(), value['user'], value['password'],
                        remote=request.remote_addr or '',
                        agent=request.user_agent.string or '')
        except MaintenanceError:
            raise
        session['maintenance_secret'] = secret
        session['csrf_token'] = secrets.token_hex(32)
        app.extensions['maintenance_content_sessions'].pop(row['id'], None)
        return jsonify(version=1, state='active', user=row['user_id'], csrf=csrf_token())

    @app.post('/api/rotate', endpoint='service.rotate')
    @_guard
    def rotate():
        row = require()
        with store.connection() as db:
            secret, identity = sessions.rotate(store, db, g.session_secret)
        # The stable session id keeps its dependent content-session cache entry.
        session['maintenance_secret'] = secret
        session['csrf_token'] = secrets.token_hex(32)
        return jsonify(version=1, state='rotated', csrf=csrf_token())

    @app.post('/api/logout', endpoint='service.logout')
    @_guard
    def logout():
        with store.connection() as db:
            sessions.end(store, db, session.get('maintenance_secret', ''), 'signed_out')
        session.clear()
        response = jsonify(version=1, state='signed_out', csrf=csrf_token())
        response.delete_cookie(app.config['SESSION_COOKIE_NAME'], secure=True,
                               httponly=True, samesite='Strict')
        return response

    @app.get('/api/sessions', endpoint='service.sessions')
    @_guard
    def list_sessions():
        row = require(trusted=False)
        with store.connection() as db:
            return jsonify(version=1, sessions=sessions.list_sessions(store, db, row['user_id']))

    @app.post('/api/sessions/terminate', endpoint='service.terminate')
    @_guard
    def terminate():
        value = body()
        fields(value, 'id')
        row = require(trusted=False)
        with store.connection() as db:
            sessions.terminate(store, db, row['user_id'], value['id'])
        cache = app.extensions['maintenance_content_sessions']
        cache.pop(value['id'], None)
        return jsonify(version=1, state='terminated')

    @app.post('/api/sessions/terminate-terminal', endpoint='service.terminate_terminal')
    @_guard
    def terminate_terminal():
        row = require(trusted=False)
        with store.connection() as db:
            count = sessions.terminate_user_on_terminal(store, db, row['user_id'],
                                                        terminal_id())
        session.clear()
        response = jsonify(version=1, state='terminated', count=count, csrf=csrf_token())
        response.delete_cookie(app.config['SESSION_COOKIE_NAME'], secure=True,
                               httponly=True, samesite='Strict')
        return response

    # -- connection approval (QR / manual code) ------------------------------
    @app.post('/api/connection/start', endpoint='service.connection_start')
    @_guard
    def connection_start():
        value = body()
        if set(value) - {'kind', 'summary', 'requested_user', 'target_user', 'document'}:
            raise MaintenanceError('invalid_fields')
        if not isinstance(value.get('kind'), str) or not isinstance(value.get('summary'), str):
            raise MaintenanceError('invalid_fields')
        kind = value['kind']
        if kind not in ('login', 'terminal', 'device'):
            raise MaintenanceError('connection_kind_refused')
        requested = value.get('requested_user', '')
        target = value.get('target_user', '')
        document = value.get('document')
        if kind == 'login' and not requested:
            raise MaintenanceError('connection_user_required')
        if kind in ('terminal', 'device') and not target:
            raise MaintenanceError('connection_target_required')
        try:
            active = session_row(touch=False)
        except MaintenanceError:
            active = None
        if kind == 'login' and active is not None and requested != active['user_id']:
            raise MaintenanceError('connection_user_mismatch', 403)
        if kind in ('terminal', 'device'):
            # Only an authenticated account may ask for retained trust, and it may
            # only ask for its own terminal/device enrollment.
            if active is None:
                raise MaintenanceError('session_required', 401)
            if kind == 'terminal' and target != active['user_id']:
                raise MaintenanceError('connection_user_mismatch', 403)
            if kind == 'device' and target != active['user_id']:
                with store.connection(write=False) as db:
                    permissions.require(db, active['user_id'], permissions.DEVICE_ENROLL)
        if document is not None and len(encode(document)) > 65536:
            raise MaintenanceError('connection_document_limit', 413)
        browser = session.get('browser_binding')
        if not isinstance(browser, str):
            browser = secrets.token_hex(32)
            session['browser_binding'] = browser
        with store.connection() as db:
            identity, record = sessions.create_connection(
                store, db, kind, terminal_id(), browser, value['summary'][:120],
                requested_user=requested, target_user=target, document=document)
            record = sessions.set_origin(db, identity, app.config['MAINTENANCE_ORIGIN'])
        uri = (app.config['MAINTENANCE_ORIGIN'] + '/connect#id=' + identity +
               '&code=' + record['code'])
        return jsonify(version=1, id=identity, code=record['code'],
                       expires=record['expires'], confirmation=identity[:8].upper(),
                       qr='data:image/png;base64,' + __import__('base64').b64encode(
                           qr_png_bytes(uri)).decode(), link=uri)

    def _resolve_connection(value):
        """Accept the manual code a person reads or the internal identity."""
        if isinstance(value.get('code'), str) and value.get('code').strip():
            with store.connection(write=False) as db:
                row = sessions.find_connection(store, db, value['code'])
            return row['id']
        if isinstance(value.get('id'), str) and value['id']:
            return value['id']
        raise MaintenanceError('connection_code_required')

    @app.post('/api/connection/review', endpoint='service.connection_review')
    @_guard
    def connection_review():
        value = body()
        identity = _resolve_connection(value)
        row = require()
        with store.connection() as db:
            connection = sessions.connection(store, db, identity)
            if connection['kind'] in ('terminal', 'device'):
                permissions.require(db, row['user_id'], permissions.DEVICE_ENROLL)
            elif connection['requested_user'] != row['user_id']:
                raise MaintenanceError('connection_user_mismatch', 403)
            summary = sessions.connection_summary(store, db, connection)
        summary['can_approve'] = True
        return jsonify(version=1, connection=summary, csrf=csrf_token())

    @app.post('/api/connection/approve', endpoint='service.connection_approve')
    @_guard
    def connection_approve():
        value = body()
        identity = _resolve_connection(value)
        row = require()
        with store.connection() as db:
            connection = sessions.connection(store, db, identity)
            if not isinstance(value.get('code'), str):
                value['code'] = connection['code']
            result = sessions.approve_connection(store, db, g.session_secret, identity,
                                                 value['code'])
            row = result['row']
            if row['kind'] == 'device':
                document = decode(row['document']).get('document') or {}
                admin_groups = set(permissions.admin_scope(db, result['approver']))
                if not set(document.get('groups') or []) <= admin_groups:
                    raise MaintenanceError('delegation_exceeds_scope', 403)
                bundle = _authority().enroll(
                    db, result['approver'], row['target_user'],
                    role=document.get('role', 'user'),
                    groups=document.get('groups') or [], targets=document.get('targets') or [],
                    permissions=document.get('permissions'))
                record = decode(row['document'])
                record['result'] = dict(
                    user=row['target_user'],
                    bundle=dict(group_id=_authority().group_id,
                                origin=_authority().origin,
                                root_spki=_authority().public['root_spki'],
                                root_sha256=_authority().public['root_sha256'],
                                policy=bundle['policy'], chain=bundle['chain'],
                                scope=bundle['scope'], role=bundle['role']))
                db.execute('UPDATE connections SET document=? WHERE id=?',
                           (encode(record), identity))
                return jsonify(version=1, state='approved', kind='device',
                               **record['result'])
        return jsonify(version=1, state='approved', kind=row['kind'])

    @app.post('/api/connection/reject', endpoint='service.connection_reject')
    @_guard
    def connection_reject():
        value = body()
        identity = _resolve_connection(value)
        row = require()
        with store.connection() as db:
            connection = sessions.connection(store, db, identity)
            if connection['kind'] in ('terminal', 'device'):
                permissions.require(db, row['user_id'], permissions.DEVICE_ENROLL)
            elif connection['requested_user'] != row['user_id']:
                raise MaintenanceError('connection_user_mismatch', 403)
            db.execute('DELETE FROM connections WHERE id=?', (identity,))
        return jsonify(version=1, state='rejected')

    @app.post('/api/connection/poll', endpoint='service.connection_poll')
    @_guard
    def connection_poll():
        value = body()
        identity = _resolve_connection(value)
        browser = session.get('browser_binding', '')
        with store.connection() as db:
            row = sessions.connection(store, db, identity)
            if row['kind'] == 'login':
                result = sessions.consume_login(
                    store, db, identity, browser, remote=request.remote_addr or '',
                    agent=request.user_agent.string or '')
                if result is None:
                    return jsonify(version=1, state='pending'), 202
                secret, created = result
                session.clear()
                session['maintenance_secret'] = secret
                session['csrf_token'] = secrets.token_hex(32)
                session['browser_binding'] = browser
                return jsonify(version=1, state='accepted', user=created['user_id'],
                               trusted=created['trusted'], csrf=csrf_token())
            if row['kind'] == 'terminal':
                done = sessions.consume_terminal(store, db, identity, browser)
                if done is None:
                    return jsonify(version=1, state='pending'), 202
                return jsonify(version=1, state='accepted', **done)
            if not row['approved']:
                return jsonify(version=1, state='pending'), 202
            record = decode(row['document'])
            return jsonify(version=1, state='approved', id=identity,
                           result=record.get('result'), document=record.get('document'))

    # -- retained terminal enrollment ---------------------------------------
    @app.post('/api/terminal/approve', endpoint='service.terminal_approve')
    @_guard
    def terminal_approve():
        value = body()
        if set(value) - {'name', 'users', 'groups', 'terminal'}:
            raise MaintenanceError('invalid_fields')
        if not all(key in value for key in ('name', 'users', 'groups')):
            raise MaintenanceError('invalid_fields')
        row = require(permission=permissions.DEVICE_ENROLL)
        target = value.get('terminal') or terminal_id()
        with store.connection() as db:
            admin_groups = set(permissions.admin_scope(db, row['user_id']))
            if not set(value['groups']) <= admin_groups:
                raise MaintenanceError('delegation_exceeds_scope', 403)
            for user in value['users']:
                permissions.require_account_authority(db, row['user_id'], user)
            sessions.approve_terminal(db, row['user_id'], target, value['name'],
                                      value['users'], value['groups'], now=_now())
            store.audit(db, 'terminal_approved', row['user_id'], target)
        return jsonify(version=1, state='approved', terminal=target)

    @app.get('/api/terminals', endpoint='service.terminals')
    @_guard
    def terminals():
        require(permission=permissions.DEVICE_ENROLL)
        with store.connection(write=False) as db:
            return jsonify(version=1, terminals=[dict(row) for row in db.execute(
                'SELECT id,name,approved,retained,approved_by,approved_at FROM terminals '
                'ORDER BY name')])

    # -- accounts, teams and scoped grants ----------------------------------
    @app.get('/api/users', endpoint='service.users')
    @_guard
    def users():
        require(permission=permissions.ACCOUNT_GRANT)
        with store.connection(write=False) as db:
            return jsonify(version=1, users=accounts.list_users(db))

    @app.post('/api/users', endpoint='service.user_create')
    @_guard
    def user_create():
        value = body()
        fields(value, 'user password role')
        row = require(permission=permissions.ACCOUNT_GRANT)
        with store.connection() as db:
            accounts.create_user(db, value['user'], value['password'], value['role'],
                                 value.get('display_name', ''), _now(), actor=row['user_id'])
            store.audit(db, 'account_created', row['user_id'], value['user'])
        return jsonify(version=1, state='created', user=value['user'])

    @app.post('/api/users/unblock', endpoint='service.user_unblock')
    @_guard
    def user_unblock():
        value = body()
        fields(value, 'user')
        row = require(permission=permissions.ACCOUNT_GRANT)
        with store.connection() as db:
            accounts.unblock(db, row['user_id'], value['user'], _now())
            store.audit(db, 'account_unblocked', row['user_id'], value['user'])
        return jsonify(version=1, state='active', user=value['user'])

    @app.post('/api/users/block', endpoint='service.user_block')
    @_guard
    def user_block():
        value = body()
        fields(value, 'user')
        row = require(permission=permissions.ACCOUNT_GRANT)
        with store.connection() as db:
            accounts.block(db, row['user_id'], value['user'], _now())
            store.audit(db, 'account_blocked', row['user_id'], value['user'])
        return jsonify(version=1, state='blocked', user=value['user'])

    @app.post('/api/teams', endpoint='service.team_create')
    @_guard
    def team_create():
        value = body()
        fields(value, 'team name')
        row = require(permission=permissions.ACCOUNT_GRANT)
        with store.connection() as db:
            accounts.add_team(db, value['team'], value['name'], _now())
            store.audit(db, 'team_created', row['user_id'], value['team'])
        return jsonify(version=1, state='created', team=value['team'])

    @app.get('/api/teams', endpoint='service.teams')
    @_guard
    def teams():
        require(permission=permissions.ACCOUNT_GRANT)
        with store.connection(write=False) as db:
            return jsonify(version=1, teams=[dict(row) for row in db.execute(
                'SELECT id,name,created FROM teams ORDER BY id')])

    @app.post('/api/memberships', endpoint='service.membership')
    @_guard
    def membership():
        value = body()
        fields(value, 'team user')
        row = require(permission=permissions.ACCOUNT_GRANT)
        with store.connection() as db:
            accounts.add_membership(db, row['user_id'], value['team'], value['user'], _now())
            store.audit(db, 'membership_added', row['user_id'],
                        value['team'] + ':' + value['user'])
        return jsonify(version=1, state='added')

    @app.post('/api/memberships/remove', endpoint='service.membership_remove')
    @_guard
    def membership_remove():
        value = body()
        fields(value, 'team user')
        row = require(permission=permissions.ACCOUNT_GRANT)
        with store.connection() as db:
            accounts.remove_membership(db, row['user_id'], value['team'], value['user'], _now())
            store.audit(db, 'membership_removed', row['user_id'],
                        value['team'] + ':' + value['user'])
        return jsonify(version=1, state='removed')

    @app.get('/api/grants', endpoint='service.grants')
    @_guard
    def grants():
        value_user = request.args.get('subject', '')
        value_type = request.args.get('subject_type', 'user')
        row = require(trusted=False)
        if value_type not in ('user', 'team'):
            raise MaintenanceError('grant_subject_refused')
        with store.connection(write=False) as db:
            if value_user != row['user_id'] or value_type != 'user':
                permissions.require(db, row['user_id'], permissions.ACCOUNT_GRANT)
            return jsonify(version=1, subject=value_user, subject_type=value_type,
                           grants=permissions.listing(db, value_type, value_user))

    @app.post('/api/grants', endpoint='service.grant')
    @_guard
    def grant():
        value = body()
        fields(value, 'subject_type subject bundle groups')
        row = require(permission=permissions.ACCOUNT_GRANT)
        with store.connection() as db:
            scope = permissions.assign(db, row['user_id'], value['subject_type'],
                                       value['subject'], value['bundle'], value['groups'],
                                       _now())
            store.audit(db, 'grant_assigned', row['user_id'],
                        value['subject_type'] + ':' + value['subject'] + ':' + value['bundle'])
        return jsonify(version=1, state='assigned', groups=scope)

    @app.post('/api/grants/revoke', endpoint='service.grant_revoke')
    @_guard
    def grant_revoke():
        value = body()
        fields(value, 'subject_type subject bundle groups')
        row = require(permission=permissions.ACCOUNT_GRANT)
        with store.connection() as db:
            permissions.revoke(db, row['user_id'], value['subject_type'], value['subject'],
                               value['bundle'], value['groups'], _now())
        return jsonify(version=1, state='revoked')

    @app.get('/api/permissions', endpoint='service.permissions')
    @_guard
    def permission_view():
        value_user = request.args.get('user', '')
        row = require(trusted=False)
        if value_user != row['user_id']:
            with store.connection() as db:
                permissions.require(db, row['user_id'], permissions.ACCOUNT_GRANT)
        with store.connection(write=False) as db:
            return jsonify(version=1, user=value_user,
                           permissions=sorted(permissions.permissions_for(db, value_user)),
                           groups=sorted(permissions.groups_for(db, value_user)))

    # -- review and one explicit Publish ------------------------------------
    def _content_secret(row):
        cache = app.extensions['maintenance_content_sessions']
        secret = cache.get(row['id'])
        if secret:
            return secret
        with store.connection() as db:
            granted = _authority().grant(db, row['user_id'])
        secret = _content().session(row['user_id'], granted['chain'])
        cache[row['id']] = secret
        return secret

    def _page_files(secret, document):
        """Fetch every exact catalog byte for independent v2 review."""
        files = {}
        plan_id = document['plan']['id']
        for target in document['targets']:
            package = {}
            for entry in target['metadata']['publication']['package']['files']:
                package[entry['path']] = _content().page_artifact(
                    secret, plan_id, target['device_id'], entry['path'])
            files[target['device_id']] = {'package': package, 'kiosk': {}, 'tv': {}}
        return files

    def _page_view(row, document, targets, files, settings_version=0):
        return review_module.validate_page(
            document, targets=targets, user_id=row['user_id'],
            group_id=_authority().group_id, origin=_authority().origin,
            now=_now(), files=files, settings_version=settings_version)

    @app.post('/api/page/review', endpoint='service.page_review')
    @_guard
    def page_review():
        value = body()
        fields(value, 'parents')
        row = require(permission=permissions.CONTENT_PUBLISH)
        secret = _content_secret(row)
        targets = _content().page_targets(secret)
        with store.connection(write=False) as db:
            granted = _authority().grant(db, row['user_id'])
        scope = granted['grant'].get('scope')
        if scope is not None and not {item['device_id'] for item in targets} <= \
                set(scope['targets']):
            raise MaintenanceError('publication_targets_outside_scope', 403)
        prepared = _content().page_prepare(secret, value['parents'])
        document = prepared['document']
        files = _page_files(secret, document)
        view = _page_view(row, document, targets, files,
                          prepared.get('settings_version', 0))
        identity = secrets.token_hex(32)
        digest = review_module.ticket_digest(document, targets, row['user_id'])
        expires = min(int(document['plan']['expires']), _now() + 15 * 60)
        with store.connection() as db:
            db.execute('INSERT INTO reviews VALUES (?,?,?,?,?,?,?,?,?,?,NULL,NULL,NULL)',
                       (identity, row['id'], row['user_id'], document['plan']['id'], digest,
                        encode(document), encode(targets), _now(), expires, 'reviewed'))
        return jsonify(version=1, id=identity, review=view,
                       expires=expires, csrf=csrf_token())

    @app.get('/api/page/review/<identity>', endpoint='service.page_review_get')
    @_guard
    def get_page_review(identity):
        row = require(permission=permissions.CONTENT_PUBLISH)
        text(identity)
        with store.connection(write=False) as db:
            item = db.execute('SELECT * FROM reviews WHERE id=?', (identity,)).fetchone()
        if item is None:
            raise MaintenanceError('review_not_found', 404)
        if item['user_id'] != row['user_id']:
            raise MaintenanceError('review_scope_refused', 403)
        document = decode(bytes(item['body']))
        if document.get('version') != 2:
            raise MaintenanceError('review_kind_refused', 409)
        targets = _json_list(item['targets'])
        secret = _content_secret(row)
        files = _page_files(secret, document)
        view = _page_view(row, document, targets, files)
        return jsonify(version=1, id=identity, state=item['state'], review=view,
                       expires=item['expires'])

    @app.post('/api/page/native-ticket', endpoint='service.page_native_ticket')
    @_guard
    def page_native_ticket():
        value = body()
        fields(value, 'parents')
        row = require(permission=permissions.CONTENT_PUBLISH)
        parents = _native_parents(value['parents'])
        now = _now()
        token = secrets.token_hex(32)
        expires = min(now + NATIVE_TICKET_SECONDS, int(row['expires']),
                      int(row['idle_deadline']))
        if expires <= now:
            raise MaintenanceError('session_required', 401)
        with store.connection() as db:
            db.execute('DELETE FROM page_native_tickets WHERE expires < ?', (now,))
            active = db.execute('SELECT COUNT(*) FROM page_native_tickets '
                                'WHERE expires>?', (now,)).fetchone()[0]
            mine = db.execute('SELECT COUNT(*) FROM page_native_tickets '
                              'WHERE expires>? AND user_id=?',
                              (now, row['user_id'])).fetchone()[0]
            if active >= MAX_NATIVE_TICKETS or mine >= MAX_NATIVE_TICKETS_USER:
                raise MaintenanceError('native_ticket_capacity', 429)
            db.execute(
                'INSERT INTO page_native_tickets '
                '(token_sha256,session_id,user_id,parents,created,expires,state,updated) '
                'VALUES (?,?,?,?,?,?,?,?)',
                (_native_token_sha(token), row['id'], row['user_id'], encode(parents),
                 now, expires, 'issued', now))
        content_origin, maintenance_origin = _authority().origin, app.config['MAINTENANCE_ORIGIN']
        handoff = ('kiosk://roaming/page#version=1&token=' + token
                   + '&expires=' + str(expires)
                   + '&content_origin=' + quote(content_origin, safe='')
                   + '&maintenance_origin=' + quote(maintenance_origin, safe=''))
        return jsonify(version=1, token=token, expires=expires,
                       content_origin=content_origin,
                       maintenance_origin=maintenance_origin,
                       handoff=handoff)

    @app.post('/api/page/native/open', endpoint='service.page_native_open')
    @_guard
    def page_native_open():
        value = body()
        fields(value, 'approval chain')
        token = _native_token()
        now = _now()
        with store.connection() as db:
            ticket = _native_ticket(db, token, now)
            _native_session(db, ticket, now)
            policy_envelope, _, _, signer = _publisher_chain(
                db, value['chain'], ticket['user_id'])
            device_id = publisher_authority.key_id(signer)
            expected = dict(token_sha256=_native_token_sha(token),
                            content_origin=_authority().origin,
                            maintenance_origin=app.config['MAINTENANCE_ORIGIN'])
            try:
                opened = publisher_authority.verified(
                    value['approval'], signer, 'page-review-open')
            except (TypeError, KeyError, ValueError):
                raise MaintenanceError('native_open_refused', 403) from None
            if opened != expected:
                raise MaintenanceError('native_open_refused', 403)
            if ticket['state'] in ('opened', 'committing', 'approved'):
                if (ticket['device_id'] != device_id
                        or bytes(ticket['chain']) != encode(value['chain'])):
                    raise MaintenanceError('native_ticket_bound', 409)
                secret = _content().session(ticket['user_id'], value['chain'])
                document = _content().page_candidate(secret, ticket['plan_id'])
            else:
                secret = _content().session(ticket['user_id'], value['chain'])
                prepared = _content().page_prepare(
                    secret, _json_list(ticket['parents']))
                document = prepared['document']
                plan = document.get('plan') or {}
                if (document.get('version') != 2
                        or plan.get('user_id') != ticket['user_id']
                        or plan.get('device_id') != device_id
                        or plan.get('group_id') != _authority().group_id
                        or plan.get('origin') != _authority().origin):
                    raise MaintenanceError('native_scope_refused', 403)
                db.execute(
                    'UPDATE page_native_tickets SET state=?,device_id=?,chain=?,'
                    'chain_sha256=?,plan_id=?,updated=? WHERE token_sha256=?',
                    ('opened', device_id, encode(value['chain']),
                     sha(encode(value['chain'])), plan['id'], now,
                     ticket['token_sha256']))
        return jsonify(version=1, document=document)

    @app.get('/api/page/native/package/<device_id>/<path:name>',
             endpoint='service.page_native_package')
    @_guard
    def page_native_package(device_id, name):
        text(device_id)
        token = _native_token()
        now = _now()
        with store.connection(write=False) as db:
            ticket = _native_ticket(db, token, now)
            _native_session(db, ticket, now)
            if ticket['state'] not in ('opened', 'approved') or not ticket['plan_id']:
                raise MaintenanceError('native_ticket_open_required', 409)
            chain, plan_id = _json_list(ticket['chain']), ticket['plan_id']
        secret = _content().session(ticket['user_id'], chain)
        document = _content().page_candidate(secret, plan_id)
        target = next((item for item in document['targets']
                       if item['device_id'] == device_id), None)
        if target is None:
            raise MaintenanceError('file_not_found', 404)
        entry = next((item for item in target['metadata']['publication']['package']['files']
                      if item['path'] == name), None)
        if entry is None:
            raise MaintenanceError('file_not_found', 404)
        payload = _content().page_artifact(secret, plan_id, device_id, name)
        if len(payload) != entry['size'] or sha(payload) != entry['sha256']:
            raise MaintenanceError('publication_integrity', 503)
        return Response(payload, mimetype='application/octet-stream',
                        headers={'Content-Length': str(len(payload))})

    @app.post('/api/page/native/approve', endpoint='service.page_native_approve')
    @_guard
    def page_native_approve():
        value = body()
        fields(value, 'id approval chain')
        token = _native_token()
        now = _now()
        approval_sha = sha(encode(value['approval']))
        chain_raw = encode(value['chain'])
        # Phase 1: a short read transaction verifies the ticket, active session,
        # caller chain and native leaf. No Content call runs under this lock.
        with store.connection(write=False) as db:
            ticket = _native_ticket(db, token, now)
            _native_session(db, ticket, now)
            if ticket['state'] not in ('opened', 'committing', 'approved'):
                raise MaintenanceError('native_ticket_open_required', 409)
            if not ticket['plan_id']:
                raise MaintenanceError('native_ticket_open_required', 409)
            if value['id'] != ticket['plan_id']:
                raise MaintenanceError('native_ticket_required', 409)
            if bytes(ticket['chain']) != chain_raw:
                raise MaintenanceError('native_ticket_bound', 409)
            policy_envelope, _, _, signer = _publisher_chain(
                db, value['chain'], ticket['user_id'])
            if ticket['device_id'] != publisher_authority.key_id(signer):
                raise MaintenanceError('native_ticket_bound', 409)
            saved_approval = ticket['approval_sha256']
            saved_receipt = ticket['receipt']
            saved_key = ticket['acceptance_key']
            distribution = (decode(bytes(ticket['distribution']))
                            if ticket['distribution'] is not None else None)
            if ticket['state'] == 'approved' and distribution is not None:
                if saved_approval == approval_sha:
                    return jsonify(version=1, state='approved',
                                   distribution=distribution)
                raise MaintenanceError('native_approval_changed', 409)
            if saved_approval is not None and saved_approval != approval_sha:
                raise MaintenanceError('native_approval_changed', 409)
        receipt = None
        acceptance_key = None
        if saved_receipt is not None and saved_key is not None:
            receipt = decode(bytes(saved_receipt))
            acceptance_key = saved_key
        else:
            # Phase 2: remote candidate, independent byte re-derivation and the
            # exact signed plan check. The Maintenance receipt is persisted in
            # the next short transaction before any Content approval is sent.
            secret = _content().session(ticket['user_id'], value['chain'])
            document = _content().page_candidate(secret, ticket['plan_id'])
            try:
                plan, _ = publisher_authority.page_approval(
                    value['approval'], value['chain'], policy_envelope,
                    _authority().root, _authority().group_id, _authority().origin,
                    now, known_heads=(), ancestry=document.get('ancestry', []))
            except (TypeError, KeyError, ValueError):
                raise MaintenanceError('native_approval_refused', 403) from None
            if plan != document.get('plan'):
                raise MaintenanceError('native_plan_changed', 409)
            targets = _content().page_targets(secret)
            if ([item['device_id'] for item in targets]
                    != [item['device_id'] for item in plan['targets']]):
                raise MaintenanceError('native_targets_changed', 409)
            files = _page_files(secret, document)
            review_module.validate_page(
                document, targets=targets, user_id=ticket['user_id'],
                group_id=_authority().group_id, origin=_authority().origin,
                now=now, files=files)
            signed = _authority().sign_page_receipt(
                plan, value['approval'], plan['policy_version'],
                secrets.token_hex(32), now)
            with store.connection() as db:
                current = _native_ticket(db, token, now)
                _native_session(db, current, now)
                if current['approval_sha256'] is not None:
                    if current['approval_sha256'] != approval_sha:
                        raise MaintenanceError('native_approval_changed', 409)
                    if current['receipt'] is None:
                        raise MaintenanceError('native_approval_changed', 409)
                    receipt = decode(bytes(current['receipt']))
                    acceptance_key = current['acceptance_key']
                else:
                    receipt = signed['receipt']
                    acceptance_key = signed['acceptance_key']
                    db.execute(
                        'UPDATE page_native_tickets SET state=?,approval_sha256=?,'
                        'receipt=?,acceptance_key=?,updated=? WHERE token_sha256=?',
                        ('committing', approval_sha, encode(receipt), acceptance_key,
                         now, current['token_sha256']))
        # Phase 3: forward the exact durable response and never hold a
        # Maintenance transaction across the Content commit. A lost response is
        # safe: the retry reuses this same receipt and Content returns its
        # original generation.
        secret = _content().session(ticket['user_id'], value['chain'])
        try:
            result = _content().page_approve(
                secret, ticket['plan_id'], value['approval'], value['chain'],
                receipt, acceptance_key)
        except ContentRefused as error:
            if error.status in (409, 410):
                raise MaintenanceError('native_plan_changed', 409) from None
            raise
        distribution = result['distribution']
        with store.connection() as db:
            current = _native_ticket(db, token, now)
            _native_session(db, current, now)
            if current['approval_sha256'] != approval_sha:
                raise MaintenanceError('native_approval_changed', 409)
            db.execute(
                'UPDATE page_native_tickets SET state=?,'
                'distribution=?,updated=? WHERE token_sha256=?',
                ('approved', encode(distribution), now, current['token_sha256']))
        return jsonify(version=1, state='approved', distribution=distribution)

    @app.post('/api/page/publish', endpoint='service.page_publish')
    @_guard
    def page_publish():
        # Browser-only Stage 6 signing is disabled: the shared interface is the
        # native ticket/open/package/approve journey. The accepted v1
        # /api/publish path below is unchanged.
        raise MaintenanceError('native_approval_required', 409)

    @app.get('/api/page/review/<identity>/status', endpoint='service.page_review_status')
    @_guard
    def page_review_status(identity):
        row = require(trusted=False)
        with store.connection(write=False) as db:
            item = db.execute('SELECT * FROM reviews WHERE id=?', (identity,)).fetchone()
        if item is None or item['user_id'] != row['user_id']:
            raise MaintenanceError('review_not_found', 404)
        return jsonify(version=1, state=item['state'], commit=item['commit_reference'])

    @app.get('/api/drafts', endpoint='service.drafts')
    @_guard
    def drafts():
        row = require(permission=permissions.CONTENT_EDIT)
        secret = _content_secret(row)
        value = _content().drafts(secret)
        return jsonify(version=1, objects=value['objects'], settings=value['settings'])

    @app.post('/api/draft', endpoint='service.draft_save')
    @_guard
    def draft_save():
        value = body()
        fields(value, 'identity expected_version payload dependencies')
        row = require(permission=permissions.CONTENT_EDIT)
        secret = _content_secret(row)
        result = _content().save_draft(secret, value['identity'], value['expected_version'],
                                       value['payload'], value['dependencies'])
        return jsonify(version=1, version_number=result['version_number'])

    @app.post('/api/draft/ready', endpoint='service.draft_ready')
    @_guard
    def draft_ready():
        value = body()
        fields(value, 'identity version')
        row = require(permission=permissions.CONTENT_EDIT)
        secret = _content_secret(row)
        _content().ready_draft(secret, value['identity'], value['version'])
        return jsonify(version=1, state='ready')

    @app.post('/api/settings', endpoint='service.settings_save')
    @_guard
    def settings_save():
        value = body()
        fields(value, 'expected_version values')
        row = require(permission=permissions.CONTENT_EDIT)
        secret = _content_secret(row)
        result = _content().save_settings(secret, value['expected_version'], value['values'])
        return jsonify(version=1, version_number=result['version_number'])

    @app.post('/api/review', endpoint='service.review')
    @_guard
    def start_review():
        value = body()
        fields(value, 'selected parents')
        row = require(permission=permissions.CONTENT_PUBLISH)
        secret = _content_secret(row)
        current = _content().targets(secret)
        with store.connection() as db:
            granted = _authority().grant(db, row['user_id'])
        scope = granted['grant'].get('scope')
        if scope is not None:
            if not {item['device_id'] for item in current} <= set(scope['targets']):
                raise MaintenanceError('publication_targets_outside_scope', 403)
        prepared = _content().prepare(secret, value['selected'], current, value['parents'])
        document = prepared['document']
        view = review_module.validate(document, targets=current, user_id=row['user_id'],
                                     group_id=_authority().group_id,
                                     origin=_authority().origin, now=_now())
        identity = secrets.token_hex(32)
        digest = review_module.ticket_digest(document, current, row['user_id'])
        expires = min(int(prepared['expires']), _now() + 15 * 60)
        with store.connection() as db:
            db.execute('INSERT INTO reviews VALUES (?,?,?,?,?,?,?,?,?,?,NULL,NULL,NULL)',
                       (identity, row['id'], row['user_id'], prepared['id'], digest,
                        encode(document), encode(current), _now(), expires, 'reviewed'))
        return jsonify(version=1, id=identity, review=view,
                       expires=expires, csrf=csrf_token())

    @app.get('/api/review/<identity>', endpoint='service.review_get')
    @_guard
    def get_review(identity):
        row = require(permission=permissions.CONTENT_PUBLISH)
        text(identity)
        with store.connection(write=False) as db:
            item = db.execute('SELECT * FROM reviews WHERE id=?', (identity,)).fetchone()
        if item is None:
            raise MaintenanceError('review_not_found', 404)
        if item['user_id'] != row['user_id']:
            raise MaintenanceError('review_scope_refused', 403)
        document = decode(bytes(item['body']))
        view = review_module.validate(document, targets=_json_list(item['targets']),
                                     user_id=row['user_id'],
                                     group_id=_authority().group_id,
                                     origin=_authority().origin, now=_now())
        return jsonify(version=1, id=identity, state=item['state'], review=view,
                       expires=item['expires'])

    @app.post('/api/publish', endpoint='service.publish')
    @_guard
    def publish():
        value = body()
        fields(value, 'id confirm')
        if value['confirm'] is not True:
            raise MaintenanceError('explicit_publish_required', 400)
        row = require(permission=permissions.CONTENT_PUBLISH)
        text(value['id'])
        with store.connection() as db:
            item = db.execute('SELECT * FROM reviews WHERE id=?', (value['id'],)).fetchone()
            if item is None:
                raise MaintenanceError('review_not_found', 404)
            if item['user_id'] != row['user_id'] or item['session_id'] != row['id']:
                raise MaintenanceError('review_scope_refused', 403)
            if item['expires'] <= _now():
                raise MaintenanceError('review_expired', 410)
            document = decode(bytes(item['body']))
            targets = _json_list(item['targets'])
            digest = review_module.ticket_digest(document, targets, row['user_id'])
            if not hmac.compare_digest(digest, item['digest']):
                raise MaintenanceError('review_changed', 409)
            view = review_module.validate(document, targets=targets, user_id=row['user_id'],
                                          group_id=_authority().group_id,
                                          origin=_authority().origin, now=_now())
            if item['approval'] is None:
                signed = _authority().sign_publication(db, row['user_id'],
                                                       document['plan'], targets, _now())
                nonce = secrets.token_hex(32)
                receipt = _authority().sign_receipt(document['plan'], signed['approval'],
                                                    document['plan']['policy_version'], nonce,
                                                    _now())
                db.execute('UPDATE reviews SET state=?, approval=?, receipt=? WHERE id=?',
                           ('signed', encode(signed), encode(receipt), value['id']))
                item = db.execute('SELECT * FROM reviews WHERE id=?', (value['id'],)).fetchone()
            signed = decode(bytes(item['approval']))
            receipt = decode(bytes(item['receipt']))
        try:
            result = _content().approve(document['plan']['id'], signed['approval'],
                                        signed['chain'], receipt['receipt'],
                                        receipt['acceptance_key'])
        except ContentRefused as error:
            with store.connection() as db:
                db.execute("UPDATE reviews SET state='signed' WHERE id=?", (value['id'],))
            return jsonify(version=1, state='signed', pending=True, error=error.code), 202
        with store.connection() as db:
            db.execute("UPDATE reviews SET state='committed', commit_reference=? WHERE id=?",
                       (result['distribution']['package_id'], value['id']))
        return jsonify(version=1, state='committed', confirmation=view['confirmation'],
                       distribution=result['distribution'])

    @app.get('/api/review/<identity>/status', endpoint='service.review_status')
    @_guard
    def review_status(identity):
        row = require(trusted=False)
        with store.connection(write=False) as db:
            item = db.execute('SELECT * FROM reviews WHERE id=?', (identity,)).fetchone()
        if item is None or item['user_id'] != row['user_id']:
            raise MaintenanceError('review_not_found', 404)
        return jsonify(version=1, state=item['state'], commit=item['commit_reference'])

    @app.post('/api/tls/renew', endpoint='service.tls_renew')
    @_guard
    def tls_renew():
        issuer = app.extensions.get('maintenance_tls_authority')
        if issuer is None:
            raise MaintenanceError('tls_issuer_unconfigured', 503)
        raw = request.get_data(cache=True)
        if len(raw) > 32768:
            raise MaintenanceError('request_limit', 413)
        issuer.authenticate(request.headers, raw, request.method, request.path)
        value = body(limit=32768)
        fields(value, 'csr')
        return jsonify(version=1, **issuer.issue('content', value['csr']))

    # -- maintenance cycle / relocation -------------------------------------
    @app.get('/api/maintenance/authority/request', endpoint='service.maintenance_authority_request')
    @_guard
    def maintenance_authority_request():
        from .offline import export_request

        actor = require(permission=permissions.SERVICE_RELOCATE)
        return jsonify(version=1, **export_request(app, actor['user_id']))

    @app.post('/api/maintenance/authority', endpoint='service.maintenance_authority')
    @_guard
    def maintenance_authority():
        actor = require(permission=permissions.SERVICE_RELOCATE)
        value = body()
        fields(value, 'user chain policy root_pin confirm' + (' lan' if isinstance(value, dict) and 'lan' in value else ''))
        # Human administrator authentication does not mint signing authority.
        # The supplied public package must authorize the retained endpoint key.
        from .offline import apply_public
        bundle = {name:value[name] for name in ('chain','policy','lan') if name in value}
        result = apply_public(app, value['user'], bundle, root_pin=value['root_pin'],
                              confirm=value['confirm'], actor=actor['user_id'])
        app.extensions['maintenance_content_sessions'].clear()
        from .authority_delivery import flush
        try:
            delivered = flush(store, _content())
        except ContentRefused:
            delivered = False
        return jsonify(version=1, recovered=result, delivery_pending=not delivered), (200 if delivered else 202)

    @app.get('/api/maintenance', endpoint='service.maintenance')
    @_guard
    def maintenance():
        return jsonify(version=1, maintenance=cycle.status(store),
                       recovery=cycle.recovery(store),
                       authority_lifecycle=cycle.authority_status(store, app.config))

    @app.post('/api/maintenance/record', endpoint='service.maintenance_record')
    @_guard
    def maintenance_record():
        require(permission=permissions.SERVICE_RELOCATE)
        value = body()
        fields(value, 'confirm')
        if value['confirm'] is not True:
            raise MaintenanceError('confirmation_required')
        return jsonify(version=1, maintenance=cycle.record(store, _now()))

    @app.get('/api/relocate/manifest', endpoint='service.relocate_manifest')
    @_guard
    def relocate_manifest():
        placement = store.placement()
        with store.connection(write=False) as db:
            local = dict(
                placement=placement,
                users=[dict(row) for row in db.execute(
                    'SELECT id,role,blocked FROM users ORDER BY id')],
                grants=[dict(row) for row in db.execute(
                    'SELECT subject_type,subject_id,bundle,CAST(groups AS TEXT) AS groups '
                    'FROM grants ORDER BY id')],
                reviewer_keys=[dict(row) for row in db.execute(
                    'SELECT user_id,device_id,role,expires FROM keys ORDER BY user_id')],
                placement_generation=(placement or {}).get('generation'))
        local['digest'] = sha(encode(local))
        return jsonify(version=1, local=local, content=_content().manifest())

    @app.post('/api/relocate/fence', endpoint='service.relocate_fence')
    @_guard
    def relocate_fence():
        row = require(permission=permissions.SERVICE_RELOCATE)
        value = body()
        fields(value, 'generation origin reason')
        generation = int(value['generation'])
        placement = store.placement()
        if placement is None or placement['generation'] != generation:
            raise MaintenanceError('placement_generation_conflict', 409)
        # Only the moved side is fenced. Its counterpart keeps serving delivery and
        # storage; a content-side move fences the content service through its own API.
        local = store.fence(value['reason'], handoff=True)
        return jsonify(version=1, state='fenced', local=local, generation=generation,
                       origin=value['origin'])

    @app.post('/api/relocate/redeem', endpoint='service.relocate_redeem')
    @_guard
    def relocate_redeem():
        """Single-use cutover claim; reachable only at the fenced source."""
        value = body()
        fields(value, 'transfer secret destination')
        if not store.fenced():
            raise MaintenanceError('placement_not_fenced', 409)
        result = store.redeem_transfer(value['transfer'], value['secret'],
                                       value['destination'], _now())
        return jsonify(version=1, **result)

    @app.post('/api/relocate/activate', endpoint='service.relocate_activate')
    @_guard
    def relocate_activate():
        value = body()
        fields(value, 'generation fence origin')
        with store.connection() as db:
            live = db.execute('SELECT id FROM users WHERE blocked=0').fetchall()
        if not live:
            raise MaintenanceError('relocation_requires_accounts', 409)
        store.activate(value['generation'], value['fence'], value['origin'],
                       transfer=value.get('transfer'))
        return jsonify(version=1, state='active')

    return app


if __name__ == '__main__':
    raise SystemExit('Use tools/kiosk_maintenance_setup.py to create a configured service.')
