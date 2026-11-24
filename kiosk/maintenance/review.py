"""Exact immutable review inside the trusted Maintenance service.

The browser receives only this allowlisted view model. Content is treated as
untrusted data: it is re-derived from the frozen draft objects and compared with
the package entry hash before anything can be signed. No server HTML or script is
imported, and there is no generic hash-signing endpoint.
"""
from __future__ import annotations

from kiosk.delivery.protocol import decode, encode, sha
from kiosk.publication import authority, mapping
from .store import MaintenanceError

MAX_REVIEW_BYTES = 2 * 1024 * 1024
FIELDS = ('title', 'short_description', 'full_description', 'event_date', 'place',
          'sort_order', 'status', 'images', 'tags')


def _text(value, limit):
    if not isinstance(value, str) or len(value) > limit or '\x00' in value:
        raise MaintenanceError('review_content_refused', 409)
    return value


def _targets(value):
    if not isinstance(value, list) or not 1 <= len(value) <= 100:
        raise MaintenanceError('review_targets_refused', 409)
    result = []
    for item in value:
        if not isinstance(item, dict):
            raise MaintenanceError('review_targets_refused', 409)
        result.append(dict(device_id=_text(item.get('device_id'), 64),
                           profile_id=_text(item.get('profile_id'), 64),
                           profile_version=int(item.get('profile_version') or 0),
                           mode=_text(item.get('mode'), 16),
                           configuration_sha256=_text(item.get('configuration_sha256'), 64)))
    return result


def _strings(value, limit, count):
    """Bounded list of plain strings; content is data, never markup."""
    if value is None:
        return []
    if not isinstance(value, list) or len(value) > count:
        raise MaintenanceError('review_content_refused', 409)
    return [_text(item, limit) for item in value]


def validate(document, *, targets, user_id, group_id, origin, now):
    """Return the review view model for one frozen candidate or refuse it."""
    if not isinstance(document, dict):
        raise MaintenanceError('review_document_refused', 409)
    plan, publication = document.get('plan'), document.get('publication')
    if not isinstance(plan, dict) or not isinstance(publication, dict):
        raise MaintenanceError('review_document_refused', 409)
    try:
        authority.validate_plan(plan, now=now)
        authority.check_ancestry(plan, (), document.get('ancestry', []))
    except ValueError:
        raise MaintenanceError('review_plan_refused', 409) from None
    if (plan['group_id'] != group_id or plan['origin'] != origin or
            plan['user_id'] != user_id):
        raise MaintenanceError('review_scope_refused', 403)
    if (targets is not None and
            [item['device_id'] for item in plan['targets']] !=
            [item['device_id'] for item in targets]):
        raise MaintenanceError('review_targets_changed', 409)
    if sha(encode(publication)) != plan['publication_sha256']:
        raise MaintenanceError('review_publication_substitution', 409)
    if publication.get('renderer', {}).get('build_id') != plan['renderer']:
        raise MaintenanceError('review_renderer_substitution', 409)
    try:
        expected = mapping.derive(document['objects'], document.get('settings', {}),
                                  document.get('content_version'))
    except (ValueError, KeyError, TypeError):
        raise MaintenanceError('review_snapshot_refused', 409) from None
    encoded = encode(expected)
    entries = [item for item in publication['package']['files']
               if item['path'] == 'data/events.json']
    if (len(entries) != 1 or entries[0]['size'] != len(encoded) or
            entries[0]['sha256'] != sha(encoded)):
        raise MaintenanceError('review_snapshot_substitution', 409)
    if str(publication.get('revision')) != str(document.get('content_version')):
        raise MaintenanceError('review_revision_substitution', 409)
    events = []
    media = []
    for event in expected.get('events', []):
        item = {name: event.get(name) for name in FIELDS}
        item['title'] = _text(item['title'], 300)
        item['short_description'] = _text(item['short_description'], 4096)
        item['full_description'] = _text(item['full_description'], 16384)
        item['event_date'] = _text(item['event_date'], 64)
        item['place'] = _text(item['place'], 512)
        item['images'] = _strings(item.get('images'), 512, 64)
        item['tags'] = _strings(item.get('tags'), 128, 64)
        item['sort_order'] = int(item.get('sort_order') or 0)
        item['status'] = _text(item.get('status') or '', 32)
        for image in item['images']:
            if image not in media:
                media.append(image)
        events.append(item)
    view = dict(
        version=1, plan_id=plan['id'], confirmation=plan['id'][:8].upper(),
        user_id=plan['user_id'], device_id=plan['device_id'],
        policy_version=plan['policy_version'], expires=plan['expires'],
        package_id=publication['package_id'], revision=document.get('content_version'),
        renderer=plan['renderer'], publication_sha256=plan['publication_sha256'],
        dependencies_sha256=plan['dependencies_sha256'],
        targets=_targets(plan['targets']), events=events,
        media=media[:256], event_count=len(events),
        settings=_settings(document.get('settings', {})),
        package_files=[dict(path=_text(item['path'], 512), size=int(item['size']),
                            sha256=_text(item['sha256'], 64))
                       for item in publication['package']['files'][:512]],
    )
    if len(encode(view)) > MAX_REVIEW_BYTES:
        raise MaintenanceError('review_limit', 413)
    return view


def _settings(values):
    allowed = ('site_title', 'interface_language', 'tv_slide_duration', 'kiosk_label',
               'kiosk_heading', 'kiosk_description')
    if not isinstance(values, dict):
        raise MaintenanceError('review_settings_refused', 409)
    return {name: _text(str(values.get(name, '')), 512) for name in allowed}


def ticket_digest(document, targets, user_id):
    value = {'document': document, 'targets': targets, 'user_id': user_id}
    return sha(encode(value))
