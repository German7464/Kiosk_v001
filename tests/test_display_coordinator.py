import json
import io
from contextlib import redirect_stdout
from pathlib import Path
import subprocess
import sys
import unittest
from unittest.mock import patch

from kiosk.display import coordinator
from kiosk.display.__main__ import main
from kiosk.display.session import install_for_display
from kiosk.publication.exporter import PackageError
from tests import test_display_session as sessions

ENGINE = r'''
import json,os,sys,time
from pathlib import Path
profile,token,behavior=sys.argv[1:]
p=Path(profile);p.mkdir(exist_ok=True,parents=True)
if behavior=='exit': sys.exit(3)
report={'session_id':token,'process_id':os.getpid(),'navigation_success':True,'renderer_ready':True,'startup_failed':False}
if behavior=='stale': report['session_id']='0'*32
if behavior=='pid': report['process_id']+=1
if behavior=='failed': report['startup_failed']=True
if behavior=='navigation': report['navigation_success']=False
if behavior=='renderer': report['renderer_ready']=False
payload=json.dumps(report) if behavior!='oversize' else 'x'*4097
(p/'status.tmp').write_text(payload)
os.replace(p/'status.tmp',p/'display-status.json')
time.sleep(0.5 if behavior=='readyexit' else 30)
'''


class CoordinatorTests(unittest.TestCase):
    def setUp(self):
        sessions.DisplaySessionTests.setUp(self)
        self.cache = self.fixture.root / 'cache'
        self.state = self.fixture.root / 'state'
        self.profile = self.fixture.root / 'profile'
        self.processes = []
        self.addCleanup(self.stop_children)
        install_for_display(self.fixture.destination, self.store.root, self.cache, mode='tv')

    def stop_children(self):
        for process in self.processes:
            coordinator._stop(process)

    def spawn(self, behavior='ready'):
        def launch(shell, view, profile, token):
            choice = behavior(view) if callable(behavior) else behavior
            # Windows venv redirectors spawn a second PID; the native EXE does not.
            process = subprocess.Popen([sys._base_executable, '-c', ENGINE, str(profile), token, choice],
                                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            self.processes.append(process)
            return process
        return patch.object(coordinator, '_spawn', side_effect=launch)

    def session(self, **kwargs):
        return coordinator.display_session(self.store.root, self.cache, self.state, self.profile,
                                           sys.executable, mode='tv', startup_timeout=0.8, **kwargs)

    def test_ready_receipt_owned_lifetime_and_competing_coordinator(self):
        with self.spawn():
            with self.session() as run:
                self.assertFalse(run.fallback)
                self.assertIsNone(run.process.poll())
                receipt = json.loads((self.state / 'last-ready-tv.json').read_bytes())
                self.assertEqual(receipt['view'], run.view.parent.name)
                self.assertEqual(receipt['mode'], 'tv')
                with self.assertRaisesRegex(PackageError, 'store_busy'):
                    with self.session():
                        self.fail('second coordinator acquired ownership')
            self.assertIsNotNone(run.process.poll())

    def test_stale_pid_failed_navigation_renderer_and_oversized_reports_never_confirm(self):
        for behavior in ('stale', 'pid', 'failed', 'navigation', 'renderer', 'oversize', 'exit'):
            with self.subTest(behavior=behavior), self.spawn(behavior):
                with self.assertRaisesRegex(PackageError, 'display_unavailable'):
                    with self.session():
                        self.fail('invalid readiness accepted')
                self.assertFalse((self.state / 'last-ready-tv.json').exists())
                self.assertIsNotNone(self.processes[-1].poll())

    def test_failed_new_engine_tries_confirmed_previous_once_without_pointer_change(self):
        with self.spawn():
            with self.session() as run:
                previous = run.view
        source = sessions.DisplaySessionTests.next_package(self)
        install_for_display(source, self.store.root, self.cache, mode='tv')
        pointer = (self.store.root / 'active.json').read_bytes()
        count = len(self.processes)
        def behavior(view):
            return 'exit' if json.loads((view.parent / 'view.json').read_bytes())['revision'] == '8' else 'ready'
        with self.spawn(behavior), self.session() as run:
            self.assertTrue(run.fallback)
            self.assertEqual(run.view, previous)
        self.assertEqual(len(self.processes) - count, 2)
        self.assertEqual((self.store.root / 'active.json').read_bytes(), pointer)

    def test_corrupt_receipt_cannot_select_an_arbitrary_fallback(self):
        with self.spawn():
            with self.session():
                pass
        path = self.state / 'last-ready-tv.json'
        receipt = json.loads(path.read_bytes())
        receipt['view'] = '../external'
        path.write_text(json.dumps(receipt))
        count = len(self.processes)
        with self.spawn('exit'), self.assertRaisesRegex(PackageError, 'display_unavailable'):
            with self.session():
                pass
        self.assertEqual(len(self.processes) - count, 1)
        self.assertEqual(json.loads(path.read_bytes()), receipt)

    def test_receipt_write_failure_stops_owned_engine_and_retains_receipt(self):
        with self.spawn():
            with self.session():
                pass
        path = self.state / 'last-ready-tv.json'
        original = path.read_bytes()
        with self.spawn(), patch.object(coordinator, '_atomic_write', side_effect=OSError('synthetic disk full')):
            with self.assertRaisesRegex(PackageError, 'display_unavailable'):
                with self.session():
                    pass
        self.assertEqual(path.read_bytes(), original)
        self.assertIsNotNone(self.processes[-1].poll())

    def test_interrupted_startup_stops_owned_engine(self):
        with self.spawn(), patch.object(coordinator, '_await_ready', side_effect=KeyboardInterrupt):
            with self.assertRaises(KeyboardInterrupt):
                with self.session():
                    pass
        self.assertIsNotNone(self.processes[-1].poll())

    def test_overlapping_storage_is_refused_before_spawn(self):
        with self.spawn() as launch, self.assertRaisesRegex(PackageError, 'overlapping_display_storage'):
            with coordinator.display_session(self.store.root, self.cache, self.cache / 'state', self.profile,
                                               sys.executable):
                pass
        launch.assert_not_called()

    def test_cli_waits_for_owned_native_lifetime(self):
        args = ['display', '--store', str(self.store.root), '--cache', str(self.cache),
                '--state', str(self.state), '--profile', str(self.profile), '--shell', sys.executable, '--mode', 'tv']
        output = io.StringIO()
        with self.spawn('readyexit'), patch('sys.argv', args), redirect_stdout(output):
            self.assertEqual(main(), 0)
        self.assertEqual(json.loads(output.getvalue()), {'result': 'ready', 'mode': 'tv', 'fallback': False})
        self.assertIsNotNone(self.processes[-1].poll())

    def test_caller_exception_propagates_after_owned_cleanup(self):
        with self.spawn(), self.assertRaisesRegex(ValueError, '^caller_abort$'):
            with self.session():
                raise ValueError('caller_abort')
        self.assertIsNotNone(self.processes[-1].poll())
