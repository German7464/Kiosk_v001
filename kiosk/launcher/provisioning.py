import json
import shutil
from pathlib import Path

from kiosk.app import create_app
from kiosk.launcher.installation import binary_directory, require_administrator, service_state
from kiosk.launcher.storage import atomic_json, read_profile, safe_local_path, save_profile
from kiosk.launcher.windows import grant_service_storage, hidden_run, service_sid
from kiosk.transport.profile import load_profile
from kiosk.transport.profile_operations import ProfileLease
from kiosk.transport.runtime import ManagedHttps
from tools.certificate_activation import CertificateActivation, require_stopped, served_certificate, verify_generation


def provision_https(storage, generation, fingerprint, origin=None, listener=None):
    require_administrator()
    if service_state() not in {"absent", "stopped"}:
        raise RuntimeError("Stop the installed service before provisioning certificates.")
    device = read_profile(storage.profile)
    generation = safe_local_path(generation)
    if not generation.is_relative_to(storage.directory("secrets")):
        raise ValueError("Create the server key generation inside installed secrets storage.")
    details, verified = verify_generation(generation, device["device_id"], fingerprint)
    filename = storage.directory("config") / "https.json"

    def factory(profile):
        return ManagedHttps(profile, app_factory=lambda overrides: create_app({**storage.app_config(), **overrides}), temporary_directory=storage.directory("temp"))

    if filename.exists():
        if origin is not None or listener is not None:
            raise ValueError("Renewal does not change the existing origin or listener.")
        session = None
        with ProfileLease(filename):
            try:
                session = CertificateActivation(filename, generation, device["device_id"], fingerprint, runtime_factory=factory)
                session.start()
                if session.rolled_back:
                    raise RuntimeError("The certificate activation rolled back.")
            finally:
                if session is not None:
                    session.close()
    else:
        if not origin or not listener:
            raise ValueError("Initial HTTPS setup requires an explicit origin and IPv4 listener.")
        candidate = filename.with_name("https.prepared.json")
        if candidate.exists():
            raise ValueError("Review the interrupted HTTPS setup before retrying.")
        data = {"schema_version": 1, "public_origin": origin, "listen_host": listener,
                "caddy_executable": str(binary_directory() / "runtime/caddy/caddy.exe"),
                "certificate_file": str(generation / "server.pem"), "private_key_file": str(generation / "server.key"),
                "ca_file": str(generation / "authority.pem")}
        atomic_json(candidate, data)
        runtime = None
        try:
            profile = load_profile(candidate)
            require_stopped(profile)
            runtime = factory(profile)
            runtime.start()
            served_certificate(profile, verified["certificate_sha256"])
            result = runtime.close()
            runtime = None
            if result.get("proxy_forced") or not result.get("backend_stopped") or result.get("proxy_exit_code") != 0:
                raise RuntimeError("Initial HTTPS verification did not stop cleanly.")
            candidate.rename(filename)
        finally:
            if runtime is not None:
                runtime.close()
            candidate.unlink(missing_ok=True)
    public = storage.directory("status") / "authority.pem"
    shutil.copyfile(generation / "authority.pem", public)
    with ProfileLease(filename):
        pass
    grant_service_storage(storage)
    hidden_run(["icacls.exe", str(filename.with_name(filename.name + ".lock")), "/grant:r", f"*{service_sid()}:M"])
    save_profile(storage, {**device, "transport": "https"})
