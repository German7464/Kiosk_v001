"""Windows durable admission facts; synthetic assignments, not renderer/ready."""
import base64
import copy
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from kiosk.delivery.protocol import PROFILE,encode,sha
from kiosk.display.delivery_authority import PrivateState
from kiosk.publication.exporter import PackageError
from kiosk.publication import authority as a
from kiosk.trust.crypto import generate_private_key,key_id,spki_der


@unittest.skipUnless(os.name=='nt','Windows private-state DPAPI')
class SignedAdmissionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.root,cls.device=generate_private_key(),generate_private_key()

    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.folder=Path(self.tmp.name)
        self.now=2_000_000_000
        clock=patch('kiosk.display.delivery_authority.time.time',return_value=self.now)
        clock.start();self.addCleanup(clock.stop)
        self.scope=dict(group_id='group',origin='https://kiosk.example:20443')
        self.policy=a.signed(self.root,'policy',dict(**self.scope,version=1,issued=self.now-4000,
            expires=self.now+86400,revoked_devices=[],revoked_users=[]))
        self.grant=a.signed(self.root,'device',dict(**self.scope,user_id='alice',role='user',
            device_key=base64.b64encode(spki_der(self.device)).decode(),issued=self.now-4000,
            expires=self.now+86400,can_delegate=True))
        self.state=PrivateState(self.folder)
        self.state.data.update(bootstrap=self.scope,binding=dict(device_id='display1',profile=PROFILE),
                              credential=dict(expires_at=self.now+86400),
                              trust=dict(expires_at=self.now+86400,payload_sha256='a'*64))
        self.state.confirm_time(self.now)
        self.state.confirm_publisher_root(base64.b64encode(spki_der(self.root)).decode(),key_id(self.root))
        self.plans=[];self.assignments=[]
        for i in range(3):
            display=dict(version=1,profile_id='events',revision=1,mode='tv')
            publication=dict(package_id=str(i+1)*64,renderer=dict(build_id='3'*64))
            plan=dict(**self.scope,user_id='alice',device_id=key_id(self.device),policy_version=1,
                      issued=self.now-3000+i*1000,expires=self.now+3600,
                      publication_sha256=sha(encode(publication)),dependencies_sha256='2'*64,renderer='3'*64,
                      targets=[dict(device_id='display1',profile_id='events',profile_version=1,mode='tv',configuration_sha256=sha(encode(display)))],
                      parents=[self.plans[-1]['id']] if self.plans else [])
            if i==1:plan['expires']=self.now-1
            plan['id']=sha(encode(plan));self.plans.append(plan)
            self.assignments.append(dict(version=3,group_id='group',device_id='display1',profile=PROFILE,
                generation=i+1,metadata_sha256=sha(encode(publication)),publication=publication,display=display,
                publisher=dict(approval=a.signed(self.device,'publication',plan),chain=[self.grant],policy=self.policy,
                               ancestry=copy.deepcopy(self.plans[:-1]))))

    def test_missed_expired_middle_accepts_current_and_persists_prior_association(self):
        self.state.accept(self.assignments[0])
        original=copy.deepcopy(self.state.data['accepted']['1'*64])
        reopened=PrivateState(self.folder)
        reopened.accept(self.assignments[2])
        restarted=PrivateState(self.folder)
        self.assertEqual(restarted.data['publisher_anchor']['heads'],[self.plans[2]['id']])
        self.assertEqual(restarted.data['accepted']['1'*64],original)
        self.assertEqual(restarted.accepted('3'*64)['package_id'],'3'*64)
        with self.assertRaises(PackageError):restarted.validate_assignment(self.assignments[0])

    def test_tampered_missing_proof_and_unsigned_preserve_prior_admission(self):
        self.state.accept(self.assignments[0])
        baseline=copy.deepcopy(self.state.data)
        for mutation in ('missing','tampered','unsigned'):
            candidate=copy.deepcopy(self.assignments[2])
            if mutation=='missing':candidate['publisher']['ancestry']=[]
            if mutation=='tampered':candidate['publisher']['ancestry'][-1]['parents']=['f'*64]
            if mutation=='unsigned':candidate.pop('publisher');candidate['version']=2
            with self.assertRaises(PackageError):self.state.validate_assignment(candidate)
            self.assertEqual(self.state.data,baseline)
            self.assertEqual(PrivateState(self.folder).data,baseline)


if __name__=='__main__':unittest.main()
