"""Content-side durable binding to a relocated, root-delegated LAN TLS issuer."""
import base64
from urllib.parse import urlsplit

from kiosk.delivery.protocol import decode, encode, fields
from kiosk.publication.store import _atomic_write
from kiosk.publication.workspace import WorkspaceError
from kiosk.trust.lifecycle import delegation_from_payload
from kiosk.trust.roles import verify_delegation


def validate(app, value):
    fields(value, 'generation delegation')
    if type(value['generation']) is not int or value['generation'] < 1:
        raise WorkspaceError('tls_authority_generation_refused', 409)
    state = app.extensions['device_delivery']
    public = state.configuration()
    envelope = value['delegation']; fields(envelope, 'payload signature')
    delegated = delegation_from_payload(envelope['payload'])
    root = base64.b64decode(public['bootstrap']['group_spki_base64'], validate=True)
    verify_delegation(root, delegated, base64.b64decode(envelope['signature'], validate=True))
    from kiosk.trust.lifecycle import verify_group_window
    trust = verify_group_window(public['trust'], root)
    now = app.extensions['roaming_workspace'].now()
    if (delegated.group_id != public['group_id'] or delegated.server_id != public['server_id']+'-maintenance'
            or delegated.issuer_key_id != trust['servers'][0]['tls_issuer_spki_sha256']
            or delegated.scopes != ('issue_tls_leaf',) or delegated.max_tls_validity_days != 7
            or delegated.permitted_dns or delegated.permitted_ip != (urlsplit(delegated.origin).hostname,)
            or not delegated.issued_at <= now < delegated.expires_at
            or delegated.expires_at - delegated.issued_at > 111*86400):
        raise WorkspaceError('tls_authority_scope_refused', 403)
    return delegated.origin


def accept(app, value):
    origin = validate(app, value)
    path = app.extensions['device_delivery'].root / 'tls-authority.json'
    if path.exists():
        previous = decode(path.read_bytes())
        older = previous['delegation']['payload']
        current = value['delegation']['payload']
        same = value['generation'] == previous['generation']
        if (value['generation'] < previous['generation'] or current['issued_at'] < older['issued_at']
                or (same and encode(value) != encode(previous)
                    and (origin != older['origin'] or current['issued_at'] <= older['issued_at']
                         or current['expires_at'] <= older['expires_at']))):
            raise WorkspaceError('tls_authority_rollback', 409)
    elif value['generation'] <= 1 and origin != app.config['TLS_RENEWAL']['authority_origin']:
        raise WorkspaceError('tls_authority_rollback', 409)
    _atomic_write(path, encode(value))
    return origin


def current_origin(app, configured):
    path = app.extensions['device_delivery'].root / 'tls-authority.json'
    return validate(app, decode(path.read_bytes())) if path.exists() else configured
