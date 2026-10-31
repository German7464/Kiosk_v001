"""Own one native display process, accepting only fresh renderer readiness."""
from contextlib import contextmanager
from dataclasses import dataclass, field
import hashlib
import json
from pathlib import Path
import re
import subprocess
import time
import threading
import uuid

from kiosk.publication.exporter import PackageError, _json, _plain_path, verify_package
from kiosk.publication.store import PublicationStore, _atomic_write, _directory
from .cache import prepare_cached_view, renderer_identity, verify_cached_view


@dataclass
class DisplayRun:
    process: subprocess.Popen
    view: Path
    fallback: bool
    store: Path = None
    cache: Path = None
    state: Path = None
    profile: Path = None
    session: str = ''
    mode: str = 'kiosk'
    pending: tuple = None
    failed_view: str = ''
    receipt_pending: bool = False
    _switch_lock: object = field(default_factory=threading.Lock, repr=False)

    def switch_to_active(self, *, timeout=20, retry=False):
        if not self._switch_lock.acquire(blocking=False):
            raise PackageError('display_switch_busy')
        try:
            return self._switch_to_active(timeout=timeout, retry=retry)
        except PackageError:
            raise
        except (OSError, ValueError, KeyError, TypeError, RecursionError):
            raise PackageError('display_switch_storage_failed') from None
        finally:
            self._switch_lock.release()

    def _switch_to_active(self, *, timeout=20, retry=False):
        """One staged native request; a timeout retains its ID for later reconciliation."""
        if isinstance(timeout, bool) or not isinstance(timeout, (int, float)) or not 0.1 <= timeout <= 60:
            raise ValueError('Invalid switch timeout')
        if self.process.poll() is not None:
            raise PackageError('display_engine_exited')
        if self.receipt_pending:
            _save_ready(self.view, self.state, self.mode, self.process)
            self.receipt_pending = False
        if self.pending is None:
            target = prepare_cached_view(self.store, self.cache, mode=self.mode)
            if target == self.view:
                if self.receipt_pending:
                    _save_ready(self.view, self.state, self.mode, self.process)
                    self.receipt_pending = False
                return False
            if self.failed_view == target.parent.name and not retry:
                raise PackageError('display_switch_refused')
            identity = _view_identity(target)
            token = uuid.uuid4().hex
            _atomic_write(self.profile / 'display-command.json', _json(
                {'session_id': self.session, 'request_id': token, 'view': target.parent.name,
                 'package_sha256': identity, 'mode': self.mode}))
            self.pending = (token, target, identity)
        token, target, identity = self.pending
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if self.process.poll() is not None:
                raise PackageError('display_engine_exited')
            try:
                status = _read_json(self.profile, 'display-status.json')
            except (OSError, ValueError, TypeError, RecursionError):
                status = None
            if (isinstance(status, dict) and status.get('session_id') == self.session and
                    type(status.get('process_id')) is int and status['process_id'] == self.process.pid and
                    status.get('switch_request_id') == token):
                if status.get('switch_state') == 'failed':
                    self.failed_view = target.parent.name
                    self.pending = None
                    raise PackageError('display_switch_failed')
                if (status.get('switch_state') == 'ready' and status.get('renderer_ready') is True and
                        status.get('navigation_success') is True and status.get('startup_failed') is False and
                        status.get('view_key') == target.parent.name and status.get('package_sha256') == identity and
                        status.get('mode') == self.mode):
                    self.view = target
                    self.fallback = False
                    self.pending = None
                    self.failed_view = ''
                    self.receipt_pending = True
                    _save_ready(target, self.state, self.mode, self.process)
                    self.receipt_pending = False
                    return True
            time.sleep(min(0.1, max(0, deadline - time.monotonic())))
        raise PackageError('display_switch_timeout')


def _view_identity(view):
    with _plain_path(view.parent, 'view.json').open('rb') as stream:
        descriptor = json.loads(stream.read(2 * 1024 * 1024 + 1))
    identity = descriptor['package_sha256']
    if not isinstance(identity, str) or not re.fullmatch('[0-9a-f]{64}', identity):
        raise PackageError('invalid_display_state')
    return identity


def _save_ready(view, state, mode, process):
    identity = _view_identity(view)
    verify_cached_view(view.parent, package_identity=identity, mode=mode)
    if process.poll() is not None:
        raise PackageError('display_engine_exited')
    receipt = {'schema_version': 1, 'package_sha256': identity, 'view': view.parent.name,
               'mode': mode, 'renderer_build': renderer_identity()}
    _atomic_write(state / ('last-ready-' + mode + '.json'), _json(receipt))


def _separate_roots(*roots):
    paths = [Path(path).absolute() for path in roots]
    for i, path in enumerate(paths):
        for other in paths[i + 1:]:
            if path == other or path in other.parents or other in path.parents:
                raise PackageError('overlapping_display_storage')
    return paths


def _read_json(root, name):
    path = _plain_path(root, name)
    with path.open('rb') as stream:
        payload = stream.read(4097)
    if len(payload) > 4096:
        raise PackageError('invalid_display_state')
    return json.loads(payload)


def _confirmed_view(store, cache, state, mode):
    """Only a previously confirmed view from this renderer build can be retried."""
    try:
        receipt = _read_json(state, 'last-ready-' + mode + '.json')
        if (not isinstance(receipt, dict) or set(receipt) !=
                {'schema_version', 'package_sha256', 'view', 'mode', 'renderer_build'} or
                type(receipt['schema_version']) is not int or receipt['schema_version'] != 1 or
                receipt['mode'] != mode or receipt['renderer_build'] != renderer_identity()):
            return None
        for field in ('package_sha256', 'view'):
            if not isinstance(receipt[field], str) or not re.fullmatch('[0-9a-f]{64}', receipt[field]):
                return None
        package = store / 'revisions' / receipt['package_sha256']
        if hashlib.sha256(_json(verify_package(package))).hexdigest() != receipt['package_sha256']:
            return None
        return verify_cached_view(cache / receipt['view'], package_identity=receipt['package_sha256'], mode=mode)
    except (PackageError, OSError, ValueError, TypeError, KeyError, RecursionError):
        return None


def _spawn(shell, view, profile, session):
    return subprocess.Popen([str(shell), '--view', str(view.parent), '--profile', str(profile), '--session', session,
                             '--cache-root', str(view.parent.parent)],
                            stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def _stop(process):
    if process.poll() is None:
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)


def _await_ready(process, profile, session, timeout):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise PackageError('display_start_failed')
        try:
            status = _read_json(profile, 'display-status.json')
        except (OSError, ValueError, TypeError, RecursionError):
            # Atomic replacement can race a read; an old or malformed report proves nothing.
            status = None
        if (isinstance(status, dict) and status.get('session_id') == session and
                type(status.get('process_id')) is int and status['process_id'] == process.pid):
            if status.get('startup_failed') is True:
                raise PackageError('display_start_failed')
            if status.get('navigation_success') is True and status.get('renderer_ready') is True:
                return
        time.sleep(min(0.1, max(0, deadline - time.monotonic())))
    raise PackageError('display_start_timeout')


@contextmanager
def display_session(store_root, cache_root, state_root, profile_root, shell, *, mode='kiosk', startup_timeout=20):
    """Hold coordinator ownership until exit; try at most current then last confirmed."""
    if mode not in ('kiosk', 'tv'):
        raise PackageError('unsupported_display_mode')
    if isinstance(startup_timeout, bool) or not isinstance(startup_timeout, (int, float)) or not 0.1 <= startup_timeout <= 60:
        raise ValueError('Invalid startup timeout')
    store, cache, state, profile = _separate_roots(store_root, cache_root, state_root, profile_root)
    shell = Path(shell).absolute()
    yielded = False
    try:
        _plain_path(shell.parent, shell.name)
        if shell.suffix.lower() != '.exe':
            raise PackageError('invalid_display_shell')
        with PublicationStore(state)._lease():
            _directory(profile)
            if PublicationStore(profile)._usage() > 256 * 1024 * 1024:
                raise PackageError('display_profile_limit')
            previous = _confirmed_view(store, cache, state, mode)
            try:
                current = prepare_cached_view(store, cache, mode=mode)
            except PackageError:
                if previous is None:
                    raise
                current = None
            choices = [(current, False)] if current is not None else []
            if previous is not None and previous != current:
                choices.append((previous, True))
            for index, (view, fallback) in enumerate(choices):
                process = None
                try:
                    token = uuid.uuid4().hex
                    process = _spawn(shell, view, profile, token)
                    _await_ready(process, profile, token, startup_timeout)
                    _save_ready(view, state, mode, process)
                except (PackageError, OSError, ValueError, KeyError, TypeError, RecursionError):
                    if process is not None:
                        _stop(process)
                    if index + 1 < len(choices):
                        continue
                    raise PackageError('display_unavailable') from None
                except BaseException:
                    if process is not None:
                        _stop(process)
                    raise
                try:
                    yielded = True
                    yield DisplayRun(process, view, fallback, store, cache, state, profile, token, mode)
                finally:
                    _stop(process)
                return
    except PackageError:
        raise
    except (OSError, ValueError, KeyError, TypeError, RecursionError):
        if yielded:
            raise
        raise PackageError('display_coordinator_failed') from None

def _publication_fingerprint(store):
    values = []
    for name in ('active.json', 'active.backup.json'):
        try:
            values.append(_read_json(store, name))
        except (OSError, ValueError, TypeError, RecursionError):
            values.append(None)
    return hashlib.sha256(_json(values)).hexdigest()


def follow_publications(run, *, interval=2):
    """Poll only small pointers; reconcile a timed-out command at most once more."""
    if isinstance(interval, bool) or not isinstance(interval, (int, float)) or not .1 <= interval <= 60:
        raise ValueError('Invalid watch interval')
    signature = None
    reconciliations = 0
    while run.process.poll() is None:
        current = _publication_fingerprint(run.store)
        changed = current != signature
        if changed:
            signature = current
            reconciliations = 0
        if changed or ((run.pending is not None or run.receipt_pending) and reconciliations < 2):
            try:
                switched = run.switch_to_active()
                if switched:
                    yield {'result': 'switched', 'mode': run.mode}
                    signature = None  # A newer publication may have arrived while awaiting readiness.
            except PackageError as error:
                if run.pending is not None or run.receipt_pending:
                    reconciliations += 1
                if str(error) == 'display_switch_failed':
                    signature = None  # A prior timed-out request may have failed after a newer pointer arrived.
                if str(error) != 'display_switch_refused':
                    yield {'result': 'switch_error', 'mode': run.mode, 'code': str(error)}
        time.sleep(interval)
