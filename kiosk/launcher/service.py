import ctypes
import threading
from ctypes import wintypes

from kiosk.launcher.runtime import supervise
from kiosk.launcher.storage import Storage, common_root
from kiosk.launcher.windows import SERVICE_NAME


class ServiceStatus(ctypes.Structure):
    _fields_ = [(name, wintypes.DWORD) for name in ("service_type", "state", "accepted", "error", "specific_error", "checkpoint", "wait_hint")]


def dispatch():
    api = ctypes.WinDLL("advapi32", use_last_error=True)
    handler_type = ctypes.WINFUNCTYPE(wintypes.DWORD, wintypes.DWORD, wintypes.DWORD, ctypes.c_void_p, ctypes.c_void_p)
    main_type = ctypes.WINFUNCTYPE(None, wintypes.DWORD, ctypes.POINTER(wintypes.LPWSTR))

    class Entry(ctypes.Structure):
        _fields_ = [("name", wintypes.LPWSTR), ("main", main_type)]

    api.RegisterServiceCtrlHandlerExW.argtypes = [wintypes.LPCWSTR, handler_type, ctypes.c_void_p]
    api.RegisterServiceCtrlHandlerExW.restype = wintypes.HANDLE
    api.SetServiceStatus.argtypes = [wintypes.HANDLE, ctypes.POINTER(ServiceStatus)]
    api.SetServiceStatus.restype = wintypes.BOOL
    api.StartServiceCtrlDispatcherW.argtypes = [ctypes.POINTER(Entry)]
    api.StartServiceCtrlDispatcherW.restype = wintypes.BOOL
    stopped = threading.Event()
    handle = None
    lock = threading.Lock()
    state = 2
    checkpoint = 0

    def report(value, error=0):
        nonlocal state, checkpoint
        with lock:
            state = value
            checkpoint = checkpoint + 1 if value in (2, 3) else 0
            status = ServiceStatus(0x10, value, 5 if value == 4 else 0, error, 0, checkpoint, 30000 if value in (2, 3) else 0)
            if not api.SetServiceStatus(handle, ctypes.byref(status)):
                raise ctypes.WinError(ctypes.get_last_error())

    @handler_type
    def control(code, event, data, context):
        if code in (1, 5):
            report(3)
            stopped.set()
        elif code == 4:
            report(state)
        return 0

    @main_type
    def main(count, arguments):
        nonlocal handle
        handle = api.RegisterServiceCtrlHandlerExW(SERVICE_NAME, control, None)
        if not handle:
            return
        report(2)
        finished = threading.Event()

        def heartbeat():
            while not finished.wait(3):
                if state in (2, 3):
                    report(state)

        worker = threading.Thread(target=heartbeat, daemon=True)
        worker.start()
        code = 1
        try:
            code = supervise(Storage(common_root()), stopped, running=lambda: report(4))
        finally:
            finished.set()
            worker.join(timeout=4)
            report(1, 1066 if code else 0)

    entries = (Entry * 2)(Entry(SERVICE_NAME, main), Entry(None, main_type()))
    if not api.StartServiceCtrlDispatcherW(entries):
        raise ctypes.WinError(ctypes.get_last_error())
