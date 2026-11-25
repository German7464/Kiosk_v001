"""Build an isolated portable Windows publisher app; no installation or trust changes."""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from kiosk.display import page_view


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--destination', required=True, type=Path)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    output = args.destination.absolute()
    output.mkdir(parents=True, exist_ok=False)
    pin = page_view.renderer_pin()
    sources = [root / name for name in (
        'kiosk/publication/publish_ui.py', 'kiosk/publication/publisher.py',
        'kiosk/publication/authority.py', 'kiosk/publication/mapping.py',
        'kiosk/publication/page_release.py',
        'kiosk/display/delivery_capture.py', 'kiosk/display/delivery_transport.py',
        'kiosk/display/delivery_authority.py', 'kiosk/display/native_crypto.py',
        'kiosk/display/page_view.py',
        'kiosk/display/cache.py', 'kiosk/publication/store.py', 'kiosk/publication/exporter.py')]
    assets = [root / 'kiosk/static/js/page_display.js',
              root / 'kiosk/static/css/page_display.css']
    digests = {str(path.relative_to(root)): hashlib.sha256(path.read_bytes()).hexdigest()
               for path in sources + assets}
    entry = output / 'publisher_entry.py'
    entry.write_text('from kiosk.publication.publish_ui import main\nraise SystemExit(main())\n',
                     encoding='utf-8')
    command = [sys.executable, '-m', 'PyInstaller', '--noconfirm', '--clean', '--onedir',
               '--windowed', '--name', 'KioskPublisher', '--paths', str(root),
               '--hidden-import', 'tools.lan_trust_admin',
               '--hidden-import', 'tools.register_publisher_link',
               '--distpath', str(output / 'dist'), '--workpath', str(output / 'work'),
               '--specpath', str(output)]
    for relative in ('kiosk/publication/renderer_assets', 'kiosk/translations',
                     'kiosk/publication/renderer.py'):
        path = root / relative
        if not path.exists():
            raise RuntimeError('Required renderer input missing: ' + relative)
        destination = relative if path.is_dir() else str(Path(relative).parent)
        command += ['--add-data', str(path) + ';' + destination]
    for relative in ('kiosk/static/js/page_display.js', 'kiosk/static/css/page_display.css'):
        path = root / relative
        if not path.exists():
            raise RuntimeError('Required page renderer input missing: ' + relative)
        command += ['--add-data', str(path) + ';' + str(Path(relative).parent)]
    command.append(str(entry))
    with (output / 'build.log').open('wb') as log:
        result = subprocess.run(command, cwd=root, stdout=log, stderr=subprocess.STDOUT,
                                timeout=900)
    result.check_returncode()
    built = output / 'dist' / 'KioskPublisher'
    executable = built / 'KioskPublisher.exe'
    if not executable.is_file():
        raise RuntimeError('publisher executable missing')
    (output / 'build.json').write_bytes(json.dumps({
        'product': 'KioskPublisher', 'sources': digests, 'page_renderer': pin,
        'executable': 'dist/KioskPublisher/KioskPublisher.exe',
        'executable_sha256': hashlib.sha256(executable.read_bytes()).hexdigest(),
        'launch': ['--root', 'PROTECTED_KEY_DIR', '--origin', 'https://HOST:PORT',
                   '--ca', 'PUBLIC_CA_PEM', '--maintenance-origin', 'https://MAINT:PORT',
                   '--maintenance-ca', 'MAINTENANCE_CA_PEM',
                   'kiosk://roaming/publish#origin=...&plan=...'],
        'notes': 'Portable candidate; no signing/CA/registration performed by the build.',
    }, indent=2).encode('utf-8'))
    print(json.dumps({'executable_sha256': hashlib.sha256(executable.read_bytes()).hexdigest(),
                      'destination': str(built)}, indent=2))


if __name__ == '__main__':
    main()
