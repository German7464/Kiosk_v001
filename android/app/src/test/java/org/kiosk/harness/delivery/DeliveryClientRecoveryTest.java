package org.kiosk.harness.delivery;

import org.junit.Test;
import static org.junit.Assert.*;
import java.io.*;
import java.nio.charset.StandardCharsets;
import java.nio.file.*;
import java.util.*;
import org.json.*;
import org.kiosk.harness.binding.*;
import org.kiosk.harness.core.LocalView;
import org.kiosk.harness.storage.PreparedAdmission;

/** Tests real client/capture logic behind bounded package-private I/O seams, not native TLS acceptance. */
public class DeliveryClientRecoveryTest {
    interface Checked {void run()throws Exception;}
    static void refused(Checked check)throws Exception{try{check.run();fail("must refuse");}catch(AssertionError failure){throw failure;}catch(Exception expected){}}
    static byte[] bytes(String s){return s.getBytes(StandardCharsets.UTF_8);}
    byte[] fixture(String name)throws Exception{try(var in=getClass().getResourceAsStream("/delivery-v1/"+name+".json")){return in.readAllBytes();}}
    static final class Store implements DeliveryIO.Store {
        JSONObject saved=new JSONObject();boolean before,after,associationBefore;
        public JSONObject read()throws Exception{return new JSONObject(saved.toString());}
        public void write(JSONObject value)throws Exception{
            if(before||(associationBefore&&value.has("accepted")&&!saved.has("accepted"))){before=false;associationBefore=false;throw new IOException("interrupted_before_commit");}
            saved=new JSONObject(value.toString());if(after){after=false;throw new IOException("interrupted_after_commit");}
        }
    }
    static final class Clock implements DeliveryIO.Clock {
        long now,elapsed=10000;int boot=1;boolean automatic=true;
        public long now(){return now;}public long elapsed(){return elapsed;}public int boot(){return boot;}public boolean automatic(){return automatic;}
    }
    final class Lab implements AutoCloseable,DeliveryIO.Wire {
        final Store store=new Store();final Clock clock=new Clock();final byte[] bootstrap,trust;
        final Path input=Path.of(System.getProperty("tvPaginationRoot")).resolve("empty"),owned=Files.createTempDirectory("delivery-capture-");
        final JSONObject preparation,pub;final String peer,pid;JSONObject binding;boolean approved=true,revoked,loseAuthorize,loseToken,loseReceipt;
        int authorizeCalls,artifactCalls,captures;long generation=1;String fault="";final List<String> receipts=new ArrayList<>();
        Lab()throws Exception{
            bootstrap=fixture("bootstrap");trust=fixture("trust");JSONObject envelope=new JSONObject(new String(trust,StandardCharsets.UTF_8));
            JSONObject payload=new JSONObject(new String(Base64.getDecoder().decode(envelope.getString("payload_base64")),StandardCharsets.UTF_8));
            clock.now=payload.getLong("issued_at")+1;peer=payload.getJSONArray("servers").getJSONObject(0).getString("tls_spki_sha256");
            preparation=new JSONObject(new String(Files.readAllBytes(input.resolve("preparation.json")),StandardCharsets.UTF_8));pid=preparation.getString("package_identity");pub=new JSONObject(new String(fixture("publication"),StandardCharsets.UTF_8));
            pub.put("package_id",pid).put("raw_manifest_sha256",preparation.getString("raw_manifest_sha256"));
            pub.put("package",inventory(preparation.getJSONObject("package").getJSONObject("files")));
            for(String part:List.of("kiosk","tv"))pub.put(part,inventory(preparation.getJSONObject("views").getJSONObject(part).getJSONObject("files")));
        }
        JSONObject inventory(JSONObject map)throws Exception{JSONArray files=new JSONArray();for(var it=map.keys();it.hasNext();){String path=it.next();JSONObject pin=map.getJSONObject(path);files.put(new JSONObject().put("path",path).put("size",pin.getLong("size")).put("sha256",pin.getString("sha256")));}return new JSONObject().put("files",files);}
        DeliveryClient client()throws Exception{return new DeliveryClient(null,store,b->this,clock,(r,p,k,t)->{captures++;return DeliveryCaptureAdapter.capture(owned,r,p,k,t);});}
        DeliveryClient enrolled()throws Exception{DeliveryClient c=client();c.confirm(bootstrap);c.authorize();assertEquals("approved",c.poll());return c;}
        byte[] bootstrapAt(long issued,long expires,String id)throws Exception{
            JSONObject j=new JSONObject(new String(bootstrap,StandardCharsets.UTF_8));
            return bytes(j.put("bootstrap_id",id).put("issued_at",issued).put("expires_at",expires).toString());
        }
        DeliveryClient enrolledAt(long issued,long expires,String id)throws Exception{
            DeliveryClient c=client();c.confirm(bootstrapAt(issued,expires,id));c.authorize();assertEquals("approved",c.poll());return c;
        }
        JSONObject credential()throws Exception{return new JSONObject().put("version",1).put("state","approved").put("device_id",binding.getString("device_id")).put("profile",DeliveryProtocol.PROFILE).put("credential_id","credential-1").put("expires_at",clock.now+86400).put("scopes",new JSONArray(List.of("read_assignment","submit_receipt")));}
        NativeTransport.Response response(int status,JSONObject body){return new NativeTransport.Response(status,bytes(body.toString()),peer);}
        public NativeTransport.Response call(String path,String secret,byte[] body,int cap,String pin)throws Exception{
            if(path.equals("/api/v2/device/authorize")){
                authorizeCalls++;JSONObject next=new JSONObject(new String(body,StandardCharsets.UTF_8));assertTrue(store.saved.has("secret"));
                if(binding!=null&&binding.getString("request_id").equals(next.getString("request_id")))assertEquals(binding.toString(),next.toString());
                binding=next;
                if(fault.equals("authorize-expired"))return response(410,new JSONObject());
                if(fault.equals("authorize-window"))return response(200,new JSONObject().put("version",1).put("request_id",binding.getString("request_id")).put("device_code","a".repeat(64)).put("user_code","ABCD2345").put("expires_in",601).put("interval",5));
                if(fault.equals("authorize-code"))return response(200,new JSONObject().put("version",1).put("request_id",binding.getString("request_id")).put("device_code","a".repeat(64)).put("user_code","ABCD").put("expires_in",600).put("interval",5));
                if(fault.equals("authorize-code-i"))return response(200,new JSONObject().put("version",1).put("request_id",binding.getString("request_id")).put("device_code","a".repeat(64)).put("user_code","ABCDI345").put("expires_in",600).put("interval",5));
                if(loseAuthorize){loseAuthorize=false;throw new IOException("lost_authorize_reply");}
                return response(200,new JSONObject().put("version",1).put("request_id",binding.getString("request_id")).put("device_code","a".repeat(64)).put("user_code","ABCD2345").put("expires_in",600).put("interval",5));
            }
            if(path.equals("/api/v2/device/token")){
                if(fault.equals("expired"))return response(410,new JSONObject());if(fault.equals("denied"))return response(403,new JSONObject());
                if(!approved)return response(202,new JSONObject().put("version",1).put("state","pending").put("interval",5));
                if(loseToken){loseToken=false;throw new IOException("lost_token_reply");}return response(200,credential());
            }
            assertEquals(store.saved.getString("secret"),secret);
            if(revoked)return response(401,new JSONObject());
            if(path.equals("/api/v2/client/status"))return response(200,credential());
            if(path.equals("/api/v2/group/trust"))return new NativeTransport.Response(200,trust,peer);
            if(path.startsWith("/api/v2/client/assignment?")){
                if(fault.equals("malformed"))return new NativeTransport.Response(200,bytes("{\"version\":1,\"version\":1}"),peer);
                JSONObject publication=new JSONObject(pub.toString());if(fault.equals("unsupported"))publication.put("resource_profile","unsupported");
                String hash=LocalView.digest(bytes(DeliveryProtocol.canonical(DeliveryJson.parse(bytes(publication.toString()),2*1024*1024))));
                return response(200,new JSONObject().put("version",1).put("group_id",new JSONObject(new String(bootstrap,StandardCharsets.UTF_8)).getString("group_id"))
                    .put("device_id",binding.getString("device_id")).put("profile",DeliveryProtocol.PROFILE).put("generation",generation).put("metadata_sha256",hash).put("publication",publication));
            }
            if(path.equals("/api/v2/client/receipts")){
                receipts.add(new String(body,StandardCharsets.UTF_8));if(loseReceipt){loseReceipt=false;throw new IOException("lost_receipt_reply");}return response(200,new JSONObject().put("version",1));
            }
            throw new IOException("unexpected_test_route");
        }
        public InputStream artifact(String path,String secret,long size,String pin)throws IOException{
            artifactCalls++;if(fault.equals("unauthorized"))throw new IOException("401");
            String rest=path.substring(("/api/v2/publications/"+pid+"/").length());int slash=rest.indexOf('/');String part=rest.substring(0,slash),name=rest.substring(slash+1);
            try{
                String base=part.equals("package")?preparation.getJSONObject("package").getString("path"):preparation.getJSONObject("views").getJSONObject(part).getString("path");
                byte[] value=Files.readAllBytes(input.resolve(base).resolve(name));
                if(fault.equals("partial"))value=Arrays.copyOf(value,Math.max(0,value.length-1));if(fault.equals("tampered"))value[0]^=1;
                return new ByteArrayInputStream(value);
            }catch(Exception e){throw new IOException("bounded_test_artifact");}
        }
        PreparedAdmission.Request accept(DeliveryClient c)throws Exception{var d=c.download();try(var captured=d.capture()){assertEquals(pid,captured.report().callerAttestedCanonicalPackageIdentity());c.verify(d.request(),PreparedAdmission.Phase.NEW_ACTIVATION);return d.request();}}
        public void close()throws Exception{try(var files=Files.walk(owned)){for(Path p:files.sorted(Comparator.reverseOrder()).toList())Files.delete(p);}}
    }
    @Test public void startupAndUnchangedAssignmentDoNotRedownloadOrEmitReady()throws Exception{
        try(var lab=new Lab()){var c=lab.enrolled();lab.accept(c);assertFalse(lab.store.saved.has("outbox"));int reads=lab.artifactCalls;
            assertNull(lab.client().download(lab.pid));assertEquals(reads,lab.artifactCalls);assertEquals(1,lab.authorizeCalls);assertEquals(1,lab.captures);}
    }
    @Test public void enrollmentLostResponsesPendingDenialExpiryAndRecovery()throws Exception{
        try(var lab=new Lab()){
            var c=lab.client();c.confirm(lab.bootstrap);String secret=lab.store.saved.getString("secret"),request=lab.store.saved.getString("request");
            lab.loseAuthorize=true;refused(c::authorize);c=lab.client();c.authorize();assertEquals(secret,lab.store.saved.getString("secret"));assertEquals(request,lab.store.saved.getString("request"));
            lab.approved=false;assertEquals("pending",c.poll());
            lab.fault="denied";assertEquals("denied",c.poll());
            assertEquals("",c.pairingPayload());assertEquals("denied",c.pairingState());assertTrue(c.pairingBlocked());refused(c::poll);
            lab.fault="";lab.approved=true;lab.loseToken=true;
            DeliveryClient retry=lab.client();retry.authorize();refused(retry::poll);assertEquals("approved",lab.client().poll());
            String credential=lab.store.saved.getString("credential");
            assertEquals("approved",lab.client().poll());assertEquals(credential,lab.store.saved.getString("credential"));
        }
        try(var lab=new Lab()){var c=lab.client();c.confirm(lab.bootstrap);c.authorize();lab.fault="expired";assertEquals("approved",c.poll());}
        try(var lab=new Lab()){var c=lab.client();c.confirm(lab.bootstrap);lab.loseAuthorize=true;refused(c::authorize);lab.fault="authorize-expired";var restarted=lab.client();restarted.authorize();assertTrue(restarted.enrolled());assertEquals(2,lab.authorizeCalls);}
    }
    @Test public void boundedPartialTamperedUnauthorizedUnsupportedAndStalePreserveAssociation()throws Exception{
        try(var lab=new Lab()){var c=lab.enrolled();lab.accept(c);String association=lab.store.saved.getJSONObject("accepted").toString();
            for(String fault:List.of("partial","tampered","unauthorized","unsupported","malformed")){lab.fault=fault;refused(c::download);assertEquals(association,lab.store.saved.getJSONObject("accepted").toString());try(var staged=Files.list(lab.owned)){assertEquals(0,staged.count());}}
            lab.fault="";lab.generation=0;refused(c::download);assertEquals(association,lab.store.saved.getJSONObject("accepted").toString());
        }
    }
    @Test public void rebootRecoveryKeepsEnrollmentAndOfflineAssociation()throws Exception{
        try(var lab=new Lab()){var c=lab.enrolled();var request=lab.accept(c);String secret=lab.store.saved.getString("secret"),credential=lab.store.saved.getString("credential");
            lab.clock.boot++;lab.clock.elapsed=1;lab.clock.now+=60;var rebooted=lab.client();
            rebooted.verify(request,PreparedAdmission.Phase.PRIVATE_REOPEN);refused(rebooted::download);
            rebooted.confirmClock();assertNull(rebooted.download(lab.pid));assertEquals(secret,lab.store.saved.getString("secret"));assertEquals(credential,lab.store.saved.getString("credential"));assertEquals(1,lab.authorizeCalls);
            lab.clock.now-=100;refused(rebooted::confirmClock);rebooted.verify(request,PreparedAdmission.Phase.PRIVATE_REOPEN);
            lab.clock.now+=100;lab.clock.automatic=false;refused(rebooted::confirmClock);
        }
    }
    @Test public void outboxLostResponseAndInterruptedCommitRetryIdenticalBody()throws Exception{
        try(var lab=new Lab()){var c=lab.enrolled();lab.accept(c);c.queueReady(lab.pid,"kiosk","ready-session");
            lab.loseReceipt=true;refused(c::flush);assertEquals(1,lab.store.saved.getJSONArray("outbox").length());
            assertEquals(1,lab.client().flush());assertEquals(lab.receipts.get(0),lab.receipts.get(1));
            c=lab.client();c.queueReady(lab.pid,"tv","ready-session");lab.store.before=true;DeliveryClient pending=c;refused(pending::flush);
            assertEquals(1,lab.store.saved.getJSONArray("outbox").length());lab.client().flush();assertEquals(lab.receipts.get(2),lab.receipts.get(3));
        }
    }
    @Test public void interruptedAssociationAndRevocationNeverCreateAuthority()throws Exception{
        try(var lab=new Lab()){var c=lab.enrolled();var d=c.download();try(var captured=d.capture()){
            lab.store.associationBefore=true;refused(()->c.verify(d.request(),PreparedAdmission.Phase.NEW_ACTIVATION));
            refused(()->lab.client().verify(d.request(),PreparedAdmission.Phase.PRIVATE_REOPEN));
            c.verify(d.request(),PreparedAdmission.Phase.NEW_ACTIVATION);lab.revoked=true;refused(c::download);c.verify(d.request(),PreparedAdmission.Phase.PRIVATE_REOPEN);
        }}
    }
    @Test public void queueCreationAndRemovalSurviveBothCommitBoundaries()throws Exception{
        try(var lab=new Lab()){var c=lab.enrolled();lab.accept(c);
            lab.store.before=true;refused(()->c.queueReady(lab.pid,"tv","s"));assertFalse(lab.store.saved.has("outbox"));
            c.queueReady(lab.pid,"tv","s");String exact=lab.store.saved.getJSONArray("outbox").getString(0);c.queueReady(lab.pid,"tv","s");assertEquals(1,lab.store.saved.getJSONArray("outbox").length());
            lab.store.after=true;refused(c::flush);assertEquals(0,lab.store.saved.getJSONArray("outbox").length());assertEquals(0,lab.client().flush());assertEquals(exact,lab.receipts.get(0));
        }
    }
    @Test public void persistedTrustFloorsCredentialExpiryAndExactReopenBindings()throws Exception{
        try(var lab=new Lab()){var c=lab.enrolled();var r=lab.accept(c);
            var changed=new PreparedAdmission.Request(r.pkg(),r.renderer(),r.kiosk(),r.tv(),r.preparationReference(),r.windowsImages(),new PreparedAdmission.ImageBudget(2000001,33554432,5000,15000),r.storage());
            refused(()->c.verify(changed,PreparedAdmission.Phase.PRIVATE_REOPEN));refused(()->c.verify(changed,PreparedAdmission.Phase.NEW_ACTIVATION));
            JSONObject original=lab.store.read();lab.store.saved.put("trust_generation",lab.store.saved.getLong("trust_generation")+1);refused(()->lab.client().download());
            lab.store.saved=new JSONObject(original.toString()).put("trust_digest","0".repeat(64));refused(()->lab.client().download());
            lab.store.saved=new JSONObject(original.toString()).put("credential_expires",lab.clock.now);refused(()->lab.client().download());
            lab.client().verify(r,PreparedAdmission.Phase.PRIVATE_REOPEN);assertEquals(1,lab.authorizeCalls);
        }
    }
    @Test public void sameAnchorRenewalIsAtomicIdempotentAndPreservesAcceptedState()throws Exception{
        try(var lab=new Lab()){
            long setup=lab.clock.now;
            var c=lab.enrolledAt(setup-1000,setup+1000,"initial");
            var request=lab.accept(c);c.queueReady(lab.pid,"tv","renewal-session");
            JSONObject before=lab.store.read();
            String device=before.getString("device"),secret=before.getString("secret"),requestId=before.getString("request"),credential=before.getString("credential");
            String accepted=before.getJSONObject("accepted").toString(),outbox=before.getJSONArray("outbox").toString();
            lab.clock.now=setup+2000;
            var reopened=lab.client();
            byte[] renewal=lab.bootstrapAt(setup+1500,1794396799L,"renewed");
            var facts=reopened.inspectRenewal(renewal);
            assertEquals("renewed",facts.bootstrapId());assertFalse(facts.unchanged());
            assertEquals("https://192.168.1.165:8443",facts.origin());assertEquals(setup+1500,facts.issued());
            String unchanged=lab.store.saved.toString();refused(()->reopened.renew(renewal,false));assertEquals(unchanged,lab.store.saved.toString());
            var saved=reopened.renew(renewal,true);assertFalse(saved.unchanged());
            JSONObject after=lab.store.read();
            assertEquals("renewed",DeliveryProtocol.bootstrap(after.getString("bootstrap").getBytes(StandardCharsets.UTF_8),after.getLong("confirmed_at")).id());
            for(String key:List.of("device","secret","request","credential","credential_expires","trust_generation","trust_digest","peer","trust_envelope","clock_boot"))assertEquals("preserved "+key,before.get(key).toString(),after.get(key).toString());
            assertEquals(accepted,after.getJSONObject("accepted").toString());assertEquals(outbox,after.getJSONArray("outbox").toString());
            assertEquals(device,after.getString("device"));assertEquals(secret,after.getString("secret"));assertEquals(requestId,after.getString("request"));assertEquals(credential,after.getString("credential"));
            assertEquals(setup+2000,after.getLong("highest_time"));assertTrue(after.getLong("highest_time")>=before.getLong("highest_time"));
            var noop=reopened.renew(renewal,true);assertTrue(noop.unchanged());assertEquals(after.toString(),lab.store.saved.toString());
            var restarted=lab.client();assertTrue(restarted.confirmed());assertEquals("https://192.168.1.165:8443",restarted.trustedOrigin());
            assertEquals("renewed",DeliveryProtocol.bootstrap(lab.store.saved.getString("bootstrap").getBytes(StandardCharsets.UTF_8),lab.store.saved.getLong("confirmed_at")).id());
            assertEquals(accepted,lab.store.saved.getJSONObject("accepted").toString());assertEquals(outbox,lab.store.saved.getJSONArray("outbox").toString());
        }
    }
    @Test public void renewalRejectsIdentityTimeCredentialTrustAndMalformedBoundaries()throws Exception{
        try(var lab=new Lab()){
            long setup=lab.clock.now;var c=lab.enrolledAt(setup-1000,setup+1000,"initial");lab.accept(c);
            lab.clock.now=setup+2000;var client=lab.client();
            byte[] base=lab.bootstrapAt(setup+1500,1794396799L,"renewed");
            String state=lab.store.saved.toString();
            JSONObject j=new JSONObject(new String(base,StandardCharsets.UTF_8));
            for(String field:List.of("group_id","server_id","origin","group_key_id","tls_ca_pem")){
                JSONObject changed=new JSONObject(j.toString());changed.put(field,field.equals("tls_ca_pem")?changed.getString(field)+"\n":changed.getString(field)+"x");
                refused(()->client.inspectRenewal(bytes(changed.toString())));assertEquals(state,lab.store.saved.toString());
            }
            refused(()->client.renew(bytes(new JSONObject(j.toString()).put("version",2).toString()),true));
            refused(()->client.renew(bytes(new JSONObject(j.toString()).put("extra",true).toString()),true));
            refused(()->client.renew(bytes(new JSONObject(j.toString()).put("issued_at",setup-2000).toString()),true));
            refused(()->client.renew(bytes(new JSONObject(j.toString()).put("expires_at",setup+500).toString()),true));
            refused(()->client.renew(bytes(new JSONObject(j.toString()).put("expires_at",1794396800L).toString()),true));
            refused(()->client.renew(bytes(new JSONObject(j.toString()).put("issued_at",setup+3000).toString()),true));
            refused(()->client.renew(bytes(new JSONObject(j.toString()).put("issued_at",setup+3000).put("expires_at",setup+4000).toString()),true));
            byte[] oversize=Arrays.copyOf(base,16385);oversize[base.length]=(byte)' ';refused(()->client.renew(oversize,true));
            refused(()->client.renew(bytes("{\"version\":1,\"version\":1}"),true));
            refused(()->client.renew(base,false));
            assertEquals(state,lab.store.saved.toString());
            JSONObject missingTrust=new JSONObject(lab.store.saved.toString());missingTrust.remove("trust_envelope");lab.store.saved=missingTrust;
            var noTrust=lab.client();refused(()->noTrust.renew(base,true));
            lab.store.saved=new JSONObject(state);
            JSONObject expiredCredential=new JSONObject(lab.store.saved.toString()).put("credential_expires",lab.clock.now);lab.store.saved=expiredCredential;
            var noCredential=lab.client();refused(()->noCredential.renew(base,true));
            lab.store.saved=new JSONObject(state).put("credential_expires",Long.MAX_VALUE);
            var infiniteCredential=lab.client();refused(()->infiniteCredential.renew(base,true));
            lab.store.saved=new JSONObject(state);
        }
        try(var lab=new Lab()){
            long setup=lab.clock.now;var c=lab.enrolledAt(setup-1000,setup+1000,"initial");
            lab.clock.now=setup+2000;var client=lab.client();byte[] base=lab.bootstrapAt(setup+1500,1794396799L,"renewed");
            lab.clock.now=1794396799L;refused(()->client.renew(base,true));
        }
    }
    @Test public void renewalCommitInterruptionKeepsOldOrCompletelyValidatedNewState()throws Exception{
        try(var lab=new Lab()){
            long setup=lab.clock.now;lab.enrolledAt(setup-1000,setup+1000,"initial");lab.accept(lab.client());
            lab.clock.now=setup+2000;var client=lab.client();byte[] renewal=lab.bootstrapAt(setup+1500,1794396799L,"renewed");
            String old=lab.store.saved.toString();lab.store.before=true;refused(()->client.renew(renewal,true));
            assertEquals(old,lab.store.saved.toString());
            assertEquals("initial",DeliveryProtocol.bootstrap(lab.store.saved.getString("bootstrap").getBytes(StandardCharsets.UTF_8),lab.store.saved.getLong("confirmed_at")).id());
            lab.store.after=true;refused(()->client.renew(renewal,true));
            var restarted=lab.client();assertEquals("renewed",DeliveryProtocol.bootstrap(lab.store.saved.getString("bootstrap").getBytes(StandardCharsets.UTF_8),lab.store.saved.getLong("confirmed_at")).id());
            assertTrue(restarted.confirmed());assertEquals("https://192.168.1.165:8443",restarted.trustedOrigin());
        }
    }
    @Test public void automaticWorkIsSingleFlightAndBackoffIsBounded(){
        DeliverySchedule s=new DeliverySchedule();assertTrue(s.begin());assertFalse(s.begin());assertEquals(10000,s.finish(false));
        for(int i=0;i<9;i++){assertTrue(s.begin());assertTrue(s.finish(false)<=120000);}assertTrue(s.begin());assertEquals(30000,s.finish(true));
        assertTrue(s.begin());assertEquals(10000,s.finish(false));
    }
    @Test public void pendingPairingShowsExactContractAndClearsOnExpiry()throws Exception{
        try(var lab=new Lab()){
            var c=lab.client();c.confirm(lab.bootstrap);
            assertEquals("",c.pairingPayload());
            c.authorize();
            String origin=new JSONObject(new String(lab.bootstrap,StandardCharsets.UTF_8)).getString("origin");
            assertEquals(origin+"/admin/devices/pair#v=1&code=ABCD2345",c.pairingPayload());
            assertEquals(lab.clock.now+600,c.pendingExpiresAt());
            assertEquals(c.pairingPayload(),lab.client().pairingPayload());
            lab.clock.now+=599;assertEquals(origin+"/admin/devices/pair#v=1&code=ABCD2345",lab.client().pairingPayload());
            lab.clock.now+=1;assertEquals("",lab.client().pairingPayload());
            lab.fault="expired";lab.revoked=true;
            assertEquals("expired",c.poll());
            assertEquals("",c.pairingPayload());assertEquals("expired",c.pairingState());assertTrue(c.pairingBlocked());
            assertFalse(lab.store.saved.has("device_code"));assertFalse(c.enrolled());
        }
        try(var lab=new Lab()){
            var c=lab.client();c.confirm(lab.bootstrap);lab.fault="authorize-window";refused(c::authorize);
            lab.fault="authorize-code";refused(c::authorize);
            lab.fault="authorize-code-i";refused(c::authorize);
            assertEquals("",c.pairingPayload());assertFalse(lab.store.saved.has("user_code"));assertFalse(c.pairingBlocked());
            lab.fault="";c.authorize();assertEquals(lab.clock.now+600,c.pendingExpiresAt());
        }
    }
    @Test public void cancellationIsLocalOnlyAndKeepsIdentityForExplicitRenewal()throws Exception{
        try(var lab=new Lab()){
            var c=lab.client();c.confirm(lab.bootstrap);c.authorize();
            String device=lab.store.saved.getString("device"),secret=lab.store.saved.getString("secret"),request=lab.store.saved.getString("request");
            int calls=lab.authorizeCalls;long now=lab.clock.now;lab.approved=false;assertEquals("pending",c.poll());
            c.cancelPending();
            assertEquals("cancellation must not contact the server",calls,lab.authorizeCalls);
            assertEquals("cancellation must not change accepted device time",now,lab.clock.now);
            assertEquals("",c.pairingPayload());assertEquals("cancelled",c.pairingState());assertTrue(c.pairingBlocked());
            assertFalse(lab.store.saved.has("device_code"));assertFalse(lab.store.saved.has("user_code"));assertFalse(c.enrolled());
            assertEquals(device,lab.store.saved.getString("device"));assertEquals(secret,lab.store.saved.getString("secret"));
            assertNotEquals(request,lab.store.saved.getString("request"));
            c.reenroll();assertFalse(c.pairingBlocked());c.authorize();assertEquals(calls+1,lab.authorizeCalls);
            assertEquals("https://192.168.1.165:8443/admin/devices/pair#v=1&code=ABCD2345",c.pairingPayload());
        }
    }
}
