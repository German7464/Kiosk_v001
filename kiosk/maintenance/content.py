"""Authenticated HTTPS client for the content-service contract.

No verification bypass and no shared database: every call is a signed request to
the exact configured origin and is refused by the content service unless the
TLS origin, service identity, body digest, timestamp and nonce all match.
"""
from __future__ import annotations

import hashlib
import hmac
import http.client
import json
import ssl
import time
from urllib.parse import urlsplit

from kiosk.delivery.protocol import decode, encode

MAX_RESPONSE = 8 * 1024 * 1024


class ContentRefused(ValueError):
    def __init__(self, code, status=0):
        self.code, self.status = code, status
        super().__init__(code)


class ContentClient:
    def __init__(self, origin, ca_file, service_id, secret, *, timeout=20):
        parsed = urlsplit(origin)
        if parsed.scheme != 'https' or not parsed.hostname or parsed.port is None:
            raise ContentRefused('content_origin_refused')
        if parsed.username or parsed.password or parsed.path or parsed.query or parsed.fragment:
            raise ContentRefused('content_origin_refused')
        self.origin = origin
        self.host, self.port = parsed.hostname, parsed.port
        self.service_id = service_id
        self.secret = secret.encode('utf-8')
        self.context = ssl.create_default_context(cafile=str(ca_file))
        self.context.minimum_version = ssl.TLSVersion.TLSv1_2
        self.timeout = timeout

    def _request(self, method, path, payload=None, *, headers=None, allow_fenced=False):
        body = b'' if payload is None else encode(payload)
        if len(body) > MAX_RESPONSE:
            raise ContentRefused('request_limit', 413)
        digest = hashlib.sha256(body).hexdigest()
        now = str(int(time.time()))
        import secrets
        nonce = secrets.token_hex(32)
        message = '\n'.join((self.service_id, method, path, now, nonce, digest))
        signature = hmac.new(self.secret, message.encode('utf-8'), hashlib.sha256).hexdigest()
        headers = dict(headers or {})
        headers.update({
            'Accept': 'application/json', 'Accept-Encoding': 'identity',
            'X-Kiosk-Service-Id': self.service_id, 'X-Kiosk-Time': now,
            'X-Kiosk-Nonce': nonce, 'X-Kiosk-Body-SHA256': digest,
            'X-Kiosk-Signature': signature,
        })
        if payload is not None:
            headers['Content-Type'] = 'application/json'
        connection = http.client.HTTPSConnection(self.host, self.port, context=self.context,
                                                 timeout=self.timeout)
        try:
            connection.request(method, path, body=body or None, headers=headers)
            response = connection.getresponse()
            raw = response.read(MAX_RESPONSE + 1)
            if len(raw) > MAX_RESPONSE:
                raise ContentRefused('response_limit', 413)
            if 300 <= response.status < 400:
                raise ContentRefused('redirect_refused', response.status)
            if response.status >= 400:
                code = 'content_http_refused'
                try:
                    value = decode(raw)
                    if isinstance(value, dict) and isinstance(value.get('error'), str):
                        code = value['error']
                except ValueError:
                    pass
                raise ContentRefused(code, response.status)
            return decode(raw) if raw else {}
        except (OSError, http.client.HTTPException):
            raise ContentRefused('content_unavailable') from None
        finally:
            connection.close()

    # -- contract ------------------------------------------------------------
    def session(self, user_id, chain):
        return self._request('POST', '/service/v1/session',
                             {'user_id': user_id, 'chain': chain})['secret']

    def targets(self, secret):
        return self._request('GET', '/service/v1/targets',
                             headers={'X-Kiosk-Content-Session': secret})['targets']

    def drafts(self, secret):
        return self._request('GET', '/service/v1/drafts',
                             headers={'X-Kiosk-Content-Session': secret})

    def save_draft(self, secret, identity, expected_version, payload, dependencies):
        return self._request('POST', '/service/v1/draft', dict(
            secret=secret, identity=identity, expected_version=expected_version,
            payload=payload, dependencies=dependencies))

    def ready_draft(self, secret, identity, version):
        return self._request('POST', '/service/v1/draft/ready', dict(
            secret=secret, identity=identity, version=version))

    def save_settings(self, secret, expected_version, values):
        return self._request('POST', '/service/v1/settings', dict(
            secret=secret, expected_version=expected_version, values=values))

    def prepare(self, secret, selected, targets, parents):
        return self._request('POST', '/service/v1/prepare', dict(
            secret=secret, selected=selected, targets=targets, parents=parents))

    def approve(self, identity, approval, chain, receipt, acceptance_key):
        return self._request('POST', '/service/v1/approve', dict(
            id=identity, approval=approval, chain=chain, receipt=receipt,
            acceptance_key=acceptance_key))

    def status(self, identity, secret):
        return self._request('GET', f'/service/v1/status/{identity}',
                             headers={'X-Kiosk-Content-Session': secret})

    def candidate(self, identity):
        return self._request('GET', f'/service/v1/candidate/{identity}')['document']

    def history(self, secret):
        return self._request('GET', '/service/v1/history',
                             headers={'X-Kiosk-Content-Session': secret})

    def manifest(self):
        return self._request('GET', '/service/v1/manifest')['manifest']

    def fence(self, reason):
        return self._request('POST', '/service/v1/fence', {'reason': reason})

    def activate(self, generation, fence, origin):
        return self._request('POST', '/service/v1/activate',
                             {'generation': generation, 'fence': fence, 'origin': origin})
