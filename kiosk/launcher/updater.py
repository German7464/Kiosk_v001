"""Supported offline server update: one recoverable, exclusively-owned transaction.

The installed server's ``KioskMaintenance.exe upgrade <package>`` uses this module.
Inno Setup is the file-installation layer (it unpacks the new binary tree into a
staging directory); this module owns the security and safety decisions around it.

One update is a single transaction with an exclusive lock, a transaction-specific
journal/result/helper/snapshot and a continuously inherited Windows kernel lock.
Phases are bounded and every failure is either fully rolled back to the previous
service state or reported honestly; interrupted directory transitions are recovered
by retaining ambiguous trees for local recovery rather than assuming success:

    verify signature + hashes + compatibility   (before any installer code runs)
    snapshot the verified payload (protected)   (the bytes actually executed)
    quiesce writes (stop the service)           (record + restore prior state)
    back up durable data with ACLs + secrets    (verified before the old point is
                                                 discarded; no blind cleanup)
    stage the new binaries with Inno Setup      (separate from the running tree)
    activate with an atomic directory swap      (old -> Kiosk.old, staging -> Kiosk)
    verify version + service health + identity  (no silent failure)

Application data (``C:\\ProgramData\\Kiosk``) stays separate from binaries
(``C:\\Program Files\\Kiosk``); the installer never touches the data root.
"""
from __future__ import annotations

import json
from kiosk.core import update_owner
import os
import shutil
import sqlite3
import subprocess
import time
from contextlib import closing
from pathlib import Path

from kiosk.core.update import DATA_SCHEMA_VERSION, new_transaction_id, rollback_directories, verify_package, verify_snapshot
from kiosk.launcher.installation import binary_directory, control_service, require_administrator, service_state
from kiosk.launcher.storage import Storage, atomic_json, common_root, safe_local_path
from kiosk.launcher.windows import SERVICE_NAME

PRODUCT = "kiosk-server"
TRUSTED_KEY_NAME = "update-verification.pem"
HELPER_NAME = "KioskUpdateHelper.exe"
INSTALLER_ARGS = ("/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART")
EPHEMERAL_DIRS = ("logs", "temp", "updates", "status")
LOCK_NAME = "upgrade.lock"
TIME_FORMAT = "%Y-%m-%dT%H:%M:%SZ"


def _now():
    return time.strftime(TIME_FORMAT, time.gmtime())


def trusted_public_key(storage):
    path = storage.directory("config") / TRUSTED_KEY_NAME
    if not path.is_file() or path.is_symlink():
        raise ValueError("No update verification key is installed. Trust the pilot public key once before updating.")
    data = path.read_bytes()
    if len(data) > 4096:
        raise ValueError("The update verification key is too large.")
    return data.decode("ascii")


def installed_version(storage):
    manifest = binary_directory() / "package.json"
    if manifest.is_file():
        try:
            data = json.loads(manifest.read_text(encoding="utf-8"))
            if isinstance(data.get("version"), str):
                return data["version"]
        except (ValueError, OSError):
            pass
    runtime = storage.directory("status") / "runtime.json"
    if runtime.is_file():
        try:
            data = json.loads(runtime.read_text(encoding="utf-8"))
            if isinstance(data.get("version"), str):
                return data["version"]
        except (ValueError, OSError):
            pass
    return "0.0.0"


def _read_runtime(storage):
    path = storage.directory("status") / "runtime.json"
    if not path.is_file():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (ValueError, OSError):
        return {}


def _content_version(storage):
    path = storage.app_config()["DATABASE_PATH"]
    if not path.is_file():
        return None
    try:
        with closing(sqlite3.connect(path.as_uri() + "?mode=ro", uri=True)) as database:
            row = database.execute("SELECT value FROM settings WHERE key = 'content_version'").fetchone()
            return int(row[0]) if row else None
    except (sqlite3.Error, ValueError, TypeError):
        return None


def identity(storage):
    from kiosk.launcher.storage import read_profile

    return {"device_id": read_profile(storage.profile)["device_id"],
            "content_version": _content_version(storage)}


def data_schema(storage):
    """Installed durable-data schema version (0 when no database exists yet)."""
    path = storage.app_config()["DATABASE_PATH"]
    if not path.is_file():
        return 0
    try:
        with closing(sqlite3.connect(path.as_uri() + "?mode=ro", uri=True)) as database:
            row = database.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='content_versions'"
            ).fetchone()
            return DATA_SCHEMA_VERSION if row else 0
    except sqlite3.Error:
        return 0


def _updates_dir(storage):
    return storage.directory("updates")


def _lock_path(storage):
    return _updates_dir(storage) / LOCK_NAME


def _lock_data(storage):
    path = _lock_path(storage)
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else None
    except (ValueError, OSError):
        return None


def _release_lock(storage):
    _lock_path(storage).unlink(missing_ok=True)


def _tx_path(storage, tx_id, kind):
    updates = _updates_dir(storage)
    return {
        "journal": updates / ("upgrade-%s.json" % tx_id),
        "result": updates / ("upgrade-%s.result" % tx_id),
        "request": updates / ("upgrade-%s.request" % tx_id),
        "helper_dir": updates / ("helper-%s" % tx_id),
        "snapshot_dir": updates / ("snapshot-%s" % tx_id),
    }[kind]


def _read_journal(storage, tx_id):
    path = _tx_path(storage, tx_id, "journal")
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else None
    except (ValueError, OSError):
        return None


def _write_journal(storage, tx_id, state):
    atomic_json(_tx_path(storage, tx_id, "journal"), state)


def _prior_service(journal):
    return journal.get("prior_service", "running")


def _service_state_safe():
    try:
        return service_state()
    except (RuntimeError, OSError):
        return "unavailable"


def _health_ok(storage, version, device_id):
    if _service_state_safe() != "running":
        return False
    runtime = _read_runtime(storage)
    return (runtime.get("state") == "running" and runtime.get("version") == version
            and runtime.get("device_id") == device_id and runtime.get("error") is None)


def _run_installer(installer, target_dir, log_path):
    command = [str(installer), *INSTALLER_ARGS, f"/DIR={target_dir}", f"/LOG={log_path}"]
    result = subprocess.run(command, capture_output=True, timeout=900)
    if result.returncode != 0:
        raise RuntimeError("The offline installer failed with exit code %d. See the install log." % result.returncode)


def verify_and_read(storage, package_dir, *, current_version=None):
    """Verify a package for this product and return (manifest, public_key_pem)."""
    public = trusted_public_key(storage)
    manifest = verify_package(package_dir, public, product=PRODUCT,
                              current_version=current_version if current_version is not None
                              else installed_version(storage))
    installer = manifest["files"]
    if len(installer) != 1:
        raise ValueError("A server update package must contain exactly one installer.")
    return manifest, public


def _check_data_schema(storage, manifest):
    declared = manifest.get("data_schema")
    if declared is None:
        return
    installed = data_schema(storage)
    if installed != 0 and declared != installed:
        raise ValueError(
            "The update package requires data schema %s but the installed data is schema %s; "
            "this offline update does not perform schema migration." % (declared, installed))


def _snapshot(storage, tx_id, package_dir, manifest, installer_name):
    snapshot = _tx_path(storage, tx_id, "snapshot_dir")
    snapshot.mkdir(parents=True)
    shutil.copy2(package_dir / installer_name, snapshot / installer_name)
    verify_snapshot(snapshot, manifest)
    return snapshot / installer_name


def _backup_data(storage, destination):
    destination = safe_local_path(destination)
    if destination.exists():
        raise ValueError("The backup destination already exists.")
    source = storage.root
    excluded = [str(source / name) for name in EPHEMERAL_DIRS]
    command = ["robocopy.exe", str(source), str(destination), "/E", "/COPY:DATS", "/DCOPY:DAT",
               "/XJ", "/R:1", "/W:1", "/NFL", "/NDL", "/NP", "/XD", *excluded]
    result = subprocess.run(command, capture_output=True, creationflags=subprocess.CREATE_NO_WINDOW, timeout=600)
    if result.returncode >= 8:
        raise RuntimeError("The data backup failed (robocopy exit %d)." % result.returncode)
    _verify_backup(storage, destination)


def _verify_backup(storage, destination):
    destination = safe_local_path(destination)
    for relative in ("config/device.json", "data/kiosk.sqlite", "secrets/session.key"):
        if not (destination / relative).is_file():
            raise RuntimeError("The data backup is incomplete (missing %s)." % relative)
    database = destination / "data" / "kiosk.sqlite"
    with closing(sqlite3.connect(database.as_uri() + "?mode=ro", uri=True)) as guard:
        if guard.execute("PRAGMA integrity_check").fetchall() != [("ok",)]:
            raise RuntimeError("The backed-up database failed integrity verification.")


def _discard_previous_restore(storage, tx_id):
    live = binary_directory()
    for name in ("Kiosk.old",):
        candidate = live.with_name(name)
        if candidate.exists():
            os.replace(candidate, candidate.with_name(candidate.name + ".retained-" + tx_id))
    backup = storage.root.with_name(storage.root.name + ".backup")
    if backup.exists():
        os.replace(backup, backup.with_name(backup.name + ".retained-" + tx_id))


def _rollback(storage, tx_id, journal, prior_service):
    live = binary_directory()
    backup_bin = safe_local_path(journal.get("backup_bin") or str(live.with_name("Kiosk.old")))
    if journal.get("handoff_prepared") and backup_bin.is_dir():
        control_service("stop")
        if live.exists():
            discarded = live.with_name("Kiosk.bad")
            discarded = discarded.with_name(discarded.name + "." + tx_id)
            rollback_directories(live, backup_bin, discarded)
        else:
            os.replace(str(backup_bin), str(live))
    if prior_service == "running":
        control_service("start")
        deadline = time.monotonic() + 90
        while time.monotonic() < deadline:
            if _restored(storage, journal):
                return
            time.sleep(1)
        raise RuntimeError("Previous server application health was not restored.")
    else:
        if _service_state_safe() != "stopped":
            control_service("stop")
        if not _restored(storage, journal):
            raise RuntimeError("Previous stopped-service state was not restored.")


def _activated(storage, journal):
    if installed_version(storage) != journal.get("to_version"):
        return False
    if _prior_service(journal) == "stopped":
        return _service_state_safe() == "stopped"
    return _health_ok(storage, journal.get("to_version"), journal.get("device_id"))


def _restored(storage, journal):
    return (journal.get("prior_digest") is not None and update_owner.tree_digest(binary_directory()) == journal["prior_digest"]) and installed_version(storage) == journal.get("from_version") and (_health_ok(storage, journal.get("from_version"), journal.get("device_id")) if _prior_service(journal) == "running" else _service_state_safe() == "stopped")


def _finalize(storage, tx_id, journal, outcome):
    # Failed/unverified rollback is never a cleanup authorization. Retain all
    # copies, diagnostics and the journal; a later update must not erase them.
    journal = dict(journal)
    if outcome == "rolled_back" and not _restored(storage, journal):
        outcome = "recovery-required"
    if outcome not in {"committed", "rolled_back"}:
        outcome = "recovery-required"
    journal["state"] = outcome
    journal["updated_at"] = _now()
    _write_journal(storage, tx_id, journal)
    if outcome == "recovery-required":
        raise RuntimeError("Update recovery-required; all transaction material is retained for local recovery.")
    # Retain transaction artifacts and binary/data restore points, including bad
    # and staging trees. A later verified update archives old trees by tx id.
    from kiosk.launcher.storage import atomic_json
    atomic_json(_lock_path(storage).with_suffix(".last.json"), journal)
    _release_lock(storage)


def _recover_transition(storage, tx_id, journal):
    # Directory presence alone proves neither restoration nor application health.
    _finalize(storage, tx_id, journal, "recovery-required")


@update_owner.guarded((lambda storage: _lock_path(storage)))
def _recover_interrupted(storage):
    """Recover any completed or interrupted transaction; raise when not recoverable."""
    lock = _lock_data(storage)
    if lock is None or not lock.get("transaction_id"):
        if _lock_path(storage).exists():
            raise RuntimeError("Unreadable transaction metadata; recovery-required; original file retained.")
        return
    tx_id = lock["transaction_id"]
    journal = _read_journal(storage, tx_id) or {}
    result_file = _tx_path(storage, tx_id, "result")
    result = result_file.read_text(encoding="utf-8").strip() if result_file.is_file() else ""

    if result == "committed" or journal.get("state") == "committed":
        if _activated(storage, journal):
            _finalize(storage, tx_id, journal, "committed")
            return
        _finalize(storage, tx_id, journal, "recovery-required")
    if result.startswith("error:") or journal.get("state") == "recovery-required":
        _finalize(storage, tx_id, journal, "recovery-required")
    if result == "rolled_back":
        _finalize(storage, tx_id, journal, "rolled_back")
        raise RuntimeError("A previous update was rolled back: %s" % (result or "unknown"))
    _recover_transition(storage, tx_id, journal)


def _acquire_lock(storage):
    update_owner.acquire(_lock_path(storage))
    try:
        if _lock_path(storage).exists():
            _recover_interrupted.__wrapped__(storage)
        tx_id = new_transaction_id()
        _lock_path(storage).write_text(json.dumps({"transaction_id": tx_id, "pid": os.getpid(),
                                     "started_at": _now()}), encoding="utf-8")
        return tx_id
    except BaseException:
        update_owner.release(_lock_path(storage))
        raise


def upgrade(storage, package_dir):
    """Perform the supported offline server update. Raises on any failure.

    The running maintenance executable cannot rename its own directory, so the
    final activation is handed to a self-contained helper that runs from the
    updates staging location; this command stages everything and returns once the
    helper is launched. Use ``upgrade_status``/the ``journey`` command to confirm.
    """
    require_administrator()
    if not getattr(__import__("sys"), "frozen", False):
        raise ValueError("Update requires the packaged KioskMaintenance.exe.")
    package_dir = safe_local_path(package_dir)
    tx_id = _acquire_lock(storage)
    journal = None
    try:
        manifest, _ = verify_and_read(storage, package_dir)
        version = manifest["version"]
        installer_name = next(iter(manifest["files"]))
        from_kind = identity(storage)
        _check_data_schema(storage, manifest)

        live = binary_directory()
        staging = live.with_name("Kiosk.staging")
        backup_bin = live.with_name("Kiosk.old")
        backup_data = storage.root.with_name(storage.root.name + ".backup")
        backup_pending = storage.root.with_name(storage.root.name + ".backup.pending")
        helper_dir = _tx_path(storage, tx_id, "helper_dir")
        helper = helper_dir / HELPER_NAME
        result_file = _tx_path(storage, tx_id, "result")
        request_file = _tx_path(storage, tx_id, "request")

        journal = {"schema_version": 1, "product": PRODUCT, "state": "prepared",
                   "transaction_id": tx_id,
                   "from_version": installed_version(storage), "to_version": version,
                   "package": str(package_dir), "prior_digest": update_owner.tree_digest(live),
                   "staging_bin": str(staging), "backup_bin": str(backup_bin),
                   "backup_data": str(backup_data),
                   "device_id": from_kind["device_id"], "content_version": from_kind["content_version"],
                   "started_at": _now(), "prior_service": _service_state_safe(), "error": None}
        _write_journal(storage, tx_id, journal)

        # Snapshot the verified payload into a protected, transaction-owned
        # directory and re-verify the bytes that will actually be executed.
        installer = _snapshot(storage, tx_id, package_dir, manifest, installer_name)

        # Quiesce writes and back up durable data (ACLs + secrets preserved).
        control_service("stop")
        journal["state"] = "stopped"
        _write_journal(storage, tx_id, journal)
        _backup_data(storage, backup_pending)
        journal["state"] = "backed_up"
        _write_journal(storage, tx_id, journal)

        # Only now discard the previous restore point: a verified data backup of
        # the current state exists, and the live binaries are still the previous
        # version until the swap.
        _discard_previous_restore(storage, tx_id)
        os.replace(str(backup_pending), str(backup_data))

        if staging.exists():
            raise ValueError("The staging directory already exists; review it first.")
        _run_installer(installer, staging, storage.directory("updates") / ("installer-%s.log" % tx_id))

        helper_source = staging / HELPER_NAME
        if not helper_source.is_file():
            raise RuntimeError("The update helper is missing from the installed package.")
        helper_dir.mkdir(parents=True, exist_ok=True)
        shutil.copy2(helper_source, helper)
        journal["state"] = "staged"
        journal["handoff_prepared"] = True
        _write_journal(storage, tx_id, journal)

        request_file.write_text(
            "staging=%s\nlive=%s\nbackup=%s\nmode=service\nresult=%s\ntask=%s\n"
            "service=%s\nversion=%s\ndevice_id=%s\nruntime=%s\nprior_version=%s\nprior_service=%s\nmarker=%s\n" % (
                str(staging), str(live), str(backup_bin), str(result_file), "",
                SERVICE_NAME, version, from_kind["device_id"],
                str(storage.directory("status") / "runtime.json"), journal["from_version"],
                journal["prior_service"], str(live / "package.json")),
            encoding="utf-8")

        update_owner.handoff(_lock_path(storage), helper, request_file)
        return {"result": "staged", "transaction_id": tx_id,
                "from_version": journal["from_version"], "to_version": version,
                "note": "activation was handed to the detached helper; run upgrade-status or journey to confirm."}
    except BaseException as error:
        if journal is not None:
            journal["error"] = "%s: %s" % (type(error).__name__, error)
            _write_journal(storage, tx_id, journal)
            try:
                _rollback(storage, tx_id, journal, _prior_service(journal))
            except BaseException as rollback_error:
                journal["rollback_error"] = "%s: %s" % (type(rollback_error).__name__, rollback_error)
                journal["state"] = "recovery-required"
                _write_journal(storage, tx_id, journal)
                raise RuntimeError("Rollback failed; recovery-required; material retained.") from rollback_error
            _finalize(storage, tx_id, journal, "rolled_back")
        else:
            _release_lock(storage)
        raise
    finally:
        update_owner.release(_lock_path(storage))


@update_owner.guarded((lambda storage: _lock_path(storage)), status=True)
def upgrade_status(storage):
    """Report the outcome of a handed-off update, or the live health when idle."""
    lock = _lock_data(storage)
    runtime = _read_runtime(storage)
    if lock is None:
        if _lock_path(storage).exists():
            return {"state": "recovery-required", "note": "Unreadable transaction metadata retained; local recovery required."}
        last = _lock_path(storage).with_suffix(".last.json")
        if last.is_file():
            data = json.loads(last.read_text(encoding="utf-8"))
            return {"state": data["state"], "transaction_id": data["transaction_id"],
                    "from_version": data["from_version"], "to_version": data["to_version"],
                    "version": installed_version(storage), "application_ready":  _health_ok(storage, data.get("to_version"), data.get("device_id")),
                    "note": "Binary activation outcome; client operation requires a separate native launch check."}
        return {"state": "idle", "version": installed_version(storage)}
    tx_id = lock.get("transaction_id")
    journal = _read_journal(storage, tx_id) or {}
    result_file = _tx_path(storage, tx_id, "result")
    result = result_file.read_text(encoding="utf-8").strip() if result_file.is_file() else ""

    if result == "committed" or journal.get("state") == "committed":
        if _activated(storage, journal):
            _finalize(storage, tx_id, journal, "committed")
            return {"state": "committed", "from_version": journal.get("from_version"),
                    "to_version": journal.get("to_version"), "service": _service_state_safe(),
                    "version": _read_runtime(storage).get("version"),
                    "device_id": _read_runtime(storage).get("device_id")}
        return {"state": "recovery-required", "helper_result": result, "service": _service_state_safe(),
                "version": runtime.get("version"),
                "note": "the helper reported committed but the new server is not healthy"}
    if result.startswith("error:") or journal.get("state") == "recovery-required":
        journal["state"] = "recovery-required"
        _write_journal(storage, tx_id, journal)
        return {"state": "recovery-required", "helper_result": result,
                "transaction_id": tx_id, "note": "Recovery copies and diagnostics retained; local recovery required."}
    if result == "rolled_back" and not _restored(storage, journal):
        journal["state"] = "recovery-required"
        _write_journal(storage, tx_id, journal)
        return {"state": "recovery-required", "helper_result": result,
                "note": "Previous application/service restoration was not verified."}
    if result == "rolled_back":
        _finalize(storage, tx_id, journal, "rolled_back")
        return {"state": "rolled_back", "from_version": journal.get("from_version"),
                "to_version": journal.get("to_version"), "service": _service_state_safe(),
                "version": runtime.get("version")}
    try:
        _recover_transition(storage, tx_id, journal)
    except RuntimeError as error:
        return {"state": "recovery-required", "note": str(error), "service": _service_state_safe(),
                "version": runtime.get("version")}
    return {"state": "committed", "from_version": journal.get("from_version"),
            "to_version": journal.get("to_version"), "service": _service_state_safe(),
            "version": _read_runtime(storage).get("version"),
            "device_id": _read_runtime(storage).get("device_id")}


def trust_update_key(storage, key_file):
    """Install the pilot public verification key into protected storage (once)."""
    require_administrator()
    from kiosk.core.update_crypto import load_public_key, public_key_id

    key_file = safe_local_path(key_file)
    data = key_file.read_bytes()
    if len(data) > 4096:
        raise ValueError("The update verification key is too large.")
    key_id = public_key_id(load_public_key(data))
    storage.directory("config").mkdir(parents=True, exist_ok=True)
    target = storage.directory("config") / TRUSTED_KEY_NAME
    import tempfile

    descriptor, name = tempfile.mkstemp(prefix=".kiosk-key-", dir=target.parent)
    temporary = Path(name)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, target)
    finally:
        temporary.unlink(missing_ok=True)
    return key_id
