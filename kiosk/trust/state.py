"""Durable trust-lifecycle state: atomic persistence, time floor, revocation and generation.

SQLite with ``BEGIN IMMEDIATE`` transactions and a persisted monotonic UTC floor.
The floor advances but never decreases; a request observed at or below the floor is
refused as a backward-clock/rollback attempt. Revocation, used recovery grants and
the TLS issuance generation are transaction-specific and survive restart.
"""
from __future__ import annotations

import sqlite3
import time
from contextlib import contextmanager
from pathlib import Path

TIME_FLOOR_KEY = "highest_utc"
SERVING_GENERATION_KEY = "serving_generation"
DB_NAME = "trust-lifecycle.sqlite"


class LifecycleError(ValueError):
    def __init__(self, code):
        super().__init__(code)
        self.code = code


class LifecycleState:
    def __init__(self, root, clock=time.time, *, database=None):
        self.root = Path(root).absolute()
        self.root.mkdir(parents=True, exist_ok=True)
        self.clock = clock
        # The installed Maintenance service keeps issuer state in its own DB so
        # the existing fenced, encrypted transfer preserves the same time floor.
        self.database = Path(database) if database is not None else self.root / DB_NAME
        with self.connection() as db:
            db.executescript(
                """
                CREATE TABLE IF NOT EXISTS meta (
                  key TEXT PRIMARY KEY, value INTEGER NOT NULL);
                CREATE TABLE IF NOT EXISTS tls_issue (
                  generation INTEGER PRIMARY KEY,
                  spki_sha256 TEXT NOT NULL,
                  not_before INTEGER NOT NULL,
                  not_after INTEGER NOT NULL,
                  recorded INTEGER NOT NULL);
                CREATE TABLE IF NOT EXISTS revoked (
                  target TEXT PRIMARY KEY, reason TEXT NOT NULL, at INTEGER NOT NULL);
                CREATE TABLE IF NOT EXISTS used_grants (
                  grant_id TEXT PRIMARY KEY, at INTEGER NOT NULL);
                """
            )

    @contextmanager
    def connection(self):
        db = sqlite3.connect(self.database, timeout=5)
        db.row_factory = sqlite3.Row
        try:
            db.execute("PRAGMA synchronous=FULL")
            db.execute("BEGIN IMMEDIATE")
            yield db
            db.commit()
        except BaseException:
            db.rollback()
            raise
        finally:
            db.close()

    def _floor(self, db):
        row = db.execute("SELECT value FROM meta WHERE key=?", (TIME_FLOOR_KEY,)).fetchone()
        return row["value"] if row else 0

    def time_floor(self):
        with self.connection() as db:
            return self._floor(db)

    def checked_now(self, db, now=None):
        """Return a monotonic ``now``; refuse a backward or rolled-back clock."""
        now = int(self.clock()) if now is None else int(now)
        floor = self._floor(db)
        if now < floor:
            raise LifecycleError("time_backward")
        return now

    def advance_floor(self, db, now):
        if now > self._floor(db):
            db.execute(
                "INSERT INTO meta(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                (TIME_FLOOR_KEY, now),
            )

    # ------------------------------------------------------------------ TLS issue
    def current_tls(self):
        with self.connection() as db:
            row = db.execute("SELECT * FROM tls_issue ORDER BY generation DESC LIMIT 1").fetchone()
            return dict(row) if row else None

    def tls_record(self, generation):
        with self.connection() as db:
            row = db.execute("SELECT * FROM tls_issue WHERE generation=?", (generation,)).fetchone()
            return dict(row) if row else None

    def serving_generation(self):
        with self.connection() as db:
            row = db.execute("SELECT value FROM meta WHERE key=?", (SERVING_GENERATION_KEY,)).fetchone()
            return row["value"] if row else None

    def serving_tls(self):
        generation = self.serving_generation()
        if generation is None:
            return None
        return self.tls_record(generation)

    def record_tls(self, spki_sha256, not_before, not_after, now=None, fail_at=None):
        """Atomically record a new TLS issuance generation; monotonic and re-verifiable."""
        with self.connection() as db:
            now = self.checked_now(db, now)
            if not_before >= not_after or not_after <= now:
                raise LifecycleError("tls_validity_refused")
            previous = db.execute("SELECT MAX(generation) AS g FROM tls_issue").fetchone()["g"] or 0
            generation = previous + 1
            db.execute(
                "INSERT INTO tls_issue VALUES (?,?,?,?,?)",
                (generation, spki_sha256, not_before, not_after, now),
            )
            self.advance_floor(db, now)
            if fail_at == "after_tls":
                raise LifecycleError("interrupted_after_tls")
            return generation

    def activate(self, generation, now=None, fail_at=None):
        """Atomically mark a recorded (non-expired) TLS generation as the serving leaf.

        Activation is explicit and monotonic: the serving generation may only move
        forward, and it must reference a leaf that is still within its validity
        window. A partial activation write is rolled back with the transaction.
        """
        with self.connection() as db:
            now = self.checked_now(db, now)
            row = db.execute("SELECT * FROM tls_issue WHERE generation=?", (generation,)).fetchone()
            if row is None:
                raise LifecycleError("activation_unknown_generation")
            if not row["not_before"] <= now < row["not_after"]:
                raise LifecycleError("activation_expired_generation")
            current = db.execute("SELECT value FROM meta WHERE key=?", (SERVING_GENERATION_KEY,)).fetchone()
            current = current["value"] if current else 0
            if generation < current:
                raise LifecycleError("activation_rollback")
            db.execute(
                "INSERT INTO meta(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                (SERVING_GENERATION_KEY, generation),
            )
            self.advance_floor(db, now)
            if fail_at == "after_activate":
                raise LifecycleError("interrupted_after_activate")
            return generation

    # ---------------------------------------------------------------- revocation
    def revoked(self, target):
        with self.connection() as db:
            row = db.execute("SELECT 1 FROM revoked WHERE target=?", (target,)).fetchone()
            return row is not None

    def revoke(self, target, reason):
        with self.connection() as db:
            now = self.checked_now(db)
            db.execute(
                "INSERT INTO revoked VALUES (?,?,?) ON CONFLICT(target) DO UPDATE SET reason=excluded.reason, at=excluded.at",
                (target, reason, now),
            )
            self.advance_floor(db, now)

    # ------------------------------------------------------------ recovery grants
    def grant_used(self, grant_id):
        with self.connection() as db:
            return db.execute("SELECT 1 FROM used_grants WHERE grant_id=?", (grant_id,)).fetchone() is not None

    def consume_grant(self, grant_id, fail_at=None):
        with self.connection() as db:
            now = self.checked_now(db)
            if db.execute("SELECT 1 FROM used_grants WHERE grant_id=?", (grant_id,)).fetchone():
                raise LifecycleError("recovery_replay")
            db.execute("INSERT INTO used_grants VALUES (?,?)", (grant_id, now))
            self.advance_floor(db, now)
            if fail_at == "after_grant":
                raise LifecycleError("interrupted_after_grant")
            return now
