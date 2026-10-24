import argparse
import sys


def main():
    parser = argparse.ArgumentParser(allow_abbrev=False)
    operations = parser.add_mutually_exclusive_group()
    for name in ("autostart", "configure", "start", "stop", "install"):
        operations.add_argument("--" + name, action="store_true")
    args = parser.parse_args()
    from kiosk.launcher.gui import elevate, run_gui
    from kiosk.launcher.windows import administrator

    operation = next((name for name in ("configure", "start", "stop", "install") if getattr(args, name)), None)
    if operation and not administrator():
        elevate(operation)
        return 0
    if args.start or args.stop:
        from tkinter import messagebox
        from kiosk.launcher.installation import control_service

        try:
            control_service("start" if args.start else "stop")
        except Exception as error:
            messagebox.showerror("Kiosk", str(error))
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

        messagebox.showerror("Kiosk", f"Операция не выполнена ({type(error).__name__}).\n{error}")
        sys.exit(1)
