"""Only new advisory discovery and affected lifecycle/UI coverage."""
from contextlib import contextmanager
import json
from pathlib import Path
import queue
import socket
import tempfile
import threading
import time
import unittest
from unittest.mock import Mock, patch

from kiosk import discovery as d
from kiosk.delivery.protocol import encode
from kiosk.display.connect import Connection, public_input

N = 'a'*32
ADDRESS = 'https://192.168.1.165:9443'


class DiscoveryTests(unittest.TestCase):
    def test_strict_query_schema_utf8_duplicate_types_and_padding(self):
        self.assertEqual(len(d.query(N)), 512)
        self.assertEqual(d.parse(d.query(N), 'query')['nonce'], N)
        valid = dict(protocol=d.PROTOCOL, type='query', nonce=N)
        invalid = [b'', b'x'*513, b'\xff'.ljust(512), b'[]'.ljust(512),
                   b'{"nonce":"x","nonce":"y"}'.ljust(512), encode(valid),
                   encode(dict(valid, other=1)).ljust(512), encode(dict(valid, nonce=True)).ljust(512),
                   encode(dict(valid, nonce='A'*32)).ljust(512), encode(dict(valid, type='reply')).ljust(512)]
        for raw in invalid:
            with self.subTest(raw=raw[:100]), self.assertRaises(ValueError): d.parse(raw, 'query')
        reordered = json.dumps(valid).encode().ljust(512)
        self.assertEqual(d.parse(reordered, 'query')['nonce'], N)

    def test_reply_nonce_origin_controls_and_encoded_limits(self):
        hint = dict(d.public_hint(ADDRESS, '<plain & untrusted>'), nonce=N)
        self.assertEqual(d.parse(encode(hint), 'reply', N)['label'], '<plain & untrusted>')
        bad = [dict(hint, nonce='b'*32), dict(hint, origin='http://host:12'),
               dict(hint, origin=ADDRESS+'/'), dict(hint, label='x\n'), dict(hint, label='x\x7f'),
               dict(hint, label='x\u202e'), dict(hint, label='x'*65), dict(hint, extra=1),
               dict(hint, origin='https://'+'x'*400+':9443'), dict(hint, label=True)]
        for value in bad:
            with self.subTest(value=value), self.assertRaises(ValueError): d.parse(encode(value), 'reply', N)
        for raw in [b'\xff', b'{}'*300, b'{"nonce":"x","nonce":"y"}', br'"\ud800"']:
            with self.assertRaises(ValueError): d.parse(raw, 'reply', N)

    def test_rate_per_source_global_and_bounded_bookkeeping(self):
        limiter = d.RateLimit()
        for i in range(1000):
            self.assertEqual(limiter.allow(str(i), 10), i < 32)
        self.assertEqual(len(limiter.sources), 32)
        self.assertFalse(limiter.allow('0', 10.9))
        self.assertTrue(limiter.allow('0', 11))
        for i in range(1000): limiter.allow(str(i), 20+i)
        self.assertLessEqual(len(limiter.sources), 256)
        self.assertLessEqual(len(limiter.total), 32)

    def test_responder_bind_conflict_cleanup_and_actual_unicast_unit_fixture(self):
        # Some host networking software rewrites wildcard bind to a LAN address.
        # Same-host unicast is deliberately NOT two-host broadcast acceptance.
        with patch.object(d, 'PORT', 0):
            responder = d.Responder(ADDRESS, 'Unit fixture')
            self.assertTrue(responder.start())
        port = responder.socket.getsockname()[1]
        address = responder.socket.getsockname()[0]
        address = '127.0.0.1' if address == '0.0.0.0' else address
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as client:
                client.bind((address, 0))
                client.settimeout(.2)
                client.sendto(d.query(N), (address, port))
                raw, _ = client.recvfrom(513)
                self.assertLessEqual(len(raw),512)
                self.assertEqual(d.parse(raw,'reply',N)['origin'], ADDRESS)
                client.sendto(d.query(N), (address, port))
                with self.assertRaises(socket.timeout): client.recvfrom(513)
            with patch.object(d, 'PORT', port):
                conflict = d.Responder(ADDRESS, 'Other')
                self.assertFalse(conflict.start())
                self.assertEqual(conflict.error['state'], 'bind_failed')
                conflict.close()
        finally: responder.close()
        self.assertFalse(responder.thread.is_alive())
        self.assertEqual(responder.socket.fileno(), -1)

    def test_opt_in_config_error_and_runtime_shutdown(self):
        app = Mock(); app.config = {}; app.extensions = {}
        with patch.object(d, 'Responder') as responder:
            self.assertIsNone(d.start_discovery(app)); responder.assert_not_called()
            app.config['LAN_DISCOVERY'] = {'enabled':'yes','origin':ADDRESS,'label':'x'}
            self.assertIsNone(d.start_discovery(app)); responder.assert_not_called()
            self.assertEqual(app.extensions['lan_discovery_error'],'invalid_configuration')
            app.config['LAN_DISCOVERY'] = {'enabled':True,'origin':ADDRESS,'label':'x'}
            responder.return_value.start.return_value = False
            self.assertIs(d.start_discovery(app),responder.return_value)
            self.assertTrue(app.logger.error.called)
        from kiosk.transport.runtime import ManagedHttps
        runtime = ManagedHttps(Mock())
        runtime.discovery = Mock()
        runtime.close()
        runtime.discovery.close.assert_called_once()
        runtime.close(); runtime.discovery.close.assert_called_once()

    def test_windows_oversize_error_discard(self):
        sock = Mock(); sock.recvfrom.side_effect = OSError(10040,'oversize')
        self.assertEqual(d.receive(sock),(b'',None))

    def search_fixture(self, replies=None, *, cancelled=False):
        stop = threading.Event()
        clock = [0.0]
        sent = []
        class Sock:
            closed = False
            def __enter__(self): return self
            def __exit__(self,*args): self.closed=True
            def setsockopt(self,*args): pass
            def bind(self,*args): pass
            def settimeout(self,*args): pass
            def getsockname(self): return ('0.0.0.0',50123)
            def sendto(self,raw,target): sent.append((raw,target))
            def recvfrom(self,size):
                clock[0] += .01 if replies else .05
                if cancelled: stop.set()
                if replies: return replies.pop(0), ('192.168.1.117',47751)
                raise socket.timeout()
        sock = Sock()
        with patch.object(d.socket,'socket',return_value=sock), patch.object(d.time,'monotonic',side_effect=lambda:clock[0]), patch.object(d.secrets,'token_hex',return_value=N):
            result = d.search(stop)
        self.assertTrue(sock.closed)
        return result,sent,clock[0]

    def test_search_traffic_result_dedup_caps_stale_and_spoofed_hints(self):
        def reply(i, n=N):return encode(dict(d.public_hint(f'https://host{i}:9443','untrusted'),nonce=n))
        replies=[reply(0,'b'*32),b'x'*513,reply(0),reply(0)]+[reply(i) for i in range(40)]
        results,sent,elapsed=self.search_fixture(replies)
        self.assertEqual(len(results),32)
        self.assertEqual(results[0]['origin'],'https://host0:9443')
        self.assertEqual(len(sent),3)
        self.assertTrue(all(target==('255.255.255.255',47751) and len(raw)==512 for raw,target in sent))
        self.assertLessEqual(elapsed,3.06)
        # A nonce-matched spoof is deliberately still only an address/label, never authority.
        self.assertEqual(set(results[0]),{'origin','label'})

    def test_search_empty_cancel_and_input_flood_are_bounded(self):
        results,sent,_=self.search_fixture(); self.assertEqual(results,[]);self.assertEqual(len(sent),3)
        results,sent,elapsed=self.search_fixture(cancelled=True)
        self.assertEqual(results,[]);self.assertEqual(len(sent),1);self.assertLess(elapsed,.1)
        flood=[b'bad']*1000
        self.search_fixture(flood)
        self.assertEqual(len(flood),744)

    def test_one_worker_existing_lease_no_native_authority_or_saved_mutation(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);(root/'private').mkdir()
            saved=root/'private/native.dpapi';saved.write_bytes(b'unchanged opaque state')
            entered=threading.Event()
            def slow(stop): entered.set();stop.wait(1);return []
            factory=Mock(side_effect=AssertionError('no client/enrollment allowed'))
            connection=Connection(root,root/'shell.exe',client_factory=factory)
            with patch.object(d,'search',side_effect=slow):
                self.assertTrue(connection.start('discover'));self.assertTrue(entered.wait(1))
                self.assertFalse(connection.start('discover'));self.assertFalse(connection.start('display'))
                connection.cancel();connection.thread.join(2)
            self.assertFalse(connection.busy);factory.assert_not_called()
            self.assertEqual(saved.read_bytes(),b'unchanged opaque state')
            self.assertEqual(connection.events.get()['state'],'discovery_cancelled')

    def test_tk_explicit_selection_manual_fallback_busy_saved_and_cancel(self):
        import tkinter as tk
        from kiosk.display.connect_ui import Window
        root=tk.Tk();root.withdraw()
        connection=Mock();connection.events=queue.Queue();connection.busy=False
        try:
            window=Window(root,connection);connection.reset_mock()
            connection.start.return_value=True
            window.search();connection.start.assert_called_once_with('discover')
            connection.reset_mock()
            connection.busy=True;window.tick()
            connection.busy=False
            connection.events.put(dict(state='discovered',hints=[dict(origin=ADDRESS,label='<b>NOT trusted</b>')]))
            window.tick();self.assertEqual(window.address.get(),'')
            self.assertIn('<b>NOT trusted</b>',window.results.get(0))
            window.results.selection_set(0);window.select()
            self.assertEqual(window.address.get(),ADDRESS);self.assertFalse(window.confirmed.get())
            connection.start.assert_not_called()
            window.enroll();connection.start.assert_not_called()
            connection.events.put(dict(state='discovered',hints=[]));window.tick()
            self.assertIn('вручную',window.status.get());self.assertEqual(window.address.get(),ADDRESS)
            connection.events.put(dict(state='discovery_failed'));window.tick()
            self.assertIn('вручную',window.status.get())
            connection.busy=True;window.tick();window.search();window.select()
            self.assertEqual(str(window.search_button['state']),'disabled');connection.start.assert_not_called()
            connection.busy=False;window.saved=True;window.tick();window.search();window.select()
            self.assertEqual(str(window.search_button['state']),'disabled');self.assertEqual(window.address.get(),ADDRESS)
            window.close();connection.cancel.assert_called_once()
        finally: root.destroy()

    def test_discovered_wrong_origin_rejected_before_existing_pairing(self):
        raw=Path('tests/fixtures/device-delivery-v1-public.json').read_bytes()
        anchor=json.loads(raw)['bootstrap']
        with self.assertRaises(ValueError):
            public_input(encode(anchor),'https://spoof:9443',now=anchor['issued_at']+1)
