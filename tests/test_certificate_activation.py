import hashlib
import json
import os
from pathlib import Path
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

from kiosk.transport.profile import load_profile
from kiosk.transport.profile_operations import ProfileLease, ProfileTransaction, atomic_profile_write, bounded_bytes, journal_path, recover_profile
from kiosk.transport.runtime import ManagedHttps, probe_https, run_https
from tools.certificate_activation import CertificateActivation, served_certificate, verify_generation
from tools.certificates import CertificateError, crypto, inspect_request, pem_bytes, private_directory
from tools.check_managed_https import fixture_factory
from tools.check_https_prototype import Client


@unittest.skipUnless(os.name == "nt", "Requires Windows profile locks")
class ProfileTransactionTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.filename = self.root / "https.json"
        self.original = b'{"generation":"old"}\r\n'
        self.candidate = b'{"generation":"new"}\n'
        self.filename.write_bytes(self.original)

    def test_commit_and_interrupted_recovery_preserve_exact_bytes(self):
        with ProfileLease(self.filename):
            transaction = ProfileTransaction(self.filename, self.candidate)
            transaction.prepare()
            self.assertEqual(self.filename.read_bytes(), self.original)
            atomic_profile_write(self.filename, self.candidate)
            self.assertTrue(recover_profile(self.filename))
            self.assertEqual(self.filename.read_bytes(), self.original)
            self.assertFalse(journal_path(self.filename).exists())
            transaction = ProfileTransaction(self.filename, self.candidate)
            transaction.prepare()
            transaction.commit()
        self.assertEqual(self.filename.read_bytes(), self.candidate)
        self.assertFalse(recover_profile(self.filename))

    def test_invalid_journal_and_owner_edit_fail_closed(self):
        pending = ProfileTransaction(self.filename, self.candidate)
        self.filename.write_bytes(b"owner edit before prepare")
        with self.assertRaises(ValueError):
            pending.prepare()
        self.assertFalse(journal_path(self.filename).exists())
        self.filename.write_bytes(self.original)
        transaction = ProfileTransaction(self.filename, self.candidate)
        transaction.prepare()
        changed = b'operator edit'
        self.filename.write_bytes(changed)
        with self.assertRaises(ValueError):
            transaction.rollback()
        self.assertEqual(self.filename.read_bytes(), changed)
        self.assertTrue(journal_path(self.filename).exists())
        journal_path(self.filename).write_bytes(b'{truncated')
        with self.assertRaises(ValueError):
            recover_profile(self.filename)
        self.assertEqual(self.filename.read_bytes(), changed)

    def test_lock_excludes_another_process_and_releases_after_owner_exit(self):
        source = "from kiosk.transport.profile_operations import ProfileLease; import sys;\ntry:\n lease=ProfileLease(sys.argv[1]).acquire()\nexcept OSError:\n raise SystemExit(3)\nlease.close()"
        with ProfileLease(self.filename):
            result = subprocess.run([sys.executable, "-c", source, str(self.filename)], capture_output=True, timeout=10)
            self.assertEqual(result.returncode, 3)
        result = subprocess.run([sys.executable, "-c", source, str(self.filename)], capture_output=True, timeout=10)
        self.assertEqual(result.returncode, 0)

    def test_process_crash_before_commit_restores_previous_profile_on_next_start(self):
        source = "from kiosk.transport.profile_operations import ProfileLease,ProfileTransaction,atomic_profile_write; import os,sys;\nlease=ProfileLease(sys.argv[1]).acquire(); transaction=ProfileTransaction(sys.argv[1],b'{\"generation\":\"new\"}'); transaction.prepare(); atomic_profile_write(transaction.filename,transaction.candidate); os._exit(27)"
        result = subprocess.run([sys.executable, "-c", source, str(self.filename)], capture_output=True, timeout=10)
        self.assertEqual(result.returncode, 27)
        with ProfileLease(self.filename):
            self.assertTrue(recover_profile(self.filename))
        self.assertEqual(self.filename.read_bytes(), self.original)

    def test_run_https_recovers_before_loading_profile(self):
        transaction = ProfileTransaction(self.filename, self.candidate)
        transaction.prepare()
        atomic_profile_write(self.filename, self.candidate)

        def inspect(filename):
            self.assertEqual(bounded_bytes(filename), self.original)
            raise ValueError("fixture stop before runtime")

        with patch("kiosk.transport.runtime.load_profile", side_effect=inspect):
            self.assertEqual(run_https(self.filename, auto_launch=False), 1)
        self.assertFalse(journal_path(self.filename).exists())


@unittest.skipUnless(os.name == "nt" and shutil.which("pwsh"), "Requires Windows and PowerShell")
class CertificateActivationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.installation = "fb764817-b32f-4844-8bc5-6b947e08d499"
        cls.secret = "temporary-activation-authority-password"
        cls.authority = crypto("initialize", installation=cls.installation, password=cls.secret)
        cls.fingerprint = hashlib.sha256(pem_bytes(cls.authority["authority"])).hexdigest()
        cls.generations = []
        for unused in range(2):
            request = crypto("request", installation=cls.installation, names=["127.0.0.1", "localhost"])
            signed = crypto("sign", installation=cls.installation, csr=request["csr"], password=cls.secret, **cls.authority)
            cls.generations.append((request, signed))

    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        caddy = Path(__file__).resolve().parent.parent / "logs/https-tools/caddy/caddy.exe"
        if not caddy.is_file():
            self.skipTest("Pinned developer Caddy is unavailable")
        self.caddy = caddy
        self.states = []
        for index, (request, signed) in enumerate(self.generations):
            state = self.root / str(index)
            private_directory(state)
            for name, value in {"server.key": request["key"], "request.pem": request["csr"], "server.pem": signed["certificate"], "authority.pem": signed["authority"]}.items():
                (state / name).write_text(value, encoding="utf-8")
            details = crypto("inspect", installation=self.installation, csr=request["csr"])
            (state / "request.json").write_text(json.dumps({"schema_version": 1, **details}), encoding="utf-8")
            self.states.append(state)
        with socket.socket() as listener:
            listener.bind(("127.0.0.1", 0))
            self.port = listener.getsockname()[1]
        self.filename = self.root / "https.json"
        self.filename.write_text(json.dumps({"schema_version": 1, "public_origin": f"https://127.0.0.1:{self.port}", "listen_host": "127.0.0.1",
            "caddy_executable": str(caddy), "certificate_file": str(self.states[0] / "server.pem"), "private_key_file": str(self.states[0] / "server.key"), "ca_file": str(self.states[0] / "authority.pem")}), encoding="utf-8")
        self.original = self.filename.read_bytes()
        self.factory = fixture_factory(self.root / "application", "disposable-activation-password")

    def runtime(self, profile):
        return ManagedHttps(profile, app_factory=self.factory)

    def session(self, **options):
        return CertificateActivation(self.filename, self.states[1], self.installation, self.fingerprint, runtime_factory=self.runtime, **options)

    def test_real_activation_persists_new_profile_and_preserves_old_generation(self):
        old = self.runtime(load_profile(self.filename)).start()
        client = Client(self.port, old.profile.trust_context(), time.monotonic() + 60, {"http_statuses": {}})
        try:
            client.form("/admin/login", {"username": "admin", "password": "disposable-activation-password"})
            client.request("/admin")
            before = client.request("/api/version")[0]
        finally:
            old.close()
        with ProfileLease(self.filename):
            session = self.session()
            try:
                session.start()
                self.assertTrue(session.committed)
                self.assertFalse(session.rolled_back)
                profile = load_profile(self.filename)
                self.assertEqual(profile.certificate_file, self.states[1] / "server.pem")
                self.assertTrue(probe_https(profile, profile.trust_context(), session.runtime.identity))
                self.assertTrue((self.states[0] / "server.key").is_file())
                client.request("/admin")
                self.assertEqual(client.request("/api/version")[0], before)
            finally:
                session.close()
        self.assertFalse(journal_path(self.filename).exists())

    def test_readiness_and_leaf_validation_survive_denied_default_source_connections(self):
        profile = load_profile(self.filename)
        original_connect = socket.create_connection
        denied = []

        def require_local_source(address, *args, **kwargs):
            if address == (profile.listen_host, profile.port) and kwargs.get("source_address") != (profile.listen_host, 0):
                denied.append(address)
                raise PermissionError("Default connection path denied")
            return original_connect(address, *args, **kwargs)

        fingerprint = hashlib.sha256(pem_bytes(profile.certificate_file.read_text())).hexdigest()
        with patch("socket.create_connection", side_effect=require_local_source):
            with self.assertRaises(PermissionError):
                socket.create_connection((profile.listen_host, profile.port), timeout=1)
            runtime = self.runtime(profile)
            try:
                runtime.start()
                served_certificate(profile, fingerprint)
                with self.assertRaisesRegex(CertificateError, "served certificate differs"):
                    served_certificate(profile, "0" * 64)
            finally:
                runtime.close()
        self.assertEqual(len(denied), 1)

    def test_failed_readiness_stops_candidate_and_restarts_original(self):
        with ProfileLease(self.filename):
            session = self.session(certificate_probe=lambda *args: (_ for _ in ()).throw(RuntimeError("injected readiness failure")))
            try:
                session.start()
                self.assertTrue(session.rolled_back)
                self.assertFalse(session.committed)
                self.assertEqual(self.filename.read_bytes(), self.original)
                self.assertTrue(probe_https(session.original, session.original.trust_context(), session.runtime.identity))
            finally:
                session.close()
        self.assertFalse(journal_path(self.filename).exists())

    def test_running_service_is_not_stopped_or_reconfigured(self):
        old = self.runtime(load_profile(self.filename)).start()
        try:
            with ProfileLease(self.filename):
                session = self.session()
                with self.assertRaises(OSError):
                    session.start()
                session.close()
            self.assertEqual(self.filename.read_bytes(), self.original)
            self.assertTrue(probe_https(old.profile, old.profile.trust_context(), old.identity))
        finally:
            old.close()

    def test_invalid_generation_is_rejected_before_journal_or_server(self):
        (self.states[1] / "server.key").write_text(self.generations[0][0]["key"], encoding="utf-8")
        with self.assertRaises(Exception):
            self.session()
        self.assertEqual(self.filename.read_bytes(), self.original)
        self.assertFalse(journal_path(self.filename).exists())
        (self.states[1] / "server.key").write_text(self.generations[1][0]["key"], encoding="utf-8")
        owner_edit = self.original + b" "

        def edit_during_validation(*arguments):
            result = verify_generation(*arguments)
            self.filename.write_bytes(owner_edit)
            return result

        with patch("tools.certificate_activation.verify_generation", side_effect=edit_during_validation), self.assertRaises(Exception):
            self.session()
        self.assertEqual(self.filename.read_bytes(), owner_edit)
        self.assertFalse(journal_path(self.filename).exists())

    def test_atomic_replacement_preserves_windows_dacl(self):
        script = self.root / "acl.ps1"
        script.write_text("param($Path) (Get-Acl -LiteralPath $Path).Sddl", encoding="utf-8")

        def dacl():
            result = subprocess.run([shutil.which("pwsh"), "-NoProfile", "-NonInteractive", "-File", str(script), str(self.filename)], capture_output=True, timeout=10)
            self.assertEqual(result.returncode, 0)
            return result.stdout

        before = dacl()
        with ProfileLease(self.filename):
            transaction = ProfileTransaction(self.filename, self.original + b" ")
            transaction.prepare()
            transaction.commit()
        self.assertEqual(dacl(), before)

    def test_commit_failure_after_profile_replace_restores_previous_service(self):
        with ProfileLease(self.filename):
            session = self.session()

            def fail_commit():
                atomic_profile_write(self.filename, session.transaction.candidate)
                raise OSError("injected failure before transaction commit point")

            session.transaction.commit = fail_commit
            try:
                session.start()
                self.assertTrue(session.rolled_back)
                self.assertEqual(self.filename.read_bytes(), self.original)
                self.assertTrue(probe_https(session.original, session.original.trust_context(), session.runtime.identity))
            finally:
                session.close()

    def test_failed_rollback_start_keeps_profile_restored_and_service_closed(self):
        with ProfileLease(self.filename):
            session = self.session(certificate_probe=lambda *args: (_ for _ in ()).throw(RuntimeError("candidate rejected")))
            candidate = self.runtime(session.candidate)
            session.runtime_factory = unittest.mock.Mock(side_effect=[candidate, RuntimeError("old startup rejected")])
            with self.assertRaises(RuntimeError):
                session.start()
            session.close()
            self.assertEqual(self.filename.read_bytes(), self.original)
            self.assertTrue(candidate.closed)
            with socket.socket() as listener:
                listener.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
                listener.bind(("127.0.0.1", self.port))

    def test_owner_crash_kills_candidate_and_recovers_previous_service(self):
        source = '''import os,sys
sys.path.insert(0,sys.argv[6])
from kiosk.transport.profile_operations import ProfileLease,atomic_profile_write
from kiosk.transport.runtime import ManagedHttps
from tools.certificate_activation import CertificateActivation
from tools.check_managed_https import fixture_factory
lease=ProfileLease(sys.argv[1]).acquire()
factory=fixture_factory(__import__('pathlib').Path(sys.argv[5]),'temporary-crash-fixture-password')
session=CertificateActivation(sys.argv[1],sys.argv[2],sys.argv[3],sys.argv[4],runtime_factory=lambda profile:ManagedHttps(profile,app_factory=factory))
def interrupted_commit():
    __import__('pathlib').Path(sys.argv[7]).write_text(session.runtime.temporary.name,encoding='utf-8')
    atomic_profile_write(session.filename,session.transaction.candidate)
    os._exit(29)
session.transaction.commit=interrupted_commit
session.start()
'''
        script = self.root / "crash-owner.py"
        script.write_text(source, encoding="utf-8")
        ownership = self.root / "crash-ownership.txt"
        result = subprocess.run([sys.executable, str(script), str(self.filename), str(self.states[1]), self.installation, self.fingerprint,
                                 str(self.root / "application"), str(Path(__file__).resolve().parent.parent), str(ownership)], capture_output=True, timeout=60)
        self.assertEqual(result.returncode, 29, "Crash fixture did not reach the injected commit boundary")
        owned_temporary = Path(ownership.read_text(encoding="utf-8")).resolve()
        self.assertEqual(owned_temporary.parent, Path(tempfile.gettempdir()).resolve())
        self.assertTrue(owned_temporary.name.startswith("kiosk-managed-https-"))
        configuration = json.loads((owned_temporary / "proxy.json").read_text(encoding="utf-8"))
        self.assertEqual(configuration["apps"]["tls"]["certificates"]["load_files"][0]["certificate"], str(self.states[1] / "server.pem"))
        self.addCleanup(shutil.rmtree, owned_temporary)
        self.assertNotEqual(self.filename.read_bytes(), self.original)
        with ProfileLease(self.filename):
            self.assertTrue(recover_profile(self.filename))
            self.assertEqual(self.filename.read_bytes(), self.original)
            old = self.runtime(load_profile(self.filename))
            try:
                old.start()
                self.assertTrue(probe_https(old.profile, old.profile.trust_context(), old.identity))
            finally:
                old.close()
