"""Validate consolidated native lifecycle records and current strict serving TLS.

This checks recorded application evidence; it does not claim to replay native UI.
The real harness journey must populate --evidence first. No private key is read.
"""
import argparse
import json
from pathlib import Path
from tools.lan_trust_supervisor import verify


def read(path):
    return json.loads(path.read_text(encoding='utf-8-sig'))


def check(lab, evidence, serving):
    before=read(evidence/'snapshot-before.json')
    after=read(evidence/'snapshot-after.json')
    offline=read(evidence/'snapshot-offline.json')
    reconnected=read(evidence/'snapshot-reconnected.json')
    admin=read(evidence/'admin-web-journey.json')
    observed=read(evidence/'rotation-observed.json')
    audit=[json.loads(line) for line in (evidence/'final-transport.jsonl').read_text().splitlines() if line]
    assert admin['ok'] and admin['login_status']==200 and admin['devices_has_target']
    assert admin['after_login_url'].endswith('/admin') and '/admin/login' in admin['after_logout_url']
    assert observed['admin']['tls_errors']==0 and observed['admin']['logout_posted'] and observed['admin']['logout_cleared']
    for key in ('group_id','server_id','device_id','credential_id','issuer_pin','accepted','bootstrap_sha256'):
        assert all(item[key]==before[key] for item in (after,offline,reconnected)),key
    assert all(item['secret_unchanged'] for item in (after,offline,reconnected))
    assert after['expires_at']>before['expires_at'] and reconnected['expires_at']>after['expires_at']
    assert before['native']['session_id']==after['native']['session_id']
    assert offline['native']['session_id']!=before['native']['session_id']
    assert reconnected['native']['session_id']==offline['native']['session_id']
    for item in (before,after,offline,reconnected):
        assert item['native']['renderer_ready'] and item['native']['navigation_success']
        assert not item['native']['startup_failed']
    assert len({r['tls_spki_sha256'] for r in audit if r['status']==200})>=3
    assert {r['tls_issuer_spki_sha256'] for r in audit if r['status']==200}=={before['issuer_pin']}
    renewals=[r for r in audit if r['path']=='/api/v2/device/renew' and r['status']==200]
    receipts=[r for r in audit if r['path']=='/api/v2/client/receipts' and r['status']==200]
    assert len(renewals)>=2 and len(receipts)>=2
    offline_lines=[json.loads(line) for line in (evidence/'native-offline.jsonl').read_text().splitlines() if line]
    assert any(r['result']=='ready' for r in offline_lines)
    assert any(r['result']=='sync_refused' and r['code']=='network_unavailable' for r in offline_lines)
    assert any(r['result']=='active' for r in offline_lines)
    assert serving['state']=='ready' and serving['active']['generation']>=3
    assert any(r['status']==200 and r['tls_spki_sha256']==serving['active']['tls_spki_sha256'] for r in audit)
    final=read(evidence/'snapshot-final.json')
    for key in ('group_id','server_id','device_id','credential_id','issuer_pin','accepted'):
        assert final[key]==before[key]
    assert final['secret_unchanged'] and final['native']['renderer_ready']
    assert final['native']['navigation_success'] and not final['native']['startup_failed']
    actual=verify(lab,serving['active']['tls_spki_sha256'])
    return {'result':'PASS within isolated pilot bounds','stage_closure':False,
            'device_id':before['device_id'],'credential_id':before['credential_id'],
            'publication':before['accepted'],'generation':serving['active']['generation'],'current_strict_tls_leaf':actual,
            'renewals':len(renewals),'native_ready_receipts':len(receipts),
            'native_ui':'recorded actual harness evidence, not replayed by this checker'}


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--lab-root',type=Path,required=True)
    p.add_argument('--evidence',type=Path,required=True)
    p.add_argument('--serving-json',type=Path,required=True)
    p.add_argument('--out',type=Path,required=True)
    a=p.parse_args();result=check(a.lab_root,a.evidence,read(a.serving_json))
    a.out.write_text(json.dumps(result,indent=2));print(json.dumps(result))


if __name__=='__main__':main()
