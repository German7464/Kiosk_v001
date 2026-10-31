using System;
using System.Collections.Generic;
using System.IO;
using System.Text;
using System.Text.RegularExpressions;
using System.Threading.Tasks;
using System.Web.Script.Serialization;
using System.Windows.Forms;
using Microsoft.Web.WebView2.Core;

public sealed class DisplayWindow : Form {
    PreparedView active, pending;
    CoreWebView2Environment environment;
    readonly LocalView initial;
    readonly string profile, session, cacheRoot;
    readonly Panel surface = new Panel { Dock = DockStyle.Fill };
    readonly Timer commands = new Timer { Interval = 500 };
    readonly Timer diagnostics = new Timer { Interval = 1000 };
    bool switching, diagnosticBusy, closing;
    string requestId = "", switchState = "idle", runtimeVersion = "unavailable";
    int accepted, denied, blocked, switchesCompleted, switchesFailed;
    int diagnosticSamples, diagnosticTransitions, diagnosticFailures;
    string diagnosticCounter = "";
    public bool StartupFailed { get; private set; }

    public static bool Hex(string value, int length) {
        return value != null && Regex.IsMatch(value, "\\A[0-9a-f]{" + length + "}\\z");
    }
    void Status() {
        if (closing) return;
        string temporary = Path.Combine(profile, ".status-" + Guid.NewGuid().ToString("N"));
        try {
            var report = new { runtime_version = runtimeVersion, accepted_requests = accepted,
                denied_requests = denied, blocked_navigation = blocked, host_objects = false,
                web_messages = false, permissions = "deny", session_id = session,
                process_id = System.Diagnostics.Process.GetCurrentProcess().Id,
                navigation_success = active != null && !StartupFailed, renderer_ready = active != null && !StartupFailed,
                startup_failed = StartupFailed, view_key = active == null ? "" : active.View.Key,
                package_sha256 = active == null ? "" : active.View.PackageIdentity,
                mode = initial.Mode, switch_request_id = requestId, switch_state = switchState,
                switches_completed = switchesCompleted, switches_failed = switchesFailed,
                diagnostic_samples = diagnosticSamples, diagnostic_transitions = diagnosticTransitions,
                diagnostic_failures = diagnosticFailures, diagnostic_counter = diagnosticCounter };
            byte[] bytes = Encoding.UTF8.GetBytes(new JavaScriptSerializer().Serialize(report));
            using (var output = new FileStream(temporary, FileMode.CreateNew, FileAccess.Write, FileShare.None)) {
                output.Write(bytes, 0, bytes.Length); output.Flush(true);
            }
            string target = Path.Combine(profile, "display-status.json");
            if (File.Exists(target)) File.Replace(temporary, target, null); else File.Move(temporary, target);
        } catch { }
        finally { try { if (File.Exists(temporary)) File.Delete(temporary); } catch { } }
    }
    void Fatal() {
        if (closing || StartupFailed) return;
        StartupFailed = true; Status();
        if (session.Length != 0) Close();
        else {
            if (active != null) { active.Dispose(); active = null; }
            surface.Controls.Clear();
            surface.Controls.Add(new Label { Text = "Offline display unavailable. Check the local view and WebView2 Runtime.", Dock = DockStyle.Fill });
        }
    }
    async Task<bool> Prepare(LocalView view) {
        var candidate = new PreparedView(view);
        pending = candidate;
        candidate.Browser.Dock = DockStyle.Fill;
        surface.Controls.Add(candidate.Browser);
        if (active != null) active.Browser.BringToFront();
        candidate.Failed += item => { if (item == active) Fatal(); };
        bool ready = await candidate.Initialize(environment,
            allowed => { if (allowed) accepted++; else denied++; Status(); },
            () => { blocked++; Status(); });
        if (!ready || closing) {
            candidate.Dispose(); if (pending == candidate) pending = null; return false;
        }
        var old = active;
        candidate.Browser.BringToFront();
        active = candidate; pending = null;
        if (old != null) old.Dispose();
        return true;
    }
    async void PollCommand(object sender, EventArgs args) {
        if (switching || closing || active == null) return;
        try {
            string path = Path.Combine(profile, "display-command.json");
            if (!File.Exists(path) || (File.GetAttributes(path) & FileAttributes.ReparsePoint) != 0) return;
            byte[] payload;
            using (var input = File.OpenRead(path)) {
                if (input.Length > 4096) return;
                payload = new byte[(int)input.Length];
                int offset = 0;
                while (offset < payload.Length) {
                    int count = input.Read(payload, offset, payload.Length - offset);
                    if (count == 0) return;
                    offset += count;
                }
                if (input.ReadByte() != -1) return;
            }
            var serializer = new JavaScriptSerializer { MaxJsonLength = 4096, RecursionLimit = 8 };
            var command = serializer.Deserialize<Dictionary<string, string>>(Encoding.UTF8.GetString(payload));
            if (command == null || command.Count != 5 || !command.ContainsKey("session_id") ||
                !command.ContainsKey("request_id") || !command.ContainsKey("view") ||
                !command.ContainsKey("package_sha256") || !command.ContainsKey("mode") ||
                command["session_id"] != session || !Hex(command["request_id"], 32) ||
                command["request_id"] == requestId || !Hex(command["view"], 64) ||
                !Hex(command["package_sha256"], 64) || command["mode"] != initial.Mode) return;
            switching = true; requestId = command["request_id"]; switchState = "preparing"; Status();
            bool ready = false;
            try {
                var view = new LocalView(Path.Combine(cacheRoot, command["view"]));
                if (view.PackageIdentity != command["package_sha256"] || view.Mode != initial.Mode)
                    throw new InvalidDataException("switch_identity_mismatch");
                if (active.View.Key == view.Key && active.View.PackageIdentity == view.PackageIdentity) ready = true;
                else ready = await Prepare(view);
            } catch {
                ready = false;
                if (pending != null) { pending.Dispose(); pending = null; }
            }
            if (closing) return;
            switchState = ready ? "ready" : "failed";
            if (ready) switchesCompleted++; else switchesFailed++;
            Status();
        } catch { }
        finally { switching = false; }
    }
    void ToggleFullscreen() {
        bool fullscreen = FormBorderStyle != FormBorderStyle.None;
        FormBorderStyle = fullscreen ? FormBorderStyle.None : FormBorderStyle.Sizable;
        WindowState = fullscreen ? FormWindowState.Maximized : FormWindowState.Normal;
    }
    public DisplayWindow(LocalView view, string profile, bool diagnostic, string session, string cacheRoot) {
        initial = view; this.profile = profile; this.session = session; this.cacheRoot = cacheRoot;
        Text = "Kiosk Offline Display"; Width = 1280; Height = 800;
        Controls.Add(surface);
        var button = new Button { Text = "Full screen / Window", Dock = DockStyle.Top, Height = 32 };
        button.Click += (s, e) => ToggleFullscreen(); Controls.Add(button);
        Shown += async (s, e) => {
            Status();
            try {
                environment = await CoreWebView2Environment.CreateAsync(null, profile);
                if (closing) return;
                runtimeVersion = environment.BrowserVersionString;
                if (!await Prepare(initial)) { if (!closing) Fatal(); return; }
                Status(); if (cacheRoot.Length != 0) commands.Start(); if (diagnostic) diagnostics.Start();
            } catch { if (!closing) Fatal(); }
        };
        commands.Tick += PollCommand;
        diagnostics.Tick += async (s, e) => {
            if (closing || diagnosticBusy || active == null || diagnosticSamples >= 120) return;
            diagnosticBusy = true;
            try {
                string result = await active.Browser.CoreWebView2.ExecuteScriptAsync(
                    "(() => { const n = document.getElementById('counter'); return n && /^\\d{1,5} \\/ \\d{1,5}$/.test(n.textContent) ? n.textContent : ''; })()");
                string counter = new JavaScriptSerializer().Deserialize<string>(result);
                if (counter != null && Regex.IsMatch(counter, "\\A[0-9]{1,5} / [0-9]{1,5}\\z")) {
                    if (diagnosticCounter.Length != 0 && diagnosticCounter != counter) diagnosticTransitions++;
                    diagnosticCounter = counter;
                } else diagnosticFailures++;
            } catch { diagnosticFailures++; }
            finally { diagnosticSamples++; diagnosticBusy = false; Status(); }
            if (diagnosticSamples >= 120) diagnostics.Stop();
        };
        KeyPreview = true;
        KeyDown += (s, e) => { if (e.KeyCode == Keys.F11) { ToggleFullscreen(); e.Handled = true; } };
        FormClosed += (s, e) => {
            closing = true; commands.Dispose(); diagnostics.Dispose();
            if (pending != null) pending.Dispose(); if (active != null) active.Dispose();
        };
    }
}
