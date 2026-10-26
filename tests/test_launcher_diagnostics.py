import io
import logging
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from kiosk.app import create_app
from kiosk.launcher.diagnostics import instrument_app, record_failure, record_resources
from kiosk.launcher.storage import DIRECTORIES, Storage
from kiosk.launcher.runtime import logger_for


class LauncherDiagnosticsTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.storage = Storage(Path(temporary.name) / "machine")
        for name in DIRECTORIES:
            self.storage.directory(name).mkdir(parents=True)
        self.output = io.StringIO()
        self.logger = logging.Logger("isolated-diagnostics", logging.INFO)
        self.handler = logging.StreamHandler(self.output)
        self.logger.addHandler(self.handler)
        self.addCleanup(self.handler.close)
        self.app = instrument_app(create_app(self.storage.app_config()), self.logger)

    def test_requests_errors_and_slow_responses_without_secrets(self):
        @self.app.get("/diagnostic-failure/<value>")
        def failure(value):
            raise RuntimeError("secret-exception-value")

        client = self.app.test_client()
        self.assertEqual(client.get("/api/version?token=secret-query", headers={"Authorization": "secret-header"}).status_code, 200)
        self.assertEqual(client.post("/admin/login", data={"password": "secret-body"}).status_code, 403)
        self.assertEqual(client.get("/unknown-secret-path").status_code, 404)
        self.assertEqual(client.get("/diagnostic-failure/secret-route-value").status_code, 500)
        with patch("kiosk.launcher.diagnostics.time.monotonic", side_effect=[100, 101.5]):
            self.assertEqual(client.get("/api/version").status_code, 200)
        output = self.output.getvalue()
        for value in ("secret-query", "secret-header", "secret-body", "unknown-secret-path", "secret-route-value", "secret-exception-value"):
            self.assertNotIn(value, output)
        self.assertIn("route=/diagnostic-failure/<value> status=500", output)
        self.assertIn("error=RuntimeError", output)
        self.assertIn("test_launcher_diagnostics.py:", output)
        self.assertIn("duration_ms=1500.000 slow=True", output)
        self.assertIn("request_id=", output)

    def test_failure_stack_excludes_exception_messages_and_source(self):
        try:
            raise ValueError("private-key-or-password")
        except ValueError as error:
            record_failure(self.logger, "isolated_failure", error)
        output = self.output.getvalue()
        self.assertNotIn("private-key-or-password", output)
        self.assertNotIn(str(self.storage.root), output)
        self.assertIn("test_failure_stack_excludes_exception_messages_and_source", output)

    def test_low_resources_and_failed_probe(self):
        with patch("kiosk.launcher.diagnostics.shutil.disk_usage") as usage, patch("kiosk.launcher.windows.available_memory", return_value=1):
            usage.return_value.free = 1
            record_resources(self.logger, self.storage)
            usage.assert_called_once_with(self.storage.root.anchor)
            usage.side_effect = OSError("secret-filesystem-message")
            record_resources(self.logger, self.storage)
        output = self.output.getvalue()
        self.assertIn("low_disk=True low_memory=True", output)
        self.assertIn("resource_probe_failed", output)
        self.assertNotIn("secret-filesystem-message", output)

    def test_bounded_rotation_retains_latest_record(self):
        logger, handler = logger_for(self.storage)
        try:
            self.assertEqual(handler.maxBytes, 5 * 1024 * 1024)
            self.assertEqual(handler.backupCount, 4)
            handler.maxBytes = 512
            for index in range(100):
                logger.warning("event=rotation_check sequence=%d", index)
            paths = list(self.storage.directory("logs").glob("startup.log*"))
            self.assertEqual(len(paths), 5)
            self.assertTrue(all(path.stat().st_size <= 512 for path in paths))
            self.assertIn("sequence=99", (self.storage.directory("logs") / "startup.log").read_text())
        finally:
            logger.removeHandler(handler)
            handler.close()


if __name__ == "__main__":
    unittest.main()
