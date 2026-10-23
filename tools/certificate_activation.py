from dataclasses import replace
import hashlib
import json
from pathlib import Path
import socket
import ssl
import time

from kiosk.transport.profile import load_profile, unique_object
from kiosk.transport.profile_operations import ProfileLease, ProfileTransaction, bounded_bytes, recover_profile
from kiosk.transport.runtime import ManagedHttps
from tools.certificates import CertificateError, checked_path, crypto, inspect_request, read_text


def verify_generation(state, installation, fingerprint):
    state = checked_path(state)
    csr, details = inspect_request(state / "request.pem", installation)
    if json.loads(read_text(state / "request.json")) != {"schema_version": 1, **details}:
        raise CertificateError("Pending request manifest mismatch.")
    verified = crypto("verify", installation=installation, csr=csr, key=read_text(state / "server.key"),
                      certificate=read_text(state / "server.pem"), authority=read_text(state / "authority.pem"), fingerprint=fingerprint)
    return details, verified


def require_stopped(profile):
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
        listener.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        listener.bind((profile.listen_host, profile.port))


def served_certificate(profile, fingerprint):
    target = "127.0.0.1" if profile.listen_host == "0.0.0.0" else profile.listen_host
    with socket.create_connection((target, profile.port), timeout=3) as connection:
        with profile.trust_context().wrap_socket(connection, server_hostname=profile.hostname) as secured:
            if hashlib.sha256(secured.getpeercert(binary_form=True)).hexdigest() != fingerprint:
                raise CertificateError("The served certificate differs from the verified generation.")


def stop_runtime(runtime):
    if runtime is None:
        return
    result = runtime.close()
    if not result["backend_stopped"] or not result["temporary_removed"] or runtime.process is not None and runtime.process.poll() is None:
        raise RuntimeError("Owned HTTPS components were not confirmed stopped.")
    return result


class CertificateActivation:
    def __init__(self, filename, state, installation, fingerprint, runtime_factory=ManagedHttps, certificate_probe=served_certificate):
        self.filename = checked_path(filename)
        self.state = checked_path(state)
        snapshot = bounded_bytes(self.filename)
        self.original = load_profile(self.filename)
        if bounded_bytes(self.filename) != snapshot:
            raise CertificateError("HTTPS profile changed during activation preflight.")
        details, verified = verify_generation(self.state, installation, fingerprint)
        old_root = ssl.PEM_cert_to_DER_cert(read_text(self.original.ca_file))
        if hashlib.sha256(old_root).hexdigest() != fingerprint or self.original.hostname not in details["names"]:
            raise CertificateError("Activation requires the same authority and an approved current origin name.")
        self.candidate = replace(self.original, certificate_file=self.state / "server.pem",
                                 private_key_file=self.state / "server.key", ca_file=self.state / "authority.pem")
        original_paths = {self.original.certificate_file.resolve(), self.original.private_key_file.resolve(), self.original.ca_file.resolve()}
        if {self.candidate.certificate_file, self.candidate.private_key_file, self.candidate.ca_file} & original_paths:
            raise CertificateError("Activation requires a separate new certificate generation.")
        data = json.loads(snapshot, object_pairs_hook=unique_object)
        for name in ("certificate_file", "private_key_file", "ca_file", "caddy_executable"):
            data[name] = str(getattr(self.candidate, name))
        self.transaction = ProfileTransaction(self.filename, (json.dumps(data, indent=2) + "\n").encode("utf-8"))
        if self.transaction.original != snapshot:
            raise CertificateError("HTTPS profile changed during activation validation.")
        self.runtime_factory = runtime_factory
        self.certificate_probe = certificate_probe
        self.expected_certificate = verified["certificate_sha256"]
        self.runtime = None
        self.rolled_back = False
        self.committed = False

    def start(self):
        require_stopped(self.original)
        self.transaction.prepare()
        try:
            self.runtime = self.runtime_factory(self.candidate)
            self.runtime.start()
            self.certificate_probe(self.candidate, self.expected_certificate)
            self.transaction.commit()
            self.committed = True
        except BaseException as error:
            stop_runtime(self.runtime)
            self.transaction.rollback()
            if not isinstance(error, Exception):
                raise
            self.runtime = self.runtime_factory(self.original)
            self.runtime.start()
            self.rolled_back = True
        return self

    def close(self):
        result = stop_runtime(self.runtime)
        if result is not None and (result["proxy_forced"] or result.get("proxy_exit_code", 0) != 0):
            raise RuntimeError("HTTPS shutdown required forced cleanup or returned an error.")


def supervise(runtime):
    while True:
        runtime.check_running()
        time.sleep(0.1)


def run_activation(filename, state, installation, fingerprint):
    session = None
    code = 1
    try:
        with ProfileLease(filename):
            try:
                if recover_profile(filename):
                    print("Recovered the previous HTTPS profile before activation.", flush=True)
                session = CertificateActivation(filename, state, installation, fingerprint)
                session.start()
                code = 1 if session.rolled_back else 0
                print(json.dumps({"status": "activation_rolled_back" if session.rolled_back else "certificate_activated",
                                  "https_ready": True, "manual_stop": "Ctrl+C"}), flush=True)
                for route in ("/kiosk", "/tv", "/admin/login"):
                    print(session.runtime.profile.public_origin + route, flush=True)
                supervise(session.runtime)
            finally:
                if session is not None:
                    session.close()
    except KeyboardInterrupt:
        pass
    except Exception as error:
        print(f"Certificate activation or HTTPS service failed ({type(error).__name__}); no HTTP fallback. Inspect the profile and transaction before retrying.", flush=True)
        code = 1
    return code
