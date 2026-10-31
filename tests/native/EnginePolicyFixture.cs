using System;
using System.Collections.Generic;
using System.IO;
using System.Threading.Tasks;
using System.Web.Script.Serialization;
using System.Windows.Forms;
using Microsoft.Web.WebView2.Core;

// Separate test host references the shipped assembly; no product test bridge or flags.
public sealed class EnginePolicyFixture : Form {
    readonly string root;
    readonly LocalView view;
    readonly List<object> cases = new List<object>();
    readonly Timer deadline = new Timer { Interval = 75000 };
    PreparedView prepared;
    int blocked, allowed, denied;
    bool completed;
    public bool Passed { get; private set; }

    EnginePolicyFixture(string root, string viewPath) {
        this.root = root;
        view = new LocalView(viewPath);
        Text = "Kiosk engine policy fixture"; Width = 960; Height = 640;
        deadline.Tick += (s, e) => { Finish(false, "fixture_timeout"); Close(); };
        FormClosed += (s, e) => {
            if (!completed) Finish(false, "fixture_closed");
            deadline.Dispose();
            if (prepared != null) prepared.Dispose();
        };
        Shown += async (s, e) => await Run();
    }
    void Record(string name, bool pass) {
        cases.Add(new { name = name, pass = pass });
        if (!pass) throw new InvalidDataException(name);
    }
    void Finish(bool pass, string error) {
        if (completed) return;
        completed = true; Passed = pass; deadline.Stop();
        var report = new { result = pass ? "PASS" : "FAIL", code = error,
            process_id = System.Diagnostics.Process.GetCurrentProcess().Id,
            runtime = prepared == null || prepared.Browser.CoreWebView2 == null ? "" : prepared.Browser.CoreWebView2.Environment.BrowserVersionString,
            cases = cases, blocked_navigation = blocked, allowed_resources = allowed, denied_resources = denied };
        File.WriteAllText(Path.Combine(root, "engine-policy-result.json"), new JavaScriptSerializer().Serialize(report));
    }
    async Task<bool> Wait(Task<bool> task) {
        return await Task.WhenAny(task, Task.Delay(3000)) == task && await task;
    }
    async Task<bool> Intact() {
        var core = prepared.Browser.CoreWebView2;
        return core.Source == LocalView.Origin + "/index.html" && await core.ExecuteScriptAsync(
            "(() => { const n=document.getElementById('counter'); return !!n && /^\\d{1,5} \\/ \\d{1,5}$/.test(n.textContent); })()") == "true";
    }
    async Task Navigation(string name, string address, bool anchor) {
        var core = prepared.Browser.CoreWebView2;
        var observed = new TaskCompletionSource<bool>();
        EventHandler<CoreWebView2NavigationStartingEventArgs> handler = (s, e) => observed.TrySetResult(e.Cancel);
        core.NavigationStarting += handler;
        try {
            if (anchor) await core.ExecuteScriptAsync("(() => {const a=document.createElement('a'); a.href=" +
                new JavaScriptSerializer().Serialize(address) + "; document.body.appendChild(a); a.click(); a.remove();})()");
            else core.Navigate(address);
            Record(name, await Wait(observed.Task));
            await Task.Delay(100);
            Record(name + "_retained", await Intact());
        } finally { core.NavigationStarting -= handler; }
    }
    async Task Run() {
        deadline.Start();
        try {
            var environment = await CoreWebView2Environment.CreateAsync(null, Path.Combine(root, "profile"));
            prepared = new PreparedView(view); prepared.Browser.Dock = DockStyle.Fill;
            Controls.Add(prepared.Browser);
            Record("initial_ready", await prepared.Initialize(environment,
                ok => { if (ok) allowed++; else denied++; }, () => blocked++));
            var core = prepared.Browser.CoreWebView2;
            Record("bridges_and_debug_disabled", !core.Settings.AreHostObjectsAllowed && !core.Settings.IsWebMessageEnabled &&
                !core.Settings.AreDevToolsEnabled && !core.Settings.AreBrowserAcceleratorKeysEnabled &&
                !core.Settings.AreDefaultContextMenusEnabled && !core.Settings.AreDefaultScriptDialogsEnabled);
            await Navigation("https_external", "https://example.invalid/kiosk-test", false);
            await Navigation("http_external", "http://example.invalid/kiosk-test", false);
            await Navigation("file_external", new Uri(Path.Combine(root, "synthetic.txt")).AbsoluteUri, false);
            await Navigation("data_external", "data:text/html,synthetic", false);
            await Navigation("local_query", LocalView.Origin + "/index.html?synthetic=1", false);
            await Navigation("local_wrong_port", "https://kiosk.invalid:444/index.html", false);
            await Navigation("anchor_external", "https://example.invalid/kiosk-anchor", true);

            var popup = new TaskCompletionSource<bool>();
            core.NewWindowRequested += (s, e) => popup.TrySetResult(e.Handled);
            await core.ExecuteScriptAsync("window.open('https://example.invalid/kiosk-popup','_blank')");
            Record("new_window_handled", await Wait(popup.Task));
            Record("new_window_retained", await Intact());

            // Native-injected probes exercise the real engine without accepting package code.
            await core.ExecuteScriptAsync(@"window.__fixture={frame:0,connect:0,image:0,fetchDenied:false};
                document.addEventListener('securitypolicyviolation',e=>{
                    if(e.effectiveDirective==='frame-src')window.__fixture.frame++;
                    if(e.effectiveDirective==='connect-src')window.__fixture.connect++;
                    if(e.effectiveDirective==='img-src')window.__fixture.image++;
                });
                const f=document.createElement('iframe');f.src='https://example.invalid/kiosk-frame';document.body.appendChild(f);
                const i=document.createElement('img');i.src='https://example.invalid/kiosk-image';document.body.appendChild(i);
                fetch('https://example.invalid/kiosk-fetch').catch(()=>window.__fixture.fetchDenied=true);");
            await Task.Delay(500);
            Record("csp_frame_denied", await core.ExecuteScriptAsync("window.__fixture.frame>0") == "true");
            Record("csp_image_denied", await core.ExecuteScriptAsync("window.__fixture.image>0") == "true");
            Record("csp_connect_denied", await core.ExecuteScriptAsync("window.__fixture.connect>0 && window.__fixture.fetchDenied") == "true");

            var unknown = new TaskCompletionSource<bool>();
            core.WebResourceResponseReceived += (s, e) => {
                if (e.Request.Uri == LocalView.Origin + "/synthetic-unlisted.png") unknown.TrySetResult(e.Response.StatusCode == 403);
            };
            await core.ExecuteScriptAsync("(()=>{const i=document.createElement('img');i.src='/synthetic-unlisted.png';document.body.appendChild(i)})()");
            Record("unlisted_resource_403", await Wait(unknown.Task));

            var download = new TaskCompletionSource<bool>();
            core.DownloadStarting += (s, e) => download.TrySetResult(e.Cancel);
            await core.ExecuteScriptAsync(@"(()=>{const a=document.createElement('a');
                a.href=URL.createObjectURL(new Blob(['synthetic'],{type:'application/octet-stream'}));
                a.download='kiosk-synthetic.bin';document.body.appendChild(a);a.click();a.remove()})()");
            Record("download_cancelled", await Wait(download.Task));
            var permission = new TaskCompletionSource<bool>();
            core.PermissionRequested += (s, e) => permission.TrySetResult(
                e.PermissionKind == CoreWebView2PermissionKind.Geolocation && e.State == CoreWebView2PermissionState.Deny);
            await core.ExecuteScriptAsync("navigator.geolocation.getCurrentPosition(()=>{},()=>{}, {timeout:2000})");
            Record("geolocation_permission_denied", await Wait(permission.Task));
            Record("final_view_retained", await Intact());
            Finish(true, "");
        } catch { Finish(false, "engine_policy_failed"); }
        Close();
    }
    [STAThread]
    public static int Main(string[] args) {
        if (args.Length != 2) return 2;
        try {
            string root = LocalView.PlainDirectory(args[0]);
            Directory.CreateDirectory(root);
            if (Directory.Exists(Path.Combine(root, "profile")) || File.Exists(Path.Combine(root, "engine-policy-result.json"))) return 2;
            Application.EnableVisualStyles(); Application.SetCompatibleTextRenderingDefault(false);
            using (var window = new EnginePolicyFixture(root, args[1])) {
                Application.Run(window); return window.Passed ? 0 : 1;
            }
        } catch { return 1; }
    }
}
