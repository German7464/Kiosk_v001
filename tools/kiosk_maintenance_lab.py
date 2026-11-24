"""Disposable Maintenance lab: create/run Combined or Separated services.

Example (local acceptance, two isolated HTTPS origins on one OS):

    python tools/kiosk_maintenance_lab.py create --root C:/KioskMaintLab \
      --content-origin https://127.0.0.1:24443 \
      --maintenance-origin https://127.0.0.1:25443 \
      --admin-password-env KIOSK_MAINT_ADMIN_PASSWORD

No retained installation, OS clock or existing trust is touched.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path


def config(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))


def content_application(path):
    from kiosk.maintenance.apps import content_application as build
    return build(path)


def maintenance_application(path):
    from kiosk.maintenance.apps import maintenance_application as build
    return build(path)


def serve(path, kind, host, port):
    value = config(path)
    tls = value.get('TLS') or {}
    app = content_application(path) if kind == 'content' else maintenance_application(path)
    app.run(host=host, port=port, debug=False, threaded=True,
            ssl_context=(tls['cert'], tls['key']))


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='command', required=True)
    create = commands.add_parser('create')
    create.add_argument('--root', required=True, type=Path)
    create.add_argument('--mode', choices=('combined', 'separated'), default='combined')
    create.add_argument('--content-origin', required=True)
    create.add_argument('--maintenance-origin', required=True)
    create.add_argument('--group', required=True)
    create.add_argument('--admin', default='admin')
    create.add_argument('--admin-password-env', default='KIOSK_MAINT_ADMIN_PASSWORD')
    create.add_argument('--node', default='n1')
    create.add_argument('--counterpart', default='')
    run = commands.add_parser('serve')
    run.add_argument('--config', required=True, type=Path)
    run.add_argument('--kind', choices=('content', 'maintenance'), required=True)
    run.add_argument('--host', default='127.0.0.1')
    run.add_argument('--port', type=int, required=True)
    args = parser.parse_args(argv)
    if args.command == 'create':
        password = os.environ.get(args.admin_password_env, '')
        if len(password) < 12:
            parser.error('Set a 12+ character disposable admin password in the named environment variable.')
        from kiosk.maintenance.setup import create_lab
        result = create_lab(args.root, mode=args.mode, content_origin=args.content_origin,
                            maintenance_origin=args.maintenance_origin, group_id=args.group,
                            admin_user=args.admin, admin_password=password,
                            maintenance_node=args.node, content_node=args.node,
                            counterpart=args.counterpart)
        print(json.dumps(result, indent=2))
        return 0
    serve(args.config, args.kind, args.host, args.port)
    return 0


if __name__ == '__main__':
    sys.exit(main())
