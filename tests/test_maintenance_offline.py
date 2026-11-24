import copy
import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from kiosk.maintenance.setup import create_lab
from kiosk.maintenance.apps import maintenance_application
from kiosk.maintenance.offline import backup, renew
from kiosk.maintenance.relocation import RelocationError
from kiosk.delivery.protocol import decode, encode
from kiosk.trust.lifecycle import verify_group_window
from kiosk.publication import authority as a


class OfflineMaintenanceTests(unittest.TestCase):
    def setUp(cls):
        cls.temp = tempfile.TemporaryDirectory()
        cls.root = Path(cls.temp.name)
        cls.created = create_lab(cls.root/'lab', content_origin='https://127.0.0.1:24443',
                                maintenance_origin='https://127.0.0.1:25443',
                                group_id='offline-test', admin_user='admin', admin_password='disposable-password')
        cls.backup_file = cls.root/'recovery.bundle'
        cls.backup_result = backup(cls.root/'lab', cls.backup_file, 'single-administrator-password')

    def tearDown(cls):
        cls.temp.cleanup()

    def test_complete_public_same_key_chain_renewal_after_independent_expiry(self):
        app = maintenance_application(self.created['maintenance_config'])
        store = app.extensions['maintenance_store']; authority = app.extensions['maintenance_authority']
        issuer = app.extensions['maintenance_tls_authority']
        with store.connection() as db:
            configuration = decode(bytes(db.execute('SELECT configuration FROM tls_issuer').fetchone()[0]))
        previous = verify_group_window(configuration['group_trust'], issuer.root_spki)
        now = previous['issued_at'] + 105*86400
        store.clock = authority.clock = lambda: now
        from kiosk.maintenance.host import _main
        from kiosk.maintenance.store import MaintenanceError
        request_file = self.root / 'recovery-request.json'
        command = ['export-lan-request', '--config', str(self.created['maintenance_config']),
                   '--out', str(request_file)]
        # No HTTPS listener is needed to export the retained key's proof.
        with patch('kiosk.maintenance.apps.maintenance_application', return_value=app), contextlib.redirect_stdout(io.StringIO()):
            with self.assertRaisesRegex(MaintenanceError, 'retained_administrator_required'):
                _main(command + ['--admin', 'missing'])
            self.assertEqual(_main(command), 0)
            with self.assertRaises(FileExistsError):
                _main(command)
        request = decode(request_file.read_bytes())
        with self.assertRaises(ValueError):
            renew(self.backup_file, 'single-administrator-password', request, now)
        with self.assertRaises(RelocationError):
            renew(self.backup_file, 'wrong-password', request, now, confirm=True)
        tampered = copy.deepcopy(request); tampered['lan']['issuer_certificate'] += '\n'
        with self.assertRaises(ValueError):
            renew(self.backup_file, 'single-administrator-password', tampered, now, confirm=True)
        result = renew(self.backup_file, 'single-administrator-password', request, now, confirm=True)
        self.assertNotIn('PRIVATE KEY', json.dumps(result))
        self.assertEqual(result, renew(self.backup_file, 'single-administrator-password', request, now+120, confirm=True))
        from kiosk.maintenance.offline import apply_public
        from kiosk.maintenance.authority_delivery import pending
        bad = copy.deepcopy(result)
        bad['lan']['group_trust']['signature_base64'] = 'AA=='
        with self.assertRaises(ValueError):
            apply_public(app, 'admin', bad, root_pin=authority.public['root_sha256'], confirm=True)
        with store.connection(write=False) as db:
            self.assertEqual(db.execute('SELECT version FROM publisher_policy').fetchone()[0], 1)
        recovered = apply_public(app, 'admin', result, root_pin=authority.public['root_sha256'], confirm=True)
        self.assertTrue(pending(store))
        self.assertEqual(recovered['device_id'], request['request']['device_id'])
        self.assertEqual(recovered['expires'], now+104*86400)
        issuer.require_current()
        self.assertEqual(issuer.current_group()['generation'], previous['generation']+1)
        self.assertTrue(self.backup_result['verified'])
        store.fence()
        from kiosk.maintenance.offline import export_request
        with self.assertRaisesRegex(MaintenanceError, 'service_fenced'):
            export_request(app, 'admin', require_lan=True)

    def test_relocated_public_issuer_binding_is_scoped_monotonic_and_durable(self):
        from kiosk.maintenance.apps import content_application
        from kiosk.maintenance.tls_binding import accept, current_origin
        from kiosk.trust.roles import sign_delegation
        from kiosk.trust.lifecycle import delegation_from_payload
        import base64
        app = content_application(self.created['content_config'])
        maintenance = maintenance_application(self.created['maintenance_config'])
        store = maintenance.extensions['maintenance_store']
        with store.connection(write=False) as db:
            config = decode(bytes(db.execute('SELECT configuration FROM tls_issuer').fetchone()[0]))
        original = config['delegations']['maintenance']['payload']
        new = dict(original, origin='https://127.0.0.3:25443', permitted_ip=['127.0.0.3'])
        group = (self.root/'lab/group/group-key.pem').read_text()
        signed = dict(payload=new, signature=base64.b64encode(sign_delegation(group, delegation_from_payload(new))).decode())
        with self.assertRaises(ValueError):
            accept(app, dict(generation=1, delegation=signed))
        self.assertEqual(accept(app, dict(generation=2, delegation=signed)), new['origin'])
        restarted = content_application(self.created['content_config'])
        self.assertEqual(current_origin(restarted, original['origin']), new['origin'])
        with self.assertRaises(ValueError):
            accept(app, dict(generation=1, delegation=signed))
        other = dict(new, server_id='another-maintenance')
        bad = dict(payload=other, signature=base64.b64encode(sign_delegation(group, delegation_from_payload(other))).decode())
        with self.assertRaises(ValueError):
            accept(app, dict(generation=3, delegation=bad))

        # Renewal at the destination does not increment the placement
        # generation. Announce the stored new delegation, not the old override.
        from kiosk.maintenance.tls_runtime import TLSRuntime
        from types import SimpleNamespace
        issuer = maintenance.extensions['maintenance_tls_authority']
        override = self.root / 'relocated-delegation.json'
        override.write_bytes(encode(signed))
        issuer.maintenance_override = override
        issuer.maintenance_origin = new['origin']
        now = new['issued_at'] + 90*86400
        restarted.extensions['roaming_workspace'].clock = store.clock = lambda: now
        store.configure_placement('separated', 'maintenance', 'n2', new['origin'], generation=2)
        refreshed = dict(new, issued_at=now, expires_at=now+111*86400)
        refreshed_envelope = dict(payload=refreshed, signature=base64.b64encode(
            sign_delegation(group, delegation_from_payload(refreshed))).decode())
        config['delegations']['maintenance'] = refreshed_envelope
        with store.connection() as db:
            db.execute('UPDATE tls_issuer SET configuration=?', (encode(config),))
        with patch.object(maintenance.extensions['maintenance_content'], '_request',
                          side_effect=lambda method, route, value: accept(restarted, value)) as send:
            TLSRuntime.announce(SimpleNamespace(app=maintenance, runtime=SimpleNamespace(side='maintenance')))
        self.assertEqual(send.call_args.args, ('POST', '/service/v1/tls-authority',
                                               dict(generation=2, delegation=refreshed_envelope)))
        with self.assertRaises(ValueError):
            accept(restarted, dict(generation=2, delegation=signed))
        restarted.extensions['roaming_workspace'].clock = lambda: new['expires_at']
        self.assertEqual(current_origin(restarted, original['origin']), new['origin'])
