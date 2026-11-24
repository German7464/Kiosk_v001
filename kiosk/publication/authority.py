"""Independent publisher permissions and exact approvals (roaming-publish-v1).

No private key or server-account lookup belongs in this verifier. Its root SPKI
must be installed through a separately authenticated administrator operation.
"""
from __future__ import annotations

import base64
from urllib.parse import urlsplit

from . import validate_manifest
from kiosk.delivery.protocol import (LIMITS, MAX_METADATA_BYTES, PROFILE, decode, digest,
                                     encode, fields, sha, text)
from kiosk.trust.crypto import key_id, sign, verify

DOMAIN = b'Kiosk/RoamingPublish/v1\0'
# Planned administrator maintenance is day90, not the instant authority fails.
# Fourteen days of bounded overlap allow planned renewal/recovery without
# promising ninety unattended days from a ninety-day signing envelope.
MAINTENANCE_DAYS = 90
AUTHORITY_OVERLAP_DAYS = 14
MAX_AUTHORITY_SECONDS = (MAINTENANCE_DAYS + AUTHORITY_OVERLAP_DAYS) * 86400
MAX_PLAN_SECONDS = 90 * 86400
MAX_ENVELOPE_BYTES = 32768
MAX_ANCESTRY_NODES = 128
MAX_ANCESTRY_BYTES = 512 * 1024
PAGE_PLAN_VERSION = 2
PAGE_ENVELOPE_VERSION = 2
PAGE_ASSIGNMENT_VERSION = 4
PAGE_KIND = 'page-publication'
PAGE_DOMAIN = b'Kiosk/PageRelease/v2\0'
PAGE_PLAN_DOMAIN = b'Kiosk/PageReleasePlan/v2\0'
PAGE_RENDERER_DOMAIN = b'Kiosk/PagesRenderer/v1\0'
PAGE_MANIFEST_VERSION = 2
PAGE_RENDERER = 'pages-v1'
PAGE_DESTINATIONS = ('android-pages-v1', 'windows-pages-v1')
PAGE_PROJECTIONS = ('kiosk-landscape', 'kiosk-portrait', 'tv-landscape', 'tv-portrait')
MAX_PAGE_ENVELOPE_BYTES = MAX_ENVELOPE_BYTES
MAX_PAGE_METADATA_FILES = 30003
MAX_PAGE_METADATA_FILE_BYTES = 64 * 1024 * 1024
MAX_PAGE_METADATA_BYTES = 192 * 1024 * 1024


def _integer(value, minimum=1):
    if type(value) is not int or not minimum <= value < 2**63:
        raise ValueError('publisher_integer_refused')
    return value


def _b64(value, maximum):
    if not isinstance(value, str) or len(value) > (maximum + 2) // 3 * 4:
        raise ValueError('publisher_encoding_refused')
    raw = base64.b64decode(value, validate=True)
    if len(raw) > maximum or base64.b64encode(raw).decode('ascii') != value:
        raise ValueError('publisher_encoding_refused')
    return raw


def origin(value):
    if not isinstance(value, str) or len(value) > 255:
        raise ValueError('publisher_origin_refused')
    if any(c.isspace() or c in '%\\' or ord(c)>127 for c in value):
        raise ValueError('publisher_origin_refused')
    parsed = urlsplit(value)
    if (parsed.scheme != 'https' or not parsed.hostname or parsed.username or
            parsed.password or parsed.path or parsed.query or parsed.fragment or
            parsed.netloc != parsed.netloc.lower()):
        raise ValueError('publisher_origin_refused')
    # Force port validation; exact strings are bound throughout the protocol.
    parsed.port
    return value


def signed(private, kind, value):
    """Local signing primitive; callers must obtain native explicit consent."""
    text(kind, 32)
    payload = encode({'kind': kind, 'value': value, 'version': 1})
    if len(payload) > MAX_ENVELOPE_BYTES:
        raise ValueError('publisher_envelope_limit')
    return {'payload': base64.b64encode(payload).decode('ascii'),
            'signature': base64.b64encode(sign(private, DOMAIN, payload)).decode('ascii')}


def verified(envelope, spki, kind):
    fields(envelope, 'payload signature')
    payload = _b64(envelope['payload'], MAX_ENVELOPE_BYTES)
    verify(spki, DOMAIN, payload, _b64(envelope['signature'], 384))
    value = decode(payload)
    fields(value, 'kind value version')
    if type(value['version']) is not int or value['version'] != 1 or value['kind'] != kind:
        raise ValueError('publisher_domain_refused')
    if encode(value) != payload or not isinstance(value['value'], dict):
        raise ValueError('publisher_canonical_refused')
    return value['value']


def page_signed(private, value):
    """Low-level v2 page-plan signature; native callers must review first."""
    payload = encode({'kind': PAGE_KIND, 'value': value, 'version': PAGE_ENVELOPE_VERSION})
    if len(payload) > MAX_PAGE_ENVELOPE_BYTES:
        raise ValueError('publisher_envelope_limit')
    return {'payload': base64.b64encode(payload).decode('ascii'),
            'signature': base64.b64encode(sign(private, PAGE_DOMAIN, payload)).decode('ascii')}


def page_verified(envelope, spki):
    fields(envelope, 'payload signature')
    payload = _b64(envelope['payload'], MAX_PAGE_ENVELOPE_BYTES)
    verify(spki, PAGE_DOMAIN, payload, _b64(envelope['signature'], 384))
    value = decode(payload)
    fields(value, 'kind value version')
    if (type(value['version']) is not int or value['version'] != PAGE_ENVELOPE_VERSION
            or value['kind'] != PAGE_KIND):
        raise ValueError('publisher_domain_refused')
    if encode(value) != payload or not isinstance(value['value'], dict):
        raise ValueError('publisher_canonical_refused')
    return value['value']


def page_renderer_build_id(js_sha256, css_sha256):
    """Bind the platform-pinned data renderer assets to one build identity."""
    digest(js_sha256)
    digest(css_sha256)
    return sha(PAGE_RENDERER_DOMAIN + encode({'css_sha256': css_sha256,
                                              'js_sha256': js_sha256}))


def _validity(value, now, maximum):
    _integer(now)
    issued, expires = _integer(value['issued']), _integer(value['expires'])
    if not issued <= now < expires or expires - issued > maximum:
        raise ValueError('publisher_authority_expired')


def _scope(value):
    """Optional versioned publication scope carried by a device grant.

    Grants issued before this extension carry no scope and keep their original
    group-wide meaning. New grants must carry one, and a display enforces it
    independently of any server-side role or database record.
    """
    fields(value, 'version groups targets permissions')
    if type(value['version']) is not int or value['version'] != 1:
        raise ValueError('publisher_scope_refused')
    for name, maximum in (('groups', 64), ('targets', 64), ('permissions', 8)):
        items = value[name]
        if (not isinstance(items, list) or not items or len(items) > maximum or
                items != sorted(set(items))):
            raise ValueError('publisher_scope_refused')
    for item in value['groups']:
        text(item, 64)
    for item in value['targets']:
        text(item, 128)
    if any(item not in ('edit', 'publish') for item in value['permissions']):
        raise ValueError('publisher_scope_refused')
    if 'publish' not in value['permissions']:
        raise ValueError('publisher_scope_refused')
    return value


def _scope_allows(scope, plan):
    if scope is None:
        return True
    if plan['group_id'] not in scope['groups']:
        return False
    return all(target['device_id'] in scope['targets'] for target in plan['targets'])


def policy(envelope, root_spki, group_id, trusted_origin, now, *, floor=0):
    value = verified(envelope, root_spki, 'policy')
    fields(value, 'group_id origin version issued expires revoked_devices revoked_users')
    if value['group_id'] != text(group_id) or value['origin'] != origin(trusted_origin):
        raise ValueError('publisher_scope_refused')
    if _integer(value['version']) < _integer(floor, 0):
        raise ValueError('publisher_policy_rollback')
    _validity(value, now, MAX_AUTHORITY_SECONDS)
    for field in ('revoked_devices', 'revoked_users'):
        items = value[field]
        if not isinstance(items, list) or len(items) > 1024 or len(set(items)) != len(items):
            raise ValueError('publisher_revocation_refused')
        for item in items:
            (digest if field == 'revoked_devices' else text)(item)
    return value


def permission(chain, root_spki, current_policy, now):
    """One root grant, optionally one delegated child (same user, or another user
    when the parent is a scoped administrator). Children can never delegate."""
    if not isinstance(chain, list) or not 1 <= len(chain) <= 2:
        raise ValueError('publisher_delegation_depth')
    parent, signer = None, root_spki
    for index, envelope in enumerate(chain):
        value = verified(envelope, signer, 'device')
        names = 'group_id origin user_id role device_key issued expires can_delegate'
        if set(value) == set(names.split()) | {'scope'}:
            scope = _scope(value['scope'])
        elif set(value) == set(names.split()):
            scope = None
        else:
            raise ValueError('publisher_scope_refused')
        for name in ('group_id', 'user_id'):
            text(value[name])
        if (value['group_id'] != current_policy['group_id'] or
                value['origin'] != current_policy['origin'] or
                value['role'] not in ('administrator', 'user') or
                type(value['can_delegate']) is not bool):
            raise ValueError('publisher_scope_refused')
        _validity(value, now, MAX_AUTHORITY_SECONDS)
        signer = _b64(value['device_key'], 1024)
        # Reuse the native verifier's strict RSA3072 SPKI format validation.
        from kiosk.display.native_crypto import rsa_parameters
        rsa_parameters(signer)
        if (key_id(signer) in current_policy['revoked_devices'] or
                value['user_id'] in current_policy['revoked_users']):
            raise ValueError('publisher_revoked')
        if parent is not None:
            if (not parent['can_delegate'] or value['can_delegate'] or
                    any(value[k] != parent[k] for k in ('group_id', 'origin')) or
                    value['issued'] < parent['issued'] or value['expires'] > parent['expires'] or
                    value['device_key'] == parent['device_key']):
                raise ValueError('publisher_delegation_escalation')
            same_user = value['user_id'] == parent['user_id']
            if same_user:
                if value['role'] != parent['role']:
                    raise ValueError('publisher_delegation_escalation')
            else:
                # Only an administrator grant may enroll another account's device,
                # and the child can never widen a scoped parent.
                if parent['role'] != 'administrator':
                    raise ValueError('publisher_delegation_escalation')
                if value.get('scope') is None:
                    raise ValueError('publisher_delegation_escalation')
            if parent.get('scope') is not None and value.get('scope') is not None:
                if (not set(value['scope']['groups']) <= set(parent['scope']['groups']) or
                        not set(value['scope']['targets']) <= set(parent['scope']['targets']) or
                        not set(value['scope']['permissions']) <= set(parent['scope']['permissions'])):
                    raise ValueError('publisher_delegation_escalation')
        if index == 1 and value['can_delegate']:
            raise ValueError('publisher_delegation_depth')
        parent = value
    return parent, signer


def validate_plan(value, *, now):
    fields(value, 'id group_id origin user_id device_id policy_version issued expires '
           'publication_sha256 dependencies_sha256 renderer targets parents')
    digest(value['id'])
    for name in ('group_id', 'user_id'):
        text(value[name])
    for name in ('device_id', 'publication_sha256', 'dependencies_sha256', 'renderer'):
        digest(value[name])
    origin(value['origin'])
    _integer(value['policy_version'])
    _validity(value, now, MAX_PLAN_SECONDS)
    targets = value['targets']
    if not isinstance(targets, list) or not 1 <= len(targets) <= 100:
        raise ValueError('publisher_target_limit')
    identities = []
    for target in targets:
        fields(target, 'device_id profile_id profile_version mode configuration_sha256')
        identities.append(text(target['device_id']))
        text(target['profile_id'])
        _integer(target['profile_version'])
        digest(target['configuration_sha256'])
        if target['mode'] not in ('tv', 'kiosk'):
            raise ValueError('publisher_mode_refused')
    if identities != sorted(set(identities)):
        raise ValueError('publisher_target_ambiguity')
    parents = value['parents']
    if not isinstance(parents, list) or len(parents) > 32 or parents != sorted(set(parents)):
        raise ValueError('publisher_parent_limit')
    for item in parents:
        digest(item)
    # Identity binds every field except itself, not a server-controlled counter.
    if value['id'] != sha(encode({k: v for k, v in value.items() if k != 'id'})):
        raise ValueError('publisher_plan_identity')
    return value


def _page_inventory(group):
    fields(group, 'files')
    entries = group['files']
    if not isinstance(entries, list) or not 2 <= len(entries) <= 10001:
        raise ValueError('publisher_metadata_inventory')
    names = set()
    for entry in entries:
        fields(entry, 'path size sha256')
        name = entry['path']
        if not isinstance(name, str) or name.casefold() in names:
            raise ValueError('publisher_metadata_inventory')
        if type(entry['size']) is not int or not 0 <= entry['size'] <= MAX_PAGE_METADATA_FILE_BYTES:
            raise ValueError('publisher_metadata_inventory')
        digest(entry['sha256'])
        names.add(name.casefold())
    if any('/'.join(name.split('/')[:index]) in names
           for name in names for index in range(1, len(name.split('/')))):
        raise ValueError('publisher_metadata_inventory')
    manifest_entries = [entry for entry in entries if entry['path'] == 'manifest.json']
    if len(manifest_entries) != 1:
        raise ValueError('publisher_metadata_inventory')
    manifest_files = [entry for entry in entries if entry is not manifest_entries[0]]
    try:
        validate_manifest({'schema_version': 1, 'revision': 'page-metadata',
                           'renderer': 'events-v1', 'files': manifest_files})
    except (TypeError, ValueError):
        raise ValueError('publisher_metadata_inventory') from None


def validate_page_metadata(value):
    """Validate the v2 target metadata envelope and its closed inventories."""
    fields(value, 'version destination revision_sha256 content_sha256 publication')
    if (type(value['version']) is not int or value['version'] != PAGE_PLAN_VERSION
            or value['destination'] not in PAGE_DESTINATIONS):
        raise ValueError('publisher_metadata_destination')
    for name in ('revision_sha256', 'content_sha256'):
        digest(value[name])
    publication = value['publication']
    fields(publication, 'version package_id revision raw_manifest_sha256 renderer '
                        'resource_profile limits windows_images package kiosk tv')
    if type(publication['version']) is not int or publication['version'] != PAGE_PLAN_VERSION:
        raise ValueError('publisher_metadata_version')
    for name in ('package_id', 'raw_manifest_sha256'):
        digest(publication[name])
    digest(publication['revision'])
    renderer = publication['renderer']
    fields(renderer, 'build_id js_sha256 css_sha256')
    for name in ('build_id', 'js_sha256', 'css_sha256'):
        digest(renderer[name])
    if renderer['build_id'] != page_renderer_build_id(renderer['js_sha256'],
                                                      renderer['css_sha256']):
        raise ValueError('publisher_metadata_renderer')
    if publication['resource_profile'] != PROFILE or publication['limits'] != LIMITS:
        raise ValueError('publisher_metadata_profile')
    if publication['windows_images'] != {}:
        raise ValueError('publisher_metadata_inventory')
    _page_inventory(publication['package'])
    for name in ('kiosk', 'tv'):
        fields(publication[name], 'files')
        if publication[name]['files'] != []:
            raise ValueError('publisher_metadata_inventory')
    total = sum(entry['size'] for entry in publication['package']['files'])
    count = len(publication['package']['files'])
    if (total > MAX_PAGE_METADATA_BYTES or count > MAX_PAGE_METADATA_FILES
            or len(encode(value)) > MAX_METADATA_BYTES):
        raise ValueError('publisher_metadata_inventory')
    return publication


def validate_group_plan(value, *, now):
    """Validate one immutable v2 group revision for a page publication."""
    fields(value, 'version id group_id origin user_id device_id policy_version issued expires '
                  'revision_sha256 dependencies_sha256 targets parents')
    if type(value['version']) is not int or value['version'] != PAGE_PLAN_VERSION:
        raise ValueError('publisher_plan_version')
    digest(value['id'])
    for name in ('group_id', 'user_id'):
        text(value[name])
    for name in ('device_id', 'revision_sha256', 'dependencies_sha256'):
        digest(value[name])
    origin(value['origin'])
    _integer(value['policy_version'])
    _validity(value, now, MAX_PLAN_SECONDS)
    targets = value['targets']
    if not isinstance(targets, list) or not 1 <= len(targets) <= 100:
        raise ValueError('publisher_target_limit')
    identities = []
    for target in targets:
        fields(target, 'device_id profile_id profile_version mode configuration_sha256 '
                       'projection destination renderer metadata_sha256')
        identities.append(text(target['device_id']))
        text(target['profile_id'])
        _integer(target['profile_version'])
        if target['mode'] not in ('tv', 'kiosk'):
            raise ValueError('publisher_mode_refused')
        if target['projection'] not in PAGE_PROJECTIONS:
            raise ValueError('publisher_projection_refused')
        if target['projection'].split('-', 1)[0] != target['mode']:
            raise ValueError('publisher_projection_refused')
        if target['destination'] not in PAGE_DESTINATIONS:
            raise ValueError('publisher_metadata_destination')
        for name in ('configuration_sha256', 'renderer', 'metadata_sha256'):
            digest(target[name])
    if identities != sorted(set(identities)):
        raise ValueError('publisher_target_ambiguity')
    parents = value['parents']
    if not isinstance(parents, list) or len(parents) > 32 or parents != sorted(set(parents)):
        raise ValueError('publisher_parent_limit')
    for item in parents:
        digest(item)
    # The v2 domain and explicit version make the changed binding unambiguous.
    if value['id'] != sha(PAGE_PLAN_DOMAIN + encode(
            {k: v for k, v in value.items() if k != 'id'})):
        raise ValueError('publisher_plan_identity')
    return value


def _validate_ancestry_record(value, now, plan_version):
    if plan_version == PAGE_PLAN_VERSION:
        if not isinstance(value, dict) or value.get('version') != PAGE_PLAN_VERSION:
            raise ValueError('publisher_ancestry_version')
        return validate_group_plan(value, now=now)
    return validate_plan(value, now=now)


def check_ancestry(plan, known_heads=(), ancestry=()):
    """Follow hash commitments, never server sequence numbers or asserted edges.

    The current authorized signature commits to each parent's entire plan hash;
    that plan commits to its parents transitively. Intermediate plans are proofs
    of ancestry only, not admission permissions. Their expired/revoked signers
    cannot authorize this publication: current approval is verified separately.
    No historical private key, re-signing or grandfathered authority is needed.
    """
    if not isinstance(known_heads, (list, tuple)) or len(known_heads)>32:
        raise ValueError('publisher_known_head_limit')
    known=set(digest(item) for item in known_heads)
    if ancestry == ():
        ancestry=[]
    if (not isinstance(ancestry,list) or len(ancestry)>MAX_ANCESTRY_NODES or
            len(encode({'nodes':ancestry}))>MAX_ANCESTRY_BYTES):
        raise ValueError('publisher_ancestry_limit')
    nodes={}
    for item in ancestry:
        # Validate framing/hash/scope without requiring historical admission now.
        if not isinstance(item,dict):
            raise ValueError('publisher_ancestry_refused')
        _validate_ancestry_record(item, now=_integer(item.get('issued')),
                                  plan_version=plan.get('version', 1))
        if (item['id'] in nodes or item['id']==plan['id'] or
                item['group_id']!=plan['group_id'] or item['origin']!=plan['origin'] or
                item['issued']>plan['issued']):
            raise ValueError('publisher_ancestry_refused')
        nodes[item['id']]=item
    reached={plan['id']}
    pending=list(plan['parents'])
    missing=False
    while pending:
        identity=pending.pop()
        if identity in reached:
            continue
        reached.add(identity)
        if identity in nodes:
            pending.extend(nodes[identity]['parents'])
        elif identity not in known:
            missing=True
    if not known.issubset(reached):
        raise ValueError('publisher_ancestry_required' if missing else 'publisher_known_conflict')


def page_approval(envelope, chain, policy_envelope, root_spki, group_id, trusted_origin,
                  now, *, policy_floor=0, known_heads=(), ancestry=()):
    """Authorize one v2 group revision without changing the v1 approval path."""
    current = policy(policy_envelope, root_spki, group_id, trusted_origin, now, floor=policy_floor)
    device, signer = permission(chain, root_spki, current, now)
    plan = validate_group_plan(page_verified(envelope, signer), now=now)
    if (plan['group_id'] != group_id or plan['origin'] != trusted_origin or
            plan['user_id'] != device['user_id'] or plan['device_id'] != key_id(signer) or
            plan['policy_version'] != current['version'] or
            plan['issued'] < device['issued'] or plan['expires'] > device['expires']):
        raise ValueError('publisher_approval_scope')
    if not _scope_allows(device.get('scope'), plan):
        raise ValueError('publisher_scope_refused')
    check_ancestry(plan, known_heads, ancestry)
    return plan, current


def page_assignment(proof, value, root_spki, trusted_origin, now, *, policy_floor=0,
                    known_heads=()):
    """Check one target's exact v2 metadata, configuration and signed release."""
    fields(proof, 'approval chain policy'+(' ancestry' if 'ancestry' in proof else ''))
    fields(value, 'version group_id device_id profile generation revision_sha256 destination '
                  'projection metadata_sha256 metadata display publisher')
    if value['publisher'] != proof:
        raise ValueError('publisher_proof_substitution')
    plan, current = page_approval(proof['approval'], proof['chain'], proof['policy'], root_spki,
                                  value['group_id'], trusted_origin, now,
                                  policy_floor=policy_floor, known_heads=known_heads,
                                  ancestry=proof.get('ancestry', []))
    if type(value['version']) is not int or value['version'] != PAGE_ASSIGNMENT_VERSION:
        raise ValueError('publisher_assignment_version')
    text(value['group_id'])
    text(value['device_id'])
    text(value['profile'], 64)
    _integer(value['generation'])
    digest(value['revision_sha256'])
    digest(value['metadata_sha256'])
    if value['destination'] not in PAGE_DESTINATIONS or value['projection'] not in PAGE_PROJECTIONS:
        raise ValueError('publisher_target_not_approved')
    metadata = value['metadata']
    publication = validate_page_metadata(metadata)
    if (value['group_id'] != plan['group_id'] or
            value['revision_sha256'] != plan['revision_sha256'] or
            value['metadata_sha256'] != sha(encode(metadata))):
        raise ValueError('publisher_content_substitution')
    if value['profile'] != publication['resource_profile']:
        raise ValueError('publisher_configuration_substitution')
    matches = [target for target in plan['targets'] if target['device_id'] == value['device_id']]
    if len(matches) != 1:
        raise ValueError('publisher_target_not_approved')
    target = matches[0]
    if (target['destination'] != value['destination'] or
            target['projection'] != value['projection'] or
            target['metadata_sha256'] != value['metadata_sha256']):
        raise ValueError('publisher_target_substitution')
    if (metadata['revision_sha256'] != plan['revision_sha256'] or
            metadata['destination'] != target['destination'] or
            publication['revision'] != plan['revision_sha256']):
        raise ValueError('publisher_content_substitution')
    if publication['renderer']['build_id'] != target['renderer']:
        raise ValueError('publisher_renderer_substitution')
    display = value['display']
    fields(display, 'version profile_id revision mode')
    if (type(display['version']) is not int or display['version'] != 1 or
            type(display['revision']) is not int or display['revision'] <= 0 or
            display['mode'] not in ('tv', 'kiosk')):
        raise ValueError('publisher_configuration_substitution')
    text(display['profile_id'], 64)
    if (target['profile_id'] != display['profile_id'] or
            target['profile_version'] != display['revision'] or
            target['mode'] != display['mode'] or
            target['configuration_sha256'] != sha(encode(display)) or
            target['projection'].split('-', 1)[0] != display['mode']):
        raise ValueError('publisher_configuration_substitution')
    return plan, target, current


def approval(envelope, chain, policy_envelope, root_spki, group_id, trusted_origin,
             now, *, policy_floor=0, known_heads=(), ancestry=()):
    current = policy(policy_envelope, root_spki, group_id, trusted_origin, now, floor=policy_floor)
    device, signer = permission(chain, root_spki, current, now)
    plan = validate_plan(verified(envelope, signer, 'publication'), now=now)
    if (plan['group_id'] != group_id or plan['origin'] != trusted_origin or
            plan['user_id'] != device['user_id'] or plan['device_id'] != key_id(signer) or
            plan['policy_version'] != current['version'] or
            plan['issued'] < device['issued'] or plan['expires'] > device['expires']):
        raise ValueError('publisher_approval_scope')
    # A signed scope narrows exactly which group/targets this signer may approve.
    if not _scope_allows(device.get('scope'), plan):
        raise ValueError('publisher_scope_refused')
    # A fresh display has no omniscient head. Withheld branches cannot be detected
    # until authenticated. A known conflicting branch requires an explicit merge
    # approval referencing all known heads; a server sequence cannot override it.
    check_ancestry(plan,known_heads,ancestry)
    return plan, current


def assignment(proof, value, root_spki, trusted_origin, now, *, policy_floor=0, known_heads=()):
    """Check actual delivery bytes and this exact display's configuration."""
    fields(proof, 'approval chain policy'+(' ancestry' if 'ancestry' in proof else ''))
    plan, current = approval(proof['approval'], proof['chain'], proof['policy'], root_spki,
                             value['group_id'], trusted_origin, now,
                             policy_floor=policy_floor, known_heads=known_heads,
                             ancestry=proof.get('ancestry',[]))
    publication=value['publication']
    if (sha(encode(publication))!=plan['publication_sha256'] or
            publication['renderer']['build_id']!=plan['renderer']):
        raise ValueError('publisher_content_substitution')
    matches=[t for t in plan['targets'] if t['device_id']==value['device_id']]
    if len(matches)!=1:
        raise ValueError('publisher_target_not_approved')
    target=matches[0]
    display=value['display']
    if (target['profile_id']!=display['profile_id'] or target['profile_version']!=display['revision'] or
            target['mode']!=display['mode'] or target['configuration_sha256']!=sha(encode(display))):
        raise ValueError('publisher_configuration_substitution')
    return plan, current
