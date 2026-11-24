"""Per-user offline client update (KioskConnect) as one recoverable transaction.

Mirrors the server updater without service coordination: the control window (or
``KioskConnect.exe --upgrade``) verifies the signed package, snapshots the payload,
stages the new binary tree with Inno Setup, then hands the atomic swap to the
self-contained helper under the current user token. The helper waits for the
initiating process to exit, swaps the binary tree and verifies the version marker.
The user explicitly reopens the client; binary activation is not application readiness.
The data root (``%LOCALAPPDATA%\\KioskConnect``) is separate from
the binaries and is never touched, so device identity, saved state and credentials
are preserved.
"""
from __future__ import annotations

import json
from kiosk.core import update_owner
import os
import shutil
import subprocess
import time
from pathlib import Path

from kiosk.core.update import new_transaction_id, rollback_directories, verify_package, verify_snapshot
from kiosk.version import VERSION

PRODUCT = "kiosk-connect"
TRUSTED_KEY_NAME = "update-verification.pem"
VERSION_MARKER = "version.json"
HELPER_NAME = "KioskUpdateHelper.exe"
INSTALLER_ARGS = ("/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART")
LOCK_NAME = "update.lock"
TIME_FORMAT = "%Y-%m-%dT%H:%M:%SZ"


def _now():
    return time.strftime(TIME_FORMAT, time.gmtime())


def app_root():
    local = os.environ.get("LOCALAPPDATA")
    if not local:
        raise RuntimeError("Windows LocalAppData is unavailable.")
    return Path(local) / "Programs" / "KioskConnectApp"


def data_root():
    local = os.environ.get("LOCALAPPDATA")
    if not local:
        raise RuntimeError("Windows LocalAppData is unavailable.")
    return Path(local) / "KioskConnect"


def trusted_key():
    path = data_root() / TRUSTED_KEY_NAME
    if not path.is_file() or path.is_symlink():
        raise ValueError("No update verification key is installed for this client.")
    data = path.read_bytes()
    if len(data) > 4096:
        raise ValueError("The update verification key is too large.")
    return data.decode("ascii")


def installed_version():
    path = app_root() / VERSION_MARKER
    if not path.is_file():
        return "0.0.0"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data["version"] if isinstance(data.get("version"), str) else "0.0.0"
    except (ValueError, OSError):
        return "0.0.0"


def verify(package_dir):
    manifest = verify_package(package_dir, trusted_key(), product=PRODUCT,
                              current_version=installed_version())
    return manifest


def _run_installer(installer, target_dir, log_path):
    result = subprocess.run([str(installer), *INSTALLER_ARGS, f"/DIR={target_dir}", f"/LOG={log_path}"],
                            capture_output=True, timeout=900)
    if result.returncode != 0:
        raise RuntimeError("The client installer failed with exit code %d." % result.returncode)


def _lock_path():
    return data_root() / LOCK_NAME


def _lock_data():
    path = _lock_path()
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else None
    except (ValueError, OSError):
        return None


def _release_lock():
    _lock_path().unlink(missing_ok=True)


def _tx_path(tx_id, kind):
    root = data_root()
    return {
        "journal": root / ("update-%s.json" % tx_id),
        "result": root / ("update-%s.result" % tx_id),
        "request": root / ("update-%s.request" % tx_id),
        "helper_dir": root / ("update-helper-%s" % tx_id),
        "snapshot_dir": root / ("update-snapshot-%s" % tx_id),
    }[kind]


def _read_journal(tx_id):
    path = _tx_path(tx_id, "journal")
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else None
    except (ValueError, OSError):
        return None


def _write_journal(tx_id, state):
    from kiosk.launcher.storage import atomic_json

    atomic_json(_tx_path(tx_id, "journal"), state)


def _snapshot(tx_id, package_dir, manifest, installer_name):
    snapshot = _tx_path(tx_id, "snapshot_dir")
    snapshot.mkdir(parents=True)
    shutil.copy2(Path(package_dir) / installer_name, snapshot / installer_name)
    verify_snapshot(snapshot, manifest)
    return snapshot / installer_name


def _rollback(tx_id, journal):
    live = app_root()
    backup = live.with_name("KioskConnectApp.old")
    if journal.get("handoff_prepared") and backup.is_dir():
        if live.exists():
            discarded = live.with_name("KioskConnectApp.bad")
            discarded = discarded.with_name(discarded.name + "." + tx_id)
            rollback_directories(live, backup, discarded)
        else:
            os.replace(str(backup), str(live))



def _restored(journal):
    return (journal.get("prior_digest") is not None and update_owner.tree_digest(app_root()) == journal["prior_digest"]) and installed_version() == journal.get("from_version")


def _finalize(tx_id, journal, outcome):
    # Failed/unverified rollback is never a cleanup authorization. Retain all
    # copies, diagnostics and the journal; a later update must not erase them.
    journal = dict(journal)
    if outcome == "rolled_back" and not _restored(journal):
        outcome = "recovery-required"
    if outcome not in {"committed", "rolled_back"}:
        outcome = "recovery-required"
    journal["state"] = outcome
    journal["updated_at"] = _now()
    _write_journal(tx_id, journal)
    if outcome == "recovery-required":
        raise RuntimeError("Update recovery-required; all transaction material is retained for local recovery.")
    # Retain transaction artifacts and binary/data restore points, including bad
    # and staging trees. A later verified update archives old trees by tx id.
    from kiosk.launcher.storage import atomic_json
    atomic_json(_lock_path().with_suffix(".last.json"), journal)
    _release_lock()


def _recover_transition(tx_id, journal):
    # Directory presence alone proves neither restoration nor application health.
    _finalize(tx_id, journal, "recovery-required")


@update_owner.guarded((lambda: _lock_path()))
def _recover_interrupted():
    lock = _lock_data()
    if lock is None or not lock.get("transaction_id"):
        if _lock_path().exists():
            raise RuntimeError("Unreadable transaction metadata; recovery-required; original file retained.")
        return
    tx_id = lock["transaction_id"]
    journal = _read_journal(tx_id) or {}
    result_file = _tx_path(tx_id, "result")
    result = result_file.read_text(encoding="utf-8").strip() if result_file.is_file() else ""

    if result == "committed" or journal.get("state") == "committed":
        if installed_version() == journal.get("to_version"):
            _finalize(tx_id, journal, "committed")
            return
        _finalize(tx_id, journal, "recovery-required")
    if result.startswith("error:") or journal.get("state") == "recovery-required":
        _finalize(tx_id, journal, "recovery-required")
    if result == "rolled_back":
        _finalize(tx_id, journal, "rolled_back")
        raise RuntimeError("A previous update was rolled back: %s" % (result or "unknown"))
    _recover_transition(tx_id, journal)


def _acquire_lock():
    update_owner.acquire(_lock_path())
    try:
        if _lock_path().exists():
            _recover_interrupted.__wrapped__()
        tx_id = new_transaction_id()
        _lock_path().write_text(json.dumps({"transaction_id": tx_id, "pid": os.getpid(),
                                     "started_at": _now()}), encoding="utf-8")
        return tx_id
    except BaseException:
        update_owner.release(_lock_path())
        raise


def upgrade(package_dir, *, relaunch=True):
    """Perform the supported offline client update. Raises on any failure.

    The running client cannot rename its own directory, so the final activation is
    handed to the self-contained helper, which waits for this process to exit and
    release its files before swapping. The caller (UI or CLI) must exit promptly
    after this returns so the helper can proceed; completion is reported by the
    helper's result file, not by keeping the old executable alive.
    """
    package_dir = Path(os.path.abspath(package_dir))
    tx_id = _acquire_lock()
    journal = None
    try:
        manifest = verify(package_dir)
        version = manifest["version"]
        installer_name = next(iter(manifest["files"]))

        live = app_root()
        staging = live.with_name("KioskConnectApp.staging")
        backup = live.with_name("KioskConnectApp.old")
        helper_dir = _tx_path(tx_id, "helper_dir")
        helper = helper_dir / HELPER_NAME
        result_file = _tx_path(tx_id, "result")
        request_file = _tx_path(tx_id, "request")

        journal = {"schema_version": 1, "product": PRODUCT, "state": "prepared",
                   "transaction_id": tx_id, "from_version": installed_version(),
                   "to_version": version, "prior_digest": update_owner.tree_digest(live), "package": str(package_dir),
                   "staging": str(staging), "backup": str(backup),
                   "started_at": _now(), "error": None}
        _write_journal(tx_id, journal)

        installer = _snapshot(tx_id, package_dir, manifest, installer_name)

        if staging.exists():
            raise ValueError("A previous client staging directory exists; review it first.")
        data_root().mkdir(parents=True, exist_ok=True)
        _run_installer(installer, staging, data_root() / ("installer-%s.log" % tx_id))

        helper_source = staging / HELPER_NAME
        if not helper_source.is_file():
            raise RuntimeError("The client update helper is missing from the installed package.")
        helper_dir.mkdir(parents=True, exist_ok=True)
        shutil.copy2(helper_source, helper)

        # The previous restore point (KioskConnectApp.old) is no longer needed once
        # the new version is staged; clear it so the helper can move the live tree.
        if backup.exists():
            os.replace(backup, backup.with_name(backup.name + ".retained-" + tx_id))

        journal["state"] = "staged"
        journal["handoff_prepared"] = True
        _write_journal(tx_id, journal)

        request_file.write_text(
            "staging=%s\nlive=%s\nbackup=%s\nmode=none\nresult=%s\ntask=\nversion=%s\nprior_version=%s\nmarker=%s\n" % (
                str(staging), str(live), str(backup), str(result_file), version,
                journal["from_version"], str(live / VERSION_MARKER)),
            encoding="utf-8")

        # No elevation or scheduled task. The UI explicitly requests reopening;
        # a committed binary activation does not assert application readiness.
        update_owner.handoff(_lock_path(), helper, request_file)
        return {"result": "staged", "transaction_id": tx_id,
                "from_version": journal["from_version"], "to_version": version,
                "backup": str(backup),
                "note": "Activation pending in your user context. Reopen KioskConnect after completion; no autostart is configured."}
    except BaseException as error:
        if journal is not None:
            journal["error"] = "%s: %s" % (type(error).__name__, error)
            _write_journal(tx_id, journal)
            try:
                _rollback(tx_id, journal)
            except BaseException as rollback_error:
                journal["rollback_error"] = "%s: %s" % (type(rollback_error).__name__, rollback_error)
                journal["state"] = "recovery-required"
                _write_journal(tx_id, journal)
                raise RuntimeError("Rollback failed; recovery-required; material retained.") from rollback_error
            _finalize(tx_id, journal, "rolled_back")
        else:
            _release_lock()
        raise
    finally:
        update_owner.release(_lock_path())


@update_owner.guarded((lambda: _lock_path()), status=True)
def upgrade_status():
    """Report the outcome of a handed-off client update, or idle when none pending."""
    lock = _lock_data()
    if lock is None:
        if _lock_path().exists():
            return {"state": "recovery-required", "note": "Unreadable transaction metadata retained; local recovery required."}
        last = _lock_path().with_suffix(".last.json")
        if last.is_file():
            data = json.loads(last.read_text(encoding="utf-8"))
            return {"state": data["state"], "transaction_id": data["transaction_id"],
                    "from_version": data["from_version"], "to_version": data["to_version"],
                    "version": installed_version(), "application_ready": False,
                    "note": "Binary activation outcome; client operation requires a separate native launch check."}
        return {"state": "idle", "version": installed_version()}
    tx_id = lock.get("transaction_id")
    journal = _read_journal(tx_id) or {}
    result_file = _tx_path(tx_id, "result")
    result = result_file.read_text(encoding="utf-8").strip() if result_file.is_file() else ""

    if result == "committed" or journal.get("state") == "committed":
        if installed_version() == journal.get("to_version"):
            _finalize(tx_id, journal, "committed")
            return {"state": "committed", "from_version": journal.get("from_version"),
                    "to_version": journal.get("to_version"), "version": installed_version()}
        return {"state": "recovery-required", "helper_result": result, "version": installed_version(),
                "note": "the helper reported committed but the new client was not confirmed"}
    if result.startswith("error:") or journal.get("state") == "recovery-required":
        journal["state"] = "recovery-required"
        _write_journal(tx_id, journal)
        return {"state": "recovery-required", "helper_result": result,
                "transaction_id": tx_id, "note": "Recovery copies and diagnostics retained; local recovery required."}
    if result == "rolled_back" and not _restored(journal):
        journal["state"] = "recovery-required"
        _write_journal(tx_id, journal)
        return {"state": "recovery-required", "helper_result": result,
                "note": "Previous application/service restoration was not verified."}
    if result == "rolled_back":
        _finalize(tx_id, journal, "rolled_back")
        return {"state": "rolled_back", "from_version": journal.get("from_version"),
                "to_version": journal.get("to_version"), "version": installed_version()}
    try:
        _recover_transition(tx_id, journal)
    except RuntimeError as error:
        return {"state": "recovery-required", "note": str(error), "version": installed_version()}
    return {"state": "committed", "from_version": journal.get("from_version"),
            "to_version": journal.get("to_version"), "version": installed_version()}


def current_package_version():
    """Return the running package version, or the default when unpackaged."""
    return VERSION
