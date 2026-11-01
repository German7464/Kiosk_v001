package org.kiosk.harness;

import android.content.Intent;
import android.os.SystemClock;
import android.test.InstrumentationTestCase;
import android.webkit.*;
import java.io.*;
import java.nio.file.*;
import java.util.*;
import java.util.concurrent.*;
import java.util.concurrent.atomic.*;
import java.util.function.BooleanSupplier;
import org.kiosk.harness.storage.*;

@SuppressWarnings("deprecation")
public class StoredCoordinatorTest extends InstrumentationTestCase {
    private final List<Path> roots=new ArrayList<>();
    private StoredHarnessActivity activity;
    private static void writeText(Path path,String text) throws IOException {Files.write(path,text.getBytes(java.nio.charset.StandardCharsets.UTF_8));}
    private static final String A=PublicationFixtures.A.identity(),B=PublicationFixtures.B.identity();
    private void ui(Runnable work) throws Exception {
        CountDownLatch done=new CountDownLatch(1);AtomicReference<Throwable> failure=new AtomicReference<>();
        new android.os.Handler(android.os.Looper.getMainLooper()).post(()->{try{work.run();}catch(Throwable e){failure.set(e);}finally{done.countDown();}});
        assertTrue("bounded UI",done.await(10,TimeUnit.SECONDS));if(failure.get()!=null)throw new AssertionError(failure.get());
    }
    private void until(BooleanSupplier condition,long ms,String label) throws Exception {long end=SystemClock.elapsedRealtime()+ms;while(!condition.getAsBoolean()&&SystemClock.elapsedRealtime()<end)Thread.sleep(25);assertTrue(label,condition.getAsBoolean());}
    private Path root() throws Exception {Path path=getInstrumentation().getTargetContext().getFilesDir().getCanonicalFile().toPath().resolve("coordinator-test-"+UUID.randomUUID());Files.createDirectory(path);roots.add(path);return path;}
    private void launch(Path root,FixturePublicationStore.Checkpoint faults,PreparedWebView.Factory factory) throws Exception {
        HarnessTestRunner.nextStoreAdapters.set(new HarnessTestRunner.StoreAdapters(faults,factory,root));
        activity=(StoredHarnessActivity)getInstrumentation().startActivitySync(new Intent(getInstrumentation().getTargetContext(),StoredHarnessActivity.class).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK|Intent.FLAG_ACTIVITY_MULTIPLE_TASK));
        until(()->!activity.busy,23000,"startup bounded");
    }
    private void install(String key,String expected) throws Exception {
        ui(()->activity.install(key));until(()->!activity.busy,23000,"install bounded");assertEquals(expected,activity.visible);
    }
    private String eval(String js) throws Exception {
        CountDownLatch done=new CountDownLatch(1);AtomicReference<String> value=new AtomicReference<>();
        ui(()->activity.active.browser.evaluateJavascript(js,s->{value.set(s);done.countDown();}));assertTrue(done.await(5,TimeUnit.SECONDS));return value.get();
    }
    private void close() throws Exception {if(activity!=null){ui(activity::finish);activity=null;getInstrumentation().waitForIdleSync();}}
    private void event(String label) {
        android.util.Log.i("StoredCoordinatorTest",label+" state="+activity.state+" pointer="+activity.store.pointer()+" selected="+activity.store.modeOrInvalid()+" visible="+activity.visible+" visibleMode="+activity.visibleMode+" receiptTV="+activity.store.receipt("tv")+" receiptKiosk="+activity.store.receipt("kiosk"));
    }
    private void mode(String mode) throws Exception {ui(()->activity.chooseMode(mode));until(()->!activity.busy,23000,"mode change bounded");}
    private org.json.JSONObject diagnostic(Path root,String mode) throws Exception {
        long end=SystemClock.elapsedRealtime()+5000;org.json.JSONObject last=null;
        while(SystemClock.elapsedRealtime()<end){
            try{last=new org.json.JSONObject(new String(Files.readAllBytes(root.resolve("display-state.json")),java.nio.charset.StandardCharsets.UTF_8));if(mode.equals(last.optString("visible_mode"))&&mode.equals(last.optString("selected_mode"))&&activity.visible.equals(last.optString("visible"))&&"ready".equals(last.optString("state")))return last;}catch(Exception e){}
            Thread.sleep(25);
        }
        throw new AssertionError("diagnostic not current "+last);
    }
    private void tapDom(String id) throws Exception {
        long end=SystemClock.elapsedRealtime()+5000;while(!activity.hasWindowFocus()&&SystemClock.elapsedRealtime()<end)Thread.sleep(25);assertTrue(activity.hasWindowFocus());
        org.json.JSONObject rect=new org.json.JSONObject(eval("(()=>{let r=document.getElementById('"+id+"').getBoundingClientRect();return {x:r.x+r.width/2,y:r.y+r.height/2,dpr:devicePixelRatio,width:r.width,height:r.height}})()"));
        assertTrue(rect.getDouble("width")>0&&rect.getDouble("height")>0);int[] origin=new int[2];ui(()->activity.active.browser.getLocationOnScreen(origin));
        float x=(float)(origin[0]+rect.getDouble("x")*rect.getDouble("dpr")),y=(float)(origin[1]+rect.getDouble("y")*rect.getDouble("dpr"));long now=SystemClock.uptimeMillis();
        android.view.MotionEvent down=android.view.MotionEvent.obtain(now,now,android.view.MotionEvent.ACTION_DOWN,x,y,0),up=android.view.MotionEvent.obtain(now,now+40,android.view.MotionEvent.ACTION_UP,x,y,0);
        try{down.setSource(android.view.InputDevice.SOURCE_TOUCHSCREEN);up.setSource(android.view.InputDevice.SOURCE_TOUCHSCREEN);getInstrumentation().sendPointerSync(down);getInstrumentation().sendPointerSync(up);}finally{down.recycle();up.recycle();}
        Thread.sleep(100);
    }
    private void screen(String label) throws Exception {
        android.graphics.Bitmap bitmap=getInstrumentation().getUiAutomation(android.app.UiAutomation.FLAG_DONT_SUPPRESS_ACCESSIBILITY_SERVICES).takeScreenshot();assertNotNull(bitmap);
        try(FileOutputStream out=getInstrumentation().getTargetContext().openFileOutput(label+".png",0)){assertTrue(bitmap.compress(android.graphics.Bitmap.CompressFormat.PNG,100,out));}finally{bitmap.recycle();}
    }
    public void testModesKioskNavigationTVRotationAndBackWithoutImport() throws Exception {
        Path root=root();launch(root,FixturePublicationStore.NONE,PreparedWebView.PLATFORM);mode("kiosk");assertEquals("kiosk",activity.store.selectedMode());assertNull(activity.visible);
        install("A",A);assertEquals("kiosk",activity.visibleMode);tapDom("home-button");assertEquals("false",eval("document.getElementById('home').hidden"));screen("mode-A-kiosk-home");tapDom("open-events");assertEquals("true",eval("document.getElementById('home').hidden"));
        install("B",B);assertEquals("\"SYNTHETIC TV CARD ONE\"",eval("document.querySelector('.event-title').textContent"));screen("mode-B-kiosk-one");tapDom("next");assertEquals("\"SYNTHETIC TV CARD TWO\"",eval("document.querySelector('.event-title').textContent"));screen("mode-B-kiosk-two");tapDom("previous");
        var before=diagnostic(root,"kiosk");mode("tv");assertEquals("tv",activity.visibleMode);assertEquals("true",eval("document.getElementById('home-button').hidden||getComputedStyle(document.getElementById('home-button')).display==='none'"));
        String first=eval("document.querySelector('.event-title').textContent"),next=first;long start=SystemClock.elapsedRealtime(),end=start+17000;
        while(next.equals(first)&&SystemClock.elapsedRealtime()<end){Thread.sleep(400);next=eval("document.querySelector('.event-title').textContent");}
        assertFalse("real automatic transition",next.equals(first));android.util.Log.i("StoredModeTest","auto_transition elapsed_ms="+(SystemClock.elapsedRealtime()-start)+" from="+first+" to="+next);screen("mode-B-tv-automatic");
        mode("kiosk");assertEquals("kiosk",activity.visibleMode);var after=diagnostic(root,"kiosk");assertEquals(before.getInt("asset_reads"),after.getInt("asset_reads"));assertEquals(before.getInt("package_asset_reads"),after.getInt("package_asset_reads"));assertEquals(B,activity.store.receipt("kiosk"));assertEquals(B,activity.store.receipt("tv"));event("both_modes_ready_no_reimport");
    }
    public void testModesMissingOrDamagedOtherViewRetainsCurrent() throws Exception {
        for(String defect:List.of("missing","hash")){
            Path root=root();launch(root,FixturePublicationStore.NONE,PreparedWebView.PLATFORM);install("A",A);var before=diagnostic(root,"tv");byte[] tv=Files.readAllBytes(root.resolve("last-ready-tv.json"));Path file=root.resolve("kiosk-views").resolve(A).resolve("view/index.html");
            if(defect.equals("missing"))Files.delete(file);else writeText(file,"bad");mode("kiosk");assertEquals("ready_previous_retained",activity.state);assertEquals("tv",activity.visibleMode);assertEquals("tv",activity.store.selectedMode());assertTrue(Arrays.equals(tv,Files.readAllBytes(root.resolve("last-ready-tv.json"))));assertEquals("invalid_or_absent",activity.store.receipt("kiosk"));assertEquals("true",eval(PreparedWebView.DOM_PROBE));event(defect+"_other_mode_keeps_current_and_receipt");close();
        }
    }
    public void testModesModeWriteAndEngineFailureDoNotHideOldView() throws Exception {
        Path root=root();AtomicBoolean writeFail=new AtomicBoolean(),engineFail=new AtomicBoolean();PreparedWebView.Factory factory=new PreparedWebView.Factory(){public WebView create(android.app.Activity a){return new WebView(a);}public void configured(WebView v){if(engineFail.get())throw new IllegalStateException("mode_engine_fault");}};
        launch(root,p->{if(writeFail.get()&&p.equals("mode.before_rename"))throw new IOException("mode_fault");},factory);install("A",A);writeFail.set(true);mode("kiosk");assertEquals("tv",activity.store.selectedMode());assertEquals("tv",activity.visibleMode);
        writeFail.set(false);engineFail.set(true);mode("kiosk");assertEquals("kiosk",activity.store.selectedMode());assertEquals("tv",activity.visibleMode);assertEquals(A,activity.store.receipt("tv"));assertEquals("invalid_or_absent",activity.store.receipt("kiosk"));event("selected_kiosk_visible_TV_after_engine_failure");close();launch(root,FixturePublicationStore.NONE,PreparedWebView.PLATFORM);assertEquals("kiosk",activity.visibleMode);assertEquals(A,activity.store.receipt("kiosk"));
    }
    public void testModesReceiptFailureAndExplicitRestart() throws Exception {
        Path root=root();AtomicBoolean fail=new AtomicBoolean();launch(root,p->{if(fail.get()&&p.equals("receipt.before_rename"))throw new IOException("receipt_fault");},PreparedWebView.PLATFORM);install("A",A);fail.set(true);mode("kiosk");assertEquals("ready_receipt_pending",activity.state);assertEquals("kiosk",activity.visibleMode);assertEquals("kiosk",activity.store.selectedMode());assertEquals(A,activity.store.receipt("tv"));assertEquals("invalid_or_absent",activity.store.receipt("kiosk"));event("kiosk_visible_receipt_pending_TV_unchanged");close();launch(root,FixturePublicationStore.NONE,PreparedWebView.PLATFORM);assertEquals("kiosk",activity.visibleMode);assertEquals(A,activity.store.receipt("kiosk"));
    }
    public void testModesLateDOMAfterRecreationCannotWriteOtherReceipt() throws Exception {
        Path root=root();AtomicBoolean hold=new AtomicBoolean();AtomicReference<HeldDom> held=new AtomicReference<>();PreparedWebView.Factory factory=a->{HeldDom v=new HeldDom(a,hold.get());if(hold.get())held.set(v);return v;};
        launch(root,FixturePublicationStore.NONE,factory);install("A",A);hold.set(true);ui(()->activity.chooseMode("kiosk"));until(()->held.get()!=null&&held.get().dom!=null,12000,"held new mode DOM");assertEquals("kiosk",activity.store.selectedMode());assertEquals("tv",activity.visibleMode);close();ui(()->held.get().dom.onReceiveValue("true"));assertEquals("invalid_or_absent",new FixturePublicationStore(root).receipt("kiosk"));
        launch(root,FixturePublicationStore.NONE,PreparedWebView.PLATFORM);assertEquals("kiosk",activity.visibleMode);assertEquals(A,activity.store.receipt("kiosk"));assertEquals(A,activity.store.receipt("tv"));event("late_other_mode_callback_rejected");
    }
    public void testModesInvalidSelectedMetadataSafeUntilExplicitChoice() throws Exception {
        Path root=root();launch(root,FixturePublicationStore.NONE,PreparedWebView.PLATFORM);install("A",A);close();writeText(root.resolve("selected-mode.json"),"invalid");launch(root,FixturePublicationStore.NONE,PreparedWebView.PLATFORM);assertEquals("failed",activity.state);assertNull(activity.visible);assertEquals("invalid",activity.selectedMode);mode("tv");assertEquals("ready",activity.state);assertEquals("tv",activity.visibleMode);event("invalid_selection_no_guessed_mode");
    }
    public void testAtoBRealReadyAndPrivateRestart() throws Exception {
        Path root=root();launch(root,FixturePublicationStore.NONE,PreparedWebView.PLATFORM);assertEquals("failed",activity.state);install("A",A);assertEquals("ready",activity.state);
        assertEquals("true",eval("Array.from(document.images).every(i=>i.complete&&i.naturalWidth>0)"));install("B",B);assertEquals(B,activity.store.pointer());assertEquals(B,activity.store.receipt());event("A_B_ready");
        close();launch(root,FixturePublicationStore.NONE,PreparedWebView.PLATFORM);assertEquals("ready",activity.state);assertEquals(B,activity.visible);assertEquals("true",eval(PreparedWebView.DOM_PROBE));event("private_restart_ready");
    }
    public void testCandidateFailureRetainsAWithoutPointerRollback() throws Exception {
        Path root=root();AtomicBoolean fail=new AtomicBoolean();PreparedWebView.Factory factory=new PreparedWebView.Factory(){public WebView create(android.app.Activity a){return new WebView(a);}public void configured(WebView v){if(fail.get())throw new IllegalStateException("test_configure");}};
        launch(root,FixturePublicationStore.NONE,factory);install("A",A);fail.set(true);install("B",A);assertEquals("ready_previous_retained",activity.state);assertEquals(B,activity.store.pointer());assertEquals(A,activity.store.receipt());assertEquals("true",eval(PreparedWebView.DOM_PROBE));event("candidate_failed_pointer_B_visible_A_receipt_A");
    }
    public void testReceiptFailureKeepsActualNewViewAndPendingReceipt() throws Exception {
        Path root=root();AtomicBoolean fault=new AtomicBoolean();launch(root,p->{if(fault.get()&&p.equals("receipt.before_rename"))throw new IOException("receipt_fault");},PreparedWebView.PLATFORM);
        install("A",A);fault.set(true);install("B",B);assertEquals("ready_receipt_pending",activity.state);assertEquals(B,activity.store.pointer());assertEquals(A,activity.store.receipt());assertEquals("true",eval(PreparedWebView.DOM_PROBE));event("receipt_pending_B_still_visible");
        close();launch(root,FixturePublicationStore.NONE,PreparedWebView.PLATFORM);assertEquals(B,activity.visible);assertEquals(B,activity.store.receipt());event("explicit_restart_confirms_B");
    }
    public void testCorruptMetadataAndViewBoundedFallbackOrSafeState() throws Exception {
        Path root=root();launch(root,FixturePublicationStore.NONE,PreparedWebView.PLATFORM);install("A",A);install("B",B);close();
        writeText(root.resolve("active.json"),"corrupt");writeText(root.resolve("active.backup.json"),"corrupt");launch(root,FixturePublicationStore.NONE,PreparedWebView.PLATFORM);assertEquals(B,activity.visible);event("receipt_only_fallback");close();
        writeText(root.resolve("last-ready-tv.json"),"corrupt");launch(root,FixturePublicationStore.NONE,PreparedWebView.PLATFORM);assertEquals("failed",activity.state);assertNull(activity.visible);assertNull(activity.active);event("no_directory_scan_safe_failed");
    }
    public void testStartupEngineFailureTriesOnlyConfirmedOtherView() throws Exception {
        Path root=root();launch(root,FixturePublicationStore.NONE,PreparedWebView.PLATFORM);install("A",A);close();
        var store=new FixturePublicationStore(root);var f=PublicationFixtures.B;store.install("B",new FixtureAssetSource(getInstrumentation().getTargetContext().getAssets(),f,false,new AtomicInteger()),new FixtureAssetSource(getInstrumentation().getTargetContext().getAssets(),f,true,new AtomicInteger()),FixturePublicationStore.NONE);
        AtomicInteger creates=new AtomicInteger();PreparedWebView.Factory factory=new PreparedWebView.Factory(){public WebView create(android.app.Activity a){if(creates.incrementAndGet()==1)throw new IllegalStateException("first_engine_failed");return new WebView(a);}};
        launch(root,FixturePublicationStore.NONE,factory);assertEquals(A,activity.visible);assertEquals(2,creates.get());assertEquals(B,activity.store.pointer());assertEquals(A,activity.store.receipt());event("one_confirmed_retry_only");
    }
    public void testActualRendererGoneAfterPublicationKeepsPointerAndLastReady() throws Exception {
        Path root=root();AtomicBoolean hold=new AtomicBoolean();AtomicReference<HeldDom> held=new AtomicReference<>();
        PreparedWebView.Factory factory=a->{HeldDom view=new HeldDom(a,hold.get());if(hold.get())held.set(view);return view;};
        launch(root,FixturePublicationStore.NONE,factory);install("A",A);hold.set(true);ui(()->activity.install("B"));
        until(()->held.get()!=null&&held.get().dom!=null,15000,"B held at actual DOM callback");assertEquals(B,activity.store.pointer());assertEquals(A,activity.visible);assertEquals(A,activity.store.receipt());
        PreparedWebView old=activity.active;AtomicBoolean initiated=new AtomicBoolean();
        ui(()->{assertNotNull(held.get().getWebViewRenderProcess());initiated.set(held.get().getWebViewRenderProcess().terminate());});assertTrue("actual terminate initiated",initiated.get());
        until(()->activity.state.equals("failed")&&activity.visible==null,10000,"actual renderer gone safe state");assertTrue(old.rendererGone.get()>0);assertEquals(B,activity.store.pointer());assertEquals(A,activity.store.receipt());
        ui(()->held.get().dom.onReceiveValue("true"));Thread.sleep(3000);assertEquals("failed",activity.state);assertNull(activity.active);assertNull(activity.candidate);event("real_gone_pointer_B_no_visible_receipt_A_no_restart");
        close();launch(root,FixturePublicationStore.NONE,PreparedWebView.PLATFORM);assertEquals(B,activity.visible);assertEquals(B,activity.store.receipt());event("explicit_restart_reverified_B");
    }
    public void testTwentySecondWatchdogDuringStagingAndRecreation() throws Exception {
        Path root=root();AtomicBoolean delay=new AtomicBoolean();CountDownLatch entered=new CountDownLatch(1),release=new CountDownLatch(1),returned=new CountDownLatch(1);
        FixturePublicationStore.Checkpoint hook=point->{
            if(delay.get()&&point.equals("stage_verified")){
                entered.countDown();boolean interrupted=false;
                try{long until=SystemClock.elapsedRealtime()+35000;while(release.getCount()>0&&SystemClock.elapsedRealtime()<until){try{release.await(100,TimeUnit.MILLISECONDS);}catch(InterruptedException e){interrupted=true;}}}
                finally{returned.countDown();if(interrupted)Thread.currentThread().interrupt();}
            }
        };
        try {
            launch(root,hook,PreparedWebView.PLATFORM);install("A",A);delay.set(true);long start=SystemClock.elapsedRealtime();ui(()->activity.install("B"));
            assertTrue(entered.await(10,TimeUnit.SECONDS));until(()->!activity.busy,23000,"actual20s coordinator watchdog");
            long elapsed=SystemClock.elapsedRealtime()-start;assertTrue("not premature",elapsed>=19500);assertEquals("ready_previous_retained",activity.state);assertEquals(A,activity.visible);assertEquals(A,activity.store.pointer());assertEquals(A,activity.store.receipt());
            assertEquals("true",eval(PreparedWebView.DOM_PROBE));event("watchdog_UI_responsive_A_retained");
            StoredHarnessActivity old=activity;close();release.countDown();assertTrue(returned.await(5,TimeUnit.SECONDS));
            long end=SystemClock.elapsedRealtime()+5000;while(true){try{new FixturePublicationStore(root).startupChoices();break;}catch(IOException e){if(SystemClock.elapsedRealtime()>end)throw e;Thread.sleep(25);}}
            launch(root,FixturePublicationStore.NONE,PreparedWebView.PLATFORM);assertEquals(A,activity.visible);assertNull(old.active);assertNull(old.candidate);assertTrue(Files.exists(root.resolve(".incoming")));event("late_stage_no_attach_after_recreation");
        }finally{release.countDown();}
    }
    private static final class HeldDom extends WebView {
        final boolean hold;volatile ValueCallback<String> dom;
        HeldDom(android.app.Activity activity,boolean hold){super(activity);this.hold=hold;}
        @Override public void evaluateJavascript(String script,ValueCallback<String> callback){if(hold)dom=callback;else super.evaluateJavascript(script,callback);}
    }
    @Override protected void tearDown() throws Exception {
        HarnessTestRunner.nextStoreAdapters.set(null);close();
        for(Path root:roots){
            long end=SystemClock.elapsedRealtime()+5000;
            while(true){try{new FixturePublicationStore(root).startupChoices();break;}catch(IOException e){if(SystemClock.elapsedRealtime()>end)throw e;Thread.sleep(25);}}
            assertTrue(root.getFileName().toString().startsWith("coordinator-test-"));try(var paths=Files.walk(root)){for(Path p:paths.sorted(Comparator.reverseOrder()).toList())Files.deleteIfExists(p);}
        }
        super.tearDown();
    }
}
