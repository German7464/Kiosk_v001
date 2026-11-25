"""Transactional enrollment, assignments, idempotent ready receipts and credential renewal."""
from contextlib import contextmanager
import base64
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
# Automatic renewal without re-enrollment: a still-valid credential may be extended
# by the server when the device proves possession of its current bearer secret, is
# not revoked, and the signed group trust is still valid. The secret and credential
# identity stay stable; only the expiry advances, so lost responses and retries are
# idempotent. Renewal is proactive: the client renews while the credential is still
# valid (before expiry), and an expired credential is NOT silently extended — it
# requires the explicit supported recovery path (fresh enrollment + admin approval).
RENEWAL_MARGIN_SECONDS = 86400
TIME_FLOOR_KEY = "highest_utc"


from .profiles import ProfileState, SCHEMA


class DeliveryState(ProfileState):
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
                CREATE TABLE IF NOT EXISTS meta (
                  key TEXT PRIMARY KEY, value INTEGER NOT NULL);
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
                CREATE TABLE IF NOT EXISTS device_contacts (
                  device_id TEXT PRIMARY KEY, last_contact INTEGER NOT NULL);
                CREATE TABLE IF NOT EXISTS device_progress (
                  device_id TEXT PRIMARY KEY, body BLOB NOT NULL, received INTEGER NOT NULL);
                CREATE TABLE IF NOT EXISTS publisher_proofs (
                  profile TEXT NOT NULL, generation INTEGER NOT NULL, device_id TEXT NOT NULL,
                  body BLOB NOT NULL,
                  PRIMARY KEY(profile, generation, device_id));
                CREATE TABLE IF NOT EXISTS acceptance_receipts (
                  profile TEXT NOT NULL, generation INTEGER NOT NULL, plan_id TEXT NOT NULL,
                  body BLOB NOT NULL, acceptance_key TEXT NOT NULL, created INTEGER NOT NULL,
                  PRIMARY KEY(profile, generation));
                CREATE TABLE IF NOT EXISTS page_plan_commits (
                  plan_id TEXT PRIMARY KEY, generation INTEGER NOT NULL UNIQUE,
                  revision_sha256 TEXT NOT NULL, targets_sha256 TEXT NOT NULL,
                  created INTEGER NOT NULL);
                CREATE TABLE IF NOT EXISTS page_plan_targets (
                  plan_id TEXT NOT NULL, device_id TEXT NOT NULL, generation INTEGER NOT NULL,
                  package_id TEXT NOT NULL, metadata_hash TEXT NOT NULL,
                  PRIMARY KEY(plan_id, device_id));
                CREATE TABLE IF NOT EXISTS page_assignments (
                  device_id TEXT PRIMARY KEY, generation INTEGER NOT NULL,
                  plan_id TEXT NOT NULL, package_id TEXT NOT NULL,
                  metadata_hash TEXT NOT NULL, revision_sha256 TEXT NOT NULL,
                  destination TEXT NOT NULL, projection TEXT NOT NULL,
                  renderer TEXT NOT NULL, configuration BLOB NOT NULL, created INTEGER NOT NULL);
                CREATE TABLE IF NOT EXISTS page_assignment_history (
                  device_id TEXT NOT NULL, generation INTEGER NOT NULL,
                  plan_id TEXT NOT NULL, package_id TEXT NOT NULL,
                  metadata_hash TEXT NOT NULL, revision_sha256 TEXT NOT NULL,
                  destination TEXT NOT NULL, projection TEXT NOT NULL,
                  renderer TEXT NOT NULL, configuration BLOB NOT NULL, created INTEGER NOT NULL,
                  PRIMARY KEY(device_id, generation));
                CREATE TABLE IF NOT EXISTS page_publisher_proofs (
                  device_id TEXT NOT NULL, generation INTEGER NOT NULL, body BLOB NOT NULL,
                  PRIMARY KEY(device_id, generation));
                CREATE TABLE IF NOT EXISTS page_acceptance_receipts (
                  plan_id TEXT PRIMARY KEY, generation INTEGER NOT NULL, body BLOB NOT NULL,
                  acceptance_key TEXT NOT NULL, created INTEGER NOT NULL);
            ''')
            db.executescript(SCHEMA)

    @contextmanager
    def connection(self, *, write=True):
        db = sqlite3.connect(self.root / 'delivery.sqlite', timeout=5)
        db.row_factory = sqlite3.Row
        try:
            db.execute('PRAGMA synchronous=FULL')
            db.execute('BEGIN IMMEDIATE' if write else 'BEGIN')
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
        now = int(self.clock())
        with self.connection(write=False) as db:
            row = db.execute('SELECT * FROM devices WHERE verifier=?', (sha(bytes.fromhex(secret)),)).fetchone()
            if row is None or row['revoked'] or row['expires'] <= now:
                raise DeliveryError('invalid_credential', 401)
            contact = db.execute('SELECT last_contact FROM device_contacts WHERE device_id=?', (row['device_id'],)).fetchone()
        # Contact writes coalesce to 30 seconds; ordinary authenticated reads no
        # longer reserve the global SQLite writer for their entire read path.
        if contact is None or now - contact['last_contact'] >= 30:
            with self.connection() as db:
                db.execute('''INSERT INTO device_contacts VALUES (?,?) ON CONFLICT(device_id)
                    DO UPDATE SET last_contact=MAX(last_contact,excluded.last_contact)''', (row['device_id'], now))
        return dict(row)

    def progress_target(self, device):
        with self.connection(write=False) as db:
            page = db.execute('SELECT generation,package_id FROM page_assignments '
                              'WHERE device_id=?', (device['device_id'],)).fetchone()
            row = db.execute('SELECT * FROM assignments WHERE profile=?', (device['profile'],)).fetchone()
            configured = db.execute('SELECT * FROM publication_configs WHERE generation=? AND device_id=?', (row['generation'], device['device_id'])).fetchone() if row else None
        if page is not None:
            return {'version': 1, 'device_id': device['device_id'],
                    'group_id': self.configuration()['group_id'],
                    'generation': page['generation'], 'package_id': page['package_id'],
                    'kind': 'page'}
        if row is None:
            raise DeliveryError('no_assignment', 404)
        return {'version': 1, 'device_id': device['device_id'],
                'group_id': self.configuration()['group_id'], 'generation': row['generation'],
                'package_id': row['package_id']}

    def progress(self, device, body):
        from .progress import validate, advances
        validate(body)
        if body['device_id'] != device['device_id'] or body['group_id'] != self.configuration()['group_id']:
            raise DeliveryError('binding_refused', 403)
        payload = encode(body)
        with self.connection() as db:
            # Recheck authority in the short write transaction (revoke/re-enroll
            # may have committed since the route authenticated the request).
            owner = db.execute('SELECT * FROM devices WHERE device_id=?', (device['device_id'],)).fetchone()
            if owner is None or owner['revoked'] or owner['expires'] <= int(self.clock()) or owner['credential_id'] != device['credential_id']:
                raise DeliveryError('invalid_credential', 401)
            page = db.execute('SELECT * FROM page_assignments WHERE device_id=?',
                              (device['device_id'],)).fetchone()
            if page is not None:
                if page['generation'] != body['generation'] or page['package_id'] != body['package_id']:
                    raise DeliveryError('assignment_changed', 409)
            else:
                target = db.execute('SELECT * FROM assignments WHERE profile=?', (device['profile'],)).fetchone()
                if target is None or target['generation'] != body['generation'] or target['package_id'] != body['package_id']:
                    raise DeliveryError('assignment_changed', 409)
            old = db.execute('SELECT body FROM device_progress WHERE device_id=?', (device['device_id'],)).fetchone()
            result = 'recorded'
            if old:
                previous = decode(bytes(old['body']))
                if body['sequence'] == previous['sequence']:
                    if bytes(old['body']) != payload:
                        raise DeliveryError('progress_conflict', 409)
                    result = 'duplicate'
                elif body['sequence'] < previous['sequence']:
                    result = 'superseded'
                elif previous['generation'] == body['generation'] and not advances(previous, body):
                    raise DeliveryError('progress_conflict', 409)
            if result == 'recorded':
                db.execute('''INSERT INTO device_progress VALUES (?,?,?) ON CONFLICT(device_id)
                    DO UPDATE SET body=excluded.body,received=excluded.received''',
                           (device['device_id'], payload, int(self.clock())))
        return {'version': 1, 'sequence': body['sequence'], 'state': result}

    # -- v4 page publication --------------------------------------------------
    @staticmethod
    def _page_schema(schema):
        """Table prefix for the page tables; empty on a delivery-only connection.

        The atomic page commit attaches the delivery database to the workspace
        connection, so the delivery tables live under the ``delivery`` schema.
        Ordinary delivery reads use the main schema.
        """
        return f'{schema}.' if schema else ''

    def _page_eligible(self, db, now, schema=''):
        """Eligible non-local displays with server-managed projection/destination.

        Orientation and platform are server configuration, never request input.
        A profile without an explicit orientation keeps the landscape default.
        """
        prefix = self._page_schema(schema)
        orphan = db.execute(
            f"""SELECT 1 FROM {prefix}device_profiles s
                LEFT JOIN {prefix}devices d ON d.device_id=s.device_id
                LEFT JOIN {prefix}display_profiles p ON p.id=s.profile_id
                WHERE d.device_id IS NULL OR p.id IS NULL LIMIT 1""").fetchone()
        if orphan:
            raise DeliveryError('profile_reference_invalid', 503)
        rows = db.execute(
            f"""SELECT d.device_id,p.id AS profile_id,p.revision,p.mode,
                       coalesce(o.orientation,'landscape') AS orientation,c.body AS capabilities
                FROM {prefix}devices d
                LEFT JOIN {prefix}device_profiles s ON s.device_id=d.device_id
                JOIN {prefix}display_profiles p ON p.id=coalesce(s.profile_id,'events-default')
                LEFT JOIN {prefix}display_orientations o ON o.profile_id=p.id
                LEFT JOIN {prefix}device_capabilities c ON c.device_id=d.device_id
                WHERE d.revoked=0 AND d.expires>? ORDER BY d.device_id""", (now,)).fetchall()
        result = {}
        for row in rows:
            if row['mode'] == 'local' or row['capabilities'] is None:
                continue
            capabilities = decode(bytes(row['capabilities']))
            if row['mode'] not in capabilities['modes']:
                continue
            orientation = row['orientation']
            if orientation not in ('landscape', 'portrait'):
                orientation = 'landscape'
            projection = f"{row['mode']}-{orientation}"
            destination = ('windows-pages-v1' if capabilities['platform'] == 'windows'
                           else 'android-pages-v1')
            config = {'version': 1, 'profile_id': row['profile_id'],
                      'revision': row['revision'], 'mode': row['mode']}
            result[row['device_id']] = dict(
                config=config, orientation=orientation, projection=projection,
                destination=destination, configuration_sha256=sha(encode(config)))
        return result

    def page_targets(self):
        """The exact server-managed target list a v2 plan must bind."""
        with self.connection(write=False) as db:
            desired = self._page_eligible(db, int(self.clock()))
        return [dict(device_id=device_id,
                     profile_id=entry['config']['profile_id'],
                     profile_version=entry['config']['revision'],
                     mode=entry['config']['mode'],
                     orientation=entry['orientation'],
                     projection=entry['projection'],
                     destination=entry['destination'],
                     configuration=entry['config'],
                     configuration_sha256=entry['configuration_sha256'])
                for device_id, entry in sorted(desired.items())]

    def page_distribute(self, db, document, proof, receipt, acceptance_key, now, *, schema=''):
        """Commit one signed v2 plan to exact per-device assignments.

        ``db`` may be the workspace connection with the delivery database
        attached; the caller holds the combined write transaction. The original
        target set is retained even when devices later join, leave or are
        revoked. An exact retry returns the original generation without
        re-evaluating the current display set.
        """
        from kiosk.publication import authority, page_release
        page_release.validate_document(document, now=now)
        plan = document['plan']
        targets = document['targets']
        approved = {target['device_id']: target for target in targets}
        prefix = self._page_schema(schema)
        targets_sha = sha(encode(plan['targets']))
        existing = db.execute(
            f'SELECT * FROM {prefix}page_plan_commits WHERE plan_id=?',
            (plan['id'],)).fetchone()
        if existing is not None:
            if (existing['revision_sha256'] != plan['revision_sha256']
                    or existing['targets_sha256'] != targets_sha):
                raise DeliveryError('page_plan_conflict', 409)
            stored = db.execute(
                f'SELECT body FROM {prefix}page_acceptance_receipts WHERE plan_id=?',
                (plan['id'],)).fetchone()
            if stored is not None and bytes(stored['body']) != encode(receipt):
                raise DeliveryError('page_acceptance_conflict', 409)
            rows = db.execute(
                f'SELECT * FROM {prefix}page_plan_targets WHERE plan_id=?',
                (plan['id'],)).fetchall()
            if {row['device_id'] for row in rows} != set(approved):
                raise DeliveryError('page_assignment_conflict', 409)
            for row in rows:
                target = approved[row['device_id']]
                metadata = target['metadata']
                if (row['package_id'] != metadata['publication']['package_id']
                        or row['metadata_hash'] != sha(encode(metadata))):
                    raise DeliveryError('page_assignment_conflict', 409)
                assignment = db.execute(
                    f'SELECT * FROM {prefix}page_assignments WHERE device_id=?',
                    (row['device_id'],)).fetchone()
                if (assignment is None
                        or assignment['generation'] != existing['generation']
                        or assignment['plan_id'] != plan['id']
                        or assignment['package_id'] != row['package_id']
                        or assignment['metadata_hash'] != row['metadata_hash']):
                    raise DeliveryError('page_assignment_conflict', 409)
            return {'generation': existing['generation'], 'plan_id': plan['id'],
                    'targets': len(approved),
                    'packages': {target['device_id']: target['metadata']['publication']['package_id']
                                 for target in targets}}
        desired = self._page_eligible(db, now, schema)
        if set(approved) != set(desired):
            raise DeliveryError('page_targets_changed', 409)
        for device_id, target in approved.items():
            entry = desired[device_id]
            if (target['configuration'] != entry['config']
                    or target['projection'] != entry['projection']
                    or target['destination'] != entry['destination']
                    or sha(encode(target['configuration'])) != entry['configuration_sha256']):
                raise DeliveryError('page_targets_changed', 409)
            authority.validate_page_metadata(target['metadata'])
        generation = (db.execute(
            f'SELECT max(generation) FROM {prefix}page_plan_commits').fetchone()[0] or 0) + 1
        db.execute(
            f'INSERT INTO {prefix}page_plan_commits VALUES (?,?,?,?,?)',
            (plan['id'], generation, plan['revision_sha256'], targets_sha, now))
        for target in targets:
            device_id = target['device_id']
            metadata = target['metadata']
            publication = authority.validate_page_metadata(metadata)
            package_id, metadata_hash = (metadata['publication']['package_id'],
                                         sha(encode(metadata)))
            values = (device_id, generation, plan['id'], package_id, metadata_hash,
                      plan['revision_sha256'], target['destination'], target['projection'],
                      publication['renderer']['build_id'], encode(target['configuration']), now)
            db.execute(
                f'INSERT INTO {prefix}page_plan_targets VALUES (?,?,?,?,?)',
                (plan['id'], device_id, generation, package_id, metadata_hash))
            db.execute(
                f'''INSERT INTO {prefix}page_assignments
                    (device_id,generation,plan_id,package_id,metadata_hash,revision_sha256,
                     destination,projection,renderer,configuration,created)
                    VALUES (?,?,?,?,?,?,?,?,?,?,?)
                    ON CONFLICT(device_id) DO UPDATE SET generation=excluded.generation,
                        plan_id=excluded.plan_id,package_id=excluded.package_id,
                        metadata_hash=excluded.metadata_hash,revision_sha256=excluded.revision_sha256,
                        destination=excluded.destination,projection=excluded.projection,
                        renderer=excluded.renderer,configuration=excluded.configuration,
                        created=excluded.created''', values)
            db.execute(
                f'''INSERT OR REPLACE INTO {prefix}page_assignment_history
                    (device_id,generation,plan_id,package_id,metadata_hash,revision_sha256,
                     destination,projection,renderer,configuration,created)
                    VALUES (?,?,?,?,?,?,?,?,?,?,?)''', values)
            db.execute(
                f'INSERT OR REPLACE INTO {prefix}page_publisher_proofs VALUES (?,?,?)',
                (device_id, generation, encode(proof)))
        db.execute(
            f'INSERT OR REPLACE INTO {prefix}page_acceptance_receipts VALUES (?,?,?,?,?)',
            (plan['id'], generation, encode(receipt), str(acceptance_key or ''), now))
        return {'generation': generation, 'plan_id': plan['id'], 'targets': len(targets),
                'packages': {target['device_id']: target['metadata']['publication']['package_id']
                             for target in targets}}

    def page_assignment(self, device, display_protocol, pages_renderer, resource_profile):
        """Return the exact v4 variant for this device, or None to fall back.

        Only an assigned device variant is served. A client that does not
        present the v2 display protocol and the pinned page renderer keeps the
        existing v1/v3 path. A pinned renderer mismatch is an update refusal, not
        a silent downgrade.
        """
        if display_protocol != 'display-profile-v2' or not pages_renderer:
            return None
        with self.connection(write=False) as db:
            row = db.execute('SELECT * FROM page_assignments WHERE device_id=?',
                             (device['device_id'],)).fetchone()
            if row is None:
                return None
            proof = db.execute(
                'SELECT body FROM page_publisher_proofs WHERE device_id=? AND generation=?',
                (device['device_id'], row['generation'])).fetchone()
        if proof is None:
            raise DeliveryError('publisher_target_not_approved', 409)
        try:
            digest(pages_renderer)
        except DeliveryError:
            raise DeliveryError('requires_update', 409) from None
        if pages_renderer != row['renderer'] or resource_profile != PROFILE:
            raise DeliveryError('requires_update', 409)
        from .publication import page_variant
        _, metadata = page_variant(self, row['package_id'], row['metadata_hash'])
        if (metadata.get('publication', {}).get('package_id') != row['package_id']
                or metadata.get('destination') != row['destination']
                or metadata.get('revision_sha256') != row['revision_sha256']
                or metadata.get('publication', {}).get('renderer', {}).get('build_id')
                != row['renderer']):
            raise DeliveryError('publication_integrity', 503)
        config = self.configuration()
        return {'version': 4, 'group_id': config['group_id'],
                'device_id': device['device_id'], 'profile': device['profile'],
                'generation': row['generation'],
                'revision_sha256': row['revision_sha256'],
                'destination': row['destination'], 'projection': row['projection'],
                'metadata_sha256': row['metadata_hash'], 'metadata': metadata,
                'display': decode(bytes(row['configuration'])),
                'publisher': decode(bytes(proof['body']))}

    def page_activation(self, plan_id):
        """Count only client activation receipts for the exact plan generation."""
        digest(plan_id)
        with self.connection(write=False) as db:
            commit = db.execute('SELECT * FROM page_plan_commits WHERE plan_id=?',
                                (plan_id,)).fetchone()
            if commit is None:
                return None
            targets = db.execute('SELECT * FROM page_plan_targets WHERE plan_id=?',
                                (plan_id,)).fetchall()
            receipts = db.execute('SELECT device_id,body FROM receipts').fetchall()
        activated = set()
        for row in receipts:
            try:
                value = decode(bytes(row['body']))
            except (TypeError, ValueError):
                continue
            if (value.get('generation') == commit['generation']
                    and any(value.get('package_id') == target['package_id']
                            and row['device_id'] == target['device_id'] for target in targets)):
                activated.add(row['device_id'])
        return {'plan_id': plan_id, 'generation': commit['generation'],
                'targets': len(targets), 'activated': len(activated),
                'pending': max(0, len(targets) - len(activated))}

    def _meta_floor(self, db):
        row = db.execute('SELECT value FROM meta WHERE key=?', (TIME_FLOOR_KEY,)).fetchone()
        return row['value'] if row else 0

    def _trust_current(self, now):
        """The signed group trust envelope must be valid at ``now`` for renewal."""
        envelope = self.configuration()['trust']
        try:
            payload = decode(base64.b64decode(envelope['payload_base64']))
        except (KeyError, ValueError):
            raise DeliveryError('configuration_unavailable', 503) from None
        if not payload.get('issued_at', 0) <= now < payload.get('expires_at', 0):
            raise DeliveryError('admission_authority_expired', 403)

    def renew(self, secret):
        """Extend a still-valid device credential without re-enrollment or re-approval.

        The device proves possession of its current bearer secret. Renewal requires
        the device to be non-revoked, the credential to be still valid (NOT expired —
        no silent grace), the signed group trust to be valid, and a non-backward
        clock. Only the expiry advances (the secret and credential identity are
        stable), so lost responses and retries are idempotent and never mint a second
        credential. An expired credential is refused; the supported recovery path is a
        fresh enrollment with explicit admin approval (the ordinary enroll flow).
        """
        digest(secret)
        now = int(self.clock())
        with self.connection() as db:
            floor = self._meta_floor(db)
            if now < floor:
                raise DeliveryError('uncertain_time', 409)
            row = db.execute('SELECT * FROM devices WHERE verifier=?', (sha(bytes.fromhex(secret)),)).fetchone()
            if row is None or row['revoked']:
                raise DeliveryError('invalid_credential', 401)
            if row['expires'] <= now:
                raise DeliveryError('credential_expired', 401)
            self._trust_current(now)
            new_expiry = now + CREDENTIAL_SECONDS
            db.execute("UPDATE devices SET expires=? WHERE device_id=?", (new_expiry, row['device_id']))
            if now > floor:
                db.execute('INSERT INTO meta(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value',
                           (TIME_FLOOR_KEY, now))
        return {'version': 1, 'state': 'renewed', 'device_id': row['device_id'],
                'credential_id': row['credential_id'], 'expires_at': new_expiry,
                'scopes': ['read_assignment', 'submit_receipt']}

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

    def publisher_targets(self, renderer=None):
        """Eligible displays with the exact profile/config digest a plan must bind."""
        with self.connection(write=False) as db:
            desired = self._desired_targets(db, renderer, int(self.clock()))
        result = []
        for device_id, config in sorted(desired.items()):
            result.append(dict(device_id=device_id, profile_id=config['profile_id'],
                               profile_version=config['revision'], mode=config['mode'],
                               configuration_sha256=sha(encode(config))))
        return result

    def _desired_targets(self, db, renderer, now):
        """Exact eligible non-local display set for one publication renderer."""
        snapshot = self.profile_snapshot(db, renderer)
        devices = {row['device_id']: row for row in db.execute('SELECT * FROM devices')}
        result = {}
        for device_id, entry in snapshot.items():
            device = devices.get(device_id)
            config = entry['config']
            if (device is None or device['revoked'] or device['expires'] <= now
                    or device['profile'] != PROFILE or entry['reason'] != 'compatible'
                    or config['mode'] == 'local'):
                continue
            result[device_id] = config
        return result

    def assign_publisher(self, metadata, proof, targets, now, receipt=None, plan_id=None,
                         acceptance_key=None):
        """Atomic validated promotion of one approved roaming publication.

        The approved target list must exactly equal the currently eligible display
        set and every configuration digest. Assignment, history, cohort,
        configurations, publisher proofs and (when supplied) the trusted-side
        acceptance receipt commit in one transaction; any mismatch leaves the
        previous assignment untouched.
        """
        fields(metadata, 'version package_id revision raw_manifest_sha256 renderer resource_profile '
                         'limits windows_images package kiosk tv')
        digest(metadata['package_id'])
        digest(metadata['renderer']['build_id'])
        if metadata['resource_profile'] != PROFILE or type(now) is not int or now < 0:
            raise DeliveryError('unsupported_profile', 409)
        payload = (self.root / 'publications' / metadata['package_id'] / 'delivery.json').read_bytes()
        if decode(payload) != metadata or sha(encode(metadata)) != sha(payload):
            raise DeliveryError('publication_integrity', 503)
        if not isinstance(targets, list) or not targets:
            raise DeliveryError('publisher_targets_changed', 409)
        approved = {}
        for target in targets:
            fields(target, 'device_id profile_id profile_version mode configuration_sha256')
            device_id = text(target['device_id'])
            if device_id in approved:
                raise DeliveryError('publisher_target_conflict', 409)
            approved[device_id] = target
        metadata_hash = sha(payload)
        with self.connection() as db:
            desired = self._desired_targets(db, metadata['renderer']['build_id'], now)
            if set(approved) != set(desired):
                raise DeliveryError('publisher_targets_changed', 409)
            for device_id, target in approved.items():
                config = desired[device_id]
                if (target['profile_id'] != config['profile_id']
                        or target['profile_version'] != config['revision']
                        or target['mode'] != config['mode']
                        or target['configuration_sha256'] != sha(encode(config))):
                    raise DeliveryError('publisher_target_configuration', 409)
            generation = self._assign(db, PROFILE, metadata['package_id'], metadata_hash,
                                      metadata['revision'],
                                      renderer=metadata['renderer']['build_id'])
            # The committed distribution is exactly the approved display set.
            db.execute('DELETE FROM assignment_targets WHERE profile=? AND generation=?',
                       (PROFILE, generation))
            for device_id in sorted(approved):
                db.execute('INSERT INTO assignment_targets VALUES (?,?,?)',
                           (PROFILE, generation, device_id))
                db.execute('INSERT OR REPLACE INTO publisher_proofs VALUES (?,?,?,?)',
                           (PROFILE, generation, device_id, encode(proof)))
            if receipt is not None:
                digest(plan_id)
                if len(encode(receipt)) > 32768:
                    raise DeliveryError('acceptance_receipt_limit', 413)
                db.execute('INSERT OR REPLACE INTO acceptance_receipts VALUES (?,?,?,?,?,?)',
                           (PROFILE, generation, plan_id, encode(receipt),
                            str(acceptance_key or ''), now))
            return {'generation': generation, 'package_id': metadata['package_id'],
                    'metadata_sha256': metadata_hash, 'targets': len(approved)}

    def publisher_distribution(self, metadata_hash):
        """Current distributed assignment for one signed publication, or None."""
        digest(metadata_hash)
        with self.connection(write=False) as db:
            row = db.execute('SELECT profile,generation,package_id FROM assignments WHERE metadata_hash=?',
                             (metadata_hash,)).fetchone()
            if row is None:
                return None
            proofs = db.execute('SELECT COUNT(*) FROM publisher_proofs WHERE profile=? AND generation=?',
                                (row['profile'], row['generation'])).fetchone()[0]
            targets = db.execute('SELECT COUNT(*) FROM assignment_targets WHERE profile=? AND generation=?',
                                 (row['profile'], row['generation'])).fetchone()[0]
            return dict(generation=row['generation'], package_id=row['package_id'],
                        targets=targets, proofs=proofs)

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
            return self._assign(db, profile, package_id, metadata_hash, metadata['revision'], renderer=metadata['renderer']['build_id'])

    def _assign(self, db, profile, package_id, metadata_hash, revision, *, renderer=None):
        """The caller holds the publication lease; targets and generation commit together."""
        old = db.execute('SELECT * FROM assignments WHERE profile=?', (profile,)).fetchone()
        snapshot = self.profile_snapshot(db, renderer)
        snapshot_bytes = encode({k: v for k, v in snapshot.items() if v['config']['mode'] != 'local'})
        prior_config = db.execute('SELECT identity FROM publication_config_sets WHERE generation=?', (old['generation'],)).fetchone() if old else None
        if old and old['package_id'] == package_id and old['metadata_hash'] == metadata_hash and (bytes(prior_config['identity']) if prior_config else encode({})) == snapshot_bytes:
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
        db.execute('INSERT INTO publication_config_sets VALUES (?,?)', (generation, snapshot_bytes))
        for device_id, entry in snapshot.items():
            db.execute('INSERT INTO publication_configs VALUES (?,?,?,?)', (generation, device_id, encode(entry['config']), entry['reason']))
            if entry['reason'] != 'compatible':
                db.execute('DELETE FROM assignment_targets WHERE profile=? AND generation=? AND device_id=?', (profile, generation, device_id))
        return generation

    def assignment(self, device, renderer, resource_profile, display_protocol=None):
        with self.connection(write=False) as db:
            row = db.execute('SELECT * FROM assignments WHERE profile=?', (device['profile'],)).fetchone()
            configured = db.execute('SELECT * FROM publication_configs WHERE generation=? AND device_id=?', (row['generation'], device['device_id'])).fetchone() if row else None
            proof_row = db.execute('SELECT body FROM publisher_proofs WHERE profile=? AND generation=? AND device_id=?',
                                   (device['profile'], row['generation'], device['device_id'])).fetchone() if row else None
            proof_count = db.execute('SELECT COUNT(*) FROM publisher_proofs WHERE profile=? AND generation=?',
                                     (device['profile'], row['generation'])).fetchone()[0] if row else 0
        if row is None:
            raise DeliveryError('no_assignment', 404)
        # A signed target set is never widened by serving unsigned content to a
        # display that was not approved for this publication.
        if proof_count and proof_row is None:
            raise DeliveryError('publisher_target_not_approved', 409)
        payload = (self.root / 'publications' / row['package_id'] / 'delivery.json').read_bytes()
        if sha(payload) != row['metadata_hash']:
            raise DeliveryError('publication_integrity', 503)
        metadata = decode(payload)
        from kiosk.display.cache import renderer_compatible
        if not renderer_compatible(metadata['renderer']['build_id'], renderer) or metadata['resource_profile'] != resource_profile:
            raise DeliveryError('requires_update', 409)
        display = decode(bytes(configured['body'])) if configured else {'version': 1, 'profile_id': 'events-default', 'revision': 1, 'mode': 'local'}
        if configured and configured['reason'] != 'compatible':
            raise DeliveryError(configured['reason'], 409)
        if proof_row is not None:
            # An approved roaming publication is never downgraded to the unsigned
            # envelope; a client that cannot carry the display profile must update.
            if display_protocol != 'display-profile-v1' or display['mode'] == 'local':
                raise DeliveryError('display_profile_update_required', 409)
        elif display_protocol != 'display-profile-v1' and display['mode'] != 'local':
            raise DeliveryError('display_profile_update_required', 409)
        config = self.configuration()
        result = {'version': 1, 'group_id': config['group_id'], 'device_id': device['device_id'],
                'profile': device['profile'], 'generation': row['generation'],
                'metadata_sha256': row['metadata_hash'], 'publication': metadata}
        if display_protocol == 'display-profile-v1':
            result.update(version=2, display=display)
            if proof_row is not None:
                result.update(version=3, publisher=decode(bytes(proof_row['body'])))
        return result

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
            assignment = db.execute('SELECT package_id FROM assignment_history WHERE profile=? AND generation=?',
                                    (device['profile'], body['generation'])).fetchone()
            page = None
            if assignment is None or body['package_id'] != assignment['package_id']:
                page = db.execute(
                    'SELECT * FROM page_assignment_history WHERE device_id=? AND generation=?',
                    (device['device_id'], body['generation'])).fetchone()
                if page is None or page['package_id'] != body['package_id']:
                    raise DeliveryError('unknown_assignment', 409)
            if assignment is not None and body['package_id'] == assignment['package_id']:
                # Historical queued receipts remain admissible only for an actual
                # retained v1 publication.
                record = self.root / 'publications' / body['package_id'] / 'delivery.json'
                if not record.is_file():
                    raise DeliveryError('unknown_publication', 409)
                display = db.execute('SELECT body,reason FROM publication_configs WHERE generation=? AND device_id=?', (body['generation'], device['device_id'])).fetchone()
                if display:
                    if display['reason'] != 'compatible':
                        raise DeliveryError('incompatible_assignment', 409)
                    mode = decode(bytes(display['body']))['mode']
                    if mode != 'local' and mode != body['mode']:
                        raise DeliveryError('ready_mode_mismatch', 409)
            else:
                # A v4 page receipt must match one exact frozen per-device
                # variant. It never authorizes the v1 Events package or a
                # different target's catalog.
                from .publication import page_variant
                page_variant(self, page['package_id'], page['metadata_hash'])
                if body['mode'] != page['projection'].split('-', 1)[0]:
                    raise DeliveryError('ready_mode_mismatch', 409)
            count = db.execute('SELECT count(*) FROM receipts WHERE device_id=?', (device['device_id'],)).fetchone()[0]
            if count >= MAX_RECEIPTS_PER_DEVICE:
                raise DeliveryError('receipt_capacity', 429)
            db.execute('INSERT INTO receipts VALUES (?,?,?,?)', (device['device_id'], body['receipt_id'], payload, int(self.clock())))
        return {'version': 1, 'receipt_id': body['receipt_id'], 'state': 'recorded'}
