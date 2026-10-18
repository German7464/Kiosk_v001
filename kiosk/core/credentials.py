import getpass
import hashlib
import hmac
import sqlite3
import sys
import warnings
from datetime import datetime, timezone

from flask import current_app
from werkzeug.security import check_password_hash, generate_password_hash

from kiosk.database import get_database


def validate_password(password):
    if not 12 <= len(password) <= 128:
        raise ValueError("Password must contain 12 to 128 characters.")


def uses_default_credentials(user):
    return user is not None and user["username"] == "admin" and check_password_hash(user["password_hash"], "admin")


def session_credential_token(user):
    key = current_app.secret_key
    if isinstance(key, str):
        key = key.encode("utf-8")
    value = f"credentials:{user['id']}:{user['password_hash']}".encode("utf-8")
    return hmac.new(key, value, hashlib.sha256).hexdigest()


def save_admin_password(app, password, setup=False):
    validate_password(password)
    password_hash = generate_password_hash(password)
    updated_at = datetime.now(timezone.utc).isoformat()
    try:
        with app.app_context():
            database = get_database()
            try:
                database.execute("BEGIN IMMEDIATE")
                if setup:
                    if database.execute("SELECT 1 FROM users LIMIT 1").fetchone() is not None:
                        raise ValueError("Accounts already exist. Use --reset-admin-password for an existing admin.")
                    database.execute(
                        "INSERT INTO users (username, password_hash, created_at, updated_at) VALUES (?, ?, ?, ?)",
                        ("admin", password_hash, updated_at, updated_at),
                    )
                else:
                    cursor = database.execute(
                        "UPDATE users SET password_hash = ?, updated_at = ? WHERE username = ?",
                        (password_hash, updated_at, "admin"),
                    )
                    if cursor.rowcount != 1:
                        raise ValueError("Admin account does not exist. Use --setup-admin if no accounts exist.")
                database.commit()
            except BaseException:
                database.rollback()
                raise
    except sqlite3.Error:
        raise RuntimeError("Cannot save administrator credentials. Check database access and available storage.") from None


def admin_password_command(app_factory, setup=False):
    try:
        if not sys.stdin.isatty():
            raise ValueError("An interactive local terminal is required; passwords cannot be supplied through stdin.")
        with warnings.catch_warnings():
            warnings.simplefilter("error", getpass.GetPassWarning)
            password = getpass.getpass("New admin password: ")
            confirmation = getpass.getpass("Confirm admin password: ")
        validate_password(password)
        if password != confirmation:
            raise ValueError("Passwords do not match.")
        save_admin_password(app_factory(), password, setup=setup)
    except (EOFError, KeyboardInterrupt):
        print("Administrator password operation cancelled.", file=sys.stderr)
        return 1
    except (ValueError, RuntimeError, OSError, getpass.GetPassWarning, sqlite3.Error) as error:
        if isinstance(error, ValueError):
            print(str(error), file=sys.stderr)
        else:
            print("Cannot configure administrator credentials. Check terminal, database, and installation access.", file=sys.stderr)
        return 1
    print("Administrator credentials saved. Sign in as admin.", flush=True)
    return 0
