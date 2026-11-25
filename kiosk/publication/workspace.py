"""Transactional disposable Events workspace, browser sessions and immutable plans.

This database is separate from published Events. Never call legacy Events write
routes as part of saving here. No private publisher/authority key is stored here.
"""
from contextlib import contextmanager
from collections import deque
import secrets
import sqlite3
import time
from pathlib import Path

from kiosk.delivery.protocol import decode, digest, encode, sha, text
from kiosk.features import events
from . import authority, page_release, pages
from .mapping import SETTINGS_LIMIT, settings as mapped_settings
from kiosk.trust.crypto import key_id

IDLE_SECONDS = 15 * 60
SESSION_SECONDS = 4 * 3600
CHALLENGE_SECONDS = 90
MAX_OBJECTS = 1000
MAX_OBJECT_BYTES = 32768
MAX_WORKSPACE_BYTES = 256 * 1024 * 1024
MAX_SETTINGS_BYTES = 8192
STAGE_SECONDS = 15 * 60


class WorkspaceError(ValueError):
    def __init__(self, code, status=400):
        self.code, self.status = code, status
        super().__init__(code)


def _exact_version(value, minimum=0):
    if type(value) is not int or not minimum <= value < 2**63:
        raise WorkspaceError('invalid_version')
    return value


class Workspace:
    def __init__(self, path, root_spki, group_id, origin, *, clock=time.time, stage6_pages=False):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.root_spki = bytes(root_spki)
        self.group_id, self.origin, self.clock = text(group_id), authority.origin(origin), clock
        self.stage6_pages = stage6_pages
        with self.db() as db:
            db.executescript('''
                CREATE TABLE IF NOT EXISTS policy (singleton INTEGER PRIMARY KEY CHECK(singleton=1), version INTEGER NOT NULL, envelope BLOB NOT NULL);
                CREATE TABLE IF NOT EXISTS objects (id TEXT PRIMARY KEY, version INTEGER NOT NULL, payload BLOB NOT NULL, author TEXT NOT NULL,
                    dependencies BLOB NOT NULL, ready INTEGER NOT NULL DEFAULT 0, published_version INTEGER NOT NULL DEFAULT 0);
                CREATE TABLE IF NOT EXISTS revisions (id TEXT NOT NULL, version INTEGER NOT NULL, payload BLOB NOT NULL,
                    author TEXT NOT NULL, dependencies BLOB NOT NULL, PRIMARY KEY(id,version));
                CREATE TABLE IF NOT EXISTS plans (id TEXT PRIMARY KEY, snapshot BLOB NOT NULL, approval BLOB, created INTEGER NOT NULL);
                CREATE TABLE IF NOT EXISTS challenges (id TEXT PRIMARY KEY, browser TEXT NOT NULL, document BLOB NOT NULL,
                    expires INTEGER NOT NULL, accepted BLOB, consumed INTEGER NOT NULL DEFAULT 0);
                CREATE TABLE IF NOT EXISTS sessions (id TEXT PRIMARY KEY, user_id TEXT NOT NULL, chain BLOB NOT NULL,
                    issued INTEGER NOT NULL, touched INTEGER NOT NULL, revoked INTEGER NOT NULL DEFAULT 0);
                CREATE TABLE IF NOT EXISTS heads (id TEXT PRIMARY KEY);
                CREATE TABLE IF NOT EXISTS settings (singleton INTEGER PRIMARY KEY CHECK(singleton=1),
                    version INTEGER NOT NULL, body BLOB NOT NULL);
                CREATE TABLE IF NOT EXISTS sequence (singleton INTEGER PRIMARY KEY CHECK(singleton=1),
                    content INTEGER NOT NULL);
                CREATE TABLE IF NOT EXISTS staged (id TEXT PRIMARY KEY, snapshot BLOB NOT NULL,
                    settings BLOB NOT NULL, content_version INTEGER NOT NULL, created INTEGER NOT NULL);
                CREATE TABLE IF NOT EXISTS feature_modules (id TEXT PRIMARY KEY,
                    enabled INTEGER NOT NULL CHECK(enabled IN (0,1)), version INTEGER NOT NULL);
                CREATE TABLE IF NOT EXISTS service_nonces (value TEXT PRIMARY KEY, seen INTEGER NOT NULL);
                CREATE TABLE IF NOT EXISTS placement (singleton INTEGER PRIMARY KEY CHECK(singleton=1),
                    mode TEXT NOT NULL, generation INTEGER NOT NULL, active INTEGER NOT NULL,
                    fence TEXT, handoff INTEGER NOT NULL DEFAULT 0,
                    counterpart TEXT NOT NULL DEFAULT '', origin TEXT NOT NULL,
                    updated INTEGER NOT NULL);
            ''')

    @contextmanager
    def db(self):
        db = sqlite3.connect(self.path, timeout=5)
        db.row_factory = sqlite3.Row
        try:
            db.execute('BEGIN IMMEDIATE')
            yield db
            db.commit()
        except BaseException:
            db.rollback()
            raise
        finally:
            db.close()

    def now(self):
        return int(self.clock())

    # -- placement / relocation fencing (content side) -----------------------
    def placement(self):
        with self.db() as db:
            row = db.execute('SELECT * FROM placement WHERE singleton=1').fetchone()
            return dict(row) if row else None

    def configure_placement(self, mode, origin, *, generation=1, counterpart='', active=True,
                            fence=None, handoff=0):
        if mode not in ('combined', 'separated'):
            raise WorkspaceError('placement_mode_refused')
        with self.db() as db:
            db.execute('DELETE FROM placement')
            db.execute('INSERT INTO placement VALUES (1,?,?,?,?,?,?,?,?)',
                       (mode, int(generation), int(active), fence, int(handoff),
                        counterpart, authority.origin(origin), self.now()))

    def fenced(self):
        row = self.placement()
        return row is not None and (not row['active'] or bool(row['fence']))

    def fence(self, reason='relocation', *, handoff=False):
        with self.db() as db:
            row = db.execute('SELECT * FROM placement WHERE singleton=1').fetchone()
            if row is None:
                raise WorkspaceError('placement_not_configured', 503)
            if not row['active']:
                return row['fence']
            fence = encode({'generation': row['generation'], 'reason': reason,
                            'at': self.now()}).decode('utf-8')
            db.execute('UPDATE placement SET active=0, fence=?, handoff=?, updated=? '
                       'WHERE singleton=1', (fence, int(handoff), self.now()))
            return fence

    def activate(self, generation, fence, origin):
        with self.db() as db:
            row = db.execute('SELECT * FROM placement WHERE singleton=1').fetchone()
            if row is None:
                raise WorkspaceError('placement_not_configured', 503)
            if row['handoff']:
                raise WorkspaceError('placement_handoff_complete', 409)
            if row['generation'] != int(generation):
                raise WorkspaceError('placement_generation_conflict', 409)
            if not isinstance(fence, str) or fence != row['fence']:
                raise WorkspaceError('placement_fence_mismatch', 409)
            if row['origin'] != authority.origin(origin):
                raise WorkspaceError('placement_origin_conflict', 409)
            db.execute('UPDATE placement SET active=1, fence=NULL, generation=generation+1, '
                       'updated=? WHERE singleton=1', (self.now(),))
            return True

    def remember_nonce(self, value, now):
        """Reject a replayed service request nonce exactly once."""
        digest(value)
        with self.db() as db:
            db.execute('DELETE FROM service_nonces WHERE seen<?', (int(now) - 3600,))
            try:
                db.execute('INSERT INTO service_nonces VALUES (?,?)', (value, int(now)))
            except sqlite3.IntegrityError:
                raise WorkspaceError('service_replay_refused', 409) from None
            if db.execute('SELECT COUNT(*) FROM service_nonces').fetchone()[0] > 20000:
                raise WorkspaceError('service_nonce_capacity', 429)
            return True

    def _capacity(self, extra=0):
        # Do not delete history or accepted data to make room. SQLite rollback
        # journals are included; failure is reported before another mutation.
        used=sum(p.stat().st_size for p in self.path.parent.glob(self.path.name+'*') if p.is_file())
        if used+extra>MAX_WORKSPACE_BYTES:
            raise WorkspaceError('workspace_full',507)

    def startup_policy(self, envelope):
        """Reopen an exactly retained expired policy without granting new rights.

        Startup must keep delivery/recovery reachable after expiry. Only an
        identical previously installed policy may take this path; every active
        operation still calls _policy() with the current clock.
        """
        raw = encode(envelope)
        with self.db() as db:
            old = db.execute('SELECT version,envelope FROM policy').fetchone()
            if old is not None and bytes(old['envelope']) != raw:
                supplied = authority.verified(envelope, self.root_spki, 'policy')
                supplied = authority.policy(envelope, self.root_spki, self.group_id,
                                             self.origin, supplied['issued'])
                if supplied['version'] < old['version']:
                    retained = decode(bytes(old['envelope']))
                    value = authority.verified(retained, self.root_spki, 'policy')
                    authority.policy(retained, self.root_spki, self.group_id,
                                     self.origin, value['issued'], floor=old['version'])
                    return
            if old is not None and bytes(old['envelope']) == raw:
                value = authority.verified(envelope, self.root_spki, 'policy')
                value = authority.policy(envelope, self.root_spki, self.group_id,
                                         self.origin, value['issued'])
                if self.now() >= value['expires']:
                    return
        self.install_policy(envelope)

    def install_policy(self, envelope):
        with self.db() as db:
            old = db.execute('SELECT * FROM policy').fetchone()
            value = authority.policy(envelope, self.root_spki, self.group_id, self.origin,
                                     self.now(), floor=old['version'] if old else 0)
            raw = encode(envelope)
            if old and old['version'] == value['version'] and bytes(old['envelope']) != raw:
                raise WorkspaceError('policy_generation_conflict', 409)
            db.execute('INSERT OR REPLACE INTO policy VALUES (1,?,?)', (value['version'], raw))

    def _policy(self, db):
        row = db.execute('SELECT envelope FROM policy').fetchone()
        if row is None:
            raise WorkspaceError('publisher_setup_required', 503)
        envelope = decode(row['envelope'])
        return authority.policy(envelope, self.root_spki, self.group_id, self.origin, self.now()), envelope

    def _device(self, db, chain):
        current, _ = self._policy(db)
        return authority.permission(chain, self.root_spki, current, self.now())

    def _settings(self, db):
        row = db.execute('SELECT version,body FROM settings').fetchone()
        if row is None:
            return 0, {}
        return row['version'], decode(row['body'])

    def settings(self, secret):
        with self.db() as db:
            self._session(db, secret)
            version, values = self._settings(db)
            return dict(version=version, values=values)

    def update_settings(self, secret, expected_version, values):
        """Display settings are allowlisted public data, not arbitrary config."""
        _exact_version(expected_version)
        values = mapped_settings(values)
        raw = encode(values)
        if len(raw) > MAX_SETTINGS_BYTES:
            raise WorkspaceError('settings_limit', 413)
        with self.db() as db:
            device, _ = self._session(db, secret)
            if self.stage6_pages:
                self._require_active_write(db)
                self._edit_authority(device, 'event')
            self._capacity(len(raw) * 2 + 16384)
            current, _ = self._settings(db)
            if current != expected_version:
                raise WorkspaceError('settings_version_conflict', 409)
            version = expected_version + 1
            db.execute('INSERT INTO settings VALUES (1,?,?) ON CONFLICT(singleton) DO UPDATE '
                       'SET version=excluded.version,body=excluded.body', (version, raw))
            return version

    def create_login(self, browser_secret, summary):
        if not isinstance(browser_secret, str) or len(browser_secret) != 64:
            raise WorkspaceError('browser_binding_required')
        if not isinstance(summary, str) or not 1 <= len(summary) <= 120:
            raise WorkspaceError('invalid_browser_summary')
        token = secrets.token_hex(32)
        identity, binding = sha(token.encode()), sha(browser_secret.encode())
        now = self.now()
        document = dict(version=1, action='login', id=identity, browser=binding,
                        origin=self.origin, group_id=self.group_id, summary=summary,
                        issued=now, expires=now+CHALLENGE_SECONDS)
        with self.db() as db:
            self._capacity(16384)
            db.execute('DELETE FROM challenges WHERE expires<=?', (now,))
            count = db.execute('SELECT COUNT(*) FROM challenges').fetchone()[0]
            pending = db.execute('SELECT COUNT(*) FROM challenges WHERE browser=?', (binding,)).fetchone()[0]
            if count >= 1024 or pending >= 3:
                raise WorkspaceError('login_request_limit', 429)
            db.execute('INSERT INTO challenges (id,browser,document,expires) VALUES (?,?,?,?)',
                       (identity, binding, encode(document), document['expires']))
        # Token returned only to this browser's QR. Never include it in a URL log.
        return token, document

    def challenge(self, token):
        with self.db() as db:
            row = self._challenge(db, token)
            return decode(row['document'])

    def _challenge(self, db, token):
        if not isinstance(token, str) or len(token) != 64 or any(x not in '0123456789abcdef' for x in token):
            raise WorkspaceError('login_unavailable', 404)
        row = db.execute('SELECT * FROM challenges WHERE id=?', (sha(token.encode()),)).fetchone()
        if row is None or row['expires'] <= self.now() or row['consumed']:
            raise WorkspaceError('login_unavailable', 410)
        return row

    def accept_login(self, token, envelope, chain):
        with self.db() as db:
            row = self._challenge(db, token)
            if row['accepted'] is not None:
                raise WorkspaceError('login_already_accepted', 409)
            device, signer = self._device(db, chain)
            signed = authority.verified(envelope, signer, 'login')
            expected = decode(row['document'])
            if signed != expected:
                raise WorkspaceError('login_context_changed', 409)
            db.execute('UPDATE challenges SET accepted=? WHERE id=?',
                       (encode({'chain':chain, 'envelope':envelope}), row['id']))
            return device['user_id']

    def consume_login(self, token, browser_secret):
        with self.db() as db:
            row = self._challenge(db, token)
            if sha(browser_secret.encode()) != row['browser']:
                raise WorkspaceError('browser_binding_refused', 403)
            if row['accepted'] is None:
                return None
            accepted = decode(row['accepted'])
            device, _ = self._device(db, accepted['chain'])
            session_secret = secrets.token_hex(32)
            now = self.now()
            db.execute('DELETE FROM sessions WHERE issued<=?',(now-SESSION_SECONDS,))
            if db.execute('SELECT COUNT(*) FROM sessions').fetchone()[0]>=4096:
                raise WorkspaceError('session_capacity',429)
            if db.execute('SELECT COUNT(*) FROM sessions WHERE user_id=? AND revoked=0',(device['user_id'],)).fetchone()[0]>=32:
                raise WorkspaceError('user_session_capacity',429)
            db.execute('UPDATE challenges SET consumed=1 WHERE id=?', (row['id'],))
            db.execute('INSERT INTO sessions VALUES (?,?,?,?,?,0)',
                       (sha(session_secret.encode()), device['user_id'], encode({'chain':accepted['chain']}), now, now))
            return session_secret, device

    def _session(self, db, secret):
        if not isinstance(secret, str) or len(secret) != 64:
            raise WorkspaceError('session_required', 401)
        row = db.execute('SELECT * FROM sessions WHERE id=?', (sha(secret.encode()),)).fetchone()
        now = self.now()
        if (row is None or row['revoked'] or now < row['touched'] or
                now-row['issued'] >= SESSION_SECONDS or now-row['touched'] >= IDLE_SECONDS):
            raise WorkspaceError('session_expired', 401)
        device, _ = self._device(db, decode(row['chain'])['chain'])
        db.execute('UPDATE sessions SET touched=? WHERE id=?', (now,row['id']))
        return device, row

    def authenticate(self, secret):
        with self.db() as db:
            return self._session(db,secret)[0]

    def sessions(self, secret):
        with self.db() as db:
            device, _ = self._session(db,secret)
            return [dict(row) for row in db.execute(
                'SELECT id,user_id,issued,touched,revoked FROM sessions WHERE user_id=? ORDER BY issued',
                (device['user_id'],))]

    def terminate(self, secret, identity=None):
        with self.db() as db:
            device, own = self._session(db,secret)
            identity = identity or own['id']
            row = db.execute('SELECT user_id FROM sessions WHERE id=?',(identity,)).fetchone()
            if row is None:
                raise WorkspaceError('session_not_found',404)
            if row['user_id'] != device['user_id'] and device['role'] != 'administrator':
                raise WorkspaceError('administrator_required',403)
            db.execute('UPDATE sessions SET revoked=1 WHERE id=?',(identity,))

    def save(self, secret, identity, expected_version, payload, dependencies):
        text(identity)
        if pages.IDENTITY.fullmatch(identity):
            raise WorkspaceError('page_route_required')
        if self.stage6_pages:
            try:
                pages.kind(identity)
            except pages.PageError as error:
                raise WorkspaceError(str(error)) from None
        return self._save(secret, identity, expected_version, payload, dependencies, page=False)

    @staticmethod
    def _edit_authority(device, object_kind):
        scope = device.get('scope')
        if scope is not None and 'edit' not in scope['permissions']:
            raise WorkspaceError('edit_permission_required', 403)
        if object_kind in ('profile', 'assignment') and device['role'] != 'administrator':
            raise WorkspaceError('administrator_required', 403)

    def _require_active_write(self, db):
        if self.stage6_pages:
            row = db.execute('SELECT active,fence FROM placement WHERE singleton=1').fetchone()
            if row is not None and (not row['active'] or row['fence']):
                raise WorkspaceError('service_fenced', 409)

    def _events_status(self, db):
        row = db.execute("SELECT enabled,version FROM feature_modules WHERE id='events'").fetchone()
        enabled, version = (bool(row['enabled']), row['version']) if row else (True, 0)
        state = 'disabled'
        if enabled:
            try:
                state = 'ready' if events.health()['status'] == 'ok' else 'faulted'
            except (RuntimeError, OSError, KeyError, TypeError, ValueError):
                state = 'faulted'
        return dict(id='events', enabled=enabled, version=version, state=state)

    def module_status(self, secret):
        with self.db() as db:
            self._session(db, secret)
            return self._events_status(db)

    def set_events_enabled(self, secret, expected_version, enabled):
        _exact_version(expected_version)
        if type(enabled) is not bool:
            raise WorkspaceError('invalid_module_setting')
        with self.db() as db:
            device, _ = self._session(db, secret)
            self._require_active_write(db)
            self._edit_authority(device, 'profile')
            status = self._events_status(db)
            if status['version'] != expected_version:
                raise WorkspaceError('module_version_conflict', 409)
            if status['enabled'] != enabled:
                db.execute("INSERT INTO feature_modules VALUES ('events',?,?) "
                           'ON CONFLICT(id) DO UPDATE SET enabled=excluded.enabled,version=excluded.version',
                           (enabled, expected_version + 1))
            return self._events_status(db)

    def _require_events(self, db, object_kind):
        if self.stage6_pages and object_kind in ('event', 'dataset'):
            if self._events_status(db)['state'] != 'ready':
                raise WorkspaceError('events_module_unavailable', 503)

    def save_page(self, secret, identity, expected_version, payload, dependencies):
        return self._save(secret, identity, expected_version, payload, dependencies, page=True)

    def _save(self, secret, identity, expected_version, payload, dependencies, *, page):
        text(identity)
        _exact_version(expected_version)
        if not page:
            events.validate_payload(payload, WorkspaceError)
        elif len(encode(payload)) > MAX_OBJECT_BYTES:
            raise WorkspaceError('draft_limit', 413)
        if not isinstance(dependencies, dict) or len(dependencies)>100:
            raise WorkspaceError('dependency_limit')
        for name, version in dependencies.items():
            text(name); _exact_version(version,1)
        if page:
            try:
                object_kind = pages.kind(identity)
                pages.validate_dependencies(identity, payload, dependencies)
            except pages.PageError as error:
                raise WorkspaceError(str(error)) from None
        else:
            object_kind = 'event'
            if any(pages.IDENTITY.fullmatch(name) for name in dependencies):
                raise WorkspaceError('incompatible_page_dependency')
        with self.db() as db:
            device,_ = self._session(db,secret)
            self._require_active_write(db)
            self._edit_authority(device, object_kind)
            self._require_events(db, object_kind)
            self._capacity(len(encode(payload))*2+16384)
            if db.execute('SELECT COUNT(*) FROM revisions').fetchone()[0]>=10000:
                raise WorkspaceError('revision_capacity',507)
            old=db.execute('SELECT version FROM objects WHERE id=?',(identity,)).fetchone()
            if (old['version'] if old else 0)!=expected_version:
                raise WorkspaceError('draft_version_conflict',409)
            if not old and db.execute('SELECT COUNT(*) FROM objects').fetchone()[0]>=MAX_OBJECTS:
                raise WorkspaceError('draft_object_limit',413)
            if object_kind == 'assignment':
                for row in db.execute("SELECT id,payload FROM objects WHERE id LIKE 'assignment-%' AND id!=?", (identity,)):
                    if decode(row['payload'])['device'] == payload['device']:
                        raise WorkspaceError('duplicate_page_assignment', 409)
                if old:
                    previous = db.execute('SELECT payload FROM objects WHERE id=?', (identity,)).fetchone()
                    if decode(previous['payload'])['device'] != payload['device']:
                        raise WorkspaceError('assignment_identity_changed', 409)
                scope = device.get('scope')
                if scope is not None and payload['device'] not in scope['targets']:
                    raise WorkspaceError('publisher_scope_refused', 403)
            version=expected_version+1
            raw,refs=encode(payload),encode(dependencies)
            db.execute('INSERT INTO revisions VALUES (?,?,?,?,?)',(identity,version,raw,device['user_id'],refs))
            db.execute('''INSERT INTO objects(id,version,payload,author,dependencies) VALUES (?,?,?,?,?)
                ON CONFLICT(id) DO UPDATE SET version=excluded.version,payload=excluded.payload,
                    author=excluded.author,dependencies=excluded.dependencies,ready=0''',
                (identity,version,raw,device['user_id'],refs))
            dependants = {}
            for row in db.execute('SELECT id,dependencies FROM objects'):
                for dependency in decode(row['dependencies']):
                    dependants.setdefault(dependency, []).append(row['id'])
            invalidated = {identity}
            pending = deque([identity])
            while pending:
                for dependant in dependants.get(pending.popleft(), ()):
                    if dependant not in invalidated:
                        invalidated.add(dependant)
                        pending.append(dependant)
            db.executemany('UPDATE objects SET ready=0 WHERE id=?', ((item,) for item in invalidated))
            return version

    def _ready(self, db, row, visiting=None, verified=None):
        visiting = set() if visiting is None else visiting
        verified = set() if verified is None else verified
        if row['id'] in verified:
            return
        if row['id'] in visiting:
            raise WorkspaceError('dependency_cycle',409)
        visiting.add(row['id'])
        dependencies = {}
        for identity,version in decode(row['dependencies']).items():
            dep=db.execute('SELECT * FROM objects WHERE id=?',(identity,)).fetchone()
            if dep is None or dep['version']!=version or (not dep['ready'] and dep['published_version']!=version):
                raise WorkspaceError('dependency_not_ready',409)
            self._ready(db, dep, visiting, verified)
            dependencies[identity] = decode(dep['payload'])
        if row['id'].startswith('page-'):
            try:
                pages.validate_layout_targets(decode(row['payload']), dependencies)
            except pages.PageError as error:
                raise WorkspaceError(str(error), 409) from None
        visiting.remove(row['id'])
        verified.add(row['id'])

    def ready(self, secret, identity, version):
        return self._mark_ready(secret, identity, version, page=False)

    def ready_page(self, secret, identity, version):
        return self._mark_ready(secret, identity, version, page=True)

    def _mark_ready(self, secret, identity, version, *, page):
        text(identity)
        if bool(pages.IDENTITY.fullmatch(identity)) != page:
            raise WorkspaceError('incompatible_page_route')
        if self.stage6_pages:
            try:
                pages.kind(identity)
            except pages.PageError as error:
                raise WorkspaceError(str(error)) from None
        with self.db() as db:
            device, _ = self._session(db,secret)
            self._require_active_write(db)
            object_kind = pages.kind(identity) if page else 'event'
            self._edit_authority(device, object_kind)
            self._require_events(db, object_kind)
            row=db.execute('SELECT * FROM objects WHERE id=?',(identity,)).fetchone()
            if row is None or row['version']!=_exact_version(version,1):
                raise WorkspaceError('draft_version_conflict',409)
            if page and identity.startswith('assignment-') and device.get('scope') is not None:
                if decode(row['payload'])['device'] not in device['scope']['targets']:
                    raise WorkspaceError('publisher_scope_refused', 403)
            self._ready(db,row)
            db.execute('UPDATE objects SET ready=1 WHERE id=?',(identity,))

    def objects(self, secret):
        return self._objects(secret, include_pages=False)

    def page_objects(self, secret):
        return self._objects(secret, include_pages=True)

    def _objects(self, secret, *, include_pages):
        with self.db() as db:
            device, _ = self._session(db,secret)
            scope = device.get('scope')
            return [dict(id=r['id'],version=r['version'],payload=decode(r['payload']),author=r['author'],
                         dependencies=decode(r['dependencies']),ready=bool(r['ready']),published_version=r['published_version'])
                    for r in db.execute('SELECT * FROM objects ORDER BY id')
                    if (include_pages or not pages.IDENTITY.fullmatch(r['id']))
                    and (scope is None or not r['id'].startswith('assignment-')
                         or decode(r['payload'])['device'] in scope['targets'])]

    def page_plan(self, secret):
        """Read-only draft selection. It does not authorize or publish anything."""
        with self.db() as db:
            device, _ = self._session(db, secret)
            plan, snapshot = self._page_plan(db, device.get('scope'))
            return dict(plan, revision_sha256=sha(encode(dict(plan=plan, objects=snapshot))))

    def page_target_preview(self, secret, device_id, target, revision_sha256):
        """Render inputs for the exact current proposed revision, never public."""
        digest(revision_sha256)
        text(device_id)
        with self.db() as db:
            device, _ = self._session(db, secret)
            scope = device.get('scope')
            if scope is not None and device_id not in scope['targets']:
                raise WorkspaceError('publisher_scope_refused', 403)
            plan, snapshot = self._page_plan(db, scope)
            if sha(encode(dict(plan=plan, objects=snapshot))) != revision_sha256:
                raise WorkspaceError('prepared_snapshot_changed', 409)
            try:
                projected, selected_events = pages.target_content(snapshot, device_id, target)
                public = events.derive(selected_events, {}, 1) if selected_events else dict(events=[], tags=[])
            except (pages.PageError, events.MappingError, KeyError):
                raise WorkspaceError('target_preview_unavailable', 409) from None
            return dict(page=projected, events=public['events'], tags=public['tags'])

    def _page_heads(self, db):
        """Only v2 plans belong to the page-release ancestry line."""
        result = []
        for row in db.execute('SELECT id FROM heads ORDER BY id'):
            plan = db.execute('SELECT snapshot FROM plans WHERE id=? AND approval IS NOT NULL',
                              (row['id'],)).fetchone()
            if plan is not None and decode(plan['snapshot']).get('version') == 2:
                result.append(row['id'])
        return result

    def page_release_context(self, secret, parents=None):
        """Freeze inputs for one v2 candidate without writing a plan or pointer."""
        if not self.stage6_pages:
            raise WorkspaceError('page_workspace_unavailable', 404)
        if parents is not None and not isinstance(parents, (list, tuple)):
            raise WorkspaceError('page_release_parent_limit')
        with self.db() as db:
            device, session = self._session(db, secret)
            self._require_active_write(db)
            plan, snapshot = self._page_plan(db, device.get('scope'))
            revision = dict(plan=plan, objects=snapshot)
            page_release.validate_revision(revision)
            policy, policy_envelope = self._policy(db)
            chain = decode(bytes(session['chain']))['chain']
            granted, signer = self._device(db, chain)
            if granted['user_id'] != device['user_id']:
                raise WorkspaceError('publisher_scope_refused', 403)
            now = self.now()
            expires = min(granted['expires'], policy['expires'],
                          now + authority.MAX_PLAN_SECONDS)
            if expires <= now:
                raise WorkspaceError('publication_authority_expired', 403)
            authorization = dict(group_id=self.group_id, origin=self.origin,
                                 user_id=granted['user_id'], device_id=key_id(signer),
                                 policy_version=policy['version'], issued=now,
                                 expires=expires)
            # Parents are server-managed: every new revision descends from all
            # current approved v2 heads. A caller-supplied ancestor is merged in
            # and still verified by hash in page_release/authority.
            known_heads = self._page_heads(db)
            lineage = sorted(set(str(item) for item in (parents or ())) | set(known_heads))
            return dict(revision=revision, authorization=authorization,
                        ancestry=self._ancestry(db, tuple(lineage)),
                        known_heads=known_heads, parents=lineage)

    def store_page_candidate(self, secret, document):
        """Persist an exact v2 plan only if the frozen revision is still current."""
        if not isinstance(document, dict) or document.get('version') != 2:
            raise WorkspaceError('page_release_document_version')
        with self.db() as db:
            device, session = self._session(db, secret)
            self._require_active_write(db)
            now = self.now()
            page_release.validate_document(document, now=now,
                                           known_heads=self._page_heads(db))
            plan, snapshot = self._page_plan(db, device.get('scope'))
            if document['revision'] != dict(plan=plan, objects=snapshot):
                raise WorkspaceError('prepared_snapshot_changed', 409)
            if (document['plan']['group_id'] != self.group_id
                    or document['plan']['origin'] != self.origin
                    or document['plan']['user_id'] != device['user_id']):
                raise WorkspaceError('publisher_scope_refused', 403)
            chain = decode(bytes(session['chain']))['chain']
            _, signer = self._device(db, chain)
            if document['plan']['device_id'] != key_id(signer):
                raise WorkspaceError('publisher_scope_refused', 403)
            row = db.execute('SELECT * FROM plans WHERE id=?', (plan_id := document['plan']['id'],)).fetchone()
            raw = encode(document)
            if row is not None:
                if bytes(row['snapshot']) != raw:
                    raise WorkspaceError('plan_identity_conflict', 409)
                return document
            if len(encode(document)) > 2 * 1024 * 1024:
                raise WorkspaceError('plan_size_limit', 413)
            db.execute('INSERT INTO plans VALUES (?,?,NULL,?)', (plan_id, raw, now))
            return document

    def page_candidate(self, secret, identity):
        """Only the authenticated owner may read an exact v2 candidate."""
        text(identity)
        with self.db() as db:
            device, _ = self._session(db, secret)
            row = db.execute('SELECT * FROM plans WHERE id=?', (identity,)).fetchone()
            if row is None:
                raise WorkspaceError('plan_not_found', 404)
            document = decode(row['snapshot'])
            plan = document.get('plan') if isinstance(document, dict) else None
            if (document.get('version') != 2 or not isinstance(plan, dict)
                    or plan.get('user_id') != device['user_id']
                    or plan.get('group_id') != self.group_id
                    or plan.get('origin') != self.origin):
                raise WorkspaceError('plan_not_found', 404)
            return document

    def page_settings_version(self):
        with self.db() as db:
            return self._settings(db)[0]

    def _page_plan(self, db, scope):
        current = {row['id']: row for row in db.execute('SELECT * FROM objects ORDER BY id')}
        published = {
            row['id']: row for row in db.execute(
                'SELECT r.* FROM revisions r JOIN objects o ON r.id=o.id AND r.version=o.published_version')
        }
        changed = {identity: row for identity, row in current.items()
                   if row['version'] != row['published_version']}
        reasons = {}
        events_ready = self._events_status(db)['state'] == 'ready'
        for identity, row in changed.items():
            if (scope is not None and identity.startswith('assignment-')
                    and decode(row['payload'])['device'] not in scope['targets']):
                reasons[identity] = 'target_out_of_scope'
            elif not events_ready and (identity.startswith('dataset-') or not pages.IDENTITY.fullmatch(identity)):
                reasons[identity] = 'events_module_unavailable'
            elif not row['ready']:
                reasons[identity] = 'working'
            else:
                try:
                    self._ready(db, row)
                except WorkspaceError as error:
                    reasons[identity] = error.code
        # A group revision contains one version of each object. Preserve pinned
        # published dependants until their consistent replacements are ready.
        while True:
            active = published | {key: row for key, row in changed.items() if key not in reasons}
            rejected = {}
            for identity, row in active.items():
                for dependency, version in decode(row['dependencies']).items():
                    actual = active.get(dependency)
                    if actual is not None and actual['version'] == version:
                        continue
                    if identity in changed and identity not in reasons:
                        rejected[identity] = 'dependency_not_in_plan'
                    elif dependency in changed and dependency not in reasons:
                        rejected[dependency] = 'published_dependant_pinned'
            if not rejected:
                break
            reasons.update(rejected)

        def entry(identity, row):
            return dict(id=identity, version=row['version'], author=row['author'])

        plan = dict(
            included=[entry(identity, row) for identity, row in changed.items() if identity not in reasons],
            excluded=[dict(entry(identity, row), reason=reasons[identity])
                      for identity, row in changed.items()
                      if identity in reasons and reasons[identity] != 'target_out_of_scope'])
        snapshot = {identity: dict(version=row['version'], payload=decode(row['payload']),
                                   dependencies=decode(row['dependencies']), author=row['author'])
                    for identity, row in active.items()}
        return plan, snapshot

    def dataset_dependants(self, secret, identity):
        if not pages.IDENTITY.fullmatch(identity) or not identity.startswith('dataset-'):
            raise WorkspaceError('invalid_dataset_identity')
        with self.db() as db:
            self._session(db, secret)
            if db.execute('SELECT 1 FROM objects WHERE id=?', (identity,)).fetchone() is None:
                raise WorkspaceError('dataset_not_found', 404)

            def references(query):
                return sorted(row['id'] for row in db.execute(query)
                              if identity in decode(row['dependencies']))
            return dict(
                working=references("SELECT id, dependencies FROM objects WHERE id LIKE 'block-%'"),
                published=references('SELECT r.id, r.dependencies FROM revisions r '
                                     'JOIN objects o ON r.id=o.id AND r.version=o.published_version '
                                     "WHERE r.id LIKE 'block-%'"),
                deletion='stage7_recycle_bin_required')

    def _snapshot(self, db, selected):
        if not isinstance(selected, dict) or not 1<=len(selected)<=MAX_OBJECTS:
            raise WorkspaceError('plan_object_limit')
        snapshot={}
        for identity,version in sorted(selected.items()):
            text(identity);_exact_version(version,1)
            if pages.IDENTITY.fullmatch(identity):
                raise WorkspaceError('page_publication_required', 409)
            obj=db.execute('SELECT * FROM objects WHERE id=?',(identity,)).fetchone()
            if obj is None or obj['version']!=version or not obj['ready']:
                raise WorkspaceError('plan_revision_not_ready',409)
            self._ready(db,obj)
            snapshot[identity]=dict(version=version,payload=decode(obj['payload']),
                                    dependencies=decode(obj['dependencies']),author=obj['author'])
        # A dependency must be included or be exactly the published revision.
        for obj in snapshot.values():
            for identity,version in obj['dependencies'].items():
                dep=db.execute('SELECT published_version FROM objects WHERE id=?',(identity,)).fetchone()
                if selected.get(identity)!=version and (dep is None or dep['published_version']!=version):
                    raise WorkspaceError('plan_dependency_missing',409)
        return snapshot

    def freeze(self, secret, selected):
        """Freeze the exact ready revisions and assign the next public revision.

        The stage id is an unguessable capability returned only to the prepared
        browser; it is single-use at ``prepare`` and expires with the review.
        """
        with self.db() as db:
            self._session(db,secret)
            if self.stage6_pages:
                raise WorkspaceError('page_publication_required', 409)
            self._capacity(2*1024*1024)
            snapshot=self._snapshot(db,selected)
            _,values=self._settings(db)
            now=self.now()
            db.execute('DELETE FROM staged WHERE created<=?',(now-STAGE_SECONDS,))
            if db.execute('SELECT COUNT(*) FROM staged').fetchone()[0]>=128:
                raise WorkspaceError('stage_capacity',507)
            seq=db.execute('SELECT content FROM sequence').fetchone()
            version=(seq['content'] if seq else 0)+1
            db.execute('INSERT INTO sequence VALUES (1,?) ON CONFLICT(singleton) DO UPDATE SET content=excluded.content',(version,))
            identity=secrets.token_hex(32)
            db.execute('INSERT INTO staged VALUES (?,?,?,?,?)',
                       (identity,encode(snapshot),encode(values),version,now))
            return dict(stage=identity,objects=snapshot,settings=values,content_version=version)

    def staged(self, identity):
        with self.db() as db:
            return self._staged(db,identity)

    def _staged(self, db, identity):
        if (not isinstance(identity,str) or len(identity)!=64 or
                any(c not in '0123456789abcdef' for c in identity)):
            raise WorkspaceError('stage_not_found',404)
        row=db.execute('SELECT * FROM staged WHERE id=?',(identity,)).fetchone()
        if row is None or row['created']<=self.now()-STAGE_SECONDS:
            raise WorkspaceError('stage_expired',410)
        return dict(stage=row['id'],objects=decode(row['snapshot']),settings=decode(row['settings']),
                    content_version=row['content_version'])

    def discard(self, identity):
        with self.db() as db:
            db.execute('DELETE FROM staged WHERE id=?',(identity,))

    def prepare(self, secret, selected, publication, targets, parents, *, stage=None):
        """Freeze exact ready revisions. Publication is a previously verified
        delivery inventory, never an arbitrary digest accepted for signing.
        Native review must independently fetch/validate/render these bytes and
        recheck the same snapshot mapping locally.
        """
        from kiosk.display.delivery_capture import validate_metadata
        from . import mapping
        validate_metadata(publication)
        with self.db() as db:
            device,row=self._session(db,secret)
            if self.stage6_pages:
                raise WorkspaceError('page_publication_required', 409)
            self._capacity(2*1024*1024)
            if db.execute('SELECT COUNT(*) FROM plans').fetchone()[0]>=1024:
                raise WorkspaceError('plan_capacity',507)
            snapshot=self._snapshot(db,selected)
            if stage is None:
                _,values=self._settings(db)
                version=int(publication['revision'])
            else:
                frozen=self._staged(db,stage)
                values,version=frozen['settings'],frozen['content_version']
                if frozen['objects']!=snapshot:
                    raise WorkspaceError('prepared_snapshot_changed',409)
            data=mapping.public_bytes(snapshot,values,version)
            entries=[item for item in publication['package']['files'] if item['path']=='data/events.json']
            if (len(entries)!=1 or entries[0]['size']!=len(data) or
                    entries[0]['sha256']!=sha(data) or publication['revision']!=str(version)):
                raise WorkspaceError('plan_content_mapping',409)
            chain=decode(row['chain'])['chain']
            _,signer=self._device(db,chain)
            current,_=self._policy(db)
            # Reference every server-known approved head so a display that accepted
            # the previous publication can authenticate this one's ancestry.
            known=[entry['id'] for entry in db.execute('SELECT id FROM heads ORDER BY id')]
            parents=sorted(set(parents)|set(known))
            now=self.now()
            plan=dict(group_id=self.group_id,origin=self.origin,user_id=device['user_id'],
                      device_id=authority.key_id(signer),policy_version=current['version'],
                      issued=now,expires=min(device['expires'],current['expires'],
                                             now+authority.MAX_PLAN_SECONDS),
                      publication_sha256=sha(encode(publication)),dependencies_sha256=sha(encode(snapshot)),
                      renderer=publication['renderer']['build_id'],targets=targets,parents=parents)
            plan['id']=sha(encode(plan))
            authority.validate_plan(plan,now=now)
            ancestry=self._ancestry(db,parents)
            authority.check_ancestry(plan,(),ancestry)
            document=dict(plan=plan,objects=snapshot,publication=publication,ancestry=ancestry,
                          settings=values,content_version=version)
            if len(encode(document))>2*1024*1024:
                raise WorkspaceError('plan_size_limit',413)
            db.execute('INSERT INTO plans VALUES (?,?,NULL,?)',(plan['id'],encode(document),now))
            if stage is not None:
                db.execute('DELETE FROM staged WHERE id=?',(stage,))
            return document


    def create_service_session(self, user_id, chain, *, label='maintenance'):
        """Issue one content-side session to the trusted Maintenance service.

        The service authenticates over its own HTTPS contract; this session only
        scopes draft/plan operations to the verified chain and is never given to a
        browser. The caller must already have proven the same user over there.
        """
        text(user_id, 64)
        with self.db() as db:
            device, _ = self._device(db, chain)
            if device['user_id'] != user_id:
                raise WorkspaceError('publisher_scope_refused', 403)
            now = self.now()
            db.execute('DELETE FROM sessions WHERE issued<=?',(now-SESSION_SECONDS,))
            if db.execute('SELECT COUNT(*) FROM sessions').fetchone()[0]>=4096:
                raise WorkspaceError('session_capacity',429)
            if db.execute('SELECT COUNT(*) FROM sessions WHERE user_id=? AND revoked=0',
                          (user_id,)).fetchone()[0]>=32:
                raise WorkspaceError('user_session_capacity',429)
            secret = secrets.token_hex(32)
            db.execute('INSERT INTO sessions VALUES (?,?,?,?,?,0)',
                       (sha(secret.encode()), user_id, encode({'chain': chain}), now, now))
            return secret

    def history(self, limit=100):
        """Committed publications for preservation/relocation verification."""
        limit = int(limit)
        if not 1 <= limit <= 500:
            raise WorkspaceError('history_limit')
        with self.db() as db:
            rows = db.execute('SELECT * FROM plans WHERE approval IS NOT NULL '
                              'ORDER BY created DESC LIMIT ?', (limit,)).fetchall()
            result = []
            for row in rows:
                document = decode(row['snapshot'])
                plan = document['plan']
                item = dict(id=row['id'], created=row['created'],
                            user_id=plan['user_id'], device_id=plan['device_id'],
                            targets=plan['targets'])
                if document.get('version') == 2:
                    item.update(version=2, revision_sha256=plan['revision_sha256'],
                                dependencies_sha256=plan['dependencies_sha256'],
                                parents=plan['parents'])
                else:
                    item.update(version=1,
                                publication_sha256=plan['publication_sha256'],
                                dependencies_sha256=plan['dependencies_sha256'],
                                content_version=document.get('content_version'))
                result.append(item)
            return result

    def preserve_report(self):
        """Explicit count of work that must survive logout/blocking/revocation."""
        with self.db() as db:
            return dict(objects=db.execute('SELECT COUNT(*) FROM objects').fetchone()[0],
                        revisions=db.execute('SELECT COUNT(*) FROM revisions').fetchone()[0],
                        plans=db.execute('SELECT COUNT(*) FROM plans').fetchone()[0],
                        approved=db.execute('SELECT COUNT(*) FROM plans WHERE approval IS NOT NULL'
                                            ).fetchone()[0])

    def _ancestry(self,db,parents):
        """Closest retained records first. A bounded partial proof may suffice
        for a recently connected display; a larger offline gap is refused by that
        display until more history/an explicitly reviewed merge is supplied. Do
        not block all future publications when the total retained graph grows.
        """
        found={}
        seen=set()
        pending=deque(parents)
        while pending:
            identity=pending.popleft()
            if identity in seen:
                continue
            seen.add(identity)
            row=db.execute('SELECT snapshot FROM plans WHERE id=? AND approval IS NOT NULL',(identity,)).fetchone()
            if row is None:
                continue
            plan=decode(row['snapshot'])['plan']
            if (len(found)>=authority.MAX_ANCESTRY_NODES or
                    len(encode({'nodes':[*found.values(),plan]}))>authority.MAX_ANCESTRY_BYTES):
                break
            found[identity]=plan
            pending.extend(plan['parents'])
        return [found[k] for k in sorted(found)]

    def candidate(self, identity):
        with self.db() as db:
            row=db.execute('SELECT * FROM plans WHERE id=?',(identity,)).fetchone()
            if row is None:
                raise WorkspaceError('plan_not_found',404)
            return decode(row['snapshot'])

    def approved(self, identity):
        """The frozen document plus the stored publisher proof, for distribution."""
        with self.db() as db:
            row=db.execute('SELECT snapshot,approval FROM plans WHERE id=?',(identity,)).fetchone()
            if row is None:
                raise WorkspaceError('plan_not_found',404)
            if row['approval'] is None:
                raise WorkspaceError('plan_not_approved',409)
            return decode(row['snapshot']),decode(row['approval'])

    def plan_state(self, identity):
        with self.db() as db:
            row=db.execute('SELECT approval FROM plans WHERE id=?',(identity,)).fetchone()
            if row is None:
                raise WorkspaceError('plan_not_found',404)
            return dict(approved=row['approval'] is not None)

    def approve(self, identity, envelope, chain):
        """Compare all frozen dependencies again in the same commit transaction.
        This stores authorization only; a distributor must activate this exact
        verified snapshot, never re-export the mutable working database.
        """
        with self.db() as db:
            row=db.execute('SELECT * FROM plans WHERE id=?',(identity,)).fetchone()
            if row is None:
                raise WorkspaceError('plan_not_found',404)
            document=decode(row['snapshot'])
            if document.get('version') == 2:
                return self._approve_page(db, row, document, envelope, chain)
            current,policy=self._policy(db)
            heads=[r['id'] for r in db.execute('SELECT id FROM heads ORDER BY id')]
            plan,_=authority.approval(envelope,chain,policy,self.root_spki,self.group_id,self.origin,self.now(),
                                      known_heads=heads,ancestry=document.get('ancestry',[]))
            if plan!=document['plan']:
                raise WorkspaceError('prepared_plan_changed',409)
            proof=encode(dict(approval=envelope,chain=chain,policy=policy,ancestry=document.get('ancestry',[])))
            if row['approval'] is not None:
                if bytes(row['approval'])!=proof:
                    raise WorkspaceError('plan_approval_conflict',409)
                return document
            if self.stage6_pages:
                raise WorkspaceError('page_publication_required', 409)
            if self.now()-row['created']>=15*60:
                raise WorkspaceError('prepared_review_expired',410)
            for identity,obj in document['objects'].items():
                actual=db.execute('SELECT * FROM objects WHERE id=?',(identity,)).fetchone()
                if (actual is None or actual['version']!=obj['version'] or not actual['ready'] or
                        decode(actual['payload'])!=obj['payload'] or decode(actual['dependencies'])!=obj['dependencies']):
                    raise WorkspaceError('prepared_revision_changed',409)
                self._ready(db,actual)
            db.execute('UPDATE plans SET approval=? WHERE id=?',(proof,plan['id']))
            db.execute('DELETE FROM heads')
            db.execute('INSERT INTO heads VALUES (?)',(plan['id'],))
            for identity,obj in document['objects'].items():
                db.execute('UPDATE objects SET published_version=? WHERE id=?',(obj['version'],identity))
            return document

    def _approve_page(self, db, row, document, envelope, chain):
        """Recheck a v2 graph, signer, ancestry and target lineage before storing."""
        if not self.stage6_pages:
            raise WorkspaceError('page_workspace_unavailable', 404)
        current, policy_envelope = self._policy(db)
        heads = self._page_heads(db)
        try:
            plan, _ = authority.page_approval(
                envelope, chain, policy_envelope, self.root_spki, self.group_id,
                self.origin, self.now(), known_heads=heads,
                ancestry=document.get('ancestry', []))
        except (TypeError, KeyError, ValueError) as error:
            code = str(error) if isinstance(error, ValueError) else 'publisher_plan'
            status = 403 if code in ('publisher_scope_refused', 'publisher_revoked',
                                     'publisher_approval_scope') else 409
            raise WorkspaceError(code, status) from None
        if plan != document['plan']:
            raise WorkspaceError('prepared_plan_changed', 409)
        proof = encode(dict(approval=envelope, chain=chain,
                            policy=policy_envelope,
                            ancestry=document.get('ancestry', [])))
        if row['approval'] is not None:
            if bytes(row['approval']) != proof:
                raise WorkspaceError('plan_approval_conflict', 409)
            return document
        if self.now() - row['created'] >= 15 * 60:
            raise WorkspaceError('prepared_review_expired', 410)
        granted, signer = self._device(db, chain)
        if (plan['user_id'] != granted['user_id']
                or plan['device_id'] != key_id(signer)):
            raise WorkspaceError('publisher_approval_scope', 403)
        plan_now, snapshot_now = self._page_plan(db, granted.get('scope'))
        if dict(plan=plan_now, objects=snapshot_now) != document['revision']:
            raise WorkspaceError('prepared_revision_changed', 409)
        # Recheck every active snapshot row against the newest working row in
        # this same commit transaction. An older published revision is valid
        # only while it is still the newest row; a newer excluded draft of that
        # object invalidates the review even when the draft stays out of the
        # candidate. Historical rows are checked against their exact retained
        # revision, and ``_ready`` is invoked only for newly included versions.
        included = {entry['id'] for entry in plan_now['included']}
        for identity, obj in document['revision']['objects'].items():
            actual = db.execute('SELECT * FROM objects WHERE id=?',
                                (identity,)).fetchone()
            historical = db.execute(
                'SELECT * FROM revisions WHERE id=? AND version=?',
                (identity, obj['version'])).fetchone()
            if (actual is None or historical is None
                    or actual['version'] != obj['version']
                    or decode(historical['payload']) != obj['payload']
                    or decode(historical['dependencies']) != obj['dependencies']
                    or historical['author'] != obj['author']):
                raise WorkspaceError('prepared_revision_changed', 409)
            if identity in included:
                if (not actual['ready']
                        or decode(actual['payload']) != obj['payload']
                        or decode(actual['dependencies']) != obj['dependencies']):
                    raise WorkspaceError('prepared_revision_changed', 409)
                self._ready(db, actual)
            elif actual['published_version'] != obj['version']:
                raise WorkspaceError('prepared_revision_changed', 409)
        db.execute('UPDATE plans SET approval=? WHERE id=?', (proof, plan['id']))
        db.execute('DELETE FROM heads')
        db.execute('INSERT INTO heads VALUES (?)', (plan['id'],))
        for identity, obj in document['revision']['objects'].items():
            db.execute('UPDATE objects SET published_version=? WHERE id=?',
                       (obj['version'], identity))
        return document
