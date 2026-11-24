"""Opt-in HTTPS Events draft editor. Native approval endpoints require signatures."""
import base64
import hmac
import secrets
from pathlib import Path

from flask import Blueprint, current_app, jsonify, render_template, request, session

from kiosk.core.request_security import AuthenticationLimiter, csrf_token
from kiosk.delivery.protocol import decode, digest, fields, DeliveryError
from kiosk.display.qr_pairing import qr_png_bytes
from .workspace import Workspace, WorkspaceError


editor = Blueprint('roaming_editor', __name__, url_prefix='/editor')


def store():
    return current_app.extensions['roaming_workspace']


def body():
    if request.mimetype!='application/json':
        raise WorkspaceError('json_required',415)
    payload=request.stream.read(65537)
    if len(payload)>65536:
        return _too_large()
    return decode(payload)


def _too_large():
    raise WorkspaceError('request_limit',413)


def secret():
    return session.get('editor_session')


@editor.before_request
def protect():
    workspace=store()
    if not request.is_secure or request.host_url.rstrip('/')!=workspace.origin:
        raise WorkspaceError('trusted_https_origin_required',403)
    limiter=current_app.extensions['roaming_limiter']
    if limiter.reserve(request.remote_addr or 'unknown',request.endpoint or 'unknown'):
        raise WorkspaceError('request_limit',429)
    path = request.path
    if ((path == '/editor/pages' or path.startswith('/editor/pages/'))
            and not workspace.stage6_pages):
        raise WorkspaceError('page_workspace_unavailable', 404)
    if request.method not in ('GET','HEAD','OPTIONS'):
        if request.endpoint not in ('roaming_editor.native_challenge','roaming_editor.native_accept','roaming_editor.native_approve'):
            expected=session.get('csrf_token')
            supplied=request.headers.get('X-CSRF-Token') or request.form.get('csrf_token')
            if (not isinstance(expected,str) or not isinstance(supplied,str) or
                    len(supplied)!=64 or not expected.isascii() or not supplied.isascii() or
                    not hmac.compare_digest(expected,supplied)):
                raise WorkspaceError('csrf_refused',403)


@editor.errorhandler(WorkspaceError)
def workspace_error(error):
    return jsonify(error=error.code),error.status


@editor.errorhandler(ValueError)
def invalid_input(error):
    # Cryptographic/parser errors never include supplied bytes in a response/log.
    return jsonify(error='request_or_authority_refused'),403


@editor.errorhandler(DeliveryError)
def protocol_error(error):
    return jsonify(error=error.code),error.status


@editor.after_request
def headers(response):
    response.headers['Cache-Control']='no-store'
    response.headers['Referrer-Policy']='no-referrer'
    response.headers['X-Content-Type-Options']='nosniff'
    response.headers.setdefault('Content-Security-Policy', "default-src 'none'; script-src 'self'; style-src 'self'; img-src data:; connect-src 'self'; form-action 'self'; frame-ancestors 'none'; base-uri 'none'")
    return response


@editor.get('')
def home():
    try:
        identity=store().authenticate(secret())
    except (ValueError,WorkspaceError):
        identity=None
    return render_template('roaming_editor.html', identity=identity, stage6_pages=store().stage6_pages)


@editor.post('/login/start')
def begin_login():
    binding=session.get('editor_browser')
    if not isinstance(binding,str):
        binding=secrets.token_hex(32)
        session['editor_browser']=binding
    summary=request.user_agent.browser or 'Browser'
    token,document=store().create_login(binding,summary)
    # Fragment is never sent in a browser HTTP request or Referer.
    uri='kiosk://roaming/login#origin='+store().origin+'&token='+token
    png=base64.b64encode(qr_png_bytes(uri)).decode()
    return jsonify(token=token,context=document,confirmation=document['id'][:8].upper(),
                   qr='data:image/png;base64,'+png)


@editor.post('/login/poll')
def poll_login():
    value=body();fields(value,'token')
    result=store().consume_login(value['token'],session.get('editor_browser',''))
    if result is None:
        return jsonify(state='pending'),202
    value,device=result
    # Rotate the entire browser session including CSRF, not only a user flag.
    session.clear()
    session['editor_session']=value
    return jsonify(state='accepted',user=device['user_id'],csrf=csrf_token())


@editor.post('/native/challenge')
def native_challenge():
    value=body();fields(value,'token')
    return jsonify(context=store().challenge(value['token']))


@editor.post('/native/accept')
def native_accept():
    value=body()
    fields(value,'token approval chain')
    store().accept_login(value['token'],value['approval'],value['chain'])
    return jsonify(state='accepted')


@editor.get('/objects')
def objects():
    return jsonify(objects=store().objects(secret()))


@editor.post('/objects/<identity>')
def save_object(identity):
    value=body()
    fields(value,'expected_version payload dependencies')
    version=store().save(secret(),identity,value['expected_version'],value['payload'],value['dependencies'])
    return jsonify(version=version),201


@editor.post('/objects/<identity>/ready')
def ready_object(identity):
    value=body();fields(value,'version')
    store().ready(secret(),identity,value['version'])
    return jsonify(state='ready')


@editor.get('/pages')
def page_library():
    identity = store().authenticate(secret())
    return render_template('page_library.html', identity=identity)


@editor.get('/pages/objects')
def page_objects():
    return jsonify(objects=store().page_objects(secret()))


@editor.post('/pages/objects/<identity>')
def save_page_object(identity):
    value = body()
    fields(value, 'expected_version payload dependencies')
    version = store().save_page(secret(), identity, value['expected_version'],
                                value['payload'], value['dependencies'])
    return jsonify(version=version), 201


@editor.post('/pages/objects/<identity>/ready')
def ready_page_object(identity):
    value = body()
    fields(value, 'version')
    store().ready_page(secret(), identity, value['version'])
    return jsonify(state='ready')


@editor.get('/pages/plan')
def page_plan():
    return jsonify(store().page_plan(secret()))


@editor.get('/pages/target-preview')
def page_target_preview():
    target = request.args.get('target', '')
    preview = store().page_target_preview(secret(), request.args.get('device', ''), target,
                                          request.args.get('revision_sha256', ''))
    media = {}
    for event in preview['events']:
        for field in ('image_tv', 'image_kiosk', 'image_thumb'):
            path = event[field]
            if path is not None and path.startswith('/static/uploads/'):
                media[path] = url_for('static', filename=path.removeprefix('/static/'))
    preview.update(mode=target.split('-', 1)[0], media=media)
    response = current_app.make_response(render_template('page_target_preview.html', preview=preview))
    response.headers['Content-Security-Policy'] = (
        "default-src 'none'; script-src 'self'; style-src 'self'; img-src 'self'; "
        "frame-ancestors 'none'; base-uri 'none'")
    return response


@editor.get('/pages/objects/<identity>/dependants')
def page_dataset_dependants(identity):
    return jsonify(store().dataset_dependants(secret(), identity))


@editor.get('/pages/modules/events')
def page_events_status():
    return jsonify(store().module_status(secret()))


@editor.post('/pages/modules/events')
def page_update_events_status():
    value = body()
    fields(value, 'expected_version enabled')
    return jsonify(store().set_events_enabled(secret(), value['expected_version'], value['enabled']))


@editor.get('/sessions')
def sessions():
    return jsonify(sessions=store().sessions(secret()))


def delivery():
    state = current_app.extensions.get('device_delivery')
    if state is None:
        raise WorkspaceError('delivery_unavailable', 503)
    return state


@editor.get('/native/settings')
def native_settings():
    return jsonify(store().settings(secret()))


@editor.post('/native/settings')
def save_settings():
    value = body()
    fields(value, 'expected_version values')
    version = store().update_settings(secret(), value['expected_version'], value['values'])
    return jsonify(version=version)


@editor.get('/native/targets')
def targets():
    store().authenticate(secret())
    from kiosk.display.cache import renderer_identity
    return jsonify(targets=delivery().publisher_targets(renderer_identity()))


@editor.post('/native/prepare')
def native_prepare():
    """Build the package only from the frozen draft snapshot, then freeze the plan."""
    identity = store().authenticate(secret())
    value = body()
    fields(value, 'selected targets parents')
    from .materialize import prepare_publication
    from kiosk.display.cache import renderer_identity
    state = delivery()
    current = state.publisher_targets(renderer_identity())
    if value['targets'] != current:
        raise WorkspaceError('publisher_targets_changed', 409)
    document = prepare_publication(store(), secret(), value['selected'], value['targets'],
                                   value['parents'], state,
                                   current_app.config['PUBLIC_UPLOAD_DIR'],
                                   current_app.config['RESOURCE_DIR'] / 'kiosk')
    plan = document['plan']
    uri = 'kiosk://roaming/publish#origin=' + store().origin + '&plan=' + plan['id']
    return jsonify(id=plan['id'], confirmation=plan['id'][:8].upper(), plan=plan,
                   package_id=document['publication']['package_id'],
                   revision=document['content_version'], user=identity['user_id'],
                   link=uri,
                   qr='data:image/png;base64,' + base64.b64encode(qr_png_bytes(uri)).decode(),
                   expires=plan['expires'])


def _distribution_report(identity):
    """Distribute an already signed plan; failure is reported, never re-signed."""
    from .distribution import promote
    try:
        result = promote(store(), delivery(), identity, store().now())
        return dict(state='ready', **result)
    except DeliveryError as error:
        return dict(state='pending', error=error.code, retry=True)
    except WorkspaceError as error:
        return dict(state='pending', error=error.code, retry=error.status != 404)
    except (OSError, KeyError, ValueError):
        return dict(state='pending', error='distribution_unavailable', retry=True)


@editor.post('/native/distribute')
def native_distribute():
    """Retry distribution of this signed plan. Signature, not role, authorizes it.

    The approving user or an administrator may retry; no new approval or second
    person is required and no queue is silently dropped.
    """
    identity = store().authenticate(secret())
    value = body()
    fields(value, 'id')
    document = store().candidate(value['id'])
    user = document['plan']['user_id']
    if identity['user_id'] != user and identity['role'] != 'administrator':
        raise WorkspaceError('publisher_scope_required', 403)
    result = _distribution_report(value['id'])
    if result['state'] != 'ready':
        raise DeliveryError(result.get('error', 'distribution_pending'), 409)
    return jsonify(result)


@editor.get('/native/candidates/<identity>/status')
def candidate_status(identity):
    """Pending/signed/distributed reporting for the browser that prepared the plan."""
    digest(identity)
    store().authenticate(secret())
    state = store().plan_state(identity)
    document = store().candidate(identity)
    distribution = None
    if state['approved']:
        delivery_state = current_app.extensions.get('device_delivery')
        if delivery_state is not None:
            distribution = delivery_state.publisher_distribution(
                document['plan']['publication_sha256'])
    return jsonify(approved=state['approved'], distribution=distribution)


@editor.get('/native/candidates/<identity>/<group>/<path:name>')
def candidate_artifact(identity, group, name):
    """Exact review bytes for a prepared candidate. Public Events data only; the
    publisher signature, not this transport, authorizes the publication."""
    digest(identity)
    if group not in ('package', 'kiosk', 'tv'):
        raise WorkspaceError('material_not_found', 404)
    document = store().candidate(identity)
    metadata = document['publication']
    entry = next((item for item in metadata[group]['files'] if item['path'] == name), None)
    if entry is None:
        raise WorkspaceError('material_not_found', 404)
    from kiosk.publication.exporter import _plain_path
    state = delivery()
    root = state.root / 'publications' / metadata['package_id'] / group
    return current_app.extensions['device_delivery_transfers'].response(_plain_path(root, name), entry)


@editor.post('/sessions/terminate')
def terminate():
    value=body();fields(value,'id')
    store().terminate(secret(),value['id'])
    return jsonify(state='terminated')


@editor.post('/logout')
def logout():
    store().terminate(secret())
    session.clear()
    return jsonify(state='signed_out')


@editor.get('/native/candidates/<identity>')
def candidate(identity):
    digest(identity)
    # Immutable public candidate only; no user/device private state in this route.
    return jsonify(store().candidate(identity))


@editor.post('/native/approve')
def native_approve():
    value=body()
    fields(value,'id approval chain')
    store().approve(value['id'],value['approval'],value['chain'])
    # One explicit native Publish action leads directly to authorized distribution;
    # the same signed approval commits here, with a retryable pending report.
    return jsonify(state='approved', distribution=_distribution_report(value['id']))


def configure(app):
    config=app.config.get('ROAMING_WORKSPACE')
    if config is None:
        return
    app.config['SESSION_COOKIE_SECURE']=True
    # Explicit installation opt-in. Root SPKI is separately authenticated public
    # configuration, never supplied by this delivery server's enrollment/login.
    workspace=Workspace(config['database'],base64.b64decode(config['root_spki'],validate=True),
                        config['group_id'],config['origin'],
                        stage6_pages=config.get('stage6_pages') is True)
    if config.get('policy'):
        workspace.startup_policy(decode(Path(config['policy']).read_bytes()))
    app.extensions['roaming_workspace']=workspace
    app.extensions['roaming_limiter']=AuthenticationLimiter(account_limit=90,source_limit=180)
    app.register_blueprint(editor)
