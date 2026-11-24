"""Build a portable isolated pilot supervisor; never replaces an installed server."""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sys


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--destination', type=Path, required=True)
    args = parser.parse_args()
    project = Path(__file__).resolve().parents[1]
    output = args.destination.absolute()
    output.mkdir(parents=True, exist_ok=False)
    entry = output / 'entry.py'
    entry.write_text('from tools.lan_trust_supervisor import main\nmain()\n')
    command = [sys.executable, '-m', 'PyInstaller', '--noconfirm', '--onedir', '--name', 'KioskLanPilot',
               '--paths', str(project), '--distpath', str(output/'dist'), '--workpath', str(output/'work'),
               '--specpath', str(output)]
    for relative in ['kiosk/templates','kiosk/static/css','kiosk/static/js','kiosk/static/img',
                     'kiosk/translations','kiosk/publication/renderer.py','kiosk/publication/renderer_assets']:
        path = project / relative
        command += ['--add-data', str(path) + ';' + (relative if path.is_dir() else str(Path(relative).parent))]
    command += ['--hidden-import','kiosk.publication.renderer', str(entry)]
    subprocess.run(command, check=True, timeout=300, stdout=(output/'build.log').open('wb'), stderr=subprocess.STDOUT)
    files = {p.relative_to(output/'dist/KioskLanPilot').as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
             for p in (output/'dist/KioskLanPilot').rglob('*') if p.is_file()}
    (output/'identities.json').write_text(json.dumps({'python':sys.version,'files':files}, indent=2))
    print(json.dumps({'built':str(output), 'files':len(files)}))


if __name__ == '__main__':
    main()
