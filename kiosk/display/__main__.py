"""Explicit preparation of an offline native view; no installation or autostart."""
import argparse
import json

from kiosk.publication.exporter import PackageError
from .session import install_for_display, prepare_active_view
from .cache import prepare_cached_view
from .coordinator import display_session, follow_publications


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--store', required=True)
    output = parser.add_mutually_exclusive_group(required=True)
    output.add_argument('--destination')
    output.add_argument('--cache')
    parser.add_argument('--package', help='Install a local verified package after cached-view preparation')
    parser.add_argument('--mode', choices=('kiosk', 'tv'), default='kiosk')
    parser.add_argument('--shell', help='Explicit local native EXE to run in this interactive session')
    parser.add_argument('--profile')
    parser.add_argument('--state')
    parser.add_argument('--watch', action='store_true', help='Watch local publication pointers while running')
    args = parser.parse_args()
    if args.package and not args.cache:
        parser.error('--package requires --cache')
    if any((args.shell, args.profile, args.state)) and not all((args.shell, args.profile, args.state, args.cache)):
        parser.error('--shell, --profile, --state and --cache are required together')
    if args.watch and not args.shell:
        parser.error('--watch requires --shell')
    try:
        if args.package:
            install_for_display(args.package, args.store, args.cache, mode=args.mode)
        elif args.cache and not args.shell:
            prepare_cached_view(args.store, args.cache, mode=args.mode)
        elif not args.shell:
            prepare_active_view(args.store, args.destination, mode=args.mode)
        if args.shell:
            with display_session(args.store, args.cache, args.state, args.profile, args.shell, mode=args.mode) as run:
                print(json.dumps({'result': 'ready', 'mode': args.mode, 'fallback': run.fallback}), flush=True)
                if args.watch:
                    for event in follow_publications(run):
                        print(json.dumps(event), flush=True)
                if run.process.wait() != 0:
                    raise PackageError('display_engine_exited')
            return 0
        print(json.dumps({'result': 'prepared', 'mode': args.mode}))
        return 0
    except PackageError as error:
        print(json.dumps({'result': 'error', 'code': str(error)}))
        return 1
    except KeyboardInterrupt:
        return 130


if __name__ == '__main__':
    raise SystemExit(main())
