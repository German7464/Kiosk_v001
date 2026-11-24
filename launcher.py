import argparse
import sys


def main():
    parser = argparse.ArgumentParser(allow_abbrev=False)
    operations = parser.add_mutually_exclusive_group()
    for name in ("autostart", "configure", "start", "stop", "install"):
        operations.add_argument("--" + name, action="store_true")
    operations.add_argument("--upgrade", metavar="PACKAGE")
    args = parser.parse_args()
    from kiosk.launcher.gui import elevate, run_gui
    from kiosk.launcher.windows import administrator

    operation = next((name for name in ("configure", "start", "stop", "install") if getattr(args, name)), None)
    if operation and not administrator():
        elevate(operation)
        return 0
    if args.upgrade:
        from kiosk.launcher.gui import elevate_upgrade
        from kiosk.launcher.windows import administrator

        if not administrator():
            elevate_upgrade(args.upgrade)
            return 0
        from kiosk.launcher.storage import Storage, atomic_json, common_root
        from kiosk.launcher.updater import upgrade

        storage = Storage(common_root())
        report = {}
        try:
            result = upgrade(storage, args.upgrade)
            report = {"result": result.get("result"), "to_version": result.get("to_version"),
                      "from_version": result.get("from_version"),
                      "transaction_id": result.get("transaction_id")}
            code = 0
        except Exception as error:
            report = {"error": type(error).__name__, "message": str(error)}
            code = 1
        try:
            atomic_json(storage.directory("updates") / "upgrade-command.json", report)
        except Exception:
            pass
        return code
    if args.start or args.stop:
        from tkinter import messagebox
        from kiosk.launcher.installation import control_service

        try:
            control_service("start" if args.start else "stop")
        except Exception as error:
            from kiosk.launcher.errors import access_message

            messagebox.showerror("Kiosk", access_message(error, "system"))
            return 1
        return 0
    if args.install:
        from kiosk.launcher.installation import install

        install()
        return 0
    run_gui(autostart=args.autostart, configure=args.configure)
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as error:
        from tkinter import messagebox
        from kiosk.launcher.errors import access_message

        messagebox.showerror("Kiosk", access_message(error, "system"))
        sys.exit(1)
