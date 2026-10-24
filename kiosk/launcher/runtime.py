import json
import logging
import os
import secrets
import threading
import time
from logging.handlers import RotatingFileHandler

from waitress import create_server, wasyncore
from waitress.task import ThreadedTaskDispatcher

from kiosk.app import create_app
from kiosk.launcher.diagnostics import instrument_app, record_failure, record_resources
from kiosk.launcher.storage import atomic_json, read_profile
from kiosk.transport.profile import load_profile
from kiosk.transport.profile_operations import ProfileLease
from kiosk.transport.runtime import ManagedHttps


VERSION = "2.0-stage3-dev"


class LocalRuntime:
    def __init__(self, storage, profile, logger=None):
        self.storage = storage
        self.profile = profile
        self.identity = secrets.token_hex(24)
        self.server = None
        self.thread = None
        self.stop = threading.Event()
        self.channels = {}
        self.dispatcher = None
        self.logger = logger

    def start(self):
        app = create_app(self.storage.app_config())
        if self.logger is not None:
            instrument_app(app, self.logger)

        def identified(environ, start_response):
            def respond(status, headers, exc_info=None):
                if environ.get("PATH_INFO") == "/api/version":
                    headers = [*headers, ("X-Kiosk-Instance", self.identity)]
                return start_response(status, headers, exc_info)
            return app(environ, respond)

        self.dispatcher = ThreadedTaskDispatcher()
        self.dispatcher.set_thread_count(4)
        try:
            self.server = create_server(identified, host="127.0.0.1", port=self.profile["port"], threads=4,
                                        map=self.channels, _dispatcher=self.dispatcher,
                                        max_request_body_size=app.config["MAX_CONTENT_LENGTH"])
        except BaseException:
            self.close()
            raise

        def serve():
            try:
                while not self.stop.is_set():
                    self.server.asyncore.loop(timeout=.05, count=1, map=self.server._map)
            except Exception as error:
                if self.logger is not None:
                    record_failure(self.logger, "listener_failed", error)
            finally:
                self.stop.set()

        self.thread = threading.Thread(target=serve, daemon=True)
        self.thread.start()
        return self

    def check_running(self):
        if self.stop.is_set() or self.thread is None or not self.thread.is_alive() or self.server.socket.fileno() < 0:
            raise RuntimeError("The local server stopped.")

    def close(self):
        if self.server is None:
            if self.dispatcher is not None:
                self.dispatcher.shutdown(timeout=8)
            wasyncore.close_all(map=self.channels)
            return
        drained = self.server.task_dispatcher.shutdown(timeout=8)
        self.stop.set()
        if self.thread:
            self.thread.join(timeout=1)
        self.server.close()
        self.server.asyncore.close_all(map=self.server._map)
        if not drained or self.thread and self.thread.is_alive():
            raise RuntimeError("The local server did not stop cleanly.")


def logger_for(storage):
    logger = logging.getLogger("kiosk.installed." + str(storage.root))
    logger.setLevel(logging.INFO)
    logger.propagate = False
    handler = RotatingFileHandler(storage.directory("logs") / "startup.log", maxBytes=5 * 1024 * 1024, backupCount=4, encoding="utf-8")
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s pid=%(process)d thread=%(threadName)s %(message)s"))
    logger.addHandler(handler)
    return logger, handler


def supervise(storage, stopped, running=lambda: None, delays=(5, 15, 60)):
    logger, handler = logger_for(storage)
    runtime = None
    lease = None
    transport_lease = None
    profile = None
    exit_code = 0
    last_error = None
    was_running = False
    started_at = time.monotonic()

    def status(state, error=None, record=True):
        nonlocal last_error
        if error is not None:
            last_error = error
        data = {"schema_version": 1, "state": state, "version": VERSION, "pid": os.getpid(),
                "device_name": profile["device_name"] if profile else "", "device_id": profile["device_id"] if profile else "",
                "mode": profile["mode"] if profile else "kiosk", "orientation": profile["orientation"] if profile else "landscape",
                "origin": origin if profile else "", "identity": runtime.identity if runtime else "",
                "updated_at": time.time(), "error": last_error if state in {"recovering", "failed"} else None}
        atomic_json(storage.directory("status") / "runtime.json", data)
        if record:
            logger.info("event=service_state state=%s error=%s uptime_seconds=%.3f", state, error or "none", time.monotonic() - started_at)

    origin = ""
    try:
        lease = ProfileLease(storage.directory("status") / "installation").acquire()
        profile = read_profile(storage.profile)
        for attempt in range(len(delays) + 1):
            try:
                attempt_started = time.monotonic()
                logger.info("event=start_attempt attempt=%d transport=%s", attempt + 1, profile["transport"])
                status("starting")
                if profile["transport"] == "https":
                    path = storage.directory("config") / "https.json"
                    transport_lease = ProfileLease(path).acquire()
                    if path.with_name(path.name + ".certificate-transaction.json").exists():
                        raise RuntimeError("Certificate recovery requires local administrative maintenance.")
                    https = load_profile(path)
                    origin = https.public_origin
                    runtime = ManagedHttps(https, app_factory=lambda overrides: instrument_app(create_app({**storage.app_config(), **overrides}), logger), temporary_directory=storage.directory("temp"))
                else:
                    origin = f"http://127.0.0.1:{profile['port']}"
                    runtime = LocalRuntime(storage, profile, logger=logger)
                runtime.start()
                logger.info("event=start_completed duration_ms=%.3f", (time.monotonic() - attempt_started) * 1000)
                was_running = True
                status("running")
                running()
                last_status = time.monotonic()
                record_resources(logger, storage)
                last_resources = time.monotonic()
                while not stopped.wait(.1):
                    runtime.check_running()
                    if time.monotonic() - last_status >= 2:
                        if time.monotonic() - last_status >= 5:
                            logger.warning("event=supervisor_delayed interval_seconds=%.3f", time.monotonic() - last_status)
                        status("running", record=False)
                        last_status = time.monotonic()
                    if time.monotonic() - last_resources >= 60:
                        record_resources(logger, storage)
                        last_resources = time.monotonic()
                break
            except Exception as error:
                record_failure(logger, "runtime_failed", error, attempt=attempt + 1, phase=getattr(runtime, "phase", "local"))
                status("recovering", type(error).__name__)
                if runtime is not None:
                    result = runtime.close()
                    if isinstance(result, dict) and (result.get("proxy_forced") or not result.get("backend_stopped", True)):
                        raise RuntimeError("Unsafe runtime cleanup; automatic restart stopped.")
                    runtime = None
                if transport_lease is not None:
                    transport_lease.close()
                    transport_lease = None
                if not was_running:
                    raise
                if attempt == len(delays):
                    raise RuntimeError("The restart budget is exhausted.") from None
                logger.warning("event=restart_scheduled delay_seconds=%s attempt=%d", delays[attempt], attempt + 2)
                if stopped.wait(delays[attempt]):
                    break
        status("stopping")
    except Exception as error:
        exit_code = 1
        if lease is not None and lease.stream is not None:
            status("failed", type(error).__name__)
        record_failure(logger, "service_failed", error)
    finally:
        try:
            if runtime is not None:
                stop_started = time.monotonic()
                result = runtime.close()
                logger.info("event=stop_completed duration_ms=%.3f", (time.monotonic() - stop_started) * 1000)
                if isinstance(result, dict) and (result.get("proxy_forced") or not result.get("backend_stopped", True)):
                    exit_code = 1
            if lease is not None and lease.stream is not None:
                status("stopped" if not exit_code else "failed")
        except Exception as error:
            record_failure(logger, "cleanup_failed", error)
            exit_code = 1
        finally:
            if transport_lease is not None:
                transport_lease.close()
            if lease is not None:
                lease.close()
            logger.removeHandler(handler)
            handler.close()
    return exit_code
