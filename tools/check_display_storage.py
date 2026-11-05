"""One isolated Windows profile-growth -> preserved publication -> offline recovery check."""
import argparse
import ctypes
from ctypes import wintypes
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import time

from kiosk.display.coordinator import display_session
from kiosk.display.session import install_for_display
from tests.test_publication_export import ExportTests, connection

ROOT = Path(__file__).resolve().parents[1]


def inventory(root):
    return {p.relative_to(root).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in root.rglob('*') if p.is_file() and p.name != 'store.lock'}


def close_window(process):
    api = ctypes.WinDLL('user32', use_last_error=True)
    callback_type = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    api.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
    api.PostMessageW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
    api.EnumWindows.argtypes = [callback_type, wintypes.LPARAM]

    @callback_type
    def visit(window, _):
        pid = wintypes.DWORD()
        api.GetWindowThreadProcessId(window, ctypes.byref(pid))
        if pid.value == process.pid:
            api.PostMessageW(window, 0x10, 0, 0)
        return True

    api.EnumWindows(visit, 0)
    if process.wait(timeout=12) != 0:
        raise AssertionError('owned window did not close normally')


def browser_handle(pid):
    api = ctypes.WinDLL('kernel32', use_last_error=True)
    api.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    api.OpenProcess.restype = wintypes.HANDLE
    handle = api.OpenProcess(0x100000, False, pid)
    if not handle:
        raise ctypes.WinError(ctypes.get_last_error())
    return api, handle


def wait_browser(api, handle):
    api.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
    api.CloseHandle.argtypes = [wintypes.HANDLE]
    try:
        assert api.WaitForSingleObject(handle, 5000) == 0, 'owned browser outlived host'
    finally:
        api.CloseHandle(handle)


def check(candidate, destination, reuse_policy=None):
    candidate, destination = Path(candidate).absolute(), Path(destination).absolute()
    destination.mkdir(parents=True, exist_ok=False)
    report = {'result': 'RUNNING', 'cases': [], 'source_head': subprocess.check_output(
        ['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip()}
    report['build'] = json.loads((candidate / 'build.json').read_bytes())
    for name, digest in report['build']['files'].items():
        assert hashlib.sha256((candidate / name).read_bytes()).hexdigest() == digest
    for name, digest in report['build']['sources'].items():
        assert hashlib.sha256((ROOT / name).read_bytes()).hexdigest() == digest
    compiler = Path(os.environ['WINDIR']) / 'Microsoft.NET/Framework64/v4.0.30319/csc.exe'
    fixture = destination / 'StoragePolicyFixture.exe'
    for name in ('KioskOfflineDisplay.exe', 'Microsoft.Web.WebView2.Core.dll',
                 'Microsoft.Web.WebView2.WinForms.dll', 'WebView2Loader.dll'):
        shutil.copy2(candidate / name, destination / name)
    if reuse_policy:
        previous = Path(reuse_policy)
        prior = json.loads(previous.read_bytes())
        assert prior['build'] == report['build'] and prior['policy']['result'] == 'PASS'
        assert hashlib.sha256((previous.parent / 'StoragePolicyFixture.exe').read_bytes()).hexdigest() == prior['fixture_sha256']
        report['policy'], report['fixture_sha256'] = prior['policy'], prior['fixture_sha256']
        report['policy_reused_from'] = str(previous)
    else:
        completed = subprocess.run([str(compiler), '/nologo', '/target:exe', '/out:' + str(fixture),
            '/r:System.Web.Extensions.dll', '/r:' + str(destination / 'KioskOfflineDisplay.exe'),
            str(ROOT / 'tests/native/StoragePolicyFixture.cs')], capture_output=True, timeout=60)
        (destination / 'compile.txt').write_bytes(completed.stdout + completed.stderr)
        assert completed.returncode == 0, 'fixture compilation failed'
        report['fixture_sha256'] = hashlib.sha256(fixture.read_bytes()).hexdigest()
        fixture_result = subprocess.run([str(fixture), str(destination / 'policy')], timeout=15)
        report['policy'] = json.loads((destination / 'policy/result.json').read_bytes())
        assert fixture_result.returncode == 0, report['policy']
    report['os'] = list(os.sys.getwindowsversion())
    fixture_source = ExportTests()
    fixture_source.setUp()

    def save():
        (destination / 'result.json').write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')

    try:
        fixture_source.export()
        shutil.copytree(fixture_source.destination, destination / 'package-a')
        with connection(fixture_source.db) as db:
            db.execute("UPDATE settings SET value='8' WHERE key='content_version'")
            db.execute("UPDATE events SET title='Storage recovery acceptance' WHERE id=1")
        fixture_source.export(destination / 'package-b')
        store, cache, state, profile = [destination / name for name in ('store', 'cache', 'state', 'profile')]
        shell = candidate / 'KioskOfflineDisplay.exe'
        # Provision NEW private roots before fixture writers create inherited broad ACLs.
        subprocess.run([str(shell), '--check-storage', *(str(p) for p in (store, cache, state, profile))], check=True, timeout=10)
        install_for_display(destination / 'package-a', store, cache, mode='tv')
        install_for_display(destination / 'package-b', store, cache, mode='tv')
        # First native preflight creates a private profile; legacy bytes must remain untouched.
        subprocess.run([str(shell), '--check-storage', *(str(p) for p in (store, cache, state, profile))], check=True, timeout=10)
        legacy = profile / 'legacy-sentinel'; legacy.write_bytes(b'keep legacy profile bytes')
        with display_session(store, cache, state, profile, shell, mode='tv') as run:
            status = json.loads((profile / 'display-status.json').read_bytes())
            before = {'store': inventory(store), 'cache': inventory(cache), 'state': inventory(state)}
            (destination / 'preserved-data-inventory.json').write_text(json.dumps(before, indent=2), encoding='utf-8')
            report['initial'] = status
            api, handle = browser_handle(status['browser_process_id'])
            assert shutil.disk_usage(profile).free > 2 * 1024**3, 'insufficient isolated test headroom'
            started = time.monotonic()
            with (profile / 'runtime-v1/browser/fixture-pressure').open('wb') as stream:
                stream.truncate(257 * 1024**2)
            assert run.process.wait(timeout=8) == 3, 'runtime growth did not stop host'
            wait_browser(api, handle)
            report['growth_stop_seconds'] = time.monotonic() - started
            diagnostic = json.loads((profile / 'display-storage.json').read_bytes())
            assert diagnostic == {'session_id': run.session, 'code': 'display_profile_limit'}
        assert before == {'store': inventory(store), 'cache': inventory(cache), 'state': inventory(state)}
        assert legacy.read_bytes() == b'keep legacy profile bytes'
        report['cases'].append('runtime-growth-stops-owned-tree-with-store-cache-receipt-intact')
        with display_session(store, cache, state, profile, shell, mode='tv') as recovered:
            assert recovered.view == run.view and not recovered.fallback
            assert not (profile / 'runtime-v1/browser/fixture-pressure').exists()
            report['recovered'] = json.loads((profile / 'display-status.json').read_bytes())
            api, handle = browser_handle(report['recovered']['browser_process_id'])
            close_window(recovered.process)
            wait_browser(api, handle)
        assert before == {'store': inventory(store), 'cache': inventory(cache), 'state': inventory(state)}
        assert legacy.read_bytes() == b'keep legacy profile bytes'
        report['cases'].append('fresh-offline-ready-and-normal-close-preserve-both-publications')
        report['result'] = 'PASS'
    except BaseException as error:
        report['result'], report['error'] = 'FAIL', repr(error)
        raise
    finally:
        save()
        fixture_source.doCleanups()
    return report


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--candidate', required=True)
    parser.add_argument('--destination', required=True)
    parser.add_argument('--reuse-policy', help='Reuse passing policy evidence only for the identical native build')
    options = parser.parse_args()
    result = check(options.candidate, options.destination, options.reuse_policy)
    print(json.dumps({'result': result['result'], 'cases': result['cases'],
                      'growth_stop_seconds': result.get('growth_stop_seconds')}, indent=2))
