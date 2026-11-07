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
from .delivery_transport import Transport, TransportError


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

    @contextmanager
    def ownership(self):
        with PublicationStore(self.private)._lease():
            # Reload only after acquiring the one network/capture/outbox owner's lease.
            self.native = PrivateState(self.private)
            yield self

    def connect(self):
        value = self.native.data
        if 'bootstrap' not in value:
            raise PackageError('confirmed_bootstrap_required')
        self.transport = Transport(value['bootstrap'], secret=value.get('secret'), audit=self.audit)
        if value.get('trust'):
            self.transport.pin = value['trust']['tls_pin']
        return self.transport

    def enroll(self, bootstrap_path=None, confirmation=None, confirmed_utc=None):
        value = self.native.data
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
            if error.status != 401 or value.get('credential'):
                if error.status == 401:
                    value['revoked'] = True
                    self.native.save()
                raise
        else:
            self._credential(credential)
            return {'result': 'approved', 'device_id': value['binding']['device_id']}
        pending = value.get('pending')
        if pending is None:
            pending = transport.json('/api/v2/device/authorize', body=value['binding'], authenticated=False)
            fields(pending, 'version request_id device_code user_code expires_in interval')
            if (type(pending['version']) is not int or pending['version'] != 1 or
                    pending['request_id'] != value['binding']['request_id'] or
                    pending['expires_in'] != 600 or pending['interval'] != 5 or
                    not isinstance(pending['user_code'], str) or len(pending['user_code']) != 8):
                raise PackageError('enrollment_response_refused')
            digest(pending['device_code'])
            value['pending'] = pending
            self.native.save()
        if time.time() < value.get('next_poll', 0):
            return {'result': 'pending', 'user_code': pending['user_code'], 'device_id': value['binding']['device_id']}
        value['next_poll'] = int(time.time()) + 5
        self.native.save()
        response = transport.json('/api/v2/device/token', body={'device_code': pending['device_code']},
                                  authenticated=False, allowed=(200, 202))
        if response.get('state') == 'pending':
            fields(response, 'version state interval')
            if type(response['version']) is not int or response['version'] != 1 or response['interval'] != 5:
                raise PackageError('enrollment_response_refused')
            return {'result': 'pending', 'user_code': pending['user_code'], 'device_id': value['binding']['device_id']}
        self._credential(response)
        return {'result': 'approved', 'device_id': value['binding']['device_id']}

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
        self.native.save()

    def _online_authority(self):
        if self.native.data.get('revoked'):
            raise PackageError('credential_revoked')
        self.native.now()
        transport = self.connect()
        try:
            self._credential(transport.json('/api/v2/client/status'))
            trust = transport.json('/api/v2/group/trust')
            self.native.verify_trust(trust, transport.observed_pin)
            transport.pin = self.native.data['trust']['tls_pin']
        except TransportError as error:
            if error.status == 401:
                self.native.data['revoked'] = True
                self.native.save()
            raise
        return transport

    def assignment(self, transport):
        query = urlencode({'renderer': renderer_identity(), 'resource_profile': PROFILE})
        value = transport.json('/api/v2/client/assignment?' + query)
        self.native.validate_assignment(value)
        validate_metadata(value['publication'])
        return value

    def synchronize(self, *, full_resync=False):
        transport = self._online_authority()
        assignment = self.assignment(transport)
        package_id = assignment['publication']['package_id']
        active = PublicationStore(self.store).active()
        if active is not None and active.name == package_id:
            # Reverify accepted package and locally pinned renderer without artifact GETs.
            self.native.accepted(package_id)
            self.native.accept(assignment)
            return package_id
        package = self.capture.fetch(assignment, transport, full_resync=full_resync)
        # Long capture cannot preserve stale/expired authority or an obsolete assignment.
        transport = self._online_authority()
        fresh = self.assignment(transport)
        if encode(fresh) != encode(assignment):
            raise PackageError('assignment_changed_before_admission')
        self.native.accept(fresh)
        install_for_display(package, self.store, self.cache, mode='tv')
        return package_id

    def queue_ready(self, run):
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
        store = PublicationStore(self.store)
        active = store.active()
        if active is None:
            raise PackageError('no_publication')
        self.native.accepted(active.name)
        from .coordinator import _confirmed_view
        previous = _confirmed_view(self.store, self.cache, self.state, mode)
        if previous is not None:
            self.native.accepted(_view_identity(previous))
        with display_session(self.store, self.cache, self.state, self.profile, self.shell, mode=mode) as run:
            self.native.accepted(_view_identity(run.view))
            self.queue_ready(run)
            yield run


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
            emit({'result': 'identity', 'renderer_build': renderer_identity(), 'python': sys.version,
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
            else:
                if not 5 <= args.interval <= 60:
                    raise PackageError('invalid_poll_interval')
                delay = args.interval
                if PublicationStore(client.store).active() is None:
                    client.synchronize()
                with client.display(args.mode) as native:
                    emit({'result': 'ready', 'package_id': _view_identity(native.view), 'session': native.session})
                    stop = client.root / 'control/stop.request'
                    while native.process.poll() is None and not stop.exists():
                        try:
                            client.flush_ready()
                            client.synchronize()
                            target = PublicationStore(client.store).active()
                            client.native.accepted(target.name)
                            native.switch_to_active()
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
