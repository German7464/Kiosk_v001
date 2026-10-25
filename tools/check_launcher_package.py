import argparse
import ctypes
import hashlib
import json
import os
import shutil
import subprocess
import tempfile
import time
from pathlib import Path

from kiosk.launcher.installation import service_state, verify_package
from kiosk.launcher.storage import DIRECTORIES, Storage, new_profile, save_profile


def storage_hashes(root):
    return {path.relative_to(root).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
            for path in root.rglob("*") if path.is_file() and not path.is_symlink()}


def check_package(package, evidence):
    if os.name != "nt" or not ctypes.windll.shell32.IsUserAnAdmin():
        raise RuntimeError("Run this isolated Windows check from an administrative terminal.")
    if service_state() != "absent":
        raise RuntimeError("This check requires no local KioskService registration.")
    package = package.resolve(strict=True)
    manifest = verify_package(package)
    executable = package / "KioskMaintenance.exe"
    if not executable.is_file():
        raise ValueError("The complete maintenance package is required.")
    evidence.mkdir(parents=True, exist_ok=True)
    report_path = evidence / "package-removal.json"
    if report_path.exists():
        raise FileExistsError("Choose a fresh evidence directory.")
    report = {"host": os.environ.get("COMPUTERNAME"), "package": str(package),
              "package_manifest_sha256": hashlib.sha256((package / "package.json").read_bytes()).hexdigest(),
              "cases": [], "passed": False, "scm_registered": False}
    try:
        with tempfile.TemporaryDirectory(prefix="kiosk-package-check-") as temporary:
            root = Path(temporary).resolve(strict=True)
            installed = root / "ProgramFiles" / "Kiosk"
            installed.parent.mkdir()
            shutil.copytree(package, installed)
            storage = Storage(root / "ProgramData" / "Kiosk")
            for name in DIRECTORIES:
                storage.directory(name).mkdir(parents=True)
            profile = new_profile("Disposable removal acceptance")
            save_profile(storage, profile)
            (storage.directory("data") / "keep.bin").write_bytes(b"disposable content")
            witness = root / "outside-data.bin"
            witness.write_bytes(b"must survive every removal attempt")
            original_witness = witness.read_bytes()
            original_data = storage_hashes(storage.root)
            environment = {name.upper(): value for name, value in os.environ.items()}
            environment.update(PROGRAMFILES=str(root / "ProgramFiles"), PROGRAMDATA=str(root / "ProgramData"),
                               PROGRAMW6432=str(root / "ProgramFiles"))
            environment["PROGRAMFILES(X86)"] = str(root / "ProgramFiles")
            environment_check = subprocess.run(
                [str(package / "runtime/powershell/pwsh.exe"), "-NoProfile", "-Command",
                 "[ordered]@{files=$env:ProgramFiles;data=$env:ProgramData}|ConvertTo-Json -Compress"],
                env=environment, capture_output=True, timeout=30, check=True)
            assert json.loads(environment_check.stdout) == {
                "files": str(root / "ProgramFiles"), "data": str(root / "ProgramData")}

            def run_case(name, arguments, expected, message=None, preserves=True):
                if service_state() != "absent":
                    raise RuntimeError("A service appeared; refuse any maintenance action.")
                started = time.monotonic()
                result = subprocess.run([str(executable), "uninstall", *arguments],
                                        env=environment, cwd=root, capture_output=True, timeout=90)
                stdout = result.stdout.decode("utf-8", errors="replace")
                stderr = result.stderr.decode("utf-8", errors="replace")
                case = {"name": name, "exit_code": result.returncode,
                        "seconds": round(time.monotonic() - started, 3),
                        "stdout": stdout, "stderr": stderr}
                report["cases"].append(case)
                assert result.returncode == expected, case
                if message:
                    assert message in stdout + stderr, case
                assert witness.read_bytes() == original_witness
                assert service_state() == "absent"
                if preserves:
                    assert storage_hashes(storage.root) == original_data
                    assert installed.is_dir()
                case["passed"] = True

            run_case("missing-confirmation", ["--delete-data", "--device-id", profile["device_id"]], 2,
                     "--confirm-uninstall")
            run_case("wrong-device-uuid", ["--confirm-uninstall", "--delete-data", "--device-id",
                                           "00000000-0000-0000-0000-000000000000"], 1,
                     "exact device UUID")
            assert verify_package(installed) == manifest
            extra = installed / "unexpected-acceptance.bin"
            extra.write_bytes(b"must not silently delete")
            try:
                run_case("unexpected-binary-file", ["--confirm-uninstall", "--delete-data", "--device-id",
                                                    profile["device_id"]], 1, "unexpected files")
                assert extra.read_bytes() == b"must not silently delete"
            finally:
                extra.unlink()
            link = storage.directory("data") / "external-link.bin"
            link.symlink_to(witness)
            try:
                run_case("reparse-data-path", ["--confirm-uninstall", "--delete-data", "--device-id",
                                              profile["device_id"]], 1, "Reparse paths")
                assert link.is_symlink()
            finally:
                link.unlink()
            assert verify_package(installed) == manifest
            run_case("matching-device-delete", ["--confirm-uninstall", "--delete-data", "--device-id",
                                                profile["device_id"]], 0, "Operation completed", preserves=False)
            assert not installed.exists() and not storage.root.exists()
            assert verify_package(package) == manifest
            report["passed"] = True
            report["outside_witness_preserved"] = True
            report["source_package_preserved"] = True
    finally:
        report_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    return report


def main():
    parser = argparse.ArgumentParser(allow_abbrev=False)
    parser.add_argument("--package", type=Path, required=True)
    parser.add_argument("--evidence", type=Path, required=True)
    arguments = parser.parse_args()
    report = check_package(arguments.package, arguments.evidence.resolve())
    print(json.dumps({"passed": report["passed"], "cases": len(report["cases"]),
                      "evidence": str(arguments.evidence / "package-removal.json")}))


if __name__ == "__main__":
    main()
