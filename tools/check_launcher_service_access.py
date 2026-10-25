import argparse
import os
import ctypes
import hashlib
import json
import re
import subprocess
import tempfile
import time
import uuid
import winreg
from pathlib import Path
from unittest.mock import patch

from kiosk.launcher.storage import DIRECTORIES, Storage
from kiosk.launcher.windows import grant_service_storage

def check_service_access(evidence):
    evidence = evidence.resolve()
    evidence.mkdir(parents=True, exist_ok=True)
    if (evidence / "local-service-access.json").exists():
        raise FileExistsError("Choose a fresh evidence directory.")
    if os.name != "nt":
        raise RuntimeError("This fixture requires Windows.")
    assert ctypes.windll.shell32.IsUserAnAdmin()
    name = "KioskAccessProbe" + uuid.uuid4().hex[:12]


    def command(*arguments, required=True):
        result = subprocess.run(arguments, capture_output=True, timeout=30)
        if required and result.returncode:
            raise RuntimeError((arguments, result.returncode, result.stdout.decode(errors="replace")))
        return result


    with tempfile.TemporaryDirectory(prefix="kiosk-service-access-") as temporary:
        root = Path(temporary).resolve()
        sid = re.search(rb"S-1-5-80(?:-\d+){5}", command("sc.exe", "showsid", name).stdout).group().decode()
        with patch("kiosk.launcher.windows.service_sid", return_value=sid):
            grant_service_storage(Storage(root))
        binary = root / "AccessService.exe"
        framework = Path(os.environ["SystemRoot"]) / "Microsoft.NET/Framework64/v4.0.30319"
        command(str(framework / "csc.exe"), "/noconfig", "/nostdlib+", "/nologo", "/target:exe",
                *["/reference:" + str(framework / library) for library in
                  ("mscorlib.dll", "System.dll", "System.ServiceProcess.dll", "System.Web.Extensions.dll")], "/out:" + str(binary),
                str(Path(__file__).parent / "fixtures/launcher_access_service.cs"))
        storage = Storage(root / "storage")
        for category in DIRECTORIES:
            storage.directory(category).mkdir(parents=True)
        for relative in ("config/device.json", "config/https.json", "secrets/session.key", "secrets/server.key",
                         "data/kiosk.sqlite", "status/runtime.json", "config/https.json.lock"):
            (storage.root / relative).write_bytes(b"disposable non-secret")
        with patch("kiosk.launcher.windows.service_sid", return_value=sid):
            grant_service_storage(storage)
        specs = []

        def add(path, accesses, expected, directory=False):
            for access in accesses:
                specs.append(dict(Path=str(path), Access=access, Directory=directory, Expected=access in expected))

        for relative in ("config/device.json", "config/https.json", "secrets/session.key", "secrets/server.key"):
            add(storage.root / relative, (1, 2, 65536, 262144), (1,))
        for category in ("config", "secrets"):
            add(storage.directory(category), (2,), (), True)
        for category in ("data", "logs", "temp", "status"):
            add(storage.directory(category), (1, 2, 4), (1, 2, 4), True)
        for relative in ("data/kiosk.sqlite", "status/runtime.json", "config/https.json.lock"):
            add(storage.root / relative, (1, 2), (1, 2))
        add(storage.directory("updates"), (1, 2, 262144), (), True)
        add(binary, (1, 2, 65536, 262144), (1,))
        assert len(specs) == 43
        specification = root / "spec.json"
        specification.write_text(json.dumps(specs), encoding="utf-8")
        output = storage.directory("status") / "probe.json"
        hashes = {path.relative_to(root).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
                  for path in root.rglob("*") if path.is_file()}
        created = False
        try:
            command("sc.exe", "create", name, "binPath=", subprocess.list2cmdline([str(binary), name, str(specification), str(output), sid]),
                    "start=", "demand", "obj=", "NT SERVICE\\" + name)
            created = True
            isolated_program_data = root / "ProgramData"
            with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE,
                                "SYSTEM\\CurrentControlSet\\Services\\" + name, 0, winreg.KEY_SET_VALUE) as key:
                winreg.SetValueEx(key, "Environment", 0, winreg.REG_MULTI_SZ, ["PROGRAMDATA=" + str(isolated_program_data)])
            command("sc.exe", "sidtype", name, "unrestricted")
            command("sc.exe", "start", name)
            deadline = time.monotonic() + 25
            while not output.exists() and time.monotonic() < deadline:
                time.sleep(.2)
            report = json.loads(output.read_text())
            (evidence / "local-service-access.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
            assert report["sid"] == sid and report["session_id"] == 0, report
            assert report["program_data"] == str(isolated_program_data), report
            assert report["passed"] and report["checks"] == 43 and report["failed"] == 0, report
            assert not report["backup_enabled"] and not report["restore_enabled"]
            assert all(hashlib.sha256((root / relative).read_bytes()).hexdigest() == expected for relative, expected in hashes.items())
            report["original_file_hashes_preserved"] = True
            report["fixture_only"] = True
            (evidence / "local-service-access.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
        finally:
            if created:
                command("sc.exe", "stop", name, required=False)
                deadline = time.monotonic() + 20
                while time.monotonic() < deadline:
                    query = command("sc.exe", "query", name, required=False)
                    if re.search(rb":\s+1\s+STOPPED", query.stdout):
                        break
                    time.sleep(.2)
                command("sc.exe", "delete", name)
                assert command("sc.exe", "query", name, required=False).returncode == 1060
                (evidence / "local-cleanup.json").write_text(json.dumps({"temporary_service": name, "removed": True}), encoding="utf-8")
    print(json.dumps({"passed": True, "checks": 43, "identity": report["identity"], "temporary_service_removed": True}))


def main():
    parser = argparse.ArgumentParser(allow_abbrev=False)
    parser.add_argument("--evidence", type=Path, required=True)
    arguments = parser.parse_args()
    check_service_access(arguments.evidence)


if __name__ == "__main__":
    main()

