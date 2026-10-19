import io
import json
import tempfile
import time
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import Mock, patch

from tools.check_https_prototype import main, run_scenario, verified_context
from tools.https_runtime import Proxy, caddy_configuration, remaining, safe_report, stop_process, verify_caddy


class HttpsPrototypeTests(unittest.TestCase):
    def test_configuration_has_no_public_backend_or_automatic_trust(self):
        configuration = caddy_configuration(24443, 25000)
        for required in ("admin off", "persist_config off", "auto_https off", "skip_install_trust",
                         "bind 127.0.0.1", "reverse_proxy 127.0.0.1:25000", "tls valid.pem valid.key",
                         "protocols h1 h2", "max_size 20971520", "respond @invalid 400",
                         "request_header -Forwarded", "request_header -X-Forwarded-*", "request_header -X-Real-IP",
                         "header_up X-Forwarded-Proto https", "header_up X-Forwarded-Host 127.0.0.1:24443"):
            self.assertIn(required, configuration)
        for forbidden in ("0.0.0.0", "tls internal", "http://", "trusted_proxies", "local_certs"):
            self.assertNotIn(forbidden, configuration)

    def test_configuration_rejects_injection_and_bad_ports(self):
        for arguments in ((0, 25000), (24443, "25000"), (True, 25000), (65536, 25000),
                          (24443, 25000, "valid\nadmin :2019"), (24443, 25000, "valid", "../../private")):
            with self.subTest(arguments=arguments), self.assertRaises(ValueError):
                caddy_configuration(*arguments)

    def test_deadline_does_not_allow_a_new_wait_after_expiry(self):
        with self.assertRaises(TimeoutError):
            remaining(time.monotonic() - 1)
        self.assertLessEqual(remaining(time.monotonic() + 100), 10)

    def test_wrong_binary_is_rejected_before_execution(self):
        with tempfile.TemporaryDirectory() as directory:
            executable = Path(directory) / "caddy.exe"
            executable.write_bytes(b"untrusted executable")
            with patch("tools.https_runtime.command") as command, self.assertRaises(ValueError):
                verify_caddy(executable, directory, time.monotonic() + 10)
            command.assert_not_called()

    def test_report_refuses_unexpected_fields_and_overwrite(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "report.json"
            with self.assertRaises(ValueError):
                safe_report(output, {"password": "private"})
            safe_report(output, {"success": False, "error": "TimeoutError"})
            self.assertEqual(json.loads(output.read_text(encoding="utf-8")), {"success": False, "error": "TimeoutError"})
            with self.assertRaises(FileExistsError):
                safe_report(output, {"success": True})

    def test_backend_stop_uses_graceful_then_bounded_fallback(self):
        process = Mock()
        process.is_alive.side_effect = [False, False]
        process.exitcode = 0
        stopped = Mock()
        self.assertEqual(stop_process(process, stopped), {"stopped": True, "forced": False, "exit_code": 0})
        stopped.set.assert_called_once()
        process.terminate.assert_not_called()
        process = Mock()
        process.is_alive.side_effect = [True, False]
        process.exitcode = -15
        self.assertTrue(stop_process(process, Mock())["forced"])
        process.terminate.assert_called_once()
        self.assertEqual(process.join.call_count, 2)

    def test_failed_proxy_start_waits_for_owned_process(self):
        process = Mock()
        process.poll.return_value = 1
        process.returncode = 1
        with tempfile.TemporaryDirectory() as directory, patch("tools.https_runtime.subprocess.Popen", return_value=process):
            with self.assertRaises(RuntimeError):
                Proxy("caddy.exe", directory, 25000, time.monotonic() + 10)
        process.wait.assert_called_once_with(timeout=5)
        process.terminate.assert_not_called()

    def test_expired_scenario_does_not_launch_a_proxy(self):
        with tempfile.TemporaryDirectory() as directory, patch("tools.https_runtime.subprocess.Popen") as launch:
            with self.assertRaises(TimeoutError):
                Proxy("caddy.exe", directory, 25000, time.monotonic() - 1)
        launch.assert_not_called()

    def test_still_running_backend_cannot_be_reported_as_cleaned(self):
        process = Mock()
        process.is_alive.return_value = True
        with self.assertRaises(RuntimeError):
            stop_process(process, Mock())

    def test_backend_cleanup_runs_even_when_proxy_cleanup_fails(self):
        backend = Mock()
        backend.port = 25000
        proxy = Mock()
        proxy.port = 24443
        proxy.close.side_effect = RuntimeError("proxy cleanup failed")
        report = {"checks": [], "cleanup": {}, "http_statuses": {}}
        with tempfile.TemporaryDirectory() as directory, patch("tools.check_https_prototype.verify_caddy"), patch(
                "tools.check_https_prototype.command", return_value=Mock(stdout=b"7.6.6")), patch(
                "tools.check_https_prototype.verified_context"), patch(
                "tools.check_https_prototype.Backend", return_value=backend), patch(
                "tools.check_https_prototype.Proxy", return_value=proxy), patch(
                "tools.check_https_prototype.check_listeners"), patch(
                "tools.check_https_prototype.http.client.HTTPConnection") as http, patch(
                "tools.check_https_prototype.exercise_application", side_effect=ValueError("scenario failed")):
            response = http.return_value.getresponse.return_value.__enter__.return_value
            response.status = 400
            response.getheader.return_value = None
            with self.assertRaises(RuntimeError):
                run_scenario(Path("caddy.exe"), Path("pwsh.exe"), Path(directory), time.monotonic() + 10, report)
        backend.close.assert_called_once()

    def test_failed_scenario_removes_private_files_and_sanitizes_error(self):
        roots = []
        reports = []

        def fail(caddy, pwsh, root, deadline, report):
            roots.append(root)
            (root / "private.key").write_text("private fixture", encoding="utf-8")
            report["phase"] = "certificates"
            raise RuntimeError("sensitive subprocess output")

        with patch("tools.check_https_prototype.run_scenario", side_effect=fail), patch(
                "tools.check_https_prototype.safe_report", side_effect=lambda path, report: reports.append(report.copy())):
            with redirect_stdout(io.StringIO()) as output:
                result = main(["--caddy", "unused.exe", "--pwsh", "unused.exe"])
        self.assertEqual(result, 1)
        self.assertFalse(roots[0].exists())
        self.assertTrue(reports[0]["cleanup"]["temporary_removed"])
        self.assertEqual(reports[0]["error"], "RuntimeError")
        self.assertNotIn("sensitive", output.getvalue())
        self.assertNotIn("private fixture", output.getvalue())

    def test_tls_context_keeps_verification_enabled(self):
        with patch("tools.check_https_prototype.ssl.create_default_context") as factory:
            verified_context(Path("authority.pem"))
        factory.assert_called_once_with(cafile="authority.pem")


if __name__ == "__main__":
    unittest.main()
