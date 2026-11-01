package org.kiosk.harness;

import android.app.Activity;
import android.graphics.Bitmap;
import android.net.http.SslError;
import android.os.Handler;
import android.os.Looper;
import android.view.ViewGroup;
import android.view.ViewParent;
import android.webkit.CookieManager;
import android.webkit.HttpAuthHandler;
import android.webkit.PermissionRequest;
import android.webkit.SslErrorHandler;
import android.webkit.WebChromeClient;
import android.webkit.WebResourceError;
import android.webkit.WebResourceRequest;
import android.webkit.WebResourceResponse;
import android.webkit.WebSettings;
import android.webkit.WebView;
import android.webkit.WebViewClient;
import android.webkit.RenderProcessGoneDetail;
import java.io.ByteArrayInputStream;
import java.util.Map;
import java.util.concurrent.atomic.AtomicInteger;
import org.kiosk.harness.core.LocalView;
import org.kiosk.harness.core.OriginPolicy;

/** One immutable view and one generation. No publication switching or page/native bridge. */
final class PreparedWebView {
    interface Completion { void ready(); void failed(); }
    interface Factory {
        WebView create(Activity activity);
        default void configured(WebView browser) {}
    }
    static final Factory PLATFORM = WebView::new;
    static final long PREPARATION_MS = 15000;
    static final String DOM_PROBE = "(() => { const n = document.getElementById('counter'); return !!n && /^\\d{1,5} \\/ \\d{1,5}$/.test(n.textContent); })()";
    private static final String CSP = "default-src 'none'; script-src 'self'; style-src 'self'; img-src 'self'; connect-src 'none'; frame-src 'none'; object-src 'none'; base-uri 'none'; form-action 'none'";
    final WebView browser;
    final AtomicInteger served = new AtomicInteger(), denied = new AtomicInteger(), blockedNavigation = new AtomicInteger();
    final AtomicInteger rendererGone = new AtomicInteger();
    private final Handler ui = new Handler(Looper.getMainLooper());
    private final OriginPolicy policy;
    private final LocalView view;
    private final Completion completion;
    private final long generation;
    private boolean disposed, finished, probing;
    private final Runnable timeout = this::fail;

    PreparedWebView(Activity activity, LocalView view, long generation, Completion completion) {
        this(activity, view, generation, completion, PLATFORM);
    }
    PreparedWebView(Activity activity, LocalView view, long generation, Completion completion, Factory factory) {
        requireUiThread();
        this.view = view;
        this.generation = generation;
        this.completion = completion;
        policy = new OriginPolicy(view);
        WebView.setWebContentsDebuggingEnabled(false);
        browser = factory.create(activity);
        try {
            configure();
            factory.configured(browser);
            // No runnable can retain a constructor that failed to transfer ownership.
            ui.postDelayed(timeout, PREPARATION_MS);
        } catch (RuntimeException | Error error) {
            try { dispose(); } catch (RuntimeException | Error cleanup) { error.addSuppressed(cleanup); }
            throw error;
        }
    }
    private void configure() {
        // Refuse legacy/provider-injected bridge names as well as registering no app bridge.
        for (String name : new String[]{"android", "searchBoxJavaBridge_", "accessibility", "accessibilityTraversal"})
            browser.removeJavascriptInterface(name);
        browser.setAlpha(0f);
        browser.setFocusable(true);
        browser.setFocusableInTouchMode(true);
        WebSettings settings = browser.getSettings();
        settings.setJavaScriptEnabled(true);
        settings.setAllowFileAccess(false);
        settings.setAllowContentAccess(false);
        settings.setAllowFileAccessFromFileURLs(false);
        settings.setAllowUniversalAccessFromFileURLs(false);
        settings.setMixedContentMode(WebSettings.MIXED_CONTENT_NEVER_ALLOW);
        settings.setBlockNetworkLoads(true);
        settings.setCacheMode(WebSettings.LOAD_NO_CACHE);
        settings.setDomStorageEnabled(false);
        settings.setDatabaseEnabled(false);
        settings.setGeolocationEnabled(false);
        settings.setJavaScriptCanOpenWindowsAutomatically(false);
        settings.setSupportMultipleWindows(false);
        settings.setMediaPlaybackRequiresUserGesture(true);
        CookieManager.getInstance().setAcceptCookie(false);
        CookieManager.getInstance().setAcceptThirdPartyCookies(browser, false);
        browser.setDownloadListener((url, agent, disposition, mime, length) -> denied.incrementAndGet());
        browser.setOnLongClickListener(v -> true);
        browser.setWebChromeClient(new WebChromeClient() {
            @Override public void onPermissionRequest(PermissionRequest request) { request.deny(); }
            @Override public void onGeolocationPermissionsShowPrompt(String origin, android.webkit.GeolocationPermissions.Callback callback) {
                callback.invoke(origin, false, false);
            }
            @Override public boolean onCreateWindow(WebView view, boolean dialog, boolean gesture, android.os.Message message) {
                denied.incrementAndGet(); return false;
            }
            @Override public boolean onShowFileChooser(WebView view, android.webkit.ValueCallback<android.net.Uri[]> callback, FileChooserParams params) {
                callback.onReceiveValue(null); return true;
            }
            @Override public boolean onJsAlert(WebView view, String url, String message, android.webkit.JsResult result) { result.cancel(); return true; }
            @Override public boolean onJsConfirm(WebView view, String url, String message, android.webkit.JsResult result) { result.cancel(); return true; }
            @Override public boolean onJsPrompt(WebView view, String url, String message, String value, android.webkit.JsPromptResult result) { result.cancel(); return true; }
        });
        browser.setWebViewClient(new WebViewClient() {
            @Override public boolean shouldOverrideUrlLoading(WebView browser, WebResourceRequest request) {
                boolean block = !policy.navigate(request.getUrl().toString(), request.getMethod(), request.isForMainFrame());
                if (block) blockedNavigation.incrementAndGet();
                return block;
            }
            @Override public boolean shouldOverrideUrlLoading(WebView browser, String url) {
                boolean block = !policy.navigate(url, "GET", true);
                if (block) blockedNavigation.incrementAndGet();
                return block;
            }
            @Override public WebResourceResponse shouldInterceptRequest(WebView browser, WebResourceRequest request) {
                return response(request.getUrl().toString(), request.getMethod(), request.isForMainFrame());
            }
            @Override public void onPageStarted(WebView browser, String url, Bitmap favicon) {
                if (!disposed && !policy.navigate(url, "GET", true)) fail();
            }
            @Override public void onPageFinished(WebView browser, String url) {
                if (disposed || finished || probing || !policy.navigate(url, "GET", true)) return;
                probing = true;
                browser.evaluateJavascript(DOM_PROBE, result -> {
                    if (disposed || finished) return;
                    if (!"true".equals(result) || !policy.navigate(browser.getUrl(), "GET", true)) { fail(); return; }
                    // Attached view plus generation-bound callback: onPageFinished alone is not readiness.
                    browser.postVisualStateCallback(generation, new WebView.VisualStateCallback() {
                        @Override public void onComplete(long requestId) {
                            if (disposed || finished || requestId != generation) return;
                            if (!policy.navigate(browser.getUrl(), "GET", true)) { fail(); return; }
                            finished = true;
                            ui.removeCallbacks(timeout);
                            browser.setAlpha(1f);
                            browser.requestFocus();
                            completion.ready();
                        }
                    });
                });
            }
            @Override public void onReceivedError(WebView browser, WebResourceRequest request, WebResourceError error) {
                if (request.isForMainFrame()) fail();
            }
            @Override public void onReceivedSslError(WebView browser, SslErrorHandler handler, SslError error) { handler.cancel(); fail(); }
            @Override public void onReceivedHttpAuthRequest(WebView browser, HttpAuthHandler handler, String host, String realm) { handler.cancel(); fail(); }
            @Override public boolean onRenderProcessGone(WebView browser, RenderProcessGoneDetail detail) {
                rendererGone.incrementAndGet();
                android.util.Log.w("EventsHarness", "renderer_gone crashed=" + detail.didCrash());
                fail(); return true;
            }
        });
    }
    void start() { requireUiThread(); if (!disposed) browser.loadUrl(OriginPolicy.INDEX); }
    void pause() { requireUiThread(); if (!disposed) browser.onPause(); }
    void resume() { requireUiThread(); if (!disposed) browser.onResume(); }
    WebResourceResponse response(String url, String method, boolean mainFrame) {
        String path = policy.resource(url, method);
        if (path != null && (!mainFrame || path.equals("index.html"))) {
            try {
                byte[] bytes = view.read(path);
                served.incrementAndGet();
                return new WebResourceResponse(LocalView.mime(path), "UTF-8", 200, "OK",
                    Map.of("Cache-Control", "no-store", "X-Content-Type-Options", "nosniff", "Content-Security-Policy", CSP),
                    new ByteArrayInputStream(bytes));
            } catch (Exception e) { ui.post(this::fail); }
        }
        denied.incrementAndGet();
        return new WebResourceResponse("text/plain", "UTF-8", 403, "Forbidden",
            Map.of("Cache-Control", "no-store", "Content-Security-Policy", "default-src 'none'"),
            new ByteArrayInputStream(new byte[0]));
    }
    private void fail() {
        if (disposed) return;
        dispose();
        completion.failed();
    }
    void dispose() {
        requireUiThread();
        if (disposed) return;
        disposed = true;
        ui.removeCallbacksAndMessages(null);
        ViewParent parent = browser.getParent();
        if (parent instanceof ViewGroup) ((ViewGroup) parent).removeView(browser);
        try { browser.stopLoading(); }
        finally { browser.destroy(); }
    }
    private static void requireUiThread() {
        if (Looper.myLooper() != Looper.getMainLooper()) throw new IllegalStateException("webview_requires_ui_thread");
    }
}
