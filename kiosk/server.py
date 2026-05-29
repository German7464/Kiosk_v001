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


def detected_lan_addresses():
    addresses = []

    try:
        hostnames = {socket.gethostname(), socket.getfqdn()}
    except OSError:
        hostnames = set()

    for hostname in hostnames:
        if not hostname:
            continue

        try:
            infos = socket.getaddrinfo(hostname, None, family=socket.AF_INET)
        except OSError:
            infos = []

        for info in infos:
            address = info[4][0]
            if address.startswith("127.") or address in addresses:
                continue
            addresses.append(address)

    try:
        _, _, hostname_addresses = socket.gethostbyname_ex(socket.gethostname())
    except OSError:
        hostname_addresses = []

    for address in hostname_addresses:
        if address.startswith("127.") or address in addresses:
            continue
        addresses.append(address)

    return sorted(addresses)


def connection_urls(host, port):
    urls = []

    if host in {"0.0.0.0", ""}:
        addresses = detected_lan_addresses()
    elif host.startswith("127.") or host == "localhost":
        addresses = []
    else:
        addresses = [host]

    if not addresses:
        return urls

    for address in addresses:
        urls.extend(active_urls(address, port))

    return urls


def lan_urls(host, port):
    return connection_urls(host, port)


def startup_message(app):
    host = app.config["SERVER_HOST"]
    port = app.config["SERVER_PORT"]
    lines = [
        "Starting Kiosk_v001 with Waitress",
        f"Bound server: http://{host}:{port}",
        "Local URLs (127.0.0.1):",
        *active_urls("127.0.0.1", port),
        "Manual stop: Ctrl+C",
    ]

    extra_urls = lan_urls(host, port)
    if extra_urls:
        lines.append("LAN URLs:")
        lines.extend(extra_urls)

    if host == "127.0.0.1":
        lines.append("Other devices cannot connect to 127.0.0.1.")
    elif host in {"0.0.0.0", ""}:
        lines.append("Other devices should use the computer LAN IP address.")
    else:
        lines.append(f"Other devices should use http://{host}:{port}.")

    lines.append(
        f"If another device cannot connect, disable VPN, check that both devices are on the same Wi-Fi, and allow TCP port {port} in Windows Firewall."
    )

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


def run_waitress(host=None, port=None):
    overrides = {}

    if host is not None:
        overrides["SERVER_HOST"] = host

    if port is not None:
        overrides["SERVER_PORT"] = port

    app = create_app(overrides or None)
    host = app.config["SERVER_HOST"]
    port = app.config["SERVER_PORT"]
    print(startup_message(app), flush=True)
    serve(app, host=host, port=port)
