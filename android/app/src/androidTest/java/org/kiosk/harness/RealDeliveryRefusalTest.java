package org.kiosk.harness;

import java.nio.file.*;
import java.nio.charset.StandardCharsets;
import java.util.*;
import java.io.*;
import org.json.JSONObject;
import org.kiosk.harness.delivery.*;
import org.kiosk.harness.storage.*;

/** One bounded continuation of the retained real A in the ordinary default store. No fake issuer. */
public final class RealDeliveryRefusalTest extends GenericPlaybackTest {
    private Map<String,String> hashes(Path root)throws Exception{Map<String,String> out=new TreeMap<>();try(var files=Files.walk(root)){for(Path p:files.filter(Files::isRegularFile).toList())out.put(root.relativize(p).toString(),org.kiosk.harness.core.LocalView.digest(Files.readAllBytes(p)));}return out;}
    public void testRealARefusalsAndIdempotentActualReady()throws Exception{
        external=true;var adapters=new org.kiosk.harness.delivery.PhoneDeliveryAdapters(getInstrumentation().getTargetContext());var client=adapters.client();
        HarnessTestRunner.nextAdmissionVerifier.set(()->client);launch(null,FixturePublicationStore.NONE,PreparedWebView.PLATFORM);
        assertEquals("ready",activity.state);assertEquals("native-device-delivery-v1",activity.store.admissionIssuer(activity.visible));
        String a=activity.visible;var bytes=hashes(activity.store.root.resolve("revisions").resolve(a));var view=activity.active;String association=adapters.associationDigest();
        for(String fault:List.of("partial","tampered","unauthorized","stale","unsupported","malformed")){
            adapters.fault=fault;try{var d=client.download();if(d!=null)d.capture().close();fail("candidate accepted: "+fault);}catch(Exception refused){}
            assertEquals(a,activity.visible);assertEquals(a,activity.store.pointer());assertSame(view,activity.active);assertEquals(bytes,hashes(activity.store.root.resolve("revisions").resolve(a)));assertEquals(association,adapters.associationDigest());
            state("real-A-preserved-"+fault);
        }
        adapters.fault="";var candidate=client.download();var r=candidate.request();var wrong=new PreparedAdmission.Request(r.pkg(),r.renderer(),r.kiosk(),r.tv(),"0".repeat(64),r.windowsImages(),r.images(),r.storage());
        ui(()->assertTrue(activity.installPrepared(candidate.capture(),wrong)));until(()->!activity.busy,24000,"independent source refusal");
        assertEquals("ready_previous_retained",activity.state);assertSame(view,activity.active);assertEquals(a,activity.store.pointer());assertEquals(bytes,hashes(activity.store.root.resolve("revisions").resolve(a)));state("real-source-binding-refused");
        mode("kiosk");assertEquals("ready",activity.state);tap("home-button");assertEquals("false",eval("document.getElementById('home').hidden"));tap("open-events");
        mode("tv");assertEquals("ready",activity.state);mode("kiosk");assertEquals("ready",activity.state);
        JSONObject diagnostic=null;long end=android.os.SystemClock.elapsedRealtime()+5000;
        while(android.os.SystemClock.elapsedRealtime()<end){try{var j=new JSONObject(new String(Files.readAllBytes(activity.store.root.resolve("display-state.json")),StandardCharsets.UTF_8));if(j.getInt("pid")==android.os.Process.myPid()&&"ready".equals(j.getString("state"))&&"kiosk".equals(j.getString("visible_mode"))){diagnostic=j;break;}}catch(Exception pending){}Thread.sleep(25);}
        assertNotNull(diagnostic);client.queueReady(a,"kiosk",diagnostic.getString("session"));
        adapters.fault="lost-receipt";try{client.flush();fail("lost response ignored");}catch(IOException expected){}
        assertTrue(adapters.queued()>0);assertTrue(adapters.client().flush()>0);assertEquals(0,adapters.queued());
        int size=adapters.receiptHashes.size();assertTrue(size>=2);assertEquals(adapters.receiptHashes.get(size-2),adapters.receiptHashes.get(size-1));
        adapters.enrollmentLostReplyRecovery();
        assertEquals(bytes,hashes(activity.store.root.resolve("revisions").resolve(a)));assertEquals(a,activity.visible);assertFalse(activity.store.developmentAuthorized(a));
        screen("real-A-after-refusals");state("real-A-final");
        JSONObject result=new JSONObject().put("preserved_A",a).put("refusals",7).put("same_store",true).put("real_issuer",true).put("lost_token_recovered_same_credential",true)
            .put("lost_receipt_retried_same_body",true).put("http_statuses",new JSONObject(adapters.statuses)).put("receipt_body_hashes",new org.json.JSONArray(adapters.receiptHashes));
        try(var out=getInstrumentation().getTargetContext().openFileOutput("real-delivery-refusals.json",0)){out.write(result.toString().getBytes(StandardCharsets.UTF_8));}
    }
}
