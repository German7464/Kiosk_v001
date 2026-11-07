"""Bounded advisory IPv4 discovery. Hints never grant native authority."""
from collections import deque
import re
import secrets
import socket
import threading
import time

from kiosk.delivery.protocol import decode, encode, fields
from kiosk.display.delivery_authority import origin

PORT = 47751
PROTOCOL = 'kiosk-discovery-v1'
MAX_BYTES = 512


def nonce(value):
    if not isinstance(value, str) or re.fullmatch('[0-9a-f]{32}', value) is None:
        raise ValueError('invalid_nonce')
    return value


def public_hint(address, label):
    origin(address)
    if (not isinstance(label, str) or len(label) > 64 or
            any(not char.isprintable() for char in label)):
        raise ValueError('invalid_label')
    value = dict(protocol=PROTOCOL, type='reply', nonce='0'*32, origin=address, label=label)
    if len(encode(value)) > MAX_BYTES:
        raise ValueError('reply_size')
    return value


def query(value):
    raw = encode(dict(protocol=PROTOCOL, type='query', nonce=nonce(value)))
    return raw.ljust(MAX_BYTES, b' ')


def parse(raw, kind, expected=None):
    if not isinstance(raw, bytes) or not 1 <= len(raw) <= MAX_BYTES:
        raise ValueError('datagram_size')
    value = decode(raw)
    fields(value, 'protocol type nonce' + (' origin label' if kind == 'reply' else ''))
    if value['protocol'] != PROTOCOL or value['type'] != kind:
        raise ValueError('invalid_protocol')
    nonce(value['nonce'])
    # Padding is ASCII spaces, independent of JSON key ordering/inner whitespace.
    if kind == 'query' and (len(raw) != MAX_BYTES or not raw.endswith(b' ') or
                            not raw.rstrip(b' ').endswith(b'}')):
        raise ValueError('query_padding')
    if kind == 'reply':
        public_hint(value['origin'], value['label'])
        if value['nonce'] != expected:
            raise ValueError('stale_nonce')
    return value


class RateLimit:
    def __init__(self):
        self.sources = {}
        self.total = deque(maxlen=32)

    def allow(self, address, now):
        while self.total and now - self.total[0] >= 1:
            self.total.popleft()
        self.sources = {key: stamp for key, stamp in self.sources.items() if now - stamp < 1}
        if address in self.sources or len(self.sources) >= 256 or len(self.total) >= 32:
            return False
        self.sources[address] = now
        self.total.append(now)
        return True


def receive(sock):
    try:
        return sock.recvfrom(MAX_BYTES + 1)
    except OSError as error:
        # Windows reports WSAEMSGSIZE instead of returning a truncated packet.
        if getattr(error, 'winerror', None) == 10040 or error.errno == 10040:
            return b'', None
        raise


class Responder:
    """Explicit runtime-owned listener; a bind error leaves HTTPS running."""
    def __init__(self, address, label, *, audit=None):
        self.template = public_hint(address, label)
        self.audit = audit
        self.stop = threading.Event()
        self.socket = None
        self.thread = None
        self.error = None
        self.limiter = RateLimit()

    def start(self):
        if self.thread is not None or self.socket is not None:
            raise RuntimeError('discovery_already_started')
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            if hasattr(socket, 'SO_EXCLUSIVEADDRUSE'):
                sock.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
            sock.bind(('0.0.0.0', PORT))
            sock.settimeout(.05)
            self.socket = sock
            self.thread = threading.Thread(target=self._serve, name='kiosk-discovery', daemon=False)
            self.thread.start()
        except OSError as error:
            sock.close()
            self.error = dict(state='bind_failed', errno=error.errno, winerror=getattr(error, 'winerror', None))
            return False
        return True

    def _serve(self):
        try:
            while not self.stop.is_set():
                try:
                    raw, sender = receive(self.socket)
                except socket.timeout:
                    continue
                if self.stop.is_set():
                    break
                try:
                    value = parse(raw, 'query')
                except ValueError:
                    continue
                if sender is None or not self.limiter.allow(sender[0], time.monotonic()):
                    continue
                reply = encode(dict(self.template, nonce=value['nonce']))
                self.socket.sendto(reply, sender)
                if self.audit:
                    self.audit(dict(query=raw.decode('utf-8'), reply=reply.decode('utf-8'), sender=list(sender),
                                    listener=list(self.socket.getsockname())))
        except OSError as error:
            if not self.stop.is_set():
                self.error = dict(state='socket_failed', errno=error.errno)
        finally:
            self.socket.close()

    def close(self):
        self.stop.set()
        if self.thread:
            self.thread.join(timeout=1)
            if self.thread.is_alive():
                raise RuntimeError('discovery_shutdown_timeout')
        elif self.socket:
            self.socket.close()


def search(stop, *, audit=None):
    """One ephemeral socket, <=3 broadcasts/3 seconds, <=256 inputs/32 hints."""
    request_nonce = secrets.token_hex(16)
    raw = query(request_nonce)
    results = {}
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        sock.bind(('0.0.0.0', 0))
        sock.settimeout(.05)
        start = time.monotonic()
        sent = received = 0
        while not stop.is_set() and time.monotonic() - start < 3 and received < 256:
            elapsed = time.monotonic() - start
            if sent < 3 and elapsed >= sent:
                sock.sendto(raw, ('255.255.255.255', PORT))
                sent += 1
                if audit:
                    audit(dict(direction='send', local=list(sock.getsockname()),
                               remote=['255.255.255.255', PORT], datagram=raw.decode('utf-8')))
            try:
                reply, sender = receive(sock)
            except socket.timeout:
                continue
            received += 1
            if audit:
                audit(dict(direction='receive', remote=list(sender) if sender else None,
                           bytes=len(reply), datagram=reply.decode('utf-8', errors='replace')))
            try:
                hint = parse(reply, 'reply', request_nonce)
            except ValueError:
                continue
            if len(results) < 32 and hint['origin'] not in results:
                results[hint['origin']] = dict(origin=hint['origin'], label=hint['label'])
        return [] if stop.is_set() else list(results.values())


def start_discovery(app):
    config = app.config.get('LAN_DISCOVERY')
    if config is None:
        return None
    # No truthy strings or implicit opt-in. Configuration mistakes are visible,
    # but must not take down an otherwise healthy HTTPS server.
    try:
        if type(config) is dict and config.get('enabled') is False:
            return None
        if type(config) is not dict or set(config) != {'enabled', 'origin', 'label'} or config['enabled'] is not True:
            raise ValueError('invalid_discovery_configuration')
        responder = Responder(config['origin'], config['label'], audit=app.extensions.get('discovery_audit'))
        app.extensions['lan_discovery'] = responder
        if not responder.start():
            app.logger.error('LAN discovery unavailable: %s', responder.error)
        return responder
    except ValueError:
        app.extensions['lan_discovery_error'] = 'invalid_configuration'
        app.logger.error('LAN discovery invalid configuration; HTTPS retained')
        return None
