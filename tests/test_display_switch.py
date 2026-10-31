import json
from pathlib import Path
import subprocess
import sys
import threading
import unittest
from unittest.mock import patch

from kiosk.display import coordinator
from kiosk.display.session import install_for_display
from kiosk.publication.exporter import PackageError
from tests import test_display_session as sessions

ENGINE = r'''
import json,os,sys,time
from pathlib import Path
profile,token,view,behavior=sys.argv[1:]
p=Path(profile);p.mkdir(exist_ok=True,parents=True)
v=Path(view);d=json.loads((v/'view.json').read_bytes())
report={'session_id':token,'process_id':os.getpid(),'navigation_success':True,'renderer_ready':True,'startup_failed':False,'view_key':v.name,'package_sha256':d['package_sha256'],'mode':d['mode']}
def save():
 (p/'status.tmp').write_text(json.dumps(report));os.replace(p/'status.tmp',p/'display-status.json')
save();seen='';attempts=0;deadline=time.monotonic()+30
while time.monotonic()<deadline:
 try: command=json.loads((p/'display-command.json').read_bytes())
 except (OSError,ValueError):time.sleep(.02);continue
 if command['request_id']==seen:time.sleep(.02);continue
 seen=command['request_id'];attempts+=1
 with (p/'requests.log').open('a') as output:output.write(seen+'\n')
 if behavior in ('delay','latefailed'):time.sleep(.4)
 reject=behavior=='failed' or (behavior=='latefailed' and attempts==1)
 report['switch_request_id']=seen;report['switch_state']='failed' if reject else 'ready'
 if not reject:report.update(view_key=command['view'],package_sha256=command['package_sha256'],mode=command['mode'])
 if behavior=='token':report['switch_request_id']='0'*32
 if behavior=='key':report['view_key']='0'*64
 if behavior=='package':report['package_sha256']='0'*64
 if behavior=='mode':report['mode']='kiosk'
 save()
'''


class DisplaySwitchTests(unittest.TestCase):
    def setUp(self):
        sessions.DisplaySessionTests.setUp(self)
        self.cache = self.fixture.root / 'cache'
        self.state = self.fixture.root / 'state'
        self.profile = self.fixture.root / 'profile'
        self.processes = []
        self.addCleanup(self.stop_children)
        install_for_display(self.fixture.destination, self.store.root, self.cache, mode='tv')
        self.next_source = sessions.DisplaySessionTests.next_package(self)

    def stop_children(self):
        for process in self.processes:
            coordinator._stop(process)

    def spawn(self, behavior='ready'):
        def launch(shell, view, profile, token):
            process = subprocess.Popen([sys._base_executable, '-c', ENGINE, str(profile), token, str(view.parent), behavior],
                                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            self.processes.append(process)
            return process
        return patch.object(coordinator, '_spawn', side_effect=launch)

    def session(self):
        return coordinator.display_session(self.store.root, self.cache, self.state, self.profile,
                                           sys.executable, mode='tv', startup_timeout=1)

    def install_next(self):
        return install_for_display(self.next_source, self.store.root, self.cache, mode='tv')

    def test_success_same_process_exact_receipt_and_idempotence(self):
        with self.spawn(), self.session() as run:
            old = run.view
            target = self.install_next()
            pointer = (self.store.root / 'active.json').read_bytes()
            pid = run.process.pid
            self.assertTrue(run.switch_to_active(timeout=1))
            self.assertEqual(run.view, target)
            self.assertNotEqual(run.view, old)
            self.assertEqual(run.process.pid, pid)
            self.assertIsNone(run.process.poll())
            receipt = json.loads((self.state / 'last-ready-tv.json').read_bytes())
            self.assertEqual(receipt['view'], target.parent.name)
            command = (self.profile / 'display-command.json').read_bytes()
            self.assertFalse(run.switch_to_active(timeout=1))
            self.assertEqual((self.profile / 'display-command.json').read_bytes(), command)
            self.assertEqual((self.store.root / 'active.json').read_bytes(), pointer)

    def test_failed_candidate_preserves_old_receipt_and_requires_explicit_retry(self):
        with self.spawn('failed'), self.session() as run:
            old = run.view
            receipt = (self.state / 'last-ready-tv.json').read_bytes()
            self.install_next()
            with self.assertRaisesRegex(PackageError, '^display_switch_failed$'):
                run.switch_to_active(timeout=1)
            command = (self.profile / 'display-command.json').read_bytes()
            with self.assertRaisesRegex(PackageError, '^display_switch_refused$'):
                run.switch_to_active(timeout=1)
            self.assertEqual((self.profile / 'display-command.json').read_bytes(), command)
            self.assertEqual(run.view, old)
            self.assertEqual((self.state / 'last-ready-tv.json').read_bytes(), receipt)
            self.assertIsNone(run.process.poll())
            with self.assertRaisesRegex(PackageError, '^display_switch_failed$'):
                run.switch_to_active(timeout=1, retry=True)
            self.assertNotEqual((self.profile / 'display-command.json').read_bytes(), command)

    def test_timeout_reconciles_same_request_without_resending(self):
        with self.spawn('delay'), self.session() as run:
            target = self.install_next()
            with self.assertRaisesRegex(PackageError, '^display_switch_timeout$'):
                run.switch_to_active(timeout=.1)
            token = run.pending[0]
            command = (self.profile / 'display-command.json').read_bytes()
            self.assertTrue(run.switch_to_active(timeout=1))
            self.assertEqual(run.view, target)
            self.assertIsNone(run.pending)
            self.assertEqual((self.profile / 'display-command.json').read_bytes(), command)
            self.assertEqual((self.profile / 'requests.log').read_text().splitlines(), [token])

    def test_wrong_ack_identity_never_changes_receipt(self):
        for behavior in ('token', 'key', 'package', 'mode'):
            with self.subTest(behavior=behavior):
                install_for_display(self.fixture.destination, self.store.root, self.cache, mode='tv')
                with self.spawn(behavior), self.session() as run:
                    old = run.view
                    receipt = (self.state / 'last-ready-tv.json').read_bytes()
                    self.install_next()
                    with self.assertRaisesRegex(PackageError, '^display_switch_timeout$'):
                        run.switch_to_active(timeout=.2)
                    self.assertEqual(run.view, old)
                    self.assertEqual((self.state / 'last-ready-tv.json').read_bytes(), receipt)

    def test_receipt_failure_records_actual_view_then_repairs_without_new_switch(self):
        with self.spawn(), self.session() as run:
            target = self.install_next()
            receipt = (self.state / 'last-ready-tv.json').read_bytes()
            original = coordinator._atomic_write
            def fail_receipt(path, payload):
                if path.name.startswith('last-ready'):
                    raise OSError('synthetic ENOSPC')
                return original(path, payload)
            with patch.object(coordinator, '_atomic_write', side_effect=fail_receipt):
                with self.assertRaisesRegex(PackageError, '^display_switch_storage_failed$'):
                    run.switch_to_active(timeout=1)
            self.assertEqual(run.view, target)
            self.assertTrue(run.receipt_pending)
            self.assertEqual((self.state / 'last-ready-tv.json').read_bytes(), receipt)
            command = (self.profile / 'display-command.json').read_bytes()
            self.assertFalse(run.switch_to_active(timeout=1))
            self.assertFalse(run.receipt_pending)
            self.assertEqual((self.profile / 'display-command.json').read_bytes(), command)

    def test_competing_switch_call_is_refused_without_command(self):
        with self.spawn(), self.session() as run:
            with run._switch_lock:
                with self.assertRaisesRegex(PackageError, '^display_switch_busy$'):
                    run.switch_to_active()
            self.assertFalse((self.profile / 'display-command.json').exists())

    def test_watch_checks_small_pointers_and_switches_on_change(self):
        with self.spawn(), self.session() as run:
            publisher = threading.Timer(.3, self.install_next)
            publisher.start()
            self.addCleanup(publisher.join)
            original = run.switch_to_active
            with patch.object(run, 'switch_to_active', wraps=original) as switch:
                events = coordinator.follow_publications(run, interval=.1)
                self.assertEqual(next(events), {'result': 'switched', 'mode': 'tv'})
                self.assertEqual(switch.call_count, 2)
                coordinator._stop(run.process)
                self.assertEqual(list(events), [])

    def test_watch_bounds_timeout_reconciliation_without_resending_command(self):
        with self.spawn('key'), self.session() as run:
            self.install_next()
            original = run.switch_to_active
            with patch.object(run, 'switch_to_active', side_effect=lambda: original(timeout=.1)) as switch:
                events = coordinator.follow_publications(run, interval=.1)
                for _ in range(2):
                    self.assertEqual(next(events)['code'], 'display_switch_timeout')
                command = (self.profile / 'display-command.json').read_bytes()
                stopper = threading.Timer(.4, coordinator._stop, args=(run.process,))
                stopper.start()
                self.addCleanup(stopper.join)
                self.assertEqual(list(events), [])
                self.assertEqual(switch.call_count, 2)
                self.assertEqual((self.profile / 'display-command.json').read_bytes(), command)

    def test_watch_rechecks_new_publication_after_prior_timed_out_request_fails(self):
        from tests import test_publication_export as fixtures
        with self.spawn('latefailed'), self.session() as run:
            self.install_next()
            with self.assertRaisesRegex(PackageError, '^display_switch_timeout$'):
                run.switch_to_active(timeout=.1)
            with fixtures.connection(self.fixture.db) as db:
                db.execute("UPDATE settings SET value='9' WHERE key='content_version'")
            source = self.fixture.root / 'third'
            self.fixture.export(source)
            target = install_for_display(source, self.store.root, self.cache, mode='tv')
            original = run.switch_to_active
            with patch.object(run, 'switch_to_active', side_effect=lambda: original(timeout=1)):
                events = coordinator.follow_publications(run, interval=.1)
                self.assertEqual(next(events)['code'], 'display_switch_failed')
                self.assertEqual(next(events), {'result': 'switched', 'mode': 'tv'})
                self.assertEqual(run.view, target)
                coordinator._stop(run.process)
                self.assertEqual(list(events), [])
