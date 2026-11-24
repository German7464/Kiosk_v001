package org.kiosk.harness;

import android.app.Activity;
import android.content.res.AssetManager;
import android.os.Bundle;
import android.os.Handler;
import android.os.Looper;
import android.util.Log;
import android.view.Gravity;
import android.view.View;
import android.widget.FrameLayout;
import android.widget.TextView;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;
import java.util.concurrent.atomic.AtomicLong;
import org.kiosk.harness.core.LocalView;

public final class HarnessActivity extends Activity {
    interface Preflight { LocalView verify(AssetManager assets, String fixture) throws Exception; }
    static final long STARTUP_MS = 20000;
    private static final AtomicLong SEQUENCE = new AtomicLong();
    private final Handler ui = new Handler(Looper.getMainLooper());
    private final ExecutorService worker = Executors.newSingleThreadExecutor();
    private final long generation = SEQUENCE.incrementAndGet();
    private Preflight preflight = (assets, fixture) -> LocalView.verify(new AssetViewSource(assets, fixture),
        FixtureCatalog.identity(fixture), FixtureCatalog.mode(fixture), FixtureCatalog.JS, FixtureCatalog.CSS);
    private PreparedWebView.Factory browserFactory = PreparedWebView.PLATFORM;
    private boolean created;
    private FrameLayout frame;
    private TextView message;
    private boolean closed;
    volatile String state = "loading";
    PreparedWebView prepared;
    private final Runnable startupTimeout = () -> fail("startup_timeout");

    void configureAdapters(Preflight preflight, PreparedWebView.Factory browserFactory) {
        if (created) throw new IllegalStateException("activity_already_created");
        this.preflight = preflight;
        this.browserFactory = browserFactory;
    }

    @Override public void onCreate(Bundle saved) {
        created = true;
        super.onCreate(saved);
        frame = new FrameLayout(this);
        message = new TextView(this);
        message.setGravity(Gravity.CENTER);
        message.setText("Preparing verified offline Events view…");
        frame.addView(message, new FrameLayout.LayoutParams(-1, -1));
        setContentView(frame);
        frame.setOnApplyWindowInsetsListener((v, insets) -> {
            android.graphics.Insets bars = insets.getInsets(android.view.WindowInsets.Type.systemBars());
            v.setPadding(bars.left, bars.top, bars.right, bars.bottom);
            return insets;
        });
        ui.postDelayed(startupTimeout, STARTUP_MS);
        String name = getIntent().getStringExtra("fixture");
        final String fixture = name == null ? "valid-kiosk" : name;
        Log.i("EventsHarness", "launch fixture=" + (FixtureCatalog.NAMES.contains(fixture) ? fixture : "unknown")
            + " webview=" + android.webkit.WebView.getCurrentWebViewPackage());
        worker.execute(() -> {
            try {
                LocalView view = preflight.verify(getAssets(), fixture);
                ui.post(() -> attach(view));
            } catch (Exception e) { ui.post(() -> fail("view_refused")); }
        });
    }
    private void attach(LocalView view) {
        if (closed || !state.equals("loading")) return;
        try {
            prepared = new PreparedWebView(this, view, generation, new PreparedWebView.Completion() {
                public void ready() {
                    if (closed || !state.equals("loading")) return;
                    state = "ready";
                    ui.removeCallbacks(startupTimeout);
                    message.setVisibility(View.GONE);
                    Log.i("EventsHarness", "ready mode=" + view.mode + " package=" + view.packageIdentity);
                }
                public void failed() { fail("engine_refused"); }
            }, browserFactory);
            frame.addView(prepared.browser, 0, new FrameLayout.LayoutParams(-1, -1));
            prepared.start();
        } catch (Exception e) { fail("engine_unavailable"); }
    }
    private void fail(String code) {
        if (closed || state.equals("failed")) return;
        state = "failed";
        ui.removeCallbacks(startupTimeout);
        if (prepared != null) {
            prepared.dispose();
        }
        message.setVisibility(View.VISIBLE);
        message.setText("Offline view unavailable. Close and explicitly relaunch the experiment.");
        Log.w("EventsHarness", code);
    }
    @Override protected void onPause() {
        if (prepared != null && state.equals("ready")) prepared.pause();
        super.onPause();
    }
    @Override protected void onResume() {
        super.onResume();
        if (prepared != null && state.equals("ready")) prepared.resume();
    }
    @Override protected void onDestroy() {
        closed = true;
        ui.removeCallbacksAndMessages(null);
        worker.shutdownNow();
        if (prepared != null) {
            prepared.dispose();
        }
        super.onDestroy();
    }
}
