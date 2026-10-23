import hashlib
import io
import json
import subprocess
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest.mock import Mock, patch

from kiosk.transport.profile import HttpsProfile, load_profile, proxy_configuration
from kiosk.transport.runtime import ManagedHttps, probe_https, run_https
from serve import main, parse_args


class ManagedHttpsTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.data = {"schema_version": 1, "public_origin": "https://kiosk.example:8443", "listen_host": "0.0.0.0",
                     "caddy_executable": "caddy.exe", "certificate_file": "server.pem", "private_key_file": "server.key", "ca_file": "authority.pem"}
        for name in ("caddy.exe", "server.pem", "server.key", "authority.pem"):
            (self.root / name).write_bytes(b"fixture")
        self.filename = self.root / "https.json"
        self.filename.write_text(json.dumps(self.data), encoding="utf-8")
        self.pin = hashlib.sha256(b"fixture").hexdigest()

    def load(self, data=None):
        if data is not None:
            self.filename.write_text(json.dumps(data), encoding="utf-8")
        with patch("kiosk.transport.profile.CADDY_SHA256", self.pin), patch("kiosk.transport.profile.ssl.SSLContext"):
            return load_profile(self.filename)

    def test_profile_paths_are_relative_to_configuration_and_origin_is_canonical(self):
        profile = self.load()
        self.assertEqual(profile.caddy_executable, self.root / "caddy.exe")
        self.assertEqual(profile.authority, "kiosk.example:8443")
        self.assertEqual(profile.port, 8443)
        profile = self.load({**self.data, "public_origin": "https://127.0.0.1:443"})
        self.assertEqual(profile.public_origin, "https://127.0.0.1")

    def test_invalid_origins_and_listeners_are_rejected(self):
        invalid = ("http://kiosk.example", "https://user@kiosk.example", "https://kiosk.example/", "https://kiosk.example?x=1",
                   "https://kiosk.example#x", "https://[::1]", "https://kiosk.example:0", "https://kiosk.example:65536",
                   "https://kiosk.example:", "https://bad..example", "https://-bad.example", "https://127.1",
                   "https://kiosk.example\nadmin", "https://kiosk.example:008443")
        for origin in invalid:
            with self.subTest(origin=origin), self.assertRaises(ValueError):
                self.load({**self.data, "public_origin": origin})
        for listener in ("localhost", "::1", "127.1", "0.0.0.0\nadmin", True):
            with self.subTest(listener=listener), self.assertRaises(ValueError):
                self.load({**self.data, "listen_host": listener})

    def test_schema_duplicate_unknown_and_oversized_configurations_are_rejected(self):
        for data in ({**self.data, "extra": 1}, {**self.data, "schema_version": True}, {**self.data, "schema_version": 2}, [], {"schema_version": 1}):
            with self.subTest(data_type=type(data).__name__), self.assertRaises(ValueError):
                self.load(data)
        self.filename.write_text('{"schema_version":1,"schema_version":1}', encoding="utf-8")
        with self.assertRaises(ValueError):
            load_profile(self.filename)
        self.filename.write_bytes(b" " * 65537)
        with self.assertRaises(ValueError):
            load_profile(self.filename)

    def test_missing_input_or_wrong_binary_fails_without_execution(self):
        with self.assertRaises(ValueError):
            load_profile(self.filename)
        (self.root / "server.key").unlink()
        with self.assertRaises(ValueError):
            self.load()

    def test_certificate_pair_and_ca_validation_are_required(self):
        with patch("kiosk.transport.profile.CADDY_SHA256", self.pin), patch.object(HttpsProfile, "trust_context", side_effect=ValueError("invalid CA")):
            with self.assertRaises(ValueError):
                load_profile(self.filename)
        with patch("kiosk.transport.profile.CADDY_SHA256", self.pin), patch.object(HttpsProfile, "trust_context"), patch("kiosk.transport.profile.ssl.SSLContext") as context:
            context.return_value.load_cert_chain.side_effect = ValueError("mismatched key")
            with self.assertRaises(ValueError):
                load_profile(self.filename)
            self.assertEqual(context.return_value.load_cert_chain.call_args.kwargs["password"](), b"")

    def test_trust_context_loads_only_explicit_authority(self):
        profile = self.load()
        with patch("kiosk.transport.profile.ssl.SSLContext") as context:
            profile.trust_context()
        context.return_value.load_verify_locations.assert_called_once_with(cafile=str(self.root / "authority.pem"))
        context.return_value.load_default_certs.assert_not_called()

    def test_https_cli_conflicts_are_rejected_and_old_defaults_survive(self):
        self.assertEqual(parse_args([]).host, "0.0.0.0")
        for extra in (("--host", "127.0.0.1"), ("--port=8443",), ("--setup-admin",), ("--reset-admin-password",), ("--hos", "127.0.0.1")):
            with self.subTest(extra=extra), redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
                parse_args(["--https-config", "https.json", *extra])
        with patch("kiosk.transport.runtime.run_https", return_value=0) as run:
            self.assertEqual(main(["--https-config", "https.json", "--open-tv", "--no-client"]), 0)
        run.assert_called_once_with("https.json", path="/tv", auto_launch=False)

    def test_generated_configuration_restricts_admin_and_does_not_copy_key_material(self):
        profile = self.load()
        configuration = proxy_configuration(profile, 25000, 25001, 12345, "instance")
        self.assertEqual(configuration["admin"]["listen"], "127.0.0.1:25001")
        self.assertTrue(configuration["admin"]["enforce_origin"])
        server = configuration["apps"]["http"]["servers"]["protected"]
        self.assertEqual(server["listen"], ["0.0.0.0:8443"])
        self.assertTrue(server["automatic_https"]["disable"])
        handlers = server["routes"][-1]["handle"]
        self.assertEqual(handlers[0]["max_size"], 12345)
        self.assertIn("X-Forwarded-*", handlers[1]["request"]["delete"])
        self.assertEqual(handlers[2]["upstreams"], [{"dial": "127.0.0.1:25000"}])
        self.assertEqual(handlers[2]["headers"]["request"]["set"]["X-Forwarded-For"], ["{http.request.remote.host}"])
        self.assertNotIn("fixture", json.dumps(configuration))

    def test_preflight_failure_precedes_application_and_cleans_reservations(self):
        profile = self.load()
        factory = Mock()
        runtime = ManagedHttps(profile, factory)
        with patch("kiosk.transport.runtime.command", side_effect=RuntimeError("private command output")), self.assertRaises(RuntimeError):
            runtime.start()
        factory.assert_not_called()
        self.assertTrue(runtime.closed)
        self.assertTrue(runtime.close_result["temporary_removed"])
        self.assertEqual(runtime.admin_reservation.fileno(), -1)
        self.assertEqual(runtime.backend_reservation.fileno(), -1)

    def test_readiness_requires_owned_identity_and_valid_payload(self):
        profile = self.load()
        response = Mock()
        response.__enter__ = Mock(return_value=response)
        response.__exit__ = Mock(return_value=False)
        response.status = 200
        response.read.return_value = b'{"content_version":1}'
        response.getheader.return_value = "foreign-instance"
        with patch("kiosk.transport.runtime.http.client.HTTPSConnection") as connection:
            connection.return_value.getresponse.return_value = response
            self.assertFalse(probe_https(profile, Mock(), "owned-instance"))
            response.getheader.return_value = "owned-instance"
            self.assertTrue(probe_https(profile, Mock(), "owned-instance"))
            response.read.return_value = b'{"content_version":"invalid"}'
            self.assertFalse(probe_https(profile, Mock(), "owned-instance"))

    def test_failed_owned_proxy_is_not_reported_as_running(self):
        runtime = ManagedHttps(self.load())
        runtime.process = Mock()
        runtime.process.poll.return_value = 1
        with self.assertRaises(RuntimeError):
            runtime.check_running()
        runtime.process.poll.return_value = None
        runtime.loop_stopped.set()
        with self.assertRaises(RuntimeError):
            runtime.check_running()
        runtime.loop_stopped.clear()
        runtime.thread = Mock()
        runtime.thread.is_alive.return_value = True
        runtime.server = Mock()
        runtime.server.socket.fileno.return_value = -1
        with self.assertRaises(RuntimeError):
            runtime.check_running()

    def test_errors_are_sanitized_and_never_open_browser_or_http_fallback(self):
        output = io.StringIO()
        with patch("kiosk.transport.runtime.load_profile", side_effect=ValueError("private secret")), patch("kiosk.server.launch_browser") as browser, redirect_stdout(output):
            self.assertEqual(run_https(self.filename), 1)
        browser.assert_not_called()
        self.assertNotIn("private secret", output.getvalue())
        self.assertIn("no HTTP fallback", output.getvalue())

    def test_shutdown_does_not_send_stop_to_an_unidentified_admin(self):
        runtime = ManagedHttps(self.load())
        runtime.process = Mock()
        runtime.process.poll.return_value = None
        runtime.process.wait.side_effect = [subprocess.TimeoutExpired("owned proxy", 1), 0]
        runtime.job = Mock()
        runtime.server = Mock()
        runtime.server.task_dispatcher.shutdown.return_value = True
        runtime.server.task_dispatcher.threads = set()
        with patch("kiosk.transport.runtime.admin_request", return_value=(200, b'{"@id":"foreign"}')) as admin:
            result = runtime.close()
        self.assertEqual(admin.call_count, 1)
        runtime.process.kill.assert_called_once()
        runtime.job.close.assert_called_once()
        runtime.server.close.assert_called_once()
        self.assertTrue(result["proxy_forced"])
        self.assertIs(result, runtime.close())

    def test_supervisor_failure_closes_components_and_returns_nonzero(self):
        runtime = Mock()
        runtime.check_running.side_effect = RuntimeError("private details")
        runtime.close.return_value = {"proxy_forced": False, "backend_stopped": True, "temporary_removed": True, "proxy_exit_code": 0}
        output = io.StringIO()
        with patch("kiosk.transport.runtime.load_profile", return_value=self.load()), patch("kiosk.transport.runtime.ManagedHttps", return_value=runtime), redirect_stdout(output):
            self.assertEqual(run_https(self.filename, auto_launch=False), 1)
        runtime.close.assert_called_once()
        self.assertNotIn("private details", output.getvalue())

    def test_keyboard_interrupt_closes_components_successfully(self):
        runtime = Mock()
        runtime.check_running.side_effect = KeyboardInterrupt
        runtime.close.return_value = {"proxy_forced": False, "backend_stopped": True, "temporary_removed": True, "proxy_exit_code": 0}
        with patch("kiosk.transport.runtime.load_profile", return_value=self.load()), patch("kiosk.transport.runtime.ManagedHttps", return_value=runtime), redirect_stdout(io.StringIO()):
            self.assertEqual(run_https(self.filename, auto_launch=False), 0)
        runtime.close.assert_called_once()


if __name__ == "__main__":
    unittest.main()
