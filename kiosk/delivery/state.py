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

    def approve(self, request_id, body):
        fields(body, 'user_code binding_sha256 decision')
        text(request_id)
        digest(body['binding_sha256'])
        if body['decision'] not in ('approve', 'deny'):
            raise DeliveryError('invalid_decision')
        now = int(self.clock())
        with self.connection() as db:
            row = db.execute('SELECT * FROM enrollments WHERE request_id=?', (request_id,)).fetchone()
            if row is None or row['expires'] <= now:
                raise DeliveryError('enrollment_expired', 410)
            if not hmac.compare_digest(str(body['user_code']), row['user_code']) or sha(bytes(row['binding'])) != body['binding_sha256']:
                raise DeliveryError('binding_refused', 403)
            if row['state'] == 'approved':
                if body['decision'] != 'approve':
                    raise DeliveryError('decision_conflict', 409)
                return {'version': 1, 'state': 'approved', 'credential_id': row['credential_id']}
            if row['state'] != 'pending':
                raise DeliveryError('decision_conflict', 409)
            if body['decision'] == 'deny':
                db.execute("UPDATE enrollments SET state='denied' WHERE request_id=?", (request_id,))
                return {'version': 1, 'state': 'denied'}
            credential_id = secrets.token_hex(16)
            existing = db.execute('SELECT 1 FROM devices WHERE device_id=?', (row['device_id'],)).fetchone()
            if not existing and db.execute('SELECT count(*) FROM devices').fetchone()[0] >= 16:
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

    def revoke(self, device_id):
        text(device_id)
        with self.connection() as db:
            if db.execute('UPDATE devices SET revoked=1 WHERE device_id=?', (device_id,)).rowcount != 1:
                raise DeliveryError('device_not_found', 404)
        return {'version': 1, 'state': 'revoked'}

    def assign(self, profile, package_id, metadata_hash):
        digest(package_id)
        digest(metadata_hash)
        if profile != PROFILE:
            raise DeliveryError('unsupported_profile', 409)
        with self.connection() as db:
            old = db.execute('SELECT * FROM assignments WHERE profile=?', (profile,)).fetchone()
            if old and old['package_id'] == package_id and old['metadata_hash'] == metadata_hash:
                return old['generation']
            generation = old['generation'] + 1 if old else 1
            db.execute('INSERT INTO assignments VALUES (?,?,?,?) ON CONFLICT(profile) DO UPDATE SET generation=excluded.generation,package_id=excluded.package_id,metadata_hash=excluded.metadata_hash',
                       (profile, generation, package_id, metadata_hash))
            db.execute('INSERT INTO assignment_history VALUES (?,?,?,?)', (profile, generation, package_id, metadata_hash))
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
