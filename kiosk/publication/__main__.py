import argparse
import json

from .exporter import PackageError, export_events_package, verify_package


def main():
    parser = argparse.ArgumentParser(description='Export or verify a standalone Events preparation package.')
    sub = parser.add_subparsers(dest='command', required=True)
    export = sub.add_parser('export')
    for name in ('database', 'uploads', 'resources', 'destination'):
        export.add_argument('--' + name, required=True)
    verify = sub.add_parser('verify')
    verify.add_argument('directory')
    args = parser.parse_args()
    try:
        if args.command == 'export':
            manifest = export_events_package(args.database, args.uploads, args.resources, args.destination)
        else:
            manifest = verify_package(args.directory)
        print(json.dumps({'result': 'verified', 'revision': manifest['revision'], 'files': len(manifest['files'])}))
        return 0
    except PackageError as error:
        print(json.dumps({'result': 'error', 'code': str(error)}))
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
