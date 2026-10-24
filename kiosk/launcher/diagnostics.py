import logging
import shutil
import time
import traceback
import uuid
from pathlib import Path

from flask import g, request


def record_failure(logger, event, error, **fields):
    frames = traceback.extract_tb(error.__traceback__)[-20:]
    location = ";".join(f"{Path(frame.filename).name}:{frame.lineno}:{frame.name}" for frame in frames)
    logger.error("event=%s error=%s frames=%s fields=%s", event, type(error).__name__, location, fields)


def record_resources(logger, storage):
    from kiosk.launcher.windows import available_memory

    try:
        disk = shutil.disk_usage(storage.root).free
        memory = available_memory()
        level = logging.WARNING if disk < 1024 ** 3 or memory < 256 * 1024 ** 2 else logging.INFO
        logger.log(level, "event=resources free_disk_bytes=%d available_memory_bytes=%d low_disk=%s low_memory=%s",
                   disk, memory, disk < 1024 ** 3, memory < 256 * 1024 ** 2)
    except OSError as error:
        record_failure(logger, "resource_probe_failed", error)


def instrument_app(app, logger, slow_seconds=1):
    def log_exception(info):
        record_failure(logger, "application_failed", info[1], request_id=getattr(g, "diagnostic_id", "none"))

    app.log_exception = log_exception

    @app.before_request
    def begin_request():
        g.diagnostic_started = time.monotonic()
        g.diagnostic_id = uuid.uuid4().hex

    @app.after_request
    def finish_request(response):
        finished = time.monotonic()
        elapsed = max(0, finished - getattr(g, "diagnostic_started", finished))
        level = logging.ERROR if response.status_code >= 500 else logging.WARNING if response.status_code >= 400 or elapsed >= slow_seconds else logging.INFO
        route = request.url_rule.rule if request.url_rule else "unmatched"
        method = request.method if request.method in {"GET", "HEAD", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"} else "other"
        logger.log(level, "event=http_request request_id=%s method=%s route=%s status=%d duration_ms=%.3f slow=%s",
                   getattr(g, "diagnostic_id", "none"), method, route, response.status_code, elapsed * 1000, elapsed >= slow_seconds)
        return response

    return app
