"""Server-side invalidation of an explicitly logged-out administrator cookie.

The Flask session is a signed client-side cookie, so clearing it on logout does
not by itself stop a copy of that cookie from authenticating again. Each login
stores a random session identifier and its sign-in time; only the identifier's
SHA-256 digest is recorded here when the session ends. ``admin_required`` rejects
a cookie whose identifier is revoked, whose sign-in is older than the fixed
session lifetime, or whose identifier had to be evicted from the bounded
revocation table -- evictions raise a monotonic cutoff so capacity cleanup can
never make a logged-out session valid again. Other administrator sessions, the
CSRF token and device credentials are untouched.
"""
import hashlib
import secrets
import time

from flask import session

from kiosk.database import get_database


SESSION_ID_KEY = "session_id"
SESSION_ISSUED_KEY = "session_issued"
SESSION_ID_BYTES = 32
# Flask signs every session cookie with a timestamp whose maximum age is
# PERMANENT_SESSION_LIFETIME (31 days by default) and re-signs it whenever the
# payload changes, so the signature age cannot bound an administrator session.
# The explicit sign-in time below is the authority and is never refreshed; a
# logout only has to be remembered until that same moment, never longer.
SESSION_LIFETIME_SECONDS = 12 * 3600
REVOCATION_SECONDS = SESSION_LIFETIME_SECONDS
MAX_REVOCATION_ROWS = 4096
# Settings key holding "sessions signed in at or before this epoch are refused".
# It is the fail-closed replacement for silently dropping a still-relevant row.
CUTOFF_KEY = "revoked_admin_sessions_before"
ALLOWED_CLOCK_SKEW_SECONDS = 300


def new_session_id():
    return secrets.token_hex(SESSION_ID_BYTES)


def start_session(now=None):
    """Begin a fresh administrator session with a stable sign-in time."""
    moment = int(time.time()) if now is None else int(now)
    session[SESSION_ID_KEY] = new_session_id()
    session[SESSION_ISSUED_KEY] = moment


def session_id_valid(value):
    return isinstance(value, str) and len(value) == SESSION_ID_BYTES * 2 and value.isascii()


def session_issued_valid(value):
    return isinstance(value, int) and not isinstance(value, bool) and value > 0


def session_id_digest(value):
    return hashlib.sha256(value.encode("ascii")).hexdigest()


def _cutoff(database):
    row = database.execute("SELECT value FROM settings WHERE key = ?", (CUTOFF_KEY,)).fetchone()
    try:
        return max(0, int(row["value"])) if row is not None else 0
    except (TypeError, ValueError):
        # An unreadable cutoff fails closed for every session signed in before it
        # could be parsed only if we cannot tell; treating it as "no cutoff" would
        # revive evicted sessions, so use the far future instead.
        return int(time.time())


def _set_cutoff(database, value):
    database.execute(
        """
        INSERT INTO settings (key, value, updated_at) VALUES (?, ?, ?)
        ON CONFLICT(key) DO UPDATE SET value = excluded.value, updated_at = excluded.updated_at
        """,
        (CUTOFF_KEY, str(int(value)), time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())),
    )


def session_revoked(value, issued=None, now=None):
    """True when the cookie must not authenticate; any unusable field is refused."""
    if not session_id_valid(value) or not session_issued_valid(issued):
        return True
    moment = int(time.time()) if now is None else int(now)
    if issued > moment + ALLOWED_CLOCK_SKEW_SECONDS:
        return True
    if moment - issued >= SESSION_LIFETIME_SECONDS:
        return True
    database = get_database()
    row = database.execute(
        "SELECT 1 FROM revoked_admin_sessions WHERE session_sha256 = ? AND expires > ?",
        (session_id_digest(value), moment),
    ).fetchone()
    if row is not None:
        return True
    return issued <= _cutoff(database)


def revoke_current_session(now=None):
    """Record the current session as logged out. Returns True when one was revoked."""
    value = session.get(SESSION_ID_KEY)
    issued = session.get(SESSION_ISSUED_KEY)
    if not session_id_valid(value) or not session_issued_valid(issued):
        return False
    database = get_database()
    moment = int(time.time()) if now is None else int(now)
    # The row is only needed while the signed cookie itself could still be
    # accepted, so it never outlives the sign-in lifetime and expired rows can be
    # removed without weakening any outstanding revocation.
    expires = max(issued + REVOCATION_SECONDS, moment)
    database.execute("DELETE FROM revoked_admin_sessions WHERE expires <= ?", (moment,))
    database.execute(
        "INSERT OR REPLACE INTO revoked_admin_sessions (session_sha256, issued, expires) VALUES (?, ?, ?)",
        (session_id_digest(value), issued, expires),
    )
    # Bounded capacity: evict the entries closest to their own expiry and raise a
    # monotonic cutoff instead of forgetting them. Sessions signed in after the
    # cutoff stay valid; sessions signed in at or before it never do.
    rows = database.execute(
        "SELECT session_sha256, issued FROM revoked_admin_sessions ORDER BY expires ASC, issued ASC"
    ).fetchall()
    overflow = len(rows) - MAX_REVOCATION_ROWS
    if overflow > 0:
        dropped = rows[:overflow]
        cutoff = max([_cutoff_from_rows(dropped), _cutoff(database)])
        _set_cutoff(database, cutoff)
        database.executemany(
            "DELETE FROM revoked_admin_sessions WHERE session_sha256 = ?",
            [(row["session_sha256"],) for row in dropped],
        )
    database.commit()
    return True


def _cutoff_from_rows(rows):
    values = [int(row["issued"]) for row in rows if session_issued_valid(row["issued"])]
    return max(values) if values else 0
