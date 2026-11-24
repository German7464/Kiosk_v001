"""Emit public content-progress-v1 contract/vectors, without any installation data."""
import argparse
import hashlib
import json
from pathlib import Path


def vectors():
    base = dict(version=1, device_id='device-public', group_id='group-public', generation=1,
                package_id='a' * 64, attempt=100, sequence=100, state='waiting',
                completed_bytes=0, total_bytes=1024, error='none')
    accepts = [dict(base, state=state, sequence=100+i, completed_bytes=1024 if i >= 2 else 0)
               for i, state in enumerate(('waiting', 'downloading', 'downloaded', 'verified'))]
    accepts += [dict(base, state='error', error='connection'),
                dict(base, state='incompatible', error='requires_update', total_bytes=0)]
    rejects = [dict(name=name, body={**base, **change}, error=error) for name, change, error in (
        ('bool-version', {'version': True}, 'unsupported_version'),
        ('unknown-version', {'version': 2}, 'unsupported_version'),
        ('negative-bytes', {'completed_bytes': -1}, 'invalid_progress'),
        ('oversize-bytes', {'total_bytes': 201326593}, 'invalid_progress'),
        ('bytes-over-total', {'completed_bytes': 1025}, 'invalid_progress'),
        ('false-download', {'state': 'downloaded'}, 'invalid_progress'),
        ('false-activation', {'state': 'activated'}, 'invalid_progress'),
        ('error-detail', {'state': 'error', 'error': 'C:/private'}, 'invalid_progress'),
        ('missing-error', {'state': 'error'}, 'invalid_progress'),
        ('bool-sequence', {'sequence': True}, 'invalid_progress'),
        ('old-sequence', {'sequence': 99}, 'invalid_progress'),
        ('huge-generation', {'generation': 2**63}, 'invalid_progress'),
        ('uppercase-hash', {'package_id': 'A'*64}, 'invalid_digest'))]
    rejects += [{'name': 'extra-field', 'body': {**base, 'secret': 'never-send'}, 'error': 'invalid_fields'}]
    return dict(contract='content-progress-v1', context={'device_id': base['device_id'],
        'group_id': base['group_id'], 'generation': 1, 'package_id': base['package_id']},
        accepts=accepts, rejects=rejects, ordering=[
            {'body': base, 'http': 200, 'state': 'recorded'},
            {'body': base, 'http': 200, 'state': 'duplicate'},
            {'body': dict(base, state='downloading', sequence=102, completed_bytes=512), 'http': 200, 'state': 'recorded'},
            {'body': dict(base, sequence=101), 'http': 200, 'state': 'superseded'},
            {'body': dict(base, sequence=102), 'http': 409, 'error': 'progress_conflict'},
            {'body': dict(base, sequence=103), 'http': 409, 'error': 'progress_conflict'},
            {'body': dict(base, sequence=104, device_id='foreign'), 'http': 403, 'error': 'binding_refused'},
            {'body': dict(base, sequence=104, generation=2), 'http': 409, 'error': 'assignment_changed'},
            {'body': dict(base, attempt=105, sequence=105), 'http': 200, 'state': 'recorded'}])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--destination', required=True, type=Path)
    args = parser.parse_args()
    args.destination.mkdir(parents=True, exist_ok=False)
    source = Path(__file__).resolve().parents[1] / 'kiosk/delivery/README.md'
    contract = source.read_text(encoding='utf-8').split('## Content-distribution monitoring contract', 1)[1].split('## Opt-in advisory', 1)[0]
    (args.destination/'README.md').write_text('## Content-distribution monitoring contract'+contract, encoding='utf-8')
    (args.destination/'vectors.json').write_text(json.dumps(vectors(), indent=2)+'\n', encoding='utf-8')
    lines = [hashlib.sha256(p.read_bytes()).hexdigest()+'  '+p.name for p in sorted(args.destination.iterdir())]
    (args.destination/'SHA256SUMS').write_text('\n'.join(lines)+'\n', encoding='ascii')
    print('\n'.join(lines))


if __name__ == '__main__':
    main()
