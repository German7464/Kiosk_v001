"""Content progress v1: advisory transfer state, never activation evidence."""
from .protocol import DeliveryError, LIMITS, digest, fields

STATES = ('waiting', 'downloading', 'downloaded', 'verified', 'error', 'incompatible')
ERRORS = ('none', 'connection', 'storage', 'integrity', 'requires_update', 'assignment_changed', 'candidate_refused')
MAX_PROGRESS_BYTES = 2048
STALE_SECONDS = 120


def validate(body):
    fields(body, 'version device_id group_id generation package_id attempt sequence state completed_bytes total_bytes error')
    if type(body['version']) is not int or body['version'] != 1:
        raise DeliveryError('unsupported_version', 409)
    for key in ('generation', 'attempt', 'sequence'):
        if type(body[key]) is not int or not 0 < body[key] < 2**63:
            raise DeliveryError('invalid_progress')
    if body['sequence'] < body['attempt']:
        raise DeliveryError('invalid_progress')
    digest(body['package_id'])
    if body['state'] not in STATES or body['error'] not in ERRORS:
        raise DeliveryError('invalid_progress')
    completed, total = body['completed_bytes'], body['total_bytes']
    if (type(completed) is not int or type(total) is not int or
            not 0 <= completed <= total <= LIMITS['capture_bytes']):
        raise DeliveryError('invalid_progress')
    if ((body['state'] in ('error', 'incompatible')) != (body['error'] != 'none') or
            (body['state'] == 'incompatible' and body['error'] != 'requires_update') or
            (body['state'] in ('downloaded', 'verified') and completed != total)):
        raise DeliveryError('invalid_progress')
    return body


def advances(old, new):
    if new['attempt'] < old['attempt']:
        return False
    if new['attempt'] > old['attempt']:
        return True
    if old['state'] in ('error', 'incompatible'):
        return new['state'] == old['state'] and new['error'] == old['error']
    if new['state'] in ('error', 'incompatible'):
        return True
    if new['total_bytes'] != old['total_bytes'] or new['completed_bytes'] < old['completed_bytes']:
        return False
    return new['state'] in ('error', 'incompatible') or STATES.index(new['state']) >= STATES.index(old['state'])
