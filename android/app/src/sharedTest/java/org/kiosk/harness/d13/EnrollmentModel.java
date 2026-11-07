package org.kiosk.harness.d13;

import java.util.*;
import static org.kiosk.harness.d13.StrictPrototypeJson.*;

/** Serial, in-memory assertions only: no real credential, durable state, server or display/store. */
public final class EnrollmentModel {
    public record Binding(String request,String device,String group,String profile,String origin,String nonce) {}
    final Binding binding;
    private final String deviceCode="fixture-native-device-secret-only",userCode="ABCD2345";
    private final long expires;
    private long nextPoll;
    private int interval=5,approvals,issues;
    private boolean approved,denied,revoked;
    private String downloaded,published,visible,lastReady;
    private long generation=7;
    private final List<Object> trace=new ArrayList<>();
    EnrollmentModel(Binding binding,long start){this.binding=binding;expires=start+600;nextPoll=start;}
    String approve(String code,Binding actual,long now){
        if(!binding.equals(actual))return "BINDING_REFUSED";
        if(!userCode.equals(code))return "USER_CODE_REFUSED";
        if(denied)return "DENIED";if(revoked)return "REVOKED";if(now>=expires)return "EXPIRED";
        if(approved)return "APPROVAL_REPLAY";approved=true;approvals++;return "APPROVED_ONCE";
    }
    String poll(String code,Binding actual,long now){
        if(!deviceCode.equals(code))return "DEVICE_SECRET_REFUSED";
        if(!binding.equals(actual))return "BINDING_REFUSED";
        if(revoked)return "REVOKED";if(denied)return "DENIED";if(now>=expires)return "EXPIRED";
        if(now<nextPoll){interval+=5;nextPoll=now+interval;return "SLOW_DOWN";}
        nextPoll=now+interval;if(!approved)return "PENDING";
        if(issues>0)return "ISSUANCE_REPLAY_NO_NEW_CREDENTIAL";issues++;return "CREDENTIAL_ISSUED_ONCE";
    }
    String authorize(String group,String origin,String peer,long listGeneration,long listExpiry,long now){
        if(revoked)return "REVOKED";if(issues!=1)return "NO_CREDENTIAL";
        if(!binding.group().equals(group))return "CROSS_GROUP";
        if(!binding.origin().equals(origin)||!peer.equals("server-A"))return "ROGUE_SERVER";
        if(listExpiry<=now)return "EXPIRED_AUTHORITY";if(listGeneration<generation)return "STALE_AUTHORITY";
        generation=listGeneration;return "AUTHORIZED";
    }
    private void event(String label,String result){Map<String,Object> s=new LinkedHashMap<>();s.put("event",label);s.put("result",result);s.put("downloaded",downloaded);s.put("published",published);s.put("visible",visible);s.put("last_ready",lastReady);s.put("generation",generation);s.put("approvals",approvals);s.put("credential_issues",issues);trace.add(s);}
    private void expect(String label,String expected,String actual)throws Refused {require(expected.equals(actual),"MODEL_"+label);event(label,actual);}
    public static Map<String,Object> run()throws Exception {
        Binding b=new Binding("request-1","device-1",D13Prototype.GROUP,"events-profile",D13Prototype.ORIGIN,"nonce-1");
        EnrollmentModel m=new EnrollmentModel(b,1000);
        m.expect("code-separation","DEVICE_SECRET_REFUSED",m.poll(m.userCode,b,1000));
        m.expect("pending","PENDING",m.poll(m.deviceCode,b,1000));
        m.expect("poll-too-fast","SLOW_DOWN",m.poll(m.deviceCode,b,1001));
        m.expect("still-too-fast","SLOW_DOWN",m.poll(m.deviceCode,b,1005));
        List<Binding> wrong=List.of(new Binding("other",b.device(),b.group(),b.profile(),b.origin(),b.nonce()),new Binding(b.request(),"other",b.group(),b.profile(),b.origin(),b.nonce()),new Binding(b.request(),b.device(),"other",b.profile(),b.origin(),b.nonce()),new Binding(b.request(),b.device(),b.group(),"other",b.origin(),b.nonce()),new Binding(b.request(),b.device(),b.group(),b.profile(),"https://rogue.invalid",b.nonce()),new Binding(b.request(),b.device(),b.group(),b.profile(),b.origin(),"other"));
        for(int i=0;i<wrong.size();i++){m.expect("approval-binding-"+i,"BINDING_REFUSED",m.approve(m.userCode,wrong.get(i),1020));m.expect("poll-binding-"+i,"BINDING_REFUSED",m.poll(m.deviceCode,wrong.get(i),1020));}
        m.expect("device-secret-not-human-code","USER_CODE_REFUSED",m.approve(m.deviceCode,b,1020));
        m.expect("approved","APPROVED_ONCE",m.approve(m.userCode,b,1020));
        m.expect("approval-replay","APPROVAL_REPLAY",m.approve(m.userCode,b,1020));
        m.expect("issued","CREDENTIAL_ISSUED_ONCE",m.poll(m.deviceCode,b,1020));
        m.expect("issuance-replay","ISSUANCE_REPLAY_NO_NEW_CREDENTIAL",m.poll(m.deviceCode,b,1040));
        m.expect("authorized-A","AUTHORIZED",m.authorize(b.group(),b.origin(),"server-A",7,2000,1041));
        m.downloaded="A";m.event("download-A","DOWNLOADED_ONLY");require(m.published==null&&m.visible==null&&m.lastReady==null,"MODEL_SEMANTICS");
        m.published="A";m.event("publish-A","POINTER_ONLY");require(m.visible==null&&m.lastReady==null,"MODEL_SEMANTICS");
        m.visible="A";m.event("visible-A","VISIBLE_NOT_READY");require(m.lastReady==null,"MODEL_SEMANTICS");
        m.lastReady="A";m.event("ready-A","MODEL_READY");
        m.expect("rogue","ROGUE_SERVER",m.authorize(b.group(),"https://rogue.invalid","rogue",8,2000,1042));
        m.expect("stale","STALE_AUTHORITY",m.authorize(b.group(),b.origin(),"server-A",6,2000,1042));
        m.expect("cross-group","CROSS_GROUP",m.authorize("other",b.origin(),"server-A",8,2000,1042));
        require(m.generation==7&&m.lastReady.equals("A"),"MODEL_REFUSAL_PRESERVATION");
        m.expect("authorized-B","AUTHORIZED",m.authorize(b.group(),b.origin(),"server-A",8,2000,1043));
        m.downloaded="B";m.event("download-B","DOWNLOADED_ONLY");require(m.published.equals("A")&&m.lastReady.equals("A"),"MODEL_SEMANTICS");
        m.published="B";m.event("publish-B","POINTER_ONLY");require(m.visible.equals("A")&&m.lastReady.equals("A"),"MODEL_SEMANTICS");
        m.visible="B";m.event("visible-B","VISIBLE_NOT_READY");require(m.lastReady.equals("A"),"MODEL_SEMANTICS");
        m.lastReady="B";m.event("ready-B","MODEL_READY");
        m.expect("offline-expired","EXPIRED_AUTHORITY",m.authorize(b.group(),b.origin(),"server-A",9,2000,2001));
        require(m.lastReady.equals("B")&&m.visible.equals("B")&&m.generation==8,"MODEL_OFFLINE_RETENTION");m.event("offline-retains-B","MODEL_CONTENT_RETAINED");
        m.revoked=true;m.expect("revoked-no-new-update","REVOKED",m.authorize(b.group(),b.origin(),"server-A",9,3000,2002));
        m.expect("revoked-poll","REVOKED",m.poll(m.deviceCode,b,2002));require(m.lastReady.equals("B")&&m.generation==8&&m.issues==1&&m.approvals==1,"MODEL_NO_RESET");
        EnrollmentModel denied=new EnrollmentModel(b,1000);denied.denied=true;m.expect("denied-poll","DENIED",denied.poll(denied.deviceCode,b,1000));m.expect("denied-approval","DENIED",denied.approve(denied.userCode,b,1000));
        EnrollmentModel expired=new EnrollmentModel(b,1000);m.expect("expired-at-boundary","EXPIRED",expired.approve(expired.userCode,b,1600));m.expect("expired-poll","EXPIRED",expired.poll(expired.deviceCode,b,1600));
        Map<String,Object> result=new LinkedHashMap<>();result.put("kind","SERIAL_IN_MEMORY_MODEL_ONLY");result.put("trace",m.trace);result.put("credential_issues",m.issues);result.put("approvals",m.approvals);result.put("final_offline_content",m.lastReady);result.put("renewal_and_lost_response_recovery","UNRESOLVED; replay refuses new credential, does not recover lost response");return result;
    }
}
