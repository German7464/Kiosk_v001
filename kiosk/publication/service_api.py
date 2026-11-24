"""Authenticated content-service contract consumed by the Maintenance service.

Only the trusted Maintenance side calls these routes. Every request is bound to
this exact HTTPS origin, the service identity, a body digest, a timestamp and a
single-use nonce; the same contract is used for Combined and Separated placement
so a localhost arrangement gets no trust shortcut. The content service never
receives a reviewer private key and never signs a publication.
"""
from __future__ import annotations

import hashlib
import hmac
import time
import threading
from functools import wraps

from flask import Blueprint, current_app, jsonify, request

from kiosk.delivery.protocol import DeliveryError, PROFILE, decode, encode, fields, sha
from .workspace import WorkspaceError

service = Blueprint('content_service', __name__, url_prefix='/service/v1')

MAX_BODY = 6 * 1024 * 1024
CLOCK_SKEW_SECONDS = 60
_authority_lock = threading.RLock()


def serialized_authority(function):
    @wraps(function)
    def call(*args, **kwargs):
        with _authority_lock:
            return function(*args, **kwargs)
    return call


def store():
    return current_app.extensions['roaming_workspace']


def delivery():
    state = current_app.extensions.get('device_delivery')
    if state is None:
        raise WorkspaceError('delivery_unavailable', 503)
    return state


def service_config():
    config = current_app.config.get('MAINTENANCE_SERVICE')
    if not isinstance(config, dict) or not config.get('secret') or not config.get('service_id'):
        raise WorkspaceError('service_not_configured', 503)
    return config


def body():
    if request.mimetype != 'application/json':
        raise WorkspaceError('json_required', 415)
    raw = request.get_data(cache=True)
    if len(raw) > MAX_BODY:
        raise WorkspaceError('request_limit', 413)
    return decode(raw), raw


def authenticate():
    """Verify the trusted service request; messages contain no supplied bytes."""
    config = service_config()
    if not request.is_secure or request.host_url.rstrip('/') != store().origin:
        raise WorkspaceError('trusted_https_origin_required', 403)
    identity = request.headers.get('X-Kiosk-Service-Id', '')
    stamp = request.headers.get('X-Kiosk-Time', '')
    nonce = request.headers.get('X-Kiosk-Nonce', '')
    body_sha = request.headers.get('X-Kiosk-Body-SHA256', '')
    signature = request.headers.get('X-Kiosk-Signature', '')
    if identity != config['service_id'] or not isinstance(nonce, str) or len(nonce) != 64:
        raise WorkspaceError('service_identity_refused', 403)
    if not (stamp.isascii() and stamp.isdecimal()):
        raise WorkspaceError('service_identity_refused', 403)
    now = store().now()
    if abs(now - int(stamp)) > CLOCK_SKEW_SECONDS:
        raise WorkspaceError('service_time_refused', 403)
    raw = request.get_data(cache=True)
    try:
        digest = hashlib.sha256(raw).hexdigest()
    except Exception:
        raise WorkspaceError('service_identity_refused', 403) from None
    if not hmac.compare_digest(digest, body_sha):
        raise WorkspaceError('service_body_refused', 403)
    message = '\n'.join((identity, request.method, request.path, stamp, nonce, digest))
    expected = hmac.new(str(config['secret']).encode('utf-8'), message.encode('utf-8'),
                        hashlib.sha256).hexdigest()
    if not (len(signature) == 64 and signature.isascii() and
            hmac.compare_digest(expected, signature)):
        raise WorkspaceError('service_signature_refused', 403)
    store().remember_nonce(nonce, now)
    return config


def guarded(function):
    @wraps(function)
    def call(*args, **kwargs):
        try:
            authenticate()
            if request.endpoint != 'content_service.activate':
                require_active()
            response = current_app.make_response(function(*args, **kwargs))
        except WorkspaceError as error:
            response = jsonify(version=1, error=error.code)
            response.status_code = error.status
        except DeliveryError as error:
            response = jsonify(version=1, error=error.code)
            response.status_code = error.status
        except (OSError, KeyError, ValueError, TypeError):
            current_app.logger.exception('content service request failed')
            response = jsonify(version=1, error='content_service_unavailable')
            response.status_code = 503
        response.headers['Cache-Control'] = 'no-store'
        response.headers['X-Content-Type-Options'] = 'nosniff'
        return response
    return call


def require_active():
    placement = store().placement()
    if placement is not None and store().fenced():
        raise WorkspaceError('service_fenced', 409)


@service.post('/tls-authority')
@guarded
@serialized_authority
def tls_authority():
    from kiosk.maintenance.tls_binding import accept
    value, _ = body()
    origin = accept(current_app, value)
    return jsonify(version=1, installed=True, origin=origin)


@service.post('/authority')
@guarded
@serialized_authority
def import_authority():
    """Install public renewals only after independent signature/scope validation.

    Replays are safe: policy and GroupTrust are monotonic and exact retries are
    accepted. A crash between the two stores leaves the durable sender pending.
    """
    import base64
    from kiosk.trust.lifecycle import verify_group_window
    from kiosk.publication.store import _atomic_write
    value, _ = body()
    fields(value, 'policy' + (' trust' if isinstance(value, dict) and 'trust' in value else ''))
    replacement = None
    if 'trust' in value:
        state = delivery()
        replacement = state.configuration()
        root = base64.b64decode(replacement['bootstrap']['group_spki_base64'], validate=True)
        old = verify_group_window(replacement['trust'], root)
        new = verify_group_window(value['trust'], root)
        if (new['group_id'] != old['group_id'] or new['servers'] != old['servers']
                or new['generation'] < old['generation']
                or not new['issued_at'] <= store().now() < new['expires_at']
                or (new['generation'] == old['generation'] and encode(value['trust']) != encode(replacement['trust']))):
            raise WorkspaceError('lan_authority_refused', 409)
        replacement['trust'] = value['trust']
        # Enrollment invitation retains the independently pinned roots/identity.
        # Only its time window follows this verified same-root GroupTrust.
        replacement['bootstrap'] = dict(replacement['bootstrap'], issued_at=new['issued_at'], expires_at=new['expires_at'])
    store().install_policy(value['policy'])
    if replacement is not None:
        _atomic_write(delivery().root / 'public.json', encode(replacement))
    return jsonify(version=1, installed=True)


def session():
    value, _ = body()
    fields(value, 'secret')
    store().authenticate(value['secret'])
    return value['secret']


@service.post('/session')
@guarded
def create_session():
    value, _ = body()
    fields(value, 'user_id chain')
    secret = store().create_service_session(value['user_id'], value['chain'])
    return jsonify(version=1, secret=secret)


@service.get('/targets')
@guarded
def targets():
    secret = request.headers.get('X-Kiosk-Content-Session', '')
    store().authenticate(secret)
    from kiosk.display.cache import renderer_identity
    return jsonify(version=1, targets=delivery().publisher_targets(renderer_identity()))


@service.get('/drafts')
@guarded
def drafts():
    secret = request.headers.get('X-Kiosk-Content-Session', '')
    return jsonify(version=1, objects=store().objects(secret),
                   settings=store().settings(secret))


@service.post('/draft')
@guarded
def save_draft():
    value, _ = body()
    fields(value, 'secret identity expected_version payload dependencies')
    version = store().save(value['secret'], value['identity'], value['expected_version'],
                           value['payload'], value['dependencies'])
    return jsonify(version=1, version_number=version)


@service.post('/draft/ready')
@guarded
def ready_draft():
    value, _ = body()
    fields(value, 'secret identity version')
    store().ready(value['secret'], value['identity'], value['version'])
    return jsonify(version=1, state='ready')


@service.post('/settings')
@guarded
def save_settings():
    value, _ = body()
    fields(value, 'secret expected_version values')
    version = store().update_settings(value['secret'], value['expected_version'],
                                      value['values'])
    return jsonify(version=1, version_number=version)


@service.post('/prepare')
@guarded
def prepare():
    value, _ = body()
    fields(value, 'secret selected targets parents')
    from .materialize import prepare_publication
    from kiosk.display.cache import renderer_identity
    state = delivery()
    current = state.publisher_targets(renderer_identity())
    if value['targets'] != current:
        raise WorkspaceError('publisher_targets_changed', 409)
    document = prepare_publication(store(), value['secret'], value['selected'],
                                   value['targets'], value['parents'], state,
                                   current_app.config['PUBLIC_UPLOAD_DIR'],
                                   current_app.config['RESOURCE_DIR'] / 'kiosk')
    plan = document['plan']
    return jsonify(version=1, id=plan['id'], plan=plan,
                   package_id=document['publication']['package_id'],
                   revision=document['content_version'],
                   user=plan['user_id'], expires=plan['expires'],
                   document=document)


@service.get('/candidate/<identity>')
@guarded
def candidate(identity):
    return jsonify(version=1, document=store().candidate(identity))


def require_acceptance(document, receipt, approval):
    """Verify the trusted side's automatic acceptance evidence before storing it."""
    configured = current_app.config.get('MAINTENANCE_ACCEPTANCE_KEY')
    if not configured:
        raise WorkspaceError('acceptance_not_configured', 503)
    import base64
    import hashlib
    from kiosk.delivery.protocol import encode as canonical
    from kiosk.publication import authority as publication
    spki = base64.b64decode(configured)
    try:
        value = publication.verified(receipt, spki, 'acceptance')
        fields(value, 'version plan_id publication_sha256 dependencies_sha256 targets_sha256 '
                      'approver_user approver_device policy_version approval_sha256 '
                      'commit_nonce issued')
    except (ValueError, KeyError, TypeError):
        raise WorkspaceError('acceptance_receipt_refused', 403) from None
    plan = document['plan']
    if (value['version'] != 1 or value['plan_id'] != plan['id'] or
            value['publication_sha256'] != plan['publication_sha256'] or
            value['dependencies_sha256'] != plan['dependencies_sha256'] or
            value['targets_sha256'] != sha(canonical(plan['targets'])) or
            value['approver_user'] != plan['user_id'] or
            value['approver_device'] != plan['device_id'] or
            value['policy_version'] != plan['policy_version'] or
            value['approval_sha256'] != hashlib.sha256(canonical(approval)).hexdigest()):
        raise WorkspaceError('acceptance_receipt_refused', 403)
    return value


@service.post('/approve')
@guarded
def approve():
    value, _ = body()
    fields(value, 'id approval chain receipt acceptance_key')
    document = store().approve(value['id'], value['approval'], value['chain'])
    require_acceptance(document, value['receipt'], value['approval'])
    configured = current_app.config.get('MAINTENANCE_ACCEPTANCE_KEY', '')
    if value['acceptance_key'] != configured:
        raise WorkspaceError('acceptance_key_mismatch', 403)
    from .distribution import promote
    result = promote(store(), delivery(), value['id'], store().now(),
                     receipt=value['receipt'], acceptance_key=value['acceptance_key'])
    return jsonify(version=1, state='ready', distribution=result,
                   plan_id=document['plan']['id'])


@service.get('/status/<identity>')
@guarded
def status(identity):
    secret = request.headers.get('X-Kiosk-Content-Session', '')
    store().authenticate(secret)
    placement = store().placement()
    state = store().plan_state(identity)
    document = store().candidate(identity)
    distribution = delivery().publisher_distribution(document['plan']['publication_sha256'])
    return jsonify(version=1, approved=state['approved'], distribution=distribution,
                   placement=placement)


@service.get('/history')
@guarded
def history():
    secret = request.headers.get('X-Kiosk-Content-Session', '')
    store().authenticate(secret)
    return jsonify(version=1, history=store().history(),
                   preserve=store().preserve_report())


@service.get('/manifest')
@guarded
def manifest():
    """Logical state identity used to verify a relocation transfer."""
    with store().db() as db:
        counts = {name: db.execute('SELECT COUNT(*) FROM ' + name).fetchone()[0]
                  for name in ('objects', 'revisions', 'plans', 'heads', 'staged')}
        sequence = db.execute('SELECT content FROM sequence').fetchone()
        policy = db.execute('SELECT version FROM policy').fetchone()
    placements = store().placement()
    state = delivery()
    with state.connection(write=False) as db:
        delivered = {name: db.execute('SELECT COUNT(*) FROM ' + name).fetchone()[0]
                     for name in ('assignments', 'assignment_history', 'assignment_targets',
                                  'publisher_proofs', 'acceptance_receipts', 'devices', 'receipts')}
        row = db.execute('SELECT generation FROM assignments WHERE profile=?', (PROFILE,)).fetchone()
        generation = row['generation'] if row else None
    value = dict(version=1, counts=counts, delivered=delivered,
                 sequence=sequence['content'] if sequence else 0,
                 policy=policy['version'] if policy else 0,
                 assignment_generation=generation,
                 placement=placements, history=[item['id'] for item in store().history(500)])
    value['digest'] = sha(encode(value))
    return jsonify(version=1, manifest=value)


@service.post('/fence')
@guarded
def fence():
    value, _ = body()
    fields(value, 'reason')
    reason = value['reason']
    if not isinstance(reason, str) or not 1 <= len(reason) <= 64:
        raise WorkspaceError('placement_reason_refused')
    token = store().fence(reason)
    return jsonify(version=1, state='fenced', fence=token)


@service.post('/activate')
@guarded
def activate():
    value, _ = body()
    fields(value, 'generation fence origin')
    store().activate(value['generation'], value['fence'], value['origin'])
    return jsonify(version=1, state='active', generation=value['generation'])


def register(app):
    if app.config.get('MAINTENANCE_SERVICE') is None:
        return
    app.register_blueprint(service)
