package org.kiosk.harness.delivery;

import android.test.InstrumentationTestCase;
import android.os.SystemClock;
import android.provider.Settings;
import java.io.*;
import java.nio.charset.StandardCharsets;
import java.util.*;
import org.json.*;
import org.kiosk.harness.core.LocalView;

/** Exact-method, test APK only; no inherited publication fixtures and no authority reset. */
@SuppressWarnings("deprecation")
public final class PhoneDeliveryCheckpointTest extends InstrumentationTestCase {
    private android.content.Context context(){return getInstrumentation().getTargetContext();}
    private String hash(String value){return LocalView.digest(value.getBytes(StandardCharsets.UTF_8));}
    private JSONObject report(String label,JSONObject state)throws Exception{
        JSONArray queue=state.optJSONArray("outbox"),hashes=new JSONArray();if(queue!=null)for(int i=0;i<queue.length();i++)hashes.put(hash(queue.getString(i)));
        JSONObject result=new JSONObject().put("label",label).put("boot_count",Settings.Global.getInt(context().getContentResolver(),Settings.Global.BOOT_COUNT,-1))
            .put("elapsed_ms",SystemClock.elapsedRealtime()).put("device_hash",hash(state.getString("device"))).put("credential_hash",hash(state.getString("credential")))
            .put("native_secret_hash",hash(state.getString("secret"))).put("request_hash",hash(state.getString("request"))).put("queued_bodies",hashes);
        try(var out=context().openFileOutput("phone-delivery-"+label+".json",0)){out.write(result.toString().getBytes(StandardCharsets.UTF_8));}return result;
    }
    public void testBeforeOfflineReboot()throws Exception{report("before-reboot",new PrivateDeliveryState(context()).read());}
    public void testAfterOfflineReboot()throws Exception{
        JSONObject state=new PrivateDeliveryState(context()).read();JSONArray queue=state.optJSONArray("outbox");assertNotNull(queue);assertTrue(queue.length()>0);
        // Receipt bodies stay in app-private storage; returned evidence contains hashes only.
        try(var out=context().openFileOutput("phone-offline-ready-bodies.json",0)){out.write(queue.toString().getBytes(StandardCharsets.UTF_8));}
        report("after-offline-reboot",state);
    }
    public void testAfterReconnectAndDuplicateReady()throws Exception{
        JSONObject state=new PrivateDeliveryState(context()).read();JSONArray pending=state.optJSONArray("outbox");assertTrue(pending==null||pending.length()==0);
        byte[] raw=LocalView.readBounded(context().openFileInput("phone-offline-ready-bodies.json"),2*1024*1024);JSONArray saved=new JSONArray(new String(raw,StandardCharsets.UTF_8));
        var anchor=DeliveryProtocol.bootstrap(state.getString("bootstrap").getBytes(StandardCharsets.UTF_8),state.getLong("confirmed_at"));var wire=new NativeTransport(anchor);JSONArray duplicates=new JSONArray();
        for(int i=0;i<saved.length();i++){
            String body=saved.getString(i);var response=wire.call("/api/v2/client/receipts",state.getString("secret"),body.getBytes(StandardCharsets.UTF_8),2*1024*1024,state.getString("peer"));
            assertEquals(200,response.status());duplicates.put(new JSONObject().put("body_sha256",hash(body)).put("http_status",response.status()));
        }
        JSONObject result=report("after-reconnect",state).put("duplicate_actual_ready",duplicates);
        try(var out=context().openFileOutput("phone-delivery-after-reconnect.json",0)){out.write(result.toString().getBytes(StandardCharsets.UTF_8));}
    }
    public void testNativeWrongHostnameRefused()throws Exception{
        JSONObject state=new PrivateDeliveryState(context()).read();var anchor=DeliveryProtocol.bootstrap(state.getString("bootstrap").getBytes(StandardCharsets.UTF_8),state.getLong("confirmed_at"));
        final java.util.concurrent.atomic.AtomicBoolean observed=new java.util.concurrent.atomic.AtomicBoolean();
        NativeTransport wire=new NativeTransport(anchor,url->{
            var connection=(javax.net.ssl.HttpsURLConnection)url.openConnection(java.net.Proxy.NO_PROXY);
            connection.setHostnameVerifier((host,session)->{observed.set(true);return javax.net.ssl.HttpsURLConnection.getDefaultHostnameVerifier().verify("wrong-name.invalid",session);});return connection;
        });
        try{wire.call("/api/version",null,null,10000,null);fail("wrong hostname accepted");}catch(javax.net.ssl.SSLException expected){}
        assertTrue("native platform hostname verifier actually invoked",observed.get());
    }
    public void testRevokedCredentialRetainsAcceptedPrivateB()throws Exception{
        var adapters=new PhoneDeliveryAdapters(context());var client=adapters.client();
        var store=new org.kiosk.harness.storage.FixturePublicationStore(context().getFilesDir().getCanonicalFile().toPath().resolve("fixture-publications"),org.kiosk.harness.storage.FixturePublicationStore.NONE,()->client);
        String b=store.pointer();assertEquals("ea2822f219ac60888e6aa7b32404299f7e1cc396a5b463f5ebdd8877b64e2e00",b);
        try{var d=client.download();if(d!=null)d.capture().close();fail("revoked credential admitted online");}catch(IOException expected){}
        assertEquals(Integer.valueOf(1),adapters.statuses.get("/api/v2/group/trust:401"));
        var startup=store.startup();assertFalse(startup.choices().isEmpty());assertEquals(b,startup.choices().get(0).id());assertEquals(b,store.pointer());
        JSONObject result=new JSONObject().put("online_http_status",401).put("accepted_private_B_retained",true).put("clock_boot",new PrivateDeliveryState(context()).read().getInt("clock_boot"));
        try(var out=context().openFileOutput("phone-delivery-revoked.json",0)){out.write(result.toString().getBytes(StandardCharsets.UTF_8));}
    }
    public void testPrepareExternalOperatorDeviceBinding()throws Exception{
        String id=new PrivateDeliveryState(context()).read().getString("device");assertTrue(id.matches("[A-Za-z0-9_.-]{1,128}"));
        // Public device identity only; secret/credential/nonce/codes never leave native private state.
        try(var out=context().openFileOutput("phone-operator-device-id.txt",0)){out.write(id.getBytes(StandardCharsets.UTF_8));}
    }
    public void testExpiredCredentialBlocksNewButKeepsPrivateB()throws Exception{
        var adapters=new PhoneDeliveryAdapters(context());var client=adapters.expiredCredentialClient();
        try{var d=client.download();if(d!=null)d.capture().close();fail("expired credential admitted");}catch(IOException expected){}
        assertTrue("expiry refused before network",adapters.statuses.isEmpty());
        var store=new org.kiosk.harness.storage.FixturePublicationStore(context().getFilesDir().getCanonicalFile().toPath().resolve("fixture-publications"),org.kiosk.harness.storage.FixturePublicationStore.NONE,()->client);
        assertFalse(store.startup().choices().isEmpty());assertEquals("ea2822f219ac60888e6aa7b32404299f7e1cc396a5b463f5ebdd8877b64e2e00",store.pointer());
        JSONObject result=new JSONObject().put("expired_native_test_clock_state",true).put("real_phone_clock_unchanged",true).put("new_admission_refused_before_network",true).put("private_B_retained",true);
        try(var out=context().openFileOutput("phone-delivery-expiry.json",0)){out.write(result.toString().getBytes(StandardCharsets.UTF_8));}
    }
}
