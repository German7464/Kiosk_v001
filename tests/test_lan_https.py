import io
import json
import os
import shutil
import socket
import ssl
import subprocess
import tempfile
import threading
import time
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from PIL import Image
from werkzeug.serving import make_server

from tests.browser_client import browser_client
from tools.check_browser_https import authority_digest
from tools.check_https_prototype import Client
from tools.check_lan_https import BROWSER_RESULTS, CLIENT_CHECKS, LanFixture, Observations, cleanup_ok, execute, firewall_commands, lan_ipv4, main, validate_addresses, validate_client_report
from tools.check_managed_https import fixture_factory


class LanHttpsTests(unittest.TestCase):
    def test_addresses_reject_unsafe_or_same_endpoints_before_binding(self):
        for address in ('127.0.0.1', '0.0.0.0', '0.2.3.4', '224.0.0.1', '255.255.255.255', '::1', 'host.invalid'):
            with self.subTest(address=address), self.assertRaises(ValueError):
                lan_ipv4(address)
        for client, port in (('192.168.10.2', 8443), ('192.168.10.3', 0), ('192.168.10.3', 443)):
            with self.subTest(client=client, port=port), self.assertRaises(ValueError), patch('tools.check_lan_https.socket.socket') as factory:
                validate_addresses('192.168.10.2', client, port)
            factory.assert_not_called()

    def test_binding_conflict_is_not_reused(self):
        with patch('tools.check_lan_https.socket.socket') as factory:
            factory.return_value.__enter__.return_value.bind.side_effect = OSError('occupied')
            with self.assertRaises(OSError):
                validate_addresses('192.168.10.2', '192.168.10.3', 8443)

    def report(self):
        return {'schema_version': 1, 'session': 'a' * 32, 'success': True, 'checks': sorted(CLIENT_CHECKS),
                'http_statuses': {str(code): 1 for code in (200, 302, 400, 401, 403, 429)}, 'error': None}

    def test_import_requires_complete_matching_safe_report(self):
        with tempfile.TemporaryDirectory() as directory:
            filename = Path(directory) / 'client.json'
            filename.write_text(json.dumps(self.report()), encoding='utf-8')
            self.assertEqual(validate_client_report(filename, 'a' * 32)['checks'], sorted(CLIENT_CHECKS))
            variants = [dict(self.report(), session='b' * 32), dict(self.report(), success=False),
                        dict(self.report(), schema_version=True), dict(self.report(), checks=[]),
                        dict(self.report(), checks=sorted(CLIENT_CHECKS) + ['secret']),
                        dict(self.report(), error='raw secret'), dict(self.report(), cookies='secret'),
                        dict(self.report(), http_statuses={'200': 1}),
                        dict(self.report(), http_statuses={**self.report()['http_statuses'], '200': True})]
            for variant in variants:
                filename.write_text(json.dumps(variant), encoding='utf-8')
                with self.subTest(keys=list(variant)), self.assertRaises(ValueError):
                    validate_client_report(filename, 'a' * 32)
            filename.write_text(' ' * 32769, encoding='utf-8')
            with self.assertRaises(ValueError):
                validate_client_report(filename, 'a' * 32)

    def test_observer_checks_real_metadata_and_records_remote_budget(self):
        observations = Observations('192.168.10.2', '192.168.10.3', '192.168.10.2:8443', 'a' * 32)
        application = Mock(side_effect=lambda environ, respond: respond('429 Too Many Requests', []))
        wrapped = observations.wrap(application)
        environ = {'REMOTE_ADDR': '192.168.10.3', 'wsgi.url_scheme': 'https', 'HTTP_HOST': '192.168.10.2:8443',
                   'PATH_INFO': '/api/version', 'QUERY_STRING': 'lan_budget=' + 'a' * 32}
        wrapped(environ, Mock())
        self.assertEqual(observations.counts, {'server': 0, 'client': 1})
        self.assertEqual(observations.invalid, 0)
        self.assertGreater(observations.remote_429, 0)
        self.assertGreater(observations.budget_marked, 0)
        for change in ({'REMOTE_ADDR': '198.51.100.2'}, {'wsgi.url_scheme': 'http'}, {'HTTP_HOST': 'evil.invalid'}, {'HTTP_FORWARDED': 'for=evil'}):
            wrapped({**environ, **change}, Mock())
        self.assertEqual(observations.invalid, 4)

    def test_budget_needs_fresh_remote_exhaustion_and_uses_public_origin(self):
        fixture = LanFixture.__new__(LanFixture)
        fixture.observations = Observations('192.168.10.2', '192.168.10.3', '192.168.10.2:8443', 'a' * 32)
        fixture.args = SimpleNamespace(port=8443)
        fixture.runtime = Mock()
        fixture.runtime.profile.public_origin = 'https://192.168.10.2:8443'
        with self.assertRaises(RuntimeError), patch('tools.check_lan_https.Client') as client_type:
            fixture.budget()
        client_type.assert_not_called()
        fixture.observations.remote_429 = time.monotonic()
        fixture.observations.budget_marked = time.monotonic()
        with patch('tools.check_lan_https.Client') as client_type:
            fixture.budget()
            self.assertEqual(client_type.return_value.base, 'https://192.168.10.2:8443')
            self.assertEqual(client_type.return_value.form.call_args.args[-1], 401)
        self.assertGreater(fixture.local_budget, 0)

    def test_browser_observations_enforce_fixed_results_order_and_real_update(self):
        fixture = SimpleNamespace(browser={}, updated=False)
        for line in ('record trusted arbitrary', 'record trusted pages_images_navigation_fullscreen', 'record removed ERR_CERT_AUTHORITY_INVALID'):
            with self.subTest(line=line), self.assertRaises(ValueError):
                execute(fixture, line)
        execute(fixture, 'record untrusted ' + BROWSER_RESULTS['untrusted'])
        execute(fixture, 'record trusted ' + BROWSER_RESULTS['trusted'])
        with self.assertRaises(ValueError):
            execute(fixture, 'record updated ' + BROWSER_RESULTS['updated'])
        fixture.updated = True
        execute(fixture, 'record updated ' + BROWSER_RESULTS['updated'])
        execute(fixture, 'record removed ' + BROWSER_RESULTS['removed'])
        self.assertEqual(fixture.browser, BROWSER_RESULTS)

    def test_finish_does_not_accept_only_browser_or_client_claims(self):
        fixture = LanFixture.__new__(LanFixture)
        fixture.observations = Observations('192.168.10.2', '192.168.10.3', '192.168.10.2:8443', 'a' * 32)
        fixture.restarted = fixture.updated = True
        fixture.client_report = self.report()
        fixture.browser = dict(BROWSER_RESULTS)
        fixture.local_budget = 0
        with self.assertRaises(RuntimeError):
            fixture.finish()
        fixture.observations.counts = {'server': 1, 'client': 1}
        fixture.local_budget = 2
        fixture.observations.remote_429 = 1
        with self.assertRaises(RuntimeError):
            fixture.finish()

    def test_forced_or_incomplete_cleanup_is_not_success(self):
        valid = {'proxy_forced': False, 'proxy_exit_code': 0, 'backend_stopped': True, 'temporary_removed': True}
        self.assertTrue(cleanup_ok(valid))
        for key, value in (('proxy_forced', True), ('proxy_exit_code', 1), ('backend_stopped', False), ('temporary_removed', False)):
            self.assertFalse(cleanup_ok({**valid, key: value}))
        fixture = LanFixture.__new__(LanFixture)
        fixture.runtime = Mock()
        fixture.runtime.close.return_value = {**valid, 'proxy_forced': True}
        fixture.cleanups = []
        with self.assertRaises(RuntimeError):
            fixture.stop()
        self.assertIsNone(fixture.runtime)
        self.assertEqual(len(fixture.cleanups), 1)

    def test_preparation_failure_stops_fixture_removes_data_and_reports_pending(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            fixture = Mock()
            fixture.prepare.side_effect = RuntimeError('sensitive preparation details')
            fixture.cleanups = []
            with patch('tools.check_lan_https.validate_addresses', return_value=('192.168.10.2', '192.168.10.3')), \
                    patch('tools.check_lan_https.getpass.getpass', return_value='disposable-test-password'), \
                    patch('tools.check_lan_https.LanFixture', return_value=fixture), \
                    patch('tools.check_lan_https.__file__', str(root / 'tools/helper.py')), redirect_stdout(io.StringIO()):
                result = main(['--server-ip', '192.168.10.2', '--client-ip', '192.168.10.3', '--caddy', __file__, '--pwsh', __file__])
            self.assertEqual(result, 1)
            fixture.stop.assert_called_once()
            report = json.loads(next((root / 'logs/https').glob('lan-*.json')).read_text(encoding='utf-8'))
            self.assertEqual(report['physical_lan'], 'Pending')
            self.assertFalse(report['success'])
            self.assertTrue(report['cleanup']['temporary_removed'])
            self.assertNotIn('sensitive', json.dumps(report))

    def test_firewall_commands_are_exact_scoped_and_never_run(self):
        args = SimpleNamespace(server_ip='192.168.10.2', client_ip='192.168.10.3', port=8443)
        add, remove = firewall_commands(args, 'a' * 32)
        self.assertIn('-LocalAddress 192.168.10.2 -LocalPort 8443 -RemoteAddress 192.168.10.3 -Profile Private', add)
        self.assertEqual(remove, "Remove-NetFirewallRule -Name 'Kiosk-LAN-test-" + 'a' * 32 + "'")

    def test_isolated_update_and_media_acceptance_preserve_working_installation(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            args = SimpleNamespace(server_ip='192.168.10.2', client_ip='192.168.10.3', port=8443)
            fixture = LanFixture(args, root, 'disposable-test-password')
            app = fixture.factory({'TESTING': True})
            fixture.runtime = SimpleNamespace(app=app)
            client = browser_client(app)
            self.assertEqual(client.post('/admin/login', data={'username': 'admin', 'password': 'disposable-test-password'}).status_code, 302)
            image = io.BytesIO()
            Image.new('RGB', (64, 64), 'teal').save(image, 'PNG')
            image.seek(0)
            self.assertEqual(client.post('/admin/events/create', data={'title': 'LAN fixture', 'status': 'active', 'event_image': (image, 'fixture.png')}).status_code, 302)
            fixture.browser = dict(BROWSER_RESULTS)
            fixture.observations.counts = {'server': 1, 'client': 1}
            fixture.observations.invalid = 0
            fixture.local_budget = 1
            fixture.observations.remote_429 = 2
            fixture.restarted = True
            fixture.client_report = self.report()
            before = client.get('/api/version').json['content_version']
            fixture.update()
            self.assertGreater(client.get('/api/version').json['content_version'], before)
            self.assertEqual(client.get('/api/events').json['events'][0]['title'], 'LAN updated')
            fixture.finish()


@unittest.skipUnless(os.name == 'nt' and shutil.which('pwsh'), 'Requires Windows PowerShell 7')
class LanPowerShellTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temporary = tempfile.TemporaryDirectory(prefix='kiosk-lan-unit-')
        cls.root = Path(cls.temporary.name)
        cls.repository = Path(__file__).resolve().parent.parent
        cls.pwsh = shutil.which('pwsh')
        result = subprocess.run([cls.pwsh, '-NoProfile', '-NonInteractive', '-File', str(cls.repository / 'tools/https_certificates.ps1'),
                                 '-OutputDirectory', str(cls.root), '-LanAddress', '192.168.10.2'], capture_output=True, timeout=30)
        if result.returncode:
            cls.temporary.cleanup()
            raise RuntimeError('Certificate fixture failed')
        Image.new('RGB', (64, 64), 'teal').save(cls.root / 'fixture.png')

    @classmethod
    def tearDownClass(cls):
        cls.temporary.cleanup()

    def powershell(self, source, arguments):
        filename = self.root / 'check.ps1'
        filename.write_text(source, encoding='utf-8')
        return subprocess.run([self.pwsh, '-NoProfile', '-NonInteractive', '-File', str(filename), *arguments], capture_output=True, timeout=30)

    def test_generator_adds_lan_san_and_rejects_unsafe_input_before_writes(self):
        certificate = ssl._ssl._test_decode_cert(str(self.root / 'valid.pem'))
        self.assertIn(('IP Address', '192.168.10.2'), certificate['subjectAltName'])
        self.assertIn(('IP Address', '127.0.0.1'), certificate['subjectAltName'])
        self.assertFalse((self.root / 'authority.key').exists())
        invalid = self.root / 'invalid'
        result = subprocess.run([self.pwsh, '-NoProfile', '-NonInteractive', '-File', str(self.repository / 'tools/https_certificates.ps1'),
                                 '-OutputDirectory', str(invalid), '-LanAddress', '127.0.0.1'], capture_output=True, timeout=15)
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse(invalid.exists())

    def test_powershell_real_tls_login_and_rejection_with_explicit_ca(self):
        source = '''param($Library, $Authority, $Digest, $Origin, $Mode)
. $Library -LibraryOnly
$script:origin = $Origin
$script:codes = @{}
$pem = [IO.File]::ReadAllText($Authority)
$transport = [KioskLanTls]::new($pem, $Digest, $true)
try {
    if ($Mode -eq 'valid') {
        try { $null = Invoke-LanRequest $transport '/api/version' } catch { throw $_.Exception.ToString() }
        Test-LanHostRejection $transport
        if ($script:codes['400'] -ne 1) { throw 'Missing actual Host rejection status' }
        $null = Send-LanForm $transport '/admin/login' @{username='admin';password='disposable-test-password'}
        $null = Invoke-LanRequest $transport '/admin'
        if ($script:codes['302'] -ne 1 -or $script:codes['200'] -lt 2) { throw 'Missing status evidence' }
        $before = (Invoke-LanRequest $transport '/api/version').Text | ConvertFrom-Json
        $multipart = [Net.Http.MultipartFormDataContent]::new()
        $multipart.Add([Net.Http.StringContent]::new('LAN fixture'), 'title')
        $multipart.Add([Net.Http.StringContent]::new('active'), 'status')
        $image = [Net.Http.ByteArrayContent]::new([IO.File]::ReadAllBytes((Join-Path (Split-Path $Authority) 'fixture.png')))
        $image.Headers.ContentType = [Net.Http.Headers.MediaTypeHeaderValue]::new('image/png')
        $multipart.Add($image, 'event_image', 'fixture.png')
        $null = Invoke-LanRequest $transport '/admin/events/create' 302 $multipart @{'X-CSRF-Token'=(Get-LanToken $transport)}
        $event = ((Invoke-LanRequest $transport '/api/events').Text | ConvertFrom-Json).events[0]
        foreach ($field in @('image_kiosk','image_tv','image_thumb')) {
            $imageResponse = Invoke-LanRequest $transport $event.$field
            if ($imageResponse.Bytes[0] -ne 255 -or $imageResponse.Bytes[1] -ne 216) { throw 'Missing JPEG' }
        }
        $after = (Invoke-LanRequest $transport '/api/version').Text | ConvertFrom-Json
        if ($after.content_version -le $before.content_version) { throw 'Version unchanged' }
        $cookie = [KioskLanTls]::new($pem, $Digest, $true)
        try {
            foreach ($entry in $transport.Cookies.GetCookies([uri]$Origin)) { $cookie.Cookies.Add([uri]$Origin, [Net.Cookie]::new($entry.Name,$entry.Value,$entry.Path)) }
            $null = Send-LanForm $transport '/admin/password/change' @{current_password='disposable-test-password';new_password='replacement-test-password';confirm_password='replacement-test-password'}
            $null = Invoke-LanRequest $cookie '/admin' 302
            $null = Send-LanForm $transport '/admin/login' @{username='admin';password='replacement-test-password'}
            $null = Invoke-LanRequest $transport '/admin'
        } finally { $cookie.Dispose() }
        $unknown = [KioskLanTls]::new($pem, $Digest, $false)
        try {
            $rejected = $false
            try { $null = Invoke-LanRequest $unknown '/api/version' } catch { $rejected = $unknown.CallbackSeen -and ($unknown.LastErrors -band [Net.Security.SslPolicyErrors]::RemoteCertificateChainErrors) }
            if (-not $rejected) { throw 'Unknown CA accepted or no TLS observed' }
            $unknown.CallbackSeen = $false
            $rejected = $false
            try { Test-LanHostRejection $unknown } catch { $rejected = $unknown.CallbackSeen -and $script:LanResponseStatus -eq 0 }
            if (-not $rejected) { throw 'Host probe bypassed unknown authority' }
        } finally { $unknown.Dispose() }
    } else {
        $rejected = $false
        try { $null = Invoke-LanRequest $transport '/api/version' } catch {
            $rejected = $transport.CallbackSeen
            if (-not $rejected) { throw $_.Exception.ToString() }
        }
        if (-not $rejected) { throw 'Invalid TLS accepted' }
        $transport.CallbackSeen = $false
        $rejected = $false
        try { Test-LanHostRejection $transport } catch { $rejected = $transport.CallbackSeen -and $script:LanResponseStatus -eq 0 }
        if (-not $rejected) { throw 'Host probe bypassed certificate identity or validity' }
    }
} finally { $transport.Dispose() }
'''
        for fixture in ('valid', 'wrong-name', 'expired'):
            with self.subTest(fixture=fixture), tempfile.TemporaryDirectory() as installation:
                app = fixture_factory(Path(installation), 'disposable-test-password')({'TRUSTED_HOSTS': ['127.0.0.1']})
                server = make_server('127.0.0.1', 0, app, ssl_context=(str(self.root / (fixture + '.pem')), str(self.root / (fixture + '.key'))))
                thread = threading.Thread(target=server.serve_forever, daemon=True)
                thread.start()
                try:
                    result = self.powershell(source, [str(self.repository / 'tools/check_lan_https.ps1'), str(self.root / 'authority.pem'),
                        authority_digest(self.root / 'authority.pem'), f'https://127.0.0.1:{server.server_port}', fixture])
                    self.assertEqual(result.returncode, 0, result.stderr.decode(errors='replace'))
                finally:
                    server.shutdown()
                    thread.join(timeout=3)
                    server.server_close()

    def test_client_digest_mismatch_fails_before_any_request_or_trust(self):
        result = self.powershell('''param($Library, $Authority)
. $Library -LibraryOnly
$rejected = $false
try { $transport = [KioskLanTls]::new([IO.File]::ReadAllText($Authority), ('0' * 64), $true); $transport.Dispose() } catch { $rejected = $true }
if (-not $rejected) { throw 'Wrong digest accepted' }
''', [str(self.repository / 'tools/check_lan_https.ps1'), str(self.root / 'authority.pem')])
        self.assertEqual(result.returncode, 0, result.stderr.decode(errors='replace'))

    def test_actual_managed_fixture_checks_listeners_and_preserves_session_on_restart(self):
        caddy = self.repository / 'logs/https-tools/caddy/caddy.exe'
        if not caddy.is_file():
            self.skipTest('Pinned developer Caddy executable is not prepared')
        with tempfile.TemporaryDirectory(prefix='kiosk-lan-managed-unit-') as directory:
            root = Path(directory)
            with socket.socket() as reserved:
                reserved.bind(('127.0.0.1', 0))
                port = reserved.getsockname()[1]
            args = SimpleNamespace(server_ip='127.0.0.1', client_ip='127.0.0.2', port=port, pwsh=Path(self.pwsh))
            fixture = LanFixture(args, root, 'disposable-test-password')
            fixture.manifest.parent.mkdir()
            fixture.profile_file.write_text(json.dumps({'schema_version': 1, 'public_origin': f'https://127.0.0.1:{port}',
                'listen_host': '127.0.0.1', 'caddy_executable': str(caddy), 'certificate_file': str(self.root / 'valid.pem'),
                'private_key_file': str(self.root / 'valid.key'), 'ca_file': str(self.root / 'authority.pem')}), encoding='utf-8')
            try:
                fixture.start()
                client = Client(port, fixture.runtime.profile.trust_context(), time.monotonic() + 30, {'http_statuses': {}})
                client.form('/admin/login', {'username': 'admin', 'password': 'disposable-test-password'})
                identity = fixture.runtime.identity
                fixture.restart()
                self.assertNotEqual(fixture.runtime.identity, identity)
                client.request('/admin')
                self.assertEqual(fixture.observations.invalid, 0)
                self.assertGreater(fixture.observations.counts['server'], 0)
                self.assertEqual(fixture.observations.counts['client'], 0)
                with self.assertRaises(RuntimeError):
                    fixture.finish()
            finally:
                fixture.stop()
            self.assertEqual(len(fixture.cleanups), 2)
            self.assertTrue(all(cleanup_ok(result) for result in fixture.cleanups))


if __name__ == '__main__':
    unittest.main()
