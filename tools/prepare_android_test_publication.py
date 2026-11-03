"""Prepare isolated Android test inputs; evidence is not a signature or admission grant."""
import argparse
import hashlib
import json
from pathlib import Path
import platform
import warnings

import PIL
from PIL import Image

from kiosk.display.cache import prepare_package_view, renderer_identity, verify_cached_view
from kiosk.publication import exporter
from kiosk.publication.exporter import PackageError, _json, _plain_path, _stream_stable, verify_package
from kiosk.publication.store import PublicationStore


def inventory(directory):
    result = {}
    for path in sorted(directory.rglob('*')):
        if path.is_file():
            name = path.relative_to(directory).as_posix()
            size, witness = _stream_stable(directory, name)
            result[name] = {'size': size, 'sha256': witness[3]}
    return result


def evidence(root, package, views):
    manifest = verify_package(package)
    identity = hashlib.sha256(_json(manifest)).hexdigest()
    artifacts = {}
    for mode, path in views.items():
        verify_cached_view(path, package_identity=identity, mode=mode)
        artifacts[mode] = {'path': path.relative_to(root).as_posix(), 'files': inventory(path)}
    return {
        'scope': 'local_test_preparation_only_not_authorization',
        'package_identity': identity,
        'raw_manifest_sha256': hashlib.sha256((package / 'manifest.json').read_bytes()).hexdigest(),
        'package': {'path': package.relative_to(root).as_posix(), 'files': inventory(package)},
        'renderer_identity': renderer_identity(),
        'preparer_sources': {name: hashlib.sha256(path.read_bytes()).hexdigest()
                             for name, path in [('exporter', Path(exporter.__file__)),
                                                ('test_preparer', Path(__file__))]},
        'views': artifacts,
        'environment': {'python': platform.python_version(), 'pillow': PIL.__version__,
                        'pillow_max_image_pixels': Image.MAX_IMAGE_PIXELS,
                        'warning_filters': [
                            [action, getattr(message, 'pattern', message),
                             category.__module__ + '.' + category.__qualname__,
                             getattr(module, 'pattern', module), lineno]
                            for action, message, category, module, lineno in warnings.filters]},
        'limitations': ['not_source_authentication', 'not_full_pixel_load_evidence',
                        'not_android_capability_evidence', 'not_power_loss_evidence'],
    }


def prepare(source, destination):
    destination = Path(destination).absolute()
    # Validate before creating output; never replace an existing user's directory.
    verify_package(source)
    destination.mkdir(parents=False, exist_ok=False)
    package = PublicationStore(destination / 'store').install(source)
    views = {mode: prepare_package_view(package, destination / 'cache', mode=mode).parent
             for mode in ('kiosk', 'tv')}
    report = evidence(destination, package, views)
    # This is the completion marker. Failed preparation leaves no usable receipt.
    payload = _json(report)
    if len(payload) > 4 * 1024 * 1024:
        raise PackageError('test_evidence_limit')
    with (destination / 'preparation.json').open('xb') as stream:
        stream.write(payload)
    return hashlib.sha256(payload).hexdigest(), report


def verify_preparation(destination, expected_sha256):
    root = Path(destination).absolute()
    if not isinstance(expected_sha256, str) or len(expected_sha256) != 64 or any(
            char not in '0123456789abcdef' for char in expected_sha256):
        raise PackageError('invalid_test_confirmation')
    receipt = _plain_path(root, 'preparation.json')
    with receipt.open('rb') as stream:
        payload = stream.read(4 * 1024 * 1024 + 1)
    if len(payload) > 4 * 1024 * 1024 or hashlib.sha256(payload).hexdigest() != expected_sha256:
        raise PackageError('test_confirmation_mismatch')
    report = json.loads(payload)
    identity = report['package_identity']
    if not isinstance(identity, str) or len(identity) != 64 or any(c not in '0123456789abcdef' for c in identity):
        raise PackageError('invalid_test_confirmation')
    package = root / 'store' / 'revisions' / identity
    views = {}
    for mode in ('kiosk', 'tv'):
        path = report['views'][mode]['path']
        parts = path.split('/')
        if len(parts) != 2 or parts[0] != 'cache' or len(parts[1]) != 64 or any(
                c not in '0123456789abcdef' for c in parts[1]):
            raise PackageError('invalid_test_confirmation')
        views[mode] = root.joinpath(*parts)
    if evidence(root, package, views) != report:
        raise PackageError('test_preparation_changed')
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--destination', type=Path, required=True)
    action = parser.add_mutually_exclusive_group(required=True)
    action.add_argument('--package', type=Path)
    action.add_argument('--confirm-sha256', help='independently obtained preparation.json SHA256')
    args = parser.parse_args()
    try:
        if args.package:
            digest, report = prepare(args.package, args.destination)
            result = {'result': 'test_prepared', 'confirmation_sha256': digest,
                      'package_identity': report['package_identity']}
        else:
            report = verify_preparation(args.destination, args.confirm_sha256)
            result = {'result': 'test_reverified', 'package_identity': report['package_identity']}
        print(json.dumps(result))
        return 0
    except (PackageError, OSError, ValueError, KeyError, TypeError):
        print(json.dumps({'result': 'error', 'code': 'test_preparation_failed'}))
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
