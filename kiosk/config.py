from pathlib import Path


class Config:
    BASE_DIR = Path(__file__).resolve().parent.parent
    INSTANCE_DIR = BASE_DIR / "instance"
    DATABASE_PATH = INSTANCE_DIR / "kiosk.sqlite"
    SECRET_KEY = "dev"
    SERVER_HOST = "127.0.0.1"
    SERVER_PORT = 5000
    DEBUG = True
