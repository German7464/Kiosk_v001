package org.kiosk.harness.admin;

import android.app.Activity;
import android.app.AlertDialog;
import android.graphics.Color;
import android.net.http.SslError;
import android.os.Bundle;
import android.os.Handler;
import android.os.Looper;
import android.view.Gravity;
import android.view.View;
import android.view.ViewGroup;
import android.view.ViewParent;
import android.view.WindowInsets;
import android.webkit.ClientCertRequest;
import android.webkit.CookieManager;
import android.webkit.HttpAuthHandler;
import android.webkit.PermissionRequest;
import android.webkit.RenderProcessGoneDetail;
import android.webkit.SslErrorHandler;
import android.webkit.WebChromeClient;
import android.webkit.WebResourceError;
import android.webkit.WebResourceRequest;
import android.webkit.WebResourceResponse;
import android.webkit.WebSettings;
import android.webkit.WebStorage;
import android.webkit.WebView;
import android.webkit.WebViewClient;
import android.webkit.WebViewDatabase;
import android.widget.Button;
import android.widget.FrameLayout;
import android.widget.LinearLayout;
import android.widget.TextView;
import java.io.ByteArrayInputStream;
import java.util.Map;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;
import org.kiosk.harness.delivery.DeliveryClient;

/**
 * Server-rendered administration inside an isolated WebView. The HTML/CSS/JS,
 * form POST, CSRF token and server session are the existing web admin; this
 * activity only supplies the trusted origin, a hardened browser container and
 * explicit sign-out. No admin password or device credential is injected.
 *
 * Runs in the private ":admin" process and calls setDataDirectorySuffix before
 * any other WebView API, so its cookies/storage cannot mix with the packaged
 * offline display WebView in the main process.
 */
public final class AdminActivity extends Activity {
    private static final String ENTRY = "/admin/devices/pair";
    private static final String HOME = "/admin";
    private static final String LOGOUT_JS =
        "(function(){var f=document.querySelector('form[action$=\"/admin/logout\"]');"
            + "if(!f)return false;f.submit();return true;})()";

    private final Handler ui = new Handler(Looper.getMainLooper());
    private final ExecutorService worker = Executors.newSingleThreadExecutor();
    private WebView browser;
    private AdminNavigationPolicy policy;
    private String origin = "";
    private DeliveryClient delivery;
    private CaSetup caSetup;
    private TextView address, notice;
    private View errorPanel;
    private TextView errorText;
    private Button signOut;
    private boolean closing, logoutPending, errorShown, initialAuthCheck = true;
    private int logoutSubmits, blocked;
    private long generation;

    @Override protected void onCreate(Bundle saved) {
        super.onCreate(saved);
        // Required before any other android.webkit call in this process.
        try {
            WebView.setDataDirectorySuffix("admin");
        } catch (IllegalStateException alreadyInitialized) {
            // The private process already selected its directory.
        }
        try {
            delivery = new DeliveryClient(this);
            origin = delivery.trustedOrigin();
        } catch (Exception unavailable) {
            origin = "";
        }
        if (origin.isEmpty()) {
            blockedScreen("No trusted server is confirmed for this device.\n\n"
                + "Connect and confirm the server in the main app, then open Administration again.");
            return;
        }
        try {
            policy = new AdminNavigationPolicy(origin);
        } catch (IllegalArgumentException unsafe) {
            blockedScreen("The saved server origin is not a safe administration origin.");
            return;
        }
        buildUi();
        caSetup = new CaSetup(this);
        preflight();
    }

    private void buildUi() {
        LinearLayout root = new LinearLayout(this);
        root.setOrientation(LinearLayout.VERTICAL);

        LinearLayout bar = new LinearLayout(this);
        bar.setGravity(Gravity.CENTER_VERTICAL);
        TextView title = new TextView(this);
        title.setText("Administration");
        title.setTextSize(18);
        bar.addView(title, new LinearLayout.LayoutParams(0, ViewGroup.LayoutParams.WRAP_CONTENT, 1));
        Button pairing = new Button(this);
        pairing.setText("Pairing");
        pairing.setOnClickListener(view -> load(ENTRY));
        bar.addView(pairing);
        Button certificate = new Button(this);
        certificate.setText("CA setup");
        certificate.setOnClickListener(view -> caSetup.begin(delivery.confirmedPublicCa(), origin));
        bar.addView(certificate);
        signOut = new Button(this);
        signOut.setText("Sign out");
        bar.addView(signOut);
        Button close = new Button(this);
        close.setText("Close");
        bar.addView(close);
        root.addView(bar);

        address = new TextView(this);
        address.setTextSize(11);
        address.setText(origin + HOME);
        root.addView(address);

        notice = new TextView(this);
        notice.setText("Checking the trusted server and certificate...");
        root.addView(notice);

        FrameLayout content = new FrameLayout(this);
        browser = new WebView(this);
        configure(browser);
        content.addView(browser, new FrameLayout.LayoutParams(-1, -1));

        LinearLayout panel = new LinearLayout(this);
        panel.setOrientation(LinearLayout.VERTICAL);
        panel.setGravity(Gravity.CENTER);
        panel.setBackgroundColor(Color.WHITE);
        errorText = new TextView(this);
        errorText.setGravity(Gravity.CENTER);
        panel.addView(errorText, new LinearLayout.LayoutParams(-1, ViewGroup.LayoutParams.WRAP_CONTENT));
        Button retry = new Button(this);
        retry.setText("Retry");
        panel.addView(retry);
        Button exit = new Button(this);
        exit.setText("Exit administration");
        panel.addView(exit);
        errorPanel = panel;
        errorPanel.setVisibility(View.GONE);
        content.addView(errorPanel, new FrameLayout.LayoutParams(-1, -1));

        root.addView(content, new LinearLayout.LayoutParams(-1, 0, 1));
        root.setOnApplyWindowInsetsListener((view, insets) -> {
            var bars = insets.getInsets(WindowInsets.Type.systemBars());
            view.setPadding(bars.left, bars.top, bars.right, bars.bottom);
            return insets;
        });
        setContentView(root);

        signOut.setOnClickListener(view -> confirmLogout());
        close.setOnClickListener(view -> finish());
        retry.setOnClickListener(view -> {
            hideError();
            preflight();
        });
        exit.setOnClickListener(view -> finish());
    }

    @Override protected void onActivityResult(int request, int result, android.content.Intent data) {
        super.onActivityResult(request,result,data);
        if(caSetup!=null)caSetup.result(request,result,data);
    }

    private void blockedScreen(String text) {
        LinearLayout root = new LinearLayout(this);
        root.setOrientation(LinearLayout.VERTICAL);
        root.setGravity(Gravity.CENTER);
        root.setOnApplyWindowInsetsListener((view, insets) -> {
            var bars = insets.getInsets(WindowInsets.Type.systemBars());
            view.setPadding(bars.left, bars.top, bars.right, bars.bottom);
            return insets;
        });
        TextView message = new TextView(this);
        message.setText(text);
        message.setGravity(Gravity.CENTER);
        root.addView(message, new LinearLayout.LayoutParams(-1, ViewGroup.LayoutParams.WRAP_CONTENT));
        Button close = new Button(this);
        close.setText("Close");
        close.setOnClickListener(view -> finish());
        root.addView(close);
        setContentView(root);
    }

    private void preflight() {
        if (closing) return;
        final long current = ++generation;
        notice.setText("Checking the trusted server and certificate...");
        worker.execute(() -> {
            String failure = null;
            try {
                delivery.checkAdminAvailability();
            } catch (Exception rejected) {
                failure = "The trusted server, certificate chain, hostname or device clock could not be validated.";
            }
            final String result = failure;
            ui.post(() -> {
                if (closing || current != generation) return;
                if (result != null) {
                    showError(result);
                    return;
                }
                hideError();
                load(HOME);
            });
        });
    }

    private void load(String path) {
        if (closing || browser == null) return;
        browser.loadUrl(origin + path);
    }

    private void configure(WebView view) {
        WebView.setWebContentsDebuggingEnabled(false);
        for (String name : new String[]{"android", "searchBoxJavaBridge_", "accessibility", "accessibilityTraversal"}) {
            view.removeJavascriptInterface(name);
        }
        WebSettings settings = view.getSettings();
        settings.setJavaScriptEnabled(true);
        settings.setDomStorageEnabled(true);
        settings.setDatabaseEnabled(false);
        settings.setAllowFileAccess(false);
        settings.setAllowContentAccess(false);
        settings.setAllowFileAccessFromFileURLs(false);
        settings.setAllowUniversalAccessFromFileURLs(false);
        settings.setMixedContentMode(WebSettings.MIXED_CONTENT_NEVER_ALLOW);
        settings.setBlockNetworkLoads(false);
        settings.setCacheMode(WebSettings.LOAD_NO_CACHE);
        settings.setGeolocationEnabled(false);
        settings.setJavaScriptCanOpenWindowsAutomatically(false);
        settings.setSupportMultipleWindows(true);
        settings.setMediaPlaybackRequiresUserGesture(true);
        settings.setSaveFormData(false);
        // Deprecated no-op on current WebView, kept for older platform fallbacks.
        settings.setSavePassword(false);
        view.setBackgroundColor(Color.WHITE);
        view.setDownloadListener((url, userAgent, disposition, mime, length) -> {
            blocked++;
            flash("Downloads are blocked in administration.");
        });
        CookieManager cookies = CookieManager.getInstance();
        cookies.setAcceptCookie(true);
        cookies.setAcceptThirdPartyCookies(view, false);

        view.setWebChromeClient(new WebChromeClient() {
            @Override public void onPermissionRequest(PermissionRequest request) {
                request.deny();
            }
            @Override public void onGeolocationPermissionsShowPrompt(String pageOrigin, android.webkit.GeolocationPermissions.Callback callback) {
                callback.invoke(pageOrigin, false, false);
            }
            @Override public boolean onCreateWindow(WebView parent, boolean dialog, boolean gesture, android.os.Message message) {
                blocked++;
                flash("Pop-up windows are blocked in administration.");
                return false;
            }
            @Override public boolean onShowFileChooser(WebView parent, android.webkit.ValueCallback<android.net.Uri[]> callback,
                                                      FileChooserParams params) {
                callback.onReceiveValue(null);
                return true;
            }
        });

        view.setWebViewClient(new WebViewClient() {
            @Override public boolean shouldOverrideUrlLoading(WebView parent, WebResourceRequest request) {
                return blockForeign(request.getUrl().toString(), request.isForMainFrame());
            }
            @Override public boolean shouldOverrideUrlLoading(WebView parent, String url) {
                return blockForeign(url, true);
            }
            @Override public WebResourceResponse shouldInterceptRequest(WebView parent, WebResourceRequest request) {
                String url = request.getUrl().toString();
                if (closing || policy.resource(url)) return null;
                blocked++;
                return new WebResourceResponse("text/plain", "UTF-8", 403, "Forbidden",
                    Map.of("Cache-Control", "no-store"), new ByteArrayInputStream(new byte[0]));
            }
            @Override public void onPageStarted(WebView parent, String url, android.graphics.Bitmap favicon) {
                if (closing) return;
                if (!policy.navigation(url)) {
                    parent.stopLoading();
                    flash("Navigation outside the trusted server was blocked.");
                }
            }
            @Override public void onPageFinished(WebView parent, String url) {
                if (closing) return;
                if (logoutPending) {
                    if (policy.isLogin(url)) completeLogout();
                    else submitLogout();
                    return;
                }
                if (initialAuthCheck && !errorShown) {
                    if (policy.isLogin(url)) return; // wait for the real server login form
                    initialAuthCheck = false;
                    load(ENTRY);
                    return;
                }
                address.setText(url);
                notice.setText(policy.isLogin(url) ? "Server sign-in is required." : "Connected to the trusted server.");
                if (!errorShown) hideError();
            }
            @Override public void onReceivedError(WebView parent, WebResourceRequest request, WebResourceError error) {
                if (!closing && request.isForMainFrame()) {
                    showError("The trusted server is unavailable or the page could not be loaded.");
                }
            }
            @Override public void onReceivedSslError(WebView parent, SslErrorHandler handler, SslError error) {
                // The only safe response: never override WebView certificate validation.
                handler.cancel();
                if (!closing) showError("TLS certificate rejected. Administration stays disabled; no trust override is permitted.");
            }
            @Override public void onReceivedHttpAuthRequest(WebView parent, HttpAuthHandler handler, String host, String realm) {
                handler.cancel();
                if (!closing) showError("HTTP authentication is not supported for administration.");
            }
            @Override public void onReceivedClientCertRequest(WebView parent, ClientCertRequest request) {
                request.cancel();
            }
            @Override public boolean onRenderProcessGone(WebView parent, RenderProcessGoneDetail detail) {
                if (!closing) showError("The browser process stopped. Retry or exit; saved display content is unaffected.");
                return true;
            }
        });
    }

    private boolean blockForeign(String url, boolean mainFrame) {
        if (closing) return true;
        if (policy.navigation(url)) return false;
        blocked++;
        if (mainFrame) flash("Navigation outside the trusted server was blocked.");
        return true;
    }

    private void flash(String text) {
        if (notice != null) notice.setText(text);
    }

    private void confirmLogout() {
        if (logoutPending || closing) return;
        new AlertDialog.Builder(this)
            .setTitle("Sign out of administration")
            .setMessage("End the server administration session and clear the local WebView cookies and page history?")
            .setNegativeButton("Cancel", null)
            .setPositiveButton("Sign out", (dialog, which) -> beginLogout())
            .show();
    }

    private void beginLogout() {
        if (logoutPending || closing) return;
        logoutPending = true;
        logoutSubmits = 0;
        signOut.setEnabled(false);
        notice.setText("Signing out...");
        hideError();
        String current = browser == null ? "" : browser.getUrl();
        if (policy.isLogin(current)) {
            completeLogout();
            return;
        }
        String path = policy.path(current);
        if ("/admin".equals(path) || "/admin/".equals(path)) {
            submitLogout();
        } else {
            load(HOME);
        }
    }

    private void submitLogout() {
        if (!logoutPending || closing || browser == null) return;
        logoutSubmits++;
        browser.evaluateJavascript(LOGOUT_JS, value -> {
            if (!logoutPending || closing) return;
            if ("true".equals(value)) return; // the existing page form is posting to /admin/logout
            if (logoutSubmits < 2) {
                load(HOME);
            } else {
                logoutPending = false;
                signOut.setEnabled(true);
                showError("Server sign-out did not complete; the session may still be active. Retry or exit.");
            }
        });
    }

    private void completeLogout() {
        if (closing) return;
        closing = true;
        notice.setText("Signed out. Cookies, form data and WebView history cleared.");
        CookieManager cookies = CookieManager.getInstance();
        cookies.removeAllCookies(value -> ui.post(this::finishSafely));
        cookies.flush();
        try {
            WebStorage.getInstance().deleteAllData();
        } catch (RuntimeException ignored) {
            // Storage is already isolated to this process; cookie removal still applies.
        }
        try {
            WebViewDatabase.getInstance(this).clearFormData();
            WebViewDatabase.getInstance(this).clearHttpAuthUsernamePassword();
        } catch (RuntimeException ignored) {
            // No saved credentials are used by this activity.
        }
        if (browser != null) {
            browser.stopLoading();
            browser.clearHistory();
            browser.clearCache(true);
            browser.loadUrl("about:blank");
        }
        // Cookie deletion is asynchronous; do not leave the authenticated page reachable.
        ui.postDelayed(this::finishSafely, 1500);
    }

    private void finishSafely() {
        if (!isFinishing()) finish();
    }

    private void showError(String text) {
        errorShown = true;
        if (errorText != null) errorText.setText(text + "\n\n" + origin);
        if (errorPanel != null) errorPanel.setVisibility(View.VISIBLE);
        if (signOut != null) signOut.setEnabled(false);
        if (browser != null) browser.stopLoading();
    }

    private void hideError() {
        errorShown = false;
        if (errorPanel != null) errorPanel.setVisibility(View.GONE);
        if (signOut != null) signOut.setEnabled(true);
    }

    @Override protected void onResume() {
        super.onResume();
        if (browser != null) browser.onResume();
    }

    @Override protected void onPause() {
        if (browser != null) browser.onPause();
        super.onPause();
    }

    @Override public void onBackPressed() {
        if (logoutPending || closing) return;
        if (browser != null && browser.canGoBack()) {
            browser.goBack();
            return;
        }
        super.onBackPressed();
    }

    @Override protected void onDestroy() {
        closing = true;
        worker.shutdownNow();
        if (browser != null) {
            ViewParent parent = browser.getParent();
            if (parent instanceof ViewGroup) ((ViewGroup) parent).removeView(browser);
            browser.stopLoading();
            browser.destroy();
            browser = null;
        }
        super.onDestroy();
    }
}
