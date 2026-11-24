"""Disposable connected profile/publication/security regression, no physical claims."""
import copy, secrets, tempfile, unittest
from pathlib import Path
from tests.test_operator_delivery import fixture_app, admin_client, enroll
from kiosk.delivery.operator import publish_current_events, distribution
from kiosk.delivery.protocol import DeliveryError, PROFILE, decode
from kiosk.display.cache import renderer_identity


class DeviceProfilesTest(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.app=fixture_app(Path(self.temp.name));self.s=self.app.extensions['device_delivery']
        self.client=admin_client(self.app)
        self.secrets={d:enroll(self.s,d) for d in ('windows','android','legacy')}
        self.caps={'version':1,'platform':'windows','modes':['tv','kiosk'],'content':['events'],
                   'resource_profile':PROFILE,'renderer':renderer_identity()}
        for d in ('windows','android'):
            self.s.report_capabilities(self.s.authenticate(self.secrets[d]),{**self.caps,'platform':d})

    def pub(self):return publish_current_events(self.app,secrets.token_hex(16))
    def assignment(self,d,protocol='display-profile-v1'):
        return self.s.assignment(self.s.authenticate(self.secrets[d]),renderer_identity(),PROFILE,protocol)
    def post(self,path,body):return self.client.post(path,data={'csrf_token':'a'*64,**body},base_url='https://localhost')

    def test_connected_publish_reassign_frozen_ready_and_restart(self):
        first=self.pub();old=self.assignment('windows');identity=self.s.authenticate(self.secrets['windows'])
        self.s.save_profile('shared','Shared Events','kiosk')
        for d in ('windows','android'):self.s.select_profile(d,'shared')
        self.assertEqual(old,self.assignment('windows')) # selection has no display side effect
        second=self.pub();self.assertGreater(second,first)
        for d in ('windows','android'):
            a=self.assignment(d);self.assertEqual(a['display']['mode'],'kiosk')
            self.assertEqual(a['publication'],old['publication'])
        self.assertEqual(identity,self.s.authenticate(self.secrets['windows']))
        body={'version':1,'receipt_id':'ready-old','group_id':'operator-fixture','device_id':'windows',
              'generation':first,'package_id':old['publication']['package_id'],'mode':'tv','session':'old','result':'ready'}
        self.s.receipt(identity,body)
        second_body={**body,'receipt_id':'new','generation':second,'mode':'kiosk'}
        self.s.receipt(identity,second_body)
        with self.assertRaises(DeliveryError):self.s.receipt(identity,{**second_body,'receipt_id':'wrong','mode':'tv'})
        frozen=distribution(self.s,first)['selected'];self.assertEqual(len(frozen['targets']),3);self.assertEqual(frozen['ready'],1)
        self.s.save_profile('shared','Shared TV','tv',1)
        self.assertEqual(self.assignment('windows')['display']['mode'],'kiosk')
        self.s.select_profile('windows','events-default');third=self.pub()
        self.assertGreater(third,second)
        after=distribution(self.s,first)['selected'];self.assertEqual(after['targets'],frozen['targets']);self.assertEqual(after['ready'],1)
        from kiosk.delivery.state import DeliveryState
        reopened=DeliveryState(self.s.root)
        self.assertEqual(reopened.assignment(identity,renderer_identity(),PROFILE,'display-profile-v1')['display']['mode'],'local')
        self.assertEqual(distribution(reopened,second)['selected']['ready'],1)

    def test_legacy_unknown_capabilities_and_negotiation(self):
        self.s.save_profile('tv','TV Events','tv')
        for d in self.secrets:self.s.select_profile(d,'tv')
        generation=self.pub()
        with self.assertRaisesRegex(DeliveryError,'report_capabilities_update_client'):self.assignment('legacy')
        with self.assertRaisesRegex(DeliveryError,'display_profile_update_required'):self.assignment('windows',None)
        self.assertEqual(len(distribution(self.s,generation)['selected']['targets']),2)
        before=self.s.profiles_admin()['capabilities']
        for patch in ({'version':True},{'modes':['touch']},{'modes':[{}]},{'content':['html']},{'platform':'tv'},{'renderer':'bad'}):
            with self.assertRaises(DeliveryError):self.s.report_capabilities(self.s.authenticate(self.secrets['windows']),{**self.caps,**patch})
        self.assertEqual(before,self.s.profiles_admin()['capabilities'])
        self.s.select_profile('legacy','events-default');self.pub()
        self.assertEqual(self.assignment('legacy',None)['version'],1)

    def test_authenticated_csrf_validation_and_escaped_forms(self):
        path='/admin/profiles/save';valid={'profile_id':'shared','name':'<Shared>','mode':'tv','revision':'0'}
        guest=self.app.test_client();self.assertEqual(guest.post(path,data=valid,base_url='https://localhost').status_code,403)
        self.assertEqual(self.client.post(path,data=valid,base_url='https://localhost').status_code,403)
        self.assertEqual(self.post(path,valid).status_code,303)
        self.assertEqual(self.post(path,valid).status_code,409)
        for patch in ({'name':'x'*65},{'name':'bad\nname'},{'mode':'touch'},{'profile_id':'../bad'},{'revision':'-1'}):
            self.assertIn(self.post(path,{**valid,'profile_id':'other',**patch}).status_code,(400,409))
        self.assertEqual(self.post('/admin/devices/windows/profile',{'profile_id':'missing'}).status_code,404)
        self.assertEqual(self.post('/admin/devices/windows/profile',{'profile_id':'shared'}).status_code,303)
        page=self.client.get('/admin/devices',base_url='https://localhost');self.assertEqual(page.status_code,200)
        self.assertIn(b'&lt;Shared&gt;',page.data);self.assertNotIn(b'<Shared>',page.data)
        for secret in self.secrets.values():self.assertNotIn(secret.encode(),page.data)
        self.assertEqual(self.client.delete('/admin/profiles/shared',base_url='https://localhost').status_code,404)
        bearer=self.app.test_client()
        response=bearer.post('/api/v2/client/capabilities',json=self.caps,base_url='https://localhost')
        self.assertEqual(response.status_code,401)
        response=bearer.post('/api/v2/client/capabilities',json=self.caps,base_url='https://localhost',headers={'Authorization':'Bearer '+self.secrets['windows']})
        self.assertEqual(response.status_code,200)

    def test_transaction_rollback_keeps_assignment_and_configuration(self):
        self.pub();old=self.assignment('windows');self.s.save_profile('new','New','tv');self.s.select_profile('windows','new')
        with self.assertRaises(RuntimeError):
            with self.s.connection() as db:
                self.s._assign(db,PROFILE,old['publication']['package_id'],old['metadata_sha256'],'test')
                raise RuntimeError('interrupted transaction')
        self.assertEqual(old,self.assignment('windows'))
