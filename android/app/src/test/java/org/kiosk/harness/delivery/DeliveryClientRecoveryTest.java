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
        JSONObject credential()throws Exception{return new JSONObject().put("version",1).put("state","approved").put("device_id",binding.getString("device_id")).put("profile",DeliveryProtocol.PROFILE).put("credential_id","credential-1").put("expires_at",clock.now+86400).put("scopes",new JSONArray(List.of("read_assignment","submit_receipt")));}
        NativeTransport.Response response(int status,JSONObject body){return new NativeTransport.Response(status,bytes(body.toString()),peer);}
        public NativeTransport.Response call(String path,String secret,byte[] body,int cap,String pin)throws Exception{
            if(path.equals("/api/v2/device/authorize")){
                authorizeCalls++;JSONObject next=new JSONObject(new String(body,StandardCharsets.UTF_8));assertTrue(store.saved.has("secret"));
                if(binding!=null)assertEquals(binding.toString(),next.toString());binding=next;
                if(fault.equals("authorize-expired"))return response(410,new JSONObject());
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
            lab.approved=false;assertEquals("pending",c.poll());lab.fault="denied";assertEquals("denied",c.poll());lab.fault="";lab.approved=true;lab.loseToken=true;
            DeliveryClient first=c;refused(first::poll);assertEquals("approved",lab.client().poll());String credential=lab.store.saved.getString("credential");
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
    @Test public void automaticWorkIsSingleFlightAndBackoffIsBounded(){
        DeliverySchedule s=new DeliverySchedule();assertTrue(s.begin());assertFalse(s.begin());assertEquals(10000,s.finish(false));
        for(int i=0;i<9;i++){assertTrue(s.begin());assertTrue(s.finish(false)<=120000);}assertTrue(s.begin());assertEquals(30000,s.finish(true));
        assertTrue(s.begin());assertEquals(10000,s.finish(false));
    }
}
