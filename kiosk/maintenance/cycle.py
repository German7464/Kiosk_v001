"""90-day administrator maintenance cycle and explicit persistent recovery state.

The schedule only reads the service clock; it never writes the OS clock or
extends expired authority silently. Routine device credential/certificate
renewal stays inside the LAN delivery client; this module provides the bounded
warning/overlap window and a durable recovery marker that survives restarts.
"""
from __future__ import annotations

import base64
from pathlib import Path

from kiosk.delivery.protocol import decode, encode
from .store import MaintenanceError

DAY = 86400
DEFAULT_INTERVAL_DAYS = 90
WARNING_DAYS = (30, 14, 7, 1)


def authority_status(store, settings, now=None):
    """Local expiry diagnostics, never permission or a promise of remote renewal."""
    from cryptography import x509
    from kiosk.publication import authority as a

    now = store.now() if now is None else int(now)
    deadlines, unavailable = [], []

    def add(name, expires):
        remaining = int(expires) - now
        deadlines.append(dict(name=name, expires=int(expires),
                              remaining_seconds=remaining,
                              state='expired' if remaining <= 0 else
                              'warning' if remaining <= 30 * DAY else 'valid'))

    tls = settings.get('TLS') or {}
    for name, path in (('maintenance_tls', tls.get('cert')), ('tls_root', tls.get('ca'))):
        try:
            certs = x509.load_pem_x509_certificates(Path(path).read_bytes())
            if not certs:
                raise ValueError('certificate_missing')
            for index, cert in enumerate(certs):
                add(name if index == 0 else name + '_issuer_' + str(index),
                    int(cert.not_valid_after_utc.timestamp()))
        except (OSError, ValueError, TypeError):
            unavailable.append(name)
    try:
        public = decode(Path(settings['MAINTENANCE_ROOT_PUBLIC']).read_bytes())
        with store.connection(write=False) as db:
            retained = db.execute('SELECT envelope FROM publisher_policy WHERE singleton=1').fetchone()
        envelope = (decode(bytes(retained['envelope'])) if retained else
                    decode(Path(settings['MAINTENANCE_ROOT_POLICY']).read_bytes()))
        root = base64.b64decode(public['root_spki'], validate=True)
        # Historical validation is diagnostic only. Privileged work still
        # checks current time, revocation and retained policy floors.
        signed = a.verified(envelope, root, 'policy')
        value = a.policy(envelope, root, public['group_id'], public['origin'], signed['issued'])
        add('publisher_policy', value['expires'])
    except (OSError, ValueError, TypeError, KeyError):
        unavailable.append('publisher_policy')
    with store.connection(write=False) as db:
        row = db.execute('SELECT MIN(expires) AS expires FROM keys WHERE chain IS NOT NULL').fetchone()
        if row['expires'] is not None:
            add('earliest_local_publisher_grant', row['expires'])
        issuer = db.execute('SELECT configuration FROM tls_issuer WHERE singleton=1').fetchone()
    unobserved = ['content_tls', 'automatic_renewal_activation', 'remote_device_credentials']
    if issuer is not None and settings.get('LAN_TLS_ROOT_SPKI'):
        try:
            from kiosk.trust.lifecycle import verify_group_window, delegation_from_payload
            from kiosk.trust.roles import verify_delegation
            configuration = decode(bytes(issuer['configuration']))
            root = base64.b64decode(settings['LAN_TLS_ROOT_SPKI'], validate=True)
            group = verify_group_window(configuration['group_trust'], root)
            add('group_trust', group['expires_at'])
            for side in ('content', 'maintenance'):
                delegated = configuration['delegations'][side]
                item = delegation_from_payload(delegated['payload'])
                verify_delegation(root, item, base64.b64decode(delegated['signature'], validate=True))
                add(side + '_tls_delegation', item.expires_at)
        except (OSError, ValueError, TypeError, KeyError):
            unavailable.append('lan_authority')
    else:
        unobserved.extend(['group_trust', 'issuer_delegation'])
    calendar = status(store, now)
    automatic = dict(configured=bool(settings.get('TLS_RENEWAL')), state='unobserved')
    if automatic['configured']:
        try:
            path = Path(tls['cert']).parent
            status_path = next(candidate for candidate in (path/'renewal-status.json', path.parent/'renewal-status.json') if candidate.is_file())
            record = decode(status_path.read_bytes())
            if not 0 <= now - record['observed'] <= 120:
                raise ValueError('stale_renewal_observation')
            automatic.update(state=record['state'], observed=record['observed'], error=record['error'])
        except (OSError, ValueError, KeyError, TypeError, StopIteration):
            pass
    bounds = []
    for item in deadlines:
        item['automatic'] = (item['name'] == 'maintenance_tls' and automatic['state'] in ('scheduled', 'renewed'))
        if not item['automatic']:
            # A full seven-day leaf must fit inside its signed delegation.
            bounds.append(item['expires'] - (7 * DAY if item['name'].endswith('_tls_delegation') else 0))
    if calendar['due'] is not None:
        bounds.append(calendar['due'])
    return dict(coverage='local_maintenance_only', deadlines=deadlines,
                automatic_tls=automatic,
                unavailable=unavailable,
                unobserved=unobserved,
                effective_due=min(bounds) if bounds else None,
                calendar_is_authority_renewal=False, unattended_interval_proven=False)


def status(store, now=None):
    now = store.now() if now is None else int(now)
    row = store.schedule()
    if row is None:
        return dict(state='unconfigured', due=None, remaining_seconds=None,
                    warnings=[], interval_days=DEFAULT_INTERVAL_DAYS)
    interval = int(row['interval_days'])
    if interval <= 0 or interval > 365:
        raise MaintenanceError('maintenance_interval_refused')
    anchor = int(row['last_maintenance'] or row['anchor'])
    due = anchor + interval * DAY
    remaining = due - now
    warnings = []
    for days in WARNING_DAYS:
        if remaining <= days * DAY:
            warnings.append(dict(days=days, level='due' if remaining <= 0 else 'warning'))
    return dict(state='due' if remaining <= 0 else 'scheduled', due=due,
                remaining_seconds=remaining, warnings=warnings,
                interval_days=interval, last_maintenance=int(row['last_maintenance']),
                anchor=int(row['anchor']))


def record(store, now=None):
    now = store.now() if now is None else int(now)
    if store.schedule() is None:
        raise MaintenanceError('maintenance_unconfigured', 503)
    store.record_maintenance(now)
    return status(store, now)


def recovery(store):
    with store.connection(write=False) as db:
        row = db.execute('SELECT * FROM recovery WHERE singleton=1').fetchone()
        if row is None:
            return dict(generation=0, state='none', detail={})
        return dict(generation=row['generation'], state=row['state'],
                    detail=decode(row['detail']))


def mark_recovery(store, state, detail=None, *, generation=None):
    """Persistent marker; increases a fencing generation and never resets it."""
    if state not in ('none', 'required', 'completed', 'failed'):
        raise MaintenanceError('recovery_state_refused')
    current = recovery(store)
    generation = int(generation if generation is not None else current['generation'])
    if generation < current['generation']:
        raise MaintenanceError('recovery_generation_rollback', 409)
    with store.connection() as db:
        db.execute('DELETE FROM recovery')
        db.execute('INSERT INTO recovery VALUES (1,?,?,?)',
                   (generation, state, encode(detail or {})))
        store.audit(db, 'recovery_state', '', state)
    return recovery(store)
