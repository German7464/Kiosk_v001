import os
import secrets
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


def load_or_create_secret_key(instance_dir):
    environment_secret = os.environ.get("KIOSK_SECRET_KEY")
    if environment_secret:
        return environment_secret

    instance_path = Path(instance_dir)
    instance_path.mkdir(parents=True, exist_ok=True)
    secret_path = instance_path / "secret_key.txt"

    if secret_path.exists():
        secret = secret_path.read_text(encoding="utf-8").strip()
        if secret:
            return secret

    secret = secrets.token_urlsafe(48)
    secret_path.write_text(secret, encoding="utf-8")
    return secret


class Config:
    BASE_DIR = runtime_directory()
    RESOURCE_DIR = resource_directory()
    RESOURCE_STATIC_DIR = RESOURCE_DIR / "kiosk" / "static"
    STATIC_DIR = BASE_DIR / "kiosk" / "static"
    INSTANCE_DIR = BASE_DIR / "instance"
    DATABASE_PATH = INSTANCE_DIR / "kiosk.sqlite"
    PRIVATE_UPLOAD_DIR = INSTANCE_DIR / "uploads"
    PUBLIC_UPLOAD_DIR = STATIC_DIR / "uploads"
    SECRET_KEY = None
    SERVER_HOST = "127.0.0.1"
    SERVER_PORT = 5000
    DEBUG = True
