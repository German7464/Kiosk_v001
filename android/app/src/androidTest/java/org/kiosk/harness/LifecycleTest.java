package org.kiosk.harness;

import android.app.Activity;
import android.app.Instrumentation;
import android.content.Intent;
import android.os.Looper;
import android.os.SystemClock;
import android.test.InstrumentationTestCase;
import android.view.View;
import android.view.ViewGroup;
import android.webkit.ValueCallback;
import android.webkit.WebSettings;
import android.webkit.WebView;
import android.webkit.WebViewClient;
import android.widget.FrameLayout;
import android.widget.TextView;
import java.util.ArrayList;
import java.util.List;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.atomic.AtomicInteger;
import java.util.concurrent.atomic.AtomicReference;
import java.util.function.BooleanSupplier;
import org.kiosk.harness.core.LocalView;

@SuppressWarnings("deprecation")
public class LifecycleTest extends InstrumentationTestCase {
    private final List<HarnessActivity> activities = new ArrayList<>();
    private final List<PreparedWebView> candidates = new ArrayList<>();
    private final List<Gate> gates = new ArrayList<>();
    private void ui(Runnable work) {
        CountDownLatch done = new CountDownLatch(1);
        AtomicReference<Throwable> failure = new AtomicReference<>();
        new android.os.Handler(Looper.getMainLooper()).post(() -> {
            try { work.run(); } catch (Throwable error) { failure.set(error); } finally { done.countDown(); }
        });
        try {
            if (!done.await(10, TimeUnit.SECONDS)) {
                for (var entry : Thread.getAllStackTraces().entrySet())
                    if (entry.getKey().getName().equals("main"))
                        android.util.Log.e("EventsHarnessFixTest", "UI timeout: "+java.util.Arrays.toString(entry.getValue()));
                throw new AssertionError("UI work timed out");
            }
        } catch (InterruptedException e) { throw new AssertionError(e); }
        if (failure.get() != null) throw new AssertionError("UI work failed", failure.get());
    }
    private void until(BooleanSupplier condition, long millis, String message) throws Exception {
        long deadline = SystemClock.elapsedRealtime() + millis;
        while (!condition.getAsBoolean() && SystemClock.elapsedRealtime() < deadline) Thread.sleep(25);
        assertTrue(message, condition.getAsBoolean());
    }
    private HarnessActivity launch(HarnessActivity.Preflight preflight, PreparedWebView.Factory factory) throws Exception {
        if (preflight != null) HarnessTestRunner.nextAdapters.set(new HarnessTestRunner.Adapters(preflight, factory));
        Intent intent = new Intent(getInstrumentation().getTargetContext(), HarnessActivity.class);
        intent.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK | Intent.FLAG_ACTIVITY_MULTIPLE_TASK);
        AtomicReference<HarnessActivity> result = new AtomicReference<>();
        AtomicReference<Throwable> error = new AtomicReference<>();
        CountDownLatch launched = new CountDownLatch(1);
        Thread launcher = new Thread(() -> {
            try { result.set((HarnessActivity)getInstrumentation().startActivitySync(intent)); }
            catch (Throwable failure) { error.set(failure); }
            finally { launched.countDown(); }
        }, "bounded-test-launch");
        launcher.setDaemon(true); launcher.start();
        assertTrue("Activity launch bounded", launched.await(10, TimeUnit.SECONDS));
        if (error.get() != null) throw new AssertionError(error.get());
        HarnessActivity activity = result.get();
        activities.add(activity);
        return activity;
    }
    private HarnessActivity host() throws Exception {
        HarnessActivity activity = launch(null, null);
        until(() -> activity.state.equals("ready"), 22000, "host ready");
        return activity;
    }
    private LocalView verified() throws Exception {
        return verify(getInstrumentation().getTargetContext().getAssets(), "valid-kiosk");
    }
    private static LocalView verify(android.content.res.AssetManager assets, String fixture) throws Exception {
        return LocalView.verify(new AssetViewSource(assets, fixture), FixtureCatalog.identity(fixture),
            FixtureCatalog.mode(fixture), FixtureCatalog.JS, FixtureCatalog.CSS);
    }
    private static final class Gate {
        final CountDownLatch entered = new CountDownLatch(1), release = new CountDownLatch(1), returned = new CountDownLatch(1);
        LocalView verify(android.content.res.AssetManager assets, String fixture) throws Exception {
            entered.countDown();
            // Deliberately emulate uncancellable work; only the worker waits, never the UI thread.
            boolean interrupted = false;
            while (true) {
                try { release.await(); break; } catch (InterruptedException e) { interrupted = true; }
            }
            try { return LifecycleTest.verify(assets, fixture); }
            finally { returned.countDown(); if (interrupted) Thread.currentThread().interrupt(); }
        }
    }
    private static final class Completion implements PreparedWebView.Completion {
        final AtomicInteger ready = new AtomicInteger(), failed = new AtomicInteger();
        public void ready() { ready.incrementAndGet(); }
        public void failed() { failed.incrementAndGet(); }
    }
    private static final class TrackedWebView extends WebView {
        boolean armed, destroyed, failSettings, holdDom, holdVisual;
        int destroys, afterDestroy;
        boolean detachedAtDestroy, destroyedOnUi;
        volatile ValueCallback<String> dom;
        volatile VisualStateCallback visual;
        long visualId;
        WebViewClient client;
        TrackedWebView(Activity activity) { super(activity); armed = true; }
        private void alive() { if (armed && destroyed) { afterDestroy++; throw new AssertionError("method after destroy"); } }
        @Override public WebSettings getSettings() { alive(); if (failSettings) throw new IllegalStateException("injected_settings"); return super.getSettings(); }
        @Override public void stopLoading() { alive(); super.stopLoading(); }
        @Override public void loadUrl(String url) { alive(); super.loadUrl(url); }
        @Override public String getUrl() { alive(); return super.getUrl(); }
        @Override public void setAlpha(float alpha) { alive(); super.setAlpha(alpha); }
        @Override public void onPause() { alive(); super.onPause(); }
        @Override public void onResume() { alive(); super.onResume(); }
        @Override public void setWebViewClient(WebViewClient client) { alive(); this.client = client; super.setWebViewClient(client); }
        @Override public void evaluateJavascript(String script, ValueCallback<String> callback) {
            alive(); if (holdDom) dom = callback; else super.evaluateJavascript(script, callback);
        }
        @Override public void postVisualStateCallback(long id, VisualStateCallback callback) {
            alive(); if (holdVisual) { visualId = id; visual = callback; } else super.postVisualStateCallback(id, callback);
        }
        @Override public void destroy() {
            alive(); destroys++;
            detachedAtDestroy = getParent() == null;
            destroyedOnUi = Looper.myLooper() == Looper.getMainLooper();
            if (!detachedAtDestroy || !destroyedOnUi) throw new AssertionError("destroy contract");
            super.destroy(); destroyed = true;
        }
        void assertClean() {
            assertEquals(1, destroys); assertTrue(destroyed); assertTrue(detachedAtDestroy);
            assertTrue(destroyedOnUi); assertEquals(0, afterDestroy);
        }
    }
    private PreparedWebView candidate(HarnessActivity activity, LocalView view, TrackedWebView browser, Completion completion, boolean attach) {
        PreparedWebView result = new PreparedWebView(activity, view, 7301, completion, ignored -> browser);
        candidates.add(result);
        if (attach) activity.addContentView(browser, new ViewGroup.LayoutParams(-1, -1));
        return result;
    }
    private void safeMessage(HarnessActivity activity) {
        assertEquals("failed", activity.state);
        ViewGroup content = activity.findViewById(android.R.id.content);
        assertTrue(hasSafeText(content));
    }
    private boolean hasSafeText(View view) {
        if (view instanceof TextView && view.getVisibility() == View.VISIBLE
                && ((TextView)view).getText().toString().startsWith("Offline view unavailable.")) return true;
        if (view instanceof ViewGroup) for (int n = 0; n < ((ViewGroup)view).getChildCount(); n++)
            if (hasSafeText(((ViewGroup)view).getChildAt(n))) return true;
        return false;
    }
    @Override protected void tearDown() throws Exception {
        HarnessTestRunner.nextAdapters.set(null);
        for (Gate gate : gates) gate.release.countDown();
        ui(() -> {
            for (PreparedWebView candidate : candidates) candidate.dispose();
            for (HarnessActivity activity : activities) if (!activity.isDestroyed()) activity.finish();
        });
        getInstrumentation().waitForIdleSync();
        super.tearDown();
    }
    public void testConstructorFailuresHaveNoLateCallbacks() throws Exception {
        HarnessActivity activity = host(); LocalView view = verified();
        Completion completion = new Completion(); List<TrackedWebView> owned = new ArrayList<>();
        AtomicInteger creates = new AtomicInteger();
        ui(() -> {
            try {
                new PreparedWebView(activity, view, 1, completion, ignored -> { creates.incrementAndGet(); throw new IllegalStateException("injected_creation"); });
                fail("creation must throw");
            } catch (IllegalStateException expected) { assertEquals("injected_creation", expected.getMessage()); }
            for (boolean late : new boolean[]{false, true}) {
                TrackedWebView browser = new TrackedWebView(activity); owned.add(browser);
                browser.failSettings = !late;
                try {
                    new PreparedWebView(activity, view, 2, completion, new PreparedWebView.Factory() {
                        public WebView create(Activity ignored) { return browser; }
                        public void configured(WebView value) {
                            activity.addContentView(value, new ViewGroup.LayoutParams(-1, -1));
                            throw new IllegalStateException("injected_late_configuration");
                        }
                    });
                    fail("configuration must throw");
                } catch (IllegalStateException expected) { assertTrue(expected.getMessage().startsWith("injected_")); }
                browser.assertClean();
            }
        });
        HarnessActivity refused = launch(LifecycleTest::verify, ignored -> { throw new IllegalStateException("injected_creation"); });
        until(() -> refused.state.equals("failed"), 5000, "Activity construction failure");
        ui(() -> safeMessage(refused));
        Thread.sleep(21000);
        ui(() -> {
            assertEquals(1, creates.get()); assertEquals(0, completion.ready.get()); assertEquals(0, completion.failed.get());
            for (TrackedWebView browser : owned) browser.assertClean();
            assertNull(refused.prepared); safeMessage(refused);
        });
        android.util.Log.i("EventsHarnessFixTest", "constructor creation/early+late configuration refused; quiet >20s; 0 late callbacks, owned views destroyed once");
    }
    public void testAttachedAndUnattachedCleanupAndErrorAreIdempotent() throws Exception {
        HarnessActivity activity = host(); LocalView view = verified();
        ui(() -> {
            for (boolean attached : new boolean[]{false, true}) {
                TrackedWebView browser = new TrackedWebView(activity); Completion completion = new Completion();
                PreparedWebView candidate = candidate(activity, view, browser, completion, attached);
                if (attached) browser.client.onPageStarted(browser, "https://example.com/refused", null);
                candidate.dispose(); candidate.dispose(); candidate.pause(); candidate.resume(); candidate.start();
                browser.assertClean(); assertEquals(0, completion.ready.get()); assertEquals(attached ? 1 : 0, completion.failed.get());
            }
        });
        android.util.Log.i("EventsHarnessFixTest", "attached error/unattached dispose: detach before UI destroy once; repeated dispose/start/pause/resume inert");
    }
    public void testNativeTimeoutDetachesAndLateDomVisualAreInert() throws Exception {
        HarnessActivity activity = host(); LocalView view = verified();
        TrackedWebView[] browsers = new TrackedWebView[3]; Completion[] completions = new Completion[3];
        ui(() -> {
            for (int i = 0; i < 3; i++) {
                TrackedWebView browser = new TrackedWebView(activity); browsers[i] = browser;
                Completion completion = new Completion(); completions[i] = completion;
                browser.holdDom = i == 1; browser.holdVisual = i == 2;
                PreparedWebView candidate = candidate(activity, view, browser, completion, true);
                if (i != 0) candidate.start();
            }
        });
        until(() -> browsers[1].dom != null && browsers[2].visual != null, 5000, "captured real DOM/visual registrations");
        until(() -> completions[0].failed.get() == 1 && completions[1].failed.get() == 1 && completions[2].failed.get() == 1, 18000, "native timeouts");
        Thread.sleep(6000);
        ui(() -> {
            browsers[1].dom.onReceiveValue("true"); browsers[2].visual.onComplete(browsers[2].visualId);
            for (TrackedWebView browser : browsers) browser.assertClean();
            for (Completion completion : completions) { assertEquals(0, completion.ready.get()); assertEquals(1, completion.failed.get()); }
            for (PreparedWebView candidate : candidates) candidate.dispose();
        });
        android.util.Log.i("EventsHarnessFixTest", "native timeouts detached attached views; held DOM/visual delivered after destroy remain inert");
    }
    public void testRealStartupWatchdogRejectsLatePreflight() throws Exception {
        Gate gate = new Gate(); gates.add(gate); AtomicInteger creates = new AtomicInteger();
        long began = SystemClock.elapsedRealtime();
        HarnessActivity activity = launch(gate::verify, owner -> { creates.incrementAndGet(); return new TrackedWebView(owner); });
        assertTrue(gate.entered.await(5, TimeUnit.SECONDS));
        AtomicInteger pulse = new AtomicInteger(); ui(pulse::incrementAndGet);
        assertEquals("loading", activity.state); assertEquals(1, pulse.get());
        until(() -> activity.state.equals("failed"), 23000, "20s startup watchdog");
        long elapsed = SystemClock.elapsedRealtime() - began;
        assertTrue("actual 20s deadline", elapsed >= 19500 && elapsed < 24000);
        ui(() -> safeMessage(activity));
        gate.release.countDown(); assertTrue(gate.returned.await(5, TimeUnit.SECONDS));
        Thread.sleep(300); getInstrumentation().waitForIdleSync();
        ui(() -> { safeMessage(activity); assertNull(activity.prepared); assertEquals(0, creates.get()); });
        android.util.Log.i("EventsHarnessFixTest", "startup watchdog elapsedMs="+elapsed+" UI pulse alive; late verified preflight rejected; no WebView created");
    }
    public void testRecreationRejectsOldPreflightAndVisualCallback() throws Exception {
        Gate gate = new Gate(); gates.add(gate); AtomicInteger oldCreates = new AtomicInteger();
        HarnessActivity old = launch(gate::verify, owner -> { oldCreates.incrementAndGet(); return new TrackedWebView(owner); });
        assertTrue(gate.entered.await(5, TimeUnit.SECONDS));
        HarnessActivity replacement = recreate(old);
        until(() -> replacement.state.equals("ready"), 22000, "replacement ready");
        gate.release.countDown(); assertTrue(gate.returned.await(5, TimeUnit.SECONDS));
        Thread.sleep(300); getInstrumentation().waitForIdleSync();
        ui(() -> { assertTrue(old.isDestroyed()); assertNull(old.prepared); assertEquals(0, oldCreates.get()); assertEquals("ready", replacement.state); });

        final TrackedWebView[] held = new TrackedWebView[1];
        HarnessActivity visualOwner = launch(LifecycleTest::verify, owner -> { held[0] = new TrackedWebView(owner); held[0].holdVisual = true; return held[0]; });
        until(() -> held[0] != null && held[0].visual != null, 5000, "old visual registered");
        HarnessActivity visualReplacement = recreate(visualOwner);
        until(() -> visualReplacement.state.equals("ready"), 22000, "visual replacement ready");
        ui(() -> {
            assertTrue(visualOwner.isDestroyed());
            held[0].visual.onComplete(held[0].visualId);
            visualOwner.prepared.dispose(); visualOwner.prepared.dispose();
            held[0].assertClean(); assertFalse(visualOwner.state.equals("ready")); assertEquals("ready", visualReplacement.state);
        });
        android.util.Log.i("EventsHarnessFixTest", "real Activity recreation: old delayed preflight and held visual cannot attach/promote; new generation ready");
    }
    private HarnessActivity recreate(HarnessActivity old) throws Exception {
        Instrumentation.ActivityMonitor monitor = getInstrumentation().addMonitor(HarnessActivity.class.getName(), null, false);
        try {
            ui(old::recreate);
            HarnessActivity next = (HarnessActivity)monitor.waitForActivityWithTimeout(5000);
            assertNotNull("recreated Activity", next); assertNotSame(old, next); activities.add(next); return next;
        } finally { getInstrumentation().removeMonitor(monitor); }
    }
}
