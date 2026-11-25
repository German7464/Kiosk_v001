"""Build an isolated portable Windows client; no installation or trust changes."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from kiosk.version import VERSION
from kiosk.display import page_view


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--destination', required=True, type=Path)
    parser.add_argument('--shell-candidate', required=True, type=Path)
    parser.add_argument('--connect-ui', action='store_true', help='Build additive Tk connection window')
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    output = args.destination.absolute()
    output.mkdir(parents=True, exist_ok=False)
    pin = page_view.renderer_pin()
    build_temp = tempfile.mkdtemp(prefix='.build-temp-', dir=output)
    environment = dict(os.environ, TEMP=build_temp, TMP=build_temp)
    sources = [*sorted((root/'kiosk/display').glob('delivery_*.py')), root/'kiosk/display/native_crypto.py',
               root/'kiosk/display/coordinator.py', root/'kiosk/display/cache.py',
               root/'kiosk/display/page_view.py', root/'kiosk/display/session.py', Path(__file__)]
    sources += [root/'kiosk/publication/authority.py', root/'kiosk/publication/page_release.py']
    assets = [root/'kiosk/static/js/page_display.js', root/'kiosk/static/css/page_display.css']
    if args.connect_ui:
        # Discovery is a top-level module (kiosk/discovery.py), not kiosk/display/discovery.py.
        sources += [root/'kiosk/display/connect.py', root/'kiosk/display/connect_ui.py',
                    root/'kiosk/display/admin.py',
                    root/'kiosk/discovery.py', root/'kiosk/display/qr_pairing.py',
                    root/'kiosk/display/qrcodegen.py', root/'kiosk/display/qrcodegen.LICENSE.txt']
    before = {str(p.relative_to(root)): hashlib.sha256(p.read_bytes()).hexdigest()
              for p in sources + assets}
    source = output / 'client_entry.py'
    module = 'connect_ui' if args.connect_ui else 'delivery_client'
    name = 'KioskConnect' if args.connect_ui else 'KioskDelivery'
    source.write_text(f'from kiosk.display.{module} import main\nraise SystemExit(main())\n', encoding='utf-8')
    command = [sys.executable, '-m', 'PyInstaller', '--noconfirm', '--clean', '--onedir', '--name', name,
               '--paths', str(root), '--distpath', str(output/'dist'), '--workpath', str(output/'work'),
               '--specpath', str(output)]
    if args.connect_ui:
        command.append('--windowed')
        # Pillow's Tk bridge is imported lazily in the pairing window; keep it bundled.
        command += ['--hidden-import', 'PIL.ImageTk']
    for relative in ['kiosk/publication/renderer.py', 'kiosk/publication/renderer_assets', 'kiosk/translations',
                     'kiosk/static/js/page_display.js', 'kiosk/static/css/page_display.css']:
        path = root / relative
        if not path.exists():
            raise RuntimeError('Required renderer input missing: ' + relative)
        command += ['--add-data', str(path) + ';' + (relative if path.is_dir() else str(Path(relative).parent))]
    if args.connect_ui:
        # Package the vendored MIT notice beside the QR module it covers.
        command += ['--add-data', str(root/'kiosk/display/qrcodegen.LICENSE.txt') + ';kiosk/display']
    command.append(str(source))
    with (output/'build.log').open('wb') as log:
        result = subprocess.run(command, cwd=root, stdout=log, stderr=subprocess.STDOUT,
                                timeout=300, env=environment)
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
    # Compile the self-contained update helper for the client's self-update.
    compiler = Path(os.environ.get('WINDIR', 'C:/Windows')) / 'Microsoft.NET/Framework64/v4.0.30319/csc.exe'
    if not compiler.is_file():
        raise RuntimeError('Windows .NET Framework compiler required for the update helper.')
    subprocess.run([str(compiler), '/nologo', '/target:exe', '/platform:x64',
                    '/out:' + str(output/'KioskUpdateHelper.exe'), str(root/'tools/update_helper.cs')],
                   check=True, timeout=60, env=environment)
    after = {str(p.relative_to(root)): hashlib.sha256(p.read_bytes()).hexdigest()
             for p in sources + assets}
    if after != before:
        raise RuntimeError('Source changed during build; reject mixed build evidence')
    shutil.rmtree(build_temp, ignore_errors=True)
    inventory = {'sources': before, 'page_renderer': pin,
                 'files': {p.relative_to(output).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
                           for folder in (output/'dist', candidate) for p in sorted(folder.rglob('*')) if p.is_file()},
                 'python': sys.version, 'version': VERSION, 'native_build_reused': expected}
    (output/'identities.json').write_text(json.dumps(inventory, indent=2), encoding='utf-8')
    (output/'version.json').write_text(json.dumps({'schema_version': 1, 'version': VERSION}, indent=2), encoding='utf-8')
    print(json.dumps({'result': 'built', 'files': len(inventory['files']),
                      'client_sha256': inventory['files'][f'dist/{name}/{name}.exe']}))


if __name__ == '__main__':
    main()
