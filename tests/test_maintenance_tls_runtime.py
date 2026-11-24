"""Real pinned Caddy/Waitress loopback integration, no installation or OS trust."""
import json
import os
import socket
import tempfile
import time
import unittest
from pathlib import Path

from kiosk.maintenance.serve import Runtime, verify_caddy
from kiosk.maintenance.setup import create_lab
from kiosk.trust.crypto import issue_tls_leaf, leaf_spki_sha256


@unittest.skipUnless(os.environ.get('KIOSK_STAGE5_TEST_CADDY'), 'Explicit pinned Caddy fixture required')
class TLSRuntimeTests(unittest.TestCase):
    def test_expired_maintenance_self_start_then_running_content_csr_rotation(self):
        caddy = Path(os.environ['KIOSK_STAGE5_TEST_CADDY'])
        verify_caddy(caddy)
        with tempfile.TemporaryDirectory(prefix='kiosk-s5-tls-') as temporary:
            root = Path(temporary) / 'lab'
            def port(host):
                with socket.socket() as probe:
                    probe.bind((host, 0))
                    return probe.getsockname()[1]
            content = 'https://127.0.0.1:' + str(port('127.0.0.1'))
            maintenance = 'https://127.0.0.2:' + str(port('127.0.0.2'))
            created = create_lab(root, content_origin=content, maintenance_origin=maintenance,
                                 group_id='tls-runtime-test', admin_user='admin',
                                 admin_password='disposable-runtime-password')
            (root / 'logs').mkdir()
            initial = {}
            for side, origin, remaining in (('maintenance', maintenance, -5),
                                             ('content', content, 2 * 86400 + 5)):
                from urllib.parse import urlsplit
                cert, key = issue_tls_leaf('pre-aged fixture',
                    (root / 'ca/issuer.pem').read_text(), (root / 'ca/issuer-key.pem').read_text(),
                    san_ips=[urlsplit(origin).hostname], san_dns=[], validity_days=7,
                    now=int(time.time()) - 7 * 86400 + remaining)
                folder = root / side / 'tls'
                (folder / 'chain.pem').write_text(cert + (root / 'ca/issuer.pem').read_text())
                (folder / 'key.pem').write_text(key)
                initial[side] = leaf_spki_sha256(cert)
            services = []
            try:
                trusted = Runtime(created['maintenance_config'], 'maintenance', caddy_path=caddy)
                services.append(trusted)
                trusted.start()
                trusted.wait_ready(timeout=15)
                self.assertNotEqual(initial['maintenance'], leaf_spki_sha256(Path(trusted.tls['cert']).read_text()))
                host = Runtime(created['content_config'], 'content', caddy_path=caddy)
                services.append(host)
                host.start()
                host.wait_ready(timeout=15)
                self.assertEqual(initial['content'], leaf_spki_sha256(Path(host.tls['cert']).read_text()))
                backend = host.thread
                deadline = time.monotonic() + 45
                while time.monotonic() < deadline and host.tls_manager.status['state'] != 'renewed':
                    time.sleep(.25)
                self.assertEqual(host.tls_manager.status['state'], 'renewed', host.tls_manager.status)
                self.assertNotEqual(initial['content'], leaf_spki_sha256(Path(host.tls['cert']).read_text()))
                self.assertIs(host.thread, backend)
                self.assertTrue(backend.is_alive())
                record = json.loads(host.tls_manager.pointer.read_text())
                self.assertEqual(record['spki'], leaf_spki_sha256(Path(host.tls['cert']).read_text()))
                host.wait_ready(timeout=5)
                host.stop()
                restored = Runtime(created['content_config'], 'content', caddy_path=caddy)
                services.append(restored)
                restored.start()
                restored.wait_ready(timeout=5)
                self.assertEqual(record['spki'], leaf_spki_sha256(Path(restored.tls['cert']).read_text()))
            finally:
                for service in reversed(services):
                    service.stop()
