import json
import ctypes
import shutil
import subprocess
import tempfile
import threading
import unittest
from pathlib import Path

from kiosk.launcher.storage import DIRECTORIES, Storage, atomic_json
from kiosk.launcher.windows import grant_service_storage, hidden_run, protect_storage, service_sid


class LauncherPermissionTests(unittest.TestCase):
    def test_status_replacement_tolerates_a_real_windows_reader(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "status.json"
            atomic_json(path, {"generation": 1})
            kernel = ctypes.WinDLL("kernel32", use_last_error=True)
            kernel.CreateFileW.argtypes = [ctypes.c_wchar_p, ctypes.c_uint32, ctypes.c_uint32, ctypes.c_void_p, ctypes.c_uint32, ctypes.c_uint32, ctypes.c_void_p]
            kernel.CreateFileW.restype = ctypes.c_void_p
            kernel.CloseHandle.argtypes = [ctypes.c_void_p]
            handle = kernel.CreateFileW(str(path), 0x80000000, 1, None, 3, 0, None)
            self.assertNotEqual(handle, ctypes.c_void_p(-1).value)
            timer = threading.Timer(.15, lambda: kernel.CloseHandle(handle))
            timer.start()
            try:
                atomic_json(path, {"generation": 2})
            finally:
                timer.join(timeout=2)
            self.assertEqual(json.loads(path.read_text()), {"generation": 2})

    def descriptor(self, path):
        result = subprocess.run([shutil.which("pwsh"), "-NoProfile", "-NonInteractive", "-Command", "$p = $input | ConvertFrom-Json; (Get-Acl -LiteralPath $p).Sddl"],
                                input=json.dumps(str(path)), text=True, capture_output=True, check=True, timeout=15)
        return result.stdout.strip()

    def test_existing_explicit_public_grants_are_removed_and_service_lock_is_writable(self):
        with tempfile.TemporaryDirectory() as temporary:
            storage = Storage(Path(temporary) / "installation")
            for name in DIRECTORIES:
                storage.directory(name).mkdir(parents=True)
            secret = storage.directory("secrets") / "server.key"
            secret.write_text("non-secret-permission-fixture")
            lock = storage.directory("config") / "https.json.lock"
            lock.write_bytes(b"0")
            status = storage.directory("status") / "runtime.json"
            status.write_text("{}")
            hidden_run(["icacls.exe", str(secret), "/grant:r", "*S-1-1-0:F"])
            self.assertIn(";;;WD)", self.descriptor(secret))
            protect_storage(storage)
            self.assertNotIn(";;;WD)", self.descriptor(secret))
            self.assertNotIn(";;;BU)", self.descriptor(secret))
            self.assertIn(";;;BU)", self.descriptor(status))
            grant_service_storage(storage)
            sid = service_sid()
            self.assertIn(";;;" + sid + ")", self.descriptor(secret))
            lock_descriptor = self.descriptor(lock)
            self.assertIn(";;;" + sid + ")", lock_descriptor)
            self.assertIn("0x1301bf", lock_descriptor)
            self.assertNotIn(";;;BU)", self.descriptor(secret))


if __name__ == "__main__":
    unittest.main()
