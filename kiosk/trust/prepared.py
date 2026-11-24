"""Automatic selection of offline-signed, bounded same-issuer trust windows.

No signing key or new delegation scope is introduced online. Preparation is a
setup operation; it cannot extend the issuer/delegation/root horizon. Exhaustion
is explicit and never affects previously accepted offline content.
"""
import base64
import json
from pathlib import Path
from cryptography.hazmat.primitives import serialization
from kiosk.trust.crypto import cert_not_after_utc, load_private
from kiosk.trust.recovery import group_trust_envelope, verify_envelope, RecoveryError

MAX_PLAN_BYTES = 128 * 1024


def prepare(root, password, now):
    root = Path(root)
    from tools.lan_trust_admin import _envelope, _atomic_replace
    group = load_private((root / 'admin-private/group-key.pem').read_text(), password)
    current = verify_envelope(_envelope(root), group)
    delegation = json.loads((root / 'server/delegation.json').read_text())
    horizon = min(delegation['expires_at'],
                  cert_not_after_utc((root / 'server/intermediate.pem').read_text()),
                  cert_not_after_utc((root / 'public/root-ca.pem').read_text()))
    if len(current['servers']) != 1:
        raise RecoveryError('prepared_target_refused')
    server = current['servers'][0]
    if (server['tls_issuer_spki_sha256'] != delegation['issuer_key_id']
            or current['group_id'] != delegation['group_id']
            or server['server_id'] != delegation['server_id'] or server['origin'] != delegation['origin']
            or server['roles'] != ['publisher']):
        raise RecoveryError('prepared_target_refused')
    # Seven-day authority, advanced five days apart; no indefinite renewal.
    start = max(now, current['expires_at'] - 2 * 86400)
    generation = current['generation']
    envelopes = []
    while start < horizon:
        if len(envelopes) >= 64:
            raise RecoveryError('prepared_horizon_too_large')
        generation += 1
        envelopes.append(group_trust_envelope(group, group_id=current['group_id'],
            server_id=server['server_id'], origin=server['origin'],
            issuer_spki_sha256=delegation['issuer_key_id'], generation=generation,
            issued_at=start, expires_at=min(start + 7 * 86400, horizon)))
        start += 5 * 86400
    if not envelopes:
        raise RecoveryError('prepared_authority_exhausted_or_already_longer')
    plan = {'version': 1, 'horizon': horizon, 'envelopes': envelopes}
    raw = json.dumps(plan)
    if len(raw.encode()) > MAX_PLAN_BYTES:
        raise RecoveryError('prepared_plan_too_large')
    _atomic_replace(root / 'server/prepared-trust.json', raw)
    return {'status': 'prepared', 'windows': len(envelopes), 'horizon': horizon,
            'online_signing_keys_added': False}


def advance(root, now):
    root = Path(root)
    path = root / 'server/prepared-trust.json'
    if not path.exists():
        return 'not_configured'
    from tools.lan_trust_admin import _envelope, _atomic_replace
    from kiosk.trust.state import LifecycleState
    with path.open('rb') as stream:
        raw = stream.read(MAX_PLAN_BYTES + 1)
    if len(raw) > MAX_PLAN_BYTES:
        raise RecoveryError('prepared_plan_too_large')
    plan = json.loads(raw)
    if (not isinstance(plan, dict) or plan.get('version') != 1
            or not isinstance(plan.get('envelopes'), list) or not 1 <= len(plan['envelopes']) <= 64):
        raise RecoveryError('prepared_plan_invalid')
    bootstrap = json.loads((root / 'public/bootstrap.json').read_text())
    group = serialization.load_der_public_key(base64.b64decode(bootstrap['group_spki_base64'], validate=True))
    current_envelope = _envelope(root)
    current = verify_envelope(current_envelope, group)
    delegation = json.loads((root / 'server/delegation.json').read_text())
    horizon = min(delegation['expires_at'],
                  cert_not_after_utc((root / 'server/intermediate.pem').read_text()),
                  cert_not_after_utc((root / 'public/root-ca.pem').read_text()))
    if (current['group_id'] != bootstrap['group_id'] or len(current['servers']) != 1
            or current['servers'][0] != {'server_id': bootstrap['server_id'], 'origin': bootstrap['origin'],
                'tls_issuer_spki_sha256': delegation['issuer_key_id'], 'roles': ['publisher']}):
        raise RecoveryError('prepared_target_refused')
    lifecycle = LifecycleState(root / 'state')
    with lifecycle.connection() as db:
        lifecycle.checked_now(db, now)
    selected, selected_payload = current_envelope, current
    previous_generation = -1
    for envelope in plan['envelopes']:
        payload = verify_envelope(envelope, group)
        if (payload['group_id'] != current['group_id'] or payload['servers'] != current['servers']
                or type(payload['generation']) is not int or payload['generation'] <= previous_generation
                or type(payload['issued_at']) is not int or type(payload['expires_at']) is not int
                or not 0 < payload['expires_at'] - payload['issued_at'] <= 7 * 86400
                or payload['expires_at'] > horizon):
            raise RecoveryError('prepared_window_refused')
        previous_generation = payload['generation']
        if payload['generation'] == current['generation'] and envelope != current_envelope:
            raise RecoveryError('prepared_generation_conflict')
        if (payload['issued_at'] <= now < payload['expires_at']
                and payload['generation'] > selected_payload['generation']):
            selected, selected_payload = envelope, payload
    if selected_payload['generation'] > current['generation']:
        public = root / 'server/public.json'
        config = json.loads(public.read_text())
        config['trust'] = selected
        _atomic_replace(public, json.dumps(config, indent=2) + '\n')
        _atomic_replace(root / 'public/trust.json', json.dumps(selected, indent=2) + '\n')
        return 'advanced'
    return 'exhausted' if now >= current['expires_at'] else 'current'
