"""Generate public candidate fixture for Android review-parity tests (public only)."""
import base64
import json
from pathlib import Path

from kiosk.delivery.protocol import encode, sha
from kiosk.publication import authority as a
from kiosk.publication import mapping
from kiosk.trust.crypto import generate_private_key, key_id, spki_der

now = 2_000_000_000
root, device = generate_private_key(), generate_private_key()

objects = {
    '1': dict(version=2, author='alice', dependencies={}, payload=dict(
        title='Zebra', short_description='S1', full_description='F1', event_date='2026-11-16',
        place='Hall', sort_order=2, status='active',
        images=['/static/uploads/z.jpg', '/static/uploads/y.jpg'], tags=['Ä', 'Zeta'])),
    '2': dict(version=1, author='alice', dependencies={}, payload=dict(
        title='Alpha', short_description='', full_description='', event_date='2026-11-15',
        place='', sort_order=1, status='active', images=[], tags=['Zeta'])),
    '3': dict(version=1, author='alice', dependencies={}, payload=dict(
        title='Hidden', short_description='', full_description='', event_date='2026-11-14',
        place='', sort_order=0, status='hidden', images=[], tags=[])),
}
settings = {'site_title': 'Museum — Ä', 'kiosk_heading': 'Events'}
content_version = 4
data = mapping.derive(objects, settings, content_version)
data_bytes = encode(data)
config = {'version': 1, 'profile_id': 'events-tv', 'revision': 3, 'mode': 'tv'}
renderer = 'ab' * 32
metadata = {
    'version': 1, 'package_id': 'cd' * 32, 'revision': str(content_version),
    'raw_manifest_sha256': 'ef' * 32,
    'renderer': {'build_id': renderer, 'js_sha256': '01' * 32, 'css_sha256': '02' * 32},
    'resource_profile': 'events-phone-lab-v1',
    'limits': {'max_pixels': 2_000_000, 'max_live_bytes': 32 * 1024 * 1024,
               'per_image_ms': 5000, 'total_image_ms': 15000, 'capture_bytes': 192 * 1024 * 1024,
               'capture_files': 30003, 'min_free_bytes': 16 * 1024 * 1024},
    'windows_images': {},
    'package': {'files': [{'path': 'data/events.json', 'size': len(data_bytes),
                           'sha256': sha(data_bytes)}]},
    'kiosk': {'files': []}, 'tv': {'files': []},
}
plan = dict(group_id='group', origin='https://kiosk.example:20443', user_id='alice',
            device_id=key_id(device), policy_version=1, issued=now - 10, expires=now + 3600,
            publication_sha256=sha(encode(metadata)), dependencies_sha256=sha(encode(objects)),
            renderer=renderer,
            targets=[{'device_id': 'display1', 'profile_id': 'events-tv', 'profile_version': 3,
                      'mode': 'tv', 'configuration_sha256': sha(encode(config))}], parents=[])
plan['id'] = sha(encode(plan))
document = dict(plan=plan, objects=objects, publication=metadata, ancestry=[],
                settings=settings, content_version=content_version)
fixture = dict(now=now, root_spki=base64.b64encode(spki_der(root)).decode(),
               device_spki=base64.b64encode(spki_der(device)).decode(),
               device_id=key_id(device), origin='https://kiosk.example:20443',
               document=document, data_base64=base64.b64encode(data_bytes).decode())
Path('android/testdata/roaming-candidate-v1-public.json').write_text(
    json.dumps(fixture, sort_keys=True, separators=(',', ':')), encoding='utf-8')
print('events', [(e['id'], e['title'], e['tag_ids'], e['image_kiosk'], e['image_tv'], e['image_thumb'])
                 for e in data['events']])
print('tags', [item['id'] for item in data['tags']], 'version', content_version,
      'plan', plan['id'][:16])
