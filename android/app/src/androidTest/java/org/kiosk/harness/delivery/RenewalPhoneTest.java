package org.kiosk.harness.delivery;

import android.os.SystemClock;
import android.provider.Settings;
import android.test.InstrumentationTestCase;
import java.io.*;
import java.nio.charset.StandardCharsets;
import java.nio.file.*;
import java.util.*;
import org.json.*;
import org.kiosk.harness.core.LocalView;

/** Read-only saved state plus an in-memory store: validates the delivered renewal without touching device authority. */
@SuppressWarnings("deprecation")
public final class RenewalPhoneTest extends InstrumentationTestCase {
    private android.content.Context context(){return getInstrumentation().getTargetContext();}
    private String hash(String value){return LocalView.digest(value.getBytes(StandardCharsets.UTF_8));}
    private String fileHash()throws Exception{
        return LocalView.digest(Files.readAllBytes(context().getNoBackupFilesDir().toPath().resolve("delivery-v1.enc")));
    }
    private static final class Memory implements DeliveryIO.Store {
        JSONObject saved;int writes;
        Memory(JSONObject value)throws Exception{saved=new JSONObject(value.toString());}
        public JSONObject read()throws Exception{return new JSONObject(saved.toString());}
        public void write(JSONObject value)throws Exception{saved=new JSONObject(value.toString());writes++;}
    }
    private static final class Dummy implements DeliveryIO.Wire {
        public NativeTransport.Response call(String path,String secret,byte[] body,int cap,NativeTransport.PeerPin pin){throw new AssertionError("renewal test must not use network");}
        public InputStream artifact(String path,String secret,long size,NativeTransport.PeerPin pin){throw new AssertionError("renewal test must not fetch");}
    }
    private final DeliveryIO.Clock realClock=new DeliveryIO.Clock(){
        public long now(){return System.currentTimeMillis()/1000;}
        public long elapsed(){return SystemClock.elapsedRealtime();}
        public int boot(){return Settings.Global.getInt(context().getContentResolver(),Settings.Global.BOOT_COUNT,-1);}
        public boolean automatic(){return Settings.Global.getInt(context().getContentResolver(),Settings.Global.AUTO_TIME,0)==1;}
    };
    private byte[] asset()throws Exception{try(InputStream in=context().getAssets().open("delivery-bootstrap-renewal.json")){return LocalView.readBounded(in,16384);}}
    private DeliveryClient client(Memory memory)throws Exception{return new DeliveryClient(null,memory,b->new Dummy(),realClock,(r,p,k,t)->{throw new AssertionError("renewal test must not capture");});}
    private JSONObject report(String name,JSONObject value)throws Exception{
        try(var out=context().openFileOutput(name,0)){out.write(value.toString(2).getBytes(StandardCharsets.UTF_8));}return value;
    }
    public void testDeliveredRenewalHasSameSavedAnchorIdentity()throws Exception{
        JSONObject saved=new PrivateDeliveryState(context()).read();
        var anchor=DeliveryProtocol.bootstrap(saved.getString("bootstrap").getBytes(StandardCharsets.UTF_8),saved.getLong("confirmed_at"));
        var memory=new Memory(saved);var client=client(memory);
        var facts=client.inspectRenewal(asset());
        assertEquals(anchor.origin(),facts.origin());assertEquals(anchor.group(),facts.group());
        assertEquals(anchor.server(),facts.server());assertEquals(anchor.keyId(),facts.keyId());
        assertTrue(facts.issued()>=anchor.issued());assertTrue(facts.expires()>=anchor.expires());
        assertTrue(facts.deviceTime()>0);
        assertEquals("inspection must not persist",0,memory.writes);
        JSONObject out=new JSONObject().put("schema",1).put("source","read_only_saved_authority")
            .put("asset_sha256",LocalView.digest(asset()))
            .put("saved_origin",anchor.origin()).put("saved_group",anchor.group()).put("saved_server",anchor.server())
            .put("renewal_id",facts.bootstrapId()).put("renewal_issued",facts.issued()).put("renewal_expires",facts.expires())
            .put("device_time",facts.deviceTime()).put("already_accepted",facts.unchanged())
            .put("saved_boot",saved.optInt("clock_boot",-1)).put("actual_boot",realClock.boot())
            .put("credential_expires",saved.optLong("credential_expires",0))
            .put("in_memory_writes",memory.writes);
        report("phone-renewal-preflight.json",out);
    }
    public void testInMemoryRenewalPreservesDeviceCredentialTrustAndContent()throws Exception{
        String beforeFile=fileHash();
        JSONObject saved=new PrivateDeliveryState(context()).read();
        var memory=new Memory(saved);var client=client(memory);
        var facts=client.inspectRenewal(asset());
        var renewed=client.renew(asset(),true);
        assertEquals(facts.unchanged(),renewed.unchanged());
        JSONObject after=memory.read();
        for(String key:List.of("device","secret","request","credential","credential_expires","trust_generation","trust_digest","peer","trust_envelope","clock_boot")){
            assertEquals("preserved "+key,saved.get(key).toString(),after.get(key).toString());
        }
        if(saved.has("accepted"))assertEquals(saved.getJSONObject("accepted").toString(),after.getJSONObject("accepted").toString());
        if(saved.has("outbox"))assertEquals(saved.getJSONArray("outbox").toString(),after.getJSONArray("outbox").toString());
        assertTrue(after.getLong("highest_time")>=saved.getLong("highest_time"));
        assertEquals(beforeFile,fileHash());
        JSONObject out=new JSONObject().put("schema",1).put("source","in_memory_only")
            .put("unchanged_input",renewed.unchanged()).put("in_memory_writes",memory.writes)
            .put("real_state_ciphertext_unchanged",true)
            .put("device_hash",hash(saved.getString("device"))).put("credential_hash",hash(saved.getString("credential")))
            .put("secret_hash",hash(saved.getString("secret"))).put("request_hash",hash(saved.getString("request")))
            .put("accepted_present",saved.has("accepted")).put("outbox_count",saved.optJSONArray("outbox")==null?0:saved.getJSONArray("outbox").length())
            .put("bootstrap_id",DeliveryProtocol.bootstrap(after.getString("bootstrap").getBytes(StandardCharsets.UTF_8),after.getLong("confirmed_at")).id());
        report("phone-renewal-in-memory.json",out);
    }
}
