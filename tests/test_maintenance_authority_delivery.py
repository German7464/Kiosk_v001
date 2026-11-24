import tempfile
import unittest
from pathlib import Path

from kiosk.delivery.protocol import encode
from kiosk.maintenance.authority_delivery import flush, pending
from kiosk.maintenance.store import MaintenanceStore


class AuthorityDeliveryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.store = MaintenanceStore(Path(self.temp.name) / 'maintenance.sqlite')
        self.queue({'policy': {'version': 2}})

    def queue(self, value):
        with self.store.connection() as db:
            db.execute('INSERT OR REPLACE INTO authority_delivery VALUES (1,?)', (encode(value),))

    def test_network_failure_is_durable_and_successful_retry_clears(self):
        class Offline:
            def _request(self, *args):
                raise OSError('offline')
        with self.assertRaises(OSError):
            flush(self.store, Offline())
        self.assertTrue(pending(self.store))
        outer = self
        class Online:
            def _request(self, method, path, value):
                outer.assertEqual((method, path), ('POST', '/service/v1/authority'))
                outer.assertEqual(value, {'policy': {'version': 2}})
                return {'installed': True}
        self.assertTrue(flush(self.store, Online()))
        self.assertFalse(pending(self.store))

    def test_older_response_cannot_acknowledge_newer_bundle(self):
        outer = self
        class Concurrent:
            def _request(self, *args):
                outer.queue({'policy': {'version': 3}})
        self.assertFalse(flush(self.store, Concurrent()))
        self.assertTrue(pending(self.store))
