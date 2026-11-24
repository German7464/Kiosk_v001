"""Password-protected single-administrator backup and public LAN renewal."""
import argparse
import getpass
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from kiosk.maintenance.offline import backup, renew
from kiosk.delivery.protocol import encode


def main():
    parser = argparse.ArgumentParser(description=__doc__, allow_abbrev=False)
    parser.add_argument('operation', choices=('backup', 'renew'))
    parser.add_argument('--staged-lab', type=Path)
    parser.add_argument('--backup', type=Path, required=True)
    parser.add_argument('--request', type=Path)
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    password = getpass.getpass('Recovery backup password: ')
    try:
        if args.operation == 'backup':
            if not args.staged_lab:
                parser.error('--staged-lab is required')
            if getpass.getpass('Confirm recovery password: ') != password:
                raise ValueError('password_mismatch')
            result = backup(args.staged_lab, args.backup, password)
        else:
            if not args.request or not args.output:
                parser.error('--request and --output are required')
            request = json.loads(args.request.read_text())
            print('Recover retained administrator device:', request.get('request', {}).get('device_id', 'invalid'))
            if input('Compare the device fingerprint; type RECOVER: ') != 'RECOVER':
                raise ValueError('administrator_confirmation_required')
            result = renew(args.backup, password, request, int(time.time()), confirm=True)
            with args.output.open('xb') as stream:
                stream.write(encode(result))
            result = {'written': True, 'private_material_transferred': False}
        print(json.dumps(result, sort_keys=True))
        return 0
    except (OSError, ValueError, KeyError, TypeError):
        print('Offline operation refused; preserve existing files. No private material logged.')
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
