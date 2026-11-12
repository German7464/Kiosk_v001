"""Changed Tk/worker integration only; previously accepted transfer/display stays reused."""
from contextlib import contextmanager
from copy import deepcopy
from datetime import datetime, timezone
import json
from pathlib import Path
import queue
import tempfile
import threading
import time
import unittest
from unittest.mock import Mock, patch

from kiosk.delivery.protocol import PROFILE, encode, sha
from kiosk.display.connect import Connection, Cancelled, _Response, public_input, confirmed_time, error_status
from kiosk.display.delivery_client import Client
from kiosk.display.delivery_transport import TransportError
from kiosk.publication.exporter import PackageError


PUBLIC = json.loads((Path(__file__).parent / 'fixtures/device-delivery-v1-public.json').read_text())['bootstrap']
NOW = PUBLIC['issued_at'] + 60


class State:
    def __init__(self):
        self.data = {}
    def save(self):
        pass


class FakeClient:
    def __init__(self, *args, **kwargs):
        self.native = State()
        self.store = args[0] / 'store'
    @contextmanager
    def ownership(self):
        yield self


class ConnectTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.raw = encode(PUBLIC)

    def drain(self, connection):
        connection.thread.join(3)
        self.assertFalse(connection.busy)
        values = []
        while not connection.events.empty():
            values.append(connection.events.get_nowait())
        return values

    def test_input_exact_origin_key_expiry_and_bound_before_network(self):
        factory = Mock()
        connection = Connection(self.root, self.root/'shell.exe', client_factory=factory)
        invalid = [b'', b'x'*16385, b'{}', self.raw.replace(b'"version":1', b'"version":true')]
        for raw in invalid:
            with self.subTest(raw_size=len(raw)), self.assertRaises(Exception):
                public_input(raw, PUBLIC['origin'], now=NOW)
        for address in ('http://localhost:9443', PUBLIC['origin']+'/', 'https://other:9443'):
            with self.subTest(address=address), self.assertRaises(PackageError):
                public_input(self.raw, address, now=NOW)
        for moment in (PUBLIC['issued_at']-1, PUBLIC['expires_at']):
            with self.assertRaises(PackageError):
                public_input(self.raw, PUBLIC['origin'], now=moment)
        damaged = deepcopy(PUBLIC); damaged['group_key_id'] = '0'*64
        with self.assertRaises(PackageError):
            public_input(encode(damaged), PUBLIC['origin'], now=NOW)
        with patch('time.time', return_value=NOW):
            connection.start('enroll', raw=b'{}', address=PUBLIC['origin'], digest=sha(self.raw), confirmed=True, utc=NOW)
            self.drain(connection)
        factory.assert_not_called()

    def test_independent_confirmation_required_not_self_derived(self):
        for digest, checked in [(sha(self.raw), False), ('0'*64, True), ('', True), (None, True)]:
            with self.subTest(digest=digest), self.assertRaises(PackageError):
                public_input(self.raw, PUBLIC['origin'], now=NOW, confirmation=digest, confirmed=checked)
        self.assertEqual(public_input(self.raw, PUBLIC['origin'], now=NOW, confirmation=sha(self.raw), confirmed=True), PUBLIC)

    def test_time_explicit_aware_recent_and_not_automatic(self):
        value = datetime.fromtimestamp(NOW, timezone.utc).isoformat()
        with patch('time.time', return_value=NOW):
            self.assertEqual(confirmed_time(value, True), NOW)
            for text, checked in [(value, False), ('2026-01-01T00:00:00', True), ('wrong', True), ('2000-01-01T00:00:00Z', True)]:
                with self.assertRaises(PackageError):
                    confirmed_time(text, checked)

    def test_repeated_click_single_owner_cancel_and_shutdown(self):
        entered = threading.Event()
        def factory(*args, **kwargs):
            entered.set()
            kwargs['stop'].wait(2)
            return FakeClient(*args, **kwargs)
        connection = Connection(self.root, self.root/'shell.exe', client_factory=factory)
        self.assertTrue(connection.start('inspect'))
        self.assertTrue(entered.wait(1))
        self.assertFalse(connection.start('enroll'))
        connection.cancel()
        self.assertEqual([v['state'] for v in self.drain(connection)], ['cancelled', 'idle'])

    def test_pending_cancellation_retains_same_request_and_secret(self):
        fake = FakeClient(self.root)
        fake.native.data = {'bootstrap': PUBLIC, 'binding': {'device_id': 'd', 'request_id': 'r'},
                            'secret': 'a'*64, 'pending': {'device_code': 'b'*64}}
        fake.enroll = Mock(return_value={'result':'pending', 'user_code':'ABCDEFGH'})
        connection = Connection(self.root, self.root/'shell.exe', client_factory=lambda *a, **k: fake)
        with patch('kiosk.display.connect.PublicationStore') as store:
            store.return_value.active.return_value = None
            connection.start('enroll')
            event = connection.events.get(timeout=1)
            self.assertEqual(event['code'], 'ABCDEFGH')
            self.assertNotIn('a'*64, json.dumps(event))
            self.assertNotIn('b'*64, json.dumps(event))
            connection.cancel(); self.drain(connection)
            connection.start('enroll')
            self.assertEqual(connection.events.get(timeout=1)['device'], 'd')
            connection.cancel(); self.drain(connection)
        self.assertEqual(fake.native.data['binding']['request_id'], 'r')
        self.assertEqual(fake.native.data['secret'], 'a'*64)

    def test_long_rate_limit_wait_is_reported_and_cancellable(self):
        fake = FakeClient(self.root)
        fake.native.data = {'bootstrap': PUBLIC, 'secret': 'a'*64,
                            'binding': {'device_id': 'd', 'request_id': 'r'}}
        fake.enroll = Mock(return_value={'result': 'rate_limited', 'user_code': 'ABCDEFGH',
                                         'retry_after': 600, 'device_id': 'd'})
        connection = Connection(self.root, self.root/'shell.exe', client_factory=lambda *a, **k: fake)
        connection.start('enroll')
        event = connection.events.get(timeout=1)
        self.assertEqual(event['state'], 'rate_limited')
        self.assertEqual(event['wait'], 600)
        connection.cancel()
        # The worker waits through the cancellable stop event, not an uninterruptible sleep.
        self.assertEqual([v['state'] for v in self.drain(connection)], ['cancelled', 'idle'])

    def test_saved_connection_cannot_be_replaced_by_input_failure(self):
        fake = FakeClient(self.root)
        old = deepcopy(PUBLIC); old['server_id'] = 'old-server'
        fake.native.data = {'bootstrap': old, 'accepted': {'retained': 1}}
        before = deepcopy(fake.native.data)
        connection = Connection(self.root, self.root/'shell.exe', client_factory=lambda *a, **k: fake)
        with patch('time.time', return_value=NOW):
            connection.start('enroll', raw=self.raw, address=PUBLIC['origin'], digest=sha(self.raw), confirmed=True, utc=NOW)
            self.assertEqual(self.drain(connection)[0]['state'], 'operation_refused')
        self.assertEqual(fake.native.data, before)

    def test_time_before_enrollment_cannot_poison_empty_configuration(self):
        fake = FakeClient(self.root)
        fake.native.confirm_time = Mock()
        connection = Connection(self.root, self.root/'shell.exe', client_factory=lambda *a, **k: fake)
        connection.start('time', utc=NOW)
        self.assertEqual(self.drain(connection)[0]['state'], 'operation_refused')
        fake.native.confirm_time.assert_not_called()
        self.assertEqual(fake.native.data, {})

    def test_terminal_denial_expiry_401_and_secret_exception_redacted(self):
        for error, expected in [(TransportError('native_http_refused',403),'denied'),
                                (TransportError('native_http_refused',410),'expired'),
                                (TransportError('native_http_refused',401),'access_refused'),
                                (PackageError('credential_revoked'),'access_refused'),
                                (PackageError('time_confirmation_required'),'time_required')]:
            self.assertEqual(error_status(error), expected)
        fake = FakeClient(self.root)
        fake.enroll = Mock(side_effect=ValueError('SECRET bearer private/path'))
        connection = Connection(self.root, self.root/'shell.exe', client_factory=lambda *a, **k: fake)
        connection.start('enroll')
        self.assertNotIn('SECRET', json.dumps(self.drain(connection)))

    def test_transport_response_cancellation_stops_before_next_read(self):
        stop = threading.Event(); response = Mock()
        guarded = _Response(response, stop)
        stop.set()
        with self.assertRaises(Cancelled):
            guarded.read(65536)
        response.read.assert_not_called()

    def test_real_enroll_lost_response_uses_persisted_native_request(self):
        # New UI retries the accepted API after cancel/network failure; no second request identity.
        client = object.__new__(Client)
        client.native = State()
        client.native.data = {'bootstrap': PUBLIC, 'secret': 'a'*64,
                              'binding': {'request_id':'fixed-request', 'device_id':'device'}}
        client.native.now = lambda: NOW
        transport = Mock()
        pending = {'version':1, 'request_id':'fixed-request', 'device_code':'b'*64,
                   'user_code':'ABCDEFGH', 'expires_in':600, 'interval':5}
        calls = []
        def request(path, **kwargs):
            if path.endswith('/status'):
                raise TransportError('native_http_refused', 401)
            calls.append(deepcopy(kwargs['body']))
            if len(calls) == 1:
                raise TransportError('network_unavailable')
            return pending if path.endswith('/authorize') else {'version':1,'state':'pending','interval':5}
        transport.json.side_effect = request
        client.connect = lambda: transport
        with self.assertRaises(TransportError):
            client.enroll()
        with patch('time.time', return_value=NOW):
            self.assertEqual(client.enroll()['result'], 'pending')
        self.assertEqual(calls[0], calls[1])
        self.assertEqual(client.native.data['secret'], 'a'*64)

    def test_enrollment_rate_limit_waits_and_resumes_same_request(self):
        client = object.__new__(Client)
        client.native = State()
        client.native.data = {'bootstrap': PUBLIC, 'secret': 'a'*64,
                              'binding': {'request_id': 'fixed-request', 'device_id': 'device'}}
        client.native.now = lambda: NOW
        pending = {'version': 1, 'request_id': 'fixed-request', 'device_code': 'b'*64,
                   'user_code': 'ABCDEFGH', 'expires_in': 600, 'interval': 5}
        credential = {'version': 1, 'state': 'approved', 'device_id': 'device', 'profile': PROFILE,
                      'credential_id': 'c'*32, 'expires_at': NOW + 86400,
                      'scopes': ['read_assignment', 'submit_receipt']}
        calls, tokens = [], []
        def request(path, **kwargs):
            calls.append(path)
            if path.endswith('/status'):
                raise TransportError('native_http_refused', 401)
            if path.endswith('/authorize'):
                return pending
            tokens.append(path)
            if len(tokens) == 1:
                raise TransportError('request_limit', 429, retry_after=7)
            return credential
        transport = Mock()
        transport.json.side_effect = request
        client.connect = lambda: transport
        with patch('time.time', return_value=NOW):
            result = client.enroll()
        self.assertEqual(result['result'], 'rate_limited')
        self.assertEqual(result['retry_after'], 7)
        self.assertEqual(client.native.data['retry_not_before'], NOW + 7)
        self.assertEqual(client.native.data['next_poll'], NOW + 8)
        self.assertEqual(client.native.data['binding'], {'request_id': 'fixed-request', 'device_id': 'device'})
        # Before the persisted wait elapses NOTHING reaches the transport: the old
        # code still sent the status request here.
        before = len(calls)
        with patch('time.time', return_value=NOW + 3):
            deferred = client.enroll()
        self.assertEqual(deferred['result'], 'rate_limited')
        self.assertEqual(deferred['retry_after'], 4)
        self.assertEqual(len(calls), before)
        self.assertEqual(len(tokens), 1)
        with patch('time.time', return_value=NOW + 9):
            self.assertEqual(client.enroll()['result'], 'approved')
        self.assertEqual(len(tokens), 2)
        self.assertEqual(client.native.data['credential']['credential_id'], 'c'*32)
        self.assertNotIn('retry_not_before', client.native.data)

    def test_persisted_backoff_survives_restart_and_respects_long_server_delay(self):
        # A 600 s Retry-After (the device-decision budget) must not be truncated to 60.
        self.assertEqual(TransportError('request_limit', 429, retry_after=600).retry_after, 600)
        for supplied, expected in [('soon', 5), ('', 5), (None, 5), ('-3', 5), ('0', 5),
                                   (str(10**9), 3600), (10**9, 3600), ('17', 17), (17, 17)]:
            with self.subTest(supplied=supplied):
                self.assertEqual(TransportError('request_limit', 429, retry_after=supplied).retry_after,
                                 expected)
        client = object.__new__(Client)
        client.native = State()
        client.native.data = {'bootstrap': PUBLIC, 'secret': 'a'*64,
                              'binding': {'request_id': 'fixed-request', 'device_id': 'device'},
                              'pending': {'device_code': 'b'*64, 'user_code': 'ABCDEFGH'},
                              'retry_not_before': NOW + 600}
        client.native.now = lambda: NOW
        transport = Mock()
        transport.json.side_effect = AssertionError('network during persisted backoff')
        client.connect = lambda: transport
        with patch('time.time', return_value=NOW + 10):
            first = client.enroll()
        # A new object over the same persisted state models a process restart.
        restarted = object.__new__(Client)
        restarted.native = client.native
        restarted.native.now = lambda: NOW
        restarted.connect = lambda: transport
        with patch('time.time', return_value=NOW + 20):
            second = restarted.enroll()
        for result in (first, second):
            self.assertEqual(result['result'], 'rate_limited')
            self.assertGreaterEqual(result['retry_after'], 580)
            self.assertEqual(result['user_code'], 'ABCDEFGH')
            self.assertEqual(result['device_id'], 'device')
        transport.json.assert_not_called()
        self.assertEqual(client.native.data['binding']['request_id'], 'fixed-request')

    def test_malformed_persisted_deadline_does_not_block_forever(self):
        client = object.__new__(Client)
        client.native = State()
        client.native.data = {'bootstrap': PUBLIC, 'secret': 'a'*64,
                              'binding': {'request_id': 'fixed-request', 'device_id': 'device'},
                              'retry_not_before': 'not-a-number', 'next_poll': None}
        client.native.now = lambda: NOW
        credential = {'version': 1, 'state': 'approved', 'device_id': 'device', 'profile': PROFILE,
                      'credential_id': 'c'*32, 'expires_at': NOW + 86400,
                      'scopes': ['read_assignment', 'submit_receipt']}
        transport = Mock()
        transport.json.return_value = credential
        client.connect = lambda: transport
        with patch('time.time', return_value=NOW):
            self.assertEqual(client.enroll()['result'], 'approved')
        self.assertEqual(transport.json.call_count, 1)

    def test_offline_reopen_never_connects_and_queues_actual_display_only(self):
        fake = FakeClient(self.root)
        fake.native.data = {'bootstrap':PUBLIC, 'binding':{'device_id':'d'}, 'accepted':{}}
        fake.connect = Mock(side_effect=AssertionError('offline network'))
        fake.synchronize = Mock(side_effect=AssertionError('offline admission'))
        run = Mock(); run.process.poll.return_value = None
        connection = Connection(self.root, self.root/'shell.exe', client_factory=lambda *a, **k: fake)
        @contextmanager
        def display(mode):
            connection.stop.set()
            yield run
        fake.display = display
        with patch('kiosk.display.connect.PublicationStore') as store:
            store.return_value.active.return_value = self.root/'retained'
            connection.start('display', mode='kiosk', online=False)
            result = self.drain(connection)
        self.assertIn('ready', [v['state'] for v in result])
        self.assertEqual(fake.native.data['ui_mode'], 'kiosk')
        fake.connect.assert_not_called(); fake.synchronize.assert_not_called()

    def test_tk_confirmation_guard_busy_controls_and_deferred_close(self):
        import tkinter as tk
        from kiosk.display.connect_ui import Window
        connection = Mock()
        connection.events = queue.Queue(); connection.busy = False
        root = tk.Tk(); root.withdraw()
        try:
            window = Window(root, connection)
            connection.reset_mock()
            window.address.set(PUBLIC['origin']); window.public.insert('1.0', self.raw.decode())
            window.digest.set(sha(self.raw)); window.confirmed.set(False)
            with patch('time.time', return_value=NOW):
                window.enroll()
            connection.start.assert_not_called()
            public_file = self.root/'public.json'
            public_file.write_bytes(self.raw)
            window.file_name.set(str(public_file))
            with patch('time.time', return_value=NOW):
                window.load()
            self.assertEqual(window.raw, self.raw)
            self.assertFalse(window.confirmed.get())
            public_file.write_bytes(b'x'*16385)
            window.load()
            self.assertIn('16', window.status.get())
            connection.busy = True
            window.tick()
            self.assertEqual(str(window.enroll_button['state']), 'disabled')
            self.assertEqual(str(window.offline_button['state']), 'disabled')
            window.close(); connection.cancel.assert_called_once()
            window.tick(); self.assertTrue(root.winfo_exists())
            connection.busy = False
            window.tick()
        finally:
            try: root.destroy()
            except tk.TclError: pass
