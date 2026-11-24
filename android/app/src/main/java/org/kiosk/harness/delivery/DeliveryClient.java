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
import org.kiosk.harness.pairing.PairingPayload;
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
    private org.kiosk.harness.publishing.PublisherAuthority.Admission publisherCandidate;
    private volatile ContentProgress progress;
    private volatile boolean progressClosed;
    private boolean progressUnavailable;
    private ContentProgress.Token progressToken;
    private PreparedAdmission.Request progressRequest;
    private long progressBytes,progressTotal;
    private volatile java.util.function.Consumer<String> progressListener=text->{};
    private long progressUiAt;private String progressUiState="";
    public void setProgressListener(java.util.function.Consumer<String> listener){progressListener=listener;}
    private volatile String transferDiagnostics="{}";
    private volatile long retryUntil;
    private volatile long credentialRetryUntil;
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
    public String trustedGroup(){Bootstrap b=anchor;return b==null?"":b.group();}
    /** Public certificate only, from the already independently confirmed anchor. */
    public String confirmedPublicCa(){Bootstrap b=anchor;if(b==null)throw new IllegalStateException("setup_required");return b.ca();}
    /** Explicit native setup only, after independently comparing the root fingerprint. */
    public synchronized void confirmPublisherRoot(String spki,String expectedSha256)throws Exception {
        var key=org.kiosk.harness.publishing.PublisherAuthority.publicKey(spki);
        need(org.kiosk.harness.publishing.PublisherAuthority.keyId(key).equals(hash(expectedSha256)));
        JSONObject prior=state.optJSONObject("publisher_anchor");
        if(prior!=null){need(prior.getString("root_spki").equals(spki));return;}
        need(anchor!=null);
        state.put("publisher_anchor",new JSONObject().put("root_spki",spki).put("policy_floor",0).put("heads",new JSONArray()));save();
    }

    private byte[] publisherAssignment(byte[] bytes)throws Exception {
        var value=json(bytes,2*1024*1024);
        JSONObject publisher=state.optJSONObject("publisher_anchor");
        boolean signed=num(value,"version")==3;
        publisherCandidate=null;
        if(!signed){if(publisher!=null)refuse("publisher_unsigned_assignment_refused");return bytes;}
        if(publisher==null)refuse("publisher_setup_required");
        org.kiosk.harness.delivery.DeliveryJson.keys(value,"version","group_id","device_id","profile","generation","metadata_sha256","publication","display","publisher");
        Set<String> heads=new HashSet<>();JSONArray saved=publisher.getJSONArray("heads");
        for(int i=0;i<saved.length();i++)heads.add(saved.getString(i));
        publisherCandidate=org.kiosk.harness.publishing.PublisherAuthority.assignment(obj(value,"publisher"),value,
            org.kiosk.harness.publishing.PublisherAuthority.publicKey(publisher.getString("root_spki")),
            anchor.origin(),clock.now(),publisher.optLong("policy_floor",0),heads);
        var legacy=new TreeMap<String,Object>(value);legacy.remove("publisher");
        legacy.put("version",new org.kiosk.harness.delivery.DeliveryJson.NumberToken("2"));
        return org.kiosk.harness.publishing.PublisherAuthority.canonical(legacy);
    }
    /**
     * Bounded preflight for the separate administration WebView process. It validates
     * the bootstrap window, certain time, TLS chain/hostname and the saved leaf pin,
     * but grants no admin authority: the server still requires its own web login.
     */
    public synchronized void checkAdminAvailability()throws Exception {
        need(anchor!=null);
        long now=clock.now();
        // Administration is not device admission: an already-confirmed anchor stays
        // usable after the short initial-enrollment bootstrap window, while the
        // WebView still performs its own strict TLS validation and the server its login.
        DeliveryClock.check(now,state.optLong("highest_time",0),processWall,clock.elapsed(),processElapsed,
            anchor.issued(),Long.MAX_VALUE,Long.MAX_VALUE,bootCount(),state.getInt("clock_boot"),clock.automatic());
        var response=call("/api/version",null,false,currentPin());
        need(response.status()==200);
    }
    public synchronized void confirm(byte[] bytes)throws Exception {
        need(anchor==null);long now=clock.now();Bootstrap b=bootstrap(bytes,now);wires.create(b);
        JSONObject initial=new JSONObject().put("bootstrap",new String(bytes,StandardCharsets.UTF_8)).put("confirmed_at",now).put("highest_time",now).put("clock_boot",bootCount())
            .put("device",UUID.randomUUID().toString()).put("request",UUID.randomUUID().toString()).put("nonce",UUID.randomUUID().toString());
        byte[] secret=new byte[32];new SecureRandom().nextBytes(secret);initial.put("secret",hex(secret));disk.write(initial);state=initial;loadAnchor();
    }
    /** Public facts for the operator confirmation step; contains no credential or secret. */
    public record Renewal(String bootstrapId,String origin,String group,String server,String keyId,
                          long issued,long expires,long deviceTime,boolean unchanged){}
    /** Validates a same-anchor public renewal without persisting it. */
    public synchronized Renewal inspectRenewal(byte[] bytes)throws Exception {return renewal(bytes,false,true);}
    /**
     * Additive manual same-anchor renewal. The operator attests the displayed independent time here; this
     * never marks uncertain-boot time confirmed, so confirmClock() remains a separate action before network use.
     */
    public synchronized Renewal renew(byte[] bytes,boolean operatorConfirmedTime)throws Exception {
        need(operatorConfirmedTime);return renewal(bytes,true,true);
    }
    private Renewal renewal(byte[] bytes,boolean commit,boolean operatorConfirmedTime)throws Exception {
        need(anchor!=null&&operatorConfirmedTime);
        long now=clock.now(),elapsed=clock.elapsed();
        Bootstrap current=anchor,next=bootstrap(bytes,now);
        need(sameAnchor(current,next));
        long highest=state.optLong("highest_time",0);
        // Strict monotonic input: no older issuance, no shorter validity, no window already behind the trusted floor.
        need(next.issued()>=current.issued()&&next.expires()>=current.expires()&&next.expires()>highest);
        need(now>=highest&&elapsed>=processElapsed&&now+2>=processWall+(elapsed-processElapsed)/1000);
        // Existing accepted registration must still be finite and the saved signed trust/leaf must bound this input.
        need(enrolled());long credentialExpires=state.optLong("credential_expires",0);
        need(credentialExpires>0&&credentialExpires!=Long.MAX_VALUE&&credentialExpires>now);
        String envelope=state.optString("trust_envelope","");
        need(!envelope.isEmpty());
        Trust trust=persistedTrust(Base64.getDecoder().decode(envelope),current,now);
        need(next.expires()<=trust.expires());
        boolean unchanged=next.id().equals(current.id())&&next.issued()==current.issued()&&next.expires()==current.expires();
        Renewal facts=new Renewal(next.id(),next.origin(),next.group(),next.server(),next.keyId(),next.issued(),next.expires(),now,unchanged);
        if(!commit||unchanged)return facts;
        DeliveryIO.Wire validated=wires.create(next);
        state.put("bootstrap",new String(bytes,StandardCharsets.UTF_8)).put("confirmed_at",now).put("highest_time",now);
        save();
        anchor=next;transport=validated;
        return facts;
    }
    private static boolean sameAnchor(Bootstrap a,Bootstrap b){
        return a.group().equals(b.group())&&a.server().equals(b.server())&&a.origin().equals(b.origin())
            &&a.ca().equals(b.ca())&&a.keyId().equals(b.keyId())&&a.key().equals(b.key());
    }
    private static String hex(byte[] b){StringBuilder s=new StringBuilder();for(byte v:b)s.append(String.format(Locale.ROOT,"%02x",v&255));return s.toString();}
    private byte[] body(JSONObject value){return value.toString().getBytes(StandardCharsets.UTF_8);}
    private String secret()throws Exception{return state.getString("secret");}
    /** The single identity this device currently trusts: v1 leaf pin, or the v2 intermediate issuer pin. */
    private NativeTransport.PeerPin currentPin(){
        if(state.optInt("trust_version",1)>=2)return NativeTransport.PeerPin.issuer(state.optString("trust_issuer",""));
        return NativeTransport.PeerPin.leaf(state.optString("peer",""));
    }
    private NativeTransport.Response call(String path,JSONObject body,boolean auth,NativeTransport.PeerPin pin)throws Exception {
        var response=transport.call(path,auth?secret():null,body==null?null:body(body),2*1024*1024,pin);
        if(auth&&(response.status()==401||response.status()==403))recordRefusal(response);
        return response;
    }
    /**
     * Persist the server's own fixed refusal label for any authenticated call, not only
     * renewal. A revoked/replaced credential or an expired signed authority therefore
     * surfaces with its real recovery path instead of a generic "update pending".
     */
    private void recordRefusal(NativeTransport.Response response)throws Exception{
        String code=refusalCode(response.body());
        String recovery;
        if("credential_expired".equals(code))recovery="credential_expired";
        else if("invalid_credential".equals(code)||"credential_revoked".equals(code))recovery="credential_revoked";
        else if("admission_authority_expired".equals(code))recovery="authority_expired";
        else return;
        String prior=state.optString("credential_recovery","");
        state.put("credential_recovery",recovery).put("credential_error",code);save();
        if(!recovery.equals(prior))try{diagnosticFile("authority-refusal.json",new JSONObject()
            .put("contract","lan-trust-lifecycle-v2").put("recovery",recovery).put("code",code)
            .put("at",clock.now()).toString());}catch(Exception diagnosticOnly){}
    }
    public synchronized String humanCode(){return state.optString("user_code","");}
    public synchronized boolean enrolled(){return state.has("credential");}
    /**
     * Exact QR contract for the current pending request, or empty when there is nothing displayable.
     * Expiry is evaluated against the device clock only to stop showing a dead code; authority still
     * comes from the server's own request state.
     */
    public synchronized String pairingPayload()throws Exception{
        if(anchor==null||enrolled())return "";
        String code=humanCode(),origin=anchor.origin();long expires=state.optLong("pair_expires",0);
        if(!code.matches(PairingPayload.USER_CODE)||expires<=0||clock.now()>=expires)return "";
        return PairingPayload.of(origin,code);
    }
    public synchronized long pendingExpiresAt(){return state.optLong("pair_expires",0);}
    /** Terminal denial/expiry/cancel stops automatic re-request until an explicit re-enrollment. */
    public synchronized boolean pairingBlocked(){return !state.optString("pair_blocked","").isEmpty();}
    public synchronized String pairingState(){return state.optString("pair_blocked","pending");}
    /** Drops local waiting only. The server request is left pending until the administrator decides. */
    public synchronized void cancelPending()throws Exception{
        need(anchor!=null&&!enrolled());
        clearPending("cancelled");
    }
    private void clearPending(String reason)throws Exception{
        state.remove("device_code");state.remove("user_code");state.remove("pair_expires");
        state.put("request",UUID.randomUUID().toString()).put("nonce",UUID.randomUUID().toString()).put("pair_blocked",reason);save();
    }
    private int bootCount(){return clock.boot();}
    /** Bounded non-secret lifecycle facts for local diagnostics and physical acceptance records. */
    public synchronized JSONObject diagnostics(){
        JSONObject out=new JSONObject();
        try{
            out.put("confirmed",confirmed()).put("enrolled",enrolled())
               .put("trust_version",state.optInt("trust_version",0))
               .put("trust_generation",state.optLong("trust_generation",0))
               .put("trust_expires",state.optLong("trust_expires",0))
               .put("credential_expires",state.optLong("credential_expires",0))
               .put("credential_recovery",credentialRecovery())
               .put("credential_error",credentialError())
               .put("clock_boot",state.optInt("clock_boot",-1))
               .put("actual_boot",bootCount())
               .put("highest_time",state.optLong("highest_time",0))
               .put("now",clock.now()).put("automatic_time",clock.automatic())
               .put("device_sha256",LocalView.digest(state.optString("device","").getBytes(StandardCharsets.UTF_8)))
               .put("accepted_count",state.optJSONObject("accepted")==null?0:state.optJSONObject("accepted").length())
               .put("outbox_count",state.optJSONArray("outbox")==null?0:state.optJSONArray("outbox").length())
               .put("trust_issuer_present",!state.optString("trust_issuer","").isEmpty());
        }catch(Exception failure){try{out.put("diagnostics_error",String.valueOf(failure.getMessage()));}catch(Exception ignored){}}
        return out;
    }
    /** A native operator confirms uncertain reboot time without replacing a valid enrollment. */
    public synchronized void confirmClock()throws Exception {
        need(anchor!=null);long now=clock.now(),elapsed=clock.elapsed();int boot=bootCount();
        // The bootstrap expiry is an initial-enrollment freshness window, not the
        // lifetime of the confirmed anchor: a long-disconnected device must still be
        // able to confirm time and obtain renewed signed authority or re-pair.
        DeliveryClock.check(now,state.getLong("highest_time"),now,elapsed,elapsed,anchor.issued(),Long.MAX_VALUE,Long.MAX_VALUE,boot,boot,clock.automatic());
        state.put("clock_boot",bootCount()).put("highest_time",now);save();processWall=now;processElapsed=clock.elapsed();
    }
    /** Explicit native action, never a page/Intent callback. Retains anchor and accepted offline associations. */
    public synchronized void reenroll()throws Exception {
        confirmClock();
        if(progress!=null)progress.close();progress=null;progressToken=null;progressRequest=null;
        byte[] secret=new byte[32];new SecureRandom().nextBytes(secret);
        state.put("secret",hex(secret)).put("request",UUID.randomUUID().toString()).put("nonce",UUID.randomUUID().toString()).put("clock_boot",bootCount());
        for(String key:List.of("credential","credential_expires","credential_recovery","credential_error","device_code","user_code","pair_expires","pair_blocked"))state.remove(key);save();
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
        need(state.getString("request").equals(str(m,"request_id"))&&str(m,"device_code").matches("[a-f0-9]{64}")&&str(m,"user_code").matches(PairingPayload.USER_CODE)&&num(m,"expires_in")>0&&num(m,"expires_in")<=600&&num(m,"interval")==5);
        state.put("device_code",str(m,"device_code")).put("user_code",str(m,"user_code"))
            .put("pair_expires",clock.now()+num(m,"expires_in")).remove("pair_blocked");save();
    }
    public synchronized String poll()throws Exception {
        if(enrolled())return "approved";need(state.has("device_code"));
        var response=call("/api/v2/device/token",new JSONObject().put("device_code",state.getString("device_code")),false,null);
        if(response.status()==202||response.status()==429)return "pending";
        if(response.status()==403){clearPending("denied");return "denied";}if(response.status()==410){
            // Approved credentials remain recoverable after the authorization request itself expires.
            response=call("/api/v2/client/status",null,true,null);
            if(response.status()!=200){clearPending("expired");return "expired";}
        }
        need(response.status()==200);acceptCredential(response.body());return "approved";
    }
    private void acceptCredential(byte[] bytes)throws Exception {
        var m=json(bytes,2*1024*1024);DeliveryJson.keys(m,"version","state","device_id","profile","credential_id","expires_at","scopes");version(m);
        need("approved".equals(str(m,"state"))&&state.getString("device").equals(str(m,"device_id"))&&PROFILE.equals(str(m,"profile"))&&DeliveryJson.array(m.get("scopes")).equals(List.of("read_assignment","submit_receipt")));
        id(str(m,"credential_id"));need(num(m,"expires_at")>clock.now());
        state.put("credential",str(m,"credential_id")).put("credential_expires",num(m,"expires_at"));
        state.remove("user_code");state.remove("pair_expires");state.remove("pair_blocked");state.remove("credential_recovery");state.remove("credential_error");save();
    }
    /**
     * lan-trust-lifecycle-v2 credential renewal: POST /api/v2/device/renew with the still-valid bearer.
     * device_id, credential_id and the local secret stay unchanged; only expires_at advances. Nothing
     * here extends root-signed group-trust authority, and an expired credential is never cleared
     * silently - it is flagged for explicit recovery/fresh enrollment.
     */
    static final long RENEW_WINDOW=86400,CREDENTIAL_MAX_LIFETIME=7*86400,RENEW_RETRY_CEILING=3600;
    public synchronized boolean credentialRenewalDue(){
        if(!enrolled())return false;long now=clock.now(),expires=state.optLong("credential_expires",0);
        return expires>0&&now<expires&&expires-now<RENEW_WINDOW;
    }
    public synchronized long credentialExpiresAt(){return state.optLong("credential_expires",0);}
    /** Non-empty only after the server definitively rejected the saved credential; identity is retained. */
    public synchronized String credentialRecovery(){return state.optString("credential_recovery","");}
    /** The fixed server refusal label that produced the recovery state, or empty for a local reason. */
    public synchronized String credentialError(){return state.optString("credential_error","");}
    /** Fixed `{version:1,error:<code>}` body only; nothing else is interpreted. */
    static String refusalCode(byte[] body){
        try{
            JSONObject value=new JSONObject(new String(body,StandardCharsets.UTF_8));
            if(value.length()!=2||value.optInt("version",0)!=1)return "";
            String code=value.optString("error","");
            return code.matches("[a-z][a-z0-9_]{0,63}")?code:"";
        }catch(Exception invalid){return "";}
    }
    public synchronized void renewCredential()throws Exception {
        need(anchor!=null&&enrolled());
        long now=certainNow(),expires=state.optLong("credential_expires",0);
        need(expires>0&&now<expires&&expires-now<RENEW_WINDOW);
        var response=call("/api/v2/device/renew",new JSONObject(),true,currentPin());
        if(response.status()==401||response.status()==403){
            // Distinguish the server's actual refusal instead of calling every 401 an
            // expiry. Registration, accepted content and identity are always retained.
            String code=refusalCode(response.body());
            String recovery;
            if("credential_expired".equals(code))recovery="credential_expired";
            else if("invalid_credential".equals(code))recovery="credential_revoked";
            else if("admission_authority_expired".equals(code))recovery="authority_expired";
            else recovery="credential_refused";
            state.put("credential_recovery",recovery).put("credential_error",code).put("highest_time",now)
                .remove("credential_retry_elapsed");save();
            throw new IOException(recovery);
        }
        need(response.status()==200);
        var m=json(response.body(),16384);
        String device=str(m,"device_id"),credential=str(m,"credential_id");
        long next=num(m,"expires_at");
        need(state.getString("device").equals(device)&&state.getString("credential").equals(credential));
        need(next>expires&&next>now&&next<=now+CREDENTIAL_MAX_LIFETIME);
        state.put("credential_expires",next).put("credential_renewed_at",now).put("credential_failures",0)
            .put("highest_time",now);state.remove("credential_recovery");state.remove("credential_error");state.remove("credential_retry_elapsed");save();
        try{JSONObject record=new JSONObject().put("contract","lan-trust-lifecycle-v2").put("result","renewed")
            .put("credential_id_sha256",LocalView.digest(credential.getBytes(StandardCharsets.UTF_8)))
            .put("previous_expires_at",expires).put("expires_at",next).put("at",now).put("http_status",response.status());
            diagnosticFile("credential-renewal.json",record.toString());}catch(Exception diagnosticOnly){}
    }
    /** Automatic attempt inside the 24h window with bounded retry; failure keeps the valid credential usable. */
    private void renewCredentialIfDue()throws Exception {
        if(!credentialRenewalDue()||credentialRetryUntil>clock.elapsed())return;
        try{renewCredential();}
        catch(IOException failure){
            String recovery=credentialRecovery();
            // A definitive expiry/revocation stops automatic retry until the operator
            // re-pairs; an expired signed authority or an unrecognized refusal keeps
            // the still-valid credential and retries on the bounded schedule.
            if("credential_expired".equals(recovery)||"credential_revoked".equals(recovery))throw failure;
            long failures=Math.min(12,state.optLong("credential_failures",0)+1);
            credentialRetryUntil=clock.elapsed()+Math.min(RENEW_RETRY_CEILING,60L<<(int)Math.min(6,failures-1));
        }
    }
    private long certainNow()throws Exception {        long now=clock.now();
        // Bootstrap expiry bounds only first confirmation/renewal of the anchor. The
        // confirmed anchor, credential and signed group authority govern later use.
        DeliveryClock.check(now,state.optLong("highest_time",0),processWall,clock.elapsed(),processElapsed,anchor.issued(),Long.MAX_VALUE,state.getLong("credential_expires"),bootCount(),state.getInt("clock_boot"),clock.automatic());return now;
    }
    /** Re-verifies the stored envelope with the verifier its own version selects; never downgrades v2 to v1. */
    private Trust persistedTrust(byte[] envelope,Bootstrap bound,long now)throws Exception {
        long prior=state.optLong("trust_generation",0);String priorDigest=state.optString("trust_digest","");
        if(envelopeVersion(envelope)==2){
            String issuer=state.optString("trust_issuer","");need(!issuer.isEmpty());
            return trustV2(envelope,bound,issuer,now,prior,priorDigest).trust();
        }
        need(state.optInt("trust_version",1)<2);
        return trust(envelope,bound,state.getString("peer"),now,prior,priorDigest);
    }
    private NativeTransport.PeerPin onlineTrust()throws Exception {
        long now=certainNow();var response=call("/api/v2/group/trust",null,true,null);need(response.status()==200);
        long prior=state.optLong("trust_generation",0);String priorDigest=state.optString("trust_digest","");
        if(envelopeVersion(response.body())==2){
            // One-way upgrade: the pinned intermediate issuer replaces the leaf pin, so a later
            // legitimate leaf rotation needs no re-enrollment and no v1 fallback is allowed.
            need(!response.issuerSha256().isEmpty());
            var accepted=trustV2(response.body(),anchor,response.issuerSha256(),now,prior,priorDigest);
            state.put("trust_generation",accepted.trust().generation()).put("trust_digest",accepted.trust().digest())
                .put("trust_envelope",Base64.getEncoder().encodeToString(response.body()))
                .put("trust_version",2).put("trust_issuer",accepted.issuerPin()).put("trust_expires",accepted.trust().expires())
                .put("highest_time",now);
            state.remove("peer");
            save();return NativeTransport.PeerPin.issuer(accepted.issuerPin());
        }
        need(state.optInt("trust_version",1)<2);
        Trust accepted=trust(response.body(),anchor,response.leafSha256(),now,prior,priorDigest);
        state.put("trust_generation",accepted.generation()).put("trust_digest",accepted.digest()).put("trust_envelope",Base64.getEncoder().encodeToString(response.body()))
            .put("peer",response.leafSha256()).put("trust_version",1).put("trust_expires",accepted.expires()).put("highest_time",now);save();
        return NativeTransport.PeerPin.leaf(response.leafSha256());
    }
    private Assignment fetchAssignment()throws Exception {
        NativeTransport.PeerPin peer=onlineTrust();
        long trustExpires=state.optLong("trust_expires",0);
        // Admission requires a currently valid signed group authority. The refresh
        // above has already stored it, so a long-disconnected device recovers
        // automatically once the offline administrator re-signs the group trust.
        if(trustExpires>0&&certainNow()>=trustExpires)throw new IOException("authority_expired");
        var caps=new JSONObject().put("version",1).put("platform","android").put("modes",new JSONArray(List.of("tv","kiosk")))
            .put("content",new JSONArray(List.of("events"))).put("resource_profile",PROFILE).put("renderer",BUILD);
        var reported=call("/api/v2/client/capabilities",caps,true,peer);
        need(reported.status()==200||reported.status()==404||reported.status()==405);
        var response=call("/api/v2/client/assignment?renderer="+BUILD+"&resource_profile="+PROFILE+"&display_protocol=display-profile-v1",null,true,peer);
        if(response.status()!=200){reportIncompatible(response);
            if(response.status()==409)throw new IOException("display_assignment_refused");need(false);}
        Assignment next=assignment(publisherAssignment(response.body()),anchor,state.getString("device"),state.optLong("assignment_generation",0),state.optString("assignment_metadata",""));
        String config=next.display().toString();
        if(next.generation()==state.optLong("assignment_generation",0)&&state.has("assignment_display")&&!config.equals(state.getString("assignment_display")))throw new IOException("display_profile_conflict");
        state.put("assignment_generation",next.generation()).put("assignment_metadata",next.metadata()).put("assignment_display",config);save();return next;
    }
    public record Download(CapturedCandidate capture,PreparedAdmission.Request request){}
    private void reportIncompatible(NativeTransport.Response response){
        try{
            if(progressUnavailable||(progress!=null&&progress.unsupported()))return;
            JSONObject error=new JSONObject(new String(response.body(),StandardCharsets.UTF_8));
            if(!"requires_update".equals(error.optString("error")))return;
            var hint=call("/api/v2/client/progress",null,true,currentPin());
            if(hint.status()==404||hint.status()==405){progressUnavailable=true;return;}if(hint.status()!=200)return;
            JSONObject b=new JSONObject(new String(hint.body(),StandardCharsets.UTF_8));
            need(b.length()==5&&b.getInt("version")==1&&state.getString("device").equals(b.getString("device_id"))&&anchor.group().equals(b.getString("group_id")));
            startProgress(new ContentProgress.Binding(b.getString("device_id"),b.getString("group_id"),b.getLong("generation"),b.getString("package_id")),0);
            report("incompatible",0,"requires_update");
        }catch(Exception advisoryOnly){}
    }
    private void startProgress(ContentProgress.Binding binding,long total){
        progressToken=null;
        if(progressClosed||progressUnavailable)return;
        try{
            if(progress==null){
                final DeliveryIO.Wire wire=transport;final String bearer=secret();final NativeTransport.PeerPin pin=currentPin();
                need(pin!=null);
                progress=new ContentProgress(bytes->wire.call("/api/v2/client/progress",bearer,bytes,2048,pin),new ContentProgress.Time(){public long elapsed(){return clock.elapsed();}public long wall(){return clock.now()*1000;}});
            }
            if(progressClosed){progress.close();return;}
            if(progress.unsupported())return;
            long first=Math.addExact(state.optLong("progress_high_water",0),1),limit=Math.addExact(first,ContentProgress.RESERVATION-1);
            // Reserve before emitting. A crash skips unused numbers; no telemetry body is persisted.
            state.put("progress_high_water",limit);save();progressTotal=total;progressBytes=0;
            progressToken=progress.begin(binding,first,limit,total);
        }catch(Exception advisoryOnly){}
    }
    private void startProgress(Assignment assignment){
        try{long total=0;var r=assignment.request();for(var files:List.of(r.pkg().files(),r.kiosk().files(),r.tv().files()))for(var pin:files.values())total=Math.addExact(total,pin.size());
            startProgress(new ContentProgress.Binding(state.getString("device"),anchor.group(),assignment.generation(),r.pkg().canonicalIdentity()),total);progressRequest=r;
        }catch(Exception advisoryOnly){progressToken=null;}
    }
    private void report(String status,long bytes,String error){
        if(progress!=null)progress.offer(progressToken,status,bytes,error);
        if(!status.equals(progressUiState)||clock.elapsed()-progressUiAt>=5000){
            progressUiState=status;progressUiAt=clock.elapsed();
            String text=switch(error){case "storage"->"Free local storage, then retry.";case "integrity"->"Retry verified download; check server content.";case "requires_update"->"Update this client.";case "assignment_changed"->"Assignment changed; sync again.";case "candidate_refused"->"Candidate refused; inspect local diagnostics.";case "connection"->"Check LAN and retry.";default->status+" "+bytes+"/"+progressTotal+" bytes.";};
            try{progressListener.accept(text);}catch(Exception ignored){}
        }
    }
    /** Called only after native admission (including package/views/images), never by screen opening. */
    public synchronized void admissionResult(PreparedAdmission.Request request,boolean verified){
        if(request!=progressRequest)return;
        report(verified?"verified":"error",verified?progressTotal:progressBytes,verified?"none":"candidate_refused");
    }
    public synchronized void admissionFailure(PreparedAdmission.Request request,Exception failure){
        if(request==progressRequest)report("error",progressBytes,progressError(failure));
    }
    static String progressError(Throwable failure){
        for(Throwable cause=failure;cause!=null;cause=cause.getCause()){
            String code=String.valueOf(cause.getMessage());
            if(cause instanceof java.nio.file.FileSystemException||Set.of("capture_disk_full","store_disk_full","capture_budget","admission_budget").contains(code))return "storage";
            if(Set.of("transfer_hash_exhausted","transfer_validator","transfer_range","transfer_length","transfer_encoding","transfer_short","transfer_trailing","reuse_changed").contains(code))return "integrity";
            if(cause instanceof ResumableCapture.TransferFailure&&((ResumableCapture.TransferFailure)cause).status==409)return "assignment_changed";
        }
        return failure instanceof IOException?"connection":"candidate_refused";
    }
    public void closeProgress(){progressClosed=true;progressListener=text->{};if(progress!=null)progress.close();}
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
        renewCredentialIfDue();
        for(int retry=0;;retry++)try{return downloadOnce(locallyComplete);}catch(ResumableCapture.TransferFailure failure){
            if((failure.status==409||failure.status==416)&&retry==0)continue;
            if(failure.status==429){retryUntil=clock.elapsed()+failure.retryMillis;state.put("transfer_retry_boot",clock.boot()).put("transfer_retry_elapsed",retryUntil);save();}
            throw failure;
        }
    }
    private Download downloadOnce(String locallyComplete)throws Exception {
        if(progress!=null)progress.abandon();progressToken=null;progressRequest=null;
        live=fetchAssignment();var request=live.request();NativeTransport.PeerPin peer=currentPin();need(peer!=null);String secret=secret();
        boolean full=state.has("full_transfer_token");
        if(!full&&request.pkg().canonicalIdentity().equals(locallyComplete)){
            verify(request,PreparedAdmission.Phase.PRIVATE_REOPEN);verify(request,PreparedAdmission.Phase.NEW_ACTIVATION);return null;
        }
        startProgress(live);
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
                    observed->{try{transferDiagnostics=observed.json().toString();if(observed.logicalBytes<progressBytes)startProgress(live);progressBytes=observed.logicalBytes;
                        if(observed.transferring)report("downloading",progressBytes,"none");}catch(Exception invalid){throw new IOException("transfer_diagnostic");}},stats);
                try{progressBytes=progressTotal;report("downloaded",progressTotal,"none");transferDiagnostics=stats.json().toString();persistTransferDiagnostic();if(full){state.remove("full_transfer_token");save();}return new Download(captured,request);}
                catch(Exception failure){captured.close();throw failure;}
            }catch(Exception failure){String reason=transferFailureReason(failure);report("error",progressBytes,progressError(failure));if(stats.reason.equals("none"))stats.reason=reason;transferDiagnostics=stats.json().toString();persistTransferDiagnostic();throw failure;}
        }
        try{CapturedCandidate captured=capture.create(request,source(base+"package/",request.pkg().files(),peer,secret),source(base+"kiosk/",request.kiosk().files(),peer,secret),source(base+"tv/",request.tv().files(),peer,secret));
            progressBytes=progressTotal;report("downloaded",progressTotal,"none");return new Download(captured,request);
        }catch(Exception failure){report("error",progressBytes,progressError(failure));throw failure;}
    }
    private LocalView.Source source(String base,Map<String,DevelopmentWitness.Pin> pins,NativeTransport.PeerPin peer,String secret){
        return new LocalView.Source(){public Set<String> files(){return pins.keySet();}public InputStream open(String path)throws IOException {
            if(!pins.containsKey(path))throw new IOException("unlisted_artifact");
            try {String escaped=new java.net.URI(null,null,"/"+path,null).getRawPath().substring(1);InputStream stream=transport.artifact(base+escaped,secret,pins.get(path).size(),peer);report("downloading",progressBytes,"none");return stream;}
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
                Assignment latest=fetchAssignment();boolean current=latest.generation()==live.generation()&&latest.metadata().equals(live.metadata())&&latest.display().equals(live.display())&&latest.request().factsFingerprint().equals(request.factsFingerprint());
                if(!current)report("error",progressBytes,"assignment_changed");need(current);
                if(associations==null)associations=new JSONObject();need(associations.length()<64||associations.has(packageId));
                associations.put(packageId,new JSONObject().put("facts",request.factsFingerprint()).put("budgets",budgetBinding(request)).put("generation",live.generation()).put("metadata",live.metadata()).put("display_mode",live.display().mode()).put("display_profile",live.display().id()).put("display_revision",live.display().revision()).put("group",anchor.group()).put("device",state.getString("device")));
                state.put("accepted",associations);
                if(publisherCandidate!=null){
                    var publisher=state.getJSONObject("publisher_anchor");
                    publisher.put("policy_floor",publisherCandidate.policyVersion())
                        .put("heads",new JSONArray().put(org.kiosk.harness.delivery.DeliveryProtocol.str(publisherCandidate.plan(),"id")));
                }
                save();
            }else {
                need(associations!=null&&associations.has(packageId));var a=associations.getJSONObject(packageId);
                need(a.getString("facts").equals(request.factsFingerprint())&&a.getString("budgets").equals(budgetBinding(request))&&a.getString("group").equals(anchor.group())&&a.getString("device").equals(state.getString("device")));
            }
        }catch(Exception e){throw new IOException("native_source_refused");}
    }
    public synchronized String assignedMode(String packageId,String fallback)throws Exception {
        JSONObject all=state.optJSONObject("accepted");
        if(all==null||!all.has(packageId))return fallback;
        String mode=all.getJSONObject(packageId).optString("display_mode","local");
        need(List.of("local","tv","kiosk").contains(mode));return mode.equals("local")?fallback:mode;
    }
    public synchronized String startupMode(String packageId,String fallback)throws Exception {
        JSONObject activated=state.optJSONObject("activated_display");
        if(activated!=null&&packageId.equals(activated.optString("package_id"))){String mode=activated.getString("mode");need(List.of("tv","kiosk").contains(mode));return mode;}
        return assignedMode(packageId,fallback);
    }
    public synchronized boolean modeAllowed(String packageId,String mode)throws Exception {return assignedMode(packageId,mode).equals(mode);}
    public synchronized void queueReady(String packageId,String mode,String session)throws Exception {
        need(List.of("kiosk","tv").contains(mode)&&modeAllowed(packageId,mode));JSONObject associations=state.optJSONObject("accepted");need(associations!=null&&associations.has(packageId));
        JSONObject a=associations.getJSONObject(packageId);
        String readyKey=LocalView.digest(new JSONArray(List.of(packageId,a.getLong("generation"),mode,session)).toString().getBytes(StandardCharsets.UTF_8));
        if(readyKey.equals(state.optString("last_ready_key","")))return;
        JSONArray queue=state.optJSONArray("outbox");if(queue==null)queue=new JSONArray();
        for(int i=0;i<queue.length();i++){JSONObject r=new JSONObject(queue.getString(i));if(r.getString("package_id").equals(packageId)&&r.getLong("generation")==a.getLong("generation")&&r.getString("mode").equals(mode)&&r.getString("session").equals(session))return;}
        need(queue.length()<256);queue.put(new JSONObject().put("version",1).put("receipt_id",UUID.randomUUID().toString()).put("group_id",anchor.group()).put("device_id",state.getString("device"))
            .put("generation",a.getLong("generation")).put("package_id",packageId).put("mode",mode).put("session",session).put("result","ready").toString());state.put("outbox",queue).put("last_ready_key",readyKey).put("activated_display",new JSONObject().put("package_id",packageId).put("mode",mode));save();
    }
    public synchronized int flush()throws Exception {
        if(!enrolled())return 0;JSONArray queue=state.optJSONArray("outbox");if(queue==null||queue.length()==0)return 0;
        // Historical accepted ready reports need no new admission authority. The exact accepted TLS peer
        // remains pinned, while the server independently enforces credential expiry/revocation.
        NativeTransport.PeerPin peer=currentPin();need(peer!=null);int count=0;
        while(queue.length()>0){String exact=queue.getString(0);var response=transport.call("/api/v2/client/receipts",secret(),exact.getBytes(StandardCharsets.UTF_8),2*1024*1024,peer);if(response.status()==401||response.status()==403)recordRefusal(response);need(response.status()==200);queue.remove(0);state.put("outbox",queue);save();count++;
            try{JSONObject ready=new JSONObject(exact);diagnosticFile("receipt-delivery.json",new JSONObject().put("package_id",ready.getString("package_id")).put("mode",ready.getString("mode")).put("session",ready.getString("session")).put("http_status",response.status()).put("body_sha256",LocalView.digest(exact.getBytes(StandardCharsets.UTF_8))).put("queue_remaining",queue.length()).toString());}catch(Exception diagnosticOnly){}
        }return count;
    }
}
