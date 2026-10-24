import subprocess
from pathlib import Path

from kiosk.launcher.client import user_directory
from kiosk.server import browser_candidates


def open_display(origin, mode, fullscreen=True):
    if mode not in {"tv", "kiosk", "admin"}:
        raise ValueError("Unsupported display mode.")
    path = "/admin/login" if mode == "admin" else "/" + mode
    profile = user_directory() / "browser"
    for candidate in browser_candidates():
        if not Path(candidate).is_file():
            continue
        arguments = [candidate, "--user-data-dir=" + str(profile), "--no-first-run", "--new-window", origin + path]
        if fullscreen and mode != "admin":
            arguments.insert(1, "--start-fullscreen")
        subprocess.Popen(arguments, creationflags=subprocess.CREATE_NO_WINDOW)
        return
    raise RuntimeError("Install Google Chrome or Microsoft Edge to open the display.")
