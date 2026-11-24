"""Bounded display configuration, separate from enrollment resource authority."""
from .protocol import DeliveryError, decode, encode, fields, text

DEFAULT = 'events-default'
SCHEMA = """
CREATE TABLE IF NOT EXISTS display_profiles (
 id TEXT PRIMARY KEY, name TEXT NOT NULL, mode TEXT NOT NULL, revision INTEGER NOT NULL);
CREATE TABLE IF NOT EXISTS device_profiles (device_id TEXT PRIMARY KEY, profile_id TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS device_capabilities (device_id TEXT PRIMARY KEY, body BLOB NOT NULL);
CREATE TABLE IF NOT EXISTS publication_configs (
 generation INTEGER NOT NULL, device_id TEXT NOT NULL, body BLOB NOT NULL, reason TEXT NOT NULL,
 PRIMARY KEY(generation,device_id));
CREATE TABLE IF NOT EXISTS publication_config_sets (generation INTEGER PRIMARY KEY, identity BLOB NOT NULL);
INSERT OR IGNORE INTO display_profiles VALUES ('events-default','Events — local mode (legacy)','local',1);
"""


def capability(body):
    fields(body, 'version platform modes content resource_profile renderer')
    if (type(body['version']) is not int or body['version'] != 1
            or body['platform'] not in ('windows', 'android')
            or body['content'] != ['events'] or body['resource_profile'] != 'events-phone-lab-v1'
            or not isinstance(body['modes'], list) or not body['modes']
            or len(body['modes']) > 2 or any(not isinstance(m, str) for m in body['modes']) or len(set(body['modes'])) != len(body['modes'])
            or any(mode not in ('tv', 'kiosk') for mode in body['modes'])):
        raise DeliveryError('unsupported_capabilities', 409)
    from .protocol import digest
    digest(body['renderer'])
    return body


class ProfileState:
    def report_capabilities(self, device, body):
        capability(body)
        with self.connection() as db:
            db.execute('INSERT INTO device_capabilities VALUES (?,?) ON CONFLICT(device_id) DO UPDATE SET body=excluded.body',
                       (device['device_id'], encode(body)))
        return {'version': 1, 'state': 'recorded'}

    def save_profile(self, profile_id, name, mode, revision=0):
        text(profile_id, 64)
        if profile_id == DEFAULT or not isinstance(name, str) or not 1 <= len(name.strip()) <= 64 or not all(c.isprintable() for c in name):
            raise DeliveryError('invalid_profile_name')
        if mode not in ('tv', 'kiosk'):
            raise DeliveryError('unsupported_display_mode', 409)
        if type(revision) is not int or revision < 0:
            raise DeliveryError('invalid_profile_revision')
        with self.connection() as db:
            old = db.execute('SELECT * FROM display_profiles WHERE id=?', (profile_id,)).fetchone()
            if old is None and db.execute('SELECT count(*) FROM display_profiles').fetchone()[0] >= 100:
                raise DeliveryError('profile_capacity', 409)
            if (old['revision'] if old else 0) != revision:
                raise DeliveryError('profile_changed', 409)
            db.execute('INSERT INTO display_profiles VALUES (?,?,?,?) ON CONFLICT(id) DO UPDATE SET name=excluded.name,mode=excluded.mode,revision=excluded.revision',
                       (profile_id, name.strip(), mode, revision + 1))

    def select_profile(self, device_id, profile_id):
        text(device_id); text(profile_id, 64)
        with self.connection() as db:
            if not db.execute('SELECT 1 FROM devices WHERE device_id=?', (device_id,)).fetchone():
                raise DeliveryError('device_not_found', 404)
            if not db.execute('SELECT 1 FROM display_profiles WHERE id=?', (profile_id,)).fetchone():
                raise DeliveryError('profile_not_found', 404)
            db.execute('INSERT INTO device_profiles VALUES (?,?) ON CONFLICT(device_id) DO UPDATE SET profile_id=excluded.profile_id', (device_id, profile_id))

    def profile_snapshot(self, db, renderer=None):
        result = {}
        orphan = db.execute("""SELECT 1 FROM device_profiles s LEFT JOIN devices d ON d.device_id=s.device_id
            LEFT JOIN display_profiles p ON p.id=s.profile_id WHERE d.device_id IS NULL OR p.id IS NULL LIMIT 1""").fetchone()
        if orphan:
            raise DeliveryError('profile_reference_invalid', 503)
        for row in db.execute("""SELECT d.device_id,p.* FROM devices d
            LEFT JOIN device_profiles s ON s.device_id=d.device_id
            JOIN display_profiles p ON p.id=coalesce(s.profile_id,'events-default') ORDER BY d.device_id"""):
            config = {'version': 1, 'profile_id': row['id'], 'revision': row['revision'], 'mode': row['mode']}
            caps = db.execute('SELECT body FROM device_capabilities WHERE device_id=?', (row['device_id'],)).fetchone()
            reason = 'compatible'
            if row['mode'] != 'local':
                if caps is None:
                    reason = 'report_capabilities_update_client'
                else:
                    c = decode(bytes(caps['body']))
                    if row['mode'] not in c['modes']:
                        reason = 'unsupported_mode_select_another_profile'
                    elif renderer:
                        from kiosk.display.cache import renderer_compatible
                        if not renderer_compatible(c['renderer'], renderer):
                            reason = 'renderer_update_required'
            result[row['device_id']] = {'config': config, 'reason': reason}
        return result

    def profiles_admin(self):
        with self.connection(write=False) as db:
            profiles = [dict(r) for r in db.execute('SELECT * FROM display_profiles ORDER BY id')]
            desired = self.profile_snapshot(db)
            caps = {r['device_id']: decode(bytes(r['body'])) for r in db.execute('SELECT * FROM device_capabilities')}
            current = db.execute('SELECT max(generation) FROM publication_config_sets').fetchone()[0]
            published = {r['device_id']: {'config': decode(bytes(r['body'])), 'reason': r['reason']} for r in db.execute('SELECT * FROM publication_configs WHERE generation=?', (current,))}
        return {'profiles': profiles, 'names': {p['id']: p['name'] for p in profiles}, 'desired': desired, 'capabilities': caps, 'published': published}
