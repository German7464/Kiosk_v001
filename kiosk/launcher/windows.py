import ctypes
import os
import re
import subprocess
from ctypes import wintypes


SERVICE_NAME = "KioskService"


def hidden_run(arguments, timeout=30):
    result = subprocess.run(arguments, capture_output=True, timeout=timeout,
                            creationflags=subprocess.CREATE_NO_WINDOW)
    if result.returncode:
        raise RuntimeError(f"Windows operation failed ({result.returncode}).")
    return result.stdout


def administrator():
    return os.name == "nt" and bool(ctypes.windll.shell32.IsUserAnAdmin())


def available_memory():
    class MemoryStatus(ctypes.Structure):
        _fields_ = [("length", wintypes.DWORD), ("load", wintypes.DWORD),
                    *[(name, ctypes.c_ulonglong) for name in ("total_physical", "available_physical", "total_page", "available_page", "total_virtual", "available_virtual", "available_extended")]]

    status = MemoryStatus()
    status.length = ctypes.sizeof(status)
    if not ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status)):
        raise OSError("Cannot inspect Windows memory availability.")
    return status.available_physical


def service_sid():
    output = hidden_run(["sc.exe", "showsid", SERVICE_NAME])
    match = re.search(rb"S-1-5-80(?:-\d+){5}", output)
    if not match:
        raise RuntimeError("Cannot determine the Windows service identity.")
    return match.group().decode("ascii")


def protect_storage(storage, include_service=False):
    if os.name != "nt":
        raise RuntimeError("Installed storage currently requires Windows.")
    user = hidden_run(["whoami.exe", "/user", "/fo", "csv", "/nh"]).decode("utf-8", errors="replace").strip().split(",")[-1].strip('"')
    if not user.startswith("S-1-"):
        raise RuntimeError("Cannot determine the current Windows identity.")
    from kiosk.launcher.storage import safe_local_path

    api = ctypes.WinDLL("advapi32", use_last_error=True)
    api.ConvertStringSecurityDescriptorToSecurityDescriptorW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, ctypes.POINTER(ctypes.c_void_p), ctypes.POINTER(wintypes.DWORD)]
    api.ConvertStringSecurityDescriptorToSecurityDescriptorW.restype = wintypes.BOOL
    api.SetFileSecurityW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, ctypes.c_void_p]
    api.SetFileSecurityW.restype = wintypes.BOOL
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.LocalFree.argtypes = [ctypes.c_void_p]
    kernel.LocalFree.restype = ctypes.c_void_p
    principal = service_sid() if include_service else None
    for path in (storage.root, *storage.root.rglob("*")):
        path = safe_local_path(path)
        relative = path.relative_to(storage.root)
        category = relative.parts[0] if relative.parts else None
        sddl = f"D:P(A;OICI;FA;;;SY)(A;OICI;FA;;;BA)(A;OICI;FA;;;{user})"
        if category == "status":
            sddl += "(A;OICI;GRGX;;;BU)"
        if principal:
            access = "0x1301bf" if category in {"data", "logs", "temp", "status"} or relative.as_posix() == "config/https.json.lock" else "GRGX"
            if category != "updates":
                sddl += f"(A;OICI;{access};;;{principal})"
        descriptor = ctypes.c_void_p()
        if not api.ConvertStringSecurityDescriptorToSecurityDescriptorW(sddl, 1, ctypes.byref(descriptor), None):
            raise ctypes.WinError(ctypes.get_last_error())
        try:
            if not api.SetFileSecurityW(str(path), 0x80000004, descriptor):
                raise ctypes.WinError(ctypes.get_last_error())
        finally:
            kernel.LocalFree(descriptor)


def grant_service_storage(storage):
    protect_storage(storage, include_service=True)
