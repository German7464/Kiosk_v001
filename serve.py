import argparse

from kiosk.config import Config
from kiosk.server import reset_admin_password_command, run_waitress


def build_parser():
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default=Config.SERVER_HOST)
    parser.add_argument("--port", type=int, default=Config.SERVER_PORT)
    parser.add_argument("--reset-admin-password", action="store_true")
    return parser


def parse_args(argv=None):
    return build_parser().parse_args(argv)


def main(argv=None):
    args = parse_args(argv)

    if args.reset_admin_password:
        reset_admin_password_command()
        return

    run_waitress(host=args.host, port=args.port)


if __name__ == "__main__":
    main()
