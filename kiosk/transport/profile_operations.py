import ctypes
from ctypes import wintypes
import json
import os
from pathlib import Path
import stat
import tempfile

from kiosk.transport.profile import unique_object


def safe_path(value):
    path = Path(os.path.abspath(value))
    for item in (path, *path.parents):
        if item.is_symlink() or item.exists() and getattr(item.stat(follow_symlinks=False), "st_file_attributes", 0) & stat.FILE_ATTRIBUTE_REPARSE_POINT:
            raise ValueError("Reparse paths are unsupported for HTTPS profiles.")
    return path


def bounded_bytes(path, limit=65536):
    with safe_path(path).open("rb") as stream:
        data = stream.read(limit + 1)
    if len(data) > limit:
        raise ValueError("HTTPS transaction input is too large.")
    return data


def copy_dacl(source, target):
    if os.name != "nt":
        os.chmod(target, source.stat().st_mode & 0o777)
        return
    api = ctypes.WinDLL("advapi32", use_last_error=True)
    api.GetFileSecurityW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(wintypes.DWORD)]
    api.GetFileSecurityW.restype = wintypes.BOOL
    api.SetFileSecurityW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, ctypes.c_void_p]
    api.SetFileSecurityW.restype = wintypes.BOOL
    api.GetSecurityDescriptorControl.argtypes = [ctypes.c_void_p, ctypes.POINTER(wintypes.WORD), ctypes.POINTER(wintypes.DWORD)]
    api.GetSecurityDescriptorControl.restype = wintypes.BOOL
    required = wintypes.DWORD()
    api.GetFileSecurityW(str(source), 4, None, 0, ctypes.byref(required))
    if not required.value:
        raise ctypes.WinError(ctypes.get_last_error())
    descriptor = ctypes.create_string_buffer(required.value)
    if not api.GetFileSecurityW(str(source), 4, descriptor, required.value, ctypes.byref(required)):
        raise ctypes.WinError(ctypes.get_last_error())
    control = wintypes.WORD()
    revision = wintypes.DWORD()
    if not api.GetSecurityDescriptorControl(descriptor, ctypes.byref(control), ctypes.byref(revision)):
        raise ctypes.WinError(ctypes.get_last_error())
    flags = 4 | (0x80000000 if control.value & 0x1000 else 0x20000000)
    if not api.SetFileSecurityW(str(target), flags, descriptor):
        raise ctypes.WinError(ctypes.get_last_error())


def atomic_profile_write(filename, data):
    filename = safe_path(filename)
    descriptor, name = tempfile.mkstemp(prefix=".kiosk-profile-", dir=filename.parent)
    temporary = Path(name)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            copy_dacl(filename, temporary)
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, filename)
    finally:
        if temporary.exists():
            temporary.unlink()


def journal_path(filename):
    filename = safe_path(filename)
    return safe_path(filename.with_name(filename.name + ".certificate-transaction.json"))


def recover_profile(filename):
    filename = safe_path(filename)
    journal = journal_path(filename)
    if not journal.exists():
        return False
    data = json.loads(bounded_bytes(journal, 300000), object_pairs_hook=unique_object)
    if not isinstance(data, dict) or set(data) != {"schema_version", "original", "candidate"} or type(data["schema_version"]) is not int or data["schema_version"] != 1:
        raise ValueError("Invalid certificate transaction journal.")
    if any(not isinstance(data[name], str) or len(data[name].encode("utf-8")) > 65536 for name in ("original", "candidate")):
        raise ValueError("Invalid certificate transaction snapshot.")
    original, candidate = (data[name].encode("utf-8") for name in ("original", "candidate"))
    current = bounded_bytes(filename)
    if current not in (original, candidate):
        raise ValueError("HTTPS profile differs from interrupted transaction; operator review required.")
    if current != original:
        atomic_profile_write(filename, original)
    journal.unlink()
    return True


class ProfileLease:
    def __init__(self, filename):
        self.filename = safe_path(filename)
        self.stream = None

    def acquire(self):
        if os.name != "nt":
            raise RuntimeError("HTTPS profile locking requires Windows.")
        import msvcrt

        lock = safe_path(self.filename.with_name(self.filename.name + ".lock"))
        self.stream = lock.open("a+b")
        try:
            self.stream.seek(0, os.SEEK_END)
            if self.stream.tell() == 0:
                self.stream.write(b"0")
                self.stream.flush()
            self.stream.seek(0)
            msvcrt.locking(self.stream.fileno(), msvcrt.LK_NBLCK, 1)
        except BaseException:
            self.stream.close()
            self.stream = None
            raise
        return self

    def close(self):
        if self.stream is not None:
            self.stream.close()
            self.stream = None

    def __enter__(self):
        return self.acquire()

    def __exit__(self, *unused):
        self.close()


class ProfileTransaction:
    def __init__(self, filename, candidate):
        self.filename = safe_path(filename)
        self.original = bounded_bytes(self.filename)
        self.candidate = candidate
        self.journal = journal_path(self.filename)

    def prepare(self):
        if len(self.candidate) > 65536 or self.original == self.candidate:
            raise ValueError("Invalid certificate candidate profile.")
        if bounded_bytes(self.filename) != self.original:
            raise ValueError("HTTPS profile changed before certificate activation.")
        payload = json.dumps({"schema_version": 1, "original": self.original.decode("utf-8"), "candidate": self.candidate.decode("utf-8")}).encode("utf-8")
        with self.journal.open("xb") as stream:
            copy_dacl(self.filename, self.journal)
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())

    def commit(self):
        if bounded_bytes(self.filename) != self.original:
            raise ValueError("HTTPS profile changed during certificate activation.")
        atomic_profile_write(self.filename, self.candidate)
        self.journal.unlink()

    def rollback(self):
        return recover_profile(self.filename)
