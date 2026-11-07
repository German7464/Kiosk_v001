package org.kiosk.harness.delivery;

import android.test.InstrumentationTestCase;
import org.json.*;
import java.nio.charset.StandardCharsets;
import java.util.*;
import org.kiosk.harness.core.LocalView;

/** Read-only saved-registration prerequisite check; never enrolls, connects or changes trust/time. */
@SuppressWarnings("deprecation")
public final class DiscoveryAuthorityPhoneTest extends InstrumentationTestCase {
    public void testWrongOriginRefusedBeforeCredentialTransmission()throws Exception{
        var context=getInstrumentation().getTargetContext();var disk=new PrivateDeliveryState(context);JSONObject original=disk.read();String unchanged=original.toString();java.util.concurrent.atomic.AtomicInteger calls=new java.util.concurrent.atomic.AtomicInteger();
        DeliveryIO.Store readOnly=new DeliveryIO.Store(){public JSONObject read()throws Exception{return new JSONObject(unchanged);}public void write(JSONObject value){throw new AssertionError("discovery must not write saved authority");}};
        DeliveryIO.Clock clock=new DeliveryIO.Clock(){public long now(){return System.currentTimeMillis()/1000;}public long elapsed(){return android.os.SystemClock.elapsedRealtime();}public int boot(){return android.provider.Settings.Global.getInt(context.getContentResolver(),android.provider.Settings.Global.BOOT_COUNT,-1);}public boolean automatic(){return true;}};
        DeliveryClient client=new DeliveryClient(null,readOnly,b->new DeliveryIO.Wire(){
            public NativeTransport.Response call(String path,String secret,byte[] body,int cap,String pin){calls.incrementAndGet();throw new AssertionError("wrong origin must not reach transport");}
            public java.io.InputStream artifact(String path,String secret,long size,String pin){calls.incrementAndGet();throw new AssertionError("wrong origin must not fetch artifacts");}
        },clock,(r,p,k,t)->{throw new AssertionError("discovery must not capture");});
        assertTrue(client.confirmed());String different=client.trustedOrigin().endsWith(":9443")?"https://untrusted:9444":"https://192.168.1.165:9443";
        getInstrumentation().runOnMainSync(()->{try{
            var activity=new org.kiosk.harness.StoredHarnessActivity();var f=activity.getClass().getDeclaredField("delivery");f.setAccessible(true);f.set(activity,client);
            var method=activity.getClass().getDeclaredMethod("confirmServer",String.class);method.setAccessible(true);method.invoke(activity,different);
            var worker=activity.getClass().getDeclaredMethod("shutdownWorker");worker.setAccessible(true);worker.invoke(activity);
        }catch(Exception failure){throw new AssertionError(failure);}});
        getInstrumentation().waitForIdleSync();assertEquals(0,calls.get());assertEquals(unchanged,disk.read().toString());
    }
    public void testReadOnlySavedAuthority()throws Exception{
        var context=getInstrumentation().getTargetContext();JSONObject s=new PrivateDeliveryState(context).read();JSONObject out=new JSONObject();
        out.put("observed_at",System.currentTimeMillis()/1000).put("has_saved_anchor",s.has("bootstrap")).put("enrolled",s.has("credential"));
        out.put("queued_receipts",s.optJSONArray("outbox")==null?0:s.getJSONArray("outbox").length());
        if(s.has("bootstrap")){
            var b=DeliveryProtocol.bootstrap(s.getString("bootstrap").getBytes(StandardCharsets.UTF_8),s.getLong("confirmed_at"));
            out.put("origin",b.origin()).put("group",b.group()).put("server",b.server()).put("bootstrap_expires",b.expires()).put("bootstrap_valid_now",System.currentTimeMillis()/1000<b.expires()).put("credential_expires",s.optLong("credential_expires",0));
            for(String k:List.of("device","credential","secret","request"))if(s.has(k))out.put(k+"_hash",LocalView.digest(s.getString(k).getBytes(StandardCharsets.UTF_8)));
            out.put("saved_boot",s.optInt("clock_boot",-1)).put("actual_boot",android.provider.Settings.Global.getInt(context.getContentResolver(),android.provider.Settings.Global.BOOT_COUNT,-1)).put("automatic_time",android.provider.Settings.Global.getInt(context.getContentResolver(),android.provider.Settings.Global.AUTO_TIME,0)==1);
            if(s.has("trust_envelope")){
                var envelope=DeliveryJson.object(DeliveryJson.parse(Base64.getDecoder().decode(s.getString("trust_envelope")),16384));
                var payload=DeliveryJson.object(DeliveryJson.parse(Base64.getDecoder().decode(DeliveryJson.string(envelope.get("payload_base64"))),8192));
                out.put("trust_envelope_present",true).put("trust_expires",DeliveryJson.integer(payload.get("expires_at"))).put("trust_generation",DeliveryJson.integer(payload.get("generation")));
                try{DeliveryProtocol.trust(Base64.getDecoder().decode(s.getString("trust_envelope")),b,s.getString("peer"),System.currentTimeMillis()/1000,s.getLong("trust_generation"),s.getString("trust_digest"));out.put("saved_trust_valid_now",true);}catch(Exception refused){out.put("saved_trust_valid_now",false);}
            }
        }
        try(var file=context.openFileOutput("discovery-authority-preflight.json",0)){file.write(out.toString(2).getBytes(StandardCharsets.UTF_8));}
    }
}
