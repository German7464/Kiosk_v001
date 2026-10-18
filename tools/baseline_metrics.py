import ctypes
import math
import platform
import statistics
import sys
from ctypes import wintypes
from importlib.metadata import version


class ProcessMemory(ctypes.Structure):
    _fields_ = [("cb", wintypes.DWORD), ("faults", wintypes.DWORD)] + [
        (name, ctypes.c_size_t) for name in (
            "peak_working", "working", "peak_paged", "paged", "peak_nonpaged",
            "nonpaged", "pagefile", "peak_pagefile",
        )
    ]


class SystemMemory(ctypes.Structure):
    _fields_ = [("length", wintypes.DWORD), ("load", wintypes.DWORD)] + [
        (name, ctypes.c_ulonglong) for name in (
            "physical", "available_physical", "pagefile", "available_pagefile",
            "virtual", "available_virtual", "extended",
        )
    ]


def working_memory(pid):
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    psapi = ctypes.WinDLL("psapi", use_last_error=True)
    kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel.OpenProcess.restype = wintypes.HANDLE
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    psapi.GetProcessMemoryInfo.argtypes = [wintypes.HANDLE, ctypes.POINTER(ProcessMemory), wintypes.DWORD]
    handle = kernel.OpenProcess(0x410, False, pid)
    if not handle:
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        memory = ProcessMemory()
        memory.cb = ctypes.sizeof(memory)
        if not psapi.GetProcessMemoryInfo(handle, ctypes.byref(memory), memory.cb):
            raise ctypes.WinError(ctypes.get_last_error())
        return memory.working
    finally:
        kernel.CloseHandle(handle)


def environment_details():
    if sys.platform != "win32":
        raise RuntimeError("This measurement profile requires Windows.")
    memory = SystemMemory()
    memory.length = ctypes.sizeof(memory)
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.GlobalMemoryStatusEx.argtypes = [ctypes.POINTER(SystemMemory)]
    if not kernel.GlobalMemoryStatusEx(ctypes.byref(memory)):
        raise ctypes.WinError(ctypes.get_last_error())
    packages = (
        "Flask", "Werkzeug", "Waitress", "Pillow", "PyInstaller", "pip",
        "altgraph", "blinker", "click", "itsdangerous", "Jinja2", "MarkupSafe",
        "packaging", "pefile", "pyinstaller-hooks-contrib", "pywin32-ctypes", "setuptools",
    )
    return {
        "python": sys.version, "os": platform.platform(), "architecture": platform.machine(),
        "processor": platform.processor(), "physical_ram_bytes": memory.physical,
        "packages": {name: version(name) for name in packages},
    }


def summarize(samples, elapsed):
    if not samples or elapsed <= 0:
        raise ValueError("Samples and positive elapsed time are required.")
    ordered = sorted(sample["milliseconds"] for sample in samples)
    codes = {}
    for sample in samples:
        key = str(sample["status"])
        codes[key] = codes.get(key, 0) + 1
    sizes = [sample["bytes"] for sample in samples]
    return {
        "requests": len(samples), "median_ms": statistics.median(ordered),
        "p95_ms": ordered[math.ceil(len(ordered) * 0.95) - 1], "max_ms": ordered[-1],
        "elapsed_seconds": elapsed, "requests_per_second": len(samples) / elapsed,
        "response_bytes_min": min(sizes), "response_bytes_max": max(sizes),
        "response_bytes_total": sum(sizes), "statuses": codes,
        "errors": sum(sample.get("error") is not None for sample in samples),
    }
