package org.kiosk.harness;

import android.content.Intent;
import android.os.SystemClock;
import android.test.InstrumentationTestCase;
import java.io.*;
import java.nio.charset.StandardCharsets;
import java.nio.file.*;
import java.util.*;
import java.util.function.BooleanSupplier;
import org.json.*;
import org.kiosk.harness.delivery.*;
import org.kiosk.harness.storage.*;

/** Explicit methods only; one accepted B ->one interrupted new candidate. No inherited fixture journeys. */
@SuppressWarnings("deprecation")
public final class ResumePhoneTest extends InstrumentationTestCase {
    private static final String B="ea2822f219ac60888e6aa7b32404299f7e1cc396a5b463f5ebdd8877b64e2e00";
    private android.content.Context context(){return getInstrumentation().getTargetContext();}
    private JSONObject read(String name)throws Exception{return new JSONObject(new String(Files.readAllBytes(context().getFilesDir().toPath().resolve(name)),StandardCharsets.UTF_8));}
    private void write(String name,JSONObject value)throws Exception{try(var out=context().openFileOutput(name,0)){out.write(value.toString().getBytes(StandardCharsets.UTF_8));}}
    private FixturePublicationStore store(DeliveryClient c)throws Exception{return new FixturePublicationStore(context().getFilesDir().getCanonicalFile().toPath().resolve("fixture-publications"),FixturePublicationStore.NONE,()->c);}
    private void until(BooleanSupplier condition,long millis)throws Exception{long end=SystemClock.elapsedRealtime()+millis;while(!condition.getAsBoolean()&&SystemClock.elapsedRealtime()<end)Thread.sleep(50);assertTrue(condition.getAsBoolean());}
    public void testExistingBRegistrationAndAuthority()throws Exception{
        var driver=new org.kiosk.harness.delivery.ResumePhoneDriver(context());var c=driver.client();assertTrue(c.enrolled());assertEquals(B,store(c).pointer());
        try{assertNull(c.download(B));write("resume-preflight.json",new JSONObject().put("current_B",B).put("continuity",driver.continuity()).put("http_statuses",new JSONObject(driver.statuses)));}
        catch(Exception failure){write("resume-preflight-error.json",new JSONObject().put("http_statuses",new JSONObject(driver.statuses)).put("type",failure.getClass().getSimpleName()));throw failure;}
    }
    public void testInterruptOneNewCandidateWhileBRemainsVisible()throws Exception{
        var driver=new org.kiosk.harness.delivery.ResumePhoneDriver(context());driver.cancel=true;var c=driver.client();HarnessTestRunner.nextAdmissionVerifier.set(()->c);
        StoredHarnessActivity activity=(StoredHarnessActivity)getInstrumentation().startActivitySync(new Intent(context(),StoredHarnessActivity.class).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK|Intent.FLAG_ACTIVITY_MULTIPLE_TASK));
        try{
            until(()->!activity.busy,24000);assertEquals("ready",activity.state);assertEquals(B,activity.visible);assertEquals(B,activity.store.pointer());var visible=activity.active;
            write("resume-test-waiting.json",new JSONObject().put("ready_for_candidate",true).put("visible",B).put("pid",android.os.Process.myPid()));
            long end=SystemClock.elapsedRealtime()+120000;boolean cancelled=false;
            while(SystemClock.elapsedRealtime()<end){
                try{var d=c.download(B);if(d!=null){d.capture().close();fail("test fixture must exceed interruption threshold");}}
                catch(IOException expected){if(!driver.interrupted)throw expected;cancelled=true;break;}
                Thread.sleep(1000);
            }
            assertTrue("controlled interruption occurred",cancelled);assertEquals(B,activity.visible);assertSame(visible,activity.active);assertEquals("ready",activity.state);assertEquals(B,activity.store.pointer());assertEquals(B,activity.store.receipt("tv"));
            Path stage=context().getNoBackupFilesDir().getCanonicalFile().toPath().resolve("captured-candidates/incomplete");JSONObject journal=new JSONObject(new String(Files.readAllBytes(stage.resolve("transfer.json")),StandardCharsets.UTF_8));JSONObject active=journal.getJSONObject("active");
            Path file=stage.resolve(active.getString("part")).resolve(active.getString("path")).normalize();assertTrue(file.startsWith(stage));long prefix=Files.size(file);assertEquals(driver.deliveredPrefix,prefix);assertTrue(prefix>0&&prefix<active.getLong("size"));
            JSONObject stats=new JSONObject(c.transferDiagnostics());assertTrue(stats.getLong("reused_accepted_bytes")>0);
            write("resume-interrupted.json",new JSONObject().put("visible",activity.visible).put("pointer",activity.store.pointer()).put("ready_tv",activity.store.receipt("tv")).put("prefix_length",prefix).put("file_size",active.getLong("size")).put("file_sha256",active.getString("sha256")).put("request_until_cancel_ms",driver.interruptionMillis).put("stats",stats).put("http_statuses",new JSONObject(driver.statuses)).put("continuity",driver.continuity()).put("candidate_ready",false));
            var bitmap=getInstrumentation().getUiAutomation().takeScreenshot();try(var out=context().openFileOutput("resume-B-incomplete.png",0)){bitmap.compress(android.graphics.Bitmap.CompressFormat.PNG,100,out);}finally{bitmap.recycle();}
        }finally{getInstrumentation().runOnMainSync(activity::finish);}
    }
    public void testCompletedResumptionAndActualReadyReceipt()throws Exception{
        var driver=new org.kiosk.harness.delivery.ResumePhoneDriver(context());var c=driver.client();var store=store(c);String current=store.pointer();assertFalse(B.equals(current));
        JSONObject diagnostic=read("fixture-publications/display-state.json"),stats=read("transfer-state.json"),receipt=read("receipt-delivery.json"),interrupted=read("resume-interrupted.json");
        assertEquals("ready",diagnostic.getString("state"));assertEquals(current,diagnostic.getString("visible"));assertEquals(current,store.receipt("tv"));assertEquals("native-device-delivery-v1",store.admissionIssuer(current));assertEquals(0,diagnostic.getInt("asset_reads"));
        assertTrue(stats.getLong("resumed_offset")>0);assertTrue(stats.getLong("reused_accepted_bytes")>0);assertEquals(current,receipt.getString("package_id"));assertEquals("tv",receipt.getString("mode"));assertEquals(200,receipt.getInt("http_status"));assertEquals(0,driver.queued());
        JSONObject before=interrupted.getJSONObject("continuity"),after=driver.continuity();for(String k:List.of("device_hash","credential_hash","secret_hash","request_hash"))assertEquals(before.getString(k),after.getString(k));
        boolean ranged=false;JSONArray requests=stats.getJSONArray("requests");for(int i=0;i<requests.length();i++){JSONObject r=requests.getJSONObject(i);if(r.getInt("status")==206){assertEquals(interrupted.getLong("prefix_length"),r.getLong("offset"));assertEquals("bytes="+r.getLong("offset")+"-",r.getString("range"));ranged=true;}}
        assertTrue("actual206 captured",ranged);assertFalse(Files.exists(context().getNoBackupFilesDir().toPath().resolve("captured-candidates/incomplete")));
        write("resume-complete.json",new JSONObject().put("current",current).put("visible",diagnostic.getString("visible")).put("ready",store.receipt("tv")).put("source_issuer",store.admissionIssuer(current)).put("stats",stats).put("actual_ready_receipt",receipt).put("same_registration",true).put("outbox",0));
    }
}
