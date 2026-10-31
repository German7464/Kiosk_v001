"""Build/run a disposable loopback-only A01 Chrome acceptance fixture.

--build DIR writes a source bundle ZIP. --build-exe DIR builds only this helper.
Double-clicking the fixture EXE starts it; open printed loopback URLs manually.
No browser launch, service, product database, certificate or account operations.
"""
import argparse
import hashlib
import json
from pathlib import Path
import secrets
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import zipfile


def resource_root():
    if getattr(sys, '_MEIPASS', None):
        return Path(sys._MEIPASS)
    directory = Path(__file__).resolve().parent
    return directory if (directory / 'kiosk').is_dir() else directory.parent


def build(destination, executable=False):
    destination = Path(destination).resolve()
    destination.mkdir(parents=True, exist_ok=False)
    root = resource_root()
    names = ('templates/base.html', 'templates/kiosk_events.html', 'static/css/base.css',
             'static/js/kiosk_events.js', 'translations/en.json')
    for name in names:
        target = destination / 'kiosk' / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(root / 'kiosk' / name, target)
    shutil.copyfile(Path(__file__), destination / 'check_kiosk_recovery.py')
    manifest = {str(p.relative_to(destination)).replace('\\', '/'): hashlib.sha256(p.read_bytes()).hexdigest()
                for p in destination.rglob('*') if p.is_file()}
    (destination / 'source-hashes.json').write_text(json.dumps(manifest, indent=2), encoding='utf-8')
    if executable:
        subprocess.run([sys.executable, '-m', 'PyInstaller', '--noconfirm', '--onefile', '--console',
                        '--name', 'KioskRecoveryFixture', '--distpath', str(destination / 'dist'),
                        '--workpath', str(destination / 'build'), '--specpath', str(destination),
                        '--add-data', str(destination / 'kiosk') + ';kiosk',
                        str(destination / 'check_kiosk_recovery.py')], check=True)
    archive = destination.with_suffix('.zip')
    with zipfile.ZipFile(archive, 'x', zipfile.ZIP_DEFLATED) as output:
        files = [destination / 'dist' / 'KioskRecoveryFixture.exe', destination / 'source-hashes.json'] if executable else [p for p in destination.rglob('*') if p.is_file()]
        for path in files:
            output.write(path, str(path.relative_to(destination)))
    print(archive)
    print('SHA256', hashlib.sha256(archive.read_bytes()).hexdigest())


def create_fixture(output, port):
    from flask import Flask, abort, jsonify, redirect, render_template, request
    root = resource_root() / 'kiosk'
    app = Flask(__name__, template_folder=str(root / 'templates'), static_folder=str(root / 'static'))
    token = secrets.token_hex(24)
    lock = threading.Lock()
    state = {'offline': True, 'version': 1, 'late_once': False, 'active': 0, 'maximum_active': 0, 'html_requests': 0}
    log = output / 'requests.jsonl'
    translations = json.loads((root / 'translations/en.json').read_text(encoding='utf-8'))

    @app.before_request
    def restrict():
        if request.remote_addr not in ('127.0.0.1', '::1') or request.host != f'127.0.0.1:{port}':
            abort(403)
        if request.method == 'POST' and (request.form.get('token') != token or request.headers.get('Origin') not in (None, f'http://127.0.0.1:{port}')):
            abort(403)
        request.started = time.monotonic()
        with lock:
            state['active'] += 1
            state['maximum_active'] = max(state['maximum_active'], state['active'])

    @app.after_request
    def record(response):
        with lock:
            if hasattr(request, 'started'):
                state['active'] -= 1
                with log.open('a', encoding='utf-8') as handle:
                    handle.write(json.dumps({'path': request.path, 'method': request.method, 'status': response.status_code,
                        'elapsed': round(time.monotonic()-request.started, 4), 'version': state['version'],
                        'active': state['active']})+'\n')
            response.headers['Cache-Control'] = 'no-store'
        return response

    @app.get('/kiosk', endpoint='kiosk_home')
    def home():
        return redirect('/kiosk/events')

    @app.get('/kiosk/events')
    def display():
        with lock:
            state['html_requests'] += 1
        return render_template('kiosk_events.html', settings={}, active_language='en',
                               t=lambda key: translations.get(key, key), csrf_token=lambda: 'synthetic-fixture')

    @app.get('/api/<name>')
    def api(name):
        if name not in ('version', 'events', 'tags'):
            abort(404)
        with lock:
            offline, version = state['offline'], state['version']
            late = name == 'events' and state['late_once']
            if late:
                state['late_once'] = False
        if offline:
            return jsonify(error='synthetic outage'), 503
        if late:
            time.sleep(13)
        if name == 'version':
            return jsonify(content_version=version)
        if name == 'tags':
            return jsonify(tags=[])
        return jsonify(events=[{'id': 1, 'title': f'A01 FIXTURE GENERATION {version}', 'event_date': '2026-10-28',
            'short_description': 'Synthetic isolated content; no reload required', 'full_description': '',
            'place': 'Disposable fixture', 'image_kiosk': None, 'tags': []}])

    @app.route('/control', methods=['GET', 'POST'])
    def control():
        if request.method == 'POST':
            action = request.form.get('action')
            with lock:
                if action == 'offline': state['offline'] = True
                elif action == 'recover': state['offline'] = False
                elif action == 'next': state['version'] += 1
                elif action == 'late':
                    state['offline'] = False
                    state['version'] += 1
                    state['late_once'] = True
                else: abort(400)
            return redirect('/control')
        with lock:
            snapshot = dict(state)
        buttons = ''.join(f'<button name="action" value="{a}">{a}</button> ' for a in ('offline', 'recover', 'next', 'late'))
        return f'<!doctype html><title>A01 fixture control</title><h1>A01 disposable fixture</h1><pre>{json.dumps(snapshot, indent=2)}</pre><form method="post"><input type="hidden" name="token" value="{token}">{buttons}</form><p>Open /kiosk/events once in another tab. Refresh this control page for counters. Late delays one events response for 13 seconds.</p>'
    return app


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--build', type=Path)
    parser.add_argument('--build-exe', type=Path)
    parser.add_argument('--port', type=int, default=8766)
    args = parser.parse_args()
    if args.build and args.build_exe:
        parser.error('Choose one build mode')
    if args.build or args.build_exe:
        build(args.build or args.build_exe, bool(args.build_exe))
        return
    if not 1024 <= args.port <= 65535:
        parser.error('Use an unprivileged TCP port')
    output = Path(tempfile.mkdtemp(prefix='KioskA01-'))
    app = create_fixture(output, args.port)
    (output / 'identity.json').write_text(json.dumps({'port': args.port, 'source_js_sha256': hashlib.sha256((resource_root() / 'kiosk/static/js/kiosk_events.js').read_bytes()).hexdigest()}, indent=2), encoding='utf-8')
    print(f'Control http://127.0.0.1:{args.port}/control\nDisplay http://127.0.0.1:{args.port}/kiosk/events\nEvidence {output}\nStop with Ctrl+C. No browser is opened automatically.', flush=True)
    from waitress import serve
    serve(app, host='127.0.0.1', port=args.port, threads=8, connection_limit=32, channel_timeout=20)


if __name__ == '__main__':
    main()
