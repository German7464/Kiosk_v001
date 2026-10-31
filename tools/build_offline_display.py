"""Build isolated x64 WinForms/WebView2 candidate from an explicitly supplied SDK."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import zipfile

SDK_VERSION = '1.0.4314.35'
SDK_SHA256 = '90778deb1b77e36292828b4b5833c9255c27533f40e0ddd55891ae718944edc4'
ROOT = Path(__file__).resolve().parents[1]


def build(sdk_archive, destination):
    sdk_archive, destination = Path(sdk_archive), Path(destination).absolute()
    if hashlib.sha256(sdk_archive.read_bytes()).hexdigest() != SDK_SHA256:
        raise ValueError('SDK checksum mismatch')
    compiler = Path(os.environ.get('WINDIR', 'C:/Windows')) / 'Microsoft.NET/Framework64/v4.0.30319/csc.exe'
    if not compiler.is_file():
        raise RuntimeError('Windows .NET Framework compiler required')
    destination.mkdir(parents=True, exist_ok=False)
    names = ('lib/net462/Microsoft.Web.WebView2.Core.dll',
             'lib/net462/Microsoft.Web.WebView2.WinForms.dll',
             'runtimes/win-x64/native/WebView2Loader.dll')
    with zipfile.ZipFile(sdk_archive) as archive:
        for name in names:
            (destination / Path(name).name).write_bytes(archive.read(name))
        for name in ('LICENSE.txt', 'NOTICE.txt'):
            (destination / ('WebView2-' + name)).write_bytes(archive.read(name))
    source = (ROOT / 'kiosk/display/windows/OfflineDisplay.cs').read_text(encoding='utf-8')
    for name, placeholder in [('events.js', '@RENDERER_JS_SHA256@'), ('events.css', '@RENDERER_CSS_SHA256@')]:
        digest = hashlib.sha256((ROOT / 'kiosk/publication/renderer_assets' / name).read_bytes()).hexdigest()
        source = source.replace(placeholder, digest)
    temporary = destination / 'OfflineDisplay.cs'
    temporary.write_text(source, encoding='utf-8')
    command = [str(compiler), '/nologo', '/target:exe', '/platform:x64',
               '/out:' + str(destination / 'KioskOfflineDisplay.exe'),
               '/r:System.Windows.Forms.dll', '/r:System.Drawing.dll', '/r:System.Web.Extensions.dll',
               '/r:' + str(destination / 'Microsoft.Web.WebView2.Core.dll'),
               '/r:' + str(destination / 'Microsoft.Web.WebView2.WinForms.dll'), str(temporary),
               str(ROOT / 'kiosk/display/windows/PreparedView.cs'),
               str(ROOT / 'kiosk/display/windows/DisplayWindow.cs')]
    subprocess.run(command, check=True, timeout=60)
    temporary.unlink()
    files = {path.name: hashlib.sha256(path.read_bytes()).hexdigest() for path in destination.iterdir() if path.is_file()}
    (destination / 'build.json').write_text(json.dumps({'sdk_version': SDK_VERSION, 'sdk_sha256': SDK_SHA256,
                                                      'sources': {str(path.relative_to(ROOT)): hashlib.sha256(path.read_bytes()).hexdigest()
                                                                  for path in sorted((ROOT / 'kiosk/display/windows').glob('*.cs'))},
                                                      'files': files}, indent=2), encoding='utf-8')
    return destination


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--sdk-archive', type=Path, required=True)
    parser.add_argument('--destination', type=Path, required=True)
    args = parser.parse_args()
    print(build(args.sdk_archive, args.destination))
