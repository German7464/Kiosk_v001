package org.kiosk.harness;
import android.content.Intent;
import android.os.*;
import android.test.InstrumentationTestCase;
import android.view.MotionEvent;
import android.webkit.*;
import java.nio.file.*;
import java.io.*;
import java.util.*;
import java.util.concurrent.*;
import java.util.concurrent.atomic.*;
import java.util.function.BooleanSupplier;
import org.kiosk.harness.binding.*;
import org.kiosk.harness.storage.*;

@SuppressWarnings("deprecation")
public class GenericPlaybackTest extends InstrumentationTestCase {
    StoredHarnessActivity activity;Path root;boolean external;
    void ui(Runnable r){getInstrumentation().runOnMainSync(r);}
    void until(BooleanSupplier c,long ms,String label)throws Exception{long end=SystemClock.elapsedRealtime()+ms;while(!c.getAsBoolean()&&SystemClock.elapsedRealtime()<end)Thread.sleep(25);assertTrue(label,c.getAsBoolean());}
    void launch(Path path,FixturePublicationStore.Checkpoint faults,PreparedWebView.Factory factory)throws Exception{
        HarnessTestRunner.nextStoreAdapters.set(new HarnessTestRunner.StoreAdapters(faults,factory,path));
        activity=(StoredHarnessActivity)getInstrumentation().startActivitySync(new Intent(getInstrumentation().getTargetContext(),StoredHarnessActivity.class).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK|Intent.FLAG_ACTIVITY_MULTIPLE_TASK));
        until(()->!activity.busy,24000,"startup");
    }
    void setupRoot()throws Exception{root=getInstrumentation().getTargetContext().getFilesDir().getCanonicalFile().toPath().resolve("generic-playback-test-"+UUID.randomUUID());Files.createDirectory(root);launch(root,FixturePublicationStore.NONE,PreparedWebView.PLATFORM);}
    PlaybackInputs.Owned inputs(String name)throws Exception{return GenericInputs.capture(getInstrumentation().getTargetContext(),getInstrumentation().getContext(),name);}
    String install(String name)throws Exception{
        var in=inputs(name);int reads=in.providerReads().get();AtomicBoolean accepted=new AtomicBoolean();
        ui(()->accepted.set(activity.installDevelopment(in.capture(),in.permit(),GenericInputs.BUDGET)));
        if(!accepted.get()){in.capture().close();fail("native owner transfer refused");}
        until(()->!activity.busy,24000,"development install");assertEquals(reads,in.providerReads().get());
        try{in.capture().report();fail("original capture must be closed");}catch(CaptureFailure closed){assertEquals(CaptureFailure.Code.CLOSED,closed.code);}
        try(var out=getInstrumentation().getTargetContext().openFileOutput("generic-capture-ownership.jsonl",android.content.Context.MODE_APPEND)){
            out.write((new org.json.JSONObject().put("identity",in.identity()).put("provider_reads_at_capture",reads).put("provider_reads_after_persistence",in.providerReads().get()).put("original_capture_closed",true).toString()+"\n").getBytes(java.nio.charset.StandardCharsets.UTF_8));
        }
        return in.identity();
    }
    String eval(String js)throws Exception{
        CountDownLatch done=new CountDownLatch(1);AtomicReference<String> result=new AtomicReference<>();ui(()->activity.active.browser.evaluateJavascript(js,s->{result.set(s);done.countDown();}));assertTrue(done.await(5,TimeUnit.SECONDS));return result.get();
    }
    void mode(String mode)throws Exception{ui(()->activity.chooseMode(mode));until(()->!activity.busy,24000,"mode");}
    void tap(String id)throws Exception{
        String bounds=eval("JSON.stringify((()=>{let r=document.getElementById('"+id+"').getBoundingClientRect();return [r.x+r.width/2,r.y+r.height/2]})())");
        var arr=new org.json.JSONArray(new org.json.JSONArray("["+bounds+"]").getString(0));
        ui(()->{float density=activity.getResources().getDisplayMetrics().density,x=(float)arr.optDouble(0)*density,y=(float)arr.optDouble(1)*density;long t=SystemClock.uptimeMillis();MotionEvent down=MotionEvent.obtain(t,t,MotionEvent.ACTION_DOWN,x,y,0),up=MotionEvent.obtain(t,t+30,MotionEvent.ACTION_UP,x,y,0);try{activity.active.browser.dispatchTouchEvent(down);activity.active.browser.dispatchTouchEvent(up);}finally{down.recycle();up.recycle();}});Thread.sleep(200);
    }
    void screen(String name)throws Exception{
        var bitmap=getInstrumentation().getUiAutomation().takeScreenshot();assertNotNull(bitmap);
        try(var out=getInstrumentation().getTargetContext().openFileOutput("generic-"+name+".png",0)){assertTrue(bitmap.compress(android.graphics.Bitmap.CompressFormat.PNG,100,out));}finally{bitmap.recycle();}
    }
    void state(String label)throws Exception{
        var j=new org.json.JSONObject().put("label",label).put("elapsed_ms",SystemClock.elapsedRealtime()).put("pid",android.os.Process.myPid()).put("state",activity.state).put("pointer",activity.store.pointer()).put("selected",activity.store.selectedMode()).put("visible",activity.visible).put("mode",activity.visibleMode).put("receipt_kiosk",activity.store.receipt("kiosk")).put("receipt_tv",activity.store.receipt("tv")).put("title",activity.active==null?"none":eval("document.querySelector('.event-title').textContent")).put("counter",activity.active==null?"none":eval("document.getElementById('counter').textContent"));
        try(var out=getInstrumentation().getTargetContext().openFileOutput("generic-observations.jsonl",android.content.Context.MODE_APPEND)){out.write((j+"\n").getBytes(java.nio.charset.StandardCharsets.UTF_8));}android.util.Log.i("GenericPlayback",j.toString());
    }
    void rotation()throws Exception{
        String first=eval("document.querySelector('.event-title').textContent"),next=first;state("rotation-before");long end=SystemClock.elapsedRealtime()+18000;
        while(next.equals(first)&&SystemClock.elapsedRealtime()<end){Thread.sleep(300);next=eval("document.querySelector('.event-title').textContent");}
        assertFalse("automatic unaccelerated transition",first.equals(next));assertEquals("true",eval("Array.from(document.images).every(i=>i.complete&&i.naturalWidth>0)"));state("rotation-after");
    }
    void closeActivity(){if(activity!=null){ui(activity::finish);activity=null;getInstrumentation().waitForIdleSync();}}
    @Override protected void tearDown()throws Exception{closeActivity();if(!external&&root!=null&&Files.exists(root)){Thread.sleep(150);try(var walk=Files.walk(root)){for(Path p:walk.sorted(Comparator.reverseOrder()).toList())Files.delete(p);}}super.tearDown();}
    public void testGenericJourneyRealReady()throws Exception{
        setupRoot();mode("kiosk");String c=install("C");assertEquals("ready",activity.state);assertEquals(c,activity.store.receipt("kiosk"));tap("home-button");assertEquals("false",eval("document.getElementById('home').hidden"));tap("open-events");tap("next");assertEquals("\"2 / 2\"",eval("document.getElementById('counter').textContent"));screen("C-kiosk-two");state("C-kiosk-ready");
        mode("tv");assertEquals("ready",activity.state);assertEquals(c,activity.store.receipt("tv"));rotation();screen("C-tv-auto");
        String b=install("B");assertEquals(b,activity.visible);assertEquals(b,activity.store.receipt("tv"));state("B-tv-ready");mode("kiosk");tap("next");screen("B-kiosk-two");assertEquals(b,activity.store.receipt("kiosk"));state("B-kiosk-ready");
    }
    public void testPointerCommitThenRendererRefusalAndExplicitRecovery()throws Exception{
        setupRoot();String c=install("C");closeActivity();
        launch(root,FixturePublicationStore.NONE,PreparedWebView.PLATFORM);
        Path missing=root.resolve("revisions").resolve(c).resolve("view-kiosk/index.html");Files.write(missing,new byte[]{1});mode("kiosk");assertEquals("ready_previous_retained",activity.state);assertEquals(c,activity.visible);assertEquals("tv",activity.visibleMode);assertEquals("tv",activity.store.selectedMode());
    }
    public void testRealGenericRendererFailureAndFreshStartup()throws Exception{
        setupRoot();String c=install("C");AtomicBoolean terminated=new AtomicBoolean();ui(()->{var renderer=activity.active.browser.getWebViewRenderProcess();assertNotNull(renderer);terminated.set(renderer.terminate());});assertTrue(terminated.get());until(()->activity.active==null&&!activity.busy,10000,"real renderer gone");assertEquals("failed",activity.state);assertEquals(c,activity.store.pointer());assertEquals(c,activity.store.receipt());Thread.sleep(800);assertNull(activity.active);state("renderer-failed-pointer-retained");closeActivity();launch(root,FixturePublicationStore.NONE,PreparedWebView.PLATFORM);assertEquals("ready",activity.state);assertEquals(c,activity.visible);
    }
    public void testLateGenericCommitAfterCloseDoesNotAttach()throws Exception{
        setupRoot();String c=install("C");var entered=new CountDownLatch(1);var release=new CountDownLatch(1);closeActivity();
        launch(root,p->{if(p.equals("preflight_complete")){entered.countDown();try{release.await(3,TimeUnit.SECONDS);}catch(InterruptedException stop){Thread.currentThread().interrupt();throw new IOException("cancelled");}}},PreparedWebView.PLATFORM);
        var input=GenericInputs.capture(getInstrumentation().getTargetContext(),getInstrumentation().getContext(),"B");ui(()->assertTrue(activity.installDevelopment(input.capture(),input.permit(),GenericInputs.BUDGET)));assertTrue(entered.await(10,TimeUnit.SECONDS));closeActivity();release.countDown();Thread.sleep(300);launch(root,FixturePublicationStore.NONE,PreparedWebView.PLATFORM);assertEquals("ready",activity.state);assertEquals(c,activity.visible);assertEquals(c,activity.store.receipt());
    }
}
