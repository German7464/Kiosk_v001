import argparse

from kiosk.server import reset_admin_password_command, run_waitress


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--reset-admin-password", action="store_true")
    args = parser.parse_args()

    if args.reset_admin_password:
        reset_admin_password_command()
        return

    run_waitress()


if __name__ == "__main__":
    main()
