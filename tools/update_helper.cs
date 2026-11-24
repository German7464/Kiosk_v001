// KioskUpdateHelper: atomic activation of a staged offline update.
//
// Runs from OUTSIDE the install directory (a trusted updates location) so it can
// rename the live directory that still contains the just-exited maintenance or
// client process. It swaps the staged binary tree into place, then verifies the
// new application is actually ready before reporting success, and rolls back to
// the previous tree with verified restoration on failure. The separate application
// data root is never touched.
//
// Usage: KioskUpdateHelper.exe <requestFile>
//   requestFile is a "key=value" text file (no quoting, no JSON) holding:
//     staging=<dir>  live=<dir>  backup=<dir>  mode=<service|relaunch|none>
//     result=<file>  task=<one-shot scheduled task to self-delete>
//   mode "service"  -> also service=<name>, version=<str>, device_id=<str>, runtime=<path>
//   mode "relaunch" -> also relaunch=<exe>
//   result receives "committed", "rolled_back" or "error: <message>".
//   exit 0 = committed; 1 = rolled back; 2 = error (including a failed rollback).
//
// The single-argument form keeps the schtasks /tr command short (its command line
// has a ~261 character limit), while the request file carries the full paths.
using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.IO;
using System.Threading;
using System.Runtime.InteropServices;
using Microsoft.Win32.SafeHandles;

public static class KioskUpdateHelper {
    [DllImport("kernel32.dll", SetLastError=true)]
    static extern bool SetHandleInformation(IntPtr handle, uint mask, uint flags);
    [DllImport("kernel32.dll")]
    static extern uint WaitForSingleObject(IntPtr handle, uint milliseconds);
    static void DeleteTask(string task) {
        if (string.IsNullOrEmpty(task)) return;
        try {
            var psi = new ProcessStartInfo("schtasks.exe", "/delete /tn \"" + task + "\" /f") {
                UseShellExecute = false, CreateNoWindow = true };
            using (var process = Process.Start(psi)) { process.WaitForExit(); }
        } catch { }
    }

    static int Fail(string resultFile, string task, string message) {
        try { File.WriteAllText(resultFile, "error: " + message); } catch { }
        DeleteTask(task);
        Console.Error.WriteLine(message);
        return 2;
    }

    static string Query(string fileName, string arguments) {
        var psi = new ProcessStartInfo(fileName, arguments) {
            UseShellExecute = false, RedirectStandardOutput = true, CreateNoWindow = true };
        using (var process = Process.Start(psi)) {
            string output = process.StandardOutput.ReadToEnd();
            process.WaitForExit();
            return output;
        }
    }

    static bool ServiceRunning(string service) {
        try { return Query("sc.exe", "query " + service).ToUpperInvariant().Contains(" RUNNING "); }
        catch { return false; }
    }

    static void StartService(string service) {
        try { Query("sc.exe", "start " + service); } catch { }
    }

    static Process StartProcess(string fileName) {
        var psi = new ProcessStartInfo(fileName) { UseShellExecute = false, CreateNoWindow = false };
        return Process.Start(psi);
    }

    static Dictionary<string, string> ReadRequest(string path) {
        var map = new Dictionary<string, string>(StringComparer.OrdinalIgnoreCase);
        foreach (var raw in File.ReadAllLines(path)) {
            string line = raw.Trim();
            if (line.Length == 0 || line.StartsWith("#")) continue;
            int eq = line.IndexOf('=');
            if (eq <= 0) continue;
            map[line.Substring(0, eq).Trim()] = line.Substring(eq + 1);
        }
        return map;
    }

    static string Get(Dictionary<string, string> req, string key) {
        return req.ContainsKey(key) ? req[key] : "";
    }

    // Line-oriented extraction from the app's own JSON status file (fields are on
    // their own lines as "key": value). Returns null when absent.
    static string JsonField(string path, string field) {
        if (string.IsNullOrEmpty(path) || !File.Exists(path)) return null;
        // Both compact version.json and indented runtime/package JSON are valid.
        var match = System.Text.RegularExpressions.Regex.Match(File.ReadAllText(path),
            "\\\"" + System.Text.RegularExpressions.Regex.Escape(field) + "\\\"\\s*:\\s*(\\\"([^\\\"]*)\\\"|null)");
        if (match.Success) return match.Groups[2].Success ? match.Groups[2].Value : "null";
        foreach (var raw in File.ReadAllLines(path)) {
            string line = raw.Trim();
            if (line.EndsWith(",")) line = line.Substring(0, line.Length - 1).TrimEnd();
            string needle = "\"" + field + "\":";
            if (!line.StartsWith(needle, StringComparison.Ordinal)) continue;
            string value = line.Substring(needle.Length).Trim();
            if (value.Length >= 2 && value.StartsWith("\"") && value.EndsWith("\""))
                value = value.Substring(1, value.Length - 2);
            return value;
        }
        return null;
    }

    static bool ServiceHealthy(Dictionary<string, string> req) {
        string service = Get(req, "service");
        string version = Get(req, "version");
        string deviceId = Get(req, "device_id");
        string runtime = Get(req, "runtime");
        if (service.Length == 0 || !ServiceRunning(service)) return false;
        if (version.Length > 0 && JsonField(runtime, "version") != version) return false;
        if (deviceId.Length > 0 && JsonField(runtime, "device_id") != deviceId) return false;
        if (JsonField(runtime, "state") != "running") return false;
        string error = JsonField(runtime, "error");
        if (error != null && error != "null" && error.Length > 0) return false;
        return true;
    }

    static void Commit(string resultFile, string task) {
        try { File.WriteAllText(resultFile, "committed"); } catch { }
        DeleteTask(task);
    }

    static int Rollback(string live, string backup, string resultFile, string task, Dictionary<string,string> req) {
        string service = Get(req, "service");
        bool startService = Get(req, "prior_service") == "running";
        string discarded = backup + ".bad." + Guid.NewGuid().ToString("N");
        string failure = null;
        try {
            if (service.Length > 0) {
                Query("sc.exe", "stop " + service);
                var stopDeadline = DateTime.UtcNow.AddSeconds(30);
                while (ServiceRunning(service) && DateTime.UtcNow < stopDeadline) Thread.Sleep(500);
                if (ServiceRunning(service)) throw new IOException("service did not stop for rollback");
            }
            if (!Directory.Exists(backup)) throw new IOException("rollback backup missing");
            if (Directory.Exists(live)) Directory.Move(live, discarded);
            Directory.Move(backup, live);
        } catch (Exception error) { failure = error.Message; }
        if (startService && !string.IsNullOrEmpty(service)) StartService(service);
        bool restored = Directory.Exists(live) && !Directory.Exists(backup)
            && JsonField(Get(req, "marker"), "version") == Get(req, "prior_version");
        if (restored && service.Length > 0) {
            req["version"] = Get(req, "prior_version");
            var deadline = DateTime.UtcNow.AddSeconds(90);
            if (startService) {
                restored = false;
                while (DateTime.UtcNow < deadline) {
                    if (ServiceHealthy(req)) { restored = true; break; }
                    Thread.Sleep(1000);
                }
            } else restored = Query("sc.exe", "query " + service).ToUpperInvariant().Contains(" STOPPED ");
        }
        if (!restored || failure != null) {
            try { File.WriteAllText(resultFile, "error: rollback incomplete" + (failure != null ? ": " + failure : "")); } catch { }
            DeleteTask(task);
            return 2;
        }
        try { File.WriteAllText(resultFile, "rolled_back"); } catch { }
        DeleteTask(task);
        return 1;
    }

    public static int Main(string[] args) {
        // This is the exact inherited kernel reference, not a PID/presence-file
        // inference. Do not let subsequently launched processes inherit it.
        long value, parentValue;
        if (!long.TryParse(Environment.GetEnvironmentVariable("KIOSK_UPDATE_OWNER_HANDLE"), out value)
            || !long.TryParse(Environment.GetEnvironmentVariable("KIOSK_UPDATE_PARENT_HANDLE"), out parentValue)) return 2;
        using (var owner = new SafeFileHandle(new IntPtr(value), true))
        using (var parent = new SafeWaitHandle(new IntPtr(parentValue), true)) {
            if (owner.IsInvalid || parent.IsInvalid || !SetHandleInformation(owner.DangerousGetHandle(), 1, 0)) return 2;
            SetHandleInformation(parent.DangerousGetHandle(), 1, 0);
            if (WaitForSingleObject(parent.DangerousGetHandle(), 60000) != 0) {
                if (args.Length == 1 && File.Exists(args[0])) {
                    var request = ReadRequest(args[0]);
                    return Fail(Get(request, "result"), Get(request, "task"), "initiating process did not exit; activation not attempted");
                }
                return 2;
            }
            return Activate(args);
        }
    }

    static int Activate(string[] args) {
        if (args.Length != 1) return 2;
        string request = args[0];
        if (!File.Exists(request)) return 2;
        var req = ReadRequest(request);
        string staging = Get(req, "staging"), live = Get(req, "live"), backup = Get(req, "backup");
        string mode = Get(req, "mode"), result = Get(req, "result"), task = Get(req, "task");
        if (!Directory.Exists(staging)) return Fail(result, task, "staging missing");
        if (Directory.Exists(backup)) return Fail(result, task, "backup already exists");

        // Wait for the spawning process to exit and release the live directory
        // (bounded, so a stuck caller fails honestly instead of hanging forever).
        string moveError = null;
        bool moved = false;
        for (int attempt = 0; attempt < 80; attempt++) {
            try { Directory.Move(live, backup); moved = true; break; }
            catch (Exception error) { moveError = error.Message; if (attempt == 79) break; Thread.Sleep(500); }
        }
        if (!moved) return Fail(result, task, "cannot move live (still locked): " + moveError);

        try {
            Directory.Move(staging, live);
        } catch (Exception) {
            return Rollback(live, backup, result, task, req);
        }

        if (mode == "service") {
            string service = Get(req, "service");
            if (Get(req, "prior_service") == "stopped") {
                if (JsonField(Get(req, "marker"), "version") != Get(req, "version"))
                    return Rollback(live, backup, result, task, req);
                Commit(result, task); return 0;
            }
            StartService(service);
            var deadline = DateTime.UtcNow.AddSeconds(90);
            while (DateTime.UtcNow < deadline) {
                if (ServiceHealthy(req)) { Commit(result, task); return 0; }
                Thread.Sleep(1000);
            }
            return Rollback(live, backup, result, task, req);
        }
        if (mode == "relaunch") {
            string exe = Get(req, "relaunch");
            if (exe.Length == 0 || !File.Exists(exe))
                return Rollback(live, backup, result, task, req);
            try { StartProcess(exe); }
            catch { return Rollback(live, backup, result, task, req); }
            Commit(result, task);
            return 0;
        }
        if (JsonField(Get(req, "marker"), "version") != Get(req, "version"))
            return Rollback(live, backup, result, task, req);
        Commit(result, task);
        return 0;
    }
}
