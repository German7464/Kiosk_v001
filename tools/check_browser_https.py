import argparse
import hashlib
import json
import os
import platform
import queue
import secrets
import shutil
import socket
import ssl
import subprocess
import sys
import tempfile
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

from kiosk.transport.profile import load_profile
from kiosk.transport.runtime import ManagedHttps
from kiosk.transport.windows import OwnedJob
from tools.check_https_prototype import Client, exercise_application
from tools.check_managed_https import fixture_factory
from tools.https_runtime import Proxy, command, verify_caddy


BROWSER_RESULTS = {
    'untrusted': 'ERR_CERT_AUTHORITY_INVALID',
    'trusted': 'pages_and_media_loaded',
    'updated': 'updated_event_visible',
    'wrong-name': 'ERR_CERT_COMMON_NAME_INVALID',
    'expired': 'ERR_CERT_DATE_INVALID',
    'removed': 'ERR_CERT_AUTHORITY_INVALID',
}


def authority_digest(filename):
    der = ssl.PEM_cert_to_DER_cert(Path(filename).read_text(encoding='utf-8'))
    return hashlib.sha256(der).hexdigest()


class BrowserTrust:
    def __init__(self, pwsh, certificate, root):
        self.pwsh = pwsh
        self.certificate = Path(certificate)
        self.root = root
        self.digest = authority_digest(certificate)
        self.owned = False

    def invoke(self, action):
        result = subprocess.run([str(self.pwsh), '-NoProfile', '-NonInteractive', '-File',
                          str(Path(__file__).with_name('browser_trust.ps1')), '-Action', action,
                          '-CertificateFile', str(self.certificate), '-ExpectedSha256', self.digest],
                         cwd=self.root, capture_output=True, timeout=180, creationflags=subprocess.CREATE_NO_WINDOW)
        if result.returncode:
            raise RuntimeError('Authority store operation failed.')
        data = json.loads(result.stdout.decode('utf-8-sig'))
        if data.get('sha256') != self.digest or type(data.get('present')) is not int:
            raise RuntimeError('Invalid authority store result.')
        return data['present']

    def enroll(self):
        if self.owned or self.invoke('inspect') != 0:
            raise RuntimeError('Refusing existing authority ownership.')
        self.owned = True
        if self.invoke('add') != 1:
            raise RuntimeError('Authority enrollment failed.')

    def remove(self):
        if self.owned:
            if self.invoke('remove') != 0:
                raise RuntimeError('Authority removal failed.')
            self.owned = False


class BrowserFixture:
    def __init__(self, caddy, pwsh, chrome, root, report):
        self.root = Path(root)
        self.caddy = caddy
        self.chrome = chrome
        self.report = report
        self.runtime = None
        self.proxies = {}
        self.browser = None
        self.job = None
        self.profile_directory = None
        self.browser_count = 0
        self.stage = None
        self.trust = None
        self.deadline = time.monotonic() + 1800
        command([str(pwsh), '-NoProfile', '-NonInteractive', '-File',
                 str(Path(__file__).with_name('https_certificates.ps1')), '-OutputDirectory', str(root)],
                root, self.deadline)
        self.trust = BrowserTrust(pwsh, self.root / 'authority.pem', root)
        report['caddy'] = verify_caddy(caddy, root, self.deadline)
        version = command([str(pwsh), '-NoProfile', '-NonInteractive', '-CommandWithArgs',
                           "$ErrorActionPreference = 'Stop'; (Get-Item -LiteralPath $args[0]).VersionInfo.ProductVersion", str(chrome)],
                          root, self.deadline)
        report['chrome_version'] = version.stdout.decode('utf-8-sig').strip()
        if not report['chrome_version'] or any(character not in '0123456789.' for character in report['chrome_version']):
            raise RuntimeError('Chrome version unavailable.')
        with socket.socket() as reservation:
            reservation.bind(('127.0.0.1', 0))
            port = reservation.getsockname()[1]
        configuration = {'schema_version': 1, 'public_origin': f'https://127.0.0.1:{port}',
                         'listen_host': '127.0.0.1', 'caddy_executable': str(caddy),
                         'certificate_file': 'valid.pem', 'private_key_file': 'valid.key', 'ca_file': 'authority.pem'}
        filename = self.root / 'https.json'
        filename.write_text(json.dumps(configuration), encoding='utf-8')
        profile = load_profile(filename)
        self.runtime = ManagedHttps(profile, fixture_factory(self.root, secrets.token_urlsafe(24)))
        self.runtime.start()
        self.port = port
        self.context = profile.trust_context()

    def close_browser(self):
        if self.job is not None:
            self.job.close()
            self.job = None
        if self.browser is not None:
            self.browser.wait(timeout=10)
            self.browser = None
        if self.profile_directory is not None:
            until = time.monotonic() + 10
            while True:
                try:
                    shutil.rmtree(self.profile_directory)
                    break
                except OSError:
                    if time.monotonic() >= until:
                        raise
                    time.sleep(0.2)
            self.profile_directory = None

    def open_browser(self, stage):
        if stage not in BROWSER_RESULTS or stage == 'updated':
            raise ValueError('Unknown browser stage.')
        self.close_browser()
        trusted = self.trust.owned
        if trusted != (stage in {'trusted', 'updated', 'wrong-name', 'expired'}):
            raise RuntimeError('Incorrect trust state for browser stage.')
        if stage in {'wrong-name', 'expired'}:
            if stage not in self.proxies:
                directory = self.root / stage
                directory.mkdir()
                for name in (f'{stage}.pem', f'{stage}.key'):
                    shutil.copyfile(self.root / name, directory / name)
                self.proxies[stage] = Proxy(self.caddy, directory, int(self.runtime.server.effective_port),
                                            self.deadline, certificate=stage)
            port = self.proxies[stage].port
        else:
            port = self.port
        self.browser_count += 1
        self.profile_directory = self.root / f'chrome-{self.browser_count}'
        self.profile_directory.mkdir()
        self.job = OwnedJob()
        self.browser = subprocess.Popen([str(self.chrome), f'--user-data-dir={self.profile_directory}',
                                         '--no-first-run', '--no-default-browser-check', '--disable-background-networking',
                                         f'https://127.0.0.1:{port}/kiosk/events'],
                                        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        try:
            self.job.assign(self.browser)
        except BaseException:
            self.browser.kill()
            self.browser.wait(timeout=10)
            raise
        self.stage = stage
        return f'https://127.0.0.1:{port}'

    def exercise(self):
        if not self.trust.owned:
            raise RuntimeError('Trust stage required.')
        from kiosk.core.credentials import save_admin_password
        password = secrets.token_urlsafe(24)
        save_admin_password(self.runtime.app, password, setup=False)
        self.client = Client(self.port, self.context, self.deadline, self.report)
        exercise_application(self.client, password, self.context, self.report)

    def update(self):
        if self.stage != 'trusted' or 'trusted' not in self.report['browser_observations']:
            raise RuntimeError('Inspect trusted browser before updating.')
        self.client.form('/admin/events/1/edit', {'title': 'HTTPS browser update', 'short_description': 'Browser refresh fixture',
                                               'full_description': 'Updated through real HTTPS', 'status': 'active', 'sort_order': '0'})
        self.stage = 'updated'

    def close(self):
        errors = []
        for name, action in [('browser', self.close_browser), ('authority', self.trust.remove if self.trust else lambda: None)]:
            try:
                action()
                self.report['cleanup'][name] = True
            except BaseException as error:
                errors.append(type(error).__name__)
                self.report['cleanup'][name] = False
        for name, proxy in self.proxies.items():
            try:
                self.report['cleanup'][name] = proxy.close()
            except BaseException as error:
                errors.append(type(error).__name__)
        if self.runtime is not None:
            try:
                result = self.runtime.close()
                self.report['cleanup']['managed'] = result
                if result.get('proxy_forced') or result.get('proxy_exit_code', 0) != 0 or not result.get('backend_stopped') or not result.get('temporary_removed'):
                    errors.append('RuntimeCleanupError')
            except BaseException as error:
                errors.append(type(error).__name__)
        if errors:
            raise RuntimeError('Incomplete browser fixture cleanup.')


def execute(fixture, line, report):
    parts = line.strip().split()
    if parts == ['trust']:
        fixture.close_browser()
        fixture.trust.enroll()
    elif parts == ['untrust']:
        fixture.close_browser()
        fixture.trust.remove()
    elif parts == ['abort']:
        raise InterruptedError('Browser scenario cancelled.')
    elif len(parts) == 2 and parts[0] == 'browser':
        print('BROWSER_ORIGIN ' + fixture.open_browser(parts[1]), flush=True)
    elif parts == ['exercise']:
        fixture.exercise()
    elif parts == ['update']:
        fixture.update()
    elif len(parts) == 3 and parts[0] == 'record':
        if fixture.stage != parts[1] or BROWSER_RESULTS.get(parts[1]) != parts[2]:
            raise ValueError('Unexpected manual observation.')
        report['browser_observations'][parts[1]] = parts[2]
    elif parts == ['finish']:
        required = {'routes_login_csrf_secure_cookie', 'multipart_event_three_images_version_fullscreen',
                    'password_change_revokes_previous_cookie', 'forwarded_spoofing_host_and_authentication_limits',
                    'request_body_limit'}
        if report['browser_observations'] != BROWSER_RESULTS or not required.issubset(report['checks']) or fixture.trust.owned:
            raise RuntimeError('Missing browser or HTTP checks.')
        return False
    else:
        raise ValueError('Unknown verification command.')
    return True


def read_commands(commands):
    for line in sys.stdin:
        commands.put(line)
    commands.put(None)


def main():
    parser = argparse.ArgumentParser(allow_abbrev=False)
    parser.add_argument('--caddy', required=True, type=Path)
    parser.add_argument('--pwsh', required=True, type=Path)
    parser.add_argument('--chrome', required=True, type=Path)
    arguments = parser.parse_args()
    if os.name != 'nt':
        parser.error('Windows is required.')
    report = {'success': False, 'phase': 'prepare', 'checks': [], 'http_statuses': {}, 'cleanup': {},
              'browser_observations': {}, 'chrome_version': '', 'windows_version': platform.version(), 'tls_failures': {}}
    started = time.monotonic()
    fixture = None
    root = Path(tempfile.mkdtemp(prefix='kiosk-browser-https-')).resolve()
    commands = queue.Queue()
    threading.Thread(target=read_commands, args=(commands,), daemon=True).start()
    try:
        fixture = BrowserFixture.__new__(BrowserFixture)
        fixture.__init__(arguments.caddy.resolve(), arguments.pwsh.resolve(), arguments.chrome.resolve(), root, report)
        report['phase'] = 'browser'
        print('READY commands: browser STAGE; trust; exercise; update; record STAGE RESULT; untrust; finish; abort', flush=True)
        while True:
            if time.monotonic() >= fixture.deadline:
                raise TimeoutError('Browser scenario deadline expired.')
            line = commands.get(timeout=max(0.1, fixture.deadline - time.monotonic()))
            if line is None:
                raise EOFError('Browser scenario input closed.')
            if not execute(fixture, line, report):
                break
            fixture.runtime.check_running()
            print('COMMAND_OK', flush=True)
        report['success'] = True
    except BaseException as error:
        report['error'] = type(error).__name__
    finally:
        try:
            if fixture is not None:
                fixture.close()
        except BaseException as error:
            report['success'] = False
            report['cleanup_error'] = type(error).__name__
        if not report.get('cleanup_error') and report['cleanup'].get('authority') is True and report['cleanup'].get('browser') is True:
            try:
                if root.parent != Path(tempfile.gettempdir()).resolve() or not root.name.startswith('kiosk-browser-https-'):
                    raise ValueError('Unsafe cleanup target.')
                shutil.rmtree(root)
                report['cleanup']['fixtures_removed'] = True
            except BaseException as error:
                report['success'] = False
                report['cleanup_error'] = type(error).__name__
        else:
            report['success'] = False
        if report['success']:
            report['phase'] = 'complete'
        report['elapsed_seconds'] = round(time.monotonic() - started, 3)
        output = Path('logs/https') / ('browser-' + datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ') + '.json')
        output.parent.mkdir(parents=True, exist_ok=True)
        with output.open('x', encoding='utf-8') as stream:
            json.dump(report, stream, indent=2)
            stream.write('\n')
        print(json.dumps({'success': report['success'], 'phase': report['phase'], 'report': str(output),
                          'error': report.get('error'), 'cleanup_error': report.get('cleanup_error')}), flush=True)
    return 0 if report['success'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
