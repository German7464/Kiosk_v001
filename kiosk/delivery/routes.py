"""Native-only JSON API and existing-session/CSRF protected admin operations."""
from functools import wraps

from flask import Blueprint, current_app, jsonify, request

from kiosk.core.request_security import AuthenticationLimiter
from kiosk.features.admin.routes import admin_required
from kiosk.publication.exporter import _plain_path
from .protocol import DeliveryError, PROFILE, decode, digest, encode, fields, sha

device_delivery = Blueprint('device_delivery', __name__, url_prefix='/api/v2')


def state():
    return current_app.extensions['device_delivery']


def guarded(function):
    @wraps(function)
    def call(*args, **kwargs):
        try:
            if not request.is_secure:
                raise DeliveryError('https_required', 403)
            response = current_app.make_response(function(*args, **kwargs))
        except DeliveryError as error:
            response = jsonify(version=1, error=error.code)
            response.status_code = error.status
        except (OSError, KeyError, ValueError):
            response = jsonify(version=1, error='delivery_unavailable')
            response.status_code = 503
        response.headers.setdefault('Cache-Control', 'no-store')
        response.headers['X-Content-Type-Options'] = 'nosniff'
        if response.status_code == 429:
            response.headers['Retry-After'] = '5'
        return response
    return call


def body():
    if request.mimetype != 'application/json':
        raise DeliveryError('json_required', 415)
    # Bound chunked bodies independently of Content-Length.
    from .protocol import MAX_METADATA_BYTES
    payload = request.stream.read(MAX_METADATA_BYTES + 1)
    return decode(payload)


def device():
    header = request.headers.get('Authorization', '')
    if not header.startswith('Bearer '):
        raise DeliveryError('invalid_credential', 401)
    secret = header[7:]
    try:
        digest(secret)
    except DeliveryError:
        raise DeliveryError('invalid_credential', 401) from None
    return state().authenticate(secret)


@device_delivery.before_request
def throttle():
    limiter = current_app.extensions.get('device_delivery_limiter')
    if limiter is None:
        # Created once at configuration; this branch is not an authority fallback.
        raise RuntimeError('delivery limiter not configured')
    wait = limiter.reserve(request.remote_addr or 'unknown', request.endpoint or 'unknown')
    if wait:
        response = jsonify(version=1, error='request_limit')
        response.status_code = 429
        response.headers['Retry-After'] = str(wait)
        response.headers['Cache-Control'] = 'no-store'
        return response


@device_delivery.post('/device/authorize')
@guarded
def authorize():
    return jsonify(state().begin(body()))


@device_delivery.post('/device/token')
@guarded
def token():
    result = state().poll(body())
    return jsonify(result), 202 if result['state'] == 'pending' else 200


@device_delivery.get('/client/status')
@guarded
def status():
    return jsonify(state()._device(device()))


@device_delivery.get('/group/trust')
@guarded
def trust():
    device()
    return jsonify(state().configuration()['trust'])


@device_delivery.get('/client/assignment')
@guarded
def assignment():
    return jsonify(state().assignment(device(), request.args.get('renderer'), request.args.get('resource_profile')))


@device_delivery.get('/publications/<package_id>/<group>/<path:name>')
@guarded
def artifact(package_id, group, name):
    owner = device()
    digest(package_id)
    if group not in ('package', 'kiosk', 'tv'):
        raise DeliveryError('file_not_found', 404)
    # Artifact fetches are restricted to the current assignment, not any known hash.
    with state().connection() as db:
        row = db.execute('SELECT * FROM assignments WHERE profile=? AND package_id=?', (owner['profile'], package_id)).fetchone()
    if row is None:
        raise DeliveryError('assignment_changed', 409)
    root = state().root / 'publications' / package_id
    payload = (root / 'delivery.json').read_bytes()
    if sha(payload) != row['metadata_hash']:
        raise DeliveryError('publication_integrity', 503)
    metadata = decode(payload)
    entry = next((item for item in metadata[group]['files'] if item['path'] == name), None)
    if entry is None:
        raise DeliveryError('file_not_found', 404)
    return current_app.extensions['device_delivery_transfers'].response(
        _plain_path(root / group, name), entry)


@device_delivery.post('/client/receipts')
@guarded
def receipt():
    return jsonify(state().receipt(device(), body()))


def register_admin_routes(app):
    # The admin.* endpoint prefix makes the existing CSRF before_request apply.
    app.extensions['device_delivery_limiter'] = AuthenticationLimiter(account_limit=1200, source_limit=2400)

    @app.get('/admin/devices/bootstrap', endpoint='admin.delivery_bootstrap')
    @admin_required
    @guarded
    def bootstrap():
        return jsonify(state().configuration()['bootstrap'])

    @app.get('/admin/devices/pending', endpoint='admin.delivery_pending')
    @admin_required
    @guarded
    def pending():
        rows = state().pending()
        for row in rows:
            row['binding_sha256'] = sha(encode(row['binding']))
            # The admin compares device/group/profile/origin, not the verifier.
            del row['binding']['secret_verifier']
        return jsonify(version=1, requests=rows)

    @app.post('/admin/devices/<request_id>/decision', endpoint='admin.delivery_decision')
    @admin_required
    @guarded
    def decision(request_id):
        return jsonify(state().approve(request_id, body()))

    @app.post('/admin/devices/<device_id>/revoke', endpoint='admin.delivery_revoke')
    @admin_required
    @guarded
    def revoke(device_id):
        fields(body(), '')
        return jsonify(state().revoke(device_id))
