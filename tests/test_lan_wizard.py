import io
import json
import os
import queue
import shutil
import socket
import subprocess
import tempfile
import time
import unittest
import zipfile
from contextlib import redirect_stdout
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from tools.check_https_prototype import Client
from tools.lan_wizard import CONTROL_PATH, WizardFixture, read_password


class LanWizardTests(unittest.TestCase):
    def fixture(self, root):
        return WizardFixture(SimpleNamespace(server_ip='192.168.1.165', client_ip='192.168.1.117', port=8443), root, 'disposable-test-password')

    def request(self, fixture, body=None, **changes):
        raw = json.dumps(body if body is not None else {'action': 'restart'}).encode()
        environ = {'REQUEST_METHOD': 'POST', 'REMOTE_ADDR': fixture.args.client_ip, 'wsgi.url_scheme': 'https',
                   'HTTP_X_LAN_TEST_TOKEN': fixture.token, 'CONTENT_LENGTH': str(len(raw)), 'wsgi.input': io.BytesIO(raw)}
        return fixture.control({**environ, **changes})

    def test_control_requires_capability_selected_peer_https_and_post(self):
        with tempfile.TemporaryDirectory() as directory:
            fixture = self.fixture(Path(directory))
            for change in ({'HTTP_X_LAN_TEST_TOKEN': 'wrong'}, {'HTTP_X_LAN_TEST_TOKEN': '\u044f'},
                           {'REMOTE_ADDR': fixture.args.server_ip}, {'wsgi.url_scheme': 'http'}, {'REQUEST_METHOD': 'GET'}):
                self.assertEqual(self.request(fixture, **change)[0], '403 Forbidden')
            self.assertTrue(fixture.commands.empty())
            status, reply = self.request(fixture)
            self.assertEqual(status, '202 Accepted')
            self.assertEqual(self.request(fixture, {'action': 'status', 'value': reply['id']}), ('200 OK', {'state': 'pending'}))
            self.assertNotIn(fixture.token, json.dumps(reply))

    def test_control_rejects_arbitrary_actions_oversized_or_malformed_inputs(self):
        with tempfile.TemporaryDirectory() as directory:
            fixture = self.fixture(Path(directory))
            for data in ({'action': 'run shell'}, {'action': ['restart']}, {'action': 'restart', 'path': 'secret'}, [], {'action': 'status', 'value': 'unknown'}):
                self.assertEqual(self.request(fixture, data)[0], '400 Bad Request')
            self.assertEqual(self.request(fixture, CONTENT_LENGTH='32769')[0], '400 Bad Request')
            for unused in range(16):
                self.assertEqual(self.request(fixture)[0], '202 Accepted')
            self.assertEqual(self.request(fixture)[0], '429 Too Many Requests')
            self.assertEqual(fixture.commands.qsize(), 16)

    def test_dispatch_cannot_complete_without_real_evidence_or_close_early(self):
        with tempfile.TemporaryDirectory() as directory:
            fixture = self.fixture(Path(directory))
            fixture.restart = Mock()
            fixture.process('restart', None)
            fixture.restart.assert_called_once()
            for action, value in (('close', None), ('complete', {'client_cleanup': False}), ('report', {}), ('record', {'stage': 'trusted', 'result': 'wrong'})):
                with self.subTest(action=action), self.assertRaises((ValueError, RuntimeError)):
                    fixture.process(action, value)
            self.assertFalse(fixture.completed)
            self.assertIsNone(fixture.client_report)
            with patch.object(fixture, 'finish') as finish, self.assertRaises(ValueError):
                fixture.process('complete', {'client_cleanup': 1})
            finish.assert_not_called()
            with self.assertRaises(EOFError):
                fixture.process('abort', None)

    def test_bundle_has_only_whitelisted_client_files_not_server_keys(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            fixture = self.fixture(root)
            fixture.manifest.parent.mkdir()
            for name in ('check_lan_https.ps1', 'browser_trust.ps1', 'session.json', 'authority.pem', 'fixture.png'):
                (fixture.manifest.parent / name).write_text('fixture', encoding='utf-8')
            (root / 'valid.key').write_text('server secret', encoding='utf-8')
            (fixture.manifest.parent / 'extra.key').write_text('extra secret', encoding='utf-8')
            output = root / 'client.zip'
            fixture.bundle(output)
            with zipfile.ZipFile(output) as archive:
                self.assertEqual(set(archive.namelist()), {'LAN_Client.cmd', 'LAN_Diagnose.cmd', 'check_lan_https.ps1', 'browser_trust.ps1',
                    'lan_wizard.ps1', 'wizard.json', 'session.json', 'authority.pem', 'fixture.png'})
                self.assertEqual(json.loads(archive.read('wizard.json'))['token'], fixture.token)
                self.assertNotIn('server secret', ''.join(archive.read(name).decode(errors='ignore') for name in archive.namelist()))

    def test_password_retries_without_echoing_or_weakening_policy(self):
        output = io.StringIO()
        with patch('tools.lan_wizard.getpass.getpass', side_effect=['short', 'test-password-one', 'test-password-two',
                                                                  'test-password-three', 'test-password-three']), redirect_stdout(output):
            self.assertEqual(read_password(), 'test-password-three')
        self.assertNotIn('test-password', output.getvalue())


@unittest.skipUnless(os.name == 'nt' and shutil.which('pwsh'), 'Requires Windows and PowerShell 7')
class LanWizardRuntimeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temporary = tempfile.TemporaryDirectory(prefix='kiosk-wizard-unit-')
        cls.root = Path(cls.temporary.name)
        cls.repository = Path(__file__).resolve().parent.parent
        cls.pwsh = shutil.which('pwsh')
        result = subprocess.run([cls.pwsh, '-NoProfile', '-NonInteractive', '-File', str(cls.repository / 'tools/https_certificates.ps1'),
            '-OutputDirectory', str(cls.root)], capture_output=True, timeout=30)
        if result.returncode:
            cls.temporary.cleanup()
            raise RuntimeError('Certificate fixture failed')

    @classmethod
    def tearDownClass(cls):
        cls.temporary.cleanup()

    def test_real_https_coordination_restarts_without_blocking_request_shutdown(self):
        caddy = self.repository / 'logs/https-tools/caddy/caddy.exe'
        if not caddy.is_file():
            self.skipTest('Pinned developer Caddy is not prepared')
        with tempfile.TemporaryDirectory(prefix='kiosk-wizard-managed-') as directory:
            root = Path(directory)
            with socket.socket() as listener:
                listener.bind(('127.0.0.1', 0))
                port = listener.getsockname()[1]
            args = SimpleNamespace(server_ip='127.0.0.1', client_ip='127.0.0.1', port=port, pwsh=Path(self.pwsh))
            fixture = WizardFixture(args, root, 'disposable-test-password')
            fixture.manifest.parent.mkdir()
            fixture.profile_file.write_text(json.dumps({'schema_version': 1, 'public_origin': f'https://127.0.0.1:{port}',
                'listen_host': '127.0.0.1', 'caddy_executable': str(caddy), 'certificate_file': str(self.root / 'valid.pem'),
                'private_key_file': str(self.root / 'valid.key'), 'ca_file': str(self.root / 'authority.pem')}), encoding='utf-8')
            try:
                fixture.start()
                client = Client(port, fixture.runtime.profile.trust_context(), time.monotonic() + 40, {'http_statuses': {}})
                client.form('/admin/login', {'username': 'admin', 'password': 'disposable-test-password'})
                body, unused = client.request(CONTROL_PATH, 403, json.dumps({'action': 'restart'}).encode(), {'Content-Type': 'application/json'})
                self.assertEqual(json.loads(body), {'error': 'denied'})
                headers = {'Content-Type': 'application/json', 'X-Lan-Test-Token': fixture.token}
                body, unused = client.request(CONTROL_PATH, 202, json.dumps({'action': 'restart'}).encode(), headers)
                identifier = json.loads(body)['id']
                command_id, action, value = fixture.commands.get_nowait()
                self.assertEqual(command_id, identifier)
                identity = fixture.runtime.identity
                fixture.process(action, value)
                fixture.states[identifier] = 'done'
                self.assertNotEqual(fixture.runtime.identity, identity)
                body, unused = client.request(CONTROL_PATH, 200, json.dumps({'action': 'status', 'value': identifier}).encode(), headers)
                self.assertEqual(json.loads(body), {'state': 'done'})
                client.request('/admin')
                config = root / 'coordination.json'
                config.write_text(json.dumps({'origin': client.base, 'token': fixture.token,
                    'authority': str(self.root / 'authority.pem')}), encoding='utf-8')
                script = root / 'coordinate.ps1'
                script.write_text('''param($Library,$Helper,$Configuration)
. $Library -LibraryOnly
. $Helper
$settings = Get-Content -Raw -LiteralPath $Configuration | ConvertFrom-Json
$script:origin = $settings.origin
$script:codes = @{}
$script:LanControlToken = $settings.token
$pem = [IO.File]::ReadAllText($settings.authority)
$cert = [Security.Cryptography.X509Certificates.X509Certificate2]::CreateFromPem($pem)
try { $digest = [Convert]::ToHexString([Security.Cryptography.SHA256]::HashData($cert.RawData)).ToLowerInvariant() } finally { $cert.Dispose() }
$transport = [KioskLanTls]::new($pem,$digest,$true)
try {
    Test-LanHostRejection $transport
    if ($script:codes['400'] -ne 1) { throw 'Managed proxy Host rejection missing' }
    Invoke-LanWizardCommand $transport 'restart'
    if ($script:codes.Count -ne 1 -or $script:codes['400'] -ne 1) { throw 'Control codes mixed into application evidence' }
} finally { $transport.Dispose() }
''', encoding='utf-8')
                identity = fixture.runtime.identity
                process = subprocess.Popen([self.pwsh, '-NoProfile', '-NonInteractive', '-File', str(script),
                    str(self.repository / 'tools/check_lan_https.ps1'), str(self.repository / 'tools/lan_wizard.ps1'), str(config)],
                    stdout=subprocess.PIPE, stderr=subprocess.PIPE)
                try:
                    deadline = time.monotonic() + 30
                    while process.poll() is None and time.monotonic() < deadline:
                        try:
                            command_id, action, value = fixture.commands.get(timeout=0.1)
                        except queue.Empty:
                            continue
                        fixture.process(action, value)
                        fixture.states[command_id] = 'done'
                    unused, errors = process.communicate(timeout=2)
                    self.assertEqual(process.returncode, 0, errors.decode(errors='replace'))
                    self.assertNotEqual(fixture.runtime.identity, identity)
                finally:
                    if process.poll() is None:
                        process.kill()
                        process.communicate(timeout=5)
            finally:
                fixture.stop()
            self.assertTrue(all(item['proxy_exit_code'] == 0 and not item['proxy_forced'] for item in fixture.cleanups))

    def run_browser_simulation(self, initial_root, fail_at):
        with tempfile.TemporaryDirectory(prefix='kiosk-wizard-client-sim-') as directory:
            root = Path(directory)
            shutil.copy2(self.repository / 'tools/lan_wizard.ps1', root / 'lan_wizard.ps1')
            fake_trust = '''param($Action,$CertificateFile,$ExpectedSha256)
$stateFile = Join-Path $PSScriptRoot 'fake-root.json'
$current = Get-Content -Raw $stateFile | ConvertFrom-Json
Add-Content -LiteralPath (Join-Path $PSScriptRoot 'root-actions.txt') -Value $Action
if ($Action -eq 'add') { $current = 1 }
if ($Action -eq 'remove') { $current = 0 }
$current | ConvertTo-Json | Set-Content $stateFile
@{present=$current;sha256=$ExpectedSha256} | ConvertTo-Json -Compress
'''
            (root / 'browser_trust.ps1').write_text(fake_trust, encoding='utf-8')
            (root / 'fake-root.json').write_text(str(initial_root), encoding='utf-8')
            source = '''param($Library,$Helper,$Authority,$Directory,$FailAt)
. $Library -LibraryOnly
. $Helper
$script:LanStateFile = Join-Path $Directory 'state.json'
$script:LanWizardState = [pscustomobject]@{session=('b'*32);digest=('a'*64);root_owned=$false}
$script:LanBudgetWait = 0
$script:count = 0
$script:commands = [Collections.Generic.List[string]]::new()
$script:stages = [Collections.Generic.List[string]]::new()
function Invoke-LanWizardCommand { param($Transport,$Action,$Value) $script:commands.Add($Action) }
function Open-LanBrowser { param($Stage,$Paths) $script:stages.Add($Stage) }
function Stop-LanBrowser {}
function Confirm-LanStep { param($Message) $script:count++; if ($script:count -eq [int]$FailAt) { throw 'operator rejected' } }
function Read-Host { param($Prompt) return '' }
$pem = [IO.File]::ReadAllText($Authority)
$cert = [Security.Cryptography.X509Certificates.X509Certificate2]::CreateFromPem($pem)
try { $digest = [Convert]::ToHexString([Security.Cryptography.SHA256]::HashData($cert.RawData)).ToLowerInvariant() } finally { $cert.Dispose() }
$success = $true
try { Complete-LanWizard @{success=$true} $pem $digest } catch { $success = $false }
@{success=$success;commands=@($script:commands.ToArray());stages=@($script:stages.ToArray());owned=$script:LanWizardState.root_owned} | ConvertTo-Json -Compress | Set-Content -LiteralPath (Join-Path $Directory 'simulation.json')
'''
            script = root / 'simulate.ps1'
            script.write_text(source, encoding='utf-8')
            result = subprocess.run([self.pwsh, '-NoProfile', '-NonInteractive', '-File', str(script),
                str(self.repository / 'tools/check_lan_https.ps1'), str(root / 'lan_wizard.ps1'),
                str(self.root / 'authority.pem'), str(root), str(fail_at)], capture_output=True, timeout=30)
            self.assertEqual(result.returncode, 0, result.stderr.decode(errors='replace'))
            return json.loads((root / 'simulation.json').read_text(encoding='utf-8-sig')), (root / 'root-actions.txt').read_text(encoding='utf-8-sig').splitlines()

    def test_guided_client_stage_order_and_cleanup_without_real_trust_or_browser(self):
        report, actions = self.run_browser_simulation(0, 0)
        self.assertTrue(report['success'])
        self.assertEqual(report['stages'], ['A', 'B', 'C'])
        self.assertEqual(report['commands'], ['report', 'record', 'record', 'update', 'record', 'record', 'complete', 'close'])
        self.assertEqual(actions, ['inspect', 'add', 'remove', 'inspect'])
        self.assertFalse(report['owned'])

    def test_failed_browser_observation_removes_only_new_root_and_aborts(self):
        report, actions = self.run_browser_simulation(0, 3)
        self.assertFalse(report['success'])
        self.assertNotIn('complete', report['commands'])
        self.assertEqual(report['commands'][-1], 'abort')
        self.assertEqual(actions, ['inspect', 'add', 'remove', 'inspect'])
        self.assertFalse(report['owned'])

    def test_existing_root_is_never_claimed_or_removed(self):
        report, actions = self.run_browser_simulation(1, 0)
        self.assertFalse(report['success'])
        self.assertEqual(actions, ['inspect'])
        self.assertFalse(report['owned'])

    def test_cleanup_only_relaunch_preserves_existing_client_report(self):
        with tempfile.TemporaryDirectory(prefix='kiosk-wizard-recovery-') as directory:
            root = Path(directory)
            for filename in ('check_lan_https.ps1', 'lan_wizard.ps1'):
                shutil.copy2(self.repository / 'tools' / filename, root / filename)
            shutil.copy2(self.root / 'authority.pem', root / 'authority.pem')
            from tools.check_browser_https import authority_digest

            session = 'c' * 32
            (root / 'session.json').write_text(json.dumps({'session': session}), encoding='utf-8')
            (root / 'wizard.json').write_text(json.dumps({'schema_version': 1, 'session': session, 'token': 'd' * 64}), encoding='utf-8')
            (root / 'wizard-cleanup.json').write_text(json.dumps({'session': session, 'digest': authority_digest(root / 'authority.pem'), 'root_owned': False}), encoding='utf-8')
            (root / 'client-report.json').write_text('preserve prior report', encoding='utf-8')
            runner = root / 'recover.ps1'
            runner.write_text("param($Main)\nfunction Read-Host { param($Prompt) return '' }\n& $Main -Wizard\n", encoding='utf-8')
            result = subprocess.run([self.pwsh, '-NoProfile', '-NonInteractive', '-File', str(runner), str(root / 'check_lan_https.ps1')], capture_output=True, timeout=20)
            self.assertEqual(result.returncode, 0, result.stderr.decode(errors='replace'))
            self.assertEqual((root / 'client-report.json').read_text(encoding='utf-8'), 'preserve prior report')

    def test_firewall_helper_rejects_unsafe_arguments_before_elevation(self):
        for server, client, session in (('127.0.0.1', '192.168.1.117', 'a' * 32),
                                        ('192.168.1.165', '192.168.1.165', 'a' * 32),
                                        ('192.168.1.165', '192.168.1.117', 'invalid')):
            result = subprocess.run([self.pwsh, '-NoProfile', '-NonInteractive', '-File', str(self.repository / 'tools/lan_firewall.ps1'),
                '-Action', 'remove', '-ServerAddress', server, '-ClientAddress', client, '-Port', '8443', '-Session', session],
                capture_output=True, timeout=15)
            self.assertNotEqual(result.returncode, 0)

    def preflight(self, client_ip='127.0.0.1', malformed=False):
        with tempfile.TemporaryDirectory(prefix='kiosk-client-preflight-') as directory:
            root = Path(directory)
            manifest = {'schema_version': 1, 'session': 'e' * 32, 'origin': 'https://192.0.2.10:8443',
                        'client_ip': client_ip, 'backend_port': 41001, 'admin_port': 41002}
            if malformed:
                manifest['schema_version'] = 999
            filename = root / 'session.json'
            filename.write_text(json.dumps(manifest), encoding='utf-8')
            report = root / 'client-report.json'
            report.write_text('retain existing evidence', encoding='utf-8')
            result = subprocess.run([self.pwsh, '-NoProfile', '-NonInteractive', '-File',
                str(self.repository / 'tools/check_lan_https.ps1'), '-PreflightOnly', '-SessionFile', str(filename),
                '-ReportFile', str(report)], capture_output=True, timeout=20)
            self.assertEqual(report.read_text(encoding='utf-8'), 'retain existing evidence')
            self.assertFalse((root / 'wizard-cleanup.json').exists())
            diagnostics = [json.loads(path.read_text(encoding='utf-8')) for path in root.glob('client-diagnostics-*.json')]
            return result, diagnostics

    def test_preflight_runs_without_ca_network_password_or_overwriting_evidence(self):
        result, diagnostics = self.preflight()
        self.assertEqual(result.returncode, 0, (diagnostics, result.stdout.decode(errors='replace'), result.stderr.decode(errors='replace')))
        self.assertEqual(diagnostics, [])

    def test_preflight_explains_wrong_pc_before_any_network_requests(self):
        result, diagnostics = self.preflight(client_ip='192.0.2.250')
        self.assertEqual(result.returncode, 1)
        self.assertEqual(len(diagnostics), 1)
        self.assertEqual(diagnostics[0]['stage'], 'client_address')
        self.assertEqual(diagnostics[0]['reason'], 'wrong_client_pc')
        self.assertGreater(diagnostics[0]['line'], 0)

    def test_preflight_explains_invalid_manifest(self):
        result, diagnostics = self.preflight(malformed=True)
        self.assertEqual(result.returncode, 1)
        self.assertEqual(diagnostics[0]['stage'], 'manifest_schema')
        self.assertEqual(diagnostics[0]['reason'], 'invalid_manifest')

    def test_unexpected_diagnostic_never_echoes_exception_secrets(self):
        with tempfile.TemporaryDirectory(prefix='kiosk-client-diagnostic-') as directory:
            root = Path(directory)
            script = root / 'sanitize.ps1'
            script.write_text('''param($Library,$Directory)
. $Library -LibraryOnly
$ReportFile = Join-Path $Directory 'client-report.json'
$script:LanStage = 'login'
$script:LanResponseStatus = 401
try { throw 'password=private-secret; token=private-secret; https://private-secret.invalid' } catch { Write-LanFailure $_ }
''', encoding='utf-8')
            result = subprocess.run([self.pwsh, '-NoProfile', '-NonInteractive', '-File', str(script),
                str(self.repository / 'tools/check_lan_https.ps1'), str(root)], capture_output=True, timeout=20)
            self.assertEqual(result.returncode, 0, result.stderr.decode(errors='replace'))
            diagnostic = next(root.glob('client-diagnostics-*.json')).read_text(encoding='utf-8')
            self.assertNotIn('private-secret', diagnostic)
            self.assertNotIn('private-secret', result.stdout.decode(errors='replace'))
            parsed = json.loads(diagnostic)
            self.assertEqual(parsed['reason'], 'unexpected_error')
            self.assertEqual(parsed['http_status'], 401)


if __name__ == '__main__':
    unittest.main()
