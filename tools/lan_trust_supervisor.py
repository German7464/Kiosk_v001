"""Isolated Windows pilot supervisor. Owns backend/TLS, bounded renewal and recovery.

No Caddy administration socket is exposed. Immutable generation configurations are
activated by an owned-process restart, then strict TLS identity verification. The
durable committed pointer changes only after verification; an interrupted pending
activation restarts the previous committed generation on the next supervisor run.
"""
import argparse
import ctypes as ct
from ctypes import wintypes as wt
import json
import os
from pathlib import Path
import socket
import ssl
import subprocess
import sys
import time
from urllib.parse import urlsplit

from kiosk.core.update_owner import Owner
from kiosk.display.native_crypto import protect
from kiosk.trust.crypto import leaf_spki_sha256
from kiosk.trust.lifecycle import OnlineIssuer
from kiosk.trust.state import LifecycleState
from tools.lan_trust_admin import _atomic_replace, _load_server, _caddyfile


def own_process_tree():
    """Kernel-enforced cleanup if the supervisor crashes or its task is stopped.

    Assign self before creating children, so descendants inherit the job without
    a spawn/assign race. Keep its non-inherited handle until process exit; closing
    the last handle kills descendants. Windows10 supports nested scheduler jobs.
    """
    class Basic(ct.Structure):
        _fields_ = [('process_time', ct.c_int64), ('job_time', ct.c_int64),
                    ('flags', wt.DWORD), ('minimum', ct.c_size_t), ('maximum', ct.c_size_t),
                    ('active', wt.DWORD), ('affinity', ct.c_size_t),
                    ('priority', wt.DWORD), ('scheduling', wt.DWORD)]
    class IO(ct.Structure):
        _fields_ = [(name, ct.c_uint64) for name in
                    ('read_ops','write_ops','other_ops','read_bytes','write_bytes','other_bytes')]
    class Extended(ct.Structure):
        _fields_ = [('basic', Basic), ('io', IO), ('process_memory', ct.c_size_t),
                    ('job_memory', ct.c_size_t), ('peak_process', ct.c_size_t), ('peak_job', ct.c_size_t)]
    kernel = ct.WinDLL('kernel32', use_last_error=True)
    kernel.CreateJobObjectW.argtypes = [ct.c_void_p, wt.LPCWSTR]
    kernel.CreateJobObjectW.restype = wt.HANDLE
    kernel.GetCurrentProcess.restype = wt.HANDLE
    kernel.SetInformationJobObject.argtypes = [wt.HANDLE, ct.c_int, ct.c_void_p, wt.DWORD]
    kernel.AssignProcessToJobObject.argtypes = [wt.HANDLE, wt.HANDLE]
    job = kernel.CreateJobObjectW(None, None)
    if not job:
        raise ct.WinError(ct.get_last_error())
    limits = Extended()
    limits.basic.flags = 0x2000  # JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
    if (not kernel.SetInformationJobObject(job, 9, ct.byref(limits), ct.sizeof(limits)) or
            not kernel.AssignProcessToJobObject(job, kernel.GetCurrentProcess())):
        raise ct.WinError(ct.get_last_error())
    return job  # Deliberately held, not inherited and not closed before self exits.


def write(path, value):
    _atomic_replace(path, json.dumps(value, indent=2))


def verify(root, expected, timeout=15):
    public = json.loads((root / 'public/manifest.json').read_text())
    target = urlsplit('https://' + public['address'] + ':' + str(public['port']))
    context = ssl.create_default_context(cafile=str(root / 'public/root-ca.pem'))
    context.minimum_version = ssl.TLSVersion.TLSv1_2
    deadline = time.monotonic() + timeout
    while True:
        try:
            with socket.create_connection((target.hostname, target.port), timeout=2) as raw:
                with context.wrap_socket(raw, server_hostname=target.hostname) as tls:
                    actual = leaf_spki_sha256(ssl.DER_cert_to_PEM_cert(tls.getpeercert(True)))
                    if actual != expected:
                        raise ValueError('serving_identity_mismatch')
                    return actual
        except (OSError, ValueError):
            if time.monotonic() >= deadline:
                raise RuntimeError('strict_tls_activation_failed') from None
            time.sleep(.2)


class Supervisor:
    def __init__(self, root, caddy, backend_port):
        self.root, self.caddy, self.backend_port = root, caddy, backend_port
        self.child = None
        self.log = (root / 'supervisor-caddy.log').open('ab')
        self.state = LifecycleState(root / 'state')
        self.pointer = root / 'server/committed.json'
        self.pending = root / 'server/activation.json'

    def stop_tls(self):
        if self.child and self.child.poll() is None:
            self.child.terminate()
            try:
                self.child.wait(timeout=10)
            except subprocess.TimeoutExpired:
                self.child.kill()
                self.child.wait(timeout=5)

    def materialize(self, result):
        folder = self.root / 'server/generations' / str(result['generation'])
        folder.mkdir(parents=True, exist_ok=False)
        (folder / 'cert.pem').write_text(result['chain_pem'])
        (folder / 'key.pem').write_text(result['leaf_key_pem'])
        manifest = json.loads((self.root / 'public/manifest.json').read_text())
        origin = 'https://' + manifest['address'] + ':' + str(manifest['port'])
        config = _caddyfile(origin, manifest['address'], self.backend_port,
                            (folder / 'cert.pem').as_posix(), (folder / 'key.pem').as_posix(),
                            self.root / 'caddy-storage')
        (folder / 'Caddyfile').write_text(config)
        return {'generation': result['generation'], 'tls_spki_sha256': result['tls_spki_sha256'],
                'not_after': result['not_after'], 'config': str(folder / 'Caddyfile')}

    def start_tls(self, record):
        self.stop_tls()
        self.child = subprocess.Popen([str(self.caddy), 'run', '--config', record['config'],
                                      '--adapter', 'caddyfile'], stdout=self.log, stderr=self.log,
                                     stdin=subprocess.DEVNULL, creationflags=subprocess.CREATE_NO_WINDOW)
        verify(self.root, record['tls_spki_sha256'])

    def activate(self, candidate, previous=None):
        write(self.pending, {'state': 'pending', 'candidate': candidate, 'previous': previous})
        try:
            self.start_tls(candidate)
            self.state.activate(candidate['generation'])
            write(self.pointer, candidate)
            write(self.pending, {'state': 'committed', 'candidate': candidate, 'previous': previous})
            return candidate
        except Exception as error:
            restored = False
            if previous:
                try:
                    self.start_tls(previous)
                    restored = True
                except Exception:
                    pass
            write(self.pending, {'state': 'failed_restored' if restored else 'recovery_required',
                                 'error': type(error).__name__, 'candidate': candidate, 'previous': previous})
            raise

    def renew(self, previous, days):
        delegation, signature, spki, _ = _load_server(self.root, None)
        password = protect((self.root / 'server/online-unlock.dpapi').read_bytes(), decrypt=True).decode()
        issuer = OnlineIssuer(self.state, spki, delegation, signature)
        result = issuer.renew_tls_leaf((self.root / 'server/intermediate.pem').read_text(),
                   (self.root / 'server/intermediate-key.pem').read_text(), validity_days=days,
                   now=int(time.time()), intermediate_key_password=password)
        return self.activate(self.materialize(result), previous)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--provision-online', action='store_true')
    parser.add_argument('--backend', action='store_true')
    parser.add_argument('--root', type=Path, required=True)
    parser.add_argument('--caddy', type=Path)
    parser.add_argument('--backend-port', type=int, default=18765)
    parser.add_argument('--renew-before-seconds', type=int, default=2*86400)
    parser.add_argument('--retry-seconds', type=int, default=60)
    parser.add_argument('--days', type=int, default=7)
    parser.add_argument('--credential-seconds', type=int, default=604800)
    args = parser.parse_args()
    if args.retry_seconds < 1 or args.renew_before_seconds < 0:
        parser.error('invalid retry/renewal bounds')
    root = args.root.absolute()
    if (root / 'state/rebuild-incomplete.json').exists():
        raise RuntimeError('interrupted_rebuild_refused: preserve this tree offline and restore a verified backup to a fresh root')
    if args.provision_online:
        from kiosk.trust.crypto import load_private, key_id
        password = sys.stdin.readline().strip()
        key = load_private((root / 'server/intermediate-key.pem').read_text(), password)
        delegation, signature, spki, manifest = _load_server(root, None)
        if key_id(key) != delegation.issuer_key_id:
            raise ValueError('issuer_mismatch')
        (root / 'server/online-unlock.dpapi').write_bytes(protect(password.encode()))
        print('online_key_provisioned')
        return
    if args.backend:
        import kiosk.delivery.state as delivery_state
        from tools.run_device_delivery_lab import lab_app, refresh
        from waitress import serve
        delivery_state.CREDENTIAL_SECONDS = args.credential_seconds
        app = lab_app(root)
        refresh(app, root)
        serve(app, host='127.0.0.1', port=args.backend_port, threads=4,
              trusted_proxy='127.0.0.1', trusted_proxy_count=1,
              trusted_proxy_headers={'x-forwarded-for','x-forwarded-proto','x-forwarded-host'})
        return
    if not args.caddy:
        parser.error('--caddy is required for supervision')
    owner = Owner(root / 'supervisor.owner')
    process_tree_job = own_process_tree()
    supervisor = Supervisor(root, args.caddy.absolute(), args.backend_port)
    backend_log = (root / 'supervisor-backend.log').open('ab')
    backend_command = ([sys.executable] if getattr(sys, 'frozen', False) else
                       [sys.executable, '-m', 'tools.lan_trust_supervisor'])
    backend = subprocess.Popen(backend_command + ['--backend', '--root', str(root),
                   '--backend-port', str(args.backend_port), '--credential-seconds', str(args.credential_seconds)], stdout=backend_log, stderr=backend_log,
                   stdin=subprocess.DEVNULL, creationflags=subprocess.CREATE_NO_WINDOW)
    status = root / 'supervisor-status.json'
    try:
        if supervisor.pointer.exists():
            active = json.loads(supervisor.pointer.read_text())
            supervisor.start_tls(active)
            if supervisor.pending.exists():
                pending = json.loads(supervisor.pending.read_text())
                if pending.get('state') in ('pending', 'recovery_required'):
                    write(root / 'server/startup-recovery.json', {'state':'previous_verified',
                          'active':active, 'interrupted':pending, 'at':int(time.time())})
        else:
            record = json.loads((root / 'public/manifest.json').read_text())['serving']
            record.update(chain_pem=(root / 'server/tls-cert.pem').read_text(),
                          leaf_key_pem=(root / 'server/tls-key.pem').read_text())
            active = supervisor.activate(supervisor.materialize(record))
        failures, next_attempt = 0, 0
        prepared_at, prepared_status = 0, 'not_checked'
        while not (root / 'stop.request').exists():
            if backend.poll() is not None or supervisor.child.poll() is not None:
                raise RuntimeError('supervised_process_exited')
            now = int(time.time())
            if now >= prepared_at:
                from kiosk.trust.prepared import advance
                try:
                    prepared_status = advance(root, now)
                except Exception:
                    # Keep the previously committed signed authority; never mint
                    # a replacement or broaden it after invalid prepared input.
                    prepared_status = 'prepared_authority_refused'
                prepared_at = now + 60
            request = root / 'server/renew.request'
            due = active['not_after'] - now <= args.renew_before_seconds or request.exists()
            if due and now >= next_attempt:
                request.unlink(missing_ok=True)
                try:
                    active = supervisor.renew(active, args.days)
                    failures = 0
                except Exception as error:
                    if supervisor.pending.exists() and json.loads(supervisor.pending.read_text()).get('state') == 'recovery_required':
                        raise RuntimeError('activation_recovery_required') from error
                    failures += 1
                    next_attempt = now + min(3600, args.retry_seconds * 2**min(failures-1, 6))
                    write(status, {'state': 'renewal_failed', 'active': active, 'failures': failures,
                                   'next_attempt': next_attempt, 'error': type(error).__name__, 'at': now})
                    time.sleep(1)
                    continue
            write(status, {'state': 'ready' if not failures else 'renewal_retry_wait', 'active': active,
                           'prepared_trust': prepared_status,
                           'failures': failures, 'next_attempt': next_attempt, 'at': now,
                           'pid': os.getpid(), 'backend_pid': backend.pid, 'caddy_pid': supervisor.child.pid})
            time.sleep(1)
    except Exception as error:
        write(status, {'state': 'recovery_required', 'error': type(error).__name__, 'at': int(time.time())})
        raise
    finally:
        supervisor.stop_tls()
        backend.terminate()
        backend.wait(timeout=10)
        backend_log.close()
        supervisor.log.close()
        owner.close()


if __name__ == '__main__':
    main()
