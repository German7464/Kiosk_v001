import json
import socket
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from kiosk.app import create_app
from kiosk.launcher.client import check_ready, export_diagnostics, read_status
from kiosk.launcher.runtime import supervise
from kiosk.launcher.storage import DIRECTORIES, Storage, needs_administrator, new_profile, save_profile
from kiosk.core.credentials import save_admin_password


class LauncherRuntimeTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.storage = Storage(Path(self.directory.name) / "installed")
        for name in DIRECTORIES:
            self.storage.directory(name).mkdir(parents=True)
        with socket.socket() as listener:
            listener.bind(("127.0.0.1", 0))
            port = listener.getsockname()[1]
        self.profile = new_profile("Isolated Runtime", port=port)
        save_profile(self.storage, self.profile)

    def test_real_http_readiness_identity_duplicate_owner_and_cleanup(self):
        stopped = threading.Event()
        ready = threading.Event()
        result = []
        thread = threading.Thread(target=lambda: result.append(supervise(self.storage, stopped, running=ready.set, delays=())), daemon=True)
        thread.start()
        try:
            self.assertTrue(ready.wait(10))
            status = read_status(self.storage)
            self.assertTrue(check_ready(self.storage, status))
            self.assertFalse(check_ready(self.storage, {**status, "identity": "another server"}))
            self.assertEqual(supervise(self.storage, threading.Event(), delays=()), 1)
            self.assertEqual(read_status(self.storage)["state"], "running")
            time.sleep(2.2)
            self.assertGreater(read_status(self.storage)["updated_at"], status["updated_at"])
            destination = Path(self.directory.name) / "diagnostics.zip"
            export_diagnostics(self.storage, destination)
            import zipfile

            with zipfile.ZipFile(destination) as archive:
                self.assertEqual(set(archive.namelist()), {"README.txt", "status.json"})
                data = archive.read("status.json").decode()
                self.assertNotIn(status["device_id"], data)
                self.assertNotIn(status["identity"], data)
            with self.assertRaises(FileExistsError):
                export_diagnostics(self.storage, destination)
        finally:
            stopped.set()
            thread.join(timeout=15)
        self.assertFalse(thread.is_alive())
        self.assertEqual(result, [0])
        self.assertEqual(read_status(self.storage)["state"], "stopped")
        self.assertFalse(check_ready(self.storage, read_status(self.storage)))
        with socket.socket() as listener:
            listener.bind(("127.0.0.1", self.profile["port"]))

    def test_busy_listener_fails_without_reusing_other_server(self):
        with socket.socket() as listener:
            listener.bind(("127.0.0.1", self.profile["port"]))
            listener.listen()
            self.assertEqual(supervise(self.storage, threading.Event(), delays=()), 1)
            self.assertEqual(read_status(self.storage)["state"], "failed")
            self.assertNotEqual(listener.fileno(), -1)

    def test_bounded_restarts_and_failed_cleanup(self):
        with patch("kiosk.launcher.runtime.LocalRuntime") as runtime:
            runtime.return_value.identity = "isolated-test-identity"
            runtime.return_value.close.return_value = None
            runtime.return_value.check_running.side_effect = RuntimeError("sensitive value")
            stopped = Mock()
            stopped.wait.return_value = False
            self.assertEqual(supervise(self.storage, stopped, delays=(0, 0, 0)), 1)
            self.assertEqual(runtime.call_count, 4)
            self.assertEqual(runtime.return_value.close.call_count, 4)
            self.assertNotIn("sensitive value", (self.storage.directory("logs") / "startup.log").read_text())
            self.assertEqual(read_status(self.storage)["error"], "RuntimeError")

    def test_interrupted_initial_setup_still_requires_admin(self):
        self.assertTrue(needs_administrator(self.storage))
        app = create_app(self.storage.app_config())
        self.assertTrue(needs_administrator(self.storage))
        save_admin_password(app, "isolated-runtime-password", setup=True)
        self.assertFalse(needs_administrator(self.storage))


if __name__ == "__main__":
    unittest.main()
