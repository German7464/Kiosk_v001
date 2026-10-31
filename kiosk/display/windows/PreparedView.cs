using System;
using System.IO;
using System.Threading.Tasks;
using Microsoft.Web.WebView2.Core;
using Microsoft.Web.WebView2.WinForms;

// One isolated WebView resource map per candidate; never mix active and staged files.
public sealed class PreparedView : IDisposable {
    public readonly WebView2 Browser = new WebView2();
    public readonly LocalView View;
    readonly TaskCompletionSource<bool> ready = new TaskCompletionSource<bool>();
    public event Action<PreparedView> Failed;
    bool disposed;
    public PreparedView(LocalView view) { View = view; }
    public async Task<bool> Initialize(CoreWebView2Environment environment, Action<bool> resource, Action blocked) {
        var work = InitializeCore(environment, resource, blocked);
        var result = await Task.WhenAny(work, Task.Delay(15000));
        return result == work && await work;
    }
    async Task<bool> InitializeCore(CoreWebView2Environment environment, Action<bool> resource, Action blocked) {
        try {
            await Browser.EnsureCoreWebView2Async(environment);
            if (disposed) return false;
            var core = Browser.CoreWebView2;
            core.Settings.AreHostObjectsAllowed = false;
            core.Settings.IsWebMessageEnabled = false;
            core.Settings.AreDefaultScriptDialogsEnabled = false;
            core.Settings.AreDefaultContextMenusEnabled = false;
            core.Settings.AreDevToolsEnabled = false;
            core.Settings.AreBrowserAcceleratorKeysEnabled = false;
            core.NavigationStarting += (s, e) => {
                e.Cancel = View.AllowedPath(e.Uri, "GET") != "index.html";
                if (e.Cancel) blocked();
            };
            core.NavigationCompleted += async (s, e) => {
                try {
                    bool valid = e.IsSuccess && await core.ExecuteScriptAsync(
                        "(() => { const n = document.getElementById('counter'); return !!n && /^\\d{1,5} \\/ \\d{1,5}$/.test(n.textContent); })()") == "true";
                    ready.TrySetResult(valid && !disposed);
                } catch { ready.TrySetResult(false); }
            };
            core.ProcessFailed += (s, e) => {
                ready.TrySetResult(false);
                if (!disposed && Failed != null) Failed(this);
            };
            core.FrameNavigationStarting += (s, e) => e.Cancel = true;
            core.NewWindowRequested += (s, e) => e.Handled = true;
            core.DownloadStarting += (s, e) => e.Cancel = true;
            core.PermissionRequested += (s, e) => e.State = CoreWebView2PermissionState.Deny;
            core.AddWebResourceRequestedFilter("*", CoreWebView2WebResourceContext.All);
            core.WebResourceRequested += (s, e) => {
                string path = View.AllowedPath(e.Request.Uri, e.Request.Method);
                try {
                    if (path == null) throw new InvalidDataException("request_denied");
                    e.Response = environment.CreateWebResourceResponse(new MemoryStream(View.Read(path)), 200, "OK",
                        "Content-Type: " + LocalView.Mime(path) + "\r\nCache-Control: no-store\r\nX-Content-Type-Options: nosniff\r\n" +
                        "Content-Security-Policy: default-src 'none'; script-src 'self'; style-src 'self'; img-src 'self'; connect-src 'none'; frame-src 'none'; object-src 'none'; base-uri 'none'; form-action 'none'\r\n");
                    resource(true);
                } catch {
                    e.Response = environment.CreateWebResourceResponse(new MemoryStream(new byte[0]), 403, "Forbidden", "Cache-Control: no-store\r\n");
                    resource(false);
                }
            };
            core.Navigate(LocalView.Origin + "/index.html");
            return await ready.Task && !disposed;
        } catch { return false; }
    }
    public void Dispose() {
        if (disposed) return;
        disposed = true;
        ready.TrySetResult(false);
        Browser.Dispose();
    }
}
