"""Bounded USB observer for the owner-selected delivery lab; never prints pairing codes."""
import argparse
import hashlib
import io
import json
from pathlib import Path
import re
import subprocess
import tarfile
from datetime import datetime, timezone
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[2]
ADB = Path('C:/Users/admin/AppData/Local/Android/Sdk/platform-tools/adb.exe')
SERIAL = 'ZY22KDWDNH'
PACKAGE = 'org.kiosk.harness.debug'
REPORT = ROOT / 'logs/pc2-device-delivery-20261104'

def adb(*args, timeout=40):
    p = subprocess.run([str(ADB), '-s', SERIAL, *args], capture_output=True, timeout=timeout)
    if p.returncode:
        raise RuntimeError('adb operation failed: ' + args[0])
    return p.stdout

def ui():
    adb('shell', 'uiautomator', 'dump', '/data/local/tmp/kiosk-delivery-ui.xml')
    return ET.fromstring(adb('shell', 'cat', '/data/local/tmp/kiosk-delivery-ui.xml'))

def snapshot():
    texts = [n.get('text', '') for n in ui().iter('node') if n.get('text')]
    return [re.sub(r'Approve on PC1: .*', 'Approve on PC1: [REDACTED]', t) for t in texts]

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('action', choices=['backup', 'backup-test', 'integrity', 'install', 'launch', 'observe', 'record', 'tap', 'approve', 'screen'])
    parser.add_argument('--text')
    args = parser.parse_args()
    REPORT.mkdir(parents=True, exist_ok=True)
    if args.action == 'backup':
        target = REPORT / 'before-install-private.tar'
        if target.exists():
            raise RuntimeError('Existing backup retained; do not overwrite')
        raw = adb('exec-out', 'run-as', PACKAGE, 'tar', '-cf', '-', '.', timeout=120)
        target.write_bytes(raw)
        hashes = {}
        with tarfile.open(fileobj=io.BytesIO(raw)) as archive:
            for entry in archive.getmembers():
                if entry.isfile():
                    hashes[entry.name] = {'size': entry.size, 'sha256': hashlib.sha256(archive.extractfile(entry).read()).hexdigest()}
        (REPORT / 'before-private-inventory.json').write_text(json.dumps(hashes, indent=2))
        remote = adb('shell', 'pm', 'path', PACKAGE).decode().strip().removeprefix('package:')
        adb('pull', remote, str(REPORT / 'before-main.apk'))
        for filename in ['before-main.apk', 'before-install-private.tar']:
            print(filename, hashlib.sha256((REPORT / filename).read_bytes()).hexdigest())
        print('Backed up private files:', len(hashes))
    elif args.action == 'backup-test':
        target = REPORT / 'before-test.apk'
        if target.exists():
            raise RuntimeError('Existing test APK backup retained; do not overwrite')
        result = adb('shell', 'pm', 'path', PACKAGE + '.test').decode().strip().splitlines()
        if len(result) != 1 or not result[0].startswith('package:/data/app/') or not result[0].endswith('/base.apk'):
            raise RuntimeError('Expected one exact installed test APK path')
        remote = result[0].removeprefix('package:')
        expected = adb('shell', 'sha256sum', remote).decode().split()[0]
        adb('pull', remote, str(target))
        actual = hashlib.sha256(target.read_bytes()).hexdigest()
        if actual != expected: raise RuntimeError('Test APK backup hash mismatch')
        print('Original test APK preserved:', actual)
    elif args.action == 'integrity':
        before = json.loads((REPORT / 'before-private-inventory.json').read_text())
        raw = adb('exec-out', 'run-as', PACKAGE, 'tar', '-cf', '-', './files/fixture-publications', timeout=120)
        after = {}
        with tarfile.open(fileobj=io.BytesIO(raw)) as archive:
            for entry in archive.getmembers():
                if entry.isfile(): after[entry.name] = {'size': entry.size, 'sha256': hashlib.sha256(archive.extractfile(entry).read()).hexdigest()}
        selected = {k: v for k, v in before.items() if k.startswith('./files/fixture-publications/') and '/revisions/' in k}
        preserved = all(after.get(k) == v for k, v in selected.items())
        result = {'prior_revision_files': len(selected), 'all_prior_revision_bytes_preserved': preserved,
                  'changed_store_metadata_names': [k for k, v in before.items() if k.startswith('./files/fixture-publications/') and '/revisions/' not in k and after.get(k) != v]}
        remote = adb('shell', 'pm', 'path', PACKAGE).decode().strip().removeprefix('package:')
        result['installed_main_sha256'] = adb('shell', 'sha256sum', remote).decode().split()[0]
        (REPORT / 'phone-final-integrity.json').write_text(json.dumps(result, indent=2))
        print(json.dumps(result))
    elif args.action == 'install':
        if not (REPORT / 'before-install-private.tar').exists():
            raise RuntimeError('Backup required')
        build = ROOT / 'android/app/build/outputs/apk'
        signer = ROOT / 'android/.gradle/debug.keystore'
        apksigner = Path('C:/Users/admin/AppData/Local/Android/Sdk/build-tools/36.0.0/apksigner.bat')
        def cert(path):
            p = subprocess.run([str(apksigner), 'verify', '--print-certs', str(path)], capture_output=True, text=True)
            if p.returncode: raise RuntimeError('APK signature verification failed')
            return re.search(r'Signer #1 certificate SHA-256 digest: (\w+)', p.stdout).group(1)
        candidate = build / 'debug/app-debug.apk'
        if cert(candidate) != cert(REPORT / 'before-main.apk'):
            raise RuntimeError('Signer incompatible; no destructive install authorized')
        print(adb('install', '-r', str(candidate), timeout=120).decode().strip())
        print(adb('install', '-r', str(build / 'androidTest/debug/app-debug-androidTest.apk'), timeout=120).decode().strip())
    elif args.action == 'launch':
        print(adb('shell', 'am', 'start', '-n', PACKAGE + '/org.kiosk.harness.StoredHarnessActivity').decode().strip())
    elif args.action == 'observe':
        print(json.dumps(snapshot(), ensure_ascii=True))
    elif args.action == 'record':
        if not args.text or not re.fullmatch(r'[a-zA-Z0-9_-]+', args.text): raise RuntimeError('Safe checkpoint name required')
        visible_ui = snapshot()
        result = json.loads(adb('exec-out', 'run-as', PACKAGE, 'cat', 'files/fixture-publications/display-state.json'))
        live_pids = adb('shell', 'pidof', PACKAGE).decode().split()
        if str(result['pid']) not in live_pids: raise RuntimeError('Diagnostic belongs to a stopped process; not a live ready checkpoint')
        if not any('state=' + result['state'] + ' selected=' + result['selected_mode'] in text for text in visible_ui):
            raise RuntimeError('Native UI/diagnostic checkpoint raced; record again after operation completes')
        result.update(label=args.text, observed_at=datetime.now(timezone.utc).isoformat(), native_ui=visible_ui)
        (REPORT / (args.text + '-state.json')).write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
        with (REPORT / 'phone-journey.jsonl').open('a', encoding='utf-8') as trace: trace.write(json.dumps(result, ensure_ascii=False) + '\n')
        print(json.dumps({k: result[k] for k in ['label', 'pid', 'state', 'pointer', 'visible', 'visible_mode', 'asset_reads', 'admission_record_issuer']}))
    elif args.action == 'tap':
        matches = [n for n in ui().iter('node') if n.get('text') == args.text]
        if len(matches) != 1: raise RuntimeError('Expected exact unique native UI text')
        coords = list(map(int, re.findall(r'\d+', matches[0].get('bounds'))))
        adb('shell', 'input', 'tap', str((coords[0]+coords[2])//2), str((coords[1]+coords[3])//2))
        print('Tapped native control:', args.text)
    elif args.action == 'approve':
        # Pairing code stays in local process memory and is never returned in evidence.
        matches = [n.get('text').removeprefix('Approve on PC1: ') for n in ui().iter('node') if n.get('text', '').startswith('Approve on PC1: ')]
        if len(matches) != 1: raise RuntimeError('Expected one displayed pairing code')
        handoff = ROOT / 'logs/pc1-delivery-v1-20261104'
        p = subprocess.run(['C:/Python314/python.exe', '-m', 'tools.device_delivery_operator', '--root', '.', '--approve-code', matches[0]], cwd=handoff, capture_output=True)
        if p.returncode: raise RuntimeError('External operator approval failed; details withheld')
        print('External authenticated operator approval: PASS (response redacted)')
    elif args.action == 'screen':
        if any('Approve on PC1:' in t for t in snapshot()): raise RuntimeError('Pairing screen must not be captured')
        if not args.text or not re.fullmatch(r'[a-zA-Z0-9_-]+', args.text): raise RuntimeError('Safe screenshot name required')
        (REPORT / (args.text + '.png')).write_bytes(adb('exec-out', 'screencap', '-p'))
        print('Screenshot saved:', args.text)

if __name__ == '__main__':
    main()
