"""Windows user-scoped publisher key and revalidated local review boundary.

No network/UI/JavaScript callbacks can call a generic digest signing operation.
This is not safe on the same compromised OS as a delivery server. DPAPI protects
at rest, not against malware running as the authorized Windows user.
"""
import base64
from dataclasses import dataclass
from pathlib import Path
import re
import secrets

from kiosk.delivery.protocol import decode, encode, sha, text
from kiosk.display.delivery_capture import validate_metadata, verify_captured
from kiosk.display.native_crypto import protect
from kiosk.publication.exporter import _plain_path
from kiosk.publication.store import PublicationStore, _atomic_write
from kiosk.trust.crypto import generate_private_key, key_id, load_private, private_pem, spki_der
from . import authority


@dataclass(frozen=True)
class Review:
    token: str
    document: bytes
    captured: Path
    packages: dict = None


def _is_page_document(document):
    return (isinstance(document, dict)
            and document.get('version') == authority.PAGE_PLAN_VERSION
            and isinstance(document.get('plan'), dict)
            and document['plan'].get('version') == authority.PAGE_PLAN_VERSION
            and 'revision' in document and 'targets' in document)


def native_token(value):
    """Strict short-lived Maintenance ticket format; never echo the value."""
    if not isinstance(value, str) or re.fullmatch('[0-9a-f]{64}', value) is None:
        raise ValueError('publisher_native_ticket_refused')
    return value


def verify_mapping(document, captured):
    """Recompute the exact frozen-draft public data from the candidate itself.

    This is the trusted-review boundary for the snapshot/package mapping: the
    server-exported Events bytes must equal the canonical derivation of the
    signed plan's own objects, settings and content revision.
    """
    from . import mapping
    metadata = validate_metadata(document['publication'])
    expected = mapping.derive(document['objects'], document.get('settings', {}),
                              document.get('content_version'))
    if str(expected['content_version']) != metadata['revision']:
        raise ValueError('publisher_review_revision_substitution')
    actual = decode(_plain_path(Path(captured) / 'package', 'data/events.json').read_bytes())
    if actual != expected:
        raise ValueError('publisher_review_snapshot_substitution')
    return expected


class LocalPublisher:
    def __init__(self, root):
        self.root=Path(root)
        self.file=self.root/'publisher.dpapi'
        self.pending={}

    def create(self):
        """Explicit own-device creation; never replaces a missing/unreadable key."""
        with PublicationStore(self.root)._lease():
            if self.file.exists():
                return self.public_identity()
            from tools.lan_trust_admin import _restrict_acl
            _restrict_acl(self.root)
            private=generate_private_key()
            payload=dict(private_key=private_pem(private),device_id=key_id(private))
            _atomic_write(self.file,protect(encode(payload)))
        return self.public_identity()

    def _read(self):
        with self.file.open('rb') as stream:raw=stream.read(262145)
        if len(raw)>262144:
            raise ValueError('publisher_key_state_limit')
        value=decode(protect(raw,decrypt=True))
        key=load_private(value['private_key'])
        if value['device_id']!=key_id(key):
            raise ValueError('publisher_key_identity_refused')
        return value,key

    def public_identity(self):
        _,key=self._read()
        return dict(device_key=base64.b64encode(spki_der(key)).decode(),device_id=key_id(key))

    def scope(self, now):
        """Exact installed public scope for the native UI (never a server response)."""
        state,_=self._read()
        device=self._permission(state,now)
        return dict(group_id=state['group_id'],origin=state['origin'],user_id=device['user_id'])

    def status(self, now):
        """Permission and expiry for maintenance warnings; fails closed when stale."""
        state,_=self._read()
        device=self._permission(state,now)
        return dict(device_id=state['device_id'],user_id=device['user_id'],role=device['role'],
                    group_id=state['group_id'],origin=state['origin'],
                    expires=device['expires'],policy_version=state['policy_floor'])

    def public_request(self,group_id,origin,user_id,now):
        from kiosk.delivery.protocol import text
        _,key=self._read()
        request=dict(**self.public_identity(),group_id=text(group_id),origin=authority.origin(origin),
                     user_id=text(user_id),action='add-device',nonce=secrets.token_hex(32),issued=now,expires=now+90)
        return dict(request=request,proof=authority.signed(key,'device-request',request))

    def install(self, root_spki, expected_fingerprint, policy, chain, group_id, origin, now):
        """Native import after an independently authenticated administrator action.
        Only public permission material is imported; local private key is retained.
        """
        if sha(root_spki)!=expected_fingerprint:
            raise ValueError('publisher_root_not_authenticated')
        with PublicationStore(self.root)._lease():
            state,key=self._read()
            if state.get('root_spki') and state['root_spki']!=base64.b64encode(root_spki).decode():
                raise ValueError('publisher_root_replacement_requires_recovery')
            if state.get('group_id') and state['group_id']!=text(group_id):
                raise ValueError('publisher_group_replacement_requires_recovery')
            if state.get('origin') and state['origin']!=authority.origin(origin):
                raise ValueError('publisher_origin_replacement_requires_recovery')
            old=state.get('policy')
            if old is not None:
                previous=authority.verified(old,root_spki,'policy')
                incoming=authority.verified(policy,root_spki,'policy')
                if (incoming['version']==previous['version'] and
                        encode(previous)!=encode(incoming)):
                    raise ValueError('publisher_policy_generation_conflict')
                if incoming['version']<previous['version']:
                    raise ValueError('publisher_policy_rollback')
            current=authority.policy(policy,root_spki,group_id,origin,now,
                                     floor=state.get('policy_floor',0))
            device,spki=authority.permission(chain,root_spki,current,now)
            if spki!=spki_der(key):
                raise ValueError('publisher_permission_for_other_device')
            state.update(root_spki=base64.b64encode(root_spki).decode(),policy=policy,chain=chain,
                         group_id=group_id,origin=origin,policy_floor=current['version'])
            _atomic_write(self.file,protect(encode(state)))
        self.pending.clear()
        return device

    def recover(self, root_spki, expected_fingerprint, policy, chain, group_id, origin, now,
                confirmation):
        """Explicit supported recovery: replaces the pinned root/policy and clears
        local ancestry. Requires the independently supplied fingerprint and a
        typed confirmation; never used by ordinary import.
        """
        if confirmation!='REPLACE' or sha(root_spki)!=expected_fingerprint:
            raise ValueError('publisher_recovery_not_confirmed')
        with PublicationStore(self.root)._lease():
            state,key=self._read()
            current=authority.policy(policy,root_spki,group_id,origin,now,floor=0)
            device,spki=authority.permission(chain,root_spki,current,now)
            if spki!=spki_der(key):
                raise ValueError('publisher_permission_for_other_device')
            # Preserve the device-bound private key and identity; clear only
            # ancestry/pending/old authority facts before rebinding.
            for name in ('publication_heads','pending_approval','device_challenges','policy_floor'):
                state.pop(name,None)
            state.update(root_spki=base64.b64encode(root_spki).decode(),policy=policy,chain=chain,
                         group_id=group_id,origin=origin,policy_floor=current['version'])
            _atomic_write(self.file,protect(encode(state)))
        self.pending.clear()
        return device

    def _permission(self,state,now):
        root=base64.b64decode(state['root_spki'],validate=True)
        policy=authority.policy(state['policy'],root,state['group_id'],state['origin'],now,
                                floor=state['policy_floor'])
        return authority.permission(state['chain'],root,policy,now)[0]

    def login(self, context, now):
        """UI calls only after showing the exact challenge and explicit Accept."""
        from kiosk.delivery.protocol import fields
        state,key=self._read();self._permission(state,now)
        fields(context,'version action id browser origin group_id summary issued expires')
        if (type(context['version']) is not int or context['version']!=1 or context['action']!='login' or
                context['origin']!=state['origin'] or context['group_id']!=state['group_id'] or
                type(context['issued']) is not int or type(context['expires']) is not int or
                not context['issued']<=now<context['expires'] or context['expires']-context['issued']>90):
            raise ValueError('publisher_login_context_refused')
        return dict(approval=authority.signed(key,'login',context),chain=state['chain'])

    def authorize_own_device(self,request,now):
        """Native explicit Add my device, distinct from login/publication.
        Only a directly root-authorized device may issue one nondelegating child.
        The request proof binds the new device's independently generated key.
        """
        from kiosk.delivery.protocol import fields
        fields(request,'request proof')
        fields(request['request'],'device_key device_id group_id origin user_id action nonce issued expires')
        new=authority._b64(request['request']['device_key'],1024)
        if key_id(new)!=request['request']['device_id']:
            raise ValueError('publisher_new_key_identity')
        if authority.verified(request['proof'],new,'device-request')!=request['request']:
            raise ValueError('publisher_new_key_possession')
        with PublicationStore(self.root)._lease():
            state,key=self._read()
            parent=self._permission(state,now)
            document=request['request']
            if (document['action']!='add-device' or
                    any(document[f]!=parent[f] for f in ('group_id','origin','user_id')) or
                    type(document['issued']) is not int or type(document['expires']) is not int or
                    not document['issued']<=now<document['expires'] or document['expires']-document['issued']>90):
                raise ValueError('publisher_device_challenge_refused')
            from kiosk.delivery.protocol import digest
            digest(document['nonce'])
            used=state.get('device_challenges',[])
            if document['nonce'] in used or len(used)>=1024:
                raise ValueError('publisher_device_challenge_replayed_or_full')
            if len(state['chain'])!=1 or not parent['can_delegate'] or key_id(new)==state['device_id']:
                raise ValueError('publisher_device_delegation_refused')
            child=dict(parent,device_key=request['request']['device_key'],issued=now,can_delegate=False)
            chain=[*state['chain'],authority.signed(key,'device',child)]
            root=base64.b64decode(state['root_spki'],validate=True)
            current=authority.policy(state['policy'],root,state['group_id'],state['origin'],now,
                                     floor=state['policy_floor'])
            authority.permission(chain,root,current,now)
            state['device_challenges']=[*used,document['nonce']]
            _atomic_write(self.file,protect(encode(state)))
            return dict(root_spki=state['root_spki'],policy=state['policy'],chain=chain,
                        group_id=state['group_id'],origin=state['origin'])

    def _review(self,state,document,captured,now):
        device=self._permission(state,now)
        plan=authority.validate_plan(document['plan'],now=now)
        authority.check_ancestry(plan,state.get('publication_heads',[]),document.get('ancestry',[]))
        if (plan['device_id']!=state['device_id'] or plan['user_id']!=device['user_id'] or
                plan['group_id']!=state['group_id'] or plan['origin']!=state['origin'] or
                plan['policy_version']!=state['policy_floor'] or
                plan['dependencies_sha256']!=sha(encode(document['objects']))):
            raise ValueError('publisher_review_scope_refused')
        metadata=validate_metadata(document['publication'])
        if plan['publication_sha256']!=sha(encode(metadata)) or plan['renderer']!=metadata['renderer']['build_id']:
            raise ValueError('publisher_review_content_substitution')
        verify_captured(captured,metadata)
        # Check all downloaded byte inventories as well as the client renderer.
        from kiosk.delivery.publication import inventory
        for mode in ('package','kiosk','tv'):
            if inventory(captured/mode)!=metadata[mode]['files']:
                raise ValueError('publisher_review_inventory_substitution')
        verify_mapping(document,captured)

    def review(self,document,captured,now):
        state,_=self._read()
        captured=Path(captured)
        raw=encode(document)
        if len(raw)>2*1024*1024:
            raise ValueError('publisher_review_limit')
        self._review(state,decode(raw),captured,now)
        self.pending.clear()
        ticket=Review(secrets.token_hex(32),raw,captured)
        self.pending[ticket.token]=sha(raw)
        return ticket

    def _review_page(self,state,document,packages,now):
        """Independently re-derive every projection and rehash every target package."""
        from . import page_release
        from kiosk.display import page_view
        self._review_page_document(state,document,now)
        if (not isinstance(packages,dict)
                or set(packages)!={target['device_id'] for target in document['targets']}):
            raise ValueError('publisher_review_target_set')
        pin=page_view.renderer_pin()
        for target in document['targets']:
            renderer=target['metadata']['publication']['renderer']
            if (renderer['js_sha256']!=pin['js_sha256'] or
                    renderer['css_sha256']!=pin['css_sha256'] or
                    renderer['build_id']!=pin['build_id']):
                raise ValueError('publisher_review_renderer_mismatch')
        files={}
        for target in document['targets']:
            tree=page_view.read_package_tree(packages[target['device_id']])
            files[target['device_id']]={'package':tree,'kiosk':{},'tv':{}}
        page_release.review(document,now=now,known_heads=state.get('publication_heads',[]),files=files)

    def _review_page_document(self,state,document,now):
        """Validate plan, ancestry and local scope before any target bytes arrive."""
        device=self._permission(state,now)
        plan=authority.validate_group_plan(document['plan'],now=now)
        authority.check_ancestry(plan,state.get('publication_heads',[]),document.get('ancestry',[]))
        if (plan['device_id']!=state['device_id'] or plan['user_id']!=device['user_id'] or
                plan['group_id']!=state['group_id'] or plan['origin']!=state['origin'] or
                plan['policy_version']!=state['policy_floor']):
            raise ValueError('publisher_review_scope_refused')
        if not isinstance(document.get('targets'),list) or not document['targets']:
            raise ValueError('publisher_review_target_set')
        if {target.get('device_id') for target in document['targets']} != \
                {target['device_id'] for target in plan['targets']}:
            raise ValueError('publisher_review_target_set')

    def validate_page_document(self,document,now):
        """Structural/scope review of a native-open response, before any download."""
        state,_=self._read()
        if not _is_page_document(document):
            raise ValueError('publisher_page_document')
        raw=encode(document)
        if len(raw)>2*1024*1024:
            raise ValueError('publisher_review_limit')
        document=decode(raw)
        self._review_page_document(state,document,now)
        return document

    def page_open_approval(self,token,content_origin,maintenance_origin,now):
        """Explicit native open approval; binds only the exact ticket hash and origins."""
        token=native_token(token)
        state,key=self._read()
        self._permission(state,now)
        if content_origin!=state['origin']:
            raise ValueError('publisher_content_origin_refused')
        value=dict(token_sha256=sha(token.encode('ascii')),
                   content_origin=content_origin,maintenance_origin=maintenance_origin)
        return dict(approval=authority.signed(key,'page-review-open',value),chain=state['chain'])

    def review_page(self,document,packages,now):
        """Explicit native review of one immutable v2 page plan and exact target bytes."""
        state,_=self._read()
        packages={str(key):Path(value) for key,value in (packages or {}).items()}
        if not _is_page_document(document):
            raise ValueError('publisher_page_document')
        raw=encode(document)
        if len(raw)>2*1024*1024:
            raise ValueError('publisher_review_limit')
        self._review_page(state,decode(raw),packages,now)
        self.pending.clear()
        ticket=Review(secrets.token_hex(32),raw,Path('.'),packages)
        self.pending[ticket.token]=sha(raw)
        return ticket

    def publish_page(self,ticket,now,*,token=None,maintenance_origin=None):
        """Sign only the exact reviewed v2 plan; the v2 domain is never used by v1."""
        if (not isinstance(ticket,Review) or ticket.packages is None or
                self.pending.pop(ticket.token,None)!=sha(ticket.document)):
            raise ValueError('publisher_review_required')
        if token is not None:
            token=native_token(token)
        with PublicationStore(self.root)._lease():
            state,key=self._read()
            if state.get('pending_approval'):
                raise ValueError('publisher_pending_approval_unresolved')
            document=decode(ticket.document)
            self._review_page(state,document,ticket.packages,now)
            result=dict(approval=authority.page_signed(key,document['plan']),chain=state['chain'],
                        policy=state['policy'],ancestry=list(document.get('ancestry',[])))
            state['pending_approval']=dict(id=document['plan']['id'],approval=result['approval'],
                                           chain=result['chain'],policy=result['policy'],
                                           ancestry=result['ancestry'],kind='pages')
            if token is not None:
                state['pending_approval'].update(token=token,
                                                 maintenance_origin=maintenance_origin)
            _atomic_write(self.file,protect(encode(state)))
            return result

    def discard_pending(self,identity):
        """Drop a definitively refused approval (for example a changed 409 plan)."""
        from kiosk.delivery.protocol import digest
        digest(identity)
        with PublicationStore(self.root)._lease():
            state,_=self._read()
            pending=state.get('pending_approval')
            if isinstance(pending,dict) and pending.get('id')==identity:
                state.pop('pending_approval',None)
                _atomic_write(self.file,protect(encode(state)))
        return True

    def pending_approval(self):
        """Exact signed approval awaiting server acknowledgement (no re-signing)."""
        state,_=self._read()
        return state.get('pending_approval')

    def confirm_published(self,identity):
        """Commit the local head only after the server accepted this exact approval."""
        from kiosk.delivery.protocol import digest
        digest(identity)
        with PublicationStore(self.root)._lease():
            state,_=self._read()
            pending=state.get('pending_approval')
            if not isinstance(pending,dict) or pending.get('id')!=identity:
                raise ValueError('publisher_pending_approval_missing')
            state['publication_heads']=[identity]
            state.pop('pending_approval',None)
            _atomic_write(self.file,protect(encode(state)))
        return True

    def publish(self,ticket,now):
        """One explicit native Publish action after preview. Reverify under the
        key lease immediately before signing; ticket is single-use on failure too.
        """
        if (not isinstance(ticket,Review) or ticket.packages is not None or
                self.pending.pop(ticket.token,None)!=sha(ticket.document)):
            raise ValueError('publisher_review_required')
        with PublicationStore(self.root)._lease():
            state,key=self._read()
            if state.get('pending_approval'):
                raise ValueError('publisher_pending_approval_unresolved')
            document=decode(ticket.document)
            self._review(state,document,ticket.captured,now)
            result=dict(approval=authority.signed(key,'publication',document['plan']),chain=state['chain'])
            # Keep the exact signed approval durable while the local head stays at
            # the last server-acknowledged plan; a lost response must not advance it.
            state['pending_approval']=dict(id=document['plan']['id'],approval=result['approval'],
                                           chain=result['chain'])
            _atomic_write(self.file,protect(encode(state)))
            return result
