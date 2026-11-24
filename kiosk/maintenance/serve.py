"""Supported HTTPS runtime for one service side.

Each side is a Windows service identity that owns a Waitress backend and a
pinned Caddy TLS edge on the exact configured origin. Caddy is the same pinned
build already used by the installed LAN runtime; the backend only listens on
loopback and trusts proxy headers from that single loopback peer.

This is deliberately not a Flask development server: the public listener, TLS
termination, body limits and header sanitising are the production components.
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import socket
import subprocess
import threading
import time
from pathlib import Path

CADDY_VERSION = 'v2.11.7'
CADDY_SHA256 = '5f93a9bd555f3aac9d33af2756ba14b3519d8cca4ffd55256bdaeab444c9db2a'
REQUEST_LIMIT = 8 * 1024 * 1024
MAX_BACKEND_BYTES = 1024 * 1024


class RuntimeError_(RuntimeError):
    pass


def verify_caddy(path):
    path = Path(path)
    if not path.is_file():
        raise RuntimeError_('caddy_missing')
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    if digest != CADDY_SHA256:
        raise RuntimeError_('caddy_identity_mismatch')
    return digest


def _free_port():
    with socket.socket() as probe:
        probe.bind(('127.0.0.1', 0))
        return probe.getsockname()[1]


def _origin_host(host):
    """Accept loopback names and literal unicast addresses, refuse DNS names.

    Combined installations normally use loopback. Separated placement needs the
    side to answer on its real LAN address, so any literal unicast IP is allowed;
    a hostname is refused because the leaf and the edge are pinned to that exact
    address and no name-resolution trust shortcut is introduced.
    """
    import ipaddress
    if host == 'localhost':
        return host
    try:
        address = ipaddress.ip_address(host or '')
    except ValueError:
        raise RuntimeError_('origin_host_refused') from None
    if address.is_unspecified or address.is_multicast:
        raise RuntimeError_('origin_host_refused')
    return str(address)


def caddyfile(origin, certificate, key, backend_port, storage):
    from urllib.parse import urlsplit
    parsed = urlsplit(origin)
    if parsed.scheme != 'https' or parsed.port is None:
        raise RuntimeError_('origin_refused')
    host = _origin_host(parsed.hostname)
    if parsed.path not in ('', '/') or parsed.query or parsed.fragment:
        raise RuntimeError_('origin_refused')
    return f"""{{
    admin off
    persist_config off
    auto_https off
    skip_install_trust
    storage file_system {storage}
    servers {{
        protocols h1 h2
    }}
}}

https://{host}:{parsed.port} {{
    bind {host}
    tls {certificate} {key} {{
        protocols tls1.2 tls1.3
    }}
    @invalid not host {host}
    respond @invalid 400
    request_body {{
        max_size {REQUEST_LIMIT}
    }}
    request_header -Forwarded
    request_header -X-Forwarded-*
    request_header -X-Real-IP
    reverse_proxy 127.0.0.1:{backend_port} {{
        header_up Host {host}:{parsed.port}
        header_up X-Forwarded-Host {host}:{parsed.port}
        header_up X-Forwarded-Proto https
        header_up X-Forwarded-For {{http.request.remote.host}}
    }}
}}
"""


class Runtime:
    """One side: Caddy in front of an in-process Waitress application."""

    def __init__(self, config_path, side, *, caddy_path, log_path=None, logger=None):
        self.config_path = Path(config_path)
        self.side = side
        self.logger = logger or logging.getLogger('kiosk.maintenance.host.' + side)
        self.log_path = Path(log_path) if log_path else None
        self.value = json.loads(self.config_path.read_text(encoding='utf-8'))
        self.tls = self.value.get('TLS') or {}
        if not self.tls.get('cert') or not self.tls.get('key'):
            raise RuntimeError_('tls_material_missing')
        self.origin = (self.value.get('MAINTENANCE_ORIGIN') if side == 'maintenance'
                       else self.value['ROAMING_WORKSPACE']['origin'])
        self.root = (self.config_path.parents[1]
                     if self.config_path.parent.name == 'config'
                     else self.config_path.parent)
        self.caddy_path = Path(caddy_path)
        self.caddy = None
        self.server = None
        self.thread = None
        self.stopped = threading.Event()
        self.caddy_log = None
        self.edge_lock = threading.RLock()
        self.tls_manager = None

    def _backend(self, app, port):
        from waitress import create_server
        server = create_server(
            app, host='127.0.0.1', port=port, threads=8, map={},
            max_request_body_size=REQUEST_LIMIT,
            trusted_proxy='127.0.0.1', trusted_proxy_count=1,
            trusted_proxy_headers={'x-forwarded-for', 'x-forwarded-proto',
                                   'x-forwarded-host'},
            clear_untrusted_proxy_headers=True)
        self.server = server
        return server

    def start(self):
        from .apps import application
        verify_caddy(self.caddy_path)
        app = application(self.config_path, self.side)
        if self.value.get('TLS_RENEWAL'):
            from .tls_runtime import TLSRuntime
            self.tls_manager = TLSRuntime(self, app)
            self.tls_manager.prepare_start()
        self.backend_port = _free_port()
        self._backend(app, self.backend_port)
        self.thread = threading.Thread(target=self._loop, name=self.side + '-backend',
                                       daemon=True)
        self.thread.start()
        self.caddy_log = open(self.root / 'logs' / (self.side + '-caddy.log'), 'ab')
        self._start_edge()
        if self.tls_manager:
            self.tls_manager.started()
        return self

    def _start_edge(self):
        storage = self.root / 'caddy' / self.side
        storage.mkdir(parents=True, exist_ok=True)
        config = self.root / 'caddy' / (self.side + '.caddyfile')
        config.write_text(caddyfile(self.origin, self.tls['cert'], self.tls['key'],
                                    self.backend_port, str(storage)), encoding='utf-8')
        self.caddy = subprocess.Popen(
            [str(self.caddy_path), 'run', '--config', str(config), '--adapter', 'caddyfile'],
            cwd=str(self.root), stdout=self.caddy_log, stderr=subprocess.STDOUT,
            creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))

    def _stop_edge(self):
        if self.caddy is not None and self.caddy.poll() is None:
            self.caddy.terminate()
            try:
                self.caddy.wait(timeout=10)
            except subprocess.TimeoutExpired:
                self.caddy.kill()
                self.caddy.wait(timeout=5)

    def rotate_edge(self, tls, expected=None):
        from .tls_runtime import verify_serving
        with self.edge_lock:
            if self.stopped.is_set():
                raise RuntimeError_('runtime_stopping')
            self._stop_edge()
            self.tls = dict(tls)
            self._start_edge()
            if expected is not None:
                verify_serving(self.origin, self.tls['ca'], expected)

    def edge_failed(self):
        with self.edge_lock:
            return self.caddy is None or self.caddy.poll() is not None

    def _loop(self):
        server = self.server
        while not self.stopped.is_set():
            try:
                server.asyncore.loop(timeout=0.25, count=1, map=server._map)
            except (OSError, ValueError):
                if self.stopped.is_set():
                    return
                time.sleep(0.1)

    def stop(self):
        self.stopped.set()
        if self.tls_manager and self.tls_manager.thread:
            self.tls_manager.thread.join(timeout=15)
        with self.edge_lock:
            self._stop_edge()
        if self.thread is not None:
            self.thread.join(timeout=5)
        if self.server is not None:
            try:
                self.server.task_dispatcher.shutdown(timeout=5)
                self.server.close()
                self.server.asyncore.close_all(map=self.server._map)
            except Exception:
                pass
        if self.caddy_log is not None:
            self.caddy_log.close()

    def wait_ready(self, timeout=60):
        import ssl
        import urllib.error
        import urllib.request
        context = ssl.create_default_context(cafile=str(self.tls['ca']))
        deadline = time.monotonic() + timeout
        path = '/api/health' if self.side == 'maintenance' else '/'
        while time.monotonic() < deadline:
            if self.edge_failed():
                raise RuntimeError_('caddy_exited')
            try:
                with urllib.request.urlopen(self.origin + path, context=context,
                                            timeout=5) as response:
                    if response.status < 500:
                        return True
            except urllib.error.HTTPError as error:
                # A bound 4xx answer still proves the TLS edge and backend work.
                code = error.code
                error.close()
                if code < 500:
                    return True
                time.sleep(0.5)
            except Exception:
                time.sleep(0.5)
        raise RuntimeError_('runtime_not_ready')

    def log(self, text):
        line = f'{time.strftime("%Y-%m-%dT%H:%M:%S")} {self.side} {text}'
        self.logger.info(line)
        if self.log_path:
            self.log_path.parent.mkdir(parents=True, exist_ok=True)
            with self.log_path.open('a', encoding='utf-8') as stream:
                stream.write(line + '\n')
