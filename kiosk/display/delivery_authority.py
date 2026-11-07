"""Confirmed native anchor, durable authority/time and private admission facts."""
import time
from pathlib import Path
from urllib.parse import urlsplit

from kiosk.delivery.protocol import decode, encode, fields, digest, text, sha
from kiosk.publication.exporter import PackageError, _plain_path
from kiosk.publication.store import _atomic_write
from .native_crypto import b64, rsa_parameters, verify_signature, protect, boot_clock


def positive(value, *, zero=False):
    if type(value) is not int or not (0 if zero else 1) <= value < 2**63:
        raise PackageError('invalid_counter')
    return value


def origin(value):
    try:
        parsed = urlsplit(value)
        if (parsed.scheme != 'https' or not parsed.hostname or parsed.port is None or
                parsed.username is not None or parsed.password is not None or parsed.path or parsed.query or
                parsed.fragment or parsed.netloc != value[len('https://'):] or
                any(c.isspace() or c in '%\\' or ord(c) > 127 for c in value)):
            raise ValueError()
        return parsed.hostname, parsed.port
    except (ValueError, TypeError):
        raise PackageError('invalid_origin') from None


def bootstrap(value, now):
    fields(value, 'version bootstrap_id group_id server_id origin tls_ca_pem group_key_id group_spki_base64 issued_at expires_at')
    if type(value['version']) is not int or value['version'] != 1:
        raise PackageError('invalid_bootstrap')
    for key in ('bootstrap_id', 'group_id', 'server_id'):
        text(value[key])
    origin(value['origin'])
    positive(value['issued_at'], zero=True)
    positive(value['expires_at'])
    if not value['issued_at'] <= now < value['expires_at']:
        raise PackageError('bootstrap_expired_or_future')
    if not isinstance(value['tls_ca_pem'], str) or len(value['tls_ca_pem']) > 16384:
        raise PackageError('invalid_bootstrap')
    public_key = b64(value['group_spki_base64'], 1024)
    rsa_parameters(public_key)
    if digest(value['group_key_id']) != sha(public_key):
        raise PackageError('group_key_mismatch')
    return value


class PrivateState:
    """DPAPI integrity and confidentiality within the existing same-user boundary."""
    def __init__(self, root):
        self.root = Path(root)
        path = self.root / 'native.dpapi'
        self.data = decode(protect(_plain_path(self.root, path.name).read_bytes(), decrypt=True)) if path.exists() else {}

    def save(self):
        payload = encode(self.data)
        if len(payload) > 2 * 1024 * 1024:
            raise PackageError('native_state_capacity')
        _atomic_write(self.root / 'native.dpapi', protect(payload))

    def now(self):
        boot, tick = boot_clock()
        now = int(time.time())
        clock = self.data.get('clock')
        if not clock or clock['boot'] != boot:
            raise PackageError('time_confirmation_required')
        elapsed = (tick - clock['tick']) // 1000
        if elapsed < 0 or now < clock['utc'] + elapsed - 2 or now < self.data.get('highest_time', 0):
            raise PackageError('uncertain_time')
        return max(now, clock['utc'] + elapsed)

    def confirm_time(self, confirmed_utc):
        now = int(time.time())
        if type(confirmed_utc) is not int or abs(confirmed_utc - now) > 60 or confirmed_utc < self.data.get('highest_time', 0):
            raise PackageError('time_confirmation_refused')
        boot, tick = boot_clock()
        self.data['clock'] = {'boot': boot, 'tick': tick, 'utc': max(now, confirmed_utc)}
        self.save()

    def verify_trust(self, envelope, tls_pin):
        if len(encode(envelope)) > 16384:
            raise PackageError('trust_limit')
        fields(envelope, 'version key_id algorithm payload_base64 signature_base64')
        anchor = self.data['bootstrap']
        if (type(envelope['version']) is not int or envelope['version'] != 1 or
                envelope['key_id'] != anchor['group_key_id'] or
                envelope['algorithm'] != 'RSA3072-SHA256-PKCS1-v1_5'):
            raise PackageError('trust_key_refused')
        raw = b64(envelope['payload_base64'], 8192)
        verify_signature(b64(anchor['group_spki_base64'], 1024), b'Kiosk/GroupTrust/v1\0' + raw,
                         b64(envelope['signature_base64'], 384))
        payload = decode(raw)
        fields(payload, 'version group_id generation issued_at expires_at servers')
        now = self.now()
        generation = positive(payload['generation'])
        positive(payload['issued_at'], zero=True)
        positive(payload['expires_at'])
        if (type(payload['version']) is not int or payload['version'] != 1 or
                payload['group_id'] != anchor['group_id'] or
                not payload['issued_at'] <= now < payload['expires_at']):
            raise PackageError('trust_binding_or_time_refused')
        servers = payload['servers']
        if not isinstance(servers, list) or len(servers) != 1:
            raise PackageError('trust_server_refused')
        server = servers[0]
        fields(server, 'server_id origin tls_spki_sha256 roles')
        if (server['server_id'] != anchor['server_id'] or server['origin'] != anchor['origin'] or
                digest(server['tls_spki_sha256']) != tls_pin or server['roles'] != ['publisher']):
            raise PackageError('trust_server_refused')
        previous = self.data.get('trust')
        if previous and (generation < previous['generation'] or
                         generation == previous['generation'] and sha(raw) != previous['payload_sha256']):
            raise PackageError('trust_rollback_or_conflict')
        self.data.update(trust={'generation': generation, 'payload_sha256': sha(raw),
                                'payload_base64': envelope['payload_base64'], 'tls_pin': tls_pin,
                                'expires_at': payload['expires_at']}, highest_time=now)
        self.save()
        return payload

    def validate_assignment(self, assignment):
        fields(assignment, 'version group_id device_id profile generation metadata_sha256 publication')
        if (type(assignment['version']) is not int or assignment['version'] != 1 or
                assignment['group_id'] != self.data['bootstrap']['group_id'] or
                assignment['device_id'] != self.data['binding']['device_id'] or
                assignment['profile'] != self.data['binding']['profile']):
            raise PackageError('assignment_binding_refused')
        generation = positive(assignment['generation'])
        if digest(assignment['metadata_sha256']) != sha(encode(assignment['publication'])):
            raise PackageError('metadata_hash_refused')
        previous = self.data.get('assignment_highest')
        identity = sha(encode(assignment))
        if previous and (generation < previous['generation'] or
                         generation == previous['generation'] and identity != previous['sha256']):
            raise PackageError('assignment_rollback_or_conflict')
        self.data['assignment_highest'] = {'generation': generation, 'sha256': identity}
        self.save()

    def accept(self, assignment):
        """Durable exact facts precede pointer admission; no caller-issued permit."""
        now = self.now()
        credential = self.data['credential']
        if self.data.get('revoked') or now >= credential['expires_at'] or now >= self.data['trust']['expires_at']:
            raise PackageError('admission_authority_expired')
        self.validate_assignment(assignment)
        package = assignment['publication']['package_id']
        accepted = self.data.setdefault('accepted', {})
        if package not in accepted and len(accepted) >= 1024:
            raise PackageError('association_capacity')
        accepted[package] = {'group_id': assignment['group_id'], 'device_id': assignment['device_id'],
                             'request_sha256': sha(encode(self.data['binding'])), 'generation': assignment['generation'],
                             'metadata_sha256': assignment['metadata_sha256'], 'package_id': package,
                             'trust_sha256': self.data['trust']['payload_sha256'], 'accepted_at': now}
        self.save()

    def accepted(self, package):
        value = self.data.get('accepted', {}).get(package)
        if (not value or value['package_id'] != package or
                value['group_id'] != self.data['bootstrap']['group_id'] or
                value['device_id'] != self.data['binding']['device_id'] or
                value['request_sha256'] != sha(encode(self.data['binding']))):
            raise PackageError('offline_association_refused')
        return value
