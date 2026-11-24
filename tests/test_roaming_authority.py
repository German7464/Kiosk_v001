import base64
import copy
import unittest

from kiosk.delivery.protocol import encode, sha
from kiosk.publication import authority as a
from kiosk.trust.crypto import generate_private_key, key_id, spki_der


class PublisherAuthorityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.root, cls.device, cls.child, cls.attacker = [generate_private_key() for _ in range(4)]

    def setUp(self):
        self.now = 2_000_000_000
        self.scope = dict(group_id='group', origin='https://kiosk.example:20443')
        self.policy = dict(**self.scope, version=1, issued=self.now-100,
                           expires=self.now+86400, revoked_devices=[], revoked_users=[])
        self.grant = dict(**self.scope, user_id='user1', role='user',
                          device_key=base64.b64encode(spki_der(self.device)).decode(),
                          issued=self.now-100, expires=self.now+3600, can_delegate=True)
        self.plan = dict(**self.scope, user_id='user1', device_id=key_id(self.device),
                         policy_version=1, issued=self.now, expires=self.now+600,
                         publication_sha256='1'*64, dependencies_sha256='2'*64,
                         renderer='3'*64, parents=[], targets=[dict(device_id='display1',
                         profile_id='events', profile_version=1, mode='tv', configuration_sha256='4'*64)])
        self.identify()

    def identify(self):
        self.plan['id'] = sha(encode({k:v for k,v in self.plan.items() if k!='id'}))

    def verify(self, *, heads=(), signer=None, chain=None, floor=0, ancestry=()):
        return a.approval(a.signed(signer or self.device, 'publication', self.plan),
                          chain or [a.signed(self.root, 'device', self.grant)],
                          a.signed(self.root, 'policy', self.policy), spki_der(self.root),
                          self.scope['group_id'], self.scope['origin'],
                          now=self.now, policy_floor=floor, known_heads=heads,ancestry=ancestry)

    def test_both_roles_can_publish_without_admin_countersignature(self):
        for role in ('user', 'administrator'):
            self.grant['role'] = role
            self.assertEqual(self.verify()[0], self.plan)

    def test_server_key_cannot_authorize_publisher(self):
        with self.assertRaises(ValueError):
            self.verify(chain=[a.signed(self.attacker, 'device', self.grant)])
        with self.assertRaises(ValueError):
            self.verify(signer=self.attacker)

    def test_tampered_target_and_domain_are_refused(self):
        self.plan['targets'][0]['mode'] = 'kiosk'
        with self.assertRaises(ValueError): self.verify()
        with self.assertRaises(ValueError):
            a.verified(a.signed(self.device, 'login', self.plan), spki_der(self.device), 'publication')

    def test_known_conflict_needs_new_explicit_merge(self):
        with self.assertRaises(ValueError): self.verify(heads=['5'*64])
        self.plan['parents'] = ['5'*64]
        self.identify()
        self.verify(heads=['5'*64])
        self.verify(heads=[self.plan['id']])  # idempotent exact retry

    def test_revoked_expired_and_policy_rollback(self):
        with self.assertRaises(ValueError): self.verify(floor=2)
        self.policy['revoked_devices'] = [key_id(self.device)]
        with self.assertRaises(ValueError): self.verify()
        self.policy['revoked_devices'] = []
        self.grant['expires'] = self.now
        with self.assertRaises(ValueError): self.verify()

    def test_bounded_same_user_device_delegation(self):
        child = dict(self.grant, device_key=base64.b64encode(spki_der(self.child)).decode(),
                     can_delegate=False)
        policy = a.policy(a.signed(self.root,'policy',self.policy), spki_der(self.root),
                          self.scope['group_id'], self.scope['origin'], now=self.now)
        chain = [a.signed(self.root,'device',self.grant), a.signed(self.device,'device',child)]
        self.assertEqual(a.permission(chain,spki_der(self.root),policy,self.now)[1],spki_der(self.child))
        for field,value in [('user_id','other'),('role','administrator'),('can_delegate',True),
                            ('expires',self.grant['expires']+1),('group_id','other')]:
            bad=dict(child,**{field:value})
            with self.assertRaises(ValueError):
                a.permission([chain[0],a.signed(self.device,'device',bad)],
                             spki_der(self.root),policy,self.now)
        with self.assertRaises(ValueError):
            a.permission(chain+[chain[-1]],spki_der(self.root),policy,self.now)

    def test_malformed_duplicate_targets_and_unknown_configuration(self):
        for mutation in [lambda: self.plan['targets'].append(copy.deepcopy(self.plan['targets'][0])),
                         lambda: self.plan.update(policy_version=True),
                         lambda: self.plan['targets'][0].update(mode='unknown')]:
            saved=copy.deepcopy(self.plan)
            mutation(); self.identify()
            with self.assertRaises(ValueError): self.verify()
            self.plan=saved

    def test_review_issue_offline_display_needs_authenticated_ancestry(self):
        """A -> missed B -> C uses hash commitments, not a server counter."""
        first=self.plan['id']
        self.plan['parents']=[first];self.plan['publication_sha256']='6'*64;self.identify()
        second=self.plan['id']
        intermediate=copy.deepcopy(self.plan)
        self.plan['parents']=[second];self.plan['publication_sha256']='7'*64;self.identify()
        with self.assertRaisesRegex(ValueError,'publisher_ancestry_required'):
            self.verify(heads=[first])
        result=self.verify(heads=[first],ancestry=[intermediate])
        self.assertEqual(result[0]['id'],self.plan['id'])

    def test_ancestry_cannot_forge_edges_or_make_a_fork_a_descendant(self):
        first=self.plan['id']
        self.plan['parents']=[first];self.plan['publication_sha256']='6'*64;self.identify()
        intermediate=copy.deepcopy(self.plan)
        self.plan['parents']=[intermediate['id']];self.plan['publication_sha256']='7'*64;self.identify()
        forged=copy.deepcopy(intermediate);forged['parents']=['8'*64]
        with self.assertRaises(ValueError):self.verify(heads=[first],ancestry=[forged])
        # Rehashing the forged record cannot change the signed C parent commitment.
        forged['id']=sha(encode({k:v for k,v in forged.items() if k!='id'}))
        with self.assertRaises(ValueError):self.verify(heads=[first],ancestry=[forged])
        with self.assertRaises(ValueError):self.verify(heads=['9'*64],ancestry=[intermediate])
        # A graph with two already-known branches requires a new explicit merge.
        self.verify(heads=[first,intermediate['id']],ancestry=[intermediate])
        with self.assertRaises(ValueError):self.verify(heads=[first,'9'*64],ancestry=[intermediate])

    def test_expired_ancestor_is_not_current_publication_authority(self):
        first=self.plan['id']
        intermediate=copy.deepcopy(self.plan)
        intermediate.update(issued=self.now-2000,expires=self.now-1,parents=[first])
        intermediate['id']=sha(encode({k:v for k,v in intermediate.items() if k!='id'}))
        self.plan['parents']=[intermediate['id']];self.identify()
        self.verify(heads=[first],ancestry=[intermediate])
        self.grant['expires']=self.now
        with self.assertRaises(ValueError):self.verify(heads=[first],ancestry=[intermediate])

    def test_ancestry_duplicates_limits_and_foreign_scope_refused(self):
        ancestor=copy.deepcopy(self.plan)
        self.plan['parents']=[ancestor['id']];self.plan['publication_sha256']='6'*64;self.identify()
        with self.assertRaises(ValueError):self.verify(ancestry=[ancestor,ancestor])
        with self.assertRaises(ValueError):self.verify(ancestry=[ancestor]*129)
        ancestor['group_id']='foreign'
        ancestor['id']=sha(encode({k:v for k,v in ancestor.items() if k!='id'}))
        with self.assertRaises(ValueError):self.verify(ancestry=[ancestor])


if __name__ == '__main__': unittest.main()
