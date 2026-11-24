import base64
import json
import re
import tempfile
import unittest
from pathlib import Path

from kiosk.app import create_app
from kiosk.delivery.protocol import PROFILE
from kiosk.publication import authority as a
from kiosk.trust.crypto import generate_private_key,spki_der


class RoamingWebTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.root,cls.device=generate_private_key(),generate_private_key()

    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        root=Path(self.tmp.name)
        self.origin='https://kiosk.example'
        self.app=create_app(dict(TESTING=True,SECRET_KEY='disposable-test-only',INSTANCE_DIR=root/'instance',
            DATABASE_PATH=root/'instance/kiosk.sqlite',PUBLIC_UPLOAD_DIR=root/'public',PRIVATE_UPLOAD_DIR=root/'private',
            ROAMING_WORKSPACE=dict(database=root/'editor.sqlite',root_spki=base64.b64encode(spki_der(self.root)).decode(),
                                   group_id='group',origin=self.origin)))
        self.client=self.app.test_client()
        self.store=self.app.extensions['roaming_workspace'];self.store.clock=lambda:2_000_000_000
        policy=dict(group_id='group',origin=self.origin,version=1,issued=1_999_999_999,
                    expires=2_000_086_400,revoked_users=[],revoked_devices=[])
        self.store.install_policy(a.signed(self.root,'policy',policy))
        self.grant=dict(group_id='group',origin=self.origin,user_id='alice',role='user',
            issued=1_999_999_999,expires=2_000_086_400,can_delegate=True,
            device_key=base64.b64encode(spki_der(self.device)).decode())
        self.chain=[a.signed(self.root,'device',self.grant)]

    def get(self,path,**kw):return self.client.get('/editor'+path,base_url=self.origin,**kw)
    def post(self,path,data,csrf=None):
        return self.client.post('/editor'+path,base_url=self.origin,json=data,
                                headers={'X-CSRF-Token':csrf} if csrf else {})
    def token(self):
        return re.search('data-csrf="([a-f0-9]{64})"',self.get('').text).group(1)
    def login(self):
        csrf=self.token()
        result=self.post('/login/start',{},csrf).json
        accepted=self.post('/native/accept',dict(token=result['token'],chain=self.chain,
            approval=a.signed(self.device,'login',result['context'])))
        self.assertEqual(accepted.status_code,200)
        response=self.post('/login/poll',dict(token=result['token']),csrf)
        self.assertEqual(response.status_code,200)
        self.assertNotEqual(csrf,response.json['csrf'])
        return response.json['csrf']

    def test_csrf_origin_and_auth_boundaries(self):
        self.assertEqual(self.get('/objects').status_code,401)
        self.assertEqual(self.post('/login/start',{}).status_code,403)
        self.assertEqual(self.client.get('/editor',base_url='http://kiosk.example').status_code,403)
        self.assertEqual(self.client.get('/editor',base_url='https://other.example').status_code,403)
        csrf=self.token()
        self.assertEqual(self.post('/native/challenge',{}).status_code,400)
        self.assertEqual(self.post('/login/start',{},'é'*64).status_code,403)
        response=self.post('/login/start',{},csrf)
        self.assertEqual(response.status_code,200)
        self.assertIn('; Secure;',response.headers['Set-Cookie'])
        self.assertIn('frame-ancestors',response.headers['Content-Security-Policy'])

    def test_draft_save_logout_and_copied_cookie_refusal(self):
        csrf=self.login()
        event=dict(title='Only a draft',short_description='',full_description='',event_date='',place='',
                   sort_order=0,status='active',images=[],tags=[])
        payload=dict(expected_version=0,payload=event,dependencies={})
        self.assertEqual(self.post('/objects/event1',payload,csrf).status_code,201)
        self.assertEqual(self.post('/objects/event1',payload,csrf).status_code,409)
        self.assertEqual(self.get('/objects').json['objects'][0]['published_version'],0)
        with self.app.app_context():
            from kiosk.database import get_database
            self.assertEqual(get_database().execute('SELECT COUNT(*) FROM events').fetchone()[0],0)
        cookie=self.client.get_cookie('session',domain='kiosk.example').value
        self.assertEqual(self.post('/logout',{},csrf).status_code,200)
        self.client.set_cookie('session',cookie,domain='kiosk.example')
        self.assertEqual(self.get('/objects').status_code,401)

    def test_opt_in_pages_keep_legacy_content_routes_read_only(self):
        from kiosk.core.credentials import save_admin_password
        from kiosk.database import get_database

        self.assertEqual(self.get('/pages/objects').status_code, 404)
        self.store.stage6_pages = True
        self.assertEqual(self.get('/pages/objects').status_code, 401)
        csrf = self.login()
        library = self.get('/pages')
        self.assertEqual(library.status_code, 200)
        self.assertIn('page_library.js', library.text)
        self.assertNotIn('id="events-module-toggle"', library.text)
        self.assertNotIn('data-new-kind="assignment"', library.text)
        dataset = 'dataset-' + '1' * 32
        draft = dict(expected_version=0, payload=dict(schema=1, name='Shared', module='events', events=[]),
                     dependencies={})
        self.assertEqual(self.post('/pages/objects/' + dataset, draft).status_code, 403)
        self.assertEqual(self.post('/pages/objects/' + dataset, draft, csrf).status_code, 201)
        self.assertEqual(self.post('/pages/objects/' + dataset, draft, csrf).status_code, 409)
        self.assertEqual(self.post('/objects/' + dataset, draft, csrf).status_code, 400)
        self.assertEqual(self.get('/pages/objects').json['objects'][0]['published_version'], 0)
        self.assertEqual(self.get('/objects').json['objects'], [])

        save_admin_password(self.app, 'disposable-stage6-smoke-password', setup=True)
        page = self.client.get('/admin/login', base_url=self.origin)
        csrf = re.search(r'<meta name="csrf-token" content="([^"]+)"', page.text).group(1)
        login = self.client.post('/admin/login', base_url=self.origin,
                                 data=dict(username='admin', password='disposable-stage6-smoke-password'),
                                 headers={'X-CSRF-Token': csrf})
        self.assertEqual(login.status_code, 302)
        page = self.client.get('/admin', base_url=self.origin)
        csrf = re.search(r'<meta name="csrf-token" content="([^"]+)"', page.text).group(1)
        paths = ('settings', 'events/create', 'events/1/edit', 'events/1/tags',
                 'events/1/delete', 'events/1/toggle', 'events/1/move',
                 'tags/create', 'tags/1/edit', 'tags/1/delete')
        public_before = self.client.get('/api/version', base_url=self.origin).json
        for path in paths:
            with self.subTest(path=path):
                response = self.client.post('/admin/' + path, base_url=self.origin,
                                            headers={'X-CSRF-Token': csrf})
                self.assertEqual(response.status_code, 409)
                self.assertEqual(response.json['error'], 'shared_drafts_required')
        with self.app.app_context():
            self.assertEqual(get_database().execute('SELECT COUNT(*) FROM events').fetchone()[0], 0)
            self.assertEqual(get_database().execute('SELECT COUNT(*) FROM tags').fetchone()[0], 0)
        self.assertEqual(self.client.get('/api/version', base_url=self.origin).json, public_before)

    def test_two_signed_browser_sessions_reject_stale_page_edit(self):
        self.store.stage6_pages = True
        alice_client, alice_csrf = self.client, self.login()
        dataset = 'dataset-' + '2' * 32
        endpoint = '/pages/objects/' + dataset
        draft = dict(expected_version=0, payload=dict(schema=1, name='Initial', module='events', events=[]),
                     dependencies={})
        self.assertEqual(self.post(endpoint, draft, alice_csrf).status_code, 201)

        bob_client = self.app.test_client()
        self.client = bob_client
        self.device = generate_private_key()
        self.grant = dict(self.grant, user_id='bob',
                          device_key=base64.b64encode(spki_der(self.device)).decode())
        self.chain = [a.signed(self.root, 'device', self.grant)]
        bob_csrf = self.login()
        bob_version = self.get('/pages/objects').json['objects'][0]['version']

        self.client = alice_client
        alice_save = dict(draft, expected_version=1, payload=dict(draft['payload'], name='Alice saved'))
        self.assertEqual(self.post(endpoint, alice_save, alice_csrf).json['version'], 2)
        self.client = bob_client
        bob_save = dict(draft, expected_version=bob_version,
                        payload=dict(draft['payload'], name='Bob unsaved'))
        refused = self.post(endpoint, bob_save, bob_csrf)
        self.assertEqual(refused.status_code, 409)
        self.assertEqual(refused.json['error'], 'draft_version_conflict')
        shared = self.get('/pages/objects').json['objects'][0]
        self.assertEqual((shared['author'], shared['payload']['name'], shared['published_version']),
                         ('alice', 'Alice saved', 0))


class RoamingPrepareWebTests(unittest.TestCase):
    """Browser prepare -> exact package -> native approval -> signed assignment."""

    @classmethod
    def setUpClass(cls):
        cls.root,cls.device=generate_private_key(),generate_private_key()

    def setUp(self):
        from kiosk.delivery.protocol import PROFILE,encode
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        root=Path(self.tmp.name);self.origin='https://kiosk.example:20443'
        self.app=create_app(dict(TESTING=True,SECRET_KEY='disposable-test-only',
            INSTANCE_DIR=root/'instance',DATABASE_PATH=root/'instance/kiosk.sqlite',
            PUBLIC_UPLOAD_DIR=root/'public',PRIVATE_UPLOAD_DIR=root/'private',
            DEVICE_DELIVERY_ROOT=root/'delivery',
            ROAMING_WORKSPACE=dict(database=root/'editor.sqlite',
                root_spki=base64.b64encode(spki_der(self.root)).decode(),
                group_id='group',origin=self.origin)))
        self.client=self.app.test_client()
        self.store=self.app.extensions['roaming_workspace'];self.store.clock=lambda:2_000_000_000
        self.delivery=self.app.extensions['device_delivery']
        (self.delivery.root/'public.json').write_bytes(encode(dict(version=1,group_id='group',
            server_id='server',origin=self.origin,bootstrap={},trust={})))
        from kiosk.display.cache import renderer_identity
        capabilities=dict(version=1,platform='windows',modes=['tv'],content=['events'],
                          resource_profile=PROFILE,renderer=renderer_identity())
        with self.delivery.connection() as db:
            db.execute("INSERT OR REPLACE INTO display_profiles VALUES ('events-tv','Events TV','tv',3)")
            db.execute("INSERT OR REPLACE INTO device_profiles VALUES ('display1','events-tv')")
            db.execute("INSERT OR REPLACE INTO device_capabilities VALUES ('display1',?)",
                       (encode(capabilities),))
            db.execute('INSERT OR REPLACE INTO devices VALUES (?,?,?,?,?,0)',
                       ('display1',PROFILE,'c'*64,'v'*64,2_000_086_400))
        policy=dict(group_id='group',origin=self.origin,version=1,issued=1_999_999_999,
                    expires=2_000_086_400,revoked_users=[],revoked_devices=[])
        self.store.install_policy(a.signed(self.root,'policy',policy))
        self.chain=[a.signed(self.root,'device',dict(group_id='group',origin=self.origin,
            user_id='alice',role='user',issued=1_999_999_999,expires=2_000_086_400,
            can_delegate=True,device_key=base64.b64encode(spki_der(self.device)).decode()))]

    def get(self,path,**kw):return self.client.get('/editor'+path,base_url=self.origin,**kw)
    def post(self,path,data,csrf=None):
        return self.client.post('/editor'+path,base_url=self.origin,json=data,
                                headers={'X-CSRF-Token':csrf} if csrf else {})
    def login(self):
        csrf=re.search('data-csrf="([a-f0-9]{64})"',self.get('').text).group(1)
        result=self.post('/login/start',{},csrf).json
        self.assertEqual(self.post('/native/accept',dict(token=result['token'],chain=self.chain,
            approval=a.signed(self.device,'login',result['context']))).status_code,200)
        return self.post('/login/poll',dict(token=result['token']),csrf).json['csrf']

    def test_prepare_requires_csrf_and_reports_missing_delivery_or_drafts(self):
        self.assertEqual(self.post('/native/prepare',{}).status_code,403)
        csrf=self.login()
        self.assertEqual(self.post('/native/prepare',{},csrf).status_code,400)

    def test_frozen_draft_package_review_candidate_and_signed_assignment(self):
        csrf=self.login()
        event=dict(title='Prepared Event',short_description='',full_description='',event_date='',
                   place='',sort_order=0,status='active',images=[],tags=['News'])
        self.assertEqual(self.post('/objects/1',dict(expected_version=0,payload=event,
                                                     dependencies={}),csrf).status_code,201)
        self.assertEqual(self.post('/objects/1/ready',{'version':1},csrf).status_code,200)
        self.assertEqual(self.post('/native/settings',{'expected_version':0,
            'values':{'site_title':'Museum'}},csrf).status_code,200)
        targets=self.get('/native/targets').json['targets']
        self.assertEqual([item['device_id'] for item in targets],['display1'])
        prepared=self.post('/native/prepare',{'selected':{'1':1},'targets':targets,'parents':[]},csrf)
        self.assertEqual(prepared.status_code,200,prepared.text)
        result=prepared.json;self.assertEqual(result['revision'],1)
        self.assertIn('data:image/png;base64,',result['qr'])
        materials=self.get('/native/candidates/'+result['id']+'/package/data/events.json')
        self.assertEqual(materials.status_code,200)
        data=json.loads(materials.data)
        self.assertEqual(data['events'][0]['title'],'Prepared Event')
        self.assertEqual(data['settings'],{'site_title':'Museum'})
        self.assertEqual(self.get('/native/candidates/'+result['id']+'/package/manifest.json')
                         .status_code,200)
        self.assertEqual(self.get('/native/candidates/'+result['id']+'/package/nope')
                         .status_code,404)
        candidate=self.get('/native/candidates/'+result['id']).json
        self.assertEqual(candidate['content_version'],1)
        self.assertEqual(candidate['plan']['id'],result['id'])
        # Anything that changes the frozen objects after preparation blocks approval.
        self.assertEqual(self.post('/objects/1',dict(expected_version=1,
            payload=dict(event,title='Changed'),dependencies={}),csrf).status_code,201)
        refused=self.post('/native/approve',{'id':result['id'],'chain':self.chain,
            'approval':a.signed(self.device,'publication',candidate['plan'])},csrf)
        self.assertEqual(refused.status_code,409)
        # Restore the same content as a new immutable revision; the old plan stays
        # refused because it pins the exact prepared revision, never content equality.
        self.assertEqual(self.post('/objects/1',dict(expected_version=2,payload=event,
                                                     dependencies={}),csrf).status_code,201)
        self.assertEqual(self.post('/objects/1/ready',{'version':3},csrf).status_code,200)
        again=self.post('/native/prepare',{'selected':{'1':3},'targets':targets,'parents':[]},csrf)
        self.assertEqual(again.status_code,200,again.text)
        final=self.get('/native/candidates/'+again.json['id']).json
        approved=self.post('/native/approve',{'id':again.json['id'],'chain':self.chain,
            'approval':a.signed(self.device,'publication',final['plan'])},csrf)
        self.assertEqual(approved.status_code,200,approved.text)
        # One ordinary User Publish action distributes without an administrator step.
        self.assertEqual(approved.json['distribution']['state'],'ready')
        self.assertEqual(approved.json['distribution']['targets'],1)
        distributed=self.post('/native/distribute',{'id':again.json['id']},csrf)
        self.assertEqual(distributed.status_code,200,distributed.text)
        self.assertEqual(distributed.json['generation'],1)
        self.assertEqual(distributed.json['targets'],1)
        status=self.get('/native/candidates/'+again.json['id']+'/status').json
        self.assertTrue(status['approved'])
        self.assertEqual(status['distribution']['targets'],1)
        assignment=self.delivery.assignment({'device_id':'display1','profile':PROFILE},
            final['publication']['renderer']['build_id'],PROFILE,'display-profile-v1')
        self.assertEqual(assignment['version'],3)
        self.assertEqual(assignment['publisher']['approval'],
                         a.signed(self.device,'publication',final['plan']))
        self.assertEqual(assignment['publisher']['chain'],self.chain)

    def test_user_approval_reports_pending_distribution_and_retry_when_targets_changed(self):
        csrf=self.login()
        event=dict(title='Pending',short_description='',full_description='',event_date='',
                   place='',sort_order=0,status='active',images=[],tags=[])
        self.assertEqual(self.post('/objects/1',dict(expected_version=0,payload=event,
                                                     dependencies={}),csrf).status_code,201)
        self.assertEqual(self.post('/objects/1/ready',{'version':1},csrf).status_code,200)
        targets=self.get('/native/targets').json['targets']
        prepared=self.post('/native/prepare',{'selected':{'1':1},'targets':targets,'parents':[]},csrf)
        self.assertEqual(prepared.status_code,200,prepared.text)
        candidate=self.get('/native/candidates/'+prepared.json['id']).json
        # The display changes after review: the signature is still stored, but no
        # broader/unsigned distribution may commit.
        with self.delivery.connection() as db:
            db.execute("UPDATE devices SET revoked=1 WHERE device_id='display1'")
        approved=self.post('/native/approve',{'id':prepared.json['id'],'chain':self.chain,
            'approval':a.signed(self.device,'publication',candidate['plan'])},csrf)
        self.assertEqual(approved.status_code,200,approved.text)
        self.assertEqual(approved.json['state'],'approved')
        self.assertEqual(approved.json['distribution']['state'],'pending')
        self.assertEqual(approved.json['distribution']['error'],'publisher_targets_changed')
        self.assertEqual(self.post('/native/distribute',{'id':prepared.json['id']},csrf).status_code,409)
        status=self.get('/native/candidates/'+prepared.json['id']+'/status').json
        self.assertTrue(status['approved'])
        self.assertIsNone(status['distribution'])
        with self.delivery.connection(write=False) as db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM assignments').fetchone()[0],0)


if __name__=='__main__':unittest.main()
