"""Transactional enrollment, assignments and idempotent ready receipts."""
from contextlib import contextmanager
import hmac
from pathlib import Path
import secrets
import sqlite3
import time

from .protocol import DeliveryError, PROFILE, decode, digest, encode, fields, sha, text

ENROLLMENT_SECONDS = 600
CREDENTIAL_SECONDS = 7 * 86400
POLL_SECONDS = 5
MAX_PENDING = 128
MAX_DEVICES = 100
ADMIN_DEVICE_PAGE_SIZE = 25
MAX_RECEIPTS_PER_DEVICE = 4096


class DeliveryState:
    def __init__(self, root, clock=time.time):
        self.root = Path(root).absolute()
        self.root.mkdir(parents=True, exist_ok=True)
        self.clock = clock
        with self.connection() as db:
            db.executescript('''
                CREATE TABLE IF NOT EXISTS enrollments (
                  request_id TEXT PRIMARY KEY, binding BLOB NOT NULL,
                  device_id TEXT NOT NULL, profile TEXT NOT NULL,
                  verifier TEXT NOT NULL, code_hash TEXT NOT NULL UNIQUE,
                  device_code TEXT NOT NULL, user_code TEXT NOT NULL UNIQUE,
                  expires INTEGER NOT NULL, poll_after INTEGER NOT NULL,
                  state TEXT NOT NULL, credential_id TEXT);
                CREATE TABLE IF NOT EXISTS devices (
                  device_id TEXT PRIMARY KEY, profile TEXT NOT NULL,
                  credential_id TEXT NOT NULL UNIQUE, verifier TEXT NOT NULL UNIQUE,
                  expires INTEGER NOT NULL, revoked INTEGER NOT NULL DEFAULT 0);
                CREATE TABLE IF NOT EXISTS assignments (
                  profile TEXT PRIMARY KEY, generation INTEGER NOT NULL,
                  package_id TEXT NOT NULL, metadata_hash TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS receipts (
                  device_id TEXT NOT NULL, receipt_id TEXT NOT NULL,
                  body BLOB NOT NULL, received INTEGER NOT NULL,
                  PRIMARY KEY(device_id,receipt_id));
                CREATE TABLE IF NOT EXISTS assignment_history (
                  profile TEXT NOT NULL,generation INTEGER NOT NULL,
                  package_id TEXT NOT NULL,metadata_hash TEXT NOT NULL,
                  PRIMARY KEY(profile,generation));
                CREATE TABLE IF NOT EXISTS assignment_cohorts (
                  profile TEXT NOT NULL,generation INTEGER NOT NULL,
                  revision TEXT NOT NULL,created INTEGER NOT NULL,
                  PRIMARY KEY(profile,generation));
                CREATE TABLE IF NOT EXISTS assignment_targets (
                  profile TEXT NOT NULL,generation INTEGER NOT NULL,
                  device_id TEXT NOT NULL,
                  PRIMARY KEY(profile,generation,device_id));
                CREATE TABLE IF NOT EXISTS operator_publications (
                  operation_id TEXT PRIMARY KEY,profile TEXT NOT NULL,
                  generation INTEGER NOT NULL);
            ''')

    @contextmanager
    def connection(self):
        db = sqlite3.connect(self.root / 'delivery.sqlite', timeout=5)
        db.row_factory = sqlite3.Row
        try:
            db.execute('PRAGMA synchronous=FULL')
            db.execute('BEGIN IMMEDIATE')
            yield db
            db.commit()
        except BaseException:
            db.rollback()
            raise
        finally:
            db.close()

    def configuration(self):
        config = decode((self.root / 'public.json').read_bytes())
        fields(config, 'version group_id server_id origin bootstrap trust')
        if type(config['version']) is not int or config['version'] != 1:
            raise DeliveryError('configuration_unavailable', 503)
        return config

    def begin(self, body):
        fields(body, 'version request_id device_id group_id profile origin nonce secret_verifier')
        config = self.configuration()
        if type(body['version']) is not int or body['version'] != 1:
            raise DeliveryError('unsupported_version', 409)
        for key in ('request_id', 'device_id', 'group_id', 'nonce'):
            text(body[key])
        digest(body['secret_verifier'])
        if body['group_id'] != config['group_id'] or body['origin'] != config['origin']:
            raise DeliveryError('binding_refused', 403)
        if body['profile'] != PROFILE:
            raise DeliveryError('unsupported_profile', 409)
        now = int(self.clock())
        binding = encode(body)
        with self.connection() as db:
            old = db.execute('SELECT * FROM enrollments WHERE request_id=?', (body['request_id'],)).fetchone()
            if old:
                if bytes(old['binding']) != binding:
                    raise DeliveryError('request_conflict', 409)
                if old['expires'] <= now:
                    raise DeliveryError('enrollment_expired', 410)
                return self._pending(old, now)
            # Expired codes confer no authority and can be removed without touching devices.
            db.execute('DELETE FROM enrollments WHERE expires<=?', (now,))
            count = db.execute('SELECT count(*) FROM enrollments').fetchone()[0]
            if count >= MAX_PENDING:
                raise DeliveryError('enrollment_capacity', 429)
            code = secrets.token_hex(32)
            alphabet = 'ABCDEFGHJKLMNPQRSTUVWXYZ23456789'
            user_code = ''.join(secrets.choice(alphabet) for _ in range(8))
            db.execute('INSERT INTO enrollments VALUES (?,?,?,?,?,?,?,?,?,?,?,?)', (
                body['request_id'], binding, body['device_id'], body['profile'], body['secret_verifier'],
                sha(code.encode('ascii')), code, user_code, now + ENROLLMENT_SECONDS, now,
                'pending', None,
            ))
            row = db.execute('SELECT * FROM enrollments WHERE request_id=?', (body['request_id'],)).fetchone()
            return self._pending(row, now)

    @staticmethod
    def _pending(row, now):
        return {'version': 1, 'request_id': row['request_id'], 'device_code': row['device_code'],
                'user_code': row['user_code'], 'expires_in': row['expires'] - now, 'interval': POLL_SECONDS}

    def poll(self, body):
        fields(body, 'device_code')
        code = digest(body['device_code'])
        now = int(self.clock())
        with self.connection() as db:
            row = db.execute('SELECT * FROM enrollments WHERE code_hash=?', (sha(code.encode('ascii')),)).fetchone()
            if row is None or row['expires'] <= now:
                raise DeliveryError('enrollment_expired', 410)
            if row['state'] == 'denied':
                raise DeliveryError('enrollment_denied', 403)
            if row['state'] == 'approved':
                device = db.execute('SELECT * FROM devices WHERE credential_id=?', (row['credential_id'],)).fetchone()
                if device is None or device['revoked'] or device['expires'] <= now:
                    raise DeliveryError('credential_revoked', 403)
                return self._device(device)
            if row['poll_after'] > now:
                raise DeliveryError('slow_down', 429)
            db.execute('UPDATE enrollments SET poll_after=? WHERE request_id=?', (now + POLL_SECONDS, row['request_id']))
            # Return pending normally so the polling timestamp transaction commits.
            return {'version': 1, 'state': 'pending', 'interval': POLL_SECONDS}

    def pending(self):
        with self.connection() as db:
            return [{'request_id': row['request_id'], 'binding': decode(bytes(row['binding'])),
                     'user_code': row['user_code'], 'expires_at': row['expires'], 'state': row['state']}
                    for row in db.execute('SELECT * FROM enrollments WHERE expires>? ORDER BY request_id', (int(self.clock()),))]

    def pair_review(self, user_code):
        """Return one enrollment's comparison facts for the trusted pairing page.

        Reached only by an authenticated administrator who already holds the
        code (QR or manual entry). Returns only the device/group/server/profile/
        origin facts plus the request id and binding hash needed to drive the
        existing guarded decision. The user_code itself, device_code, verifier,
        credential_id and secret_verifier never leave this boundary. Unknown and
        expired codes are distinguished only for the administrator's UX, and the
        caller rate-limits lookups.
        """
        if (not isinstance(user_code, str) or len(user_code) != 8
                or any(char not in 'ABCDEFGHJKLMNPQRSTUVWXYZ23456789' for char in user_code)):
            raise DeliveryError('invalid_user_code', 400)
        now = int(self.clock())
        with self.connection() as db:
            row = db.execute('SELECT * FROM enrollments WHERE user_code=?', (user_code,)).fetchone()
            if row is None:
                raise DeliveryError('unknown_code', 404)
            if row['expires'] <= now:
                raise DeliveryError('enrollment_expired', 410)
            binding = decode(bytes(row['binding']))
            config = self.configuration()
            return {'request_id': row['request_id'],
                    'binding_sha256': sha(bytes(row['binding'])),
                    'device_id': binding['device_id'], 'group_id': binding['group_id'],
                    'profile': binding['profile'], 'nonce': binding['nonce'],
                    'server_id': config['server_id'], 'origin': config['origin'],
                    'expires_at': row['expires'], 'state': row['state']}

    def approve(self, request_id, body):
        fields(body, 'user_code binding_sha256 decision')
        text(request_id)
        digest(body['binding_sha256'])
        if body['decision'] not in ('approve', 'deny'):
            raise DeliveryError('invalid_decision')
        if (not isinstance(body['user_code'], str) or len(body['user_code']) != 8
                or any(char not in 'ABCDEFGHJKLMNPQRSTUVWXYZ23456789' for char in body['user_code'])):
            raise DeliveryError('invalid_user_code')
        now = int(self.clock())
        with self.connection() as db:
            row = db.execute('SELECT * FROM enrollments WHERE request_id=?', (request_id,)).fetchone()
            if row is None or row['expires'] <= now:
                raise DeliveryError('enrollment_expired', 410)
            if not hmac.compare_digest(str(body['user_code']), row['user_code']) or sha(bytes(row['binding'])) != body['binding_sha256']:
                raise DeliveryError('binding_refused', 403)
            binding = decode(bytes(row['binding']))
            config = self.configuration()
            if (binding['group_id'] != config['group_id'] or binding['origin'] != config['origin']
                    or binding['profile'] != PROFILE):
                raise DeliveryError('binding_refused', 403)
            if row['state'] == 'approved':
                if body['decision'] != 'approve':
                    raise DeliveryError('decision_conflict', 409)
                device = db.execute('SELECT * FROM devices WHERE device_id=?', (row['device_id'],)).fetchone()
                if (device is None or device['credential_id'] != row['credential_id']
                        or device['revoked'] or device['expires'] <= now):
                    raise DeliveryError('approval_no_longer_active', 409)
                return {'version': 1, 'state': 'approved', 'credential_id': row['credential_id']}
            if row['state'] == 'denied' and body['decision'] == 'deny':
                return {'version': 1, 'state': 'denied'}
            if row['state'] != 'pending':
                raise DeliveryError('decision_conflict', 409)
            if body['decision'] == 'deny':
                db.execute("UPDATE enrollments SET state='denied' WHERE request_id=?", (request_id,))
                return {'version': 1, 'state': 'denied'}
            credential_id = secrets.token_hex(16)
            existing = db.execute('SELECT 1 FROM devices WHERE device_id=?', (row['device_id'],)).fetchone()
            # Counting includes revoked/expired rows; reapproval replaces an existing identity.
            if not existing and db.execute('SELECT count(*) FROM devices').fetchone()[0] >= MAX_DEVICES:
                raise DeliveryError('device_capacity', 429)
            try:
                db.execute('''INSERT INTO devices VALUES (?,?,?,?,?,0)
                    ON CONFLICT(device_id) DO UPDATE SET profile=excluded.profile,
                    credential_id=excluded.credential_id,verifier=excluded.verifier,
                    expires=excluded.expires,revoked=0''',
                    (row['device_id'], row['profile'], credential_id, row['verifier'], now + CREDENTIAL_SECONDS))
            except sqlite3.IntegrityError:
                raise DeliveryError('credential_conflict', 409) from None
            db.execute("UPDATE enrollments SET state='approved',credential_id=? WHERE request_id=?", (credential_id, request_id))
            return {'version': 1, 'state': 'approved', 'credential_id': credential_id}

    @staticmethod
    def _device(row):
        return {'version': 1, 'state': 'approved', 'device_id': row['device_id'],
                'profile': row['profile'], 'credential_id': row['credential_id'],
                'expires_at': row['expires'], 'scopes': ['read_assignment', 'submit_receipt']}

    def authenticate(self, secret):
        digest(secret)
        with self.connection() as db:
            row = db.execute('SELECT * FROM devices WHERE verifier=?', (sha(bytes.fromhex(secret)),)).fetchone()
            if row is None or row['revoked'] or row['expires'] <= int(self.clock()):
                raise DeliveryError('invalid_credential', 401)
            return dict(row)

    @staticmethod
    def device_review_hash(row):
        # Includes the private credential identity so a stale form cannot revoke a replacement.
        return sha(encode({key: row[key] for key in ('device_id', 'profile', 'credential_id', 'expires')}))

    def admin_devices(self, page=1):
        """Bounded public view; no credential, verifier or human/device code leaves here.

        The registered list is paged so the fixed 100-identity bound stays readable;
        the model always reports the honest total and page range.
        """
        now = int(self.clock())
        config = self.configuration()
        page = max(1, int(page))
        with self.connection() as db:
            requests = []
            for row in db.execute('SELECT request_id,binding,expires,state FROM enrollments WHERE expires>? ORDER BY request_id LIMIT 128', (now,)):
                binding = decode(bytes(row['binding']))
                binding.pop('secret_verifier')
                requests.append({'request_id': row['request_id'], 'binding': binding,
                                 'binding_sha256': sha(bytes(row['binding'])), 'expires': row['expires'],
                                 'state': row['state']})
            total = db.execute('SELECT count(*) FROM devices').fetchone()[0]
            pages = max(1, (total + ADMIN_DEVICE_PAGE_SIZE - 1) // ADMIN_DEVICE_PAGE_SIZE)
            page = min(page, pages)
            offset = (page - 1) * ADMIN_DEVICE_PAGE_SIZE
            devices = []
            for row in db.execute('''SELECT device_id,profile,credential_id,expires,revoked FROM devices
                ORDER BY device_id LIMIT ? OFFSET ?''', (ADMIN_DEVICE_PAGE_SIZE, offset)):
                devices.append({'device_id': row['device_id'], 'profile': row['profile'], 'expires': row['expires'],
                                'revoked': bool(row['revoked']), 'expired': row['expires'] <= now,
                                'review_hash': self.device_review_hash(row)})
        return {'requests': requests, 'devices': devices, 'group_id': config['group_id'],
                'server_id': config['server_id'], 'origin': config['origin'], 'now': now,
                'device_total': total, 'device_page': page, 'device_pages': pages,
                'device_page_size': ADMIN_DEVICE_PAGE_SIZE, 'device_capacity': MAX_DEVICES,
                'device_first': offset + 1 if total else 0, 'device_last': offset + len(devices)}

    def revoke(self, device_id, review_hash=None):
        text(device_id)
        with self.connection() as db:
            if review_hash is not None:
                digest(review_hash)
                row = db.execute('SELECT * FROM devices WHERE device_id=?', (device_id,)).fetchone()
                if row is None:
                    raise DeliveryError('device_not_found', 404)
                if not hmac.compare_digest(self.device_review_hash(row), review_hash):
                    raise DeliveryError('device_changed', 409)
            if db.execute('UPDATE devices SET revoked=1 WHERE device_id=?', (device_id,)).rowcount != 1:
                raise DeliveryError('device_not_found', 404)
        return {'version': 1, 'state': 'revoked'}

    def assign(self, profile, package_id, metadata_hash):
        digest(package_id)
        digest(metadata_hash)
        if profile != PROFILE:
            raise DeliveryError('unsupported_profile', 409)
        with self.connection() as db:
            payload = (self.root / 'publications' / package_id / 'delivery.json').read_bytes()
            if sha(payload) != metadata_hash:
                raise DeliveryError('publication_integrity', 503)
            metadata = decode(payload)
            if metadata['package_id'] != package_id or metadata['resource_profile'] != profile:
                raise DeliveryError('publication_identity_conflict', 409)
            return self._assign(db, profile, package_id, metadata_hash, metadata['revision'])

    def _assign(self, db, profile, package_id, metadata_hash, revision):
        """The caller holds the publication lease; targets and generation commit together."""
        old = db.execute('SELECT * FROM assignments WHERE profile=?', (profile,)).fetchone()
        if old and old['package_id'] == package_id and old['metadata_hash'] == metadata_hash:
            # A retry must neither refreeze membership nor backfill unknown legacy history.
            return old['generation']
        generation = old['generation'] + 1 if old else 1
        db.execute('INSERT INTO assignments VALUES (?,?,?,?) ON CONFLICT(profile) DO UPDATE SET generation=excluded.generation,package_id=excluded.package_id,metadata_hash=excluded.metadata_hash',
                   (profile, generation, package_id, metadata_hash))
        db.execute('INSERT INTO assignment_history VALUES (?,?,?,?)', (profile, generation, package_id, metadata_hash))
        now = int(self.clock())
        db.execute('INSERT INTO assignment_cohorts VALUES (?,?,?,?)', (profile, generation, revision, now))
        db.execute('''INSERT INTO assignment_targets
            SELECT ?,?,device_id FROM devices WHERE profile=? AND revoked=0 AND expires>?''',
                   (profile, generation, profile, now))
        return generation

    def assignment(self, device, renderer, resource_profile):
        with self.connection() as db:
            row = db.execute('SELECT * FROM assignments WHERE profile=?', (device['profile'],)).fetchone()
        if row is None:
            raise DeliveryError('no_assignment', 404)
        payload = (self.root / 'publications' / row['package_id'] / 'delivery.json').read_bytes()
        if sha(payload) != row['metadata_hash']:
            raise DeliveryError('publication_integrity', 503)
        metadata = decode(payload)
        if metadata['renderer']['build_id'] != renderer or metadata['resource_profile'] != resource_profile:
            raise DeliveryError('requires_update', 409)
        config = self.configuration()
        return {'version': 1, 'group_id': config['group_id'], 'device_id': device['device_id'],
                'profile': device['profile'], 'generation': row['generation'],
                'metadata_sha256': row['metadata_hash'], 'publication': metadata}

    def receipt(self, device, body):
        fields(body, 'version receipt_id group_id device_id generation package_id mode session result')
        if type(body['version']) is not int or body['version'] != 1 or type(body['generation']) is not int or body['generation'] <= 0:
            raise DeliveryError('invalid_receipt')
        for key in ('receipt_id', 'session'):
            text(body[key])
        digest(body['package_id'])
        if body['device_id'] != device['device_id'] or body['group_id'] != self.configuration()['group_id']:
            raise DeliveryError('binding_refused', 403)
        if body['mode'] not in ('kiosk', 'tv') or body['result'] != 'ready':
            raise DeliveryError('invalid_receipt')
        payload = encode(body)
        with self.connection() as db:
            old = db.execute('SELECT body FROM receipts WHERE device_id=? AND receipt_id=?',
                             (device['device_id'], body['receipt_id'])).fetchone()
            if old:
                if bytes(old['body']) != payload:
                    raise DeliveryError('receipt_conflict', 409)
                return {'version': 1, 'receipt_id': body['receipt_id'], 'state': 'recorded'}
            # Historical queued receipts remain admissible only for an actual retained publication.
            record = self.root / 'publications' / body['package_id'] / 'delivery.json'
            if not record.is_file():
                raise DeliveryError('unknown_publication', 409)
            assignment = db.execute('SELECT package_id FROM assignment_history WHERE profile=? AND generation=?',
                                    (device['profile'], body['generation'])).fetchone()
            if assignment is None or body['package_id'] != assignment['package_id']:
                raise DeliveryError('unknown_assignment', 409)
            count = db.execute('SELECT count(*) FROM receipts WHERE device_id=?', (device['device_id'],)).fetchone()[0]
            if count >= MAX_RECEIPTS_PER_DEVICE:
                raise DeliveryError('receipt_capacity', 429)
            db.execute('INSERT INTO receipts VALUES (?,?,?,?)', (device['device_id'], body['receipt_id'], payload, int(self.clock())))
        return {'version': 1, 'receipt_id': body['receipt_id'], 'state': 'recorded'}
