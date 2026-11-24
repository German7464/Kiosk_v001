"""Manual offline Windows update workflow: one entry point, four modes.

    python -m tools.build_windows_update check
    python -m tools.build_windows_update build --product server --full --pwsh-directory D --caddy-directory C
    python -m tools.build_windows_update build --product client --full --shell-candidate S
    python -m tools.build_windows_update deploy --target pc4 --package DIR
    python -m tools.build_windows_update deploy --target pc5 --package DIR --trust-key
    python -m tools.build_windows_update journey --target pc4

``check`` runs the fast affected checks (compile + update unit tests + helper
compile + ISCC) without building or deploying. ``build`` produces a versioned,
signed, complete offline update package (Inno Setup installer + signed manifest)
tied to the source/dependency identities, and refuses to overwrite a previous
package silently. ``deploy`` transfers the directory package to the target VM,
installs the trust key only when explicitly requested (never silently replacing an
existing key), invokes the real product update and verifies the final outcome.
``journey`` verifies the installed health and returns a meaningful exit code.
Build and check never deploy implicitly.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

from kiosk.core.update import DATA_SCHEMA_VERSION, verify_package
from kiosk.core.update_crypto import load_private_key, public_key_id
from kiosk.version import VERSION

ISCC = r"C:\KioskTools\InnoSetup7\ISCC.exe"
PROJECT = Path(__file__).resolve().parents[1]
DEFAULT_KEYS = Path(os.environ.get("KIOSK_UPDATE_KEYS", r"C:\KioskUpdateKeys"))
PRIVATE_NAME = "update-signing-key.pem"
PUBLIC_NAME = "update-verification-key.pem"
SERVER_APPID = "D5E5A9F0-8E2C-4A1B-9C3D-123456789ABC"
CLIENT_APPID = "A7F3B1C2-4D5E-4F6A-8B9C-0D1E2F3A4B5C"
REMOTE_BASE = "C:/KioskLab-20261112"
CSC = Path(os.environ.get("WINDIR", "C:/Windows")) / "Microsoft.NET/Framework64/v4.0.30319/csc.exe"

TARGETS = {
    "pc4": {
        "ssh": "WorkPc4@192.168.1.124",
        "product": "server",
        "binary": r"C:\Program Files\Kiosk",
        "maintenance": r"C:\Program Files\Kiosk\KioskMaintenance.exe",
        "runtime": r"C:\ProgramData\Kiosk\status\runtime.json",
        "trust_key": r"C:\ProgramData\Kiosk\config\update-verification.pem",
    },
    "pc5": {
        "ssh": "WorkPc5@192.168.1.125",
        "product": "client",
        "client_exe": r"C:\Users\Work\AppData\Local\Programs\KioskConnectApp\dist\KioskConnect\KioskConnect.exe",
        "app_root": r"C:\Users\Work\AppData\Local\Programs\KioskConnectApp",
        "version_marker": r"C:\Users\Work\AppData\Local\Programs\KioskConnectApp\version.json",
        "data_root": r"C:\Users\Work\AppData\Local\KioskConnect",
        "trust_key": r"C:\Users\Work\AppData\Local\KioskConnect\update-verification.pem",
    },
}


def _digest(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def _server_iss(payload, version):
    payload = str(Path(payload).resolve()).replace("\\", "/")
    appid = "{{" + SERVER_APPID + "}}"
    return f"""[Setup]
AppId={appid}
AppName=Kiosk
AppVersion={version}
AppPublisher=Kiosk
DefaultDirName={{autopf}}\\Kiosk
DisableProgramGroupPage=yes
DisableDirPage=yes
DisableReadyPage=yes
DisableWelcomePage=yes
Uninstallable=no
PrivilegesRequired=admin
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
Compression=lzma2/ultra64
SolidCompression=yes
SetupLogging=no

[Files]
Source: "{payload}\\*"; DestDir: "{{app}}"; Flags: ignoreversion recursesubdirs createallsubdirs
"""


def _client_iss(payload, version):
    payload = str(Path(payload).resolve()).replace("\\", "/")
    appid = "{{" + CLIENT_APPID + "}}"
    return f"""[Setup]
AppId={appid}
AppName=KioskConnect
AppVersion={version}
AppPublisher=Kiosk
DefaultDirName={{localappdata}}\\Programs\\KioskConnectApp
DisableProgramGroupPage=yes
DisableDirPage=yes
DisableReadyPage=yes
DisableWelcomePage=yes
Uninstallable=no
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
Compression=lzma2/ultra64
SolidCompression=yes
SetupLogging=no

[Files]
Source: "{payload}\\dist\\KioskConnect\\*"; DestDir: "{{app}}\\dist\\KioskConnect"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "{payload}\\shell\\*"; DestDir: "{{app}}\\shell"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "{payload}\\version.json"; DestDir: "{{app}}"; Flags: ignoreversion
Source: "{payload}\\KioskUpdateHelper.exe"; DestDir: "{{app}}"; Flags: ignoreversion
"""


def _run(*command, **kwargs):
    return subprocess.run([*command], check=True, **kwargs)


def _payload_version(product, payload):
    marker = payload / ("package.json" if product == "server" else "version.json")
    if not marker.is_file():
        raise ValueError("The payload has no version marker: " + str(marker))
    try:
        return json.loads(marker.read_text(encoding="utf-8"))["version"]
    except (ValueError, KeyError, OSError) as error:
        raise ValueError("The payload version marker is invalid.") from error


def compile_installer(product, payload, version, work_dir):
    work_dir.mkdir(parents=True, exist_ok=True)
    script = work_dir / ("server.iss" if product == "server" else "client.iss")
    script.write_text((_server_iss if product == "server" else _client_iss)(payload, version),
                      encoding="utf-8")
    output_name = "kiosk-server-setup" if product == "server" else "kiosk-connect-setup"
    _run(ISCC, f"/O{work_dir}", f"/F{output_name}", str(script), cwd=PROJECT)
    installer = work_dir / (output_name + ".exe")
    if not installer.is_file():
        raise RuntimeError("Inno Setup did not produce an installer.")
    return installer


def build_package(product, payload, version, key_dir, out_dir, force=False):
    payload = Path(payload).resolve()
    if not payload.is_dir():
        raise ValueError("The payload directory is unavailable.")
    if version is None:
        version = _payload_version(product, payload)
    private_pem = (key_dir / PRIVATE_NAME).read_text(encoding="ascii")
    public_pem = (key_dir / PUBLIC_NAME).read_text(encoding="ascii")
    key_id = public_key_id(load_private_key(private_pem).public_key())

    package = out_dir / f"update-{product}-{version}"
    if package.exists() and not force:
        raise RuntimeError("A package already exists at %s; preserve it before retrying." % package)
    work = out_dir / ".build" / (product + '-' + version + '-' + str(time.time_ns()))
    work.mkdir(parents=True, exist_ok=True)
    installer = compile_installer(product, payload, version, work)

    package = out_dir / f"update-{product}-{version}"
    if package.exists() and not force:
        raise RuntimeError("A package already exists at %s; pass --force to overwrite unique evidence." % package)
    if package.exists():
        shutil.rmtree(package)
    package.mkdir(parents=True)
    shutil.move(str(installer), str(package / installer.name))
    marker = payload / ("package.json" if product == "server" else "version.json")
    sources = [*PROJECT.joinpath('kiosk').rglob('*.py'), *PROJECT.joinpath('tools').glob('*.py'),
               PROJECT / 'tools/update_helper.cs', PROJECT / 'requirements.txt',
               PROJECT / 'KioskLauncher.spec', PROJECT / 'launcher.py',
               PROJECT / 'launcher_service.py', PROJECT / 'launcher_maintenance.py']
    manifest = {
        "schema_version": 1, "product": "kiosk-server" if product == "server" else "kiosk-connect",
        "platform": "win-x64", "version": version, "min_compatible": "2.0.0",
        "data_schema": DATA_SCHEMA_VERSION, "key_id": key_id,
        "signature_algorithm": "ed25519",
        "built_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "build": {
            "payload_marker_sha256": _digest(marker),
            "iscc_sha256": _digest(ISCC),
            "python": sys.version,
            "tool": "tools/build_windows_update.py",
            "sources": {p.relative_to(PROJECT).as_posix(): _digest(p) for p in sorted(sources)},
            "helper_sha256": _digest(payload / 'KioskUpdateHelper.exe'),
        },
        "files": {installer.name: _digest(package / installer.name)},
    }
    manifest_bytes = json.dumps(manifest, indent=2).encode("utf-8")
    (package / "manifest.json").write_bytes(manifest_bytes)
    from kiosk.core.update_crypto import sign

    (package / "manifest.json.sig").write_bytes(sign(private_pem, manifest_bytes))
    return package


def _read_package(package, public_pem, product=None):
    package = Path(package).resolve()
    manifest = verify_package(package, public_pem, product=product) if product else _manifest_only(package)
    return manifest


def _manifest_only(package):
    package = Path(package).resolve()
    manifest_path = package / "manifest.json"
    if not manifest_path.is_file():
        raise ValueError("The package directory has no manifest.json.")
    return json.loads(manifest_path.read_text(encoding="utf-8"))


def check(_args):
    checks = []
    _run(sys.executable, "-m", "compileall", "-q", "kiosk/core/update.py",
         "kiosk/core/update_crypto.py", "kiosk/launcher/updater.py",
         "kiosk/display/updater.py", "tools/build_windows_update.py",
         "tools/update_signing.py", "launcher_maintenance.py", cwd=PROJECT)
    checks.append("compileall")
    _run(sys.executable, "-m", "unittest", "tests.test_update", "tests.test_update_transaction", "-q", cwd=PROJECT)
    checks.append("tests.test_update + tests.test_update_transaction")
    if not Path(ISCC).is_file():
        raise RuntimeError("Inno Setup 7 is not available at " + ISCC)
    checks.append("iscc")
    if not CSC.is_file():
        raise RuntimeError("Windows .NET Framework compiler required for the update helper.")
    import tempfile

    helper_out = Path(tempfile.mkdtemp(prefix="kiosk-helper-check-")) / "KioskUpdateHelper.exe"
    _run(str(CSC), "/nologo", "/target:exe", "/platform:x64", "/out:" + str(helper_out),
         str(PROJECT / "tools/update_helper.cs"))
    shutil.rmtree(helper_out.parent, ignore_errors=True)
    checks.append("update_helper")
    print(json.dumps({"result": "check_ok", "checks": checks, "version": VERSION,
                      "data_schema": DATA_SCHEMA_VERSION}))
    return 0


def build(args):
    if args.full:
        if args.product == "server":
            if not args.pwsh_directory or not args.caddy_directory:
                raise ValueError("--full server build needs --pwsh-directory and --caddy-directory.")
            _run(sys.executable, "-m", "tools.build_launcher", "--pwsh-directory", args.pwsh_directory,
                 "--caddy-directory", args.caddy_directory, cwd=PROJECT)
        else:
            if not args.shell_candidate:
                raise ValueError("--full client build needs --shell-candidate.")
            destination = PROJECT / f"dist/KioskConnect-build-{args.version or VERSION}"
            if destination.exists():
                raise RuntimeError("A client build already exists at %s; remove it or pass --version." % destination)
            _run(sys.executable, "tools/build_windows_delivery.py", "--destination", str(destination),
                 "--shell-candidate", args.shell_candidate, "--connect-ui", cwd=PROJECT)

    if args.payload:
        payload = Path(args.payload).resolve()
    elif args.product == "server":
        payload = PROJECT / "dist/KioskLauncher"
    else:
        payload = destination if args.full else None

    if payload is None:
        raise ValueError("A client build needs --full or --payload; no silent stale selection.")

    target_version = args.version or _payload_version(args.product, payload)
    if _payload_version(args.product, payload) != target_version:
        raise ValueError("The payload version does not match --version (stale output refused).")

    key_dir = Path(args.key_dir)
    package = build_package(args.product, payload, target_version, key_dir, Path(args.out), force=args.force)
    print(json.dumps({"result": "built", "package": str(package),
                      "product": args.product, "version": target_version,
                      "data_schema": DATA_SCHEMA_VERSION}))
    return 0


def ssh(target, command, timeout=180):
    result = subprocess.run(["ssh", "-o", "StrictHostKeyChecking=yes", "-o", "BatchMode=yes",
                             "-o", "ConnectTimeout=20", target["ssh"], command],
                            capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=timeout)
    if result.returncode:
        raise RuntimeError("SSH failed: " + result.stderr[-400:])
    return result.stdout


def scp_file(local, target, remote, timeout=600):
    subprocess.run(["scp", "-o", "StrictHostKeyChecking=yes", "-o", "BatchMode=yes",
                    "-o", "ConnectTimeout=20", local, f"{target['ssh']}:{remote}"],
                   check=True, timeout=timeout)


def scp_dir(local, target, remote_parent, timeout=900):
    subprocess.run(["scp", "-r", "-o", "StrictHostKeyChecking=yes", "-o", "BatchMode=yes",
                    "-o", "ConnectTimeout=20", local, f"{target['ssh']}:{remote_parent}"],
                   check=True, timeout=timeout)


def _manifest_product(target):
    return "kiosk-server" if target["product"] == "server" else "kiosk-connect"


def _ps(target, script, timeout=180):
    """Run a PowerShell script on the target over SSH (script on stdin).

    Passing the script on stdin avoids the remote shell re-expanding ``$variables``
    inside a double-quoted ``-Command`` argument.
    """
    result = subprocess.run(["ssh", "-o", "StrictHostKeyChecking=yes", "-o", "BatchMode=yes",
                             "-o", "ConnectTimeout=20", target["ssh"],
                             "powershell -NoProfile -NonInteractive -Command -"],
                            input=script, capture_output=True, text=True, encoding="utf-8",
                            errors="replace", timeout=timeout)
    if result.returncode:
        raise RuntimeError("SSH failed: " + result.stderr[-400:])
    return result.stdout


def _install_trust(target, key_dir, force):
    public_key = Path(key_dir) / PUBLIC_NAME
    if not public_key.is_file():
        raise ValueError("The public verification key is missing at " + str(public_key))
    trust = target["trust_key"]
    exists = _ps(target, f"if (Test-Path '{trust}') {{'True'}} else {{'False'}}")
    if exists.strip() == "True" and not force:
        raise RuntimeError("A trust key is already installed; refusing to replace it. Pass --force-trust to replace explicitly.")
    scp_file(str(public_key), target, REMOTE_BASE + "/update-verification-key.pem")
    _ps(target, f"New-Item -ItemType Directory -Force -Path (Split-Path '{trust}') | Out-Null; "
                f"Copy-Item '{REMOTE_BASE}\\update-verification-key.pem' '{trust}' -Force; "
                f"(Get-Item '{trust}').Length")
    print(json.dumps({"trust_key": "installed", "target": target["ssh"], "force": force}))


def _upgrade(target, remote_pkg):
    """Keep the SSH job alive until activation terminates, not merely staging.

    Windows OpenSSH can kill detached descendants when the session closes.
    Use a protected server script (per-user client script) and -File: a native
    executable inside PowerShell -Command - can also consume the script stdin.
    """
    import tempfile
    import uuid

    def quote(value):
        return "'" + str(value).replace("'", "''") + "'"

    if target["product"] == "server":
        invoke = f"& {quote(target['maintenance'])} upgrade {quote(remote_pkg)}\nif ($LASTEXITCODE -ne 0) {{exit $LASTEXITCODE}}"
        status = f"$raw=(& {quote(target['maintenance'])} upgrade-status) -join \"`n\""
        script_root = r"C:\ProgramData\Kiosk\updates"
    else:
        exe = quote(target['client_exe'])
        report = quote(target['data_root'] + r'\upgrade-command.json')
        invoke = (f"$p=Start-Process -WindowStyle Hidden -FilePath {exe} -ArgumentList '--upgrade',{quote(remote_pkg)} -Wait -PassThru\n"
                  f"if ($p.ExitCode -ne 0) {{throw 'Client update command failed'}}\n"
                  f"$initial=Get-Content {report} -Raw | ConvertFrom-Json\nif ($initial.error) {{throw 'Client update command reported failure'}}")
        status = (f"Start-Process -WindowStyle Hidden -FilePath {exe} -ArgumentList '--upgrade-status' -Wait | Out-Null\n"
                  f"$raw=Get-Content {report} -Raw")
        script_root = target['data_root']
    remote_script = script_root + r'\invoke-update-' + uuid.uuid4().hex + '.ps1'
    script = ("$ErrorActionPreference='Stop'\n" + invoke + "\n$deadline=(Get-Date).AddSeconds(180)\n"
              "do {\nStart-Sleep -Seconds 1\n" + status + "\n$status=$raw | ConvertFrom-Json\n"
              "if ($status.state -in @('committed','rolled_back','failed','recovery-required')) {\n"
              "Write-Output $raw\nif ($status.state -ne 'committed') {exit 1}\nexit 0\n}\n"
              "} while ((Get-Date) -lt $deadline)\nthrow 'Activation pending timeout; recovery material retained'\n")
    with tempfile.TemporaryDirectory(prefix='kiosk-update-invoke-') as temporary:
        local = Path(temporary) / 'invoke.ps1'
        local.write_text(script, encoding='utf-8-sig')
        scp_file(str(local), target, remote_script.replace('\\', '/'))
        # The remote script is retained as transaction evidence, without secrets.
        return ssh(target, 'powershell -NoProfile -NonInteractive -File ' +
                   subprocess.list2cmdline([remote_script]), timeout=240)


def _check_server_health(target):
    out = _ps(target, f"$r = Get-Content '{target['runtime']}' -Raw -ErrorAction SilentlyContinue | ConvertFrom-Json; "
                      "[ordered]@{state=$r.state; version=$r.version; device_id=$r.device_id; error=$r.error; "
                      "service=(Get-Service KioskService -ErrorAction SilentlyContinue).Status.ToString(); "
                      "old=(Test-Path 'C:\\Program Files\\Kiosk.old'); "
                      "backup=(Test-Path 'C:\\ProgramData\\Kiosk.backup')} | ConvertTo-Json -Compress")
    try:
        return json.loads(out.strip().splitlines()[-1])
    except (ValueError, IndexError):
        return {"state": "unreachable"}


def _check_client_health(target):
    out = _ps(target, f"$v = (Get-Content '{target['version_marker']}' -Raw -ErrorAction SilentlyContinue | ConvertFrom-Json).version; "
                      f"$d=Get-Content '{target['data_root']}\\profile\\display-status.json' -Raw -ErrorAction SilentlyContinue | ConvertFrom-Json; "
                      "$engine=Get-Process -Id $d.process_id -ErrorAction SilentlyContinue; "
                      f"$control=Get-Process KioskConnect -ErrorAction SilentlyContinue | Where-Object {{$_.Path -eq '{target['client_exe']}'}}; "
                      f"$receipt=Get-Content ('{target['data_root']}\\state\\last-ready-'+$d.mode+'.json') -Raw -ErrorAction SilentlyContinue | ConvertFrom-Json; "
                      f"$nativePath='{target['app_root']}\\shell\\KioskOfflineDisplay.exe'; "
                      f"$displayFile=Get-Item '{target['data_root']}\\profile\\display-status.json' -ErrorAction SilentlyContinue; "
                      "[ordered]@{version=$v; native=$d; control_running=[bool]$control; "
                      "native_process_matches=[bool]($engine -and $engine.Path -eq $nativePath -and $displayFile.LastWriteTimeUtc -ge $engine.StartTime.ToUniversalTime()); "
                      "receipt_matches=[bool]($receipt -and $receipt.package_sha256 -eq $d.package_sha256); "
                      "staging=(Test-Path 'C:\\Users\\Work\\AppData\\Local\\Programs\\KioskConnectApp.staging'); "
                      "old=(Test-Path 'C:\\Users\\Work\\AppData\\Local\\Programs\\KioskConnectApp.old'); "
                      "tasks=((Get-ScheduledTask -TaskName 'KioskConnectUpdateSwap-*' -ErrorAction SilentlyContinue | Measure-Object).Count)} | ConvertTo-Json -Compress")
    try:
        return json.loads(out.strip().splitlines()[-1])
    except (ValueError, IndexError):
        return {"state": "unreachable"}


def _server_healthy(health):
    return (health.get("state") == "running" and health.get("error") in (None, "null", "")
            and health.get("service") == "Running")


def _client_healthy(health):
    native = health.get('native') or {}
    return (health.get('version') is not None and health.get('control_running') is True
            and health.get('native_process_matches') is True and health.get('receipt_matches') is True
            and native.get('renderer_ready') is True and native.get('navigation_success') is True
            and native.get('startup_failed') is False and bool(native.get('session_id'))
            and not health.get('staging') and not health.get('tasks'))


def _status(target):
    """Return the installed updater's own status (finalizes a finished transaction)."""
    if target["product"] == "server":
        out = _ps(target, f"& '{target['maintenance']}' upgrade-status")
    else:
        out = _ps(target, f"$p = Start-Process -FilePath '{target['client_exe']}' -ArgumentList '--upgrade-status' -Wait -PassThru | Out-Null; "
                          f"Get-Content '{target['data_root']}\\upgrade-command.json' -Raw -ErrorAction SilentlyContinue")
    try:
        return json.loads(out.strip().splitlines()[-1])
    except (ValueError, IndexError):
        return {"state": "unreachable"}


def _wait_and_verify(target, version, timeout=180):
    deadline = time.monotonic() + timeout
    last = None
    while time.monotonic() < deadline:
        status = _status(target)
        last = status
        state = status.get("state")
        if state == "committed":
            if (status.get("version") or status.get("to_version")) != version:
                return {"state": "failed", "version": status.get("version"),
                        "note": "Committed status does not identify the requested package version."}
            return {"state": "committed", "version": status.get("version") or status.get("to_version"),
                    "from_version": status.get("from_version")}
        if state in ("rolled_back", "failed", "recovery-required"):
            return {"state": state, "version": status.get("version"),
                    "note": status.get("note") or status.get("helper_result")}
        time.sleep(5)
    return {"state": "pending_timeout", "last": last,
            "note": "the update did not reach a verified outcome within %ds" % timeout}


def deploy(args):
    target = TARGETS[args.target]
    package = Path(args.package).resolve()
    public_pem = (Path(args.key_dir) / PUBLIC_NAME).read_text(encoding="ascii")
    manifest = verify_package(package, public_pem, product=_manifest_product(target))
    version = manifest["version"]

    remote_pkg = REMOTE_BASE + "/" + package.name
    _ps(target, f"New-Item -ItemType Directory -Force -Path '{remote_pkg}' | Out-Null")

    if args.trust_key:
        _install_trust(target, args.key_dir, force=args.force_trust)

    scp_dir(str(package), target, REMOTE_BASE + "/")
    upgrade_out = _upgrade(target, remote_pkg)
    print(upgrade_out.strip())
    result = _wait_and_verify(target, version)
    print(json.dumps(result))
    return 0 if result.get("state") == "committed" else 1


def journey(args):
    target = TARGETS[args.target]
    status = _status(target)  # finalizes a finished transaction if one is pending
    if target["product"] == "server":
        health = _check_server_health(target)
        print(json.dumps({"status": status, "health": health}))
        return 0 if _server_healthy(health) and status.get("state") in ("idle", "committed") else 1
    health = _check_client_health(target)
    print(json.dumps({"status": status, "health": health}))
    ok = _client_healthy(health) and status.get('state') in ('idle', 'committed')
    print(json.dumps({"application_ready": ok,
                      "note": "Current native display receipt/process check; authenticated admin operations are a separate UI acceptance."}))
    return 0 if ok else 1


def main():
    parser = argparse.ArgumentParser(allow_abbrev=False, description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("check")
    build_p = sub.add_parser("build")
    build_p.add_argument("--product", choices=("server", "client"), required=True)
    build_p.add_argument("--full", action="store_true")
    build_p.add_argument("--payload", type=Path)
    build_p.add_argument("--version")
    build_p.add_argument("--pwsh-directory")
    build_p.add_argument("--caddy-directory")
    build_p.add_argument("--shell-candidate")
    build_p.add_argument("--key-dir", type=Path, default=DEFAULT_KEYS)
    build_p.add_argument("--out", default=str(PROJECT / "logs/windows-offline-updater-20261112/packages"))
    build_p.add_argument("--force", action="store_true")
    deploy_p = sub.add_parser("deploy")
    deploy_p.add_argument("--target", choices=("pc4", "pc5"), required=True)
    deploy_p.add_argument("--package", required=True)
    deploy_p.add_argument("--key-dir", type=Path, default=DEFAULT_KEYS)
    deploy_p.add_argument("--trust-key", action="store_true")
    deploy_p.add_argument("--force-trust", action="store_true")
    journey_p = sub.add_parser("journey")
    journey_p.add_argument("--target", choices=("pc4", "pc5"), required=True)
    args = parser.parse_args()
    if args.command == "check":
        return check(args)
    if args.command == "build":
        return build(args)
    if args.command == "deploy":
        return deploy(args)
    if args.command == "journey":
        return journey(args)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
