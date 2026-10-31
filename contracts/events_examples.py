"""Generate isolated public package cases and compare the reference verifier."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import sqlite3
import tempfile

from PIL import Image

from kiosk.publication.exporter import PackageError, export_events_package, verify_package
from kiosk.publication.renderer import build_view


EXPECTED = {
    'valid': 'ok', 'empty': 'ok', 'tampered': 'integrity_failure',
    'extra-file': 'inventory_mismatch', 'unsupported-contract': 'unsupported_client_contract',
    'unsafe-path': 'invalid_package', 'bad-public-data': 'invalid_public_data',
    'revision-mismatch': 'revision_mismatch',
    'missing-resource': 'reference_closure_failure',
}


def write_json(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, sort_keys=True,
                               separators=(',', ':')), encoding='utf-8')


def generate(output):
    output = Path(output)
    output.mkdir(parents=True, exist_ok=False)
    with tempfile.TemporaryDirectory(prefix='kiosk-contract-') as temporary:
        root = Path(temporary)
        uploads = root / 'uploads'
        uploads.mkdir()
        Image.new('RGB', (4, 4), 'blue').save(uploads / 'card.png')
        database = root / 'synthetic.sqlite'
        db = sqlite3.connect(database)
        try:
            db.executescript('''
                CREATE TABLE events (id INTEGER,title TEXT,short_description TEXT,
                    full_description TEXT,event_date TEXT,place TEXT,image_kiosk TEXT,
                    image_tv TEXT,image_thumb TEXT,sort_order INTEGER,status TEXT);
                CREATE TABLE tags (id INTEGER,name TEXT);
                CREATE TABLE event_tags (event_id INTEGER,tag_id INTEGER);
                CREATE TABLE settings (key TEXT,value TEXT);
                INSERT INTO events VALUES (1,'Synthetic — пример','Short','Public text',
                    NULL,'Test hall','/static/uploads/card.png',
                    '/static/uploads/card.png',NULL,0,'active');
                INSERT INTO tags VALUES (1,'Example');
                INSERT INTO event_tags VALUES (1,1);
                INSERT INTO settings VALUES ('content_version','1');
                INSERT INTO settings VALUES ('site_title','Synthetic contract fixture');
            ''')
            db.commit()
            resources = Path(__file__).resolve().parents[1] / 'kiosk'
            export_events_package(database, uploads, resources, output / 'valid')
            db.execute("UPDATE events SET status='hidden'")
            db.commit()
            export_events_package(database, uploads, resources, output / 'empty')
        finally:
            db.close()
    for case in EXPECTED.keys() - {'valid', 'empty'}:
        target = output / case
        shutil.copytree(output / 'valid', target)
        manifest_path = target / 'manifest.json'
        manifest = json.loads(manifest_path.read_text(encoding='utf-8'))
        if case == 'tampered':
            with (target / 'data/events.json').open('ab') as stream:
                stream.write(b' ')
        elif case == 'extra-file':
            (target / 'extra.txt').write_text('synthetic', encoding='utf-8')
        elif case == 'unsupported-contract':
            manifest['resource_contract'] = 2
        elif case == 'unsafe-path':
            manifest['files'][0]['path'] = '../escape'
        elif case == 'bad-public-data':
            path = target / 'data/events.json'
            data = json.loads(path.read_text(encoding='utf-8'))
            data['content_version'] = True
            write_json(path, data)
            entry = next(e for e in manifest['files'] if e['path'] == 'data/events.json')
            entry.update(size=path.stat().st_size, sha256=hashlib.sha256(path.read_bytes()).hexdigest())
        elif case == 'revision-mismatch':
            manifest['revision'] = '2'
        elif case == 'missing-resource':
            name = 'resources/translations/de.json'
            (target / name).unlink()
            manifest['files'] = [e for e in manifest['files'] if e['path'] != name]
        write_json(manifest_path, manifest)
    write_json(output / 'expected.json', EXPECTED)
    results = {}
    for case, expected in EXPECTED.items():
        try:
            verify_package(output / case)
            actual = 'ok'
        except PackageError as error:
            actual = str(error)
        results[case] = actual
        if actual != expected:
            raise AssertionError(f'{case}: expected {expected}, got {actual}')
    for mode in ('kiosk', 'tv'):
        build_view(output / 'valid', output / ('view-' + mode), mode=mode)
    write_json(output / 'results.json', results)
    print(json.dumps({'cases': len(results), 'passed': True, 'views': ['kiosk', 'tv']}))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', required=True, type=Path)
    generate(parser.parse_args().output)
