package org.kiosk.harness.delivery;

import android.content.Context;
import android.os.SystemClock;
import android.provider.Settings;
import java.io.*;
import java.nio.charset.StandardCharsets;
import java.security.SecureRandom;
import java.util.*;
import org.json.*;
import org.kiosk.harness.binding.*;
import org.kiosk.harness.core.LocalView;
import org.kiosk.harness.storage.PreparedAdmission;
import static org.kiosk.harness.delivery.DeliveryProtocol.*;

/** Serialized native owner of trust, enrollment, accepted associations and durable ready outbox. */
public final class DeliveryClient implements PreparedAdmission.SourceVerifier {
    private final Context context;
    private final DeliveryIO.Store disk;
    private final DeliveryIO.Wires wires;
    private final DeliveryIO.Clock clock;
    private final DeliveryIO.Capture capture;
    private JSONObject state;
    private volatile Bootstrap anchor;
    private DeliveryIO.Wire transport;
    private Assignment live;
    private volatile String transferDiagnostics="{}";
    private volatile long retryUntil;
    private long processWall,processElapsed;
    public DeliveryClient(Context c)throws Exception {
        this(c.getApplicationContext(),new PrivateDeliveryState(c),NativeTransport::new,new DeliveryIO.Clock(){
            public long now(){return System.currentTimeMillis()/1000;}public long elapsed(){return SystemClock.elapsedRealtime();}
            public int boot(){return Settings.Global.getInt(c.getContentResolver(),Settings.Global.BOOT_COUNT,-1);}
            public boolean automatic(){return Settings.Global.getInt(c.getContentResolver(),Settings.Global.AUTO_TIME,0)==1;}
        },(r,p,k,t)->CapturedCandidate.capture(c,p,k,t,r.pkg(),r.renderer(),r.kiosk(),r.tv(),r.storage(),new CapturedCandidate.Cancellation()));
    }
    DeliveryClient(Context c,DeliveryIO.Store store,DeliveryIO.Wires wires,DeliveryIO.Clock clock,DeliveryIO.Capture capture)throws Exception {
        context=c;disk=store;this.wires=wires;this.clock=clock;this.capture=capture;
        processWall=clock.now();processElapsed=clock.elapsed();state=disk.read();
        if(state.optInt("transfer_retry_boot",-2)==clock.boot())retryUntil=state.optLong("transfer_retry_elapsed",0);
        if(state.has("bootstrap"))loadAnchor();
        if(c!=null)try{File prior=new File(c.getFilesDir(),"transfer-state.json");if(prior.isFile())transferDiagnostics=new JSONObject(new String(LocalView.readBounded(new FileInputStream(prior),16384),StandardCharsets.UTF_8)).toString();}catch(Exception ignored){transferDiagnostics="{\"restart_reason\":\"diagnostic_invalid\"}";}
    }
    private void save()throws Exception {try{disk.write(state);}catch(Exception failure){state=disk.read();throw failure;}}
    private void loadAnchor()throws Exception {
        anchor=bootstrap(state.getString("bootstrap").getBytes(StandardCharsets.UTF_8),state.getLong("confirmed_at"));transport=wires.create(anchor);
    }
    public boolean confirmed(){return anchor!=null;}
    public String trustedOrigin(){Bootstrap b=anchor;return b==null?"":b.origin();}
    public synchronized void confirm(byte[] bytes)throws Exception {
        need(anchor==null);long now=clock.now();Bootstrap b=bootstrap(bytes,now);wires.create(b);
        JSONObject initial=new JSONObject().put("bootstrap",new String(bytes,StandardCharsets.UTF_8)).put("confirmed_at",now).put("highest_time",now).put("clock_boot",bootCount())
            .put("device",UUID.randomUUID().toString()).put("request",UUID.randomUUID().toString()).put("nonce",UUID.randomUUID().toString());
        byte[] secret=new byte[32];new SecureRandom().nextBytes(secret);initial.put("secret",hex(secret));disk.write(initial);state=initial;loadAnchor();
    }
    private static String hex(byte[] b){StringBuilder s=new StringBuilder();for(byte v:b)s.append(String.format(Locale.ROOT,"%02x",v&255));return s.toString();}
    private byte[] body(JSONObject value){return value.toString().getBytes(StandardCharsets.UTF_8);}
    private String secret()throws Exception{return state.getString("secret");}
    private NativeTransport.Response call(String path,JSONObject body,boolean auth,String pin)throws Exception {
        return transport.call(path,auth?secret():null,body==null?null:body(body),2*1024*1024,pin);
    }
    public synchronized String humanCode(){return state.optString("user_code","");}
    public synchronized boolean enrolled(){return state.has("credential");}
    private int bootCount(){return clock.boot();}
    /** A native operator confirms uncertain reboot time without replacing a valid enrollment. */
    public synchronized void confirmClock()throws Exception {
        need(anchor!=null);long now=clock.now(),elapsed=clock.elapsed();int boot=bootCount();
        DeliveryClock.check(now,state.getLong("highest_time"),now,elapsed,elapsed,anchor.issued(),anchor.expires(),Long.MAX_VALUE,boot,boot,clock.automatic());
        state.put("clock_boot",bootCount()).put("highest_time",now);save();processWall=now;processElapsed=clock.elapsed();
    }
    /** Explicit native action, never a page/Intent callback. Retains anchor and accepted offline associations. */
    public synchronized void reenroll()throws Exception {
        confirmClock();
        byte[] secret=new byte[32];new SecureRandom().nextBytes(secret);
        state.put("secret",hex(secret)).put("request",UUID.randomUUID().toString()).put("nonce",UUID.randomUUID().toString()).put("clock_boot",bootCount());
        for(String key:List.of("credential","credential_expires","device_code","user_code"))state.remove(key);save();
    }
    public synchronized void authorize()throws Exception {
        need(anchor!=null);if(enrolled())return;
        byte[] raw=new byte[32];String secret=secret();for(int i=0;i<32;i++)raw[i]=(byte)Integer.parseInt(secret.substring(2*i,2*i+2),16);
        JSONObject binding=new JSONObject().put("version",1).put("request_id",state.getString("request")).put("device_id",state.getString("device"))
            .put("group_id",anchor.group()).put("profile",PROFILE).put("origin",anchor.origin()).put("nonce",state.getString("nonce")).put("secret_verifier",LocalView.digest(raw));
        var response=call("/api/v2/device/authorize",binding,false,null);
        if(response.status()==410){var recovered=call("/api/v2/client/status",null,true,null);need(recovered.status()==200);acceptCredential(recovered.body());return;}
        need(response.status()==200);
        var m=json(response.body(),2*1024*1024);DeliveryJson.keys(m,"version","request_id","device_code","user_code","expires_in","interval");version(m);
        need(state.getString("request").equals(str(m,"request_id"))&&str(m,"device_code").matches("[a-f0-9]{64}")&&str(m,"user_code").matches("[A-Z2-9]{8}")&&num(m,"expires_in")>0&&num(m,"expires_in")<=600&&num(m,"interval")==5);
        state.put("device_code",str(m,"device_code")).put("user_code",str(m,"user_code"));save();
    }
    public synchronized String poll()throws Exception {
        if(enrolled())return "approved";need(state.has("device_code"));
        var response=call("/api/v2/device/token",new JSONObject().put("device_code",state.getString("device_code")),false,null);
        if(response.status()==202||response.status()==429)return "pending";
        if(response.status()==403)return "denied";if(response.status()==410){
            // Approved credentials remain recoverable after the authorization request itself expires.
            response=call("/api/v2/client/status",null,true,null);if(response.status()!=200)return "expired";
        }
        need(response.status()==200);acceptCredential(response.body());return "approved";
    }
    private void acceptCredential(byte[] bytes)throws Exception {
        var m=json(bytes,2*1024*1024);DeliveryJson.keys(m,"version","state","device_id","profile","credential_id","expires_at","scopes");version(m);
        need("approved".equals(str(m,"state"))&&state.getString("device").equals(str(m,"device_id"))&&PROFILE.equals(str(m,"profile"))&&DeliveryJson.array(m.get("scopes")).equals(List.of("read_assignment","submit_receipt")));
        id(str(m,"credential_id"));need(num(m,"expires_at")>clock.now());
        state.put("credential",str(m,"credential_id")).put("credential_expires",num(m,"expires_at"));state.remove("user_code");save();
    }
    private long certainNow()throws Exception {
        long now=clock.now();
        DeliveryClock.check(now,state.optLong("highest_time",0),processWall,clock.elapsed(),processElapsed,anchor.issued(),anchor.expires(),state.getLong("credential_expires"),bootCount(),state.getInt("clock_boot"),clock.automatic());return now;
    }
    private String onlineTrust()throws Exception {
        long now=certainNow();var response=call("/api/v2/group/trust",null,true,null);need(response.status()==200);
        Trust accepted=trust(response.body(),anchor,response.peer(),now,state.optLong("trust_generation",0),state.optString("trust_digest",""));
        state.put("trust_generation",accepted.generation()).put("trust_digest",accepted.digest()).put("trust_envelope",Base64.getEncoder().encodeToString(response.body()))
            .put("peer",response.peer()).put("highest_time",now);save();return response.peer();
    }
    private Assignment fetchAssignment()throws Exception {
        String peer=onlineTrust();var response=call("/api/v2/client/assignment?renderer="+BUILD+"&resource_profile="+PROFILE,null,true,peer);need(response.status()==200);
        Assignment next=assignment(response.body(),anchor,state.getString("device"),state.optLong("assignment_generation",0),state.optString("assignment_metadata",""));
        state.put("assignment_generation",next.generation()).put("assignment_metadata",next.metadata());save();return next;
    }
    public record Download(CapturedCandidate capture,PreparedAdmission.Request request){}
    public String transferDiagnostics(){return transferDiagnostics;}
    public String transferSummary(){try{return summarizeTransfer(transferDiagnostics).toString();}catch(Exception invalid){return "{}";}}
    static JSONObject summarizeTransfer(String raw)throws Exception{
        JSONObject source=new JSONObject(raw),out=new JSONObject();String candidate=source.optString("candidate","none"),reason=source.optString("restart_reason","none");
        out.put("candidate",candidate.matches("[a-f0-9]{64}")?candidate:"none").put("restart_reason",reason.matches("[a-z0-9_]{1,64}")?reason:"invalid_diagnostic");
        for(String key:List.of("reused_bytes","reused_accepted_bytes","downloaded_bytes","resumed_offset","staged_bytes","artifact_gets","reused_files"))out.put(key,Math.max(0,source.optLong(key,0)));
        return out;
    }
    public long transferRetryMillis(){return Math.max(0,Math.min(120000,retryUntil-clock.elapsed()));}
    public synchronized void fullResync()throws Exception{
        need(context!=null);ResumableCapture.discardIncomplete(context.getNoBackupFilesDir().getCanonicalFile().toPath().resolve("captured-candidates"));
        state.put("full_transfer_token",UUID.randomUUID().toString());save();
        transferDiagnostics=new JSONObject().put("restart_reason","full_resync").toString();persistTransferDiagnostic();
    }
    private void persistTransferDiagnostic()throws Exception{
        diagnosticFile("transfer-state.json",transferDiagnostics);
    }
    static String transferFailureReason(Exception failure){
        if(failure instanceof ResumableCapture.TransferFailure)return "http_"+((ResumableCapture.TransferFailure)failure).status;
        String detail=String.valueOf(failure.getMessage());
        return Set.of("capture_budget","capture_disk_full","transfer_busy","transfer_range","transfer_validator","transfer_length","transfer_encoding","transfer_short","transfer_trailing","transfer_hash_exhausted","unowned_capture").contains(detail)?detail:"interrupted_or_invalid";
    }
    private void diagnosticFile(String name,String value)throws Exception{
        if(context==null)return;byte[] bytes=value.getBytes(StandardCharsets.UTF_8);need(bytes.length<=16384);
        android.util.AtomicFile file=new android.util.AtomicFile(new File(context.getFilesDir(),name));FileOutputStream out=null;
        try{out=file.startWrite();out.write(bytes);file.finishWrite(out);}catch(Exception failure){if(out!=null)file.failWrite(out);throw failure;}
    }
    public synchronized Download download()throws Exception {
        return download(null);
    }
    public synchronized Download download(String locallyComplete)throws Exception {
        if(transferRetryMillis()>0)throw new ResumableCapture.TransferFailure("transfer_retry_pending",429,transferRetryMillis());
        for(int retry=0;;retry++)try{return downloadOnce(locallyComplete);}catch(ResumableCapture.TransferFailure failure){
            if((failure.status==409||failure.status==416)&&retry==0)continue;
            if(failure.status==429){retryUntil=clock.elapsed()+failure.retryMillis;state.put("transfer_retry_boot",clock.boot()).put("transfer_retry_elapsed",retryUntil);save();}
            throw failure;
        }
    }
    private Download downloadOnce(String locallyComplete)throws Exception {
        live=fetchAssignment();var request=live.request();String peer=state.getString("peer"),secret=secret();
        boolean full=state.has("full_transfer_token");
        if(!full&&request.pkg().canonicalIdentity().equals(locallyComplete)){
            verify(request,PreparedAdmission.Phase.PRIVATE_REOPEN);return null;
        }
        String base="/api/v2/publications/"+request.pkg().canonicalIdentity()+"/";
        if(context!=null){
            var stats=new ResumableCapture.Stats(request.pkg().canonicalIdentity());
            String binding=LocalView.digest((anchor.group()+"\n"+anchor.server()+"\n"+anchor.origin()+"\n"+state.getString("device")+"\n"+live.generation()+"\n"+live.metadata()+"\n"+request.factsFingerprint()+"\n"+budgetBinding(request)+"\n"+state.optString("full_transfer_token","")).getBytes(StandardCharsets.UTF_8));
            if(full)stats.reason="full_resync";
            try{
                var captured=ResumableCapture.capture(context.getNoBackupFilesDir().getCanonicalFile().toPath().resolve("captured-candidates"),
                    full?null:context.getFilesDir().getCanonicalFile().toPath().resolve("fixture-publications/revisions"),request,binding,false,
                    (part,path,pin,offset)->{String group=part==CapturedCandidate.Part.PACKAGE?"package":part==CapturedCandidate.Part.KIOSK?"kiosk":"tv";
                        String escaped=new java.net.URI(null,null,"/"+path,null).getRawPath().substring(1);return transport.rangeArtifact(base+group+"/"+escaped,secret,pin.size(),pin.sha256(),offset,peer);},
                    progress->{try{transferDiagnostics=progress.json().toString();}catch(Exception invalid){throw new IOException("transfer_diagnostic");}},stats);
                try{transferDiagnostics=stats.json().toString();persistTransferDiagnostic();if(full){state.remove("full_transfer_token");save();}return new Download(captured,request);}
                catch(Exception failure){captured.close();throw failure;}
            }catch(Exception failure){if(stats.reason.equals("none"))stats.reason=transferFailureReason(failure);transferDiagnostics=stats.json().toString();persistTransferDiagnostic();throw failure;}
        }
        CapturedCandidate captured=capture.create(request,source(base+"package/",request.pkg().files(),peer,secret),source(base+"kiosk/",request.kiosk().files(),peer,secret),source(base+"tv/",request.tv().files(),peer,secret));
        return new Download(captured,request);
    }
    private LocalView.Source source(String base,Map<String,DevelopmentWitness.Pin> pins,String peer,String secret){
        return new LocalView.Source(){public Set<String> files(){return pins.keySet();}public InputStream open(String path)throws IOException {
            if(!pins.containsKey(path))throw new IOException("unlisted_artifact");
            try {String escaped=new java.net.URI(null,null,"/"+path,null).getRawPath().substring(1);return transport.artifact(base+escaped,secret,pins.get(path).size(),peer);}
            catch(Exception e){throw new IOException("artifact_refused");}
        }};
    }
    @Override public String issuerId(){return "native-device-delivery-v1";}
    private static String budgetBinding(PreparedAdmission.Request r){return r.images().toString()+"/"+r.storage().toString();}
    @Override public synchronized void verify(PreparedAdmission.Request request,PreparedAdmission.Phase phase)throws IOException {
        try {
            need(anchor!=null);String packageId=request.pkg().canonicalIdentity();JSONObject associations=state.optJSONObject("accepted");
            if(phase==PreparedAdmission.Phase.NEW_ACTIVATION){
                need(live!=null&&live.request().factsFingerprint().equals(request.factsFingerprint())&&budgetBinding(live.request()).equals(budgetBinding(request)));
                Assignment latest=fetchAssignment();need(latest.generation()==live.generation()&&latest.metadata().equals(live.metadata())&&latest.request().factsFingerprint().equals(request.factsFingerprint()));
                if(associations==null)associations=new JSONObject();need(associations.length()<64||associations.has(packageId));
                associations.put(packageId,new JSONObject().put("facts",request.factsFingerprint()).put("budgets",budgetBinding(request)).put("generation",live.generation()).put("metadata",live.metadata()).put("group",anchor.group()).put("device",state.getString("device")));
                state.put("accepted",associations);save();
            }else {
                need(associations!=null&&associations.has(packageId));var a=associations.getJSONObject(packageId);
                need(a.getString("facts").equals(request.factsFingerprint())&&a.getString("budgets").equals(budgetBinding(request))&&a.getString("group").equals(anchor.group())&&a.getString("device").equals(state.getString("device")));
            }
        }catch(Exception e){throw new IOException("native_source_refused");}
    }
    public synchronized void queueReady(String packageId,String mode,String session)throws Exception {
        need(List.of("kiosk","tv").contains(mode));JSONObject associations=state.optJSONObject("accepted");need(associations!=null&&associations.has(packageId));
        JSONObject a=associations.getJSONObject(packageId);JSONArray queue=state.optJSONArray("outbox");if(queue==null)queue=new JSONArray();
        for(int i=0;i<queue.length();i++){JSONObject r=new JSONObject(queue.getString(i));if(r.getString("package_id").equals(packageId)&&r.getString("mode").equals(mode)&&r.getString("session").equals(session))return;}
        need(queue.length()<256);queue.put(new JSONObject().put("version",1).put("receipt_id",UUID.randomUUID().toString()).put("group_id",anchor.group()).put("device_id",state.getString("device"))
            .put("generation",a.getLong("generation")).put("package_id",packageId).put("mode",mode).put("session",session).put("result","ready").toString());state.put("outbox",queue);save();
    }
    public synchronized int flush()throws Exception {
        if(!enrolled())return 0;JSONArray queue=state.optJSONArray("outbox");if(queue==null||queue.length()==0)return 0;
        // Historical accepted ready reports need no new admission authority. The exact accepted TLS peer
        // remains pinned, while the server independently enforces credential expiry/revocation.
        String peer=state.getString("peer");int count=0;
        while(queue.length()>0){String exact=queue.getString(0);var response=transport.call("/api/v2/client/receipts",secret(),exact.getBytes(StandardCharsets.UTF_8),2*1024*1024,peer);need(response.status()==200);queue.remove(0);state.put("outbox",queue);save();count++;
            try{JSONObject ready=new JSONObject(exact);diagnosticFile("receipt-delivery.json",new JSONObject().put("package_id",ready.getString("package_id")).put("mode",ready.getString("mode")).put("session",ready.getString("session")).put("http_status",response.status()).put("body_sha256",LocalView.digest(exact.getBytes(StandardCharsets.UTF_8))).put("queue_remaining",queue.length()).toString());}catch(Exception diagnosticOnly){}
        }return count;
    }
}
