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
from . import authority
from .mapping import SETTINGS_LIMIT, settings as mapped_settings

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


def _payload(value):
    if not isinstance(value, dict) or len(encode(value)) > MAX_OBJECT_BYTES:
        raise WorkspaceError('draft_limit', 413)
    # Events only. References are versioned separately; no arbitrary HTML/script.
    allowed = {'title', 'short_description', 'full_description', 'event_date', 'place',
               'sort_order', 'status', 'images', 'tags'}
    if set(value) != allowed:
        raise WorkspaceError('invalid_event_fields')
    for name, maximum in (('title', 300), ('short_description', 4096),
                          ('full_description', 16384), ('event_date', 64), ('place', 512)):
        item = value[name]
        if name == 'event_date' and item is None:
            continue
        if not isinstance(item, str) or len(item) > maximum or '\x00' in item:
            raise WorkspaceError('invalid_event_text')
    if not value['title'].strip() or value['status'] not in ('active', 'hidden'):
        raise WorkspaceError('invalid_event')
    if type(value['sort_order']) is not int or not -100000 <= value['sort_order'] <= 100000:
        raise WorkspaceError('invalid_event_order')
    for field, maximum in (('images', 3), ('tags', 32)):
        items = value[field]
        if not isinstance(items, list) or len(items) > maximum or any(not isinstance(x, str) and
                not (field == 'images' and len(items) == 3 and x is None) for x in items):
            raise WorkspaceError('invalid_event_references')
        if field == 'tags' and len(set(items)) != len(items):
            raise WorkspaceError('invalid_event_references')
        for item in items:
            if field == 'images':
                if item is None:
                    continue
                if (not item.startswith('/static/uploads/') or '\\' in item
                        or any(part in ('', '.', '..') for part in item.split('/')[1:])
                        or len(item) > 512 or '\x00' in item or '?' in item or '#' in item or '%' in item):
                    raise WorkspaceError('invalid_event_references')
            elif not item.strip() or len(item) > 128 or '\x00' in item:
                raise WorkspaceError('invalid_event_references')
    return value


class Workspace:
    def __init__(self, path, root_spki, group_id, origin, *, clock=time.time):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.root_spki = bytes(root_spki)
        self.group_id, self.origin, self.clock = text(group_id), authority.origin(origin), clock
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
            self._session(db, secret)
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
        _exact_version(expected_version)
        _payload(payload)
        if not isinstance(dependencies, dict) or len(dependencies)>100:
            raise WorkspaceError('dependency_limit')
        for name, version in dependencies.items():
            text(name); _exact_version(version,1)
        with self.db() as db:
            device,_ = self._session(db,secret)
            self._capacity(len(encode(payload))*2+16384)
            if db.execute('SELECT COUNT(*) FROM revisions').fetchone()[0]>=10000:
                raise WorkspaceError('revision_capacity',507)
            old=db.execute('SELECT version FROM objects WHERE id=?',(identity,)).fetchone()
            if (old['version'] if old else 0)!=expected_version:
                raise WorkspaceError('draft_version_conflict',409)
            if not old and db.execute('SELECT COUNT(*) FROM objects').fetchone()[0]>=MAX_OBJECTS:
                raise WorkspaceError('draft_object_limit',413)
            version=expected_version+1
            raw,refs=encode(payload),encode(dependencies)
            db.execute('INSERT INTO revisions VALUES (?,?,?,?,?)',(identity,version,raw,device['user_id'],refs))
            db.execute('''INSERT INTO objects(id,version,payload,author,dependencies) VALUES (?,?,?,?,?)
                ON CONFLICT(id) DO UPDATE SET version=excluded.version,payload=excluded.payload,
                    author=excluded.author,dependencies=excluded.dependencies,ready=0''',
                (identity,version,raw,device['user_id'],refs))
            # Readiness pins dependency versions; recursively invalidated below
            # at planning too, so an interrupted request cannot publish stale refs.
            for row in db.execute('SELECT id,dependencies FROM objects WHERE ready=1').fetchall():
                if identity in decode(row['dependencies']):
                    db.execute('UPDATE objects SET ready=0 WHERE id=?',(row['id'],))
            return version

    def _ready(self, db, row, visiting=None):
        visiting=set() if visiting is None else visiting
        if row['id'] in visiting:
            raise WorkspaceError('dependency_cycle',409)
        visiting=visiting|{row['id']}
        for identity,version in decode(row['dependencies']).items():
            dep=db.execute('SELECT * FROM objects WHERE id=?',(identity,)).fetchone()
            if dep is None or dep['version']!=version or (not dep['ready'] and dep['published_version']!=version):
                raise WorkspaceError('dependency_not_ready',409)
            self._ready(db,dep,visiting)

    def ready(self, secret, identity, version):
        with self.db() as db:
            self._session(db,secret)
            row=db.execute('SELECT * FROM objects WHERE id=?',(identity,)).fetchone()
            if row is None or row['version']!=_exact_version(version,1):
                raise WorkspaceError('draft_version_conflict',409)
            self._ready(db,row)
            db.execute('UPDATE objects SET ready=1 WHERE id=?',(identity,))

    def objects(self, secret):
        with self.db() as db:
            self._session(db,secret)
            return [dict(id=r['id'],version=r['version'],payload=decode(r['payload']),author=r['author'],
                         dependencies=decode(r['dependencies']),ready=bool(r['ready']),published_version=r['published_version'])
                    for r in db.execute('SELECT * FROM objects ORDER BY id')]

    def _snapshot(self, db, selected):
        if not isinstance(selected, dict) or not 1<=len(selected)<=MAX_OBJECTS:
            raise WorkspaceError('plan_object_limit')
        snapshot={}
        for identity,version in sorted(selected.items()):
            text(identity);_exact_version(version,1)
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
                      issued=now,expires=min(device['expires'],current['expires']),
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
                result.append(dict(id=row['id'], created=row['created'],
                                   user_id=document['plan']['user_id'],
                                   device_id=document['plan']['device_id'],
                                   publication_sha256=document['plan']['publication_sha256'],
                                   targets=document['plan']['targets'],
                                   content_version=document.get('content_version')))
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
            current,policy=self._policy(db)
            heads=[r['id'] for r in db.execute('SELECT id FROM heads ORDER BY id')]
            document=decode(row['snapshot'])
            plan,_=authority.approval(envelope,chain,policy,self.root_spki,self.group_id,self.origin,self.now(),
                                      known_heads=heads,ancestry=document.get('ancestry',[]))
            if plan!=document['plan']:
                raise WorkspaceError('prepared_plan_changed',409)
            proof=encode(dict(approval=envelope,chain=chain,policy=policy,ancestry=document.get('ancestry',[])))
            if row['approval'] is not None:
                if bytes(row['approval'])!=proof:
                    raise WorkspaceError('plan_approval_conflict',409)
                return document
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
