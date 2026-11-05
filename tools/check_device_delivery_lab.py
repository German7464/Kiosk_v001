"""Real TLS/API check for disposable lab data; never logs secrets or cookies."""
import argparse
from collections import Counter
import hashlib
from http.cookiejar import CookieJar
import json
from pathlib import Path
import re
import secrets
import socket
import ssl
import time
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import HTTPRedirectHandler, HTTPSHandler, HTTPCookieProcessor, ProxyHandler, Request, build_opener


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


def encoded(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False).encode('utf-8')


def digest(value):
    return hashlib.sha256(value).hexdigest()


class LabClient:
    def __init__(self, root):
        self.root = root
        self.bootstrap = json.loads((root / 'public/bootstrap.json').read_bytes())
        self.origin = self.bootstrap['origin']
        self.context = ssl.create_default_context(cafile=str(root / 'public/lab-ca.pem'))
        self.jar = CookieJar()
        self.opener = build_opener(ProxyHandler({}), HTTPSHandler(context=self.context), HTTPCookieProcessor(self.jar), NoRedirect())
        self.statuses = Counter()

    def call(self, path, expected=200, *, body=None, form=None, secret=None, csrf=None):
        headers = {}
        data = None
        if body is not None:
            data = encoded(body)
            headers['Content-Type'] = 'application/json'
        if form is not None:
            data = urlencode(form).encode('ascii')
            headers['Content-Type'] = 'application/x-www-form-urlencoded'
        if secret:
            headers['Authorization'] = 'Bearer ' + secret
        if csrf:
            headers['X-CSRF-Token'] = csrf
        try:
            response = self.opener.open(Request(self.origin + path, data=data, headers=headers), timeout=10)
        except HTTPError as error:
            response = error
        with response:
            payload = response.read(2 * 1024 * 1024 + 1)
            status = response.status
        self.statuses[status] += 1
        if status != expected:
            raise RuntimeError('Unexpected status %s for %s' % (status, path.split('?')[0]))
        return payload

    def csrf(self):
        page = self.call('/kiosk')
        match = re.search(rb'name="csrf-token" content="([a-f0-9]{64})"', page)
        if not match:
            raise RuntimeError('Missing existing CSRF token')
        return match.group(1).decode('ascii')

    def login(self):
        password = (self.root / 'admin-private/admin-password.txt').read_text(encoding='utf-8')
        self.call('/admin/login', 302, form={'username': 'admin', 'password': password}, csrf=self.csrf())


def probe(root):
    client = LabClient(root)
    client.call('/api/version')
    host_port = client.origin.removeprefix('https://').rsplit(':', 1)
    host, port = host_port[0], int(host_port[1])
    refusals = {}
    for label, context, hostname in (('untrusted_root', ssl.create_default_context(), host), ('wrong_name', client.context, 'wrong-name.invalid')):
        try:
            with socket.create_connection((host, port), timeout=10) as stream:
                with context.wrap_socket(stream, server_hostname=hostname):
                    raise RuntimeError('TLS negative unexpectedly accepted')
        except ssl.SSLCertVerificationError:
            refusals[label] = 'certificate_verification_refused'
        except ssl.SSLError:
            if label != 'wrong_name':
                raise
            refusals[label] = 'server_rejected_unknown_sni_before_certificate_validation'
    return client, {'tls_chain_and_ip': 'PASS', **refusals}


def exercise(client, report):
    client.login()
    bootstrap = client.bootstrap
    secret = secrets.token_hex(32)
    binding = {'version': 1, 'request_id': secrets.token_hex(16), 'device_id': 'pc1-api-' + secrets.token_hex(8),
               'group_id': bootstrap['group_id'], 'profile': 'events-phone-lab-v1', 'origin': client.origin,
               'nonce': secrets.token_hex(16), 'secret_verifier': digest(bytes.fromhex(secret))}
    request = json.loads(client.call('/api/v2/device/authorize', body=binding))
    repeated = json.loads(client.call('/api/v2/device/authorize', body=binding))
    if repeated['device_code'] != request['device_code']:
        raise RuntimeError('Enrollment retry changed identity')
    client.call('/api/v2/device/token', 202, body={'device_code': request['device_code']})
    client.call('/api/v2/device/token', 429, body={'device_code': request['device_code']})
    pending = json.loads(client.call('/admin/devices/pending'))
    row = next(row for row in pending['requests'] if row['request_id'] == binding['request_id'])
    decision = {'user_code': request['user_code'], 'binding_sha256': row['binding_sha256'], 'decision': 'approve'}
    path = '/admin/devices/' + binding['request_id'] + '/decision'
    client.call(path, 403, body=decision)
    approved = json.loads(client.call(path, body=decision, csrf=client.csrf()))
    repeat_approved = json.loads(client.call(path, body=decision, csrf=client.csrf()))
    if approved != repeat_approved:
        raise RuntimeError('Duplicate approval changed credential')
    first = client.call('/api/v2/device/token', body={'device_code': request['device_code']})
    if first != client.call('/api/v2/device/token', body={'device_code': request['device_code']}):
        raise RuntimeError('Lost approval response not recoverable')
    trust = json.loads(client.call('/api/v2/group/trust', secret=secret))
    # Signature verification is performed by the native client; this probe records no authority claim.
    report['trust_envelope_sha256'] = digest(encoded(trust))
    renderer = json.loads((client.root / 'public/capability.json').read_bytes())['renderer']
    assignment_path = '/api/v2/client/assignment?' + urlencode({'renderer': renderer, 'resource_profile': binding['profile']})
    client.call(assignment_path, 401)
    client.call('/api/v2/client/assignment?renderer=unsupported&resource_profile=' + binding['profile'], 409, secret=secret)
    assignment = json.loads(client.call(assignment_path, secret=secret))
    publication = assignment['publication']
    if digest(encoded(publication)) != assignment['metadata_sha256']:
        raise RuntimeError('Metadata identity mismatch')
    downloaded = 0
    for group in ('package', 'kiosk', 'tv'):
        for item in publication[group]['files']:
            data = client.call('/api/v2/publications/' + publication['package_id'] + '/' + group + '/' + item['path'], secret=secret)
            if len(data) != item['size'] or digest(data) != item['sha256']:
                raise RuntimeError('Artifact mismatch')
            downloaded += 1
    client.call('/api/v2/publications/' + publication['package_id'] + '/package/delivery.sqlite', 404, secret=secret)
    # This is an API fixture, not a claim of a renderer or physical screen ready event.
    receipt = {'version': 1, 'receipt_id': secrets.token_hex(16), 'group_id': bootstrap['group_id'],
               'device_id': binding['device_id'], 'generation': assignment['generation'],
               'package_id': publication['package_id'], 'mode': 'tv', 'session': 'api-fixture', 'result': 'ready'}
    client.call('/api/v2/client/receipts', body=receipt, secret=secret)
    client.call('/api/v2/client/receipts', body=receipt, secret=secret)
    client.call('/api/v2/client/receipts', 409, body={**receipt, 'mode': 'kiosk'}, secret=secret)
    # Edit through existing authenticated Events routes; background publication must advance itself.
    events = json.loads(client.call('/api/events'))['events']
    original = events[0]
    changed = {key: original.get(key) or '' for key in ('title', 'short_description', 'full_description', 'event_date', 'place', 'status', 'sort_order')}
    changed['title'] = 'Laboratory Events B — network API fixture'
    try:
        client.call('/admin/events/' + str(original['id']) + '/edit', 302, form=changed, csrf=client.csrf())
        until = time.monotonic() + 15
        while time.monotonic() < until:
            newer = json.loads(client.call(assignment_path, secret=secret))
            if newer['generation'] > assignment['generation']:
                break
            time.sleep(0.5)
        else:
            raise RuntimeError('Edited Events did not automatically publish')
        report['automatic_edit_to_assignment'] = 'PASS'
        report['generation_advanced'] = [assignment['generation'], newer['generation']]
    finally:
        restore = {key: original.get(key) or '' for key in changed}
        client.call('/admin/events/' + str(original['id']) + '/edit', 302, form=restore, csrf=client.csrf())
    client.call('/admin/devices/' + binding['device_id'] + '/revoke', body={}, csrf=client.csrf())
    client.call(assignment_path, 401, secret=secret)
    report.update(api_journey='PASS', downloaded_files=downloaded,
                  receipt_scope='synthetic API input only; no native readiness claimed')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', required=True, type=Path)
    parser.add_argument('--probe-only', action='store_true')
    parser.add_argument('--report', required=True, type=Path)
    args = parser.parse_args()
    client, report = probe(args.root)
    if not args.probe_only:
        exercise(client, report)
    report['http_statuses'] = dict(client.statuses)
    args.report.write_bytes(encoded(report))
    print(json.dumps(report))


if __name__ == '__main__':
    main()
