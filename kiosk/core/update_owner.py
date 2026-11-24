"""Windows kernel ownership, shared with the detached activation helper.

The persistent .owner file is only a kernel object name. Never unlink it: an
exclusive CreateFile handle, not its contents, PID, timeout or a task, owns work.
An explicitly inherited handle keeps ownership continuous across parent exit.
"""
import ctypes
import os
import subprocess
import hashlib
from ctypes import wintypes
from pathlib import Path
from functools import wraps


class Busy(RuntimeError):
    pass


class Owner:
    def __init__(self, path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.kernel = ctypes.WinDLL('kernel32', use_last_error=True)
        self.kernel.CreateFileW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD,
            wintypes.DWORD, wintypes.LPVOID, wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE]
        self.kernel.CreateFileW.restype = wintypes.HANDLE
        self.kernel.CloseHandle.argtypes = [wintypes.HANDLE]
        self.handle = self.kernel.CreateFileW(str(self.path), 0xC0000000, 0, None, 4, 0x80, None)
        if self.handle == wintypes.HANDLE(-1).value:
            error = ctypes.get_last_error()
            self.handle = None
            if error in (32, 33):
                raise Busy('An update is already in progress; its live owner holds the Windows lock.')
            raise ctypes.WinError(error)

    def close(self):
        if self.handle is not None:
            self.kernel.CloseHandle(self.handle)
            self.handle = None

    def launch(self, helper, request):
        """Same token as caller; no scheduler, elevation or writable SYSTEM code."""
        env = os.environ.copy()
        env['KIOSK_UPDATE_OWNER_HANDLE'] = str(self.handle)
        self.kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        self.kernel.OpenProcess.restype = wintypes.HANDLE
        parent = self.kernel.OpenProcess(0x00100000, True, os.getpid())
        if not parent:
            raise ctypes.WinError(ctypes.get_last_error())
        env['KIOSK_UPDATE_PARENT_HANDLE'] = str(parent)
        startup = subprocess.STARTUPINFO(lpAttributeList={'handle_list': [self.handle, parent]})
        os.set_handle_inheritable(self.handle, True)
        try:
            child = subprocess.Popen([str(helper), str(request)], env=env,
                startupinfo=startup, close_fds=True, stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                creationflags=subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP)
        finally:
            os.set_handle_inheritable(self.handle, False)
            self.kernel.CloseHandle(parent)
        # The child's inherited reference now owns the SAME kernel file object.
        self.close()
        return child.pid


_owners = {}


def tree_digest(root):
    root = Path(root)
    records = []
    for path in sorted((p for p in root.rglob('*') if p.is_file()),
                       key=lambda p: p.relative_to(root).as_posix()):
        with path.open('rb') as stream:
            digest = hashlib.file_digest(stream, 'sha256').hexdigest()
        records.append(path.relative_to(root).as_posix() + '\0' + digest + '\n')
    return hashlib.sha256(''.join(records).encode('utf-8')).hexdigest()


def acquire(path):
    key = str(Path(path).resolve())
    owner = Owner(key + '.owner')
    _owners[key] = owner
    return owner


def release(path):
    owner = _owners.pop(str(Path(path).resolve()), None)
    if owner is not None:
        owner.close()


def handoff(path, helper, request):
    key = str(Path(path).resolve())
    owner = _owners[key]
    pid = owner.launch(helper, request)
    _owners.pop(key)
    return pid


def guarded(path_function, *, status=False):
    """Serialize status/recovery too; observers must never finalize a live owner."""
    def decorate(function):
        @wraps(function)
        def run(*args, **kwargs):
            path = path_function(*args, **kwargs)
            try:
                acquire(path)
            except Busy:
                if status:
                    return {'state': 'pending', 'note': 'a live updater owns preparation or activation'}
                raise
            try:
                return function(*args, **kwargs)
            finally:
                release(path)
        return run
    return decorate
