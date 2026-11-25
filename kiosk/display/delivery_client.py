"""Native Windows Events delivery using the existing store and display coordinator."""
import argparse
from contextlib import contextmanager
import json
import secrets
import time
from pathlib import Path
from urllib.parse import urlencode

from kiosk.delivery.protocol import DeliveryError, PROFILE, decode, digest, encode, fields, sha, text
from kiosk.publication.exporter import PackageError, _json, verify_package
from kiosk.publication.store import PublicationStore
from .cache import renderer_identity, verify_cached_view
from .coordinator import _check_storage, _view_identity, _read_json, display_session
from .session import install_for_display
from .delivery_authority import PrivateState, bootstrap, positive
from .delivery_capture import Capture, validate_metadata
from .delivery_transport import MAX_RETRY_SECONDS, Transport, TransportError, retry_delay
from .delivery_progress import Reporter
from . import page_view


PAGE_DESTINATION = 'windows-pages-v1'


def page_expectation(native):
    """Pinned local v4 expectations; renderer hashes never come from the response."""
    context = native.page_context()
    pin = page_view.renderer_pin()
    return {'root_spki': context['root_spki'], 'trusted_origin': context['origin'],
            'expected_group_id': context['group_id'],
            'expected_device_id': context['device_id'],
            'expected_profile': context['profile'],
            'expected_destination': PAGE_DESTINATION,
            'expected_js_sha256': pin['js_sha256'],
            'expected_css_sha256': pin['css_sha256'],
            'policy_floor': context['policy_floor'],
            'known_heads': context['heads']}


def check_page_assignment(native, assignment, now):
    """Verify one v4 assignment's proof and local target before downloading bytes."""
    from kiosk.publication import authority as page_authority
    if not isinstance(assignment, dict) or assignment.get('version') != 4:
        raise PackageError('page_release_assignment')
    expected = page_expectation(native)
    if (assignment.get('group_id') != expected['expected_group_id']
            or assignment.get('device_id') != expected['expected_device_id']
            or assignment.get('profile') != expected['expected_profile']
            or assignment.get('destination') != expected['expected_destination']):
        raise PackageError('page_release_local_identity')
    try:
        renderer = assignment['metadata']['publication']['renderer']
    except (KeyError, TypeError):
        raise PackageError('page_release_metadata') from None
    if (renderer.get('js_sha256') != expected['expected_js_sha256']
            or renderer.get('css_sha256') != expected['expected_css_sha256']
            or renderer.get('build_id') != page_view.page_renderer_identity()):
        raise PackageError('page_release_renderer_mismatch')
    try:
        plan, target, policy = page_authority.page_assignment(
            assignment['publisher'], assignment, expected['root_spki'],
            expected['trusted_origin'], now, policy_floor=expected['policy_floor'],
            known_heads=expected['known_heads'])
    except (TypeError, KeyError):
        raise PackageError('page_release_assignment') from None
    return plan, target, policy


def admit_page_package(native, assignment, files):
    """Full v4 admission: proof plus every outer and inner package byte."""
    from kiosk.publication import page_release
    expected = page_expectation(native)
    return page_release.admit(
        assignment['publisher'], assignment, expected['root_spki'],
        expected['trusted_origin'], native.now(), files=files,
        expected_group_id=expected['expected_group_id'],
        expected_device_id=expected['expected_device_id'],
        expected_profile=expected['expected_profile'],
        expected_destination=expected['expected_destination'],
        expected_js_sha256=expected['expected_js_sha256'],
        expected_css_sha256=expected['expected_css_sha256'],
        policy_floor=expected['policy_floor'], known_heads=expected['known_heads'])


# The server enforces a minimum poll interval and answers earlier polls with 429
# slow_down. A one-second client margin keeps ordinary jitter from colliding with
# the server timestamp, and any remaining 429 is retried after its Retry-After.
POLL_SECONDS = 5
POLL_MARGIN_SECONDS = 1
# Renew the device credential proactively when less than one day remains, so a
# routine LAN sync extends authorization without re-enrollment or admin re-approval.
RENEWAL_MARGIN_SECONDS = 86400
# Fixed server refusal codes that have a distinct recovery meaning. Everything
# else stays a generic transport refusal and is never guessed from the HTTP status.
REFUSAL_STATES = {
    'credential_expired': 'expired',
    'invalid_credential': 'revoked_or_replaced',
    'credential_revoked': 'revoked_or_replaced',
    'admission_authority_expired': 'authority_expired',
    'trust_binding_or_time_refused': 'authority_expired',
}
RECOVERY_STATES = ('expired', 'revoked_or_replaced', 'authority_expired')
# Persisted server-imposed prohibition; distinct from the ordinary local poll
# schedule so a throttle is not confused with "the next ordinary poll is due".
RETRY_DEADLINE_KEY = 'retry_not_before'
RETRYABLE_STATUSES = (429, 503)


def retry_wait(error):
    return max(1, retry_delay(getattr(error, 'retry_after', POLL_SECONDS), POLL_SECONDS))


def retry_deadline(value):
    """Read a persisted deadline defensively; a malformed value never delays forever."""
    try:
        return max(0, int(value))
    except (TypeError, ValueError):
        return 0


class Client:
    def __init__(self, root, shell, *, audit=None):
        self.root, self.shell = Path(root).absolute(), Path(shell).absolute()
        self.private, self.store, self.cache = [self.root / name for name in ('private', 'store', 'cache')]
        self.state, self.profile, self.capture_root = [self.root / name for name in ('state', 'profile', 'capture')]
        _check_storage(self.shell, (self.private, self.capture_root, self.root / 'control', self.root / 'diagnostics'))
        _check_storage(self.shell, (self.store, self.cache, self.state, self.profile))
        self.native = PrivateState(self.private)
        self.audit = audit
        self.capture = Capture(self.capture_root, reuse_roots=(self.store / 'revisions', self.cache), audit=audit)
        self.transport = None
        self.progress = Reporter(self.private / 'progress-sequence.json')
        self.progress_target = None

    @contextmanager
    def ownership(self):
        with PublicationStore(self.private)._lease():
            # Reload only after acquiring the one network/capture/outbox owner's lease.
            self.native = PrivateState(self.private)
            try:
                yield self
            finally:
                self.progress.close()

    def connect(self):
        value = self.native.data
        if 'bootstrap' not in value:
            raise PackageError('confirmed_bootstrap_required')
        self.transport = Transport(value['bootstrap'], secret=value.get('secret'), audit=self.audit)
        if value.get('trust'):
            self.transport.pin = value['trust']['tls_pin']
            self.transport.pin_kind = value['trust'].get('pin_kind', 'leaf')
        return self.transport

    def enroll(self, bootstrap_path=None, confirmation=None, confirmed_utc=None):
        value = self.native.data
        # Both persisted deadlines are checked BEFORE any request, using only local
        # state, so a restart or an impatient click cannot reach the endpoints early.
        # A server-imposed retry prohibition (429/503) is distinct from the ordinary
        # poll schedule, but neither may send the pending enrollment again.
        now = int(time.time())
        prohibition = retry_deadline(value.get(RETRY_DEADLINE_KEY))
        schedule = retry_deadline(value.get('next_poll'))
        deferred = value.get('pending') or {}
        if value.get('binding') and max(prohibition, schedule) > now:
            if prohibition > now:
                return {'result': 'rate_limited', 'user_code': deferred.get('user_code', ''),
                        'device_id': value['binding'].get('device_id', ''),
                        'retry_after': prohibition - now}
            return {'result': 'pending', 'user_code': deferred.get('user_code', ''),
                    'device_id': value['binding'].get('device_id', ''), 'wait': schedule - now}
        if not value:
            raw = Path(bootstrap_path).read_bytes() if bootstrap_path else b''
            if len(raw) > 16384 or digest(confirmation) != sha(raw):
                raise PackageError('independent_bootstrap_confirmation_required')
            anchor = bootstrap(decode(raw), int(time.time()))
            secret = secrets.token_hex(32)
            binding = {'version': 1, 'request_id': secrets.token_hex(16), 'device_id': secrets.token_hex(16),
                       'group_id': anchor['group_id'], 'profile': PROFILE, 'origin': anchor['origin'],
                       'nonce': secrets.token_hex(16), 'secret_verifier': sha(bytes.fromhex(secret))}
            value.update(bootstrap=anchor, secret=secret, binding=binding)
            self.native.confirm_time(confirmed_utc)
            # Atomic DPAPI persistence happened BEFORE any enrollment request.
        self.native.now()
        transport = self.connect()
        try:
            credential = transport.json('/api/v2/client/status')
        except TransportError as error:
            # A bounded server rate limit is retryable: keep the persisted request
            # and report the wait instead of ending the enrollment workflow.
            if error.status in RETRYABLE_STATUSES:
                return self._defer(value, retry_wait(error))
            if error.status != 401 or value.get('credential'):
                if error.status == 401:
                    self._record_refusal(error)
                raise
        else:
            self._credential(credential)
            return {'result': 'approved', 'device_id': value['binding']['device_id']}
        pending = value.get('pending')
        if pending is None:
            try:
                pending = transport.json('/api/v2/device/authorize', body=value['binding'], authenticated=False)
            except TransportError as error:
                if error.status in RETRYABLE_STATUSES:
                    return self._defer(value, retry_wait(error))
                raise
            fields(pending, 'version request_id device_code user_code expires_in interval')
            if (type(pending['version']) is not int or pending['version'] != 1 or
                    pending['request_id'] != value['binding']['request_id'] or
                    pending['expires_in'] != 600 or pending['interval'] != POLL_SECONDS or
                    not isinstance(pending['user_code'], str) or len(pending['user_code']) != 8):
                raise PackageError('enrollment_response_refused')
            digest(pending['device_code'])
            value['pending'] = pending
            self.native.save()
        remaining = int(value.get('next_poll', 0)) - int(time.time())
        if remaining > 0:
            return {'result': 'pending', 'user_code': pending['user_code'],
                    'device_id': value['binding']['device_id'], 'wait': remaining}
        value['next_poll'] = int(time.time()) + pending['interval'] + POLL_MARGIN_SECONDS
        self.native.save()
        try:
            response = transport.json('/api/v2/device/token', body={'device_code': pending['device_code']},
                                      authenticated=False, allowed=(200, 202))
        except TransportError as error:
            if error.status in RETRYABLE_STATUSES:
                return self._defer(value, retry_wait(error), pending['user_code'])
            raise
        if response.get('state') == 'pending':
            fields(response, 'version state interval')
            if type(response['version']) is not int or response['version'] != 1 or response['interval'] != POLL_SECONDS:
                raise PackageError('enrollment_response_refused')
            return {'result': 'pending', 'user_code': pending['user_code'],
                    'device_id': value['binding']['device_id'], 'wait': POLL_SECONDS + POLL_MARGIN_SECONDS}
        self._credential(response)
        return {'result': 'approved', 'device_id': value['binding']['device_id']}

    def _defer(self, value, wait, user_code=''):
        """Persist the server wait for 429/503; the same request identity is kept."""
        wait = max(1, min(MAX_RETRY_SECONDS, int(wait)))
        moment = int(time.time())
        value[RETRY_DEADLINE_KEY] = moment + wait
        # The ordinary poll schedule stays separate but must not fire earlier.
        value['next_poll'] = moment + wait + POLL_MARGIN_SECONDS
        self.native.save()
        return {'result': 'rate_limited', 'user_code': user_code,
                'device_id': value['binding']['device_id'], 'retry_after': wait}

    def _credential(self, credential):
        fields(credential, 'version state device_id profile credential_id expires_at scopes')
        if (type(credential['version']) is not int or credential['version'] != 1 or credential['state'] != 'approved' or
                credential['device_id'] != self.native.data['binding']['device_id'] or credential['profile'] != PROFILE or
                credential['scopes'] != ['read_assignment', 'submit_receipt']):
            raise PackageError('credential_binding_refused')
        text(credential['credential_id'])
        if positive(credential['expires_at']) <= self.native.now():
            raise PackageError('credential_expired')
        old = self.native.data.get('credential')
        if old and old != credential:
            raise PackageError('credential_replacement_requires_enrollment')
        self.native.data['credential'] = credential
        self.native.data.pop('revoked', None)
        self.clear_recovery()
        self.native.data.pop(RETRY_DEADLINE_KEY, None)
        self.native.data.pop('next_poll', None)
        self.native.save()

    def recovery(self):
        """Persisted server-confirmed refusal state, or None.

        The value is evidence-backed: ``code`` is the fixed server refusal label and
        ``state`` is its client meaning. It never blocks retained offline display.
        """
        value = self.native.data.get('recovery')
        return value if isinstance(value, dict) and value.get('state') in RECOVERY_STATES else None

    def clear_recovery(self):
        if self.native.data.pop('recovery', None) is not None:
            self.native.save()

    def _record_refusal(self, error):
        """Persist the server's actual refusal reason instead of guessing from 401."""
        code = str(error)
        state = REFUSAL_STATES.get(code)
        if state is None:
            return None
        try:
            when = self.native.now()
        except PackageError:
            when = int(time.time())
        self.native.data['recovery'] = {'code': code, 'state': state, 'at': when}
        # A confirmed revocation is a durable prohibition; an expired credential or
        # expired signed authority is recoverable by explicit re-pairing/refresh.
        if state == 'revoked_or_replaced':
            self.native.data['revoked'] = True
        else:
            self.native.data.pop('revoked', None)
        self.native.save()
        return state

    def _renew_if_needed(self, transport):
        """Automatically renew the device credential before expiry, without re-enrollment.

        The server extends only the expiry of a stable, non-revoked credential when
        the device proves possession of its current bearer secret and the signed
        group trust is still valid. The secret/credential identity are unchanged, so
        lost responses and retries are idempotent. Failure keeps the current
        credential (and accepted offline content) and is not an enrollment reset.
        """
        credential = self.native.data.get('credential')
        if not credential:
            return
        if positive(credential['expires_at']) - self.native.now() >= RENEWAL_MARGIN_SECONDS:
            return
        renewed = transport.json('/api/v2/device/renew', body={}, authenticated=True)
        fields(renewed, 'version state device_id credential_id expires_at scopes')
        if (type(renewed['version']) is not int or renewed['version'] != 1 or
                renewed['state'] != 'renewed' or
                renewed['device_id'] != credential['device_id'] or
                renewed['credential_id'] != credential['credential_id'] or
                renewed['scopes'] != ['read_assignment', 'submit_receipt']):
            raise PackageError('renewal_refused')
        if positive(renewed['expires_at']) <= self.native.now():
            raise PackageError('renewal_expired')
        self.native.data['credential'] = {**credential, 'expires_at': renewed['expires_at']}
        self.native.save()

    def recover(self):
        """Explicit re-pairing for the SAME device identity, preserving accepted content.

        Only the enrollment request identity and any server-confirmed refusal are
        cleared. The confirmed bootstrap anchor, device_id, secret verifier, accepted
        offline packages and their binding stay unchanged, so a new administrator
        approval of the same device cannot invalidate retained display content.
        """
        value = self.native.data
        if not value.get('bootstrap') or not value.get('binding'):
            raise PackageError('confirmed_bootstrap_required')
        value['binding'] = {**value['binding'], 'request_id': secrets.token_hex(16),
                            'nonce': secrets.token_hex(16)}
        value.pop('credential', None)
        value.pop('revoked', None)
        value.pop('recovery', None)
        value.pop('pending', None)
        value.pop(RETRY_DEADLINE_KEY, None)
        value.pop('next_poll', None)
        self.native.save()
        return True

    def _online_authority(self):
        recovery = self.recovery()
        # A server-confirmed revocation is durable until the explicit re-pairing
        # action clears it; an expired credential or expired signed authority is
        # recoverable automatically and must not be blocked here.
        if self.native.data.get('revoked') or (recovery and recovery['state'] == 'revoked_or_replaced'):
            raise PackageError('credential_revoked')
        self.native.now()
        transport = self.connect()
        try:
            self._credential(transport.json('/api/v2/client/status'))
            trust = transport.json('/api/v2/group/trust')
            self.native.verify_trust(trust, transport.observed_pin, transport.observed_issuer_pin)
            transport.pin = self.native.data['trust']['tls_pin']
            transport.pin_kind = self.native.data['trust'].get('pin_kind', 'leaf')
            if (self.recovery() or {}).get('state') == 'authority_expired':
                # The server served a currently valid signed group list at a
                # non-decreasing generation: ordinary admission is restored.
                self.clear_recovery()
            self._renew_if_needed(transport)
        except (TransportError, PackageError) as error:
            self._record_refusal(error)
            raise
        return transport

    def assignment(self, transport):
        try:
            transport.json('/api/v2/client/capabilities', body={'version': 1, 'platform': 'windows',
                'modes': ['tv', 'kiosk'], 'content': ['events'], 'resource_profile': PROFILE,
                'renderer': renderer_identity(),
                'pages_renderer': page_view.page_renderer_identity()})
        except TransportError as exc:
            if exc.status not in (404, 405):
                raise
        query = urlencode({'renderer': renderer_identity(), 'resource_profile': PROFILE,
                           'display_protocol': 'display-profile-v2',
                           'pages_renderer': page_view.page_renderer_identity()})
        value = transport.json('/api/v2/client/assignment?' + query)
        if isinstance(value, dict) and value.get('version') == 4:
            check_page_assignment(self.native, value, self.native.now())
            publication = value['metadata']['publication']
        else:
            self.native.validate_assignment(value)
            digest(value['publication']['package_id'])
            validate_metadata(value['publication'])
            publication = value['publication']
        self.progress_target = {key: value[key] for key in ('device_id', 'group_id', 'generation')}
        self.progress_target['version'] = 1
        self.progress_target['package_id'] = publication['package_id']
        return value

    def synchronize(self, *, full_resync=False):
        transport = self._online_authority()
        target = {'version': 1, 'device_id': self.native.data['binding']['device_id'],
                  'group_id': self.native.data['bootstrap']['group_id']}
        attempt = self.progress.begin()
        self.progress_target = None
        try:
            assignment = self.assignment(transport)
        except (PackageError, DeliveryError) as exc:
            incompatible = ((isinstance(exc, TransportError) and exc.status == 409) or str(exc).startswith('unsupported_'))
            if self.progress_target or incompatible:
                self.progress.offer(transport, self.progress_target or target, attempt,
                                    'incompatible' if incompatible else 'error',
                                    error='requires_update' if incompatible else 'candidate_refused')
            raise
        if isinstance(assignment, dict) and assignment.get('version') == 4:
            return self._synchronize_pages(transport, assignment, attempt, full_resync)
        # Only the fully validated assignment binds download telemetry. A changed
        # target snapshot cannot redirect reports to another publication.
        target = {key: assignment[key] for key in ('device_id', 'group_id', 'generation')}
        target['version'] = 1
        target['package_id'] = assignment['publication']['package_id']
        package_id = assignment['publication']['package_id']
        active = PublicationStore(self.store).active()
        if active is not None and active.name == package_id:
            # Reverify accepted package and locally pinned renderer without artifact GETs.
            self.native.accepted(package_id)
            self.native.accept(assignment)
            page_view.set_active_kind(self.store, 'events', package_id)
            return package_id
        total = sum(entry['size'] for group in ('package', 'kiosk', 'tv') for entry in assignment['publication'][group]['files'])
        def report(state, completed=0):
            self.progress.offer(transport, target, attempt, state, completed, total)
        report('waiting')
        try:
            package = self.capture.fetch(assignment, transport, full_resync=full_resync, progress=report)
            # Long capture cannot preserve stale/expired authority or an obsolete assignment.
            transport = self._online_authority()
            fresh = self.assignment(transport)
            if encode(fresh) != encode(assignment):
                raise PackageError('assignment_changed_before_admission')
            self.native.accept(fresh)
            install_for_display(package, self.store, self.cache, mode='tv')
            page_view.set_active_kind(self.store, 'events', package_id)
        except (PackageError, DeliveryError, OSError, ValueError, KeyError, TypeError) as exc:
            code = str(exc)
            error = ('connection' if isinstance(exc, TransportError) else
                     'storage' if isinstance(exc, OSError) or code == 'capture_disk_full' else
                     'assignment_changed' if code == 'assignment_changed_before_admission' else
                     'requires_update' if code.startswith('unsupported_') else
                     'integrity' if any(word in code for word in ('hash', 'binding', 'validator')) else 'candidate_refused')
            self.progress.offer(transport, target, attempt, 'incompatible' if error == 'requires_update' else 'error',
                                self.capture.completed, total, error)
            raise
        return package_id

    def _synchronize_pages(self, transport, assignment, attempt, full_resync):
        """Admit, store and prepare one signed per-target data-only page package."""
        target = self.progress_target
        publication = assignment['metadata']['publication']
        package_id = publication['package_id']
        if page_view.active_page_package(self.store) == package_id:
            self.native.accepted(package_id)
            self.native.accept_page(assignment)
            self.native.data['activated_display'] = {
                'package_id': package_id, 'mode': assignment['display']['mode'], 'kind': 'pages'}
            self.native.save()
            return package_id
        total = sum(entry['size'] for entry in publication['package']['files'])
        def report(state, completed=0):
            self.progress.offer(transport, target, attempt, state, completed, total)
        report('waiting')
        try:
            package = self.capture.fetch_pages(assignment, transport, full_resync=full_resync,
                                               progress=report)
            transport = self._online_authority()
            fresh = self.assignment(transport)
            if encode(fresh) != encode(assignment):
                raise PackageError('assignment_changed_before_admission')
            files = page_view.read_package_tree(package)
            admit_page_package(self.native, fresh,
                               {'package': files, 'kiosk': {}, 'tv': {}})
            self.native.accept_page(fresh)
            page_view.install_page_for_display(package, fresh['metadata'], self.store,
                                               self.cache, mode=fresh['display']['mode'])
        except (PackageError, DeliveryError, OSError, ValueError, KeyError, TypeError) as exc:
            code = str(exc)
            error = ('connection' if isinstance(exc, TransportError) else
                     'storage' if isinstance(exc, OSError) or code == 'capture_disk_full' else
                     'assignment_changed' if code == 'assignment_changed_before_admission' else
                     'requires_update' if code.startswith('unsupported_') or 'renderer' in code else
                     'integrity' if any(word in code for word in ('hash', 'binding', 'validator')) else
                     'candidate_refused')
            self.progress.offer(transport, target, attempt,
                                'incompatible' if error == 'requires_update' else 'error',
                                self.capture.completed, total, error)
            raise
        return package_id

    def queue_ready(self, run):
        try:
            return self._queue_ready(run)
        except (PackageError, DeliveryError, OSError, ValueError, KeyError, TypeError):
            self.activation_failed()
            raise

    def activation_failed(self):
        if getattr(self, 'transport', None) is None:
            return
        if getattr(self, 'progress_target', None):
            self.progress.offer(self.transport, self.progress_target, self.progress.begin(), 'error', error='candidate_refused')

    def assigned_mode(self, package, fallback='tv'):
        mode = self.native.accepted(package).get('display', {}).get('mode', 'local')
        return mode if mode in ('tv', 'kiosk') else fallback

    def active_publication(self):
        """Newest admitted publication; a broken pages pointer falls back to Events."""
        try:
            if page_view.active_kind(self.store) == 'pages':
                package = page_view.active_page_package(self.store)
                if package is not None:
                    return {'kind': 'pages', 'package_id': package}
        except PackageError:
            pass
        active = PublicationStore(self.store).active()
        if active is None:
            return None
        return {'kind': 'events', 'package_id': active.name}

    def switch_to_active(self, run):
        try:
            active = self.active_publication()
            if active is None:
                raise PackageError('no_publication')
            self.native.accepted(active['package_id'])
            mode = self.assigned_mode(active['package_id'], run.mode)
            return run.switch_to_active(mode=mode)
        except (PackageError, OSError, ValueError, KeyError, TypeError):
            self.activation_failed()
            raise

    def _queue_ready(self, run):
        if run.process.poll() is not None or run.pending is not None or run.receipt_pending:
            raise PackageError('native_ready_not_confirmed')
        package = _view_identity(run.view)
        status = _read_json(run.profile, 'display-status.json')
        if (status.get('session_id') != run.session or type(status.get('process_id')) is not int or
                status['process_id'] != run.process.pid or status.get('renderer_ready') is not True or
                status.get('navigation_success') is not True or status.get('startup_failed') is not False or
                status.get('package_sha256') != package or status.get('mode') != run.mode or
                status.get('view_key') != run.view.parent.name):
            raise PackageError('native_ready_not_confirmed')
        verify_cached_view(run.view.parent, package_identity=package, mode=run.mode)
        association = self.native.accepted(package)
        if self.assigned_mode(package, run.mode) != run.mode:
            return None  # Preserve the previous usable display without crediting the new configuration.
        self.native.data['activated_display'] = {'package_id': package, 'mode': run.mode,
                                                 'kind': page_view.view_kind(run.view)}
        self.native.save()
        receipt_path = run.state / ('last-ready-' + run.mode + '.json')
        receipt = decode(receipt_path.read_bytes())
        if receipt.get('package_sha256') != package or receipt.get('view') != run.view.parent.name:
            raise PackageError('native_ready_not_confirmed')
        # Each actual native session/package/mode/generation gets one stable body.
        key = sha(encode([run.session, package, run.mode, association['generation']]))
        sent = self.native.data.setdefault('ready_sessions', [])
        if key in sent:
            return
        outbox = self.native.data.setdefault('outbox', [])
        if len(outbox) >= 4096 or len(sent) >= 4096:
            raise PackageError('receipt_capacity')
        body = {'version': 1, 'receipt_id': secrets.token_hex(16), 'group_id': association['group_id'],
                'device_id': association['device_id'], 'generation': association['generation'], 'package_id': package,
                'mode': run.mode, 'session': run.session, 'result': 'ready'}
        outbox.append(body)
        sent.append(key)
        try:
            self.native.save()
        except BaseException:
            outbox.remove(body)
            sent.remove(key)
            raise

    def flush_ready(self):
        # Accepted historical ready can drain after reboot without NEW admission authority.
        transport = self.connect()
        for body in list(self.native.data.get('outbox', [])):
            result = transport.json('/api/v2/client/receipts', body=body)
            fields(result, 'version receipt_id state')
            if type(result['version']) is not int or result['version'] != 1 or result['receipt_id'] != body['receipt_id'] or result['state'] != 'recorded':
                raise PackageError('receipt_ack_refused')
            queue = self.native.data['outbox']
            queue.remove(body)
            try:
                self.native.save()
            except BaseException:
                queue.insert(0, body)
                raise

    @contextmanager
    def display(self, mode='tv'):
        # Validate every fallback the existing coordinator may select before it can spawn.
        active = self.active_publication()
        if active is None:
            raise PackageError('no_publication')
        saved = self.native.data.get('activated_display', {})
        if saved.get('package_id') == active['package_id']:
            mode = saved.get('mode', mode)
        else:
            mode = self.assigned_mode(active['package_id'], mode)
        self.native.accepted(active['package_id'])
        from .coordinator import _confirmed_view
        previous = _confirmed_view(self.store, self.cache, self.state, mode)
        if previous is not None:
            self.native.accepted(_view_identity(previous))
        try:
            with display_session(self.store, self.cache, self.state, self.profile, self.shell, mode=mode) as run:
                self.native.accepted(_view_identity(run.view))
                if self.progress_target and _view_identity(run.view) != self.progress_target['package_id']:
                    self.activation_failed()  # Coordinator recovered the previous usable view.
                self.queue_ready(run)
                yield run
        except (PackageError, OSError, ValueError, KeyError, TypeError):
            self.activation_failed()
            raise


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', required=True, type=Path)
    parser.add_argument('--shell', required=True, type=Path)
    parser.add_argument('--audit', type=Path, help='Private diagnostics path, never request/response headers or bodies')
    commands = parser.add_subparsers(dest='command', required=True)
    enrollment = commands.add_parser('enroll')
    enrollment.add_argument('--bootstrap', type=Path)
    enrollment.add_argument('--bootstrap-sha256')
    enrollment.add_argument('--confirmed-utc', type=int)
    confirm = commands.add_parser('confirm-time')
    confirm.add_argument('--utc', required=True, type=int)
    commands.add_parser('sync').add_argument('--full-resync', action='store_true')
    commands.add_parser('flush')
    commands.add_parser('identity')
    anchor = commands.add_parser('publisher-root')
    anchor.add_argument('--public', type=Path, required=True,
                        help='Publisher public.json with root_spki and root_sha256')
    anchor.add_argument('--fingerprint', required=True,
                        help='Root SHA-256 received through an independent trusted channel')
    run = commands.add_parser('run')
    run.add_argument('--mode', choices=('kiosk', 'tv'), default='tv')
    run.add_argument('--interval', type=int, default=5)
    args = parser.parse_args()

    def audit(value):
        if args.audit:
            with args.audit.open('a', encoding='utf-8') as stream:
                stream.write(json.dumps(value, sort_keys=True) + '\n')

    def emit(value):
        print(json.dumps(value, sort_keys=True), flush=True)

    try:
        if args.command == 'identity':
            import platform
            import ssl
            import sys
            pin = page_view.renderer_pin()
            emit({'result': 'identity', 'renderer_build': renderer_identity(),
                  'pages_renderer': pin['build_id'], 'pages_js_sha256': pin['js_sha256'],
                  'pages_css_sha256': pin['css_sha256'], 'python': sys.version,
                  'platform': platform.platform(), 'tls_runtime': ssl.OPENSSL_VERSION,
                  'shell_sha256': sha(args.shell.read_bytes())})
            return 0
        client = Client(args.root, args.shell, audit=audit)
        with client.ownership():
            if args.command == 'enroll':
                emit(client.enroll(args.bootstrap, args.bootstrap_sha256, args.confirmed_utc))
            elif args.command == 'confirm-time':
                client.native.confirm_time(args.utc)
                emit({'result': 'time_confirmed'})
            elif args.command == 'sync':
                identity = client.synchronize(full_resync=args.full_resync)
                emit({'result': 'admitted', 'package_id': identity, 'capture': client.capture.stats})
            elif args.command == 'flush':
                client.flush_ready()
                emit({'result': 'receipts_delivered', 'queued': len(client.native.data.get('outbox', []))})
            elif args.command == 'publisher-root':
                public = decode(args.public.read_bytes())
                client.native.confirm_publisher_root(public['root_spki'], args.fingerprint)
                emit({'result': 'publisher_root_confirmed', 'root_sha256': public['root_sha256']})
            else:
                if not 5 <= args.interval <= 60:
                    raise PackageError('invalid_poll_interval')
                delay = args.interval
                if client.active_publication() is None:
                    client.synchronize()
                with client.display(args.mode) as native:
                    emit({'result': 'ready', 'package_id': _view_identity(native.view), 'session': native.session})
                    stop = client.root / 'control/stop.request'
                    while native.process.poll() is None and not stop.exists():
                        try:
                            client.flush_ready()
                            client.synchronize()
                            target = client.active_publication()
                            if target is None:
                                raise PackageError('no_publication')
                            client.native.accepted(target['package_id'])
                            client.switch_to_active(native)
                            client.queue_ready(native)
                            client.flush_ready()
                            delay = args.interval
                            emit({'result': 'active', 'package_id': _view_identity(native.view), 'capture': client.capture.stats})
                        except (PackageError, DeliveryError) as error:
                            delay = max(args.interval, error.retry_after if isinstance(error, TransportError) else min(60, delay * 2))
                            emit({'result': 'sync_refused', 'code': str(error), 'status': getattr(error, 'status', 0),
                                  'visible_package': _view_identity(native.view), 'retry_after': delay})
                        except (OSError, ValueError, KeyError, TypeError):
                            delay = min(60, delay * 2)
                            emit({'result': 'sync_refused', 'code': 'native_candidate_unavailable',
                                  'visible_package': _view_identity(native.view), 'retry_after': delay})
                        deadline = time.monotonic() + delay
                        while native.process.poll() is None and not stop.exists() and time.monotonic() < deadline:
                            time.sleep(.2)
        return 0
    except (PackageError, DeliveryError) as error:
        emit({'result': 'error', 'code': str(error), 'status': getattr(error, 'status', 0)})
        return 1
    except (OSError, ValueError, KeyError, TypeError):
        emit({'result': 'error', 'code': 'native_delivery_unavailable'})
        return 1
    except KeyboardInterrupt:
        return 130


if __name__ == '__main__':
    raise SystemExit(main())
