using System;
using System.Collections.Generic;
using System.IO;
using System.Security.AccessControl;
using System.Security.Principal;
using System.Threading;
using System.Web.Script.Serialization;

// Isolated filesystem checks using the exact production storage implementation.
public static class StoragePolicyFixture {
    static readonly List<string> passed = new List<string>();
    static void Need(bool result, string name) { if (!result) throw new Exception(name); passed.Add(name); }
    static bool Refused(Action operation, string code) {
        try { operation(); return false; } catch (InvalidDataException error) { return error.Message == code; }
    }
    public static int Main(string[] args) {
        if (args.Length != 1 || Directory.Exists(args[0])) return 2;
        string root = RuntimeStorage.CheckRoot(args[0]);
        try {
            string profile = Path.Combine(root, "profile"); RuntimeStorage.CheckRoot(profile);
            string legacy = Path.Combine(profile, "legacy-data"); File.WriteAllText(legacy, "preserve");
            using (var storage = new RuntimeStorage(profile, 1024 * 1024, 0)) {
                Directory.CreateDirectory(storage.BrowserDirectory);
                File.WriteAllText(Path.Combine(storage.BrowserDirectory, "cache"), "disposable");
                storage.Check();
            }
            using (var recovered = new RuntimeStorage(profile, 1024 * 1024, 0)) {
                Need(!File.Exists(Path.Combine(recovered.BrowserDirectory, "cache")) && File.ReadAllText(legacy) == "preserve", "owned-recovery-preserves-legacy");
                Directory.CreateDirectory(recovered.BrowserDirectory);
                using (var pressure = File.Create(Path.Combine(recovered.BrowserDirectory, "pressure"))) pressure.SetLength(2 * 1024 * 1024);
                using (var signalled = new ManualResetEvent(false)) {
                    string reason = ""; recovered.StartWatch(code => { reason = code; signalled.Set(); });
                    Need(signalled.WaitOne(5000) && reason == "display_profile_limit", "runtime-growth-detected");
                    recovered.Dispose();
                }
            }
            using (var recovered = new RuntimeStorage(profile, 1024 * 1024, 0)) {
                recovered.Check(); Need(File.ReadAllText(legacy) == "preserve", "restart-after-overflow");
                recovered.CleanupAfterBrowserExit();
            }
            Need(Refused(() => { using (var low = new RuntimeStorage(profile, 1024 * 1024, Int64.MaxValue)) { } }, "display_disk_reserve"), "low-disk-refusal");
            string unowned = Path.Combine(profile, "runtime-v1"); Directory.CreateDirectory(unowned);
            File.WriteAllText(Path.Combine(unowned, "unknown"), "do-not-delete");
            Need(Refused(() => { using (var bad = new RuntimeStorage(profile)) { } }, "display_runtime_unowned") &&
                File.ReadAllText(Path.Combine(unowned, "unknown")) == "do-not-delete", "unowned-data-not-deleted");
            Need(Refused(() => RuntimeStorage.Separate(profile, profile.ToUpperInvariant()), "overlapping_display_storage"), "case-insensitive-root-refusal");
            string shared = RuntimeStorage.CheckRoot(Path.Combine(root, "shared")); var original = Directory.GetAccessControl(shared);
            try {
                var broad = Directory.GetAccessControl(shared);
                broad.AddAccessRule(new FileSystemAccessRule(new SecurityIdentifier(WellKnownSidType.WorldSid, null), FileSystemRights.Modify, AccessControlType.Allow));
                Directory.SetAccessControl(shared, broad);
                Need(Refused(() => RuntimeStorage.CheckRoot(shared), "display_storage_permissions"), "broad-writer-refusal");
            } finally { Directory.SetAccessControl(shared, original); }
            File.WriteAllText(Path.Combine(root, "result.json"), new JavaScriptSerializer().Serialize(new { result = "PASS", cases = passed }));
            return 0;
        } catch (Exception error) {
            File.WriteAllText(Path.Combine(root, "result.json"), new JavaScriptSerializer().Serialize(new { result = "FAIL", cases = passed, error = error.ToString() }));
            return 1;
        }
    }
}
