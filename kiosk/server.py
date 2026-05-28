import socket

from waitress import serve

from kiosk.app import create_app


def kiosk_url(host, port):
    display_host = "127.0.0.1" if host in {"0.0.0.0", ""} else host
    return f"http://{display_host}:{port}/kiosk"


def connection_urls(host, port):
    urls = [kiosk_url(host, port)]

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


def startup_message(app):
    host = app.config["SERVER_HOST"]
    port = app.config["SERVER_PORT"]
    lines = [
        "Starting Kiosk_v001 with Waitress",
        f"Server: http://{host}:{port}",
        f"Kiosk: {kiosk_url(host, port)}",
        "Manual stop: Ctrl+C",
    ]

    extra_urls = connection_urls(host, port)[1:]
    if extra_urls:
        lines.append("Additional kiosk URLs:")
        lines.extend(extra_urls)
    elif host == "127.0.0.1":
        lines.append("Listening on 127.0.0.1 for local testing.")

    return "\n".join(lines)


def run_waitress():
    app = create_app()
    host = app.config["SERVER_HOST"]
    port = app.config["SERVER_PORT"]
    print(startup_message(app), flush=True)
    serve(app, host=host, port=port)
