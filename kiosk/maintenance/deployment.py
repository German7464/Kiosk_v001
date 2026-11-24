"""Supported installation layout, ACLs and Windows service control.

Combined placement is two services on one OS, each running its own least-privileged
built-in Windows service identity (``LocalService`` for content, ``NetworkService``
for Maintenance unless overridden). Separated placement installs one side per OS
with an explicit authenticated counterpart; the same layout and service commands
apply. Root custody stays outside both services: the publisher authority root is
stored under ``admin-only`` and no service identity is granted access to it.

Nothing here changes the OS clock, time services, host networking or trust. ACLs
are applied explicitly with a protected DACL so that a side without an ACE has no
access even through inherited permissions.
"""
from __future__ import annotations

import ctypes
import json
import os
import shutil
import subprocess
import time
from ctypes import wintypes
from pathlib import Path

SID_ADMINISTRATORS = 'BA'
SID_SYSTEM = 'SY'
SID_LOCAL_SERVICE = 'LS'
SID_NETWORK_SERVICE = 'NS'
IDENTITY_SID = {'LocalService': SID_LOCAL_SERVICE, 'NetworkService': SID_NETWORK_SERVICE,
                'LocalSystem': SID_SYSTEM}
# Service Control Manager resolves the account through LookupAccountName, which
# needs the authority prefix for the per-service built-in accounts; a bare
# "LocalService" fails with error 1057. LocalSystem is a lone well-known alias.
IDENTITY_ACCOUNT = {'LocalService': 'NT AUTHORITY\\LocalService',
                    'NetworkService': 'NT AUTHORITY\\NetworkService',
                    'LocalSystem': 'LocalSystem'}

LAYOUT = ('app', 'config', 'data', 'logs', 'caddy', 'public', 'admin-only', 'transfer')


class DeploymentError(RuntimeError):
    pass


def identity_sid(name):
    try:
        return IDENTITY_SID[name]
    except KeyError:
        raise DeploymentError('service_identity_unsupported') from None


def identity_account(name):
    try:
        return IDENTITY_ACCOUNT[name]
    except KeyError:
        raise DeploymentError('service_identity_unsupported') from None


def sddl(full=(), read=()):
    parts = [f'(A;OICI;FA;;;{SID_SYSTEM})', f'(A;OICI;FA;;;{SID_ADMINISTRATORS})']
    for sid in full:
        parts.append(f'(A;OICI;FA;;;{sid})')
    for sid in read:
        parts.append(f'(A;OICI;GRGX;;;{sid})')
    return 'D:P' + ''.join(parts)


def set_security(path, descriptor, *, recursive=True):
    """Apply one explicit protected DACL to a path and (optionally) its tree."""
    api = ctypes.WinDLL('advapi32', use_last_error=True)
    api.ConvertStringSecurityDescriptorToSecurityDescriptorW.argtypes = [
        wintypes.LPCWSTR, wintypes.DWORD, ctypes.POINTER(ctypes.c_void_p),
        ctypes.POINTER(wintypes.DWORD)]
    api.ConvertStringSecurityDescriptorToSecurityDescriptorW.restype = wintypes.BOOL
    api.SetFileSecurityW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, ctypes.c_void_p]
    api.SetFileSecurityW.restype = wintypes.BOOL
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    kernel.LocalFree.argtypes = [ctypes.c_void_p]
    kernel.LocalFree.restype = ctypes.c_void_p
    path = Path(path)
    targets = [path]
    if recursive and path.is_dir():
        targets.extend(sorted(item for item in path.rglob('*')))
    for target in targets:
        handle = ctypes.c_void_p()
        if not api.ConvertStringSecurityDescriptorToSecurityDescriptorW(
                descriptor, 1, ctypes.byref(handle), None):
            raise ctypes.WinError(ctypes.get_last_error())
        try:
            if not api.SetFileSecurityW(str(target), 0x80000004, handle):
                raise ctypes.WinError(ctypes.get_last_error())
        finally:
            kernel.LocalFree(handle)
    return len(targets)


def apply_layout_acls(root, *, content_identity='LocalService',
                      maintenance_identity='NetworkService'):
    """Grant each side only its own tree; both may read the public CA."""
    root = Path(root)
    content = identity_sid(content_identity)
    maintenance = identity_sid(maintenance_identity)
    applied = {}

    def tree(relative, descriptor):
        path = root / relative
        if path.exists():
            applied[relative] = set_security(path, descriptor)

    tree('', sddl())
    for side, sid in (('content', content), ('maintenance', maintenance)):
        # The shared executable root holds one copy per side; each side may only
        # read and execute its own copy. The side root itself is also owned by
        # that identity so a service can use it as a working directory.
        tree(side, sddl(full=(sid,)))
        tree(f'app/{side}', sddl(full=(sid,)))
        for part in ('config', 'data', 'logs', 'caddy', 'tls'):
            tree(f'{side}/{part}', sddl(full=(sid,)))
    # The root public directory holds only public material (CA, bootstrap).
    # Shared trust anchors/policies are administrator-owned. Either service
    # writing here could replace the other side's CA or publisher root on restart.
    tree('public', sddl(read=(content, maintenance)))
    # The offline publisher authority and transfer passphrases stay admin-only.
    tree('admin-only', sddl())
    tree('transfer', sddl())
    return applied


def grant_identity_read(path, identity, *, recursive=True):
    return set_security(path, sddl(read=(identity_sid(identity),)), recursive=recursive)


def hidden(arguments, *, timeout=60, check=True):
    result = subprocess.run(list(arguments), capture_output=True, timeout=timeout,
                            text=True, errors='replace',
                            creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
    if check and result.returncode:
        raise DeploymentError('command_failed: ' + ' '.join(arguments) + ': ' +
                              (result.stdout + result.stderr)[-400:])
    return result


def service_create(name, executable, arguments, identity, *, display=None,
                   description=''):
    quote = '"{}"'.format
    binary = quote(str(executable))
    if arguments:
        binary += ' ' + ' '.join(quote(str(item)) for item in arguments)
    existing = service_status(name)
    if existing != 'absent':
        raise DeploymentError('service_exists')
    hidden(['sc.exe', 'create', name, 'binPath=', binary, 'start=', 'auto',
            'obj=', identity_account(identity), 'DisplayName=', display or name])
    hidden(['sc.exe', 'description', name, description or display or name], check=False)
    hidden(['sc.exe', 'failure', name, 'reset=', '86400', 'actions=',
            'restart/5000/restart/30000/none/0'], check=False)
    hidden(['sc.exe', 'sidtype', name, 'unrestricted'], check=False)
    return name


def service_delete(name):
    if service_status(name) == 'absent':
        return False
    service_stop(name)
    hidden(['sc.exe', 'delete', name], check=False)
    return True


def service_status(name):
    result = hidden(['sc.exe', 'query', name], check=False)
    if result.returncode:
        return 'absent'
    if 'RUNNING' in result.stdout:
        return 'running'
    if 'STOPPED' in result.stdout:
        return 'stopped'
    if 'START_PENDING' in result.stdout or 'STOP_PENDING' in result.stdout:
        return 'pending'
    return 'unknown'


def service_start(name, *, timeout=90):
    hidden(['sc.exe', 'start', name])
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        state = service_status(name)
        if state == 'running':
            return state
        if state in ('absent', 'stopped'):
            raise DeploymentError('service_failed_to_start')
        time.sleep(1)
    raise DeploymentError('service_start_timeout')


def service_stop(name, *, timeout=90):
    if service_status(name) in ('absent', 'stopped'):
        return True
    hidden(['sc.exe', 'stop', name], check=False)
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if service_status(name) in ('absent', 'stopped'):
            return True
        time.sleep(1)
    raise DeploymentError('service_stop_timeout')


def service_sid(name):
    result = hidden(['sc.exe', 'showsid', name])
    marker = result.stdout.upper().find('S-1-5-80')
    if marker < 0:
        raise DeploymentError('service_sid_unavailable')
    remainder = result.stdout[marker:].split()[0]
    return remainder.strip()


def write_json(path, value, mode=0o600):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        raise DeploymentError('deployment_file_exists')
    path.write_text(json.dumps(value, indent=2, sort_keys=True), encoding='utf-8')
    try:
        os.chmod(path, mode)
    except OSError:
        pass
    return path


def copy_tree(source, destination):
    source, destination = Path(source), Path(destination)
    if destination.exists():
        raise DeploymentError('deployment_destination_exists')
    shutil.copytree(source, destination)
    return destination
