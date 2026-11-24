"""Build the frozen Windows host used by both supported deployment sides."""
import argparse
import hashlib
import json
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from kiosk.maintenance.serve import CADDY_SHA256, verify_caddy

DATA = ('kiosk/maintenance/templates', 'kiosk/maintenance/static', 'kiosk/templates',
        'kiosk/static', 'kiosk/translations', 'kiosk/publication/renderer_assets')


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--destination', required=True, type=Path)
    parser.add_argument('--caddy', required=True, type=Path)
    args = parser.parse_args()
    verify_caddy(args.caddy)
    output = args.destination.absolute()
    if output.exists():
        raise SystemExit('Build destination already exists.')
    output.mkdir(parents=True)
    sources = [p for folder in DATA for p in (ROOT / folder).rglob('*') if p.is_file()]
    sources += sorted((ROOT / 'kiosk/maintenance').glob('*.py')) + [Path(__file__)]
    sources += sorted((ROOT / 'kiosk/publication').glob('*.py'))
    sources += [ROOT / 'kiosk/publication/authority.py'] + sorted((ROOT / 'kiosk/trust').glob('*.py'))
    sources += [ROOT / name for name in ('kiosk/display/cache.py', 'kiosk/display/delivery_capture.py',
                                        'kiosk/delivery/state.py', 'kiosk/delivery/profiles.py',
                                        'kiosk/delivery/publication.py')]
    before = {p.relative_to(ROOT).as_posix(): digest(p) for p in sources}
    entry = output / 'host_entry.py'
    entry.write_text('from kiosk.maintenance.host import main\nraise SystemExit(main())\n',
                     encoding='utf-8')
    command = [sys.executable, '-m', 'PyInstaller', '--noconfirm', '--clean', '--onedir',
               '--name', 'KioskMaintenanceHost', '--paths', str(ROOT),
               '--distpath', str(output / 'dist'), '--workpath', str(output / 'work'),
               '--specpath', str(output)]
    for folder in DATA:
        path = ROOT / folder
        target = folder if path.is_dir() else str(Path(folder).parent)
        command += ['--add-data', str(path) + ';' + target]
    command.append(str(entry))
    with (output / 'build.log').open('wb') as log:
        result = subprocess.run(command, cwd=ROOT, stdout=log, stderr=subprocess.STDOUT,
                                timeout=900)
    result.check_returncode()
    bundle = output / 'dist' / 'KioskMaintenanceHost'
    (bundle / 'caddy').mkdir()
    shutil.copy2(args.caddy, bundle / 'caddy' / 'caddy.exe')
    verify_caddy(bundle / 'caddy' / 'caddy.exe')
    after = {p.relative_to(ROOT).as_posix(): digest(p) for p in sources}
    if after != before:
        raise SystemExit('Source changed during build; reject mixed evidence.')
    files = {p.relative_to(bundle).as_posix(): digest(p)
             for p in sorted(bundle.rglob('*')) if p.is_file()}
    identity = {'sources': before, 'files': files, 'python': sys.version,
                'caddy_sha256': CADDY_SHA256}
    (output / 'identities.json').write_text(json.dumps(identity, indent=2), encoding='utf-8')
    exe = 'KioskMaintenanceHost.exe'
    print(json.dumps({'result': 'built', 'files': len(files),
                      'host_sha256': files[exe], 'caddy_sha256': CADDY_SHA256}))


if __name__ == '__main__':
    main()
