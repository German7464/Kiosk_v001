"""Single-owner native connection workflow; no new authority or wire protocol."""
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
import queue
import threading
import time

from kiosk.delivery.protocol import decode, sha
from kiosk.publication.exporter import PackageError
from kiosk.publication.store import PublicationStore, _atomic_write
from .delivery_authority import bootstrap, origin
from .delivery_client import Client
from .delivery_transport import TransportError


class Cancelled(Exception):
    pass


_REVIEW_ONLY = object()


def public_input(raw, address, *, now=None, confirmation=_REVIEW_ONLY, confirmed=False):
    if not isinstance(raw, bytes) or not 1 <= len(raw) <= 16384:
        raise PackageError('bootstrap_size')
    origin(address)
    value = bootstrap(decode(raw), int(time.time()) if now is None else now)
    if value['origin'] != address:
        raise PackageError('origin_mismatch')
    if confirmation is not _REVIEW_ONLY and (not confirmed or confirmation != sha(raw)):
        raise PackageError('independent_bootstrap_confirmation_required')
    return value


def confirmed_time(value, checked):
    if not checked:
        raise PackageError('time_confirmation_required')
    try:
        moment = datetime.fromisoformat(value.replace('Z', '+00:00'))
        if moment.tzinfo is None:
            raise ValueError()
        seconds = int(moment.timestamp())
    except (ValueError, OverflowError, AttributeError):
        raise PackageError('time_confirmation_refused') from None
    if abs(seconds - time.time()) > 60:
        raise PackageError('time_confirmation_refused')
    return seconds


def error_status(error):
    """Only fixed labels cross the worker/UI boundary, never arbitrary exception text."""
    status = getattr(error, 'status', 0)
    code = str(error)
    if code in ('time_confirmation_required', 'uncertain_time', 'time_confirmation_refused'):
        return 'time_required'
    if status == 403:
        return 'denied'
    if status == 410:
        return 'expired'
    if status == 401 or code == 'credential_revoked':
        return 'access_refused'
    if code in ('bootstrap_expired_or_future', 'credential_expired', 'admission_authority_expired',
                'trust_binding_or_time_refused'):
        return 'expired'
    if code == 'no_publication':
        return 'no_content'
    if isinstance(error, TransportError):
        return 'network_unavailable' if not status else 'server_refused'
    return 'operation_refused'


class _Response:
    def __init__(self, response, stop):
        self.response, self.stop = response, stop

    def __getattr__(self, name):
        return getattr(self.response, name)

    def read(self, size=-1):
        if self.stop.is_set():
            raise Cancelled()
        return self.response.read(size)


class InteractiveClient(Client):
    def __init__(self, *args, stop, **kwargs):
        self.stop = stop
        super().__init__(*args, **kwargs)

    def connect(self):
        transport = super().connect()
        original = transport.response

        @contextmanager
        def response(*args, **kwargs):
            if self.stop.is_set():
                raise Cancelled()
            with original(*args, **kwargs) as current:
                if self.stop.is_set():
                    raise Cancelled()
                yield _Response(current, self.stop)

        transport.response = response
        return transport


class Connection:
    """Tk consumes safe snapshots; one cancellable thread owns native state/network/display."""
    def __init__(self, root, shell, *, audit=None, client_factory=InteractiveClient):
        self.root, self.shell, self.audit = Path(root), Path(shell), audit
        self.factory = client_factory
        self.events = queue.Queue()
        self.stop = threading.Event()
        self.thread = None
        self._guard = threading.Lock()

    @property
    def busy(self):
        return self.thread is not None and self.thread.is_alive()

    def emit(self, state, **facts):
        self.events.put(dict(state=state, **facts))

    def cancel(self):
        self.stop.set()

    def start(self, action, **options):
        with self._guard:
            if self.busy:
                return False
            self.stop.clear()
            self.thread = threading.Thread(target=self._work, args=(action, options), daemon=False)
            self.thread.start()
            return True

    def _facts(self, client):
        data = client.native.data
        anchor = data.get('bootstrap', {})
        binding = data.get('binding', {})
        credential = data.get('credential')
        active = PublicationStore(client.store).active()
        return dict(origin=anchor.get('origin', ''), group=anchor.get('group_id', ''),
                    server=anchor.get('server_id', ''), device=binding.get('device_id', ''),
                    nonce=binding.get('nonce', ''), request=binding.get('request_id', ''),
                    profile=binding.get('profile', ''), saved=bool(anchor),
                    approved=bool(credential), revoked=bool(data.get('revoked')),
                    credential_expires=credential['expires_at'] if credential else None,
                    mode=data.get('ui_mode', 'tv'),
                    content=active.name if active else None)

    def _work(self, action, options):
        try:
            if action == 'discover':
                # Same worker/lease as enrollment and display; discovery cannot fork
                # a competing synchronization owner or inspect/change native state.
                from kiosk.discovery import search
                with PublicationStore(self.root / 'private')._lease():
                    hints = search(self.stop)
                self.emit('discovery_cancelled' if self.stop.is_set() else 'discovered', hints=hints)
                return
            # New inputs are validated before creating/changing private state or sending anything.
            raw = options.get('raw')
            if raw is not None:
                anchor = public_input(raw, options['address'], confirmation=options['digest'],
                                      confirmed=options['confirmed'])
                if not options.get('utc') or abs(options['utc'] - time.time()) > 60:
                    raise PackageError('time_confirmation_required')
            client = self.factory(self.root, self.shell, stop=self.stop, audit=self.audit)
            with client.ownership():
                if self.stop.is_set():
                    raise Cancelled()
                if raw is not None and client.native.data:
                    if client.native.data.get('bootstrap') != anchor:
                        raise PackageError('saved_connection_preserved')
                if action == 'inspect':
                    self.emit('saved', **self._facts(client))
                elif action == 'time':
                    if not client.native.data.get('bootstrap'):
                        raise PackageError('confirmed_bootstrap_required')
                    client.native.confirm_time(options['utc'])
                    self.emit('time_confirmed', **self._facts(client))
                elif action == 'enroll':
                    path = self.root / 'control' / 'confirmed-bootstrap.json'
                    if raw is not None and not client.native.data:
                        _atomic_write(path, raw)
                    try:
                        self._enroll(client, path if raw is not None else None, options)
                    finally:
                        if path.exists():
                            path.unlink()
                elif action == 'display':
                    self._display(client, options['mode'], options['online'])
                else:
                    raise ValueError('unknown_action')
        except Cancelled:
            self.emit('cancelled')
        except Exception as error:
            self.emit('discovery_failed' if action == 'discover' else error_status(error), http=getattr(error, 'status', 0))
        finally:
            self.emit('idle')

    def _enroll(self, client, path, options):
        while not self.stop.is_set():
            result = client.enroll(path, options.get('digest'), options.get('utc'))
            if self.stop.is_set():
                raise Cancelled()
            self.emit(result['result'], code=result.get('user_code', ''), **self._facts(client))
            if result['result'] == 'approved':
                return
            if self.stop.wait(5):
                raise Cancelled()

    def _display(self, client, mode, online):
        if mode not in ('tv', 'kiosk'):
            raise PackageError('invalid_mode')
        if PublicationStore(client.store).active() is None:
            if not online:
                raise PackageError('no_publication')
            self.emit('synchronizing')
            client.synchronize()
        if self.stop.is_set():
            raise Cancelled()
        with client.display(mode) as run:
            client.native.data['ui_mode'] = mode
            client.native.save()
            self.emit('ready', online=online, **self._facts(client))
            delay = 5
            while not self.stop.is_set() and run.process.poll() is None:
                if online:
                    try:
                        client.flush_ready()
                        client.synchronize()
                        run.switch_to_active()
                        client.queue_ready(run)
                        client.flush_ready()
                        self.emit('connected', **self._facts(client))
                        delay = 5
                    except Cancelled:
                        raise
                    except Exception as error:
                        self.emit(error_status(error), http=getattr(error, 'status', 0), retained=True)
                        if error_status(error) in ('access_refused', 'expired', 'time_required'):
                            online = False  # Stop new admission; keep the existing native window alive.
                        delay = max(5, getattr(error, 'retry_after', min(60, delay * 2)))
                self.stop.wait(delay if online else .25)
        self.emit('display_closed')
