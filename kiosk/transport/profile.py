import hashlib
import ipaddress
import json
import re
import ssl
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit


CADDY_VERSION = "v2.11.7"
CADDY_SHA256 = "5f93a9bd555f3aac9d33af2756ba14b3519d8cca4ffd55256bdaeab444c9db2a"


def unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Duplicate HTTPS configuration field.")
        result[key] = value
    return result


@dataclass(frozen=True)
class HttpsProfile:
    public_origin: str
    hostname: str
    authority: str
    port: int
    listen_host: str
    caddy_executable: Path
    certificate_file: Path
    private_key_file: Path
    ca_file: Path

    def trust_context(self):
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        context.minimum_version = ssl.TLSVersion.TLSv1_2
        context.load_verify_locations(cafile=str(self.ca_file))
        return context


def load_profile(filename):
    filename = Path(filename).resolve()
    if filename.stat().st_size > 65536:
        raise ValueError("HTTPS configuration is too large.")
    data = json.loads(filename.read_text(encoding="utf-8"), object_pairs_hook=unique_object)
    fields = {"schema_version", "public_origin", "listen_host", "caddy_executable", "certificate_file", "private_key_file", "ca_file"}
    if not isinstance(data, dict) or set(data) != fields or type(data["schema_version"]) is not int or data["schema_version"] != 1:
        raise ValueError("Invalid HTTPS configuration fields or version.")
    if any(not isinstance(data[name], str) or not data[name] or any(ord(char) < 32 for char in data[name]) for name in fields - {"schema_version"}):
        raise ValueError("Invalid HTTPS configuration value.")
    origin = urlsplit(data["public_origin"])
    hostname = origin.hostname
    if origin.scheme != "https" or origin.username is not None or origin.password is not None or origin.path or origin.query or origin.fragment or not hostname:
        raise ValueError("An HTTPS origin without a path or credentials is required.")
    if not re.fullmatch(r"[a-z0-9](?:[a-z0-9.-]*[a-z0-9])?", hostname) or len(hostname) > 253:
        raise ValueError("Invalid HTTPS hostname.")
    if any(not label or len(label) > 63 or label.startswith("-") or label.endswith("-") for label in hostname.split(".")):
        raise ValueError("Invalid HTTPS hostname labels.")
    if all(char in "0123456789." for char in hostname):
        ipaddress.IPv4Address(hostname)
    port = origin.port or 443
    if not 1 <= port <= 65535 or origin.netloc.endswith(":") or origin.port == 0:
        raise ValueError("Invalid HTTPS port.")
    listen_host = str(ipaddress.IPv4Address(data["listen_host"]))
    authority = hostname if port == 443 else f"{hostname}:{port}"
    if data["public_origin"].lower() != f"https://{origin.netloc.lower()}" or origin.netloc.lower() not in {authority, f"{hostname}:443" if port == 443 else authority}:
        raise ValueError("Invalid HTTPS authority.")
    paths = {name: (filename.parent / data[name]).resolve() for name in fields - {"schema_version", "public_origin", "listen_host"}}
    if any(not path.is_file() for path in paths.values()):
        raise ValueError("An HTTPS input file is unavailable.")
    with paths["caddy_executable"].open("rb") as executable:
        if hashlib.file_digest(executable, "sha256").hexdigest() != CADDY_SHA256:
            raise ValueError("Caddy executable does not match the pinned release.")
    profile = HttpsProfile(f"https://{authority}", hostname, authority, port, listen_host, **paths)
    profile.trust_context()
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.load_cert_chain(str(profile.certificate_file), str(profile.private_key_file), password=lambda: b"")
    return profile


def proxy_configuration(profile, backend_port, admin_port, maximum_body, identity):
    for value in (backend_port, admin_port):
        if type(value) is not int or not 0 < value < 65536:
            raise ValueError("Invalid internal HTTPS port.")
    if type(maximum_body) is not int or maximum_body <= 0:
        raise ValueError("Invalid HTTPS body limit.")
    admin = f"127.0.0.1:{admin_port}"
    return {
        "admin": {"listen": admin, "enforce_origin": True, "origins": [admin], "config": {"persist": False}},
        "storage": {"module": "file_system", "root": "storage"},
        "apps": {
            "tls": {"certificates": {"load_files": [{"certificate": str(profile.certificate_file), "key": str(profile.private_key_file), "tags": ["server"]}]}},
            "http": {"grace_period": 8000000000, "servers": {"protected": {
                "listen": [f"{profile.listen_host}:{profile.port}"],
                "protocols": ["h1", "h2"], "automatic_https": {"disable": True},
                "tls_connection_policies": [{"certificate_selection": {"any_tag": ["server"]}, "protocol_min": "tls1.2", "protocol_max": "tls1.3"}],
                "routes": [
                    {"match": [{"not": [{"header": {"Host": [profile.authority]}}]}], "handle": [{"handler": "static_response", "status_code": 400}]},
                    {"match": [{"expression": {"name": "oversized", "expr": f'{{http.request.header.Content-Length}} != "" && int({{http.request.header.Content-Length}}) > {maximum_body}'}}], "handle": [{"handler": "static_response", "status_code": 413}]},
                    {"handle": [
                        {"handler": "request_body", "max_size": maximum_body},
                        {"handler": "headers", "request": {"delete": ["Forwarded", "X-Forwarded-*", "X-Real-IP"]}},
                        {"@id": identity, "handler": "reverse_proxy", "upstreams": [{"dial": f"127.0.0.1:{backend_port}"}], "headers": {"request": {"set": {
                            "Host": [profile.authority], "X-Forwarded-Host": [profile.authority],
                            "X-Forwarded-Proto": ["https"], "X-Forwarded-For": ["{http.request.remote.host}"]
                        }}}}
                    ]}
                ]
            }}}
        }
    }
