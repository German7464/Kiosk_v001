"""One-origin native HTTPS, explicit public CA and per-connection SPKI binding."""
import http.client
import re
import ssl
from contextlib import contextmanager

from kiosk.delivery.protocol import decode, encode, sha
from kiosk.publication.exporter import PackageError
from .delivery_authority import origin
from .native_crypto import certificate_spki


# The server may legitimately ask for a wait longer than one poll interval
# (for example the 600 s device-decision budget). Only an implausible or
# malformed value is bounded, so a valid Retry-After is never truncated.
MAX_RETRY_SECONDS = 3600
DEFAULT_RETRY_SECONDS = 5


def retry_delay(value, default=DEFAULT_RETRY_SECONDS):
    """Parse Retry-After safely: non-numeric, non-positive or huge values are bounded."""
    try:
        seconds = int(str(value).strip())
    except (TypeError, ValueError, AttributeError):
        return default
    if seconds <= 0:
        return default
    return min(MAX_RETRY_SECONDS, seconds)


class TransportError(PackageError):
    def __init__(self, code, status=0, retry_after=DEFAULT_RETRY_SECONDS):
        self.status, self.retry_after = status, retry_delay(retry_after)
        super().__init__(code)


# The server's guarded errors are exactly ``{version:1,error:<fixed code>}``. Only
# that fixed label is retained; arbitrary body text, paths or headers never become
# a client reason. Anything else stays a generic transport refusal.
_REFUSAL = re.compile(r'[a-z][a-z0-9_]{0,63}\Z')


def refusal_reason(response):
    """Return the server's fixed refusal code for a non-success response, else None."""
    try:
        raw = response.read(4096)
        value = decode(raw)
        if not isinstance(value, dict) or set(value) != {'version', 'error'}:
            return None
        if type(value['version']) is not int or value['version'] != 1:
            return None
        code = value['error']
        return code if isinstance(code, str) and _REFUSAL.match(code) else None
    except (ValueError, OSError, http.client.HTTPException):
        return None


class Transport:
    def __init__(self, bootstrap, *, secret=None, audit=None, paths=('/api/v2/',)):
        self.host, self.port = origin(bootstrap['origin'])
        self.context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        self.context.minimum_version = ssl.TLSVersion.TLSv1_2
        self.context.load_verify_locations(cadata=bootstrap['tls_ca_pem'])
        self.secret, self.audit, self.paths = secret, audit, tuple(paths)
        # ``pin`` is the SPKI the client enforces; ``pin_kind`` selects leaf (legacy)
        # or issuer (intermediate) pinning. ``observed_pin``/``observed_issuer_pin``
        # are the SPKIs observed on the last handshake.
        self.pin, self.pin_kind, self.observed_pin, self.observed_issuer_pin = None, None, None, None

    def _peer_spkis(self, connection):
        """Return (leaf_spki_sha256, issuer_spki_sha256) for the served chain.

        The issuer is the first CA after the leaf (the intermediate that signed it).
        The chain is only read from a handshake that already validated to the
        bootstrap CA, so a MITM cannot substitute it.
        """
        sock = connection.sock
        if isinstance(sock, ssl.SSLSocket) and hasattr(sock, 'get_unverified_chain'):
            chain = sock.get_unverified_chain()
        else:  # Python < 3.13 or a test double: only the leaf is available.
            chain = [sock.getpeercert(binary_form=True)]
        leaf = sha(certificate_spki(chain[0]))
        issuer = sha(certificate_spki(chain[1])) if len(chain) > 1 else None
        return leaf, issuer

    @contextmanager
    def response(self, path, *, body=None, headers=None, authenticated=True):
        if not any(path.startswith(prefix) for prefix in self.paths) or '\r' in path or '\n' in path:
            raise PackageError('invalid_native_route')
        request_headers = {'Accept': 'application/json', 'Accept-Encoding': 'identity'}
        request_headers.update(headers or {})
        if authenticated:
            if not self.secret:
                raise PackageError('enrollment_required')
            request_headers['Authorization'] = 'Bearer ' + self.secret
        payload = None if body is None else encode(body)
        if payload is not None:
            request_headers['Content-Type'] = 'application/json'
        connection = http.client.HTTPSConnection(self.host, self.port, context=self.context, timeout=15)
        response = None
        try:
            connection.connect()
            observed_leaf, observed_issuer = self._peer_spkis(connection)
            self.observed_pin, self.observed_issuer_pin = observed_leaf, observed_issuer
            if self.pin is not None:
                expected = observed_leaf if self.pin_kind == 'leaf' else observed_issuer
                if expected is None or expected != self.pin:
                    raise PackageError('tls_publisher_pin_refused')
            connection.request('GET' if body is None else 'POST', path, body=payload, headers=request_headers)
            response = connection.getresponse()
            if self.audit:
                self.audit({'method': 'GET' if body is None else 'POST', 'path': path,
                            'status': response.status, 'range': request_headers.get('Range'),
                            'etag': response.getheader('ETag'), 'content_range': response.getheader('Content-Range'),
                            'length': response.getheader('Content-Length'), 'tls_spki_sha256': observed_leaf,
                            'tls_issuer_spki_sha256': observed_issuer})
            if 300 <= response.status < 400:
                raise TransportError('redirect_refused', response.status)
            if response.getheader('Content-Encoding', 'identity') != 'identity':
                raise TransportError('encoding_refused', response.status)
            for name in ('Content-Length', 'ETag', 'Content-Range', 'Content-Encoding'):
                if sum(key.lower() == name.lower() for key, _ in response.getheaders()) > 1:
                    raise TransportError('duplicate_header_refused', response.status)
            yield response
        except (OSError, http.client.HTTPException):
            raise TransportError('network_unavailable') from None
        finally:
            if response:
                response.close()
            connection.close()

    def json(self, path, *, body=None, authenticated=True, allowed=(200,)):
        with self.response(path, body=body, authenticated=authenticated) as response:
            if response.status not in allowed:
                reason = refusal_reason(response)
                raise TransportError(reason or 'native_http_refused', response.status,
                                     response.getheader('Retry-After', DEFAULT_RETRY_SECONDS))
            if response.getheader('Content-Type', '').split(';')[0] != 'application/json':
                raise TransportError('json_content_type_refused', response.status)
            value = decode(response.read(2 * 1024 * 1024 + 1))
            return value
