import argparse
import os
import sys
from pathlib import Path

from kiosk.launcher.installation import require_administrator
from kiosk.launcher.storage import Storage, atomic_json, common_root, import_mvp, read_profile


def main():
    parser = argparse.ArgumentParser(allow_abbrev=False)
    commands = parser.add_subparsers(dest="command", required=True)
    importer = commands.add_parser("import-mvp")
    importer.add_argument("--source", required=True)
    importer.add_argument("--source-stopped", action="store_true", required=True)
    provisioning = commands.add_parser("provision-https")
    provisioning.add_argument("--generation", required=True)
    provisioning.add_argument("--fingerprint", required=True)
    provisioning.add_argument("--origin")
    provisioning.add_argument("--listener")
    remover = commands.add_parser("uninstall")
    remover.add_argument("--confirm-uninstall", action="store_true", required=True)
    remover.add_argument("--delete-data", action="store_true")
    remover.add_argument("--device-id")
    recovery = commands.add_parser("restore-config")
    recovery.add_argument("--device-id", required=True)
    commands.add_parser("setup-admin")
    commands.add_parser("reset-admin-password")
    args = parser.parse_args()
    require_administrator()
    if getattr(sys, "frozen", False):
        os.environ["PATH"] = str(Path(sys.executable).parent / "runtime/powershell") + os.pathsep + os.environ.get("PATH", "")
    storage = Storage(common_root())
    if args.command == "import-mvp":
        import_mvp(args.source, storage, source_stopped=args.source_stopped)
    elif args.command == "provision-https":
        from kiosk.launcher.provisioning import provision_https

        provision_https(storage, args.generation, args.fingerprint, args.origin, args.listener)
    elif args.command == "uninstall":
        from kiosk.launcher.installation import uninstall

        uninstall(delete_data=args.delete_data, device_id=args.device_id)
    elif args.command == "restore-config":
        from kiosk.launcher.installation import service_state

        if service_state() not in {"absent", "stopped"}:
            raise RuntimeError("Stop the service before restoring configuration.")
        previous = read_profile(storage.profile.with_suffix(".previous.json"))
        if previous["device_id"] != args.device_id:
            raise ValueError("Configuration restoration requires the exact previous device UUID.")
        if storage.profile.exists():
            damaged = storage.profile.with_suffix(".retained.json")
            if damaged.exists():
                raise ValueError("Preserve the previous retained configuration before restoring another one.")
            content = storage.profile.read_bytes()
            if len(content) > 16384:
                raise ValueError("Review the oversized configuration before restoring it.")
            with damaged.open("xb") as stream:
                stream.write(content)
        atomic_json(storage.profile, previous)
    elif args.command in {"setup-admin", "reset-admin-password"}:
        from kiosk.app import create_app
        from kiosk.core.credentials import admin_password_command

        return admin_password_command(lambda: create_app(storage.app_config()), setup=args.command == "setup-admin")
    print("Operation completed. Open Launcher to review configuration and start the service.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
