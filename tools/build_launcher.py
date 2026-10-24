import argparse
import hashlib
import importlib.metadata
import json
import shutil
import subprocess
import sys
from pathlib import Path

from kiosk.launcher.storage import atomic_json, copy_tree, safe_local_path
from kiosk.transport.profile import CADDY_SHA256, CADDY_VERSION


def digest(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def main():
    parser = argparse.ArgumentParser(allow_abbrev=False)
    parser.add_argument("--pwsh-directory", required=True)
    parser.add_argument("--caddy-directory", required=True)
    args = parser.parse_args()
    import PyInstaller

    for name in ("run.exe", "runw.exe"):
        if not (Path(PyInstaller.__file__).parent / "bootloader" / PyInstaller.PLATFORM / name).is_file():
            raise RuntimeError("A required pinned PyInstaller bootloader is missing. Review the installation and system protection before building.")
    project = Path(__file__).resolve().parent.parent
    powershell = safe_local_path(args.pwsh_directory)
    caddy = safe_local_path(args.caddy_directory)
    if digest(caddy / "caddy.exe") != CADDY_SHA256 or not (caddy / "LICENSE").is_file():
        raise ValueError("The pinned Caddy binary and license are required.")
    for name in ("pwsh.exe", "LICENSE.txt", "ThirdPartyNotices.txt"):
        if not (powershell / name).is_file():
            raise ValueError("The portable PowerShell distribution is incomplete.")
    script = "$p = $input | ConvertFrom-Json; $s = Get-AuthenticodeSignature -LiteralPath $p.executable; @{version=$PSVersionTable.PSVersion.ToString(); framework=[System.Runtime.InteropServices.RuntimeInformation]::FrameworkDescription; signature=$s.Status.ToString(); signer=$s.SignerCertificate.Subject} | ConvertTo-Json -Compress"
    result = subprocess.run([str(powershell / "pwsh.exe"), "-NoProfile", "-NonInteractive", "-Command", script],
                            input=json.dumps({"executable": str(powershell / "pwsh.exe")}), text=True, encoding="utf-8", capture_output=True, check=True, timeout=30)
    info = json.loads(result.stdout)
    if info["version"] != "7.6.6" or not info["framework"].startswith(".NET 10.") or info["signature"] != "Valid" or "Microsoft Corporation" not in info["signer"]:
        raise ValueError("PowerShell must be the verified Microsoft-signed 7.6.6/.NET 10 portable runtime.")
    target = project / "dist/KioskLauncher"
    if target.exists():
        raise ValueError("Preserve the existing build or remove its exact directory explicitly before rebuilding.")
    subprocess.run([sys.executable, "-m", "PyInstaller", "--noconfirm", "KioskLauncher.spec"], cwd=project, check=True)
    copy_tree(powershell, target / "runtime/powershell")
    (target / "runtime/caddy").mkdir(parents=True)
    for name in ("caddy.exe", "LICENSE"):
        shutil.copy2(caddy / name, target / "runtime/caddy" / name)
    licenses = target / "licenses"
    licenses.mkdir()
    shutil.copy2(project / "requirements.txt", licenses / "requirements.txt")
    for distribution in importlib.metadata.distributions():
        for file in distribution.files or []:
            if ".dist-info/" in str(file).replace("\\", "/") and any(word in file.name.lower() for word in ("license", "copying", "notice")):
                destination = licenses / distribution.metadata["Name"] / file.name
                destination.parent.mkdir(exist_ok=True)
                shutil.copy2(distribution.locate_file(file), destination)
    files = {path.relative_to(target).as_posix(): digest(path) for path in sorted(target.rglob("*")) if path.is_file()}
    atomic_json(target / "package.json", {"schema_version": 1, "powershell": info, "caddy_version": CADDY_VERSION, "files": files})
    print(json.dumps({"package": str(target), "files": len(files), "bytes": sum(path.stat().st_size for path in target.rglob("*") if path.is_file())}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
