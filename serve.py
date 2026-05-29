import argparse

from kiosk.config import Config
from kiosk.server import reset_admin_password_command, run_waitress, run_waitress_with_launcher


def build_parser():
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default=Config.SERVER_HOST)
    parser.add_argument("--port", type=int, default=Config.SERVER_PORT)
    open_group = parser.add_mutually_exclusive_group()
    open_group.add_argument("--open-kiosk", action="store_true")
    open_group.add_argument("--open-tv", action="store_true")
    parser.add_argument("--reset-admin-password", action="store_true")
    return parser


def parse_args(argv=None):
    return build_parser().parse_args(argv)


def main(argv=None):
    args = parse_args(argv)

    if args.reset_admin_password:
        reset_admin_password_command()
        return

    if args.open_kiosk:
        run_waitress_with_launcher(host=args.host, port=args.port, path="/kiosk")
        return

    if args.open_tv:
        run_waitress_with_launcher(host=args.host, port=args.port, path="/tv")
        return

    run_waitress(host=args.host, port=args.port)


if __name__ == "__main__":
    main()
