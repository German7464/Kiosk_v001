import sys
from pathlib import Path


def resource_directory():
    if getattr(sys, "frozen", False):
        return Path(sys._MEIPASS)

    return Path(__file__).resolve().parent.parent


def runtime_directory():
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent

    return Path(__file__).resolve().parent.parent


class Config:
    BASE_DIR = runtime_directory()
    RESOURCE_DIR = resource_directory()
    RESOURCE_STATIC_DIR = RESOURCE_DIR / "kiosk" / "static"
    STATIC_DIR = BASE_DIR / "kiosk" / "static"
    INSTANCE_DIR = BASE_DIR / "instance"
    DATABASE_PATH = INSTANCE_DIR / "kiosk.sqlite"
    PRIVATE_UPLOAD_DIR = INSTANCE_DIR / "uploads"
    PUBLIC_UPLOAD_DIR = STATIC_DIR / "uploads"
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = "Lax"
    MAX_CONTENT_LENGTH = 20 * 1024 * 1024
    MAX_UPLOAD_FILE_BYTES = 16 * 1024 * 1024
    MAX_IMAGE_PIXELS = 25_000_000
    MAX_FORM_MEMORY_SIZE = 256 * 1024
    MAX_FORM_PARTS = 100
    SECRET_KEY = None
    SERVER_HOST = "127.0.0.1"
    SERVER_PORT = 5000
    DEBUG = False
