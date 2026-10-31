"""Local Windows publication storage; no network, renderer or server credentials."""
from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import tempfile

from .compatibility import EVENTS_RUNTIME
from .exporter import PackageError, _is_link, _json, _plain_path, _read_stable, _stream_stable, verify_package

DEFAULT_STORE_BYTES = 256 * 1024 * 1024
POINTER_RESERVE_BYTES = 64 * 1024


class _ExpectedFileWriter:
    def __init__(self, stream, maximum):
        self.stream = stream
        self.remaining = maximum

    def write(self, block):
        if len(block) > self.remaining:
            raise PackageError('source_changed')
        self.stream.write(block)
        self.remaining -= len(block)


def _directory(path):
    path = Path(path).absolute()
    for item in (path, *path.parents):
        if item.exists() and (_is_link(item.lstat()) or not item.is_dir()):
            raise PackageError('unsafe_store')
    path.mkdir(parents=True, exist_ok=True)
    return path


def _atomic_write(path, payload):
    descriptor, temporary = tempfile.mkstemp(prefix='.pointer-', dir=path.parent)
    try:
        with os.fdopen(descriptor, 'wb') as output:
            output.write(payload)
            output.flush()
            os.fsync(output.fileno())
        os.replace(temporary, path)
    finally:
        Path(temporary).unlink(missing_ok=True)


class PublicationStore:
    def __init__(self, root, *, runtime=EVENTS_RUNTIME, max_bytes=DEFAULT_STORE_BYTES):
        if type(max_bytes) is not int or max_bytes <= POINTER_RESERVE_BYTES:
            raise ValueError('Invalid store bound')
        self.root = Path(root).absolute()
        self.runtime = runtime
        self.max_bytes = max_bytes

    @contextmanager
    def _lease(self):
        if os.name != 'nt':
            raise PackageError('unsupported_store_platform')
        import msvcrt

        _directory(self.root)
        lock = self.root / 'store.lock'
        if lock.exists():
            _plain_path(self.root, 'store.lock')
        with lock.open('a+b') as stream:
            stream.seek(0, os.SEEK_END)
            if stream.tell() == 0:
                stream.write(b'0')
                stream.flush()
            stream.seek(0)
            try:
                msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
            except OSError:
                raise PackageError('store_busy') from None
            try:
                yield
            finally:
                stream.seek(0)
                msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)

    def _pointer(self, name):
        path = self.root / name
        if not path.exists():
            return None
        path = _plain_path(self.root, name)
        with path.open('rb') as stream:
            payload = stream.read(4097)
        if len(payload) > 4096:
            raise PackageError('invalid_store_pointer')
        data = json.loads(payload)
        if not isinstance(data, dict) or set(data) != {'schema_version', 'current', 'previous'}:
            raise PackageError('invalid_store_pointer')
        if type(data['schema_version']) is not int or data['schema_version'] != 1:
            raise PackageError('invalid_store_pointer')
        for field in ('current', 'previous'):
            value = data[field]
            if value is None and field == 'previous':
                continue
            if not isinstance(value, str) or re.fullmatch('[0-9a-f]{64}', value) is None:
                raise PackageError('invalid_store_pointer')
        return data

    def _resolve(self):
        found = False
        for name in ('active.json', 'active.backup.json'):
            try:
                state = self._pointer(name)
                if state is None:
                    continue
                found = True
                for identity in (state['current'], state['previous']):
                    if identity is None:
                        continue
                    path = self.root / 'revisions' / identity
                    try:
                        manifest = verify_package(path, runtime=self.runtime)
                        if hashlib.sha256(_json(manifest)).hexdigest() == identity:
                            return identity, path
                    except (PackageError, OSError, ValueError):
                        continue
            except (OSError, ValueError, TypeError, RecursionError):
                found = True
        if found:
            raise PackageError('no_valid_publication')
        return None, None

    def active(self):
        """Reverify content on restart; return None before first publication."""
        try:
            with self._lease():
                return self._resolve()[1]
        except PackageError:
            raise
        except (OSError, ValueError):
            raise PackageError('store_failed') from None

    def _usage(self):
        total = 0
        for parent, directories, files in os.walk(self.root, followlinks=False):
            for name in directories + files:
                path = Path(parent) / name
                if _is_link(path.lstat()):
                    raise PackageError('unsafe_store')
            total += sum((Path(parent) / name).stat().st_size for name in files)
        return total

    def install(self, source, *, pre_activate=None):
        """Install atomically; optional local preflight runs under the writer lease."""
        staging = None
        try:
            with self._lease():
                revisions = _directory(self.root / 'revisions')
                previous, _ = self._resolve()
                source = Path(source).absolute()
                manifest = verify_package(source, runtime=self.runtime)
                payload = _json(manifest)
                identity = hashlib.sha256(payload).hexdigest()
                destination = revisions / identity
                if destination.exists():
                    if verify_package(destination, runtime=self.runtime) != manifest:
                        raise PackageError('stored_revision_mismatch')
                else:
                    needed = sum(entry['size'] for entry in manifest['files']) + len(payload)
                    if self._usage() + needed + POINTER_RESERVE_BYTES > self.max_bytes:
                        raise PackageError('store_limit')
                    if shutil.disk_usage(self.root).free < needed + POINTER_RESERVE_BYTES:
                        raise PackageError('store_disk_full')
                    staging = Path(tempfile.mkdtemp(prefix='.incoming-', dir=self.root))
                    for entry in manifest['files']:
                        target = staging / entry['path']
                        target.parent.mkdir(parents=True, exist_ok=True)
                        with target.open('xb') as output:
                            size, witness = _stream_stable(
                                source, entry['path'], _ExpectedFileWriter(output, entry['size']))
                            output.flush()
                            os.fsync(output.fileno())
                        if size != entry['size'] or witness[3] != entry['sha256']:
                            raise PackageError('source_changed')
                    with (staging / 'manifest.json').open('xb') as output:
                        output.write(payload)
                        output.flush()
                        os.fsync(output.fileno())
                    if verify_package(staging, runtime=self.runtime) != manifest:
                        raise PackageError('source_changed')
                    current_manifest, _ = _read_stable(source, 'manifest.json')
                    if json.loads(current_manifest) != manifest:
                        raise PackageError('source_changed')
                    staging.rename(destination)
                    staging = None
                if pre_activate is not None:
                    # The client must prepare its view before changing publication authority.
                    # This callback must not re-enter this store or wait on network/UI.
                    pre_activate(destination)
                    if verify_package(destination, runtime=self.runtime) != manifest:
                        raise PackageError('source_changed')
                if previous == identity:
                    return destination
                if previous is not None:
                    backup = {'schema_version': 1, 'current': previous, 'previous': None}
                    _atomic_write(self.root / 'active.backup.json', _json(backup))
                state = {'schema_version': 1, 'current': identity, 'previous': previous}
                _atomic_write(self.root / 'active.json', _json(state))
                return destination
        except PackageError:
            raise
        except (OSError, ValueError, TypeError, KeyError, RecursionError):
            raise PackageError('store_failed') from None
        finally:
            if staging is not None:
                try:
                    shutil.rmtree(staging)
                except OSError:
                    raise PackageError('store_cleanup_failed') from None
