"""Offline publisher administrator. Run outside the delivery-server OS.

Only public root, permission and policy records may be transferred to the server.
Passwords use getpass; no private material appears in stdout or CLI arguments.
"""
import argparse
import base64
import getpass
from pathlib import Path
import time

from kiosk.delivery.protocol import decode, digest, encode, fields, sha, text
from kiosk.publication import authority as a
from kiosk.publication.store import _atomic_write
from kiosk.trust.crypto import generate_private_key, key_id, load_private, private_pem, spki_der


def read(path,limit=131072):
    with Path(path).open('rb') as stream:raw=stream.read(limit+1)
    if len(raw)>limit:raise ValueError('authority_input_limit')
    return decode(raw)


def init(root,group_id,origin,password,now):
    if root.exists():raise ValueError('authority_destination_exists')
    root.mkdir(parents=True)
    from tools.lan_trust_admin import _restrict_acl
    _restrict_acl(root)
    key=generate_private_key()
    _atomic_write(root/'authority-key.pem',private_pem(key,password).encode('ascii'))
    pub=dict(root_spki=base64.b64encode(spki_der(key)).decode(),root_sha256=key_id(key),
             group_id=text(group_id),origin=a.origin(origin))
    _atomic_write(root/'public.json',encode(pub))
    policy=dict(group_id=group_id,origin=origin,version=1,issued=now,
                expires=now+a.MAX_AUTHORITY_SECONDS,revoked_devices=[],revoked_users=[])
    _atomic_write(root/'policy.json',encode(a.signed(key,'policy',policy)))
    return pub


def _load_key(root,password):
    public=read(root/'public.json')
    with (root/'authority-key.pem').open('rb') as stream:raw=stream.read(16385)
    if len(raw)>16384:raise ValueError('authority_key_limit')
    key=load_private(raw.decode('ascii'),password)
    if key_id(key)!=public['root_sha256'] or base64.b64encode(spki_der(key)).decode()!=public['root_spki']:
        raise ValueError('authority_key_mismatch')
    return key,public


def load(root,password,now):
    key,public=_load_key(root,password)
    policy=a.policy(read(root/'policy.json'),spki_der(key),public['group_id'],public['origin'],now)
    return key,public,policy


def renew(root,password,now,confirmation):
    """Explicit offline administrator maintenance, including after expiry.

    Verify the previous policy at its signed issuance time only to authenticate
    the recovery input. This never makes it usable for ordinary authorization.
    Keep the root and revocations; old endpoint grants are not extended.
    """
    if confirmation != 'RENEW':
        raise ValueError('authority_renewal_not_confirmed')
    key,public=_load_key(root,password)
    envelope=read(root/'policy.json')
    previous=a.verified(envelope,spki_der(key),'policy')
    previous=a.policy(envelope,spki_der(key),public['group_id'],public['origin'],
                      previous['issued'])
    if type(now) is not int or now < previous['issued']:
        raise ValueError('authority_renewal_time_rollback')
    updated=dict(previous,version=previous['version']+1,issued=now,
                 expires=now+a.MAX_AUTHORITY_SECONDS)
    result=a.signed(key,'policy',updated)
    a.policy(result,spki_der(key),public['group_id'],public['origin'],now)
    _atomic_write(root/'policy.json',encode(result))
    return result


def authorize(root,password,request,role,user_id,now):
    key,public,policy=load(root,password,now)
    fields(request,'request proof')
    document=request['request']
    fields(document,'device_key device_id group_id origin user_id action nonce issued expires')
    new=a._b64(document['device_key'],1024)
    if (a.verified(request['proof'],new,'device-request')!=document or
            document['device_id']!=key_id(new) or document['group_id']!=public['group_id'] or
            document['origin']!=public['origin'] or document['user_id']!=text(user_id) or
            document['action']!='add-device' or type(document['issued']) is not int or
            type(document['expires']) is not int or not document['issued']<=now<document['expires'] or
            document['expires']-document['issued']>90 or role not in ('administrator','user')):
        raise ValueError('authority_device_request_refused')
    digest(document['nonce'])
    receipt=root/('request-'+document['nonce']+'.json')
    if receipt.exists():raise ValueError('authority_request_already_used')
    if len(list(root.glob('request-*.json')))>=1024:raise ValueError('authority_request_capacity')
    grant=dict(group_id=public['group_id'],origin=public['origin'],user_id=user_id,role=role,
               device_key=document['device_key'],issued=now,expires=policy['expires'],can_delegate=True)
    chain=[a.signed(key,'device',grant)]
    a.permission(chain,spki_der(key),policy,now)
    result=dict(**public,policy=read(root/'policy.json'),chain=chain)
    # A receipt contains public authorization only. Crash after this commit may
    # require re-exporting this exact receipt, never issuing a different grant.
    _atomic_write(receipt,encode(result))
    return result


def revoke(root,password,device_id,now):
    key,public,policy=load(root,password,now)
    digest(device_id)
    if device_id not in policy['revoked_devices']:
        policy['revoked_devices']=sorted([*policy['revoked_devices'],device_id])
        policy['version']+=1
        envelope=a.signed(key,'policy',policy)
        _atomic_write(root/'policy.json',encode(envelope))
    return read(root/'policy.json')


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('operation',choices=('init','authorize','revoke','renew'))
    parser.add_argument('--authority-root',required=True,type=Path)
    parser.add_argument('--group');parser.add_argument('--origin');parser.add_argument('--user')
    parser.add_argument('--role',choices=('user','administrator'),default='user')
    parser.add_argument('--request',type=Path);parser.add_argument('--device')
    parser.add_argument('--output',required=True,type=Path)
    args=parser.parse_args();root=args.authority_root.resolve()
    if root.is_relative_to(Path.cwd().resolve()):
        parser.error('Keep authority outside source/server roots and outside delivery-server OS.')
    if args.output.exists():parser.error('Public output already exists; choose a fresh destination.')
    password=getpass.getpass('Publisher authority password: ')
    if len(password)<12:parser.error('Use at least 12 characters.')
    now=int(time.time())
    try:
        if args.operation=='init':
            if not args.group or not args.origin:parser.error('--group and --origin required')
            if getpass.getpass('Confirm password: ')!=password:parser.error('Password mismatch')
            result=init(root,args.group,args.origin,password,now)
        elif args.operation=='authorize':
            if not args.request or not args.user:parser.error('--request and --user required')
            request=read(args.request)
            fingerprint=request.get('request',{}).get('device_id','invalid')
            print('Authorize',args.user,args.role,'device',fingerprint)
            if input('Compare this fingerprint on the new device; type AUTHORIZE: ')!='AUTHORIZE':
                parser.error('Not confirmed')
            result=authorize(root,password,request,args.role,args.user,now)
        elif args.operation=='renew':
            print('Renew for the 90-day maintenance interval plus 14-day overlap; preserve all revocations.')
            print('Existing device grants remain bounded; authorize endpoints explicitly afterward.')
            result=renew(root,password,now,input('Type RENEW to confirm administrator maintenance: '))
        else:
            if not args.device:parser.error('--device required')
            if input('Revoke only device '+args.device+'? Type REVOKE: ')!='REVOKE':parser.error('Not confirmed')
            result=revoke(root,password,args.device,now)
        args.output.parent.mkdir(parents=True,exist_ok=True)
        with args.output.open('xb') as stream:stream.write(encode(result))
        print('Public material written. No private authority transferred.')
        return 0
    except (ValueError,OSError):
        print('Authority operation refused. Preserve existing files; no private material logged.')
        return 1


if __name__=='__main__':raise SystemExit(main())
