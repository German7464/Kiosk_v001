import hashlib
import json
import shutil
import socket
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from kiosk.app import create_app
from kiosk.core.credentials import save_admin_password
from kiosk.launcher.provisioning import provision_https
from kiosk.launcher.storage import DIRECTORIES, Storage, new_profile, read_profile, save_profile
from kiosk.transport.profile import load_profile
from kiosk.transport.runtime import ManagedHttps, probe_https
from tools.certificates import crypto, pem_bytes


class LauncherProvisioningTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.installation = "b1740fe6-aa62-4446-a12b-d56f480bbf4c"
        cls.password = "temporary-installed-authority-password"
        authority = crypto("initialize", installation=cls.installation, password=cls.password)
        cls.fingerprint = hashlib.sha256(pem_bytes(authority["authority"])).hexdigest()
        cls.generations = []
        for unused in range(2):
            request = crypto("request", installation=cls.installation, names=["127.0.0.1"])
            signed = crypto("sign", installation=cls.installation, csr=request["csr"], password=cls.password, **authority)
            details = crypto("inspect", installation=cls.installation, csr=request["csr"])
            cls.generations.append((request, signed, details))

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.storage = Storage(self.root / "installed")
        for name in DIRECTORIES:
            self.storage.directory(name).mkdir(parents=True)
        profile = {**new_profile("Provisioned fixture"), "device_id": self.installation}
        save_profile(self.storage, profile)
        self.binary = self.root / "binaries"
        caddy = self.binary / "runtime/caddy/caddy.exe"
        caddy.parent.mkdir(parents=True)
        shutil.copy2(Path(__file__).resolve().parent.parent / "logs/https-tools/caddy/caddy.exe", caddy)
        self.states = []
        for index, (request, signed, details) in enumerate(self.generations):
            state = self.storage.directory("secrets") / str(index)
            state.mkdir()
            files = {"server.key": request["key"], "request.pem": request["csr"], "server.pem": signed["certificate"],
                     "authority.pem": signed["authority"], "request.json": json.dumps({"schema_version": 1, **details})}
            for name, value in files.items():
                (state / name).write_text(value, encoding="utf-8")
            self.states.append(state)
        with socket.socket() as listener:
            listener.bind(("127.0.0.1", 0))
            self.port = listener.getsockname()[1]
        self.addCleanup(patch.stopall)
        patch("kiosk.launcher.provisioning.require_administrator").start()
        patch("kiosk.launcher.provisioning.service_state", return_value="stopped").start()
        patch("kiosk.launcher.provisioning.binary_directory", return_value=self.binary).start()
        patch("kiosk.launcher.provisioning.grant_service_storage").start()
        patch("kiosk.launcher.provisioning.hidden_run").start()
        patch("kiosk.launcher.provisioning.service_sid", return_value="S-1-5-80-1-2-3-4-5").start()

    def provision_first(self):
        provision_https(self.storage, self.states[0], self.fingerprint, f"https://127.0.0.1:{self.port}", "127.0.0.1")

    def test_real_initial_provisioning_and_same_ca_renewal_keep_installed_database(self):
        app = create_app(self.storage.app_config())
        save_admin_password(app, "temporary-installed-admin-password", setup=True)
        version = app.test_client().get("/api/version").json
        key = (self.storage.directory("secrets") / "session.key").read_bytes()
        self.provision_first()
        self.assertEqual(read_profile(self.storage.profile)["transport"], "https")
        self.assertEqual(read_profile(self.storage.profile)["device_id"], self.installation)
        provision_https(self.storage, self.states[1], self.fingerprint)
        profile = load_profile(self.storage.directory("config") / "https.json")
        self.assertEqual(profile.certificate_file, self.states[1] / "server.pem")
        self.assertTrue((self.states[0] / "server.key").exists())
        runtime = ManagedHttps(profile, app_factory=lambda overrides: create_app({**self.storage.app_config(), **overrides}), temporary_directory=self.storage.directory("temp"))
        try:
            runtime.start()
            self.assertTrue(probe_https(profile, profile.trust_context(), runtime.identity))
        finally:
            result = runtime.close()
        self.assertFalse(result["proxy_forced"])
        self.assertTrue(result["backend_stopped"])
        self.assertTrue(result["temporary_removed"])
        self.assertEqual(app.test_client().get("/api/version").json, version)
        self.assertEqual((self.storage.directory("secrets") / "session.key").read_bytes(), key)
        self.assertEqual(list(self.storage.directory("temp").iterdir()), [])

    def test_invalid_return_and_busy_service_do_not_change_device(self):
        original = self.storage.profile.read_bytes()
        with self.assertRaises(Exception):
            provision_https(self.storage, self.states[0], "0" * 64, f"https://127.0.0.1:{self.port}", "127.0.0.1")
        self.assertEqual(self.storage.profile.read_bytes(), original)
        self.assertFalse((self.storage.directory("config") / "https.json").exists())
        with patch("kiosk.launcher.provisioning.service_state", return_value="running"), self.assertRaises(RuntimeError):
            self.provision_first()
        self.assertEqual(self.storage.profile.read_bytes(), original)


if __name__ == "__main__":
    unittest.main()
