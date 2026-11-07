"""One bounded durable candidate; verified-byte reuse and strict v1 ranges."""
import http.client
import os
from pathlib import Path
import shutil
import time
from urllib.parse import quote

from PIL import Image

from kiosk.delivery.protocol import LIMITS, PROFILE, decode, encode, fields, digest, sha
from kiosk.publication.exporter import PackageError, _is_link, _path_name, _plain_path, _references, _stream_stable, _json, verify_package
from kiosk.publication.renderer import ASSETS
from kiosk.publication.store import _atomic_write
from .cache import renderer_identity, verify_cached_view
from .delivery_authority import positive
from .delivery_transport import TransportError


def validate_metadata(value):
    fields(value, 'version package_id revision raw_manifest_sha256 renderer resource_profile limits windows_images package kiosk tv')
    if type(value['version']) is not int or value['version'] != 1 or value['resource_profile'] != PROFILE:
        raise PackageError('unsupported_profile')
    digest(value['package_id'])
    digest(value['raw_manifest_sha256'])
    if not isinstance(value['revision'], (str, int)) or isinstance(value['revision'], bool):
        raise PackageError('invalid_revision')
    if value['limits'] != LIMITS or any(type(v) is not int for v in value['limits'].values()):
        raise PackageError('unsupported_limits')
    expected = {'build_id': renderer_identity(), 'js_sha256': sha((ASSETS / 'events.js').read_bytes()),
                'css_sha256': sha((ASSETS / 'events.css').read_bytes())}
    if value['renderer'] != expected:
        raise PackageError('unsupported_renderer')
    total, count = 0, 0
    for group in ('package', 'kiosk', 'tv'):
        fields(value[group], 'files')
        entries = value[group]['files']
        if not isinstance(entries, list) or not 1 <= len(entries) <= 10001:
            raise PackageError('invalid_inventory')
        names = set()
        for entry in entries:
            fields(entry, 'path size sha256')
            name = _path_name(entry['path'])
            size = positive(entry['size'], zero=True)
            digest(entry['sha256'])
            if name.casefold() in names or size > 64 * 1024 * 1024:
                raise PackageError('invalid_inventory')
            names.add(name.casefold())
            total += size
            count += 1
        if any('/'.join(name.split('/')[:i]) in names for name in names for i in range(1, len(name.split('/')))):
            raise PackageError('inventory_path_conflict')
    if total > LIMITS['capture_bytes'] or count > LIMITS['capture_files']:
        raise PackageError('capture_limit')
    if not isinstance(value['windows_images'], dict) or len(value['windows_images']) > 10000:
        raise PackageError('invalid_image_inventory')
    return value


class Capture:
    def __init__(self, root, *, reuse_roots=(), audit=None):
        self.root = Path(root)
        self.reuse_roots, self.audit = tuple(map(Path, reuse_roots)), audit
        self.stats = {'reused_files': 0, 'reused_bytes': 0, 'received_bytes': 0, 'resumed_offsets': [], 'restarts': []}

    def inspect(self):
        total, count = 0, 0
        for parent, dirs, files in os.walk(self.root, followlinks=False):
            for name in dirs + files:
                item = Path(parent) / name
                if _is_link(item.lstat()):
                    raise PackageError('unsafe_capture')
                count += 1
                if item.is_file():
                    total += item.stat().st_size
                if total > LIMITS['capture_bytes'] + 2 * 1024 * 1024 or count > LIMITS['capture_files'] * 2 + 16:
                    raise PackageError('capture_limit')
        return total

    def reset(self):
        marker = self.root / 'owner.json'
        self.inspect()
        if any(self.root.iterdir()) and (not marker.is_file() or marker.read_bytes() != encode({'owner': 'windows-delivery-v1'})):
            raise PackageError('unowned_capture')
        work = self.root / 'work'
        if work.exists():
            shutil.rmtree(work)
        (self.root / 'candidate.json').unlink(missing_ok=True)
        _atomic_write(marker, encode({'owner': 'windows-delivery-v1'}))

    def _valid(self, root, name, entry):
        try:
            size, witness = _stream_stable(root, name)
            return size == entry['size'] and witness[3] == entry['sha256']
        except (OSError, PackageError):
            return False

    def _reuse(self, target, entry):
        for root in self.reuse_roots:
            if not root.exists():
                continue
            inspected = 0
            for parent, dirs, files in os.walk(root, followlinks=False):
                for name in dirs:
                    if _is_link((Path(parent) / name).lstat()):
                        raise PackageError('unsafe_reuse')
                for name in files:
                    inspected += 1
                    if inspected > 60000:
                        raise PackageError('reuse_limit')
                    source = Path(parent) / name
                    relative = source.relative_to(root).as_posix()
                    if source.stat().st_size != entry['size'] or not self._valid(root, relative, entry):
                        continue
                    # Copy, rehash and fsync. Never hardlink or mutate retained source bytes.
                    source = _plain_path(root, relative)
                    with source.open('rb') as incoming, target.open('wb') as outgoing:
                        copied = 0
                        while block := incoming.read(65536):
                            copied += len(block)
                            if copied > entry['size']:
                                raise PackageError('reuse_changed')
                            outgoing.write(block)
                        outgoing.flush()
                        os.fsync(outgoing.fileno())
                    if not self._valid(target.parent, target.name, entry):
                        raise PackageError('reuse_changed')
                    self.stats['reused_files'] += 1
                    self.stats['reused_bytes'] += entry['size']
                    return True
        return False

    def fetch(self, assignment, transport, *, full_resync=False):
        metadata = validate_metadata(assignment['publication'])
        identity = sha(encode(assignment))
        self.inspect()
        journal_path = self.root / 'candidate.json'
        journal = decode(journal_path.read_bytes()) if journal_path.exists() else None
        if full_resync or not journal or journal.get('assignment_sha256') != identity:
            self.reset()
            journal = {'assignment_sha256': identity, 'offsets': {}}
            _atomic_write(journal_path, encode(journal))
        elif (self.root / 'owner.json').read_bytes() != encode({'owner': 'windows-delivery-v1'}):
            raise PackageError('unowned_capture')
        work = self.root / 'work'
        for group in ('package', 'kiosk', 'tv'):
            for entry in metadata[group]['files']:
                relative = group + '/' + entry['path']
                target = work / relative
                target.parent.mkdir(parents=True, exist_ok=True)
                self.inspect()
                if shutil.disk_usage(self.root).free < LIMITS['min_free_bytes'] + entry['size']:
                    raise PackageError('capture_disk_full')
                if target.exists():
                    _plain_path(work, relative)
                    if self._valid(work, relative, entry):
                        continue
                else:
                    # Include already captured complete files for cross-mode exact-byte reuse.
                    before = self.reuse_roots
                    self.reuse_roots = before + (work,)
                    try:
                        reused = self._reuse(target, entry)
                    finally:
                        self.reuse_roots = before
                    if reused:
                        continue
                self._download(target, relative, entry, metadata['package_id'], transport, journal, journal_path)
        verify_captured(work, metadata)
        return work / 'package'

    def _download(self, target, relative, entry, package, transport, journal, journal_path):
        for attempt in range(2):
            actual = target.stat().st_size if target.exists() else 0
            saved = journal['offsets'].get(relative, 0)
            positive(saved, zero=True)
            if actual > entry['size'] or saved > entry['size']:
                raise PackageError('impossible_prefix')
            offset = min(actual, saved)
            if actual != offset:
                with target.open('r+b') as stream:
                    stream.truncate(offset)
            if offset == entry['size']:
                offset = 0  # A complete hash mismatch cannot be repaired by a suffix.
            headers = {'Range': f'bytes={offset}-', 'If-Range': '"' + entry['sha256'] + '"'} if offset else {}
            path = '/api/v2/publications/' + package + '/' + quote(relative, safe='/')
            with transport.response(path, headers=headers) as response:
                status = response.status
                if status == 416:
                    self.stats['restarts'].append('range_416')
                    target.write_bytes(b'')
                    journal['offsets'][relative] = 0
                    _atomic_write(journal_path, encode(journal))
                    # Return to the synchronization owner: revalidate authority/assignment
                    # before the next cycle retries only this reset file.
                    raise TransportError('artifact_range_reconcile', 416)
                if status not in (200, 206):
                    retry = response.getheader('Retry-After', '5')
                    raise TransportError('artifact_http_refused', status, int(retry) if retry.isdecimal() else 5)
                if (response.getheader('ETag') != '"' + entry['sha256'] + '"' or
                        response.getheader('Accept-Ranges') != 'bytes' or
                        response.getheader('Content-Type', '').split(';')[0] != 'application/octet-stream'):
                    raise PackageError('artifact_validator_refused')
                if status == 206:
                    if not offset or response.getheader('Content-Range') != f'bytes {offset}-{entry["size"] - 1}/{entry["size"]}':
                        raise PackageError('artifact_range_refused')
                    self.stats['resumed_offsets'].append(offset)
                else:
                    if offset:
                        self.stats['restarts'].append('full_200_after_range')
                    offset = 0
                    if response.getheader('Content-Range') is not None:
                        raise PackageError('artifact_range_refused')
                remaining = entry['size'] - offset
                if response.getheader('Content-Length') != str(remaining):
                    raise PackageError('artifact_length_refused')
                with target.open('r+b' if target.exists() else 'w+b') as outgoing:
                    outgoing.truncate(offset)
                    outgoing.seek(offset)
                    while remaining:
                        try:
                            block = response.read(min(65536, remaining))
                        except http.client.IncompleteRead as error:
                            block = error.partial
                        if not block:
                            raise TransportError('artifact_interrupted')
                        if len(block) > remaining:
                            raise PackageError('artifact_overflow')
                        outgoing.write(block)
                        outgoing.flush()
                        os.fsync(outgoing.fileno())
                        remaining -= len(block)
                        offset += len(block)
                        journal['offsets'][relative] = offset
                        _atomic_write(journal_path, encode(journal))
                        self.stats['received_bytes'] += len(block)
                    if response.read(1):
                        raise PackageError('artifact_overflow')
            if self._valid(target.parent, target.name, entry):
                return
            target.write_bytes(b'')
            journal['offsets'][relative] = 0
            _atomic_write(journal_path, encode(journal))
            self.stats['restarts'].append('hash_mismatch')
        raise PackageError('artifact_hash_refused')


def verify_captured(work, metadata):
    package = work / 'package'
    manifest = verify_package(package)
    if (sha(_json(manifest)) != metadata['package_id'] or manifest['revision'] != metadata['revision'] or
            sha((package / 'manifest.json').read_bytes()) != metadata['raw_manifest_sha256']):
        raise PackageError('captured_package_binding_refused')
    for mode in ('kiosk', 'tv'):
        verify_cached_view(work / mode, package_identity=metadata['package_id'], mode=mode)
    data = decode((package / 'data/events.json').read_bytes())
    references = {name[1:] for name in _references(data)} | {'resources/static/img/site_icon.png'}
    if set(metadata['windows_images']) != references:
        raise PackageError('image_binding_refused')
    started = time.monotonic()
    for name in references:
        image_started = time.monotonic()
        path = _plain_path(package, name)
        if metadata['windows_images'][name] != {'sha256': _stream_stable(package, name)[1][3], 'result': 'VERIFIED'}:
            raise PackageError('image_binding_refused')
        with Image.open(path) as image:
            width, height = image.size
            if (image.format not in ('PNG', 'JPEG') or getattr(image, 'n_frames', 1) != 1 or
                    width * height > LIMITS['max_pixels'] or
                    path.stat().st_size + width * height * 8 > LIMITS['max_live_bytes']):
                raise PackageError('unsupported_native_image')
            image.verify()
        with Image.open(path) as image:
            image.load()
        now = time.monotonic()
        if ((now - image_started) * 1000 > LIMITS['per_image_ms'] or
                (now - started) * 1000 > LIMITS['total_image_ms']):
            # Refuse after measured work; this cannot forcibly cancel a native decoder.
            raise PackageError('image_elapsed_budget')
