import sqlite3
from datetime import datetime, timezone

from flask import current_app, g
from werkzeug.security import generate_password_hash


def get_database():
    if "database" not in g:
        g.database = sqlite3.connect(current_app.config["DATABASE_PATH"])
        g.database.row_factory = sqlite3.Row
        g.database.execute("PRAGMA foreign_keys = ON")

    return g.database


def close_database(exception=None):
    database = g.pop("database", None)

    if database is not None:
        database.close()


def initialize_database(app):
    app.config["INSTANCE_DIR"].mkdir(parents=True, exist_ok=True)

    with app.app_context():
        database = get_database()
        database.executescript(
            """
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT NOT NULL UNIQUE,
                password_hash TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                title TEXT NOT NULL,
                short_description TEXT NOT NULL DEFAULT '',
                full_description TEXT NOT NULL DEFAULT '',
                event_date TEXT,
                place TEXT NOT NULL DEFAULT '',
                image_original TEXT,
                image_kiosk TEXT,
                image_tv TEXT,
                image_thumb TEXT,
                status TEXT NOT NULL DEFAULT 'hidden',
                sort_order INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS tags (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL UNIQUE,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS event_tags (
                event_id INTEGER NOT NULL,
                tag_id INTEGER NOT NULL,
                PRIMARY KEY (event_id, tag_id),
                FOREIGN KEY (event_id) REFERENCES events (id) ON DELETE CASCADE,
                FOREIGN KEY (tag_id) REFERENCES tags (id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS settings (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS content_versions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                version INTEGER NOT NULL,
                created_at TEXT NOT NULL
            );
            """
        )
        seed_settings(database)
        seed_default_admin_user(database)
        database.commit()


def seed_settings(database):
    updated_at = datetime.now(timezone.utc).isoformat()
    settings = {
        "interface_language": "en",
        "site_title": "Kiosk_v001",
        "site_icon": "",
        "tv_slide_duration": "10",
        "kiosk_label": "",
        "kiosk_heading": "",
        "kiosk_description": "",
        "content_version": "1",
    }

    for key, value in settings.items():
        database.execute(
            """
            INSERT OR IGNORE INTO settings (key, value, updated_at)
            VALUES (?, ?, ?)
            """,
            (key, value, updated_at),
        )

    database.execute(
        """
        INSERT INTO content_versions (version, created_at)
        SELECT ?, ?
        WHERE NOT EXISTS (SELECT 1 FROM content_versions)
        """,
        (1, updated_at),
    )


def seed_default_admin_user(database):
    user_count = database.execute("SELECT COUNT(*) FROM users").fetchone()[0]

    if user_count > 0:
        return

    created_at = datetime.now(timezone.utc).isoformat()
    database.execute(
        """
        INSERT INTO users (username, password_hash, created_at, updated_at)
        VALUES (?, ?, ?, ?)
        """,
        ("admin", generate_password_hash("admin"), created_at, created_at),
    )


def increase_content_version(database):
    updated_at = datetime.now(timezone.utc).isoformat()
    row = database.execute(
        """
        SELECT value
        FROM settings
        WHERE key = ?
        """,
        ("content_version",),
    ).fetchone()
    current_version = int(row["value"]) if row is not None else 1
    next_version = current_version + 1

    database.execute(
        """
        INSERT INTO settings (key, value, updated_at)
        VALUES (?, ?, ?)
        ON CONFLICT(key) DO UPDATE SET value = excluded.value, updated_at = excluded.updated_at
        """,
        ("content_version", str(next_version), updated_at),
    )
    database.execute(
        """
        INSERT INTO content_versions (version, created_at)
        VALUES (?, ?)
        """,
        (next_version, updated_at),
    )

    return next_version
