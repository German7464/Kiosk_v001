import base64
from contextlib import redirect_stderr, redirect_stdout
import hashlib
import io
import json
import os
from pathlib import Path
import shutil
import socket
import ssl
import subprocess
import tempfile
import threading
import unittest
from unittest.mock import patch

from tools import certificates


INSTALLATION = "7e43702a-b5f9-4928-a85b-486897ca7f46"
PASSWORD = "temporary-test-authority-password"


@unittest.skipUnless(os.name == "nt" and shutil.which("pwsh"), "Requires Windows and PowerShell 7")
class CertificateWorkflowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.request = certificates.crypto("request", installation=INSTALLATION, names=["127.0.0.1", "localhost"])
        cls.authority = certificates.crypto("initialize", installation=INSTALLATION, password=PASSWORD)
        cls.signed = certificates.crypto("sign", installation=INSTALLATION, csr=cls.request["csr"], password=PASSWORD, **cls.authority)
        cls.fingerprint = hashlib.sha256(certificates.pem_bytes(cls.authority["authority"])).hexdigest()

    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)

    def run_cli(self, arguments):
        output = io.StringIO()
        error = io.StringIO()
        with redirect_stdout(output), redirect_stderr(error):
            result = certificates.main(arguments)
        self.assertNotIn(PASSWORD, output.getvalue() + error.getvalue())
        self.assertNotIn("PRIVATE KEY", output.getvalue() + error.getvalue())
        return result, output.getvalue()

    def verify(self, **changes):
        values = dict(installation=INSTALLATION, csr=self.request["csr"], key=self.request["key"],
                      certificate=self.signed["certificate"], authority=self.signed["authority"], fingerprint=self.fingerprint)
        values.update(changes)
        return certificates.crypto("verify", **values)

    def test_encrypted_authority_wrong_password_and_installation_are_rejected(self):
        self.assertIn("BEGIN ENCRYPTED PRIVATE KEY", self.authority["encrypted_key"])
        for changes in ({"password": "wrong-test-password"}, {"installation": "00000000-0000-0000-0000-000000000001"}):
            values = dict(installation=INSTALLATION, csr=self.request["csr"], password=PASSWORD, **self.authority)
            values.update(changes)
            with self.assertRaises(certificates.CertificateError):
                certificates.crypto("sign", **values)

    def test_csr_tampering_multiple_pem_and_foreign_installation_rejected(self):
        encoded = self.request["csr"].split("-----")[2]
        raw = bytearray(base64.b64decode(encoded))
        raw[-1] ^= 1
        tampered = "-----BEGIN CERTIFICATE REQUEST-----\n" + base64.b64encode(raw).decode() + "\n-----END CERTIFICATE REQUEST-----"
        for csr in (tampered, self.request["csr"] * 2, self.request["csr"] + "trailing", "x" * 65537):
            with self.subTest(case=csr[:20]), self.assertRaises(certificates.CertificateError):
                certificates.crypto("inspect", installation=INSTALLATION, csr=csr)
        with self.assertRaises(certificates.CertificateError):
            certificates.crypto("inspect", installation="00000000-0000-0000-0000-000000000001", csr=self.request["csr"])

    def test_unsafe_csr_extensions_and_weak_keys_are_rejected(self):
        source = r'''param($Mode)
$key = [Security.Cryptography.RSA]::Create($(if ($Mode -eq 'weak') { 2048 } else { 3072 }))
try {
    $request = [Security.Cryptography.X509Certificates.CertificateRequest]::new('CN=Kiosk server 7e43702a-b5f9-4928-a85b-486897ca7f46', $key, [Security.Cryptography.HashAlgorithmName]::SHA256, [Security.Cryptography.RSASignaturePadding]::Pkcs1)
    $names = [Security.Cryptography.X509Certificates.SubjectAlternativeNameBuilder]::new()
    if ($Mode -eq 'uri') { $names.AddUri([uri]'https://evil.invalid') } else { $names.AddDnsName('localhost') }
    $request.CertificateExtensions.Add($names.Build())
    if ($Mode -eq 'ca') { $request.CertificateExtensions.Add([Security.Cryptography.X509Certificates.X509BasicConstraintsExtension]::new($true, $false, 0, $true)) }
    $request.CreateSigningRequestPem()
} finally { $key.Dispose() }
'''
        script = self.root / "unsafe.ps1"
        script.write_text(source, encoding="utf-8")
        for mode in ("weak", "uri", "ca"):
            result = subprocess.run([shutil.which("pwsh"), "-NoProfile", "-NonInteractive", "-File", str(script), mode], capture_output=True, text=True, encoding="utf-8", timeout=20)
            self.assertEqual(result.returncode, 0, result.stderr)
            with self.subTest(mode=mode), self.assertRaises(certificates.CertificateError):
                certificates.crypto("inspect", installation=INSTALLATION, csr=result.stdout)

    def test_certificate_key_authority_and_fingerprint_must_match(self):
        verified = self.verify()
        self.assertEqual(verified["authority_sha256"], self.fingerprint)
        foreign = certificates.crypto("request", installation=INSTALLATION, names=["127.0.0.1", "localhost"])
        for changes in ({"fingerprint": "0" * 64}, {"key": foreign["key"]}, {"csr": foreign["csr"]}):
            with self.subTest(fields=list(changes)), self.assertRaises(certificates.CertificateError):
                self.verify(**changes)
        other = certificates.crypto("initialize", installation=INSTALLATION, password=PASSWORD)
        with self.assertRaises(certificates.CertificateError):
            self.verify(authority=other["authority"], fingerprint=hashlib.sha256(certificates.pem_bytes(other["authority"])).hexdigest())

    def test_two_command_roundtrip_transfer_allowlists_and_idempotent_receive(self):
        state = self.root / "server"
        export = self.root / "to-admin"
        result, output = self.run_cli(["request", "--installation", INSTALLATION, "--state", str(state), "--export", str(export), "--name", "localhost", "--name", "127.0.0.1"])
        self.assertEqual(result, 0)
        details = json.loads(output)
        self.assertEqual({path.name for path in export.iterdir()}, {"request.pem"})
        authority = self.root / "authority"
        output_dir = self.root / "to-server"
        with patch("tools.certificates.sys.stdin.isatty", return_value=True), patch("builtins.input", return_value="SIGN " + details["request_sha256"]), patch("tools.certificates.getpass.getpass", return_value=PASSWORD):
            result, _ = self.run_cli(["sign", "--installation", INSTALLATION, "--authority", str(authority), "--csr", str(export / "request.pem"), "--output", str(output_dir), "--initialize-authority"])
        self.assertEqual(result, 0)
        self.assertEqual({path.name for path in output_dir.iterdir()}, {"server.pem", "authority.pem"})
        self.assertIn("ENCRYPTED PRIVATE KEY", (authority / "authority.key").read_text())
        fingerprint = hashlib.sha256(certificates.pem_bytes((output_dir / "authority.pem").read_text())).hexdigest()
        receive = ["request", "--installation", INSTALLATION, "--state", str(state), "--certificate", str(output_dir / "server.pem"), "--ca", str(output_dir / "authority.pem"), "--fingerprint", fingerprint]
        bad_receive = receive[:-1] + ["0" * 64]
        self.assertEqual(self.run_cli(bad_receive)[0], 1)
        self.assertFalse((state / "verified.json").exists())
        self.assertFalse((state / "server.pem").exists())
        self.assertEqual(self.run_cli(receive)[0], 0)
        self.assertEqual(self.run_cli(receive)[0], 0)
        self.assertTrue((state / "verified.json").is_file())
        self.assertFalse(json.loads(self.run_cli(receive)[1])["active_profile_changed"])
        acl_script = "param($Path) $acl=Get-Acl -LiteralPath $Path; if (-not $acl.AreAccessRulesProtected) { exit 1 }; foreach ($rule in $acl.Access) { if ($rule.IdentityReference.Translate([Security.Principal.SecurityIdentifier]).Value -in @('S-1-1-0','S-1-5-32-545')) { exit 2 } }"
        acl_file = self.root / "acl.ps1"
        acl_file.write_text(acl_script, encoding="utf-8")
        for private in (state, authority):
            check = subprocess.run([shutil.which("pwsh"), "-NoProfile", "-NonInteractive", "-File", str(acl_file), str(private)], capture_output=True, timeout=10)
            self.assertEqual(check.returncode, 0, check.stderr.decode(errors="replace"))

    def test_cancel_noninteractive_missing_authority_and_overwrite_preserve_files(self):
        transfer = self.root / "transfer"
        transfer.mkdir()
        export = transfer / "request.pem"
        export.write_text(self.request["csr"], encoding="utf-8")
        output = self.root / "output"
        arguments = ["sign", "--installation", INSTALLATION, "--authority", str(self.root / "missing"), "--csr", str(export), "--output", str(output)]
        self.assertEqual(self.run_cli(arguments)[0], 1)
        self.assertFalse(output.exists())
        with patch("tools.certificates.sys.stdin.isatty", return_value=False):
            self.assertEqual(self.run_cli(arguments + ["--initialize-authority"])[0], 1)
        with patch("tools.certificates.sys.stdin.isatty", return_value=True), patch("builtins.input", return_value="cancel"):
            self.assertEqual(self.run_cli(arguments + ["--initialize-authority"])[0], 1)
        self.assertFalse((self.root / "missing").exists())
        output.mkdir()
        marker = output / "marker"
        marker.write_bytes(b"preserve")
        self.assertEqual(self.run_cli(arguments)[0], 1)
        self.assertEqual(marker.read_bytes(), b"preserve")

    def test_material_works_in_real_offline_tls_and_renewal_keeps_root(self):
        (self.root / "server.pem").write_text(self.signed["certificate"], encoding="utf-8")
        (self.root / "server.key").write_text(self.request["key"], encoding="utf-8")
        (self.root / "authority.pem").write_text(self.signed["authority"], encoding="utf-8")
        server_context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        server_context.load_cert_chain(self.root / "server.pem", self.root / "server.key")
        errors = []
        with socket.socket() as listener:
            listener.bind(("127.0.0.1", 0))
            listener.listen()
            listener.settimeout(5)

            def respond():
                try:
                    with listener.accept()[0] as raw, server_context.wrap_socket(raw, server_side=True) as stream:
                        stream.sendall(b"verified")
                except Exception as error:
                    errors.append(type(error).__name__)

            thread = threading.Thread(target=respond)
            thread.start()
            context = ssl.create_default_context(cafile=str(self.root / "authority.pem"))
            with socket.create_connection(listener.getsockname(), timeout=3) as raw, context.wrap_socket(raw, server_hostname="localhost") as stream:
                self.assertEqual(stream.recv(8), b"verified")
            thread.join(timeout=6)
            self.assertFalse(thread.is_alive())
            self.assertFalse(errors)
        fresh = certificates.crypto("request", installation=INSTALLATION, names=["127.0.0.1", "localhost"])
        renewed = certificates.crypto("sign", installation=INSTALLATION, csr=fresh["csr"], password=PASSWORD, **self.authority)
        self.assertEqual(renewed["authority"], self.signed["authority"])
        self.assertNotEqual(renewed["certificate"], self.signed["certificate"])
        self.verify(csr=fresh["csr"], key=fresh["key"], certificate=renewed["certificate"])

    def test_expired_or_changed_names_are_not_accepted(self):
        source = r'''
$ErrorActionPreference = 'Stop'
$data = [Console]::In.ReadToEnd() | ConvertFrom-Json
$key = [Security.Cryptography.RSA]::Create()
$key.ImportFromEncryptedPem($data.encrypted_key, $data.password)
$public = [Security.Cryptography.X509Certificates.X509Certificate2]::CreateFromPem($data.authority)
$authority = [Security.Cryptography.X509Certificates.RSACertificateExtensions]::CopyWithPrivateKey($public, $key)
try {
    $csr = [Security.Cryptography.X509Certificates.CertificateRequest]::LoadSigningRequestPem($data.csr, [Security.Cryptography.HashAlgorithmName]::SHA256, [Security.Cryptography.X509Certificates.CertificateRequestLoadOptions]::UnsafeLoadCertificateExtensions, [Security.Cryptography.RSASignaturePadding]::Pkcs1)
    $request = [Security.Cryptography.X509Certificates.CertificateRequest]::new($csr.SubjectName, $csr.PublicKey, [Security.Cryptography.HashAlgorithmName]::SHA256, [Security.Cryptography.RSASignaturePadding]::Pkcs1)
    $request.CertificateExtensions.Add([Security.Cryptography.X509Certificates.X509BasicConstraintsExtension]::new($false, $false, 0, $true))
    $request.CertificateExtensions.Add([Security.Cryptography.X509Certificates.X509KeyUsageExtension]::new([Security.Cryptography.X509Certificates.X509KeyUsageFlags]::DigitalSignature -bor [Security.Cryptography.X509Certificates.X509KeyUsageFlags]::KeyEncipherment, $true))
    $purposes = [Security.Cryptography.OidCollection]::new()
    $purposes.Add([Security.Cryptography.Oid]::new('1.3.6.1.5.5.7.3.1')) | Out-Null
    $request.CertificateExtensions.Add([Security.Cryptography.X509Certificates.X509EnhancedKeyUsageExtension]::new($purposes, $true))
    if ($data.mode -eq 'names') {
        $names = [Security.Cryptography.X509Certificates.SubjectAlternativeNameBuilder]::new()
        $names.AddDnsName('wrong.invalid')
        $request.CertificateExtensions.Add($names.Build())
    } else { $request.CertificateExtensions.Add($csr.CertificateExtensions[0]) }
    $now = [DateTimeOffset]::UtcNow
    $start = $now.AddMinutes(-2)
    $end = $(if ($data.mode -eq 'expired') { $now.AddMinutes(-1) } else { $now.AddDays(1) })
    $serial = [Security.Cryptography.RandomNumberGenerator]::GetBytes(16)
    $certificate = $request.Create($authority, $start, $end, $serial)
    try { $certificate.ExportCertificatePem() } finally { $certificate.Dispose() }
} finally { $authority.Dispose(); $public.Dispose(); $key.Dispose() }
'''
        script = self.root / "invalid-leaf.ps1"
        script.write_text(source, encoding="utf-8")
        for mode in ("expired", "names"):
            result = subprocess.run([shutil.which("pwsh"), "-NoProfile", "-NonInteractive", "-File", str(script)],
                                    input=json.dumps({**self.authority, "password": PASSWORD, "csr": self.request["csr"], "mode": mode}),
                                    capture_output=True, text=True, encoding="utf-8", timeout=20)
            self.assertEqual(result.returncode, 0, "Invalid-leaf fixture failed")
            with self.subTest(mode=mode), self.assertRaises(certificates.CertificateError):
                self.verify(certificate=result.stdout)


class CertificateInputTests(unittest.TestCase):
    def test_activation_is_only_available_after_returned_certificate_validation(self):
        with tempfile.TemporaryDirectory() as directory, redirect_stderr(io.StringIO()), patch("tools.certificates.create_request") as create:
            result = certificates.main(["request", "--installation", INSTALLATION, "--state", directory, "--export", directory + "-export", "--name", "localhost", "--activate-profile", "https.json"])
            self.assertEqual(result, 1)
            create.assert_not_called()

    def test_activation_result_is_returned_by_the_request_workflow(self):
        with patch("tools.certificates.receive_certificate") as receive, patch("tools.certificate_activation.run_activation", return_value=7) as activate:
            result = certificates.main(["request", "--installation", INSTALLATION, "--state", "generation", "--certificate", "returned.pem", "--ca", "ca.pem", "--fingerprint", "0" * 64, "--activate-profile", "https.json"])
            self.assertEqual(result, 7)
            receive.assert_called_once()
            activate.assert_called_once_with("https.json", "generation", INSTALLATION, "0" * 64)

    def test_invalid_names_and_directory_overlap_are_rejected(self):
        for names in ([], ["*.example"], ["::1"], ["0.0.0.0"], ["224.1.1.1"], ["bad_name"], ["LOCALHOST", "localhost"]):
            with self.subTest(names=names), self.assertRaises(certificates.CertificateError):
                certificates.normalized_names(names)
        with self.assertRaises(certificates.CertificateError):
            certificates.disjoint(Path("private"), Path("private/transfer"))
