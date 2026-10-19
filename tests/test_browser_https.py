import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from tools.check_browser_https import BROWSER_RESULTS, BrowserFixture, BrowserTrust, execute


class BrowserHttpsTests(unittest.TestCase):
    def trust(self):
        with patch('tools.check_browser_https.authority_digest', return_value='a' * 64):
            return BrowserTrust(Path('pwsh.exe'), Path('authority.pem'), Path('.'))

    def test_existing_authority_is_not_owned_or_removed(self):
        trust = self.trust()
        trust.invoke = Mock(return_value=1)
        with self.assertRaises(RuntimeError):
            trust.enroll()
        trust.remove()
        self.assertFalse(trust.owned)
        trust.invoke.assert_called_once_with('inspect')

    def test_uncertain_enrollment_is_removed_and_removal_is_idempotent(self):
        trust = self.trust()
        trust.invoke = Mock(side_effect=[0, TimeoutError(), 0])
        with self.assertRaises(TimeoutError):
            trust.enroll()
        self.assertTrue(trust.owned)
        trust.remove()
        trust.remove()
        self.assertFalse(trust.owned)
        self.assertEqual([call.args[0] for call in trust.invoke.call_args_list], ['inspect', 'add', 'remove'])

    def test_failed_removal_retains_ownership_for_recovery(self):
        trust = self.trust()
        trust.owned = True
        trust.invoke = Mock(return_value=1)
        with self.assertRaises(RuntimeError):
            trust.remove()
        self.assertTrue(trust.owned)

    def test_store_output_and_failures_are_checked_without_raw_output(self):
        trust = self.trust()
        outputs = [subprocess.CompletedProcess([], 1, b'private output', b'private error'),
                   subprocess.CompletedProcess([], 0, json.dumps({'sha256': 'b' * 64, 'present': 0}).encode()),
                   subprocess.CompletedProcess([], 0, json.dumps({'sha256': 'a' * 64, 'present': True}).encode())]
        for result in outputs:
            with self.subTest(result=result.returncode), patch('tools.check_browser_https.subprocess.run', return_value=result), self.assertRaises(RuntimeError) as raised:
                trust.invoke('inspect')
            self.assertNotIn('private', str(raised.exception))

    def test_cleanup_continues_after_browser_or_authority_failure(self):
        fixture = BrowserFixture.__new__(BrowserFixture)
        fixture.report = {'cleanup': {}}
        fixture.close_browser = Mock(side_effect=TimeoutError())
        fixture.trust = Mock()
        fixture.trust.remove.side_effect = RuntimeError()
        proxy = Mock()
        proxy.close.return_value = {'stopped': True}
        fixture.proxies = {'expired': proxy}
        fixture.runtime = Mock()
        fixture.runtime.close.return_value = {'backend_stopped': True, 'temporary_removed': True, 'proxy_forced': False}
        with self.assertRaises(RuntimeError):
            fixture.close()
        fixture.trust.remove.assert_called_once()
        proxy.close.assert_called_once()
        fixture.runtime.close.assert_called_once()
        self.assertFalse(fixture.report['cleanup']['browser'])
        self.assertFalse(fixture.report['cleanup']['authority'])

    def test_browser_rejects_invalid_stage_and_wrong_trust_state(self):
        fixture = BrowserFixture.__new__(BrowserFixture)
        fixture.close_browser = Mock()
        fixture.trust = Mock(owned=False)
        for stage in ('invalid', 'updated', 'trusted', 'wrong-name', 'expired'):
            with self.subTest(stage=stage), self.assertRaises((ValueError, RuntimeError)):
                fixture.open_browser(stage)

    def test_browser_assignment_failure_stops_the_unassigned_process(self):
        with tempfile.TemporaryDirectory() as directory:
            fixture = BrowserFixture.__new__(BrowserFixture)
            fixture.root = Path(directory)
            fixture.close_browser = Mock()
            fixture.trust = Mock(owned=False)
            fixture.port = 12345
            fixture.browser_count = 0
            fixture.chrome = Path('chrome.exe')
            process = Mock()
            job = Mock()
            job.assign.side_effect = OSError()
            with patch('tools.check_browser_https.OwnedJob', return_value=job), patch('tools.check_browser_https.subprocess.Popen', return_value=process), self.assertRaises(OSError):
                fixture.open_browser('untrusted')
            process.kill.assert_called_once()
            process.wait.assert_called_once_with(timeout=10)

    def test_observations_require_matching_stage_and_fixed_result(self):
        fixture = Mock(stage='untrusted')
        report = {'browser_observations': {}}
        for line in ('record trusted pages_and_media_loaded', 'record untrusted arbitrary', 'unknown'):
            with self.subTest(line=line), self.assertRaises(ValueError):
                execute(fixture, line, report)
        self.assertEqual(report['browser_observations'], {})
        execute(fixture, 'record untrusted ERR_CERT_AUTHORITY_INVALID', report)
        self.assertEqual(report['browser_observations']['untrusted'], BROWSER_RESULTS['untrusted'])

    def test_finish_requires_all_checks_observations_and_removed_trust(self):
        fixture = Mock()
        fixture.trust.owned = False
        report = {'browser_observations': {}, 'checks': []}
        with self.assertRaises(RuntimeError):
            execute(fixture, 'finish', report)
        report['browser_observations'] = dict(BROWSER_RESULTS)
        report['checks'] = ['routes_login_csrf_secure_cookie', 'multipart_event_three_images_version_fullscreen',
                            'password_change_revokes_previous_cookie', 'forwarded_spoofing_host_and_authentication_limits',
                            'request_body_limit']
        fixture.trust.owned = True
        with self.assertRaises(RuntimeError):
            execute(fixture, 'finish', report)
        fixture.trust.owned = False
        self.assertFalse(execute(fixture, 'finish', report))

    def test_update_preserves_browser_and_requires_prior_inspection(self):
        fixture = BrowserFixture.__new__(BrowserFixture)
        fixture.stage = 'trusted'
        fixture.report = {'browser_observations': {}}
        fixture.client = Mock()
        with self.assertRaises(RuntimeError):
            fixture.update()
        fixture.report['browser_observations']['trusted'] = BROWSER_RESULTS['trusted']
        fixture.update()
        fixture.client.form.assert_called_once()
        self.assertEqual(fixture.stage, 'updated')


if __name__ == '__main__':
    unittest.main()
