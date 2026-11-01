package org.kiosk.harness;

import android.app.Activity;
import android.content.Intent;
import android.os.Looper;
import android.os.SystemClock;
import android.test.InstrumentationTestCase;
import android.webkit.ValueCallback;
import android.webkit.WebView;
import android.webkit.WebViewRenderProcess;
import android.widget.TextView;
import android.view.ViewGroup;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.atomic.AtomicReference;
import java.util.concurrent.atomic.AtomicInteger;
import org.json.JSONObject;
import org.kiosk.harness.core.LocalView;

/** Observes unchanged renderer timers; real process termination, never a synthetic gone callback. */
@SuppressWarnings("deprecation")
public class RuntimeTest extends InstrumentationTestCase {
    private HarnessActivity activity;
    private void ui(Runnable work) throws Exception {
        CountDownLatch done = new CountDownLatch(1);
        AtomicReference<Throwable> failure = new AtomicReference<>();
        new android.os.Handler(Looper.getMainLooper()).post(() -> {
            try { work.run(); } catch (Throwable e) { failure.set(e); } finally { done.countDown(); }
        });
        assertTrue("UI bounded", done.await(10, TimeUnit.SECONDS));
        if (failure.get() != null) throw new AssertionError(failure.get());
    }
    private void launch() throws Exception {
        Intent intent = new Intent(getInstrumentation().getTargetContext(), HarnessActivity.class);
        intent.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK | Intent.FLAG_ACTIVITY_MULTIPLE_TASK);
        intent.putExtra("fixture", "two-card-tv");
        activity = (HarnessActivity)getInstrumentation().startActivitySync(intent);
        long end = SystemClock.elapsedRealtime() + 22000;
        while (activity.state.equals("loading") && SystemClock.elapsedRealtime() < end) Thread.sleep(25);
        assertEquals("ready", activity.state);
    }
    private String evaluate(String script) throws Exception {
        AtomicReference<String> result = new AtomicReference<>();
        CountDownLatch done = new CountDownLatch(1);
        ui(() -> activity.prepared.browser.evaluateJavascript(script, value -> { result.set(value); done.countDown(); }));
        assertTrue("DOM bounded", done.await(5, TimeUnit.SECONDS));
        return result.get();
    }
    private void close() throws Exception {
        if (activity != null) { ui(activity::finish); getInstrumentation().waitForIdleSync(); activity = null; }
    }
    @Override protected void tearDown() throws Exception {
        HarnessTestRunner.nextAdapters.set(null); close(); super.tearDown();
    }
    public void testThreeAutomaticTvTransitions() throws Exception {
        launch();
        // Read-only sampling: no model.move, clicks, keys, timer replacement or injected observers.
        String script = "JSON.stringify({counter:document.getElementById('counter').textContent,title:document.querySelector('.event-title').textContent,dom:(" + PreparedWebView.DOM_PROBE + "),controls:['home','previous','next','tags','home-button'].every(id=>{const n=document.getElementById(id);return n.hidden||getComputedStyle(n).display==='none'||n.getClientRects().length===0}),images:Array.from(document.images).every(i=>i.complete&&i.naturalWidth>0),bootstrap:JSON.parse(document.getElementById('bootstrap').textContent)})";
        long end = SystemClock.elapsedRealtime() + 85000;
        JSONObject previous = null;
        long previousAt = 0;
        int transitions = 0;
        while (SystemClock.elapsedRealtime() < end && transitions < 3) {
            long before = SystemClock.elapsedRealtime();
            JSONObject sample = new JSONObject((String)new org.json.JSONTokener(evaluate(script)).nextValue());
            long at = SystemClock.elapsedRealtime();
            assertEquals("ready", activity.state);
            assertTrue(sample.getBoolean("dom")); assertTrue(sample.getBoolean("controls"));
            // A render creates a fresh image: allow its local response to complete before asserting it.
            if (!sample.getBoolean("images")) { Thread.sleep(50); continue; }
            JSONObject bootstrap = sample.getJSONObject("bootstrap");
            assertEquals("tv", bootstrap.getString("mode"));
            assertEquals(2, bootstrap.getJSONObject("data").getInt("content_version"));
            if (previous == null || !previous.getString("counter").equals(sample.getString("counter"))) {
                int index = sample.getString("counter").startsWith("1") ? 0 : 1;
                JSONObject event = bootstrap.getJSONObject("data").getJSONArray("events").getJSONObject(index);
                assertEquals(event.getString("title"), sample.getString("title"));
                if (previous != null) {
                    assertFalse(previous.getString("title").equals(sample.getString("title")));
                    JSONObject old = bootstrap.getJSONObject("data").getJSONArray("events").getJSONObject(1-index);
                    String text = old.optString("title") + " " + old.optString("short_description") + " " + old.optString("place");
                    double seconds = bootstrap.getJSONObject("data").getJSONObject("settings").optDouble("tv_slide_duration",8);
                    double expected = Math.min(24000, Math.max(8000, seconds*1000 + text.length()*70));
                    long elapsed = at-previousAt;
                    android.util.Log.i("EventsRuntimeTest", "transition="+(transitions+1)+" intervalMs="+elapsed+" expectedMs="+expected);
                    // First interval starts after native readiness; later samples have <=250ms sampling error.
                    assertTrue("unmodified duration lower bound", elapsed >= expected - (transitions == 0 ? 2500 : 750));
                    assertTrue("bounded scheduling delay", elapsed <= expected+2500);
                    transitions++;
                }
                android.util.Log.i("EventsRuntimeTest", "sample monotonicBeforeMs="+before+" monotonicAfterMs="+at+" counter="+sample.getString("counter")+" title="+sample.getString("title")+" images=true controlsHidden=true package="+FixtureCatalog.identity("two-card-tv"));
                previous = sample; previousAt = at;
            }
            Thread.sleep(200);
        }
        assertEquals("three automatic transitions within 85s",3,transitions);
    }
    static final class TrackedView extends WebView {
        boolean destroyed;
        int destroys, loads;
        ValueCallback<String> dom;
        VisualStateCallback visual;
        long visualId;
        TrackedView(Activity host) { super(host); }
        @Override public void loadUrl(String url) { assertFalse(destroyed); loads++; super.loadUrl(url); }
        @Override public void evaluateJavascript(String script, ValueCallback<String> callback) {
            assertFalse(destroyed); super.evaluateJavascript(script, callback);
            if (script.equals(PreparedWebView.DOM_PROBE)) dom=callback;
        }
        @Override public void postVisualStateCallback(long id, VisualStateCallback callback) {
            assertFalse(destroyed); visual=callback; visualId=id; super.postVisualStateCallback(id, callback);
        }
        @Override public void destroy() {
            assertSame(Looper.getMainLooper(),Looper.myLooper()); assertNull(getParent()); assertFalse(destroyed);
            destroys++; super.destroy(); destroyed=true;
        }
    }
    public void testRealRendererTerminationAndExplicitRecovery() throws Exception {
        AtomicInteger preflights = new AtomicInteger(), creations = new AtomicInteger();
        AtomicReference<TrackedView> tracked = new AtomicReference<>();
        HarnessActivity.Preflight preflight = (assets,fixture) -> {
            preflights.incrementAndGet();
            return LocalView.verify(new AssetViewSource(assets,fixture),FixtureCatalog.identity(fixture),
                FixtureCatalog.mode(fixture),FixtureCatalog.JS,FixtureCatalog.CSS);
        };
        PreparedWebView.Factory factory = host -> { creations.incrementAndGet(); TrackedView view=new TrackedView(host); tracked.set(view); return view; };
        HarnessTestRunner.nextAdapters.set(new HarnessTestRunner.Adapters(preflight,factory));
        launch();
        PreparedWebView old=activity.prepared;
        TrackedView browser=tracked.get();
        assertNotNull(browser.dom); assertNotNull(browser.visual);
        AtomicReference<Boolean> terminated=new AtomicReference<>();
        int pid=android.os.Process.myPid();
        ui(() -> {
            WebViewRenderProcess renderer=browser.getWebViewRenderProcess();
            assertNotNull("multiprocess renderer API available",renderer);
            terminated.set(renderer.terminate());
        });
        assertEquals(Boolean.TRUE,terminated.get());
        android.util.Log.i("EventsRuntimeTest","terminate=true appPid="+pid+" one owned WebView");
        long end=SystemClock.elapsedRealtime()+10000;
        while(!activity.state.equals("failed") && SystemClock.elapsedRealtime()<end)Thread.sleep(25);
        assertEquals("failed",activity.state); assertEquals(1,old.rendererGone.get());
        ui(() -> {
            assertTrue(browser.destroyed); assertEquals(1,browser.destroys);
            ViewGroup content=activity.findViewById(android.R.id.content);
            ViewGroup frame=(ViewGroup)content.getChildAt(0);
            assertEquals(1,frame.getChildCount());
            assertTrue(((TextView)frame.getChildAt(0)).getText().toString().contains("Offline view unavailable"));
            // Redeliver the real readiness registrations after actual process death.
            browser.dom.onReceiveValue("true"); browser.visual.onComplete(browser.visualId);
            old.dispose(); old.pause(); old.resume(); old.start();
        });
        Thread.sleep(21000);
        ui(() -> { assertEquals("failed",activity.state); assertEquals(1,browser.destroys); assertEquals(1,browser.loads); });
        assertEquals(1,creations.get()); assertEquals(1,preflights.get());
        assertEquals(pid,android.os.Process.myPid());
        android.util.Log.i("EventsRuntimeTest","gone=1 detached destroy=1 safeMessage=true UI alive no reload/restart after21s lateCallbacksInert=true");
        close();
        HarnessTestRunner.nextAdapters.set(new HarnessTestRunner.Adapters(preflight,factory));
        launch(); assertEquals(2,preflights.get()); assertEquals(2,creations.get());
        assertEquals("true",evaluate(PreparedWebView.DOM_PROBE));
        assertEquals("true",evaluate("Array.from(document.images).every(i=>i.complete&&i.naturalWidth>0)"));
        android.util.Log.i("EventsRuntimeTest","explicit relaunch reverified same assets ready package="+FixtureCatalog.identity("two-card-tv")+" appPid="+android.os.Process.myPid());
    }
}
