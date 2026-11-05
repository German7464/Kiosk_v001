"""Isolated Events lab, with existing Waitress/Caddy and no working-data writes."""
import argparse
from contextlib import closing
from datetime import datetime, timezone
import json
from pathlib import Path
import secrets
import sqlite3
import threading
import time

from waitress import serve

from kiosk.app import create_app
from kiosk.core.credentials import save_admin_password
from kiosk.delivery.protocol import PROFILE, encode, sha
from kiosk.delivery.publication import publish
from kiosk.publication.exporter import export_events_package


def lab_app(root):
    root = Path(root).absolute()
    if not (root / 'server/public.json').is_file() or not root.is_relative_to(Path('logs').absolute()):
        raise ValueError('Use a prepared disposable logs lab')
    instance = root / 'instance'
    app = create_app({'INSTANCE_DIR': instance, 'DATABASE_PATH': instance / 'kiosk.sqlite',
                      'PRIVATE_UPLOAD_DIR': instance / 'uploads', 'PUBLIC_UPLOAD_DIR': root / 'uploads',
                      'STATIC_FOLDER': root, 'DEVICE_DELIVERY_ROOT': root / 'server'})
    password_file = root / 'admin-private/admin-password.txt'
    if not password_file.exists():
        password_file.write_text(secrets.token_urlsafe(32), encoding='utf-8')
        save_admin_password(app, password_file.read_text(), setup=True)
        now = datetime.now(timezone.utc).isoformat()
        with closing(sqlite3.connect(app.config['DATABASE_PATH'])) as db:
            db.execute("INSERT INTO events(title,full_description,status,created_at,updated_at) VALUES (?,?,?,?,?)",
                       ('Laboratory Events A', 'Server-authorized offline Events publication.', 'active', now, now))
            db.commit()
    return app


def refresh(app, root):
    state = app.extensions['device_delivery']
    with closing(sqlite3.connect(app.config['DATABASE_PATH'])) as db:
        revision = db.execute("SELECT value FROM settings WHERE key='content_version'").fetchone()[0]
    with state.connection() as db:
        assigned = db.execute('SELECT package_id FROM assignments WHERE profile=?', (PROFILE,)).fetchone()
    if assigned:
        old = json.loads((state.root / 'publications' / assigned['package_id'] / 'delivery.json').read_bytes())
        if old['revision'] == revision:
            return
    import tempfile
    with tempfile.TemporaryDirectory(prefix='export-', dir=root) as folder:
        package = Path(folder) / 'package'
        export_events_package(app.config['DATABASE_PATH'], app.config['PUBLIC_UPLOAD_DIR'], app.config['RESOURCE_DIR'] / 'kiosk', package)
        metadata = publish(state, package)
    generation = state.assign(PROFILE, metadata['package_id'], sha(encode(metadata)))
    (root / 'public/capability.json').write_bytes(encode({'renderer': metadata['renderer']['build_id']}))
    print('Assigned Events revision', metadata['revision'], 'generation', generation, flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', required=True, type=Path)
    parser.add_argument('--backend-port', type=int, default=8765)
    parser.add_argument('--prepare-only', action='store_true')
    args = parser.parse_args()
    app = lab_app(args.root)
    refresh(app, args.root)
    if args.prepare_only:
        return
    def worker():
        while True:
            time.sleep(2)
            try:
                refresh(app, args.root)
            except Exception as error:
                # No paths, request bodies, native credentials or private data in this log.
                print('Publication deferred:', type(error).__name__, flush=True)
    threading.Thread(target=worker, name='lab-publication', daemon=True).start()
    serve(app, host='127.0.0.1', port=args.backend_port, threads=4,
          max_request_body_size=2 * 1024 * 1024, trusted_proxy='127.0.0.1', trusted_proxy_count=1,
          trusted_proxy_headers={'x-forwarded-for', 'x-forwarded-proto', 'x-forwarded-host'},
          clear_untrusted_proxy_headers=True)


if __name__ == '__main__':
    main()
