import json
import hashlib
import os
import shutil
import subprocess
import sys
import time
import winreg
from pathlib import Path

from kiosk.launcher.storage import DIRECTORIES, Storage, common_root, read_profile, safe_local_path
from kiosk.launcher.windows import SERVICE_NAME, administrator, grant_service_storage, hidden_run, protect_storage


def binary_directory():
    value = os.environ.get("PROGRAMFILES")
    if not value:
        raise RuntimeError("Windows ProgramFiles is unavailable.")
    return safe_local_path(Path(value) / "Kiosk")


def require_administrator():
    if not administrator():
        raise PermissionError("Windows administrator approval is required.")


def verify_package(directory):
    directory = safe_local_path(directory)
    manifest = directory / "package.json"
    if manifest.stat().st_size > 2 * 1024 * 1024:
        raise ValueError("Package manifest is too large.")
    from kiosk.transport.profile import unique_object

    data = json.loads(manifest.read_text(encoding="utf-8"), object_pairs_hook=unique_object)
    if not isinstance(data, dict) or data.get("schema_version") != 1 or not isinstance(data.get("files"), dict) or not data["files"]:
        raise ValueError("Unsupported package manifest.")
    for name, expected in data["files"].items():
        if not isinstance(name, str) or Path(name).is_absolute() or ".." in Path(name).parts or ":" in name:
            raise ValueError("Invalid package path.")
        path = safe_local_path(directory / name)
        if not path.is_relative_to(directory) or not path.is_file():
            raise ValueError("A package file is unavailable.")
        with path.open("rb") as stream:
            if hashlib.file_digest(stream, "sha256").hexdigest() != expected:
                raise ValueError("A package file does not match its manifest.")
    actual = {path.relative_to(directory).as_posix() for path in directory.rglob("*") if path.is_file() and path != manifest}
    if actual != set(data["files"]):
        raise ValueError("The package contains unexpected files.")
    return data


def service_state():
    result = subprocess.run(["sc.exe", "query", SERVICE_NAME], capture_output=True, creationflags=subprocess.CREATE_NO_WINDOW)
    if result.returncode == 1060:
        return "absent"
    if result.returncode:
        raise RuntimeError("Cannot query the Kiosk service.")
    import re

    match = re.search(rb":\s+([1-7])\s+(?:STOPPED|START_PENDING|STOP_PENDING|RUNNING|CONTINUE_PENDING|PAUSE_PENDING|PAUSED)\b", result.stdout)
    if not match:
        raise RuntimeError("Cannot interpret the Kiosk service state.")
    return {"1": "stopped", "2": "starting", "3": "stopping", "4": "running"}.get(match[1].decode(), "unavailable")


def control_service(action):
    require_administrator()
    if action not in {"start", "stop"}:
        raise ValueError("Unsupported service action.")
    state = service_state()
    if action == "start" and state == "running" or action == "stop" and state == "stopped":
        return
    hidden_run(["sc.exe", action, SERVICE_NAME])
    desired = "running" if action == "start" else "stopped"
    deadline = time.monotonic() + 40
    while time.monotonic() < deadline:
        state = service_state()
        if state == desired:
            return
        if action == "start" and state == "stopped":
            raise RuntimeError("The Kiosk service failed to start. Export diagnostics.")
        time.sleep(.2)
    raise TimeoutError("The Kiosk service operation timed out.")


def register_service(storage):
    require_administrator()
    executable = binary_directory() / "KioskService.exe"
    if not executable.is_file():
        raise ValueError("Install the packaged application first.")
    profile = read_profile(storage.profile)
    command = subprocess.list2cmdline([str(executable)])
    state = service_state()
    if state not in {"absent", "stopped"}:
        raise RuntimeError("Stop the service before changing its configuration.")
    operation = "create" if state == "absent" else "config"
    hidden_run(["sc.exe", operation, SERVICE_NAME, "binPath=", command, "start=", "auto" if profile["server_autostart"] else "demand",
                "obj=", "NT SERVICE\\" + SERVICE_NAME, "DisplayName=", "Kiosk Local Server"])
    hidden_run(["sc.exe", "sidtype", SERVICE_NAME, "unrestricted"])
    from kiosk.launcher.windows import service_sid

    hidden_run(["icacls.exe", str(binary_directory()), "/grant:r", f"*{service_sid()}:(OI)(CI)RX", "/T"])
    grant_service_storage(storage)
    hidden_run(["sc.exe", "description", SERVICE_NAME, "Kiosk local content server. Display starts separately after user sign-in."])


def install():
    require_administrator()
    if not getattr(sys, "frozen", False):
        raise ValueError("Installation requires the packaged application.")
    source = safe_local_path(Path(sys.executable).parent)
    target = binary_directory()
    if source == target:
        return
    manifest = verify_package(source)
    if service_state() not in {"absent", "stopped"}:
        raise RuntimeError("Stop Kiosk before reinstalling.")
    for name in ("KioskLauncher.exe", "KioskService.exe", "KioskCertificates.exe", "_internal"):
        if not (source / name).exists():
            raise ValueError("The offline installation package is incomplete.")
    if target.exists():
        if verify_package(target) == manifest:
            return
        raise ValueError("A different installation already exists. Preserve it; executable updates belong to stage 7.")
    staging = target.with_name("Kiosk.installing")
    if staging.exists():
        raise ValueError("An interrupted installation requires local review.")
    staging.mkdir()
    try:
        hidden_run(["icacls.exe", str(staging), "/inheritance:r", "/grant:r", "*S-1-5-18:(OI)(CI)F",
                    "*S-1-5-32-544:(OI)(CI)F", "*S-1-5-32-545:(OI)(CI)RX"])
        for item in source.iterdir():
            safe_local_path(item)
            if item.is_dir():
                from kiosk.launcher.storage import copy_tree

                copy_tree(item, staging / item.name)
            else:
                shutil.copy2(item, staging / item.name)
        staging.rename(target)
    except BaseException:
        if staging.exists():
            shutil.rmtree(staging)
        raise


def uninstall(delete_data=False, device_id=None):
    require_administrator()
    target = binary_directory()
    if not getattr(sys, "frozen", False) or Path(sys.executable).parent == target:
        raise ValueError("Run uninstall from the original external offline package.")
    verify_package(target)
    storage = Storage(common_root())
    if delete_data:
        if device_id != read_profile(storage.profile)["device_id"]:
            raise ValueError("Data deletion requires the exact device UUID.")
        for path in storage.root.rglob("*"):
            safe_local_path(path)
    state = service_state()
    if state != "absent":
        if state != "stopped":
            control_service("stop")
        hidden_run(["sc.exe", "delete", SERVICE_NAME])
    for path in target.rglob("*"):
        safe_local_path(path)
    shutil.rmtree(target)
    if delete_data:
        shutil.rmtree(storage.root)


def initialize_directories(storage):
    require_administrator()
    storage.root.mkdir(parents=True, exist_ok=True)
    protect_storage_root = storage.root
    hidden_run(["icacls.exe", str(protect_storage_root), "/inheritance:r", "/grant:r", "*S-1-5-18:(OI)(CI)F", "*S-1-5-32-544:(OI)(CI)F"])
    for name in DIRECTORIES:
        storage.directory(name).mkdir(exist_ok=True)
    protect_storage(storage)


def configure_user_startup(enabled):
    executable = binary_directory() / "KioskLauncher.exe"
    with winreg.CreateKey(winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\Run") as key:
        if enabled:
            if not executable.is_file():
                raise ValueError("Install Kiosk before enabling startup.")
            winreg.SetValueEx(key, "KioskDisplay", 0, winreg.REG_SZ, subprocess.list2cmdline([str(executable), "--autostart"]))
        else:
            try:
                winreg.DeleteValue(key, "KioskDisplay")
            except FileNotFoundError:
                pass


def user_startup_enabled():
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\Run") as key:
            return winreg.QueryValueEx(key, "KioskDisplay")[0] == subprocess.list2cmdline([str(binary_directory() / "KioskLauncher.exe"), "--autostart"])
    except FileNotFoundError:
        return False
