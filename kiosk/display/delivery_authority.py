"""Confirmed native anchor, durable authority/time and private admission facts."""
import time
import ssl
from pathlib import Path
from urllib.parse import urlsplit

from kiosk.delivery.protocol import decode, encode, fields, digest, text, sha
from kiosk.publication.exporter import PackageError, _plain_path
from kiosk.publication.store import _atomic_write
from .native_crypto import b64, rsa_parameters, verify_signature, protect, boot_clock, sequence


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
    if value['tls_ca_pem'].count('-----BEGIN CERTIFICATE-----') != 1:
        raise PackageError('bootstrap_requires_one_root')
    try:
        cert = sequence(ssl.PEM_cert_to_DER_cert(value['tls_ca_pem']))
        tbs = sequence(cert[0][2])
        offset = 1 if tbs[0][0] == 0xa0 else 0
        if tbs[offset + 2][2] != tbs[offset + 4][2]:
            raise ValueError()
    except (ValueError, IndexError):
        raise PackageError('bootstrap_requires_one_root') from None
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

    def verify_trust(self, envelope, tls_pin, issuer_pin=None):
        if len(encode(envelope)) > 16384:
            raise PackageError('trust_limit')
        fields(envelope, 'version key_id algorithm payload_base64 signature_base64')
        anchor = self.data['bootstrap']
        if (type(envelope['version']) is not int or envelope['version'] not in (1, 2) or
                envelope['key_id'] != anchor['group_key_id'] or
                envelope['algorithm'] != 'RSA3072-SHA256-PKCS1-v1_5'):
            raise PackageError('trust_key_refused')
        raw = b64(envelope['payload_base64'], 8192)
        verify_signature(b64(anchor['group_spki_base64'], 1024), ('Kiosk/GroupTrust/v%d\0' % envelope['version']).encode('ascii') + raw,
                         b64(envelope['signature_base64'], 384))
        payload = decode(raw)
        fields(payload, 'version group_id generation issued_at expires_at servers')
        now = self.now()
        generation = positive(payload['generation'])
        positive(payload['issued_at'], zero=True)
        positive(payload['expires_at'])
        if (type(payload['version']) is not int or payload['version'] != envelope['version'] or
                payload['group_id'] != anchor['group_id'] or
                not payload['issued_at'] <= now < payload['expires_at']):
            raise PackageError('trust_binding_or_time_refused')
        servers = payload['servers']
        if not isinstance(servers, list) or len(servers) != 1:
            raise PackageError('trust_server_refused')
        server = servers[0]
        # Two additive pin schemes:
        #  * legacy ``tls_spki_sha256`` pins the leaf SPKI (frozen device-delivery-v1);
        #  * ``tls_issuer_spki_sha256`` pins the intermediate (issuer) SPKI, which is
        #    stable across leaf rotations, so the client accepts any legitimate new
        #    leaf that chains to the pinned issuer without re-pinning or re-enrollment.
        if 'tls_issuer_spki_sha256' in server:
            if envelope['version'] != 2:
                raise PackageError('trust_format_refused')
            if set(server) != {'server_id', 'origin', 'tls_issuer_spki_sha256', 'roles'}:
                raise PackageError('trust_server_refused')
            if (server['server_id'] != anchor['server_id'] or server['origin'] != anchor['origin'] or
                    digest(server['tls_issuer_spki_sha256']) != issuer_pin or server['roles'] != ['publisher']):
                raise PackageError('trust_server_refused')
            pin, pin_kind = issuer_pin, 'issuer'
        else:
            if envelope['version'] != 1:
                raise PackageError('trust_format_refused')
            fields(server, 'server_id origin tls_spki_sha256 roles')
            if (server['server_id'] != anchor['server_id'] or server['origin'] != anchor['origin'] or
                    digest(server['tls_spki_sha256']) != tls_pin or server['roles'] != ['publisher']):
                raise PackageError('trust_server_refused')
            pin, pin_kind = tls_pin, 'leaf'
        previous = self.data.get('trust')
        if previous and (generation < previous['generation'] or
                         generation == previous['generation'] and sha(raw) != previous['payload_sha256']):
            raise PackageError('trust_rollback_or_conflict')
        self.data.update(trust={'generation': generation, 'payload_sha256': sha(raw),
                                'payload_base64': envelope['payload_base64'], 'tls_pin': pin,
                                'pin_kind': pin_kind, 'expires_at': payload['expires_at']},
                         highest_time=now)
        self.save()
        return payload

    def validate_assignment(self, assignment):
        signed = assignment.get('version') == 3
        publisher = self.data.get('publisher_anchor')
        if signed:
            fields(assignment, 'version group_id device_id profile generation metadata_sha256 publication display publisher')
            if not publisher:
                raise PackageError('publisher_setup_required')
            from kiosk.publication.authority import assignment as verify_approval
            try:
                verify_approval(assignment['publisher'], assignment,
                                b64(publisher['root_spki_base64'],1024), self.data['bootstrap']['origin'],
                                self.now(), policy_floor=publisher.get('policy_floor',0),
                                known_heads=publisher.get('heads',[]))
            except (ValueError,KeyError,TypeError):
                raise PackageError('publisher_approval_refused') from None
            assignment = {k:v for k,v in assignment.items() if k!='publisher'}
            assignment['version']=2
        elif publisher:
            raise PackageError('publisher_unsigned_assignment_refused')
        extended = assignment.get('version') == 2
        fields(assignment, 'version group_id device_id profile generation metadata_sha256 publication' + (' display' if extended else ''))
        if extended:
            display = assignment['display']
            fields(display, 'version profile_id revision mode')
            if (type(display['version']) is not int or display['version'] != 1 or
                    type(display['revision']) is not int or display['revision'] <= 0 or
                    display['mode'] not in ('local', 'tv', 'kiosk')):
                raise PackageError('unsupported_display_profile')
            text(display['profile_id'], 64)
        if (type(assignment['version']) is not int or assignment['version'] not in (1, 2) or
                assignment['group_id'] != self.data['bootstrap']['group_id'] or
                assignment['device_id'] != self.data['binding']['device_id'] or
                assignment['profile'] != self.data['binding']['profile']):
            raise PackageError('assignment_binding_refused')
        generation = positive(assignment['generation'])
        if digest(assignment['metadata_sha256']) != sha(encode(assignment['publication'])):
            raise PackageError('metadata_hash_refused')
        previous = self.data.get('assignment_highest')
        normalized = dict(assignment)
        if extended and assignment['display'] == {'version': 1, 'profile_id': 'events-default', 'revision': 1, 'mode': 'local'}:
            normalized.pop('display')
            normalized['version'] = 1
        identity = sha(encode(normalized))
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
        if assignment['version']==3:
            from kiosk.publication.authority import assignment as verify_approval
            publisher=self.data['publisher_anchor']
            plan,policy=verify_approval(assignment['publisher'],assignment,
                b64(publisher['root_spki_base64'],1024),self.data['bootstrap']['origin'],now,
                policy_floor=publisher.get('policy_floor',0),known_heads=publisher.get('heads',[]))
            publisher['heads']=[plan['id']]
            publisher['policy_floor']=policy['version']
        package = assignment['publication']['package_id']
        accepted = self.data.setdefault('accepted', {})
        if package not in accepted and len(accepted) >= 1024:
            raise PackageError('association_capacity')
        accepted[package] = {'group_id': assignment['group_id'], 'device_id': assignment['device_id'],
                             'request_sha256': sha(encode(self.data['binding'])), 'generation': assignment['generation'],
                             'metadata_sha256': assignment['metadata_sha256'], 'package_id': package,
                             'trust_sha256': self.data['trust']['payload_sha256'], 'accepted_at': now,
                             'display': assignment.get('display', {'mode': 'local'})}
        self.save()

    def page_context(self):
        """Local v4 expectations; never inferred from a server response."""
        anchor = self.data.get('bootstrap')
        binding = self.data.get('binding')
        publisher = self.data.get('publisher_anchor')
        if not anchor or not binding or not publisher:
            raise PackageError('page_admission_setup_required')
        return {'group_id': anchor['group_id'], 'device_id': binding['device_id'],
                'profile': binding['profile'], 'destination': 'windows-pages-v1',
                'origin': anchor['origin'], 'root_spki': b64(publisher['root_spki_base64'], 1024),
                'policy_floor': publisher.get('policy_floor', 0),
                'heads': tuple(publisher.get('heads', []))}

    def validate_page_assignment(self, assignment):
        """Check a signed v4 page assignment without committing local facts."""
        from kiosk.publication import authority as page_authority
        fields(assignment, 'version group_id device_id profile generation revision_sha256 '
                           'destination projection metadata_sha256 metadata display publisher')
        if type(assignment['version']) is not int or assignment['version'] != 4:
            raise PackageError('unsupported_assignment_version')
        context = self.page_context()
        if (assignment['group_id'] != context['group_id']
                or assignment['device_id'] != context['device_id']
                or assignment['profile'] != context['profile']
                or assignment['destination'] != context['destination']):
            raise PackageError('assignment_binding_refused')
        positive(assignment['generation'])
        digest(assignment['revision_sha256'])
        digest(assignment['metadata_sha256'])
        if assignment['publisher'] != assignment.get('publisher'):
            raise PackageError('publisher_approval_refused')
        try:
            page_authority.page_assignment(
                assignment['publisher'], assignment, context['root_spki'],
                context['origin'], self.now(), policy_floor=context['policy_floor'],
                known_heads=context['heads'])
        except (ValueError, KeyError, TypeError):
            raise PackageError('publisher_approval_refused') from None
        identity = sha(encode({key: value for key, value in assignment.items()
                               if key != 'publisher'}))
        previous = self.data.get('assignment_highest')
        if previous and (assignment['generation'] < previous['generation'] or
                         assignment['generation'] == previous['generation'] and
                         identity != previous['sha256']):
            raise PackageError('assignment_rollback_or_conflict')
        return identity

    def accept_page(self, assignment):
        """Persist one verified v4 association and advance replay floors atomically."""
        from kiosk.publication import authority as page_authority
        now = self.now()
        credential = self.data['credential']
        if (self.data.get('revoked') or now >= credential['expires_at']
                or now >= self.data['trust']['expires_at']):
            raise PackageError('admission_authority_expired')
        identity = self.validate_page_assignment(assignment)
        context = self.page_context()
        try:
            plan, _target, policy = page_authority.page_assignment(
                assignment['publisher'], assignment, context['root_spki'],
                context['origin'], now, policy_floor=context['policy_floor'],
                known_heads=context['heads'])
        except (ValueError, KeyError, TypeError):
            raise PackageError('publisher_approval_refused') from None
        publisher = self.data['publisher_anchor']
        package = assignment['metadata']['publication']['package_id']
        accepted = self.data.setdefault('accepted', {})
        if package not in accepted and len(accepted) >= 1024:
            raise PackageError('association_capacity')
        self.data['assignment_highest'] = {'generation': assignment['generation'],
                                           'sha256': identity}
        publisher['heads'] = [plan['id']]
        publisher['policy_floor'] = policy['version']
        accepted[package] = {'group_id': assignment['group_id'],
                             'device_id': assignment['device_id'],
                             'request_sha256': sha(encode(self.data['binding'])),
                             'generation': assignment['generation'],
                             'metadata_sha256': assignment['metadata_sha256'],
                             'package_id': package,
                             'trust_sha256': self.data['trust']['payload_sha256'],
                             'accepted_at': now, 'kind': 'pages',
                             'projection': assignment['projection'],
                             'destination': assignment['destination'],
                             'revision_sha256': assignment['revision_sha256'],
                             'display': assignment['display']}
        self.save()

    def confirm_publisher_root(self, spki_base64, independently_verified_sha256):
        """Explicit local setup only; never populated from server/login responses."""
        spki=b64(spki_base64,1024)
        rsa_parameters(spki)
        if sha(spki)!=digest(independently_verified_sha256):
            raise PackageError('publisher_root_confirmation_refused')
        prior=self.data.get('publisher_anchor')
        if prior and prior['root_spki_base64']!=spki_base64:
            raise PackageError('publisher_root_replacement_requires_recovery')
        if not prior:
            self.data['publisher_anchor']={'root_spki_base64':spki_base64,'policy_floor':0,'heads':[]}
            self.save()

    def accepted(self, package):
        value = self.data.get('accepted', {}).get(package)
        if (not value or value['package_id'] != package or
                value['group_id'] != self.data['bootstrap']['group_id'] or
                value['device_id'] != self.data['binding']['device_id'] or
                value['request_sha256'] != sha(encode(self.data['binding']))):
            raise PackageError('offline_association_refused')
        return value
