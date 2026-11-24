"""Exact immutable draft-snapshot -> public Events data mapping.

The mapping is a pure function of the frozen workspace objects, the display
settings and a content revision. Both the server that exports the package and
every native reviewer that signs it recompute this mapping; a package whose
``data/events.json`` differs is refused before signing. Never re-read the
mutable Events database or the working draft rows for this mapping.
"""
from kiosk.delivery.protocol import sha, encode

MAX_EVENT_ID = 2 ** 31 - 1
EVENT_TEXT = {'title': 300, 'short_description': 4096, 'full_description': 16384,
              'event_date': 64, 'place': 512}
SETTINGS_LIMIT = {'site_title': 300, 'interface_language': 8, 'site_icon': 512,
                  'tv_slide_duration': 16, 'kiosk_label': 300, 'kiosk_heading': 300,
                  'kiosk_description': 2000}
IMAGE_FIELDS = ('image_kiosk', 'image_tv', 'image_thumb')


class MappingError(ValueError):
    """Stable mapping diagnostic; never contains draft text or private paths."""


def _event_id(identity):
    if (not isinstance(identity, str) or not identity.isascii() or not identity.isdigit()
            or not 1 <= int(identity) <= MAX_EVENT_ID or str(int(identity)) != identity):
        raise MappingError('mapping_event_identity')
    return int(identity)


def settings(values):
    """Validate the allowlisted public display settings only."""
    if not isinstance(values, dict) or len(values) > len(SETTINGS_LIMIT):
        raise MappingError('mapping_settings')
    result = {}
    for name, value in values.items():
        if name not in SETTINGS_LIMIT or not isinstance(value, str) or len(value) > SETTINGS_LIMIT[name]:
            raise MappingError('mapping_settings')
        if '\x00' in value:
            raise MappingError('mapping_settings')
        result[name] = value
    return result


def _images(images):
    if len(images) == 3:
        return tuple(images)
    if images and images[0]:
        first = images[0]
        return first, images[1] if len(images) > 1 else first, images[2] if len(images) > 2 else first
    return None, None, None


def derive(objects, settings_values, content_version):
    """Deterministic public data for exactly these frozen object revisions.

    Identity must be the decimal Events id. Only ``active`` drafts are public.
    Tag ids are assigned by sorted tag name, so they are stable for this exact
    snapshot and cannot be influenced by the live Tags table. Media references
    are the public upload paths already validated by the exporter.
    """
    if type(content_version) is not int or content_version < 1:
        raise MappingError('mapping_content_version')
    if not isinstance(objects, dict) or not 1 <= len(objects) <= 1000:
        raise MappingError('mapping_objects')
    active = []
    names = set()
    for identity, entry in objects.items():
        number = _event_id(identity)
        payload = entry.get('payload') if isinstance(entry, dict) else None
        if not isinstance(payload, dict) or payload.get('status') not in ('active', 'hidden'):
            raise MappingError('mapping_object_payload')
        if payload['status'] == 'hidden':
            continue
        for name, maximum in EVENT_TEXT.items():
            value = payload.get(name)
            if name == 'event_date' and name in payload and value is None:
                continue
            if not isinstance(value, str) or len(value) > maximum or '\x00' in value:
                raise MappingError('mapping_object_text')
        if not payload['title'].strip():
            raise MappingError('mapping_object_text')
        images = payload.get('images')
        if (not isinstance(images, list) or len(images) > 3
                or any(not isinstance(item, str) and not (len(images) == 3 and item is None) for item in images)):
            raise MappingError('mapping_object_media')
        for item in images:
            if item is None:
                continue
            if not item.startswith('/static/uploads/') or '\\' in item or '..' in item.split('/'):
                raise MappingError('mapping_object_media')
        tags = payload.get('tags')
        if (not isinstance(tags, list) or len(tags) > 32 or len(set(tags)) != len(tags)
                or any(not isinstance(tag, str) or not tag.strip() or len(tag) > 128 or '\x00' in tag for tag in tags)):
            raise MappingError('mapping_object_tags')
        names.update(tags)
        active.append((number, payload))
    tag_ids = {name: index for index, name in enumerate(sorted(names), 1)}
    events = []
    for number, payload in sorted(active, key=lambda item: (item[1]['sort_order'], item[1]['event_date'] or '', item[0])):
        kiosk, tv, thumb = _images(payload['images'])
        events.append({'id': number, 'title': payload['title'],
                       'short_description': payload['short_description'],
                       'full_description': payload['full_description'],
                       'event_date': payload['event_date'], 'place': payload['place'],
                       'image_kiosk': kiosk, 'image_tv': tv, 'image_thumb': thumb,
                       'sort_order': payload['sort_order'],
                       'tag_ids': sorted(tag_ids[name] for name in payload['tags'])})
    return {'content_version': content_version,
            'events': events,
            'tags': [{'id': tag_ids[name], 'name': name} for name in sorted(tag_ids)],
            'settings': settings(settings_values)}


def digest(data):
    return sha(encode(data))


def public_bytes(objects, settings_values, content_version):
    """The exact bytes a package must contain at ``data/events.json``."""
    return encode(derive(objects, settings_values, content_version))


def verify(data, objects, settings_values, content_version):
    """Refuse substituted public data before any signature is produced."""
    if data != derive(objects, settings_values, content_version):
        raise MappingError('mapping_substitution')
    return data
