import os
import re
import secrets
import tempfile
from pathlib import Path


def configure_session_security(app):
    if app.config.get("SECRET_KEY") is not None:
        if not app.config["SECRET_KEY"]:
            raise RuntimeError("Explicit SECRET_KEY must not be empty.")
        return

    app.config["SECRET_KEY"] = load_session_key(app.config.get("SECRETS_DIR", app.config["INSTANCE_DIR"]))


def load_session_key(instance_directory):
    key_path = Path(instance_directory) / "session.key"
    temporary_path = None
    try:
        key_path.parent.mkdir(parents=True, exist_ok=True)
        if not key_path.exists():
            with tempfile.NamedTemporaryFile(dir=key_path.parent, prefix=".session-", delete=False) as stream:
                temporary_path = Path(stream.name)
                os.chmod(temporary_path, 0o600)
                stream.write(secrets.token_hex(32).encode("ascii"))
                stream.flush()
                os.fsync(stream.fileno())
            try:
                os.link(temporary_path, key_path)
            except FileExistsError:
                pass
        key = key_path.read_bytes()
        if re.fullmatch(rb"[0-9a-f]{64}", key) is None:
            raise ValueError
        return key.decode("ascii")
    except (OSError, ValueError):
        raise RuntimeError("Cannot initialize session key at instance/session.key. Check file access and integrity; the existing key has not been replaced.") from None
    finally:
        if temporary_path is not None:
            try:
                temporary_path.unlink(missing_ok=True)
            except OSError:
                pass
