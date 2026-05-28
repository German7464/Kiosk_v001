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
    SECRET_KEY = "dev"
    SERVER_HOST = "127.0.0.1"
    SERVER_PORT = 5000
    DEBUG = True
