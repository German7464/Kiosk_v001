import argparse

from kiosk.config import Config
from kiosk.server import reset_admin_password_command, run_waitress_with_launcher


def build_parser():
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=Config.SERVER_PORT)
    parser.add_argument("--no-client", action="store_true")
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
        run_waitress_with_launcher(host=args.host, port=args.port, path="/kiosk", auto_launch=not args.no_client)
        return

    if args.open_tv:
        run_waitress_with_launcher(host=args.host, port=args.port, path="/tv", auto_launch=not args.no_client)
        return

    run_waitress_with_launcher(host=args.host, port=args.port, path="/kiosk", auto_launch=not args.no_client)


if __name__ == "__main__":
    main()
