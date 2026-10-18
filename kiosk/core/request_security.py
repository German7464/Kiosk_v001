import hashlib
import hmac
import math
import secrets
import threading
import time
from collections import deque

from flask import current_app, jsonify, render_template, request, session

from kiosk.core.i18n import translate
from kiosk.database import get_database


class AuthenticationLimiter:
    def __init__(self, account_limit=10, source_limit=40, window=60, capacity=2048):
        self.account_limit = account_limit
        self.source_limit = source_limit
        self.window = window
        self.capacity = capacity
        self.entries = {}
        self.lock = threading.Lock()

    def reserve(self, source, username):
        account = hashlib.sha256(username.encode("utf-8", errors="replace")).hexdigest()
        limits = ((('source', source), self.source_limit), (('account', source, account), self.account_limit))
        with self.lock:
            now = time.monotonic()
            for key in list(self.entries):
                queue = self.entries[key]
                while queue and queue[0] <= now - self.window:
                    queue.popleft()
                if not queue:
                    del self.entries[key]
            waits = [self.entries[key][0] + self.window - now for key, limit in limits if len(self.entries.get(key, ())) >= limit]
            missing = sum(key not in self.entries for key, limit in limits)
            if len(self.entries) + missing > self.capacity:
                waits.append(min(queue[0] + self.window - now for queue in self.entries.values()))
            if waits:
                return max(1, math.ceil(max(waits)))
            for key, limit in limits:
                self.entries.setdefault(key, deque()).append(now)
        return 0


def csrf_token():
    token = session.get("csrf_token")
    if not isinstance(token, str) or len(token) != 64 or not token.isascii():
        token = secrets.token_hex(32)
        session["csrf_token"] = token
    return token


def security_error(message, status, retry_after=None):
    row = get_database().execute("SELECT value FROM settings WHERE key = 'interface_language'").fetchone()
    language = row["value"] if row is not None else "en"
    if request.endpoint == "admin.fullscreen_validate":
        response = jsonify(success=False, error=translate(message, language))
        response.status_code = status
    else:
        response = current_app.make_response((render_template("admin_security_error.html", message=message), status))
    if retry_after is not None:
        response.headers["Retry-After"] = str(retry_after)
    response.headers["Cache-Control"] = "no-store"
    return response


def protect_admin_request():
    if request.blueprint != "admin" or request.method in {"GET", "HEAD", "OPTIONS"}:
        return None
    expected = session.get("csrf_token")
    supplied = request.headers.get("X-CSRF-Token") or request.form.get("csrf_token")
    if not isinstance(expected, str) or not isinstance(supplied, str) or len(expected) != 64 or len(supplied) != 64 or not expected.isascii() or not supplied.isascii() or not hmac.compare_digest(expected, supplied):
        return security_error("security.request_expired", 403)
    if request.endpoint not in {"admin.login_post", "admin.fullscreen_validate", "admin.change_password_post"}:
        return None
    if request.endpoint == "admin.fullscreen_validate":
        payload = request.get_json(silent=True) if request.is_json else request.form
        if not hasattr(payload, "get"):
            return security_error("security.invalid_credentials", 400)
    else:
        payload = request.form
    username = str(session.get("admin_username", "")) if request.endpoint == "admin.change_password_post" else str(payload.get("username", "")).strip()
    wait = current_app.extensions["authentication_limiter"].reserve(request.remote_addr or "unknown", username)
    if wait:
        return security_error("security.too_many_attempts", 429, retry_after=wait)
    return None


def configure_request_security(app):
    app.extensions["authentication_limiter"] = AuthenticationLimiter()
    app.jinja_env.globals["csrf_token"] = csrf_token
    app.before_request(protect_admin_request)
    app.after_request(prevent_form_caching)


def prevent_form_caching(response):
    if response.mimetype == "text/html":
        response.headers["Cache-Control"] = "no-store"
    return response
