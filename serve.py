import argparse
import sys

from kiosk.config import Config
from kiosk.server import reset_admin_password_command, run_waitress_with_launcher, setup_admin_command


def build_parser():
    parser = argparse.ArgumentParser(allow_abbrev=False)
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=Config.SERVER_PORT)
    parser.add_argument("--no-client", action="store_true")
    parser.add_argument("--https-config")
    open_group = parser.add_mutually_exclusive_group()
    open_group.add_argument("--open-kiosk", action="store_true")
    open_group.add_argument("--open-tv", action="store_true")
    credential_group = parser.add_mutually_exclusive_group()
    credential_group.add_argument("--reset-admin-password", action="store_true")
    credential_group.add_argument("--setup-admin", action="store_true")
    return parser


def parse_args(argv=None):
    parser = build_parser()
    arguments = list(sys.argv[1:] if argv is None else argv)
    args = parser.parse_args(arguments)
    if args.https_config and (args.setup_admin or args.reset_admin_password or any(
        item in {"--host", "--port"} or item.startswith(("--host=", "--port=")) for item in arguments
    )):
        parser.error("--https-config cannot be combined with --host, --port, or credential commands.")
    return args


def main(argv=None):
    args = parse_args(argv)

    if args.https_config:
        from kiosk.transport.runtime import run_https

        return run_https(args.https_config, path="/tv" if args.open_tv else "/kiosk", auto_launch=not args.no_client)

    if args.reset_admin_password:
        return reset_admin_password_command()

    if args.setup_admin:
        return setup_admin_command()

    if args.open_kiosk:
        run_waitress_with_launcher(host=args.host, port=args.port, path="/kiosk", auto_launch=not args.no_client)
        return

    if args.open_tv:
        run_waitress_with_launcher(host=args.host, port=args.port, path="/tv", auto_launch=not args.no_client)
        return

    run_waitress_with_launcher(host=args.host, port=args.port, path="/kiosk", auto_launch=not args.no_client)


if __name__ == "__main__":
    sys.exit(main())
