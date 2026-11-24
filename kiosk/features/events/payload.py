"""Validated Events draft payload used by publication snapshots.

The validator preserves the existing workspace diagnostic codes and statuses.
Callers that need their own exception type can pass its two-argument
``(code, status)`` constructor as ``error``.
"""
from kiosk.delivery.protocol import encode

MAX_OBJECT_BYTES = 32768
EVENT_FIELDS = frozenset({'title', 'short_description', 'full_description', 'event_date', 'place',
                          'sort_order', 'status', 'images', 'tags'})
EVENT_TEXT_LIMIT = (('title', 300), ('short_description', 4096),
                    ('full_description', 16384), ('event_date', 64), ('place', 512))


class PayloadError(ValueError):
    def __init__(self, code, status=400):
        self.code, self.status = code, status
        super().__init__(code)


def validate_payload(value, error=PayloadError):
    """Return one valid Events draft payload or raise a stable coded error."""
    if not isinstance(value, dict) or len(encode(value)) > MAX_OBJECT_BYTES:
        raise error('draft_limit', 413)
    if set(value) != EVENT_FIELDS:
        raise error('invalid_event_fields')
    for name, maximum in EVENT_TEXT_LIMIT:
        item = value[name]
        if name == 'event_date' and item is None:
            continue
        if not isinstance(item, str) or len(item) > maximum or '\x00' in item:
            raise error('invalid_event_text')
    if not value['title'].strip() or value['status'] not in ('active', 'hidden'):
        raise error('invalid_event')
    if type(value['sort_order']) is not int or not -100000 <= value['sort_order'] <= 100000:
        raise error('invalid_event_order')
    for field, maximum in (('images', 3), ('tags', 32)):
        items = value[field]
        if not isinstance(items, list) or len(items) > maximum or any(not isinstance(x, str) and
                not (field == 'images' and len(items) == 3 and x is None) for x in items):
            raise error('invalid_event_references')
        if field == 'tags' and len(set(items)) != len(items):
            raise error('invalid_event_references')
        for item in items:
            if field == 'images':
                if item is None:
                    continue
                if (not item.startswith('/static/uploads/') or '\\' in item
                        or any(part in ('', '.', '..') for part in item.split('/')[1:])
                        or len(item) > 512 or '\x00' in item or '?' in item or '#' in item or '%' in item):
                    raise error('invalid_event_references')
            elif not item.strip() or len(item) > 128 or '\x00' in item:
                raise error('invalid_event_references')
    return value


validate = validate_payload
