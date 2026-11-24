"""Service host and installation commands for the Maintenance workflow.

One executable serves either side, so a Combined or Separated deployment runs the
same code with a different config and Windows service identity. Installation
commands are intentionally narrow and idempotence-hostile: they refuse to
overwrite an existing installation or service.
"""
from __future__ import annotations

import argparse
import base64
import json
import os
import secrets
import shutil
import sys
import threading
import time
from contextlib import contextmanager
from pathlib import Path

from . import deployment
from .deployment import DeploymentError
from .relocation import (RelocationError, export_maintenance, import_maintenance,
                         redeem_remote)
from .serve import Runtime, verify_caddy
from .store import MaintenanceError, MaintenanceStore


def _read(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))


def _passphrase(path):
    value = Path(path).read_text(encoding='utf-8').strip()
    if len(value) < 12:
        raise DeploymentError('relocation_passphrase_required')
    return value


def _rewrite_content_paths(config, root):
    config = dict(config)
    config['INSTANCE_DIR'] = str(root / 'content' / 'data' / 'instance')
    config['DATABASE_PATH'] = str(root / 'content' / 'data' / 'instance' / 'kiosk.sqlite')
    config['PUBLIC_UPLOAD_DIR'] = str(root / 'content' / 'data' / 'static' / 'uploads')
    config['PRIVATE_UPLOAD_DIR'] = str(root / 'content' / 'data' / 'instance' / 'uploads')
    config['DEVICE_DELIVERY_ROOT'] = str(root / 'content' / 'data' / 'delivery')
    workspace = dict(config['ROAMING_WORKSPACE'])
    workspace['database'] = str(root / 'content' / 'data' / 'workspace.sqlite')
    workspace['policy'] = str(root / 'public' / 'publisher-policy.json')
    config['ROAMING_WORKSPACE'] = workspace
    config['CONTENT_CA_FILE'] = str(root / 'public' / 'root-ca.pem')
    return config


def _rewrite_maintenance_paths(config, root):
    config = dict(config)
    config['MAINTENANCE_DATABASE'] = str(root / 'maintenance' / 'data' / 'maintenance.sqlite')
    config['MAINTENANCE_SECRETS_DIR'] = str(root / 'maintenance' / 'data' / 'secrets')
    config['MAINTENANCE_ROOT_PUBLIC'] = str(root / 'public' / 'publisher-public.json')
    config['MAINTENANCE_ROOT_POLICY'] = str(root / 'public' / 'publisher-policy.json')
    config['CONTENT_CA_FILE'] = str(root / 'public' / 'root-ca.pem')
    return config


def create_lab(args):
    """Provision a disposable installation, then leave root custody admin-only."""
    from .setup import create_lab as build
    root = Path(args.root).absolute()
    if root.exists() and any(item.name not in ('app', 'logs') for item in root.iterdir()):
        raise DeploymentError('setup_destination_exists')
    work = root / 'work' / 'lab'
    for part in ('app', 'public', 'admin-only', 'transfer', 'logs'):
        (root / part).mkdir(parents=True, exist_ok=True)
    tls = None
    if args.tls_content_cert:
        tls = {'ca': args.ca,
               'content': {'cert': args.tls_content_cert, 'key': args.tls_content_key},
               'maintenance': {'cert': args.tls_maintenance_cert,
                               'key': args.tls_maintenance_key}}
    created = build(work, mode=args.mode, content_origin=args.content_origin,
                    maintenance_origin=args.maintenance_origin, group_id=args.group,
                    admin_user=args.admin, admin_password=args.admin_password,
                    maintenance_node=args.node, content_node=args.node,
                    counterpart=args.counterpart, tls_material=tls)
    content = _read(created['content_config'])
    maintenance = _read(created['maintenance_config'])

    # Move the generated state into the supported per-side layout.
    for side in ('content', 'maintenance'):
        for part in ('config', 'data', 'logs', 'caddy', 'tls'):
            (root / side / part).mkdir(parents=True, exist_ok=True)
    shutil.move(str(work / 'content' / 'instance'), str(root / 'content' / 'data' / 'instance'))
    shutil.move(str(work / 'content' / 'delivery'), str(root / 'content' / 'data' / 'delivery'))
    shutil.move(str(work / 'content' / 'static'), str(root / 'content' / 'data' / 'static'))
    shutil.move(str(work / 'content' / 'workspace.sqlite'),
                str(root / 'content' / 'data' / 'workspace.sqlite'))
    shutil.move(str(work / 'maintenance' / 'secrets'),
                str(root / 'maintenance' / 'data' / 'secrets'))
    shutil.move(str(work / 'maintenance' / 'maintenance.sqlite'),
                str(root / 'maintenance' / 'data' / 'maintenance.sqlite'))
    for side, source in (('content', work / 'content' / 'tls'),
                         ('maintenance', work / 'maintenance' / 'tls')):
        for item in sorted(source.glob('*')):
            shutil.copy2(item, root / side / 'tls' / item.name)
    if tls:
        for side in ('content', 'maintenance'):
            shutil.copy2(tls[side]['cert'], root / side / 'tls' / 'cert.pem')
            shutil.copy2(tls[side]['key'], root / side / 'tls' / 'key.pem')
            # The edge must present leaf + issuer so a display can derive the
            # pinned issuer SPKI from the live chain.
            chain = (Path(tls[side]['cert']).read_text().rstrip() + '\n' +
                     Path(tls['ca']).read_text().rstrip() + '\n')
            (root / side / 'tls' / 'chain.pem').write_text(chain, encoding='utf-8')
    shutil.copy2(work / 'ca' / 'root-ca.pem', root / 'public' / 'root-ca.pem')
    shutil.copy2(work / 'authority' / 'public.json',
                 root / 'public' / 'publisher-public.json')
    shutil.copy2(work / 'authority' / 'policy.json',
                 root / 'public' / 'publisher-policy.json')
    # Only the encrypted authority file and its passphrase stay in admin-only.
    shutil.copytree(work / 'authority', root / 'admin-only' / 'authority')
    shutil.copy2(work / 'authority-password.txt',
                 root / 'admin-only' / 'authority-password.txt')
    shutil.copy2(work / 'group' / 'bootstrap.json', root / 'public' / 'bootstrap.json')

    content = _rewrite_content_paths(content, root)
    maintenance = _rewrite_maintenance_paths(maintenance, root)
    content['TLS'] = {'cert': str(root / 'content' / 'tls' / 'chain.pem'),
                      'key': str(root / 'content' / 'tls' / 'key.pem'),
                      'ca': str(root / 'public' / 'root-ca.pem'),
                      'chain': str(root / 'content' / 'tls' / 'chain.pem')}
    maintenance['TLS'] = {'cert': str(root / 'maintenance' / 'tls' / 'chain.pem'),
                         'key': str(root / 'maintenance' / 'tls' / 'key.pem'),
                         'ca': str(root / 'public' / 'root-ca.pem'),
                         'chain': str(root / 'maintenance' / 'tls' / 'chain.pem')}
    deployment.write_json(root / 'content' / 'config' / 'content.json', content)
    deployment.write_json(root / 'maintenance' / 'config' / 'maintenance.json', maintenance)

    # The content side needs its own ordinary administrator for device pairing;
    # it is a separate credential store from the Maintenance accounts.
    from .apps import content_application
    from kiosk.core.credentials import save_admin_password
    content_app = content_application(root / 'content' / 'config' / 'content.json')
    save_admin_password(content_app, args.admin_password, setup=True)

    # Fence the admin-staged store and export it for import under the service
    # identity, where the reviewer key is re-wrapped by that identity's DPAPI.
    staging_db = root / 'admin-only' / 'staging' / 'maintenance.sqlite'
    staging_db.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(root / 'maintenance' / 'data' / 'maintenance.sqlite'), str(staging_db))
    staging_secrets = root / 'admin-only' / 'staging' / 'secrets'
    shutil.move(str(root / 'maintenance' / 'data' / 'secrets'), str(staging_secrets))
    store = MaintenanceStore(staging_db)
    placement = store.placement()
    fence = store.fence('install', handoff=True)
    passphrase = secrets.token_urlsafe(32)
    (root / 'admin-only' / 'transfer-passphrase.txt').write_text(passphrase + '\n',
                                                                encoding='utf-8')
    bundle = root / 'transfer' / 'install.bundle'
    exported = export_maintenance(store, staging_secrets, bundle, passphrase,
                                  transfer=secrets.token_hex(32),
                                  cutover_secret=secrets.token_hex(32))
    install = dict(version=1, mode=args.mode, root=str(root),
                   content_origin=args.content_origin,
                   maintenance_origin=args.maintenance_origin,
                   group_id=args.group, admin=args.admin, node=args.node,
                   content_identity=args.content_identity,
                   maintenance_identity=args.maintenance_identity,
                   content_service=args.content_service,
                   maintenance_service=args.maintenance_service,
                   generation=placement['generation'], fence=fence,
                   transfer=exported['transfer'], bundle=str(bundle),
                   created=int(time.time()),
                   ca_sha256=_sha(root / 'public' / 'root-ca.pem'),
                   content_config_sha256=_sha(root / 'content' / 'config' / 'content.json'),
                   maintenance_config_sha256=_sha(root / 'maintenance' / 'config' /
                                                  'maintenance.json'))
    deployment.write_json(root / 'install.json', install)
    return install


def _sha(path):
    import hashlib
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def import_install(args):
    """Run under the Maintenance service identity: import and activate once."""
    from .relocation import peek_transfer
    install = _read(args.install)
    root = Path(install['root'])
    passphrase = _passphrase(args.passphrase_file)
    destination = (args.destination_id or install.get('destination_id') or
                   install['maintenance_origin'])
    store = MaintenanceStore(root / 'maintenance' / 'data' / 'maintenance.sqlite')
    secrets_dir = root / 'maintenance' / 'data' / 'secrets'
    secrets_dir.mkdir(parents=True, exist_ok=True)
    transfer = peek_transfer(args.bundle, passphrase)
    placement = store.placement()
    if placement is not None and placement['active'] and not placement['fence']:
        return dict(state='already_active', generation=placement['generation'],
                    origin=placement['origin'], destination=destination)
    if placement is not None and not placement['active'] and transfer.get('id') and \
            store_transfer(store, transfer['id']):
        # A previous attempt imported and possibly claimed already; resume
        # without duplicating rows. The claim is idempotent for this destination.
        result = dict(generation=placement['generation'], fence=placement['fence'],
                      transfer=transfer['id'], cutover_secret=transfer['secret'])
    else:
        result = import_maintenance(args.bundle, store, secrets_dir, passphrase,
                                    node=install['node'],
                                    origin=install['maintenance_origin'],
                                    counterpart=install['content_origin'],
                                    mode=install.get('mode', 'combined'))
    if args.claim_db:
        # Colocated cutover: the fenced source store is stopped but its database
        # is available under administrator custody, and the claim is still
        # single-use and atomic.
        claim = MaintenanceStore(args.claim_db).redeem_transfer(
            result['transfer'], result['cutover_secret'], destination)
    else:
        claim = redeem_remote(args.source_origin, args.ca, result['transfer'],
                              result['cutover_secret'], destination)
    store.claim_transfer(result['transfer'], destination)
    try:
        store.activate(result['generation'], result['fence'],
                       install['maintenance_origin'], transfer=result['transfer'])
    except MaintenanceError as error:
        if error.code != 'placement_generation_conflict':
            raise
    return dict(imported=result['generation'], transfer=result['transfer'],
                claim=claim['state'], destination=destination,
                origin=install['maintenance_origin'], placement=store.placement())


def store_transfer(store, identity):
    with store.connection(write=False) as db:
        return db.execute('SELECT 1 FROM transfers WHERE id=?', (identity,)).fetchone() \
            is not None


def export_side(args):
    install = _read(args.install)
    root = Path(install['root'])
    passphrase = _passphrase(args.passphrase_file)
    store = MaintenanceStore(root / 'maintenance' / 'data' / 'maintenance.sqlite')
    if args.fence:
        store.fence(args.fence, handoff=True)
    exported = export_maintenance(store, root / 'maintenance' / 'data' / 'secrets',
                                  args.out, passphrase)
    return exported


def _write_new(path, data, mode=0o600):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        raise DeploymentError('deployment_file_exists')
    if isinstance(data, str):
        data = data.encode('utf-8')
    path.write_bytes(data)
    try:
        os.chmod(path, mode)
    except OSError:
        pass
    return path


def stage_remote(args):
    """Prepare a fresh Maintenance root on another OS from a fenced source lab.

    The caller copies the frozen host bundle to ``<destination>/app/maintenance``
    first (the same package the source uses). This command only derives the
    destination-owned configuration, its own TLS leaf from the source issuer and
    the public trust/authority material; the encrypted data bundle is imported
    later with ``import-install`` under the destination service identity.
    """
    source = Path(args.root).absolute()
    destination = Path(args.destination_root).absolute()
    install = _read(source / 'install.json')
    maintenance = _read(source / 'maintenance' / 'config' / 'maintenance.json')
    origin = args.maintenance_origin or ''
    content_origin = args.content_origin or install['content_origin']
    from urllib.parse import urlsplit
    parsed = urlsplit(origin)
    if parsed.scheme != 'https' or not parsed.hostname or parsed.port is None:
        raise DeploymentError('destination_origin_refused')
    import ipaddress
    try:
        address = ipaddress.ip_address(parsed.hostname)
    except ValueError:
        raise DeploymentError('destination_origin_refused') from None
    if address.is_unspecified or address.is_multicast:
        raise DeploymentError('destination_origin_refused')
    tls_delegation = None
    if maintenance.get('LAN_TLS_ROOT_SPKI'):
        from kiosk.trust.crypto import load_private, spki_der
        from kiosk.trust.roles import make_delegation, delegation_payload, sign_delegation, verify_delegation
        from kiosk.trust.lifecycle import delegation_from_payload
        store = MaintenanceStore(maintenance['MAINTENANCE_DATABASE'])
        with store.connection(write=False) as db:
            row = db.execute('SELECT configuration FROM tls_issuer WHERE singleton=1').fetchone()
        if row is None:
            raise DeploymentError('tls_issuer_unavailable')
        old = json.loads(bytes(row['configuration']))['delegations']['maintenance']
        public_root = base64.b64decode(maintenance['LAN_TLS_ROOT_SPKI'], validate=True)
        if getattr(args, 'tls_delegation', None):
            tls_delegation = _read(args.tls_delegation)
        else:
            # Disposable create-lab setup keeps a staged offline-administrator
            # copy. A real separated/offline custody workflow supplies the public
            # signed destination delegation instead, never a runtime root key.
            group_file = source / 'work' / 'lab' / 'group' / 'group-key.pem'
            if not group_file.is_file():
                raise DeploymentError('signed_destination_tls_delegation_required')
            pem = group_file.read_text(encoding='ascii')
            if spki_der(load_private(pem)) != public_root:
                raise DeploymentError('group_authority_mismatch')
            original = old['payload']
            item = make_delegation(group_id=original['group_id'], server_id=original['server_id'],
                origin=origin, permitted_ip=[str(address)], permitted_dns=[],
                issuer_key_id=original['issuer_key_id'], issuer_spki_base64=original['issuer_spki_base64'],
                max_tls_validity_days=original['max_tls_validity_days'],
                issued_at=original['issued_at'], expires_at=original['expires_at'])
            tls_delegation = dict(payload=json.loads(delegation_payload(item)),
                                  signature=base64.b64encode(sign_delegation(pem, item)).decode('ascii'))
        item = delegation_from_payload(tls_delegation['payload'])
        verify_delegation(public_root, item, base64.b64decode(tls_delegation['signature'], validate=True))
        unchanged = ('group_id', 'server_id', 'issuer_key_id', 'issuer_spki_base64',
                     'scopes', 'max_tls_validity_days', 'issued_at', 'expires_at', 'version')
        if (any(tls_delegation['payload'][key] != old['payload'][key] for key in unchanged)
                or item.origin != origin or item.permitted_ip != (str(address),) or item.permitted_dns):
            raise DeploymentError('tls_relocation_scope_refused')
    ca_dir = source / 'work' / 'lab' / 'ca'
    issuer_cert = ca_dir / 'issuer.pem'
    issuer_key = ca_dir / 'issuer-key.pem'
    if not issuer_cert.is_file() or not issuer_key.is_file():
        raise DeploymentError('issuer_unavailable')
    from kiosk.trust.crypto import issue_tls_leaf
    cert, key = issue_tls_leaf(
        'Kiosk maintenance ' + (args.dest_node or 'n2'),
        issuer_cert.read_text(encoding='ascii'), issuer_key.read_text(encoding='ascii'),
        san_ips=[str(address)], san_dns=[], validity_days=7 if tls_delegation else 90)
    chain = cert.rstrip() + '\n' + issuer_cert.read_text(encoding='ascii').rstrip() + '\n'
    tls_dir = destination / 'maintenance' / 'tls'
    _write_new(tls_dir / 'cert.pem', cert, 0o644)
    _write_new(tls_dir / 'key.pem', key)
    _write_new(tls_dir / 'chain.pem', chain, 0o644)
    public = destination / 'public'
    if tls_delegation is not None:
        _write_new(public / 'maintenance-delegation.json', json.dumps(tls_delegation), 0o644)
    for name in ('root-ca.pem', 'publisher-public.json', 'publisher-policy.json',
                 'bootstrap.json'):
        origin_file = source / 'public' / name
        if origin_file.is_file():
            _write_new(public / name, origin_file.read_bytes(),
                       0o644 if name != 'publisher-policy.json' else 0o644)
    (destination / 'maintenance' / 'data').mkdir(parents=True, exist_ok=True)
    (destination / 'maintenance' / 'logs').mkdir(parents=True, exist_ok=True)
    value = dict(maintenance)
    if tls_delegation is not None:
        value['LAN_TLS_DELEGATION_OVERRIDE'] = str(public / 'maintenance-delegation.json')
    value.update(
        SECRET_KEY=secrets.token_hex(32),
        MAINTENANCE_DATABASE=str(destination / 'maintenance' / 'data' / 'maintenance.sqlite'),
        MAINTENANCE_SECRETS_DIR=str(destination / 'maintenance' / 'data' / 'secrets'),
        MAINTENANCE_ROOT_PUBLIC=str(public / 'publisher-public.json'),
        MAINTENANCE_ROOT_POLICY=str(public / 'publisher-policy.json'),
        MAINTENANCE_ORIGIN=origin,
        CONTENT_ORIGIN=content_origin,
        CONTENT_CA_FILE=str(public / 'root-ca.pem'),
        MAINTENANCE_PLACEMENT=dict(
            mode='separated', side='maintenance', node=args.dest_node or 'n2',
            origin=origin, counterpart=content_origin, generation=1),
        TLS=dict(cert=str(tls_dir / 'chain.pem'), key=str(tls_dir / 'key.pem'),
                 ca=str(public / 'root-ca.pem'), chain=str(tls_dir / 'chain.pem')))
    deployment.write_json(destination / 'maintenance' / 'config' / 'maintenance.json', value)
    record = dict(
        version=1, mode='separated', root=str(destination), content_origin=content_origin,
        maintenance_origin=origin, group_id=install.get('group_id'), admin=install.get('admin'),
        node=args.dest_node or 'n2', content_identity=install.get('content_identity',
                                                                 'LocalService'),
        maintenance_identity=install.get('maintenance_identity', 'NetworkService'),
        content_service=install.get('content_service'),
        maintenance_service=install.get('maintenance_service'), generation=1,
        fence=None, bundle=str(destination / 'maintenance' / 'data' / 'relocation.bundle'),
        created=int(time.time()), destination_id=args.destination_id or origin,
        ca_sha256=_sha(public / 'root-ca.pem'))
    deployment.write_json(destination / 'install.json', record)
    return dict(side='maintenance', root=str(destination), origin=origin,
                content_origin=content_origin, generation=1,
                executable_present=(destination / 'app' / 'maintenance' /
                                    'KioskMaintenanceHost.exe').is_file(),
                tls_cert_sha256=_sha(tls_dir / 'cert.pem'),
                ca_sha256=record['ca_sha256'])


def apply_acl(args):
    root = Path(args.root)
    return deployment.apply_layout_acls(root, content_identity=args.content_identity,
                                        maintenance_identity=args.maintenance_identity)


def install_service(args):
    root = Path(args.root)
    side = args.side
    identity = args.identity
    executable = root / 'app' / side / args.executable
    config = root / side / 'config' / (side + '.json')
    if not executable.is_file():
        raise DeploymentError('host_executable_missing')
    if not config.is_file():
        raise DeploymentError('side_config_missing')
    name = args.name
    deployment.service_create(
        name, executable,
        ['run', '--config', str(config), '--side', side, '--caddy',
         str(root / 'app' / side / 'caddy' / 'caddy.exe'),
         '--service-name', name,
         '--log', str(root / side / 'logs' / 'service.log')],
        identity, display=args.display or name,
        description=f'Kiosk {side} service ({args.mode} placement)')
    return dict(service=name, identity=identity,
                sid=deployment.service_sid(name), state=deployment.service_status(name))


def service_command(args):
    action = args.command
    if action == 'service-start':
        return dict(state=deployment.service_start(args.name))
    if action == 'service-stop':
        return dict(state=deployment.service_stop(args.name))
    if action == 'service-status':
        return dict(state=deployment.service_status(args.name))
    if action == 'service-delete':
        return dict(removed=deployment.service_delete(args.name))
    raise DeploymentError('service_command_refused')


# -- Windows service dispatcher --------------------------------------------

def _dispatch(runtime_args, name):
    import ctypes
    from ctypes import wintypes

    class ServiceStatus(ctypes.Structure):
        _fields_ = [(field, wintypes.DWORD) for field in
                    ('service_type', 'state', 'accepted', 'error', 'specific_error',
                     'checkpoint', 'wait_hint')]

    api = ctypes.WinDLL('advapi32', use_last_error=True)
    handler_type = ctypes.WINFUNCTYPE(wintypes.DWORD, wintypes.DWORD, wintypes.DWORD,
                                      ctypes.c_void_p, ctypes.c_void_p)
    main_type = ctypes.WINFUNCTYPE(None, wintypes.DWORD, ctypes.POINTER(wintypes.LPWSTR))

    class Entry(ctypes.Structure):
        _fields_ = [('name', wintypes.LPWSTR), ('main', main_type)]

    api.RegisterServiceCtrlHandlerExW.argtypes = [wintypes.LPCWSTR, handler_type,
                                                  ctypes.c_void_p]
    api.RegisterServiceCtrlHandlerExW.restype = wintypes.HANDLE
    api.SetServiceStatus.argtypes = [wintypes.HANDLE, ctypes.POINTER(ServiceStatus)]
    api.SetServiceStatus.restype = wintypes.BOOL
    api.StartServiceCtrlDispatcherW.argtypes = [ctypes.POINTER(Entry)]
    api.StartServiceCtrlDispatcherW.restype = wintypes.BOOL
    stopped = threading.Event()
    handle = None
    lock = threading.Lock()
    state = 2
    checkpoint = 0

    def report(value, error=0):
        nonlocal state, checkpoint
        with lock:
            state = value
            checkpoint = checkpoint + 1 if value in (2, 3) else 0
            status = ServiceStatus(0x10, value, 5 if value == 4 else 0, error, 0,
                                   checkpoint, 30000 if value in (2, 3) else 0)
            if not api.SetServiceStatus(handle, ctypes.byref(status)):
                raise ctypes.WinError(ctypes.get_last_error())

    @handler_type
    def control(code, event, data, context):
        if code in (1, 5):
            report(3)
            stopped.set()
        elif code == 4:
            report(state)
        return 0

    @main_type
    def main(count, arguments):
        nonlocal handle
        handle = api.RegisterServiceCtrlHandlerExW(name, control, None)
        if not handle:
            return
        report(2)
        runtime = None
        code, error = 0, 0
        try:
            runtime = Runtime(runtime_args['config'], runtime_args['side'],
                              caddy_path=runtime_args['caddy'])
            runtime.start()
            runtime.log_path = runtime.root / 'logs' / (runtime_args['side'] + '.log')
            if not runtime.wait_ready():
                raise RuntimeError('runtime_not_ready')
            report(4)
            while not stopped.wait(1):
                if runtime.edge_failed():
                    code, error = 1, 1066
                    break
        except Exception:
            import traceback
            traceback.print_exc()
            code, error = 1, 1066
        finally:
            if runtime is not None:
                runtime.stop()
            report(1, error)

    entries = (Entry * 2)(Entry(name, main), Entry(None, main_type()))
    if not api.StartServiceCtrlDispatcherW(entries):
        raise ctypes.WinError(ctypes.get_last_error())


def run_console(args):
    runtime = Runtime(args.config, args.side, caddy_path=args.caddy)
    runtime.start()
    runtime.wait_ready()
    print(json.dumps({'state': 'ready', 'origin': runtime.origin}), flush=True)
    try:
        while True:
            if runtime.edge_failed():
                raise RuntimeError('caddy_exited')
            time.sleep(1)
    except KeyboardInterrupt:
        return 0
    finally:
        runtime.stop()


def _emit(args, value):
    rendered = json.dumps(value, indent=2, default=str)
    if getattr(args, 'result', None):
        Path(args.result).write_text(rendered, encoding='utf-8')
    print(rendered)
    return rendered


def main(argv=None):
    """Entry point with bounded diagnostics for non-interactive service runs."""
    argv = list(sys.argv[1:] if argv is None else argv)
    result_path = _option(argv, '--result')
    log_path = _option(argv, '--log') or (result_path + '.log' if result_path else None)
    stream = None
    if log_path:
        try:
            Path(log_path).parent.mkdir(parents=True, exist_ok=True)
            stream = open(log_path, 'a', encoding='utf-8', buffering=1)
            sys.stdout = sys.stderr = stream
        except OSError:
            stream = None
    try:
        return _main(argv)
    except SystemExit:
        raise
    except BaseException as error:
        if result_path:
            try:
                Path(result_path).write_text(json.dumps(
                    {'error': 'host_failed',
                     'detail': (type(error).__name__ + ': ' + str(error))[:500]}),
                    encoding='utf-8')
            except OSError:
                pass
        raise
    finally:
        if stream is not None:
            try:
                stream.close()
            except OSError:
                pass
            sys.stdout, sys.stderr = sys.__stdout__, sys.__stderr__


def _option(argv, name):
    try:
        index = argv.index(name)
    except ValueError:
        return None
    return argv[index + 1] if index + 1 < len(argv) else None


def _main(argv=None):
    parser = argparse.ArgumentParser(allow_abbrev=False, description=__doc__)
    parser.add_argument('command', choices=(
        'create-lab', 'import-install', 'export-side', 'acl', 'install-service',
        'service-start', 'service-stop', 'service-status', 'service-delete',
        'stage-remote', 'trust-status', 'install-tls-issuer', 'export-lan-request', 'recover-lan', 'run'))
    parser.add_argument('--root')
    parser.add_argument('--mode', choices=('combined', 'separated'), default='combined')
    parser.add_argument('--content-origin')
    parser.add_argument('--maintenance-origin')
    parser.add_argument('--group')
    parser.add_argument('--admin', default='admin')
    parser.add_argument('--admin-password-env', default='KIOSK_MAINT_ADMIN_PASSWORD')
    parser.add_argument('--admin-password')
    parser.add_argument('--node', default='n1')
    parser.add_argument('--counterpart', default='')
    parser.add_argument('--content-identity', default='LocalService')
    parser.add_argument('--maintenance-identity', default='NetworkService')
    parser.add_argument('--content-service', default='KioskContentLab')
    parser.add_argument('--maintenance-service', default='KioskMaintenanceLab')
    parser.add_argument('--tls-content-cert')
    parser.add_argument('--tls-content-key')
    parser.add_argument('--tls-maintenance-cert')
    parser.add_argument('--tls-maintenance-key')
    parser.add_argument('--tls-delegation', help='Offline-root-signed public destination TLS delegation')
    parser.add_argument('--ca')
    parser.add_argument('--install')
    parser.add_argument('--bundle')
    parser.add_argument('--passphrase-file')
    parser.add_argument('--out')
    parser.add_argument('--source-origin')
    parser.add_argument('--claim-db')
    parser.add_argument('--destination-id')
    parser.add_argument('--destination-root')
    parser.add_argument('--dest-node', default='n2')
    parser.add_argument('--result')
    parser.add_argument('--log')
    parser.add_argument('--fence')
    parser.add_argument('--side', choices=('content', 'maintenance'))
    parser.add_argument('--identity', default='NetworkService')
    parser.add_argument('--name')
    parser.add_argument('--display', default='')
    parser.add_argument('--executable', default='KioskMaintenanceHost.exe')
    parser.add_argument('--config')
    parser.add_argument('--root-pin')
    parser.add_argument('--confirm', action='store_true')
    parser.add_argument('--fixture-now', type=int,
                        help='Diagnostic trust-status only; never changes service or OS time')
    parser.add_argument('--caddy')
    parser.add_argument('--service-name', default='KioskMaintenanceHost')
    parser.add_argument('--console', action='store_true')
    args = parser.parse_args(argv)

    if args.fixture_now is not None and args.command != 'trust-status':
        parser.error('--fixture-now is diagnostic only')
    if args.command == 'export-lan-request':
        if not all((args.config, args.out)):
            parser.error('--config and --out are required')
        from .apps import maintenance_application
        from .offline import export_request
        from kiosk.delivery.protocol import encode
        request = export_request(maintenance_application(args.config), args.admin, require_lan=True)
        with Path(args.out).open('xb') as output:
            output.write(encode(request))
        _emit(args, dict(version=1, exported=True, device_id=request['request']['device_id'],
                         expires=request['request']['expires']))
        return 0
    if args.command == 'recover-lan':
        if not all((args.config, args.bundle, args.root_pin, args.confirm)):
            parser.error('--config, --bundle, --root-pin and --confirm are required')
        from .apps import maintenance_application
        from .offline import apply_public
        if Path(args.bundle).stat().st_size > 131072:
            raise DeploymentError('recovery_bundle_limit')
        app = maintenance_application(args.config)
        result = apply_public(app, args.admin, _read(args.bundle), root_pin=args.root_pin, confirm=True)
        _emit(args, dict(version=1, recovered=result, delivery_pending=True, restart_required=True))
        return 0
    if args.command == 'install-tls-issuer':
        if not all((args.config, args.bundle, args.passphrase_file)):
            parser.error('--config, --bundle and --passphrase-file are required')
        from .relocation import _read_bundle
        from .tls import provision, TLSAuthority
        from kiosk.trust.crypto import load_private, spki_der, key_id
        from kiosk.trust.lifecycle import verify_group_window, delegation_from_payload
        from kiosk.trust.roles import verify_delegation
        from cryptography import x509
        config = _read(args.config)
        _, payload = _read_bundle(args.bundle, _passphrase(args.passphrase_file), limit=131072)
        if set(payload) != {'configuration', 'issuer_key'}:
            raise DeploymentError('tls_install_bundle_refused')
        public = payload['configuration']
        root = base64.b64decode(config['LAN_TLS_ROOT_SPKI'], validate=True)
        trust = verify_group_window(public['group_trust'], root)
        identity = _read(config['MAINTENANCE_ROOT_PUBLIC'])
        if (trust['group_id'] != identity['group_id'] or trust['servers'][0]['origin'] != config['CONTENT_ORIGIN']
                or not trust['issued_at'] <= int(time.time()) < trust['expires_at']):
            raise DeploymentError('tls_install_scope_refused')
        key = load_private(payload['issuer_key'])
        certificate = x509.load_pem_x509_certificate(public['issuer_certificate'].encode('ascii'))
        if (spki_der(key) != spki_der(certificate.public_key())
                or trust['servers'][0]['tls_issuer_spki_sha256'] != key_id(key)):
            raise DeploymentError('tls_install_key_refused')
        for side, origin in (('content', config['CONTENT_ORIGIN']), ('maintenance', config['MAINTENANCE_ORIGIN'])):
            delegated = public['delegations'][side]
            item = delegation_from_payload(delegated['payload'])
            verify_delegation(root, item, base64.b64decode(delegated['signature'], validate=True))
            if item.origin != origin or item.issuer_key_id != key_id(key):
                raise DeploymentError('tls_install_scope_refused')
        store = MaintenanceStore(config['MAINTENANCE_DATABASE'])
        if store.fenced():
            raise DeploymentError('tls_install_fenced')
        provision(store, config['MAINTENANCE_SECRETS_DIR'], payload['issuer_key'], public)
        _emit(args, dict(version=1, installed=True, issuer_spki_sha256=key_id(key)))
        return 0
    if args.command == 'trust-status':
        if not args.config:
            parser.error('--config is required')
        from . import cycle
        value = _read(args.config)
        path = Path(value['MAINTENANCE_DATABASE'])
        if not path.is_file():
            raise DeploymentError('diagnostic_database_missing')
        store = MaintenanceStore(path)
        _emit(args, dict(version=1, diagnostic=True,
                         simulated_time=args.fixture_now,
                         authority_lifecycle=cycle.authority_status(store, value, args.fixture_now)))
        return 0

    if args.command == 'create-lab':
        for name in ('root', 'content_origin', 'maintenance_origin', 'group'):
            if not getattr(args, name):
                parser.error('--' + name.replace('_', '-') + ' is required')
        args.admin_password = args.admin_password or os.environ.get(
            args.admin_password_env, '')
        if len(args.admin_password) < 12:
            parser.error('Set a 12+ character disposable admin password.')
        if bool(args.tls_content_cert) != bool(args.tls_content_key) or \
                bool(args.tls_maintenance_cert) != bool(args.tls_maintenance_key):
            parser.error('TLS certificate/key pairs must be supplied together.')
        if args.tls_content_cert and not args.ca:
            parser.error('--ca is required with external TLS material.')
        result = create_lab(args)
        _emit(args, result)
        return 0
    if args.command == 'run':
        if not args.config or not args.side or not args.caddy:
            parser.error('--config, --side and --caddy are required')
        verify_caddy(args.caddy)
        if args.console:
            return run_console(args)
        if os.name != 'nt':
            raise DeploymentError('service_dispatch_windows_only')
        _dispatch({'config': args.config, 'side': args.side, 'caddy': args.caddy},
                  args.service_name)
        return 0
    if not Path(args.root or '.').exists() and args.command not in ('import-install',):
        parser.error('--root is required')
    if args.command == 'import-install':
        if not all((args.install, args.bundle, args.passphrase_file)):
            parser.error('--install, --bundle and --passphrase-file are required')
        if not args.claim_db and not (args.source_origin and args.ca):
            parser.error('--claim-db or both --source-origin and --ca are required')
        try:
            _emit(args, import_install(args))
        except (RelocationError, MaintenanceError) as error:
            _emit(args, {'error': getattr(error, 'code', str(error))})
            return 1
        return 0
    if args.command == 'export-side':
        _emit(args, export_side(args))
        return 0
    if args.command == 'stage-remote':
        if not args.destination_root:
            parser.error('--destination-root is required')
        try:
            _emit(args, stage_remote(args))
        except DeploymentError as error:
            _emit(args, {'error': getattr(error, 'code', str(error))})
            return 1
        return 0
    if args.command == 'acl':
        _emit(args, apply_acl(args))
        return 0
    if args.command == 'install-service':
        if not all((args.side, args.identity, args.name)):
            parser.error('--side, --identity and --name are required')
        _emit(args, install_service(args))
        return 0
    _emit(args, service_command(args))
    return 0


if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except (DeploymentError, RelocationError, MaintenanceError, RuntimeError) as error:
        print(json.dumps({'error': getattr(error, 'code', str(error))}), file=sys.stderr)
        raise SystemExit(1)
