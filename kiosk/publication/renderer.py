"""Build a local Events view using shipped code, never packaged executable assets."""
import hashlib
import json
from pathlib import Path
import shutil
import tempfile

from jinja2 import Environment, FileSystemLoader, select_autoescape

from .exporter import PackageError, _json, _read_stable, _references, _stream_stable, verify_package
from .store import _ExpectedFileWriter, _directory

ASSETS = Path(__file__).with_name('renderer_assets')
TRANSLATIONS = Path(__file__).parent.parent / 'translations'


def build_view(package, destination, *, mode='kiosk', max_bytes=128 * 1024 * 1024):
    """Build a NEW offline view; activation and WebView integration are separate."""
    if mode not in ('kiosk', 'tv'):
        raise PackageError('unsupported_display_mode')
    if type(max_bytes) is not int or max_bytes <= 0:
        raise ValueError('Invalid view bound')
    destination = Path(destination).absolute()
    staging = None
    try:
        _directory(destination.parent)
        if destination.exists() or destination.is_symlink():
            raise PackageError('destination_exists')
        manifest = verify_package(package)
        payload, _ = _read_stable(package, 'data/events.json')
        entry = next(item for item in manifest['files'] if item['path'] == 'data/events.json')
        if len(payload) != entry['size'] or hashlib.sha256(payload).hexdigest() != entry['sha256']:
            raise PackageError('source_changed')
        data = json.loads(payload)
        language = data['settings'].get('interface_language', 'en')
        language = language if language in ('en', 'ru', 'de') else 'en'
        labels = json.loads((TRANSLATIONS / 'en.json').read_text(encoding='utf-8'))
        labels.update(json.loads((TRANSLATIONS / (language + '.json')).read_text(encoding='utf-8')))
        inventory = {item['path']: item for item in manifest['files']}
        media = {reference: reference[1:] for reference in sorted(_references(data))}
        environment = Environment(loader=FileSystemLoader(ASSETS), autoescape=select_autoescape(['html']))
        bootstrap = {'data': data, 'labels': labels, 'media': media, 'mode': mode}
        html = environment.get_template('events.html').render(
            bootstrap=bootstrap, language=language, title=data['settings'].get('site_title', labels['kiosk.current_events']))
        html_bytes = html.encode('utf-8')
        assets = {name: (ASSETS / name).read_bytes() for name in ('events.css', 'events.js')}
        # Reserve a bounded descriptor before copying any media into staging.
        needed = len(html_bytes) + sum(map(len, assets.values())) + sum(inventory[name]['size'] for name in media.values())
        descriptor_reserve = 2 * 1024 * 1024
        if needed + descriptor_reserve > max_bytes:
            raise PackageError('view_limit')
        if shutil.disk_usage(destination.parent).free < needed + descriptor_reserve:
            raise PackageError('view_disk_full')
        staging = Path(tempfile.mkdtemp(prefix='.events-view-', dir=destination.parent))
        for reference in media:
            name = reference[1:]
            target = staging / name
            target.parent.mkdir(parents=True, exist_ok=True)
            with target.open('xb') as output:
                size, witness = _stream_stable(package, name, _ExpectedFileWriter(output, inventory[name]['size']))
            if size != inventory[name]['size'] or witness[3] != inventory[name]['sha256']:
                raise PackageError('source_changed')
        for name, payload in assets.items():
            (staging / name).write_bytes(payload)
        (staging / 'index.html').write_bytes(html_bytes)
        files = []
        for path in sorted(staging.rglob('*')):
            if path.is_file():
                name = path.relative_to(staging).as_posix()
                size, witness = _stream_stable(staging, name)
                files.append({'path': name, 'size': size, 'sha256': witness[3]})
        descriptor = _json({'schema_version': 1, 'revision': manifest['revision'],
                                                 'renderer': 'events-v1', 'mode': mode, 'files': files,
                                                 'package_sha256': hashlib.sha256(_json(manifest)).hexdigest()})
        if len(descriptor) > descriptor_reserve:
            raise PackageError('view_limit')
        (staging / 'view.json').write_bytes(descriptor)
        staging.rename(destination)
        staging = None
        return destination / 'index.html'
    except PackageError:
        raise
    except (OSError, ValueError, KeyError, TypeError, RecursionError):
        raise PackageError('view_build_failed') from None
    finally:
        if staging is not None:
            try:
                shutil.rmtree(staging)
            except OSError:
                raise PackageError('view_cleanup_failed') from None
