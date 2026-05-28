import socket
import secrets
from datetime import datetime, timezone

from waitress import serve
from werkzeug.security import generate_password_hash

from kiosk.app import create_app
from kiosk.database import get_database


def kiosk_url(host, port):
    display_host = "127.0.0.1" if host in {"0.0.0.0", ""} else host
    return f"http://{display_host}:{port}/kiosk"


def base_url(host, port):
    display_host = "127.0.0.1" if host in {"0.0.0.0", ""} else host
    return f"http://{display_host}:{port}"


def active_urls(host, port):
    root = base_url(host, port)
    return [
        f"{root}/kiosk",
        f"{root}/kiosk/events",
        f"{root}/tv",
        f"{root}/preview",
        f"{root}/admin/login",
        f"{root}/api/version",
    ]


def connection_urls(host, port):
    urls = []

    if host not in {"0.0.0.0", ""}:
        return urls

    try:
        addresses = socket.gethostbyname_ex(socket.gethostname())[2]
    except OSError:
        return urls

    for address in sorted(set(addresses)):
        if not address.startswith("127."):
            urls.append(f"http://{address}:{port}/kiosk")

    return urls


def lan_urls(host, port):
    if host not in {"0.0.0.0", ""}:
        return []

    return [f"{url}/kiosk" for url in connection_urls(host, port)]


def startup_message(app):
    host = app.config["SERVER_HOST"]
    port = app.config["SERVER_PORT"]
    lines = [
        "Starting Kiosk_v001 with Waitress",
        f"Server: http://{host}:{port}",
        "Local URLs:",
        *active_urls(host, port),
        "Manual stop: Ctrl+C",
    ]

    extra_urls = lan_urls(host, port)
    if extra_urls:
        lines.append("LAN kiosk URLs:")
        lines.extend(extra_urls)
    elif host == "127.0.0.1":
        lines.append("Listening on 127.0.0.1 for local testing.")

    return "\n".join(lines)


def reset_admin_password(app):
    temporary_password = secrets.token_urlsafe(12)
    updated_at = datetime.now(timezone.utc).isoformat()

    with app.app_context():
        database = get_database()
        database.execute(
            """
            INSERT INTO users (username, password_hash, created_at, updated_at)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(username) DO UPDATE SET password_hash = excluded.password_hash, updated_at = excluded.updated_at
            """,
            ("admin", generate_password_hash(temporary_password), updated_at, updated_at),
        )
        database.commit()

    return temporary_password


def reset_admin_password_command(app=None):
    if app is None:
        app = create_app()

    temporary_password = reset_admin_password(app)
    print("Admin password has been reset.", flush=True)
    print(f"Temporary password: {temporary_password}", flush=True)
    print("Log in as admin and change this password immediately.", flush=True)


def run_waitress():
    app = create_app()
    host = app.config["SERVER_HOST"]
    port = app.config["SERVER_PORT"]
    print(startup_message(app), flush=True)
    serve(app, host=host, port=port)
