import argparse
import copy
import http.client
import io
import json
import os
import re
import secrets
import socket
import ssl
import sys
import tempfile
import time
from contextlib import closing
from datetime import datetime, timezone
from http.cookiejar import CookieJar
from pathlib import Path
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import HTTPSHandler, HTTPCookieProcessor, ProxyHandler, Request, build_opener

from PIL import Image
from werkzeug.test import EnvironBuilder

from tools.https_runtime import Backend, Proxy, REQUEST_LIMIT, caddy_configuration, command, remaining, safe_report, verify_caddy
from tools.measure_mvp_baseline import NoRedirect


class Client:
    def __init__(self, port, context, deadline, report, jar=None):
        self.base = f"https://127.0.0.1:{port}"
        self.deadline = deadline
        self.report = report
        self.jar = jar if jar is not None else CookieJar()
        self.opener = build_opener(ProxyHandler({}), HTTPSHandler(context=context), HTTPCookieProcessor(self.jar), NoRedirect())

    def request(self, path, expected=200, data=None, headers=None):
        request = Request(self.base + path, data=data, headers=headers or {})
        try:
            response = self.opener.open(request, timeout=remaining(self.deadline))
        except HTTPError as error:
            response = error
        with response:
            body = response.read()
            status = response.status
            response_headers = response.headers
        codes = self.report["http_statuses"]
        codes[str(status)] = codes.get(str(status), 0) + 1
        self.last_status = status
        if status not in (expected if isinstance(expected, tuple) else (expected,)):
            raise RuntimeError("Unexpected HTTPS response status.")
        return body, response_headers

    def token(self):
        body, headers = self.request("/kiosk")
        match = re.search(rb'name="csrf-token" content="([a-f0-9]{64})"', body)
        if match is None:
            raise RuntimeError("Missing CSRF token.")
        return match.group(1).decode()

    def form(self, path, values, expected=302, extra_headers=None):
        headers = {"X-CSRF-Token": self.token(), **(extra_headers or {})}
        with closing(EnvironBuilder(method="POST", data=values)) as builder:
            environ = builder.get_environ()
            headers["Content-Type"] = environ["CONTENT_TYPE"]
            return self.request(path, expected, environ["wsgi.input"].read(), headers)


def verified_context(authority):
    return ssl.create_default_context(cafile=str(authority))


def check_tls_rejection(port, context, deadline, report, label):
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=remaining(deadline)) as connection:
            with context.wrap_socket(connection, server_hostname="127.0.0.1"):
                pass
    except ssl.SSLCertVerificationError as error:
        expected = {"unknown_authority": {18, 19, 20, 21}, "wrong_name": {62, 64}, "expired": {10}}
        if error.verify_code not in expected[label]:
            raise RuntimeError("Certificate rejected for an unexpected reason.") from None
        report["tls_failures"][label] = error.verify_code
        return
    raise RuntimeError("Invalid certificate was accepted.")


def check_listeners(pwsh, root, deadline, backend, proxy):
    script = ("Get-NetTCPConnection -State Listen -ErrorAction Stop | Where-Object { $_.OwningProcess -in @("
              + f"{backend.process.pid},{proxy.process.pid}"
              + ") } | Select-Object LocalAddress,LocalPort,OwningProcess | ConvertTo-Json -Compress")
    result = command([str(pwsh), "-NoProfile", "-NonInteractive", "-Command", script], root, deadline)
    listeners = json.loads(result.stdout.decode("utf-8-sig"))
    if isinstance(listeners, dict):
        listeners = [listeners]
    actual = {(item["LocalAddress"], item["LocalPort"], item["OwningProcess"]) for item in listeners}
    expected = {("127.0.0.1", backend.port, backend.process.pid), ("127.0.0.1", proxy.port, proxy.process.pid)}
    if actual != expected:
        raise RuntimeError("Unexpected owned TCP listener.")


def exercise_application(client, password, context, report):
    for route in ("/kiosk", "/kiosk/events", "/tv", "/preview", "/admin/login", "/api/version", "/api/events", "/api/tags"):
        body, unused = client.request(route)
        if route in {"/kiosk", "/kiosk/events", "/tv", "/preview"} and b'http://' in body:
            raise RuntimeError("Plaintext URL in HTTPS display HTML.")
    client.request("/admin", 302)
    client.request("/admin/login")
    cookies = list(client.jar)
    if not cookies or not all(cookie.secure and cookie.has_nonstandard_attr("HttpOnly")
                              and cookie.get_nonstandard_attr("SameSite") == "Lax" for cookie in cookies):
        raise RuntimeError("Missing secure session attributes.")
    client.request("/admin/login", 403, urlencode({"username": "admin", "password": password}).encode(),
                   {"Content-Type": "application/x-www-form-urlencoded"})
    client.form("/admin/login", {"username": "admin", "password": password})
    client.request("/admin")
    report["checks"].append("routes_login_csrf_secure_cookie")
    before = json.loads(client.request("/api/version")[0])["content_version"]
    stream = io.BytesIO()
    Image.new("RGB", (1920, 1080), "teal").save(stream, "PNG")
    stream.seek(0)
    client.form("/admin/events/create", {"title": "HTTPS fixture", "short_description": "Temporary event",
                "full_description": "HTTPS image verification", "status": "active", "sort_order": "0",
                "event_image": (stream, "fixture.png")})
    events = json.loads(client.request("/api/events")[0])["events"]
    if len(events) != 1 or events[0]["title"] != "HTTPS fixture":
        raise RuntimeError("Unexpected event fixture.")
    for field in ("image_kiosk", "image_tv", "image_thumb"):
        with Image.open(io.BytesIO(client.request(events[0][field])[0])) as image:
            image.load()
    after = json.loads(client.request("/api/version")[0])["content_version"]
    if after <= before:
        raise RuntimeError("Content version did not advance.")
    body, unused = client.form("/admin/fullscreen/validate", {"username": "admin", "password": password}, 200)
    if json.loads(body) != {"success": True}:
        raise RuntimeError("Fullscreen credential validation failed.")
    report["checks"].append("multipart_event_three_images_version_fullscreen")
    jar = CookieJar()
    for cookie in client.jar:
        jar.set_cookie(copy.copy(cookie))
    stale = Client(int(client.base.rsplit(":", 1)[1]), context, client.deadline, report, jar)
    new_password = secrets.token_urlsafe(24)
    client.form("/admin/password/change", {"current_password": password, "new_password": new_password,
                "confirm_password": new_password})
    stale.request("/admin", 302)
    client.form("/admin/login", {"username": "admin", "password": new_password})
    client.request("/admin")
    report["checks"].append("password_change_revokes_previous_cookie")
    spoof = {"Forwarded": 'for=198.51.100.1;proto=http;host=evil.invalid', "X-Forwarded-For": "198.51.100.2",
             "X-Forwarded-Proto": "http", "X-Forwarded-Host": "evil.invalid", "X-Forwarded-Port": "80",
             "X-Real-IP": "198.51.100.3"}
    client.request("/api/version", headers=spoof)
    client.request("/api/version", 400, headers={"Host": "evil.invalid"})
    for unused in range(10):
        client.form("/admin/login", {"username": "throttle-fixture", "password": "invalid"}, 401)
    unused, headers = client.form("/admin/login", {"username": "throttle-fixture", "password": "invalid"}, 429, spoof)
    if int(headers.get("Retry-After", "0")) < 1:
        raise RuntimeError("Missing authentication retry interval.")
    for index in range(40):
        token = client.token()
        body = urlencode({"username": f"source-fixture-{index}", "password": "invalid"}).encode()
        spoof["X-Forwarded-For"] = f"198.51.100.{index + 10}"
        client.request("/admin/login", (401, 429), body,
            {**spoof, "X-CSRF-Token": token, "Content-Type": "application/x-www-form-urlencoded"})
        if client.last_status == 429:
            break
    else:
        raise RuntimeError("Source authentication budget was bypassed.")
    report["checks"].append("forwarded_spoofing_host_and_authentication_limits")
    port = int(client.base.rsplit(":", 1)[1])
    report["phase"] = "body_limit"
    connection = http.client.HTTPSConnection("127.0.0.1", port, context=context, timeout=remaining(client.deadline))
    try:
        connection.putrequest("POST", "/admin/events/create")
        connection.putheader("Content-Length", str(REQUEST_LIMIT + 1))
        connection.putheader("Content-Type", "application/octet-stream")
        connection.endheaders()
        connection.send(b"x" * (256 * 1024 + 1))
        with connection.getresponse() as response:
            response.read()
            report["http_statuses"][str(response.status)] = report["http_statuses"].get(str(response.status), 0) + 1
            if response.status != 413:
                raise RuntimeError("Oversized declared body accepted.")
    finally:
        connection.close()
    report["checks"].append("request_body_limit")


def run_scenario(caddy, pwsh, root, deadline, report):
    report["phase"] = "tools"
    report["caddy"] = verify_caddy(caddy, root, deadline)
    result = command([str(pwsh), "-NoProfile", "-NonInteractive", "-Command", "$PSVersionTable.PSVersion.ToString()"], root, deadline)
    report["pwsh_version"] = result.stdout.decode().strip()
    report["phase"] = "certificates"
    helper = Path(__file__).with_name("https_certificates.ps1")
    command([str(pwsh), "-NoProfile", "-NonInteractive", "-File", str(helper), "-OutputDirectory", str(root)], root, deadline)
    context = verified_context(root / "authority.pem")
    password = secrets.token_urlsafe(24)
    backend = None
    proxy = None
    try:
        report["phase"] = "backend"
        backend = Backend(root, password, deadline)
        report["phase"] = "https"
        proxy = Proxy(caddy, root, backend.port, deadline)
        backend.connection.send({"origin": f"127.0.0.1:{proxy.port}"})
        check_listeners(pwsh, root, deadline, backend, proxy)
        report["checks"].append("only_two_loopback_tcp_listeners")
        plaintext = http.client.HTTPConnection("127.0.0.1", proxy.port, timeout=remaining(deadline))
        try:
            plaintext.request("GET", "/admin/login")
            with plaintext.getresponse() as response:
                response.read()
                if response.status != 400 or response.getheader("Set-Cookie"):
                    raise RuntimeError("Plaintext request was not rejected.")
                report["http_statuses"]["400"] = report["http_statuses"].get("400", 0) + 1
        finally:
            plaintext.close()
        report["checks"].append("plaintext_rejected_without_cookie")
        client = Client(proxy.port, context, deadline, report)
        exercise_application(client, password, context, report)
        check_tls_rejection(proxy.port, ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT), deadline, report, "unknown_authority")
        report["phase"] = "backend_failure"
        report["cleanup"]["backend"] = backend.close()
        client.request("/api/version", 502)
        invalid = {name for item in backend.observations for name, valid in item.get("metadata_checks", {}).items() if not valid}
        if invalid:
            report["checks"].extend("invalid_metadata_" + name for name in sorted(invalid))
        if not backend.observations or invalid or any("backend_error" in item for item in backend.observations):
            raise RuntimeError("Invalid forwarded request metadata.")
        report["metadata_requests"] = len(backend.observations)
        report["cleanup"]["proxy"] = proxy.close()
        proxy = None
        for fixture, label in (("wrong-name", "wrong_name"), ("expired", "expired")):
            report["phase"] = label
            proxy = Proxy(caddy, root, backend.port, deadline, fixture)
            check_tls_rejection(proxy.port, context, deadline, report, label)
            report["cleanup"][label] = proxy.close()
            proxy = None
        report["phase"] = "renewal"
        proxy = Proxy(caddy, root, backend.port, deadline, "renewed")
        with socket.create_connection(("127.0.0.1", proxy.port), timeout=remaining(deadline)) as connection:
            with context.wrap_socket(connection, server_hostname="127.0.0.1") as tls:
                renewed = ssl.PEM_cert_to_DER_cert((root / "renewed.pem").read_text(encoding="utf-8"))
                original = ssl.PEM_cert_to_DER_cert((root / "valid.pem").read_text(encoding="utf-8"))
                if tls.getpeercert(binary_form=True) != renewed or renewed == original:
                    raise RuntimeError("Replacement certificate was not served.")
                report["certificate_replaced"] = True
        report["cleanup"]["renewed"] = proxy.close()
        proxy = None
        report["phase"] = "invalid_configuration"
        for key in ("renewed", "missing"):
            configuration = root / "invalid.Caddyfile"
            configuration.write_text(caddy_configuration(24443, backend.port, "valid", key), encoding="utf-8")
            command([str(caddy), "validate", "--config", str(configuration), "--adapter", "caddyfile"], root, deadline, expected=1)
        report["checks"].extend(["backend_failure_no_fallback", "invalid_key_configurations", "certificate_replacement"])
    finally:
        try:
            if proxy is not None:
                report["cleanup"]["proxy_final"] = proxy.close()
        finally:
            if backend is not None:
                report["cleanup"]["backend"] = backend.close()


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--caddy", type=Path, required=True)
    parser.add_argument("--pwsh", type=Path, required=True)
    args = parser.parse_args(argv)
    if os.name != "nt":
        parser.error("This fixed prototype supports Windows only.")
    started = time.monotonic()
    report = {"success": False, "phase": "startup", "checks": [], "http_statuses": {}, "tls_failures": {}, "cleanup": {}}
    temporary = None
    try:
        with tempfile.TemporaryDirectory(prefix="kiosk-https-") as directory:
            temporary = Path(directory)
            run_scenario(args.caddy.resolve(), args.pwsh.resolve(), temporary, started + 180, report)
        report["success"] = True
        report["phase"] = "complete"
    except Exception as error:
        report["error"] = type(error).__name__
    finally:
        report["cleanup"]["temporary_removed"] = temporary is not None and not temporary.exists()
        report["success"] = report["success"] and report["cleanup"]["temporary_removed"]
        report["elapsed_seconds"] = round(time.monotonic() - started, 3)
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
        output = Path(__file__).resolve().parent.parent / "logs" / "https" / f"prototype-{stamp}.json"
        safe_report(output, report)
        print(json.dumps(report, indent=2))
        print(f"Report: logs/https/{output.name}")
    return 0 if report["success"] else 1


if __name__ == "__main__":
    sys.exit(main())
