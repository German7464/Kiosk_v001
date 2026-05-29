import os
import shutil
import socket
import secrets
import subprocess
import threading
import time
import sys
import urllib.error
import urllib.request
import webbrowser
from datetime import datetime, timezone
from pathlib import Path

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


def runtime_base_directory():
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent

    return Path(__file__).resolve().parent.parent


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


def local_api_version_url(port):
    return f"http://127.0.0.1:{port}/api/version"


def display_url(port, path, host="127.0.0.1"):
    display_host = "127.0.0.1" if host in {"0.0.0.0", ""} else host
    return f"http://{display_host}:{port}{path}"


def launch_host(host):
    return "127.0.0.1" if host in {"0.0.0.0", ""} else host


def clientkiosk_search_directories(base_dir=None):
    directories = []
    for directory in (base_dir or runtime_base_directory(), Path.cwd()):
        resolved = Path(directory).resolve()
        if resolved not in directories:
            directories.append(resolved)

    return directories


def find_clientkiosk_executable(base_dir=None):
    for directory in clientkiosk_search_directories(base_dir):
        candidate = directory / "ClientKiosk.exe"
        if candidate.is_file():
            return candidate

    return None


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


def local_server_is_ready(port, opener=None, timeout=0.5):
    probe = opener or urllib.request.urlopen

    try:
        response = probe(local_api_version_url(port), timeout=timeout)
    except (urllib.error.URLError, OSError, TimeoutError, ValueError):
        return False

    status = getattr(response, "status", None)
    if status is None and hasattr(response, "getcode"):
        status = response.getcode()

    return status == 200


def wait_for_local_server(port, timeout=10.0, interval=0.25, opener=None):
    deadline = time.monotonic() + timeout

    while time.monotonic() < deadline:
        if local_server_is_ready(port, opener=opener):
            return True

        time.sleep(interval)

    return False


def browser_candidates():
    candidates = [
        shutil.which("msedge"),
        shutil.which("chrome"),
        shutil.which("google-chrome"),
        shutil.which("msedge.exe"),
        shutil.which("chrome.exe"),
    ]

    program_files = os.environ.get("PROGRAMFILES", "")
    program_files_x86 = os.environ.get("PROGRAMFILES(X86)", "")
    local_appdata = os.environ.get("LOCALAPPDATA", "")

    candidates.extend(
        [
            Path(program_files) / "Microsoft/Edge/Application/msedge.exe" if program_files else None,
            Path(program_files_x86) / "Microsoft/Edge/Application/msedge.exe" if program_files_x86 else None,
            Path(program_files) / "Google/Chrome/Application/chrome.exe" if program_files else None,
            Path(program_files_x86) / "Google/Chrome/Application/chrome.exe" if program_files_x86 else None,
            Path(local_appdata) / "Google/Chrome/Application/chrome.exe" if local_appdata else None,
        ]
    )

    return [str(candidate) for candidate in candidates if candidate]


def launch_browser(url, kiosk_mode=False):
    browser_path = None
    browser_arguments = []

    for candidate in browser_candidates():
        browser_name = Path(candidate).name.lower()
        if "msedge" in browser_name:
            browser_path = candidate
            browser_arguments = ["--new-window", url]
            if kiosk_mode:
                browser_arguments = ["--kiosk", "--edge-kiosk-type=fullscreen", "--no-first-run", "--new-window", url]
            break
        if "chrome" in browser_name:
            browser_path = candidate
            browser_arguments = ["--new-window", url]
            if kiosk_mode:
                browser_arguments = ["--start-fullscreen", "--new-window", url]
            break

    if browser_path is not None:
        try:
            subprocess.Popen([browser_path, *browser_arguments], close_fds=False)
            return True
        except OSError:
            pass

    try:
        if webbrowser.open(url, new=1):
            return True
    except webbrowser.Error:
        pass

    return False


def server_information_lines(host, port):
    lines = [
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

    return lines


def startup_message(app):
    host = app.config["SERVER_HOST"]
    port = app.config["SERVER_PORT"]
    lines = ["Starting Kiosk_v001 with Waitress", *server_information_lines(host, port)]
    return "\n".join(lines)


def launch_clientkiosk(client_path, host, port, path):
    client_host = launch_host(host)
    client_mode = "tv" if path == "/tv" else "kiosk"
    command = [
        str(client_path),
        "--url",
        display_url(port, path, client_host),
        "--host",
        client_host,
        "--port",
        str(port),
        "--mode",
        client_mode,
    ]

    try:
        subprocess.Popen(command, close_fds=False, cwd=str(client_path.parent))
        return True
    except OSError:
        return False


def startup_launch_lines(host, port, path="/kiosk", auto_launch=True, base_dir=None):
    url = display_url(port, path, launch_host(host))
    lines = [
        f"Automatic kiosk client/browser launch: {'enabled' if auto_launch else 'disabled'}",
    ]

    if not auto_launch:
        lines.append("Automatic client/browser launch disabled with --no-client.")
        lines.append(f"Open this URL manually: {url}")
        return lines

    client_path = find_clientkiosk_executable(base_dir)

    if client_path is not None:
        lines.append(f"ClientKiosk.exe found: {client_path}")
        if launch_clientkiosk(client_path, host, port, path):
            lines.append(f"ClientKiosk.exe launched: {client_path}")
            return lines
        lines.append("ClientKiosk.exe failed to launch.")
    else:
        lines.append("ClientKiosk.exe was not found.")

    if launch_browser(url, kiosk_mode=True):
        lines.append("Default browser fallback launched.")
        return lines

    lines.append("Default browser could not be opened.")
    lines.append(f"Open this URL manually: {url}")
    return lines


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


def run_waitress_with_launcher(host=None, port=None, path="/kiosk", auto_launch=True):
    if local_server_is_ready(port):
        print(f"Existing local server detected at {local_api_version_url(port)}", flush=True)
        for line in server_information_lines(host, port):
            print(line, flush=True)
        for line in startup_launch_lines(host, port, path=path, auto_launch=auto_launch):
            print(line, flush=True)
        return

    overrides = {}

    if host is not None:
        overrides["SERVER_HOST"] = host

    if port is not None:
        overrides["SERVER_PORT"] = port

    app = create_app(overrides or None)
    host = app.config["SERVER_HOST"]
    port = app.config["SERVER_PORT"]

    print(startup_message(app), flush=True)

    server_thread = threading.Thread(
        target=serve,
        args=(app,),
        kwargs={"host": host, "port": port},
        daemon=True,
    )
    server_thread.start()

    if not wait_for_local_server(port):
        print(f"Server startup is taking longer than expected. Opening {display_url(port, path, launch_host(host))}.", flush=True)

    for line in startup_launch_lines(host, port, path=path, auto_launch=auto_launch, base_dir=app.config["BASE_DIR"]):
        print(line, flush=True)
    server_thread.join()
