"""Emit v2 public-only pilot contract, vectors, handoff and complete hashes."""
import argparse
import base64
import hashlib
import json
from pathlib import Path
import shutil
from kiosk.trust.roles import make_delegation, delegation_payload


def emit(lab, out, runtime):
    bundle = out / 'public-bundle'
    bundle.mkdir(exist_ok=True)
    for name in ('bootstrap.json','trust.json','root-ca.pem','intermediate.pem','manifest.json'):
        shutil.copyfile(lab/'public'/name,bundle/name)
    delegation = json.loads((lab/'server/delegation.json').read_text())
    delegation['version']=1
    (bundle/'delegation.json').write_text(json.dumps(delegation,indent=2))
    manifest=json.loads((bundle/'manifest.json').read_text())
    manifest['initial_issuance']=manifest.pop('serving')
    manifest['serving']=runtime['serving']['active']
    manifest['contract_version']='lan-trust-lifecycle-v2'
    (bundle/'manifest.json').write_text(json.dumps(manifest,indent=2))
    bootstrap=json.loads((bundle/'bootstrap.json').read_text())
    trust=json.loads((bundle/'trust.json').read_text())
    raw=base64.b64decode(trust['payload_base64'])
    assert trust['version']==json.loads(raw)['version']==2
    assert bootstrap['tls_ca_pem'].count('-----BEGIN CERTIFICATE-----')==1
    assert bootstrap['tls_ca_pem']==(bundle/'root-ca.pem').read_text()
    d=make_delegation(**{k:delegation[k] for k in ('group_id','server_id','origin','permitted_ip','permitted_dns','issuer_key_id','issuer_spki_base64','max_tls_validity_days','issued_at','expires_at')})
    vectors={'contract':'lan-trust-lifecycle-v2','group_spki_base64':bootstrap['group_spki_base64'],
      'trust_valid':{'envelope':trust,'domain_hex':b'Kiosk/GroupTrust/v2\0'.hex(),'payload_utf8':raw.decode(),'payload_sha256':hashlib.sha256(raw).hexdigest()},
      'delegation_valid':{'payload_base64':base64.b64encode(delegation_payload(d)).decode(),'signature_base64':delegation['signature_base64'],'domain_hex':b'Kiosk/LanTrust/v1/delegation\0'.hex()},
      'negative_transformations':[
        {'base':'trust_valid','change':'envelope.version=1','expect':'signature/domain refused'},
        {'base':'trust_valid','change':'payload.version=1 without re-signing','expect':'signature refused'},
        {'base':'bootstrap','change':'append intermediate to tls_ca_pem','expect':'bootstrap_requires_one_root'},
        {'base':'delegation_valid','change':'origin/server/group/IP/DNS expansion','expect':'signature refused'},
        {'base':'TLS','change':'unknown root/wrong SAN/expired leaf/wrong issuer pin','expect':'refused'},
        {'base':'trust_valid','change':'lower generation or equal generation/different payload','expect':'rollback/conflict refused'}]}
    (bundle/'vectors.json').write_text(json.dumps(vectors,indent=2))
    shutil.copyfile(Path('kiosk/trust/README.md'),bundle/'CONTRACT.md')
    handoff={'schema':'lan-trust-lifecycle-handoff-v2','contract_version':'lan-trust-lifecycle-v2',
      'status':'isolated pilot, not production D13 or migration approval',
      'group_id':bootstrap['group_id'],'server_id':bootstrap['server_id'],'origin':bootstrap['origin'],
      'bootstrap_expires_at':bootstrap['expires_at'],'delegation_expires_at':delegation['expires_at'],
      'runtime':runtime,'credentials':'private separate transfer, absent from public bundle',
      'contract':'CONTRACT.md','vectors':'vectors.json'}
    (bundle/'handoff.json').write_text(json.dumps(handoff,indent=2))
    sums={}
    for p in sorted(bundle.iterdir()):
        if p.is_file() and p.name!='SHA256SUMS.txt':
            if b'PRIVATE KEY' in p.read_bytes():raise ValueError('private material refused')
            sums[p.name]=hashlib.sha256(p.read_bytes()).hexdigest()
    (bundle/'SHA256SUMS.txt').write_text(''.join(h+'  '+n+'\n' for n,h in sums.items()))
    for name in ('handoff.json','vectors.json'):shutil.copyfile(bundle/name,out/name)
    return sums


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--lab-root',type=Path,required=True)
    p.add_argument('--out-dir',type=Path,required=True)
    p.add_argument('--runtime-json',type=Path,required=True)
    a=p.parse_args()
    print(json.dumps(emit(a.lab_root,a.out_dir,json.loads(a.runtime_json.read_text())),indent=2))


if __name__=='__main__':main()
