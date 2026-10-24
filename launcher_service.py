import argparse
import threading

from kiosk.launcher.storage import Storage


def main():
    parser = argparse.ArgumentParser(allow_abbrev=False)
    parser.add_argument("--console-root")
    args = parser.parse_args()
    if args.console_root:
        from kiosk.launcher.runtime import supervise

        stopped = threading.Event()
        try:
            return supervise(Storage(args.console_root), stopped)
        except KeyboardInterrupt:
            stopped.set()
            return 1
    from kiosk.launcher.service import dispatch

    dispatch()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
