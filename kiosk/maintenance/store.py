"""SQLite state for the trusted Maintenance service.

The Maintenance database is deliberately separate from the content service's
``workspace``/``delivery`` databases. Accounts, grants, browser sessions,
terminal approvals and reviewer keys live here; drafts, packages and publication
history stay on the content side and are exchanged only through the authenticated
service API.
"""
from __future__ import annotations

from contextlib import contextmanager
import hmac
import sqlite3
import time
from pathlib import Path

from kiosk.delivery.protocol import decode, encode

MAX_MAINTENANCE_DB_BYTES = 256 * 1024 * 1024
MAX_AUDIT_ROWS = 20000


class MaintenanceError(ValueError):
    def __init__(self, code, status=400):
        self.code, self.status = code, status
        super().__init__(code)


CONNECTIONS_TABLE = '''
CREATE TABLE IF NOT EXISTS connections (
    id TEXT PRIMARY KEY,
    kind TEXT NOT NULL CHECK(kind IN ('login','terminal','device')),
    code TEXT NOT NULL,
    browser TEXT NOT NULL,
    terminal_id TEXT NOT NULL,
    requested_user TEXT NOT NULL DEFAULT '',
    target_user TEXT NOT NULL DEFAULT '',
    summary TEXT NOT NULL,
    origin TEXT NOT NULL,
    issued INTEGER NOT NULL,
    expires INTEGER NOT NULL,
    approved INTEGER NOT NULL DEFAULT 0,
    approved_by TEXT,
    consumed INTEGER NOT NULL DEFAULT 0,
    attempts INTEGER NOT NULL DEFAULT 0,
    document BLOB NOT NULL
);
'''

SCHEMA = '''
CREATE TABLE IF NOT EXISTS authority_delivery (
    singleton INTEGER PRIMARY KEY CHECK(singleton=1),
    body BLOB NOT NULL
);
CREATE TABLE IF NOT EXISTS users (
    id TEXT PRIMARY KEY,
    password_hash TEXT NOT NULL,
    display_name TEXT NOT NULL DEFAULT '',
    role TEXT NOT NULL CHECK(role IN ('administrator','user')),
    blocked INTEGER NOT NULL DEFAULT 0,
    auth_epoch INTEGER NOT NULL DEFAULT 0,
    created INTEGER NOT NULL,
    updated INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS teams (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    created INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS memberships (
    user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    team_id TEXT NOT NULL REFERENCES teams(id) ON DELETE CASCADE,
    PRIMARY KEY (user_id, team_id)
);
CREATE TABLE IF NOT EXISTS grants (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    subject_type TEXT NOT NULL CHECK(subject_type IN ('user','team')),
    subject_id TEXT NOT NULL,
    bundle TEXT NOT NULL,
    groups TEXT NOT NULL,
    created_by TEXT NOT NULL,
    created INTEGER NOT NULL,
    UNIQUE(subject_type, subject_id, bundle, groups)
);
CREATE TABLE IF NOT EXISTS terminals (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    approved INTEGER NOT NULL DEFAULT 0,
    retained INTEGER NOT NULL DEFAULT 0,
    approved_by TEXT,
    approved_at INTEGER,
    policy TEXT NOT NULL DEFAULT '{}'
);
CREATE TABLE IF NOT EXISTS sessions (
    id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL,
    terminal_id TEXT NOT NULL,
    secret_sha256 TEXT NOT NULL UNIQUE,
    issued INTEGER NOT NULL,
    touched INTEGER NOT NULL,
    expires INTEGER NOT NULL,
    idle_deadline INTEGER NOT NULL,
    state TEXT NOT NULL CHECK(state IN ('active','locked','ended')),
    auth_method TEXT NOT NULL,
    trusted INTEGER NOT NULL DEFAULT 0,
    temporary INTEGER NOT NULL DEFAULT 0,
    parent TEXT,
    connection TEXT,
    epoch INTEGER NOT NULL,
    remote TEXT NOT NULL DEFAULT '',
    agent TEXT NOT NULL DEFAULT '',
    last_contact INTEGER NOT NULL,
    ended_reason TEXT NOT NULL DEFAULT ''
);
CREATE TABLE IF NOT EXISTS connections (
    id TEXT PRIMARY KEY,
    kind TEXT NOT NULL CHECK(kind IN ('login','terminal','device')),
    code TEXT NOT NULL,
    browser TEXT NOT NULL,
    terminal_id TEXT NOT NULL,
    requested_user TEXT NOT NULL DEFAULT '',
    target_user TEXT NOT NULL DEFAULT '',
    summary TEXT NOT NULL,
    origin TEXT NOT NULL,
    issued INTEGER NOT NULL,
    expires INTEGER NOT NULL,
    approved INTEGER NOT NULL DEFAULT 0,
    approved_by TEXT,
    consumed INTEGER NOT NULL DEFAULT 0,
    attempts INTEGER NOT NULL DEFAULT 0,
    document BLOB NOT NULL
);
CREATE TABLE IF NOT EXISTS keys (
    user_id TEXT PRIMARY KEY,
    protected BLOB NOT NULL,
    spki TEXT NOT NULL,
    device_id TEXT NOT NULL,
    role TEXT NOT NULL,
    chain BLOB,
    policy BLOB,
    group_id TEXT NOT NULL,
    origin TEXT NOT NULL,
    scope TEXT NOT NULL DEFAULT '{}',
    issued INTEGER NOT NULL,
    expires INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS reviews (
    id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL,
    user_id TEXT NOT NULL,
    plan_id TEXT NOT NULL,
    digest TEXT NOT NULL,
    body BLOB NOT NULL,
    targets TEXT NOT NULL,
    created INTEGER NOT NULL,
    expires INTEGER NOT NULL,
    state TEXT NOT NULL CHECK(state IN ('reviewed','signed','committed','failed')),
    approval BLOB,
    receipt BLOB,
    commit_reference TEXT
);
CREATE TABLE IF NOT EXISTS receipts (
    plan_id TEXT PRIMARY KEY,
    body BLOB NOT NULL,
    created INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS placements (
    singleton INTEGER PRIMARY KEY CHECK(singleton=1),
    mode TEXT NOT NULL CHECK(mode IN ('combined','separated')),
    side TEXT NOT NULL,
    node TEXT NOT NULL,
    origin TEXT NOT NULL,
    generation INTEGER NOT NULL,
    active INTEGER NOT NULL DEFAULT 1,
    fence TEXT,
    handoff INTEGER NOT NULL DEFAULT 0,
    counterpart TEXT NOT NULL DEFAULT '',
    updated INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS nonces (
    value TEXT PRIMARY KEY,
    seen INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS tls_issuer (
    singleton INTEGER PRIMARY KEY CHECK(singleton=1),
    protected BLOB NOT NULL,
    configuration BLOB NOT NULL
);
CREATE TABLE IF NOT EXISTS publisher_policy (
    singleton INTEGER PRIMARY KEY CHECK(singleton=1),
    version INTEGER NOT NULL,
    envelope BLOB NOT NULL
);
CREATE TABLE IF NOT EXISTS transfers (
    id TEXT PRIMARY KEY,
    secret_sha256 TEXT NOT NULL,
    state TEXT NOT NULL DEFAULT 'issued',
    destination TEXT NOT NULL DEFAULT '',
    created INTEGER NOT NULL,
    redeemed INTEGER NOT NULL DEFAULT 0,
    claimed INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS audit (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    at INTEGER NOT NULL,
    kind TEXT NOT NULL,
    user_id TEXT NOT NULL DEFAULT '',
    detail TEXT NOT NULL DEFAULT ''
);
CREATE TABLE IF NOT EXISTS schedule (
    singleton INTEGER PRIMARY KEY CHECK(singleton=1),
    anchor INTEGER NOT NULL,
    interval_days INTEGER NOT NULL DEFAULT 90,
    last_maintenance INTEGER NOT NULL DEFAULT 0,
    detail TEXT NOT NULL DEFAULT '{}'
);
CREATE TABLE IF NOT EXISTS recovery (
    singleton INTEGER PRIMARY KEY CHECK(singleton=1),
    generation INTEGER NOT NULL DEFAULT 0,
    state TEXT NOT NULL DEFAULT 'none',
    detail TEXT NOT NULL DEFAULT '{}'
);
CREATE INDEX IF NOT EXISTS sessions_user ON sessions(user_id, state);
CREATE INDEX IF NOT EXISTS connections_terminal ON connections(terminal_id, expires);
'''


def _migrate_connections(db):
    """Bring a database created by an earlier task build to the current contract.

    SQLite cannot relax a CHECK constraint, so the old table is rebuilt once and
    every existing row is carried over. No request could have been stored with a
    refused kind, but any legacy ``enroll`` row maps to the equivalent ``device``
    request instead of being dropped.
    """
    row = db.execute("SELECT sql FROM sqlite_master WHERE type='table' "
                     "AND name='connections'").fetchone()
    if row is None or "'terminal'" in (row[0] or '').lower():
        return
    db.execute('ALTER TABLE connections RENAME TO connections_legacy')
    db.execute(CONNECTIONS_TABLE.replace('IF NOT EXISTS connections', 'connections'))
    db.execute('INSERT INTO connections (id,kind,code,browser,terminal_id,requested_user,'
               'target_user,summary,origin,issued,expires,approved,approved_by,consumed,'
               'attempts,document) '
               "SELECT id, CASE WHEN kind='enroll' THEN 'device' ELSE kind END, code, browser, "
               'terminal_id, requested_user, target_user, summary, origin, issued, expires, '
               'approved, approved_by, consumed, attempts, document FROM connections_legacy')
    db.execute('DROP TABLE connections_legacy')
    db.execute('CREATE INDEX IF NOT EXISTS connections_terminal '
               'ON connections(terminal_id, expires)')


class MaintenanceStore:
    """Small transaction helper around one private SQLite database."""

    def __init__(self, path, *, clock=time.time):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.clock = clock
        with self.connection() as db:
            db.executescript(SCHEMA)
            _migrate_connections(db)

    def now(self):
        return int(self.clock())

    @contextmanager
    def connection(self, write=True):
        db = sqlite3.connect(self.path, timeout=10)
        db.row_factory = sqlite3.Row
        db.execute('PRAGMA foreign_keys = ON')
        try:
            if write:
                db.execute('BEGIN IMMEDIATE')
            yield db
            if write:
                db.commit()
        except BaseException:
            if write:
                db.rollback()
            raise
        finally:
            db.close()

    def capacity(self, extra=0):
        used = sum(item.stat().st_size for item in self.path.parent.glob(self.path.name + '*')
                   if item.is_file())
        if used + extra > MAX_MAINTENANCE_DB_BYTES:
            raise MaintenanceError('maintenance_storage_full', 507)

    def audit(self, db, kind, user_id='', detail=''):
        db.execute('INSERT INTO audit (at, kind, user_id, detail) VALUES (?,?,?,?)',
                   (self.now(), kind, user_id, detail[:512]))
        rows = db.execute('SELECT COUNT(*) FROM audit').fetchone()[0]
        if rows > MAX_AUDIT_ROWS:
            db.execute('DELETE FROM audit WHERE id IN (SELECT id FROM audit ORDER BY id LIMIT ?)',
                       (rows - MAX_AUDIT_ROWS,))

    # -- placement / fencing -------------------------------------------------
    def placement(self):
        with self.connection(write=False) as db:
            row = db.execute('SELECT * FROM placements WHERE singleton=1').fetchone()
            return dict(row) if row else None

    def configure_placement(self, mode, side, node, origin, *, counterpart='', generation=1,
                            active=True, fence=None, handoff=0):
        with self.connection() as db:
            db.execute('DELETE FROM placements')
            db.execute('''INSERT INTO placements VALUES (1,?,?,?,?,?,?,?,?,?,?)''',
                       (mode, side, node, origin, generation, int(active), fence,
                        int(handoff), counterpart, self.now()))

    def fenced(self):
        row = self.placement()
        return row is not None and (not row['active'] or bool(row['fence']))

    def fence(self, reason='relocation', *, handoff=False):
        with self.connection() as db:
            row = db.execute('SELECT * FROM placements WHERE singleton=1').fetchone()
            if row is None:
                raise MaintenanceError('placement_not_configured', 503)
            if not row['active']:
                return row['fence']
            fence = encode({'generation': row['generation'], 'reason': reason,
                            'at': self.now()}).decode('utf-8')
            db.execute('UPDATE placements SET active=0, fence=?, handoff=?, updated=? '
                       'WHERE singleton=1', (fence, int(handoff), self.now()))
            self.audit(db, 'placement_fenced', '', reason)
            return fence

    def activate(self, generation, fence, origin, *, transfer=None):
        with self.connection() as db:
            row = db.execute('SELECT * FROM placements WHERE singleton=1').fetchone()
            if row is None:
                raise MaintenanceError('placement_not_configured', 503)
            if row['handoff']:
                raise MaintenanceError('placement_handoff_complete', 409)
            if row['generation'] != int(generation):
                raise MaintenanceError('placement_generation_conflict', 409)
            if not isinstance(fence, str) or not isinstance(row['fence'], str):
                raise MaintenanceError('placement_fence_required', 409)
            if fence != row['fence']:
                raise MaintenanceError('placement_fence_mismatch', 409)
            if row['origin'] != origin:
                raise MaintenanceError('placement_origin_conflict', 409)
            pending = db.execute('SELECT COUNT(*) FROM transfers').fetchone()[0]
            if pending:
                # An imported transfer can only activate after the source has
                # granted the single-use cutover claim to this destination.
                if not isinstance(transfer, str) or not transfer:
                    raise MaintenanceError('placement_transfer_required', 409)
                claim = db.execute('SELECT * FROM transfers WHERE id=?',
                                   (transfer,)).fetchone()
                if claim is None:
                    raise MaintenanceError('placement_transfer_unknown', 409)
                if not claim['redeemed'] or not claim['claimed']:
                    raise MaintenanceError('placement_transfer_unredeemed', 409)
                if claim['destination'] and claim['destination'] != origin:
                    raise MaintenanceError('placement_transfer_other_destination', 409)
            db.execute('UPDATE placements SET active=1, fence=NULL, generation=generation+1, '
                       'updated=? WHERE singleton=1', (self.now(),))
            self.audit(db, 'placement_activated', '', str(generation))
            return True

    # -- exclusive cutover ---------------------------------------------------
    def issue_transfer(self, identity, secret_sha256, now=None):
        with self.connection() as db:
            db.execute('INSERT INTO transfers VALUES (?,?,?,?,?,0,0)',
                       (identity, secret_sha256, 'issued', '', int(now or self.now())))
        return identity

    def import_transfer(self, identity, secret_sha256, origin, now=None):
        """Record the transfer this destination intends to claim (unredeemed)."""
        with self.connection() as db:
            db.execute('INSERT OR REPLACE INTO transfers VALUES (?,?,?,?,?,0,0)',
                       (identity, secret_sha256, 'imported', origin, int(now or self.now())))

    def claim_transfer(self, identity, destination, now=None):
        """Local, idempotent record that this destination holds the remote claim."""
        with self.connection() as db:
            row = db.execute('SELECT * FROM transfers WHERE id=?', (identity,)).fetchone()
            if row is None:
                raise MaintenanceError('placement_transfer_unknown', 409)
            if row['destination'] and row['destination'] != destination:
                raise MaintenanceError('placement_transfer_other_destination', 409)
            db.execute('UPDATE transfers SET redeemed=1, claimed=1, destination=?, state=? '
                       'WHERE id=?', (destination, 'claimed', identity))
        return True

    def redeem_transfer(self, identity, secret, destination, now=None):
        """Single-use claim at the fenced source; only one destination may win."""
        import hashlib
        with self.connection() as db:
            row = db.execute('SELECT * FROM transfers WHERE id=?', (identity,)).fetchone()
            if row is None:
                raise MaintenanceError('placement_transfer_unknown', 404)
            supplied = hashlib.sha256(secret.encode('utf-8')).hexdigest() \
                if isinstance(secret, str) else ''
            if not supplied or not hmac.compare_digest(supplied, row['secret_sha256']):
                raise MaintenanceError('placement_transfer_refused', 403)
            if row['redeemed']:
                if row['destination'] == destination:
                    return dict(state='claimed', destination=destination, id=identity)
                raise MaintenanceError('cutover_already_claimed', 409)
            db.execute('UPDATE transfers SET redeemed=1, destination=?, state=? WHERE id=?',
                       (destination, 'claimed', identity))
            self.audit(db, 'cutover_claimed', '', destination)
            return dict(state='claimed', destination=destination, id=identity)

    # -- maintenance cycle ---------------------------------------------------
    def schedule(self):
        with self.connection(write=False) as db:
            row = db.execute('SELECT * FROM schedule WHERE singleton=1').fetchone()
            return dict(row) if row else None

    def configure_schedule(self, anchor, interval_days=90):
        with self.connection() as db:
            db.execute('DELETE FROM schedule')
            db.execute('INSERT INTO schedule VALUES (1,?,?,0,?)',
                       (int(anchor), int(interval_days), '{}'))

    def record_maintenance(self, at):
        with self.connection() as db:
            db.execute('UPDATE schedule SET last_maintenance=? WHERE singleton=1', (int(at),))
            self.audit(db, 'maintenance_recorded', '', str(at))
