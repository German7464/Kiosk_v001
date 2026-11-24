import base64
import tempfile
import unittest
import copy
import json
from pathlib import Path

from kiosk.delivery.protocol import sha,encode
from kiosk.publication import authority as a
from kiosk.publication.workspace import Workspace, WorkspaceError
from kiosk.trust.crypto import generate_private_key, spki_der


class WorkspaceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.root,cls.key=generate_private_key(),generate_private_key()

    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.time=2_000_000_000
        self.store=Workspace(Path(self.tmp.name)/'workspace.sqlite',spki_der(self.root),'group',
                             'https://kiosk.example',clock=lambda:self.time)
        self.scope=dict(group_id='group',origin='https://kiosk.example')
        self.policy=dict(**self.scope,version=1,issued=self.time-1,expires=self.time+86400,
                         revoked_devices=[],revoked_users=[])
        self.store.install_policy(a.signed(self.root,'policy',self.policy))
        self.grant=dict(**self.scope,user_id='alice',role='user',issued=self.time-1,
                        expires=self.time+20000,can_delegate=True,
                        device_key=base64.b64encode(spki_der(self.key)).decode())
        self.chain=[a.signed(self.root,'device',self.grant)]
        self.browser='b'*64
        self.secret=self.login()
        self.event=dict(title='Event',short_description='',full_description='',event_date='',
                        place='',sort_order=0,status='active',images=[],tags=[])

    def login(self):
        token,doc=self.store.create_login(self.browser,'Chrome on Windows')
        self.store.accept_login(token,a.signed(self.key,'login',doc),self.chain)
        return self.store.consume_login(token,self.browser)[0]

    def test_restart_retains_exact_expired_policy_but_refuses_new_work(self):
        envelope = a.signed(self.root, 'policy', self.policy)
        self.time = self.policy['expires'] + 1
        restarted = Workspace(self.store.path, spki_der(self.root), 'group',
                              self.scope['origin'], clock=lambda: self.time)
        restarted.startup_policy(envelope)
        with restarted.db() as db:
            with self.assertRaisesRegex(ValueError, 'publisher_authority_expired'):
                restarted._device(db, self.chain)
        with self.assertRaises(ValueError):
            restarted.authenticate(self.secret)
        with self.assertRaises(ValueError):
            restarted.install_policy(envelope)
        changed = dict(self.policy, version=2)
        with self.assertRaises(ValueError):
            restarted.startup_policy(a.signed(self.root, 'policy', changed))
        empty = Workspace(Path(self.tmp.name) / 'empty.sqlite', spki_der(self.root),
                          'group', self.scope['origin'], clock=lambda: self.time)
        with self.assertRaises(ValueError):
            empty.startup_policy(envelope)
        fresh = dict(self.policy, version=2, issued=self.time,
                     expires=self.time + 90 * 86400)
        restarted.startup_policy(a.signed(self.root, 'policy', fresh))
        with restarted.db() as db:
            self.assertEqual(restarted._policy(db)[0]['version'], 2)

    def test_login_replay_session_binding_and_fixation(self):
        token,doc=self.store.create_login(self.browser,'Chrome')
        self.assertIsNone(self.store.consume_login(token,self.browser))
        self.store.accept_login(token,a.signed(self.key,'login',doc),self.chain)
        with self.assertRaises(WorkspaceError): self.store.consume_login(token,'x'*64)
        with self.assertRaises(WorkspaceError):
            self.store.accept_login(token,a.signed(self.key,'login',doc),self.chain)
        secret,_=self.store.consume_login(token,self.browser)
        self.assertNotEqual(secret,self.secret)
        self.assertNotEqual(secret,self.browser)
        with self.assertRaises(WorkspaceError): self.store.consume_login(token,self.browser)

    def test_cross_origin_expired_and_unauthorized_login(self):
        token,doc=self.store.create_login(self.browser,'Chrome')
        changed=dict(doc,origin='https://other.example')
        with self.assertRaises(WorkspaceError):
            self.store.accept_login(token,a.signed(self.key,'login',changed),self.chain)
        with self.assertRaises(ValueError):
            self.store.accept_login(token,a.signed(self.root,'login',doc),self.chain)
        self.time+=90
        with self.assertRaises(WorkspaceError): self.store.challenge(token)

    def test_idle_logout_remote_termination_and_revocation(self):
        second=self.login()
        self.store.terminate(self.secret,sha(second.encode()))
        with self.assertRaises(WorkspaceError): self.store.authenticate(second)
        self.store.terminate(self.secret)
        with self.assertRaises(WorkspaceError): self.store.authenticate(self.secret)
        self.secret=self.login();self.time+=900
        with self.assertRaises(WorkspaceError): self.store.authenticate(self.secret)
        self.secret=self.login()
        self.policy['version']=2;self.policy['revoked_users']=['alice']
        self.store.install_policy(a.signed(self.root,'policy',self.policy))
        with self.assertRaises(ValueError): self.store.authenticate(self.secret)

    def test_versions_authors_and_immutable_revisions(self):
        self.assertEqual(self.store.save(self.secret,'event1',0,self.event,{}),1)
        with self.assertRaises(WorkspaceError): self.store.save(self.secret,'event1',0,self.event,{})
        self.store.ready(self.secret,'event1',1)
        self.store.save(self.secret,'event1',1,dict(self.event,title='Changed'),{})
        current=self.store.objects(self.secret)[0]
        self.assertFalse(current['ready']);self.assertEqual(current['published_version'],0)
        self.assertEqual(current['author'],'alice')
        with self.store.db() as db:
            self.assertEqual(db.execute('SELECT count(*) FROM revisions').fetchone()[0],2)
            # No published Events table exists or is changed by these writes.
            self.assertIsNone(db.execute("SELECT name FROM sqlite_master WHERE name='events'").fetchone())

    def test_dependency_changes_invalidate_readiness(self):
        self.store.save(self.secret,'event1',0,self.event,{})
        self.store.save(self.secret,'event2',0,self.event,{'event1':1})
        with self.assertRaises(WorkspaceError): self.store.ready(self.secret,'event2',1)
        self.store.ready(self.secret,'event1',1)
        self.store.ready(self.secret,'event2',1)
        self.store.save(self.secret,'event1',1,dict(self.event,title='New'),{})
        self.assertFalse(self.store.objects(self.secret)[1]['ready'])
        with self.assertRaises(WorkspaceError): self.store.ready(self.secret,'event2',1)

    def test_interrupted_transaction_and_restart_preserve_state(self):
        self.store.save(self.secret,'event1',0,self.event,{})
        with self.assertRaises(RuntimeError):
            with self.store.db() as db:
                db.execute('DELETE FROM objects')
                raise RuntimeError('interrupted')
        reopened=Workspace(self.store.path,spki_der(self.root),'group','https://kiosk.example',clock=lambda:self.time)
        self.assertEqual(reopened.objects(self.secret)[0]['version'],1)

    def test_history_bound_keeps_closest_links_without_globally_blocking_publication(self):
        fixture=json.loads(Path('android/testdata/roaming-ancestry-v1-public.json').read_text(encoding='utf-8'))
        template=json.loads(base64.b64decode(fixture['proof']['approval']['payload']))['value']
        history=[]
        with self.store.db() as db:
            for i in range(150):
                plan=copy.deepcopy(template);plan.pop('id')
                plan['parents']=[history[-1]['id']] if history else []
                plan['id']=sha(encode(plan));history.append(plan)
                # Synthetic approved-row setup exercises bounded graph retrieval,
                # not publication approval or a native ready receipt.
                db.execute('INSERT INTO plans VALUES (?,?,?,?)',
                           (plan['id'],encode({'plan':plan}),encode({'fixture':True}),self.time))
            proof=self.store._ancestry(db,[history[-1]['id']])
        self.assertEqual(len(proof),128)
        self.assertIn(history[-1]['id'],{node['id'] for node in proof})
        current=copy.deepcopy(template);current.pop('id');current['parents']=[history[-1]['id']]
        current['id']=sha(encode(current))
        a.check_ancestry(current,[history[-1]['id']],proof)
        with self.assertRaisesRegex(ValueError,'publisher_ancestry_required'):
            a.check_ancestry(current,[history[0]['id']],proof)


if __name__=='__main__': unittest.main()
