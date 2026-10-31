"""Build a native engine test against an identified, unchanged display candidate."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess

from build_offline_display import ROOT, SDK_SHA256, SDK_VERSION


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def build(candidate, destination):
    candidate, destination = Path(candidate).resolve(), Path(destination).absolute()
    inventory = json.loads((candidate / 'build.json').read_text(encoding='utf-8'))
    if inventory['sdk_version'] != SDK_VERSION or inventory['sdk_sha256'] != SDK_SHA256:
        raise ValueError('candidate SDK mismatch')
    sources = {key.replace('\\', '/'): value for key, value in inventory['sources'].items()}
    for name in ('OfflineDisplay.cs', 'PreparedView.cs', 'DisplayWindow.cs'):
        source = Path('kiosk/display/windows') / name
        if sources.get(source.as_posix()) != digest(ROOT / source):
            raise ValueError('candidate source mismatch')
    names = ('KioskOfflineDisplay.exe', 'Microsoft.Web.WebView2.Core.dll',
             'Microsoft.Web.WebView2.WinForms.dll', 'WebView2Loader.dll',
             'WebView2-LICENSE.txt', 'WebView2-NOTICE.txt')
    for name in names:
        if inventory['files'].get(name) != digest(candidate / name):
            raise ValueError('candidate file mismatch')
    compiler = Path(os.environ.get('WINDIR', 'C:/Windows')) / 'Microsoft.NET/Framework64/v4.0.30319/csc.exe'
    fixture = ROOT / 'tests/native/EnginePolicyFixture.cs'
    destination.mkdir(parents=True, exist_ok=False)
    for name in names:
        shutil.copyfile(candidate / name, destination / name)
    command = [str(compiler), '/nologo', '/target:exe', '/platform:x64',
               '/out:' + str(destination / 'KioskEnginePolicyFixture.exe'),
               '/r:System.Windows.Forms.dll', '/r:System.Drawing.dll', '/r:System.Web.Extensions.dll',
               '/r:' + str(destination / 'KioskOfflineDisplay.exe'),
               '/r:' + str(destination / 'Microsoft.Web.WebView2.Core.dll'),
               '/r:' + str(destination / 'Microsoft.Web.WebView2.WinForms.dll'), str(fixture)]
    subprocess.run(command, check=True, timeout=60)
    report = {'candidate': inventory, 'fixture_source_sha256': digest(fixture),
              'files': {name.name: digest(name) for name in destination.iterdir() if name.is_file()}}
    (destination / 'fixture-build.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
    return destination


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--candidate', type=Path, required=True)
    parser.add_argument('--destination', type=Path, required=True)
    args = parser.parse_args()
    print(build(args.candidate, args.destination))
