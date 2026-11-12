using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.IO;
using System.Text;
using System.Threading;
using System.Threading.Tasks;
using System.Web.Script.Serialization;
using System.Windows.Forms;
using Microsoft.Web.WebView2.Core;
using Microsoft.Web.WebView2.WinForms;

// In-app administration for the existing Windows connection application.
//
// The accepted native shell hosts the ordinary server-rendered admin HTML/CSS/JS
// in a dedicated WebView2 environment (its own user-data folder). The TV/Kiosk
// display shell is a different executable mode with a different profile, so
// display cookies/storage and administrative cookies/storage never mix.
//
// Trust rules:
//  * only the exact verified HTTPS origin supplied by the connection UI is
//    accepted; document, frame and subresource requests are restricted to it;
//  * the WebView2/Chromium network stack performs the real chain, hostname and
//    expiry validation against the Windows certificate store;
//  * certificate errors are observed and cancelled, never allowed;
//  * no password is read, stored, injected or autofilled by native code.
public sealed class AdminWindow : Form {
    public const int ExitPolicy = 2, ExitStorage = 3, ExitBusy = 4;
    const string ProfileOwner = "KioskAdminWebView/v1\n";
    const int StartupTimeoutMs = 15000;

    readonly Uri origin;
    readonly string profile, browserDirectory, displayProfile, statusPath;
    readonly int diagnosticPort;
    readonly string diagnosticHostMap;
    readonly WebView2 browser = new WebView2 { Dock = DockStyle.Fill };
    readonly Panel banner = new Panel { Dock = DockStyle.Top, Height = 52, Visible = false };
    readonly Label bannerText = new Label { Dock = DockStyle.Fill, TextAlign = System.Drawing.ContentAlignment.MiddleLeft, Padding = new Padding(8, 0, 8, 0) };
    readonly Button retryButton = new Button { Text = "Повторить", Dock = DockStyle.Right, Width = 120 };
    readonly Label originLabel = new Label { AutoSize = true, TextAlign = System.Drawing.ContentAlignment.MiddleLeft, Padding = new Padding(8, 9, 8, 0) };
    readonly Button backButton = new Button { Text = "Назад", Width = 92, Enabled = false };
    readonly Button reloadButton = new Button { Text = "Обновить", Width = 104, Enabled = false };
    readonly Button homeButton = new Button { Text = "Главная", Width = 104, Enabled = false };
    CoreWebView2Environment environment;
    CoreWebView2 core;
    FileStream lease;
    bool closing, startupFailed, securityObserver, clearing, browserExited, certificateFailed;
    int blockedNavigation, blockedRequests, blockedFrames, blockedNewWindows, blockedDownloads, deniedPermissions;
    int tlsErrors, retries;
    string state = "starting", lastUriPath = "", lastWebError = "", lastTlsError = "", lastTlsPath = "";
    string tlsProtocol = "", tlsCipher = "", tlsSubject = "", tlsIssuer = "", tlsValidTo = "";
    string failure = "", cleanup = "not_attempted";
    bool logoutPosted, logoutSeen, logoutCleared;
    long browserProcessId;
    readonly string startedAt = DateTime.UtcNow.ToString("o");
    readonly string cleanupMarker;

    public bool StartupFailed { get { return startupFailed; } }

    // Exact origin only: absolute https, explicit host, no credentials, path must
    // be "/" (or empty), no query and no fragment. The connection UI passes only
    // the origin that came from the already verified saved anchor.
    public static Uri ParseOrigin(string value) {
        Uri uri;
        if (String.IsNullOrEmpty(value) || !Uri.TryCreate(value, UriKind.Absolute, out uri)) return null;
        if (uri.Scheme != Uri.UriSchemeHttps) return null;
        if (uri.UserInfo.Length != 0 || uri.Query.Length != 0 || uri.Fragment.Length != 0) return null;
        if (uri.AbsolutePath != "/") return null;
        if (String.IsNullOrEmpty(uri.Host) || uri.HostNameType == UriHostNameType.Unknown) return null;
        foreach (char item in uri.Host) if (item > 127) return null;
        return uri;
    }

    public static bool SameOrigin(Uri expected, string value) {
        Uri uri;
        if (!Uri.TryCreate(value, UriKind.Absolute, out uri)) return false;
        if (uri.Scheme != Uri.UriSchemeHttps || uri.UserInfo.Length != 0) return false;
        return String.Equals(uri.Host, expected.Host, StringComparison.OrdinalIgnoreCase) && uri.Port == expected.Port;
    }

    static bool Internal(string value) {
        return value == "about:blank" ||
            value.StartsWith("data:", StringComparison.OrdinalIgnoreCase) ||
            value.StartsWith("blob:", StringComparison.OrdinalIgnoreCase) ||
            value.StartsWith("about:", StringComparison.OrdinalIgnoreCase);
    }

    // The administration root must be a standalone local directory, not inside
    // the display/native roots and not containing them.
    public static string ValidateProfiles(string profileValue, string displayValue) {
        string admin = RuntimeStorage.CheckRoot(profileValue).TrimEnd(Path.DirectorySeparatorChar);
        string display = LocalView.PlainDirectory(displayValue).TrimEnd(Path.DirectorySeparatorChar);
        RuntimeStorage.Separate(admin, display);
        return admin;
    }

    static void PrepareProfile(string root) {
        string marker = Path.Combine(root, "owner");
        if ((Directory.Exists(marker) || File.Exists(marker)) &&
            (File.GetAttributes(marker) & FileAttributes.ReparsePoint) != 0)
            throw new InvalidDataException("admin_profile_unowned");
        if (File.Exists(marker)) {
            if (new FileInfo(marker).Length != ProfileOwner.Length || File.ReadAllText(marker, Encoding.ASCII) != ProfileOwner)
                throw new InvalidDataException("admin_profile_unowned");
            return;
        }
        if (Directory.GetFileSystemEntries(root).Length != 0)
            throw new InvalidDataException("admin_profile_unowned");
        File.WriteAllText(marker, ProfileOwner, Encoding.ASCII);
    }

    public AdminWindow(Uri verifiedOrigin, string profileRoot, string displayRoot, int diagnosticPortValue, string diagnosticHostMapValue) {
        origin = verifiedOrigin; profile = profileRoot; displayProfile = displayRoot;
        diagnosticPort = diagnosticPortValue; diagnosticHostMap = diagnosticHostMapValue ?? "";
        statusPath = Path.Combine(profile, "admin-status.json");
        browserDirectory = Path.Combine(profile, "browser");
        cleanupMarker = Path.Combine(profile, "cleanup-required");
        PrepareProfile(profile);
        // One window per administration profile; the OS releases the lease on exit.
        lease = new FileStream(Path.Combine(profile, "admin.lock"), FileMode.OpenOrCreate,
                               FileAccess.ReadWrite, FileShare.None);
        // A previous close could not delete the browser data while runtime files
        // were still mapped. No browser is running now, so finish that cleanup
        // before a new environment (and a new login) can start.
        if (File.Exists(cleanupMarker)) {
            try {
                if (Directory.Exists(browserDirectory)) Directory.Delete(browserDirectory, true);
                File.Delete(cleanupMarker);
                cleanup = "profile_data_deleted_on_start";
            } catch { cleanup = "profile_data_cleanup_pending"; }
        }
        Text = "Kiosk — администрирование";
        Width = 1180; Height = 820;
        MinimumSize = new System.Drawing.Size(760, 520);
        StartPosition = FormStartPosition.CenterScreen;
        Controls.Add(browser);
        banner.Controls.Add(bannerText);
        banner.Controls.Add(retryButton);
        Controls.Add(banner);
        var bar = new FlowLayoutPanel { Dock = DockStyle.Top, Height = 42, WrapContents = false, FlowDirection = FlowDirection.LeftToRight };
        bar.Controls.Add(backButton); bar.Controls.Add(reloadButton); bar.Controls.Add(homeButton); bar.Controls.Add(originLabel);
        Controls.Add(bar);
        originLabel.Text = origin.GetComponents(UriComponents.SchemeAndServer, UriFormat.UriEscaped);
        backButton.Click += (s, e) => { if (core != null && core.CanGoBack) core.GoBack(); };
        reloadButton.Click += (s, e) => { if (core != null) core.Reload(); };
        homeButton.Click += (s, e) => { if (core != null) core.Navigate(origin.AbsoluteUri + "admin"); };
        retryButton.Click += (s, e) => { retries++; Retry(); };
        Shown += async (s, e) => { await Start(); };
        FormClosing += (s, e) => {
            closing = true;
            // If the process exits before the profile can be removed, the next
            // launch must delete it before creating a new environment.
            try { File.WriteAllText(cleanupMarker, "pending"); } catch { }
        };
        FormClosed += (s, e) => {
            try { if (core != null) core.CookieManager.DeleteAllCookies(); } catch { }
            try { if (browser != null) browser.Dispose(); } catch { }
            try { if (lease != null) lease.Dispose(); } catch { }
            lease = null;
            state = "closed"; Status();
        };
    }

    static string PathOnly(string value) {
        Uri uri;
        if (!Uri.TryCreate(value, UriKind.Absolute, out uri)) return "";
        return uri.AbsolutePath;
    }

    void Report(string stateValue) {
        string temporary = Path.Combine(profile, ".admin-status-" + Guid.NewGuid().ToString("N"));
        bool canGoBack = false;
        try { canGoBack = core != null && core.CanGoBack; } catch { }
        try {
            var report = new {
                schema = "kiosk-windows-admin-webview-v1", state = stateValue,
                origin = origin.GetComponents(UriComponents.SchemeAndServer, UriFormat.UriEscaped),
                runtime_version = environment == null ? "" : environment.BrowserVersionString,
                profile = profile, browser_directory = browserDirectory, display_profile = displayProfile,
                isolated_profile = true, autofill_disabled = true, password_autosave = false,
                host_objects = false, web_messages = false, devtools = false,
                diagnostic_port = diagnosticPort, diagnostic_host_map = diagnosticHostMap,
                blocked_navigation = blockedNavigation, blocked_requests = blockedRequests,
                blocked_frames = blockedFrames, blocked_new_windows = blockedNewWindows,
                blocked_downloads = blockedDownloads, denied_permissions = deniedPermissions,
                tls_errors = tlsErrors, last_tls_error = lastTlsError, last_tls_path = lastTlsPath,
                certificate_failed = certificateFailed,
                last_web_error = lastWebError, last_uri_path = lastUriPath, retry_count = retries,
                logout_posted = logoutSeen, logout_cleared = logoutCleared,
                can_go_back = canGoBack,
                security_observer = securityObserver, tls_protocol = tlsProtocol, tls_cipher = tlsCipher,
                tls_subject = tlsSubject, tls_issuer = tlsIssuer, tls_valid_to = tlsValidTo,
                process_id = Process.GetCurrentProcess().Id, browser_process_id = browserProcessId,
                started_at = startedAt, closed_at = closing ? DateTime.UtcNow.ToString("o") : "",
                cleanup = cleanup, failure = failure
            };
            byte[] bytes = Encoding.UTF8.GetBytes(new JavaScriptSerializer().Serialize(report));
            using (var output = new FileStream(temporary, FileMode.CreateNew, FileAccess.Write, FileShare.None)) {
                output.Write(bytes, 0, bytes.Length); output.Flush(true);
            }
            if (File.Exists(statusPath)) File.Replace(temporary, statusPath, null); else File.Move(temporary, statusPath);
        } catch { }
        finally { try { if (File.Exists(temporary)) File.Delete(temporary); } catch { } }
    }

    void Status() { Report(state); }

    void ShowBanner(string message, bool retry) {
        bannerText.Text = message;
        retryButton.Visible = retry;
        banner.Visible = true;
    }

    void Retry() {
        string target = lastUriPath.Length != 0 && lastWebError.Length != 0 ? origin.AbsoluteUri.TrimEnd('/') + lastUriPath
                                                                          : origin.AbsoluteUri + "admin/devices/pair";
        banner.Visible = false; lastWebError = ""; state = "retrying"; Status();
        if (core != null) core.Navigate(target);
    }

    static string FailureMessage(object code, bool tls) {
        if (tls) return "TLS-сертификат сервера отклонён. Проверьте установку доверенного CA и имя сервера; обход проверки не выполняется.";
        if (code == null) return "Страница не загрузилась. Проверьте сеть и повторите.";
        var name = code.ToString();
        if (name == "ConnectionRefused" || name == "ConnectionAborted" || name == "ConnectionReset" ||
            name == "Timeout" || name == "HostNameNotResolved" || name == "CannotConnect" ||
            name == "ServerUnreachable" || name == "NetworkConnectionLost")
            return "Сервер недоступен. Проверьте сеть и адрес, затем нажмите «Повторить».";
        if (name.StartsWith("Certificate", StringComparison.Ordinal))
            return "TLS-сертификат сервера отклонён. Проверьте установку доверенного CA и имя сервера; обход проверки не выполняется.";
        return "Страница не загрузилась (" + name + "). Проверьте адрес и повторите.";
    }

    async Task Start() {
        var work = StartCore();
        var finished = await Task.WhenAny(work, Task.Delay(StartupTimeoutMs));
        if (finished != work) { failure = "startup_timeout"; Fatal(); return; }
        if (!await work) { Fatal(); return; }
    }

    void Fatal() {
        if (closing || startupFailed) return;
        startupFailed = true;
        state = "startup_failed";
        if (failure.Length == 0) failure = "webview_startup_failed";
        ShowBanner("Не удалось открыть встроенное администрирование. Проверьте WebView2 Runtime и повторите.", false);
        Status();
    }

    async Task<bool> StartCore() {
        try {
            var options = new CoreWebView2EnvironmentOptions();
            options.ExclusiveUserDataFolderAccess = true;
            // Diagnostic launch only (never passed by the control window): a
            // loopback DevTools endpoint used by the acceptance harness. The
            // page still cannot reach it and no certificate rule changes.
            if (diagnosticPort != 0) {
                string arguments = "--remote-debugging-port=" + diagnosticPort;
                // Test-only, explicitly supplied resolver mapping; used to prove
                // that the real WebView rejects a name the certificate lacks.
                if (diagnosticHostMap.Length != 0)
                    arguments += " --host-resolver-rules=\"MAP " + diagnosticHostMap + "\"";
                options.AdditionalBrowserArguments = arguments;
            }
            environment = await CoreWebView2Environment.CreateAsync(null, browserDirectory, options);
            if (!String.Equals(Path.GetFullPath(environment.UserDataFolder), Path.GetFullPath(browserDirectory),
                               StringComparison.OrdinalIgnoreCase))
                throw new InvalidDataException("unexpected_runtime_directory");
            environment.BrowserProcessExited += (s, e) => { browserExited = true; Status(); };
            await browser.EnsureCoreWebView2Async(environment);
            if (closing) return false;
            core = browser.CoreWebView2;
            browserProcessId = core.BrowserProcessId;

            // No native bridge, no script dialogs, no devtools, no downloads/popups.
            core.Settings.AreHostObjectsAllowed = false;
            core.Settings.IsWebMessageEnabled = false;
            core.Settings.AreDevToolsEnabled = false;
            core.Settings.AreDefaultScriptDialogsEnabled = false;
            core.Settings.AreDefaultContextMenusEnabled = false;
            core.Settings.AreBrowserAcceleratorKeysEnabled = false;
            core.Settings.IsPasswordAutosaveEnabled = false;   // never save admin credentials
            core.Settings.IsGeneralAutofillEnabled = false;
            core.Settings.IsStatusBarEnabled = false;
            core.Settings.IsZoomControlEnabled = false;
            core.Settings.IsBuiltInErrorPageEnabled = true;

            core.NavigationStarting += (s, e) => {
                lastUriPath = PathOnly(e.Uri);
                if (!Internal(e.Uri) && !SameOrigin(origin, e.Uri)) {
                    e.Cancel = true; blockedNavigation++;
                    state = "foreign_navigation_refused"; Status();
                }
            };
            core.FrameNavigationStarting += (s, e) => {
                if (!Internal(e.Uri) && !SameOrigin(origin, e.Uri)) { e.Cancel = true; blockedFrames++; Status(); }
            };
            core.NavigationCompleted += (s, e) => {
                if (e.IsSuccess) {
                    state = "ready"; lastWebError = ""; banner.Visible = false; certificateFailed = false;
                    backButton.Enabled = core.CanGoBack; reloadButton.Enabled = true; homeButton.Enabled = true;
                } else {
                    lastWebError = e.WebErrorStatus.ToString();
                    state = "navigation_failed";
                    ShowBanner(FailureMessage(e.WebErrorStatus,
                        certificateFailed || lastWebError.StartsWith("Certificate")), true);
                    reloadButton.Enabled = true; homeButton.Enabled = true;
                }
                Status();
                if (logoutPosted && !clearing) { logoutPosted = false; ClearAfterLogout(); }
            };
            core.NewWindowRequested += (s, e) => { e.Handled = true; blockedNewWindows++; Status(); };
            core.DownloadStarting += (s, e) => { e.Cancel = true; blockedDownloads++; Status(); };
            core.PermissionRequested += (s, e) => { e.State = CoreWebView2PermissionState.Deny; deniedPermissions++; Status(); };
            core.ServerCertificateErrorDetected += (s, e) => {
                tlsErrors++; lastTlsError = e.ErrorStatus.ToString(); lastTlsPath = PathOnly(e.RequestUri);
                var certificate = e.ServerCertificate;
                if (certificate != null) {
                    tlsSubject = certificate.Subject ?? ""; tlsIssuer = certificate.Issuer ?? "";
                    tlsValidTo = certificate.ValidTo.ToUniversalTime().ToString("yyyy-MM-ddTHH:mm:ssZ");
                }
                // The real WebView connection must fail closed; never allow here.
                e.Action = CoreWebView2ServerCertificateErrorAction.Cancel;
                certificateFailed = true;
                state = "certificate_refused";
                ShowBanner(FailureMessage(e.ErrorStatus.ToString(), true), false);
                Status();
            };
            core.AddWebResourceRequestedFilter("*", CoreWebView2WebResourceContext.All);
            core.WebResourceRequested += (s, e) => {
                try {
                    Uri uri;
                    string address = e.Request.Uri;
                    if (!Uri.TryCreate(address, UriKind.Absolute, out uri)) { Deny(e); return; }
                    if (Internal(address)) return;
                    if (!SameOrigin(origin, address)) { Deny(e); return; }
                    if (String.Equals(e.Request.Method, "POST", StringComparison.OrdinalIgnoreCase) &&
                        uri.AbsolutePath == "/admin/logout") { logoutPosted = true; logoutSeen = true; }
                } catch { Deny(e); }
            };
            core.ProcessFailed += (s, e) => {
                state = "renderer_failed"; failure = "renderer_failed";
                ShowBanner("Встроенный просмотр остановился. Закройте и откройте администрирование снова.", false);
                Status();
            };
            await ObserveSecurity();
            state = "navigating"; Status();
            core.Navigate(origin.AbsoluteUri + "admin/devices/pair");
            return true;
        } catch (InvalidDataException) { failure = "profile_or_runtime_refused"; return false; }
        catch { failure = "webview_startup_failed"; return false; }
    }

    void Deny(CoreWebView2WebResourceRequestedEventArgs e) {
        blockedRequests++;
        e.Response = environment.CreateWebResourceResponse(new MemoryStream(new byte[0]), 403, "Forbidden",
            "Cache-Control: no-store\r\nX-Content-Type-Options: nosniff\r\n");
        Status();
    }

    // Evidence/diagnostics only: read the certificate facts Chromium actually used
    // for the main document. This does not alter validation or trust.
    async Task ObserveSecurity() {
        try {
            var receiver = core.GetDevToolsProtocolEventReceiver("Network.responseReceived");
            receiver.DevToolsProtocolEventReceived += (s, e) => {
                try {
                    var serializer = new JavaScriptSerializer { MaxJsonLength = 262144, RecursionLimit = 32 };
                    var message = serializer.Deserialize<Dictionary<string, object>>(e.ParameterObjectAsJson);
                    if (message == null) return;
                    // The receiver delivers the event parameters object; tolerate a
                    // full {"params":{...}} envelope as well.
                    var parameters = message;
                    if (message.ContainsKey("params") && message["params"] is Dictionary<string, object>)
                        parameters = (Dictionary<string, object>)message["params"];
                    if (!"Document".Equals(parameters.ContainsKey("type") ? parameters["type"] as string : null)) return;
                    var response = parameters.ContainsKey("response") ? parameters["response"] as Dictionary<string, object> : null;
                    if (response == null || !response.ContainsKey("securityDetails")) return;
                    var details = response["securityDetails"] as Dictionary<string, object>;
                    if (details == null) return;
                    tlsProtocol = Field(details, "protocol"); tlsCipher = Field(details, "cipher");
                    tlsSubject = Field(details, "subjectName"); tlsIssuer = Field(details, "issuer");
                    tlsValidTo = Stamp(details.ContainsKey("validTo") ? details["validTo"] : null);
                    Status();
                } catch { }
            };
            await core.CallDevToolsProtocolMethodAsync("Network.enable", "{}");
            securityObserver = true;
        } catch { securityObserver = false; }
    }

    static string Field(Dictionary<string, object> value, string key) {
        object item;
        return value.TryGetValue(key, out item) && item != null ? Convert.ToString(item) : "";
    }

    static string Stamp(object value) {
        try {
            if (value == null) return "";
            double seconds = Convert.ToDouble(value);
            return DateTimeOffset.FromUnixTimeSeconds((long)seconds).UtcDateTime.ToString("yyyy-MM-ddTHH:mm:ssZ");
        } catch { return ""; }
    }

    async void ClearAfterLogout() {
        clearing = true; state = "clearing_local_session"; Status();
        try {
            // Server logout already ran through the ordinary CSRF-protected form.
            // Local cleanup: cookies, storage, cache, history, autofill/password.
            if (core != null) {
                await core.Profile.ClearBrowsingDataAsync(CoreWebView2BrowsingDataKinds.AllProfile);
                core.CookieManager.DeleteAllCookies();
                await core.CallDevToolsProtocolMethodAsync("Page.resetNavigationHistory", "{}");
            }
            logoutCleared = true;
        } catch { logoutCleared = false; }
        clearing = false;
        state = "logged_out";
        if (!closing) {
            ShowBanner("Вы вышли. Локальные cookie, хранилище и история администрирования очищены.", false);
            core.Navigate(origin.AbsoluteUri + "admin/login");
        }
        Status();
    }

    // Called after Application.Run when the window is closed. Deletes this task's
    // isolated WebView profile data so a new launch cannot restore a session.
    public bool FinishCleanup() {
        var released = Stopwatch.StartNew();
        while (!browserExited && released.ElapsedMilliseconds < 4000) {
            Application.DoEvents(); Thread.Sleep(50);
        }
        var wait = Stopwatch.StartNew();
        while (wait.ElapsedMilliseconds < 4000) {
            try {
                if (Directory.Exists(browserDirectory)) Directory.Delete(browserDirectory, true);
                try { File.Delete(cleanupMarker); } catch { }
                cleanup = "profile_data_deleted"; Status();
                return true;
            } catch {
                Application.DoEvents(); Thread.Sleep(200);
            }
        }
        // Runtime files may stay mapped briefly; cookies were already deleted and
        // the persisted marker deletes the whole profile before the next launch.
        cleanup = "profile_data_delete_pending_next_launch"; Status();
        return false;
    }
}
