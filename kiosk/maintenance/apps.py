"""Build a configured Flask application for one side from a JSON config file.

The same loader is used by the disposable lab tools, the supported host and the
frozen service packages, so a Combined or Separated deployment runs exactly the
application that the tests exercise. No development server and no localhost
trust shortcut is involved.
"""
from __future__ import annotations

import json
from pathlib import Path


def config(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))


def _paths(value, keys):
    for key in keys:
        if key in value and value[key] is not None:
            value[key] = Path(value[key])
    return value


def content_application(path):
    from kiosk.app import create_app
    value = config(path)
    value.pop('TLS', None)
    _paths(value, ('INSTANCE_DIR', 'DATABASE_PATH', 'PUBLIC_UPLOAD_DIR',
                   'PRIVATE_UPLOAD_DIR', 'DEVICE_DELIVERY_ROOT'))
    workspace = value.get('ROAMING_WORKSPACE') or {}
    _paths(workspace, ('database', 'policy'))
    if workspace:
        value['ROAMING_WORKSPACE'] = workspace
    return create_app(value)


def maintenance_application(path):
    from . import create_maintenance_app
    value = config(path)
    # Public certificate paths also drive expiry diagnostics. Responses never
    # expose the key path or private material.
    _paths(value, ('MAINTENANCE_DATABASE', 'MAINTENANCE_SECRETS_DIR',
                   'MAINTENANCE_ROOT_PUBLIC', 'MAINTENANCE_ROOT_POLICY',
                   'CONTENT_CA_FILE'))
    return create_maintenance_app(value)


def application(path, side):
    if side == 'content':
        return content_application(path)
    if side == 'maintenance':
        return maintenance_application(path)
    raise ValueError('side_refused')
