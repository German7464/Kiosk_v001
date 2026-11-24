"""Explicit disposable-only Events baseline transition; never a live migration."""
import argparse
import base64
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from kiosk.publication.baseline import seed
from kiosk.publication.workspace import Workspace


def main():
    parser = argparse.ArgumentParser(description=__doc__, allow_abbrev=False)
    parser.add_argument('--config', required=True, type=Path)
    parser.add_argument('--package', required=True, type=Path)
    parser.add_argument('--expected-package', required=True)
    parser.add_argument('--confirm-disposable', action='store_true')
    args = parser.parse_args()
    if not args.confirm_disposable:
        parser.error('--confirm-disposable is required; retained/live installations are excluded')
    config = json.loads(args.config.read_text())['ROAMING_WORKSPACE']
    path = Path(config['database'])
    if not path.is_file():
        parser.error('An existing empty disposable workspace is required')
    workspace = Workspace(path, base64.b64decode(config['root_spki'], validate=True),
                          config['group_id'], config['origin'])
    result = seed(workspace, args.package, args.expected_package, confirm_disposable=True)
    print(json.dumps(result, sort_keys=True))


if __name__ == '__main__':
    main()
