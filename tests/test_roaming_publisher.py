import os
import tempfile
import unittest
from pathlib import Path

from kiosk.delivery.protocol import encode,sha
from kiosk.publication.publisher import LocalPublisher
from kiosk.publication import authority as a
from tools.publisher_authority import init,authorize,revoke


@unittest.skipUnless(os.name=='nt','Windows DPAPI boundary')
class LocalPublisherTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name);self.now=2_000_000_000
        self.password='disposable authority test password'
        self.public=init(self.root/'offline','group','https://kiosk.example:20443',self.password,self.now)
        self.primary=LocalPublisher(self.root/'primary')
        self.identity=self.primary.create()
        request=self.primary.public_request('group',self.public['origin'],'alice',self.now)
        self.bundle=authorize(self.root/'offline',self.password,request,'user','alice',self.now)
        self.install(self.primary,self.bundle)

    def install(self,device,bundle):
        import base64
        return device.install(base64.b64decode(bundle['root_spki']),self.public['root_sha256'],
            bundle['policy'],bundle['chain'],bundle['group_id'],bundle['origin'],self.now)

    def test_real_dpapi_unique_keys_restart_and_own_device_authorization(self):
        self.assertNotIn(b'PRIVATE KEY',(self.root/'primary/publisher.dpapi').read_bytes())
        reopened=LocalPublisher(self.root/'primary')
        self.assertEqual(reopened.public_identity(),self.identity)
        child=LocalPublisher(self.root/'child');identity=child.create()
        self.assertNotEqual(identity['device_id'],self.identity['device_id'])
        request=child.public_request('group',self.public['origin'],'alice',self.now)
        bundle=reopened.authorize_own_device(request,self.now)
        self.assertEqual(self.install(child,bundle)['user_id'],'alice')
        with self.assertRaises(ValueError):reopened.authorize_own_device(request,self.now)
        with self.assertRaises(ValueError):child.authorize_own_device(self.primary.public_request('group',self.public['origin'],'alice',self.now),self.now)

    def test_cross_user_escalation_wrong_root_revocation_and_wrong_password(self):
        child=LocalPublisher(self.root/'child');child.create()
        request=child.public_request('group',self.public['origin'],'other',self.now)
        with self.assertRaises(ValueError):self.primary.authorize_own_device(request,self.now)
        with self.assertRaises(ValueError):
            authorize(self.root/'offline','wrong password',request,'administrator','other',self.now)
        import base64
        with self.assertRaises(ValueError):
            child.install(base64.b64decode(self.public['root_spki']),'0'*64,self.bundle['policy'],self.bundle['chain'],'group',self.public['origin'],self.now)
        policy=revoke(self.root/'offline',self.password,self.identity['device_id'],self.now)
        revoked=dict(self.bundle,policy=policy)
        with self.assertRaises(ValueError):self.install(self.primary,revoked)

    def test_native_login_domain_and_challenge_expiry(self):
        context=dict(version=1,action='login',id='a'*64,browser='b'*64,group_id='group',
                     origin=self.public['origin'],summary='Chrome',issued=self.now,expires=self.now+90)
        response=self.primary.login(context,self.now)
        import base64
        signer=a.permission(response['chain'],base64.b64decode(self.public['root_spki']),
            a.policy(self.bundle['policy'],base64.b64decode(self.public['root_spki']),'group',self.public['origin'],self.now),self.now)[1]
        self.assertEqual(a.verified(response['approval'],signer,'login'),context)
        with self.assertRaises(ValueError):self.primary.login(dict(context,action='publication'),self.now)
        with self.assertRaises(ValueError):self.primary.login(context,self.now+90)


if __name__=='__main__':unittest.main()
