"""Build an isolated portable Windows client; no installation or trust changes."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--destination', required=True, type=Path)
    parser.add_argument('--shell-candidate', required=True, type=Path)
    parser.add_argument('--connect-ui', action='store_true', help='Build additive Tk connection window')
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    output = args.destination.absolute()
    output.mkdir(parents=True, exist_ok=False)
    sources = [*sorted((root/'kiosk/display').glob('delivery_*.py')), root/'kiosk/display/native_crypto.py', Path(__file__)]
    if args.connect_ui:
        sources += [root/'kiosk/display/connect.py', root/'kiosk/display/connect_ui.py', root/'kiosk/discovery.py']
    before = {str(p.relative_to(root)): hashlib.sha256(p.read_bytes()).hexdigest() for p in sources}
    source = output / 'client_entry.py'
    module = 'connect_ui' if args.connect_ui else 'delivery_client'
    name = 'KioskConnect' if args.connect_ui else 'KioskDelivery'
    source.write_text(f'from kiosk.display.{module} import main\nraise SystemExit(main())\n', encoding='utf-8')
    command = [sys.executable, '-m', 'PyInstaller', '--noconfirm', '--clean', '--onedir', '--name', name,
               '--paths', str(root), '--distpath', str(output/'dist'), '--workpath', str(output/'work'),
               '--specpath', str(output)]
    if args.connect_ui:
        command.append('--windowed')
    for relative in ['kiosk/publication/renderer.py', 'kiosk/publication/renderer_assets', 'kiosk/translations']:
        path = root / relative
        if not path.exists():
            raise RuntimeError('Required renderer input missing: ' + relative)
        command += ['--add-data', str(path) + ';' + (relative if path.is_dir() else str(Path(relative).parent))]
    command.append(str(source))
    with (output/'build.log').open('wb') as log:
        result = subprocess.run(command, cwd=root, stdout=log, stderr=subprocess.STDOUT, timeout=300)
    result.check_returncode()
    candidate = output/'shell'
    candidate.mkdir()
    expected = json.loads((args.shell_candidate/'build.json').read_text())
    for relative, digest in expected['sources'].items():
        if hashlib.sha256((root/relative).read_bytes()).hexdigest() != digest:
            raise RuntimeError('Native source changed; a fresh native build is required')
    for filename, digest in expected['files'].items():
        payload = (args.shell_candidate/filename).read_bytes()
        if hashlib.sha256(payload).hexdigest() != digest:
            raise RuntimeError('Native shell identity mismatch')
        (candidate/filename).write_bytes(payload)
    (candidate/'build.json').write_bytes((args.shell_candidate/'build.json').read_bytes())
    after = {str(p.relative_to(root)): hashlib.sha256(p.read_bytes()).hexdigest() for p in sources}
    if after != before:
        raise RuntimeError('Source changed during build; reject mixed build evidence')
    inventory = {'sources': before,
                 'files': {p.relative_to(output).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
                           for folder in (output/'dist', candidate) for p in sorted(folder.rglob('*')) if p.is_file()},
                 'python': sys.version, 'native_build_reused': expected}
    (output/'identities.json').write_text(json.dumps(inventory, indent=2), encoding='utf-8')
    print(json.dumps({'result': 'built', 'files': len(inventory['files']),
                      'client_sha256': inventory['files'][f'dist/{name}/{name}.exe']}))


if __name__ == '__main__':
    main()
