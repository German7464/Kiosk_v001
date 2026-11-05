using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.IO;
using System.Runtime.InteropServices;
using System.Security.AccessControl;
using System.Security.Principal;
using System.Text;
using System.Threading;

// Browser data is disposable. Publications, prepared views and receipts never live here.
public sealed class RuntimeStorage : IDisposable {
    public const long ProfileLimit = 256L * 1024 * 1024;
    public const long FreeReserve = 128L * 1024 * 1024;
    const string Owner = "KioskOfflineRuntime/v1\n";
    readonly string profile, runtime;
    readonly long limit, reserve;
    Timer watch;
    int scanning;
    public string BrowserDirectory { get { return Path.Combine(runtime, "browser"); } }

    static readonly SecurityIdentifier User = WindowsIdentity.GetCurrent().User;
    static readonly SecurityIdentifier SystemUser = new SecurityIdentifier(WellKnownSidType.LocalSystemSid, null);
    static readonly SecurityIdentifier Administrators = new SecurityIdentifier(WellKnownSidType.BuiltinAdministratorsSid, null);
    static bool Trusted(IdentityReference identity) {
        return identity.Equals(User) || identity.Equals(SystemUser) || identity.Equals(Administrators);
    }
    public static string CheckRoot(string value) {
        string root = LocalView.PlainDirectory(value);
        if (root.StartsWith(@"\\", StringComparison.Ordinal) ||
            new DriveInfo(Path.GetPathRoot(root)).DriveType != DriveType.Fixed)
            throw new InvalidDataException("display_storage_not_local");
        if (!Directory.Exists(root)) {
            var acl = new DirectorySecurity();
            acl.SetAccessRuleProtection(true, false);
            foreach (var principal in new[] { User, SystemUser, Administrators })
                acl.AddAccessRule(new FileSystemAccessRule(principal, FileSystemRights.FullControl,
                    InheritanceFlags.ContainerInherit | InheritanceFlags.ObjectInherit,
                    PropagationFlags.None, AccessControlType.Allow));
            Directory.CreateDirectory(root, acl);
        }
        var security = Directory.GetAccessControl(root);
        var descriptor = new RawSecurityDescriptor(security.GetSecurityDescriptorBinaryForm(), 0);
        if (descriptor.DiscretionaryAcl == null)
            throw new InvalidDataException("display_storage_permissions");
        if (!Trusted(security.GetOwner(typeof(SecurityIdentifier))))
            throw new InvalidDataException("display_storage_owner");
        FileSystemRights writes = FileSystemRights.Write | FileSystemRights.Delete |
            FileSystemRights.DeleteSubdirectoriesAndFiles | FileSystemRights.ChangePermissions | FileSystemRights.TakeOwnership;
        foreach (FileSystemAccessRule rule in security.GetAccessRules(true, true, typeof(SecurityIdentifier)))
            if (rule.AccessControlType == AccessControlType.Allow &&
                (rule.PropagationFlags & PropagationFlags.InheritOnly) == 0 &&
                (rule.FileSystemRights & writes) != 0 && !Trusted(rule.IdentityReference))
                throw new InvalidDataException("display_storage_permissions");
        return root;
    }
    public static void Separate(params string[] values) {
        var roots = new List<string>();
        foreach (string value in values) {
            string path = LocalView.PlainDirectory(value).TrimEnd(Path.DirectorySeparatorChar);
            foreach (string other in roots)
                if (String.Equals(path, other, StringComparison.OrdinalIgnoreCase) ||
                    path.StartsWith(other + "\\", StringComparison.OrdinalIgnoreCase) ||
                    other.StartsWith(path + "\\", StringComparison.OrdinalIgnoreCase))
                    throw new InvalidDataException("overlapping_display_storage");
            roots.Add(path);
        }
    }
    // Bound traversal as well as bytes; reject links before following or removing anything.
    static long Usage(string root, long maximum) {
        long total = 0; int count = 0;
        var pending = new Stack<string>(); pending.Push(root);
        while (pending.Count != 0) {
            string directory = pending.Pop();
            LocalView.PlainDirectory(directory);
            using (var entries = Directory.EnumerateFileSystemEntries(directory).GetEnumerator()) {
              while (true) {
                bool next;
                try { next = entries.MoveNext(); }
                catch (DirectoryNotFoundException) { if (directory == root) throw; else break; }
                if (!next) break;
                string path = entries.Current;
                if (++count > 20000) throw new InvalidDataException("display_profile_entries");
                FileAttributes attributes;
                try { attributes = File.GetAttributes(path); }
                catch (FileNotFoundException) { continue; }
                if ((attributes & FileAttributes.ReparsePoint) != 0)
                    throw new InvalidDataException("display_profile_link");
                if ((attributes & FileAttributes.Directory) != 0) pending.Push(path);
                else {
                    try { total = checked(total + new FileInfo(path).Length); }
                    catch (FileNotFoundException) { continue; }
                    if (total > maximum) throw new InvalidDataException("display_profile_limit");
                }
              }
            }
        }
        return total;
    }
    public RuntimeStorage(string directory) : this(directory, ProfileLimit, FreeReserve) { }
    // Explicit bounds are used by the isolated native fixture, never by CLI/page input.
    public RuntimeStorage(string directory, long maximum, long minimumFree) {
        if (maximum < 1024 || minimumFree < 0) throw new ArgumentOutOfRangeException();
        profile = CheckRoot(directory); runtime = Path.Combine(profile, "runtime-v1");
        limit = maximum; reserve = minimumFree;
        RemoveOwnedRuntime();
        Check();
        Directory.CreateDirectory(runtime);
        using (var output = new FileStream(Path.Combine(runtime, "owner"), FileMode.CreateNew, FileAccess.Write, FileShare.Read)) {
            byte[] bytes = Encoding.ASCII.GetBytes(Owner); output.Write(bytes, 0, bytes.Length); output.Flush(true);
        }
    }
    public void Check() {
        Usage(profile, limit);
        if (new DriveInfo(Path.GetPathRoot(profile)).AvailableFreeSpace < reserve)
            throw new InvalidDataException("display_disk_reserve");
    }
    void RemoveOwnedRuntime() {
        if (!Directory.Exists(runtime) && !File.Exists(runtime)) return;
        LocalView.PlainDirectory(runtime);
        string marker = Path.Combine(runtime, "owner");
        if (!File.Exists(marker)) {
            if (Directory.GetFileSystemEntries(runtime).Length == 0) { Directory.Delete(runtime); return; }
            throw new InvalidDataException("display_runtime_unowned");
        }
        if ((File.GetAttributes(marker) & FileAttributes.ReparsePoint) != 0 ||
            new FileInfo(marker).Length != Owner.Length || File.ReadAllText(marker, Encoding.ASCII) != Owner)
            throw new InvalidDataException("display_runtime_unowned");
        Usage(runtime, Int64.MaxValue);
        // Exact fixed child only, after ownership/link checks and while holding display.lock.
        // An open browser file causes refusal; publications and legacy profile data are untouched.
        foreach (string path in Directory.GetFileSystemEntries(runtime)) {
            if (path == marker) continue;
            if (Directory.Exists(path)) Directory.Delete(path, true); else File.Delete(path);
        }
        File.Delete(marker); Directory.Delete(runtime);
    }
    public void StartWatch(Action<string> exhausted) {
        if (watch != null) throw new InvalidOperationException();
        watch = new Timer(_ => {
            if (Interlocked.Exchange(ref scanning, 1) != 0) return;
            try { Check(); }
            catch (Exception error) {
                string reason = error is InvalidDataException ? error.Message : "display_storage_unavailable";
                exhausted(reason);
            }
            finally { Interlocked.Exchange(ref scanning, 0); }
        }, null, 1000, 1000);
    }
    public void CleanupAfterBrowserExit() { RemoveOwnedRuntime(); }
    public void Dispose() {
        if (watch != null) {
            using (var done = new ManualResetEvent(false)) { watch.Dispose(done); done.WaitOne(); }
            watch = null;
        }
    }
}

// A private nested Windows job closes the owned browser tree even if the UI/host crashes.
// Keep its handle until process exit: closing it earlier would terminate this host too.
public static class DisplayProcessJob {
    static IntPtr handle;
    [StructLayout(LayoutKind.Sequential)] struct BasicLimits {
        public long PerProcess, PerJob; public uint Flags; public UIntPtr Minimum, Maximum;
        public uint Active; public UIntPtr Affinity; public uint Priority, Scheduling;
    }
    [StructLayout(LayoutKind.Sequential)] struct IoCounters { public ulong A, B, C, D, E, F; }
    [StructLayout(LayoutKind.Sequential)] struct ExtendedLimits {
        public BasicLimits Basic; public IoCounters Io; public UIntPtr ProcessMemory, JobMemory, PeakProcess, PeakJob;
    }
    [DllImport("kernel32.dll", CharSet = CharSet.Unicode, SetLastError = true)] static extern IntPtr CreateJobObject(IntPtr attributes, string name);
    [DllImport("kernel32.dll", SetLastError = true)] static extern bool SetInformationJobObject(IntPtr job, int kind, ref ExtendedLimits limits, int size);
    [DllImport("kernel32.dll", SetLastError = true)] static extern bool AssignProcessToJobObject(IntPtr job, IntPtr process);
    [DllImport("kernel32.dll")] static extern bool CloseHandle(IntPtr value);
    public static void OwnProcessTree() {
        if (handle != IntPtr.Zero) return;
        IntPtr job = CreateJobObject(IntPtr.Zero, null);
        var limits = new ExtendedLimits(); limits.Basic.Flags = 0x2000; // KILL_ON_JOB_CLOSE; no breakaway.
        if (job == IntPtr.Zero || !SetInformationJobObject(job, 9, ref limits, Marshal.SizeOf(limits)) ||
            !AssignProcessToJobObject(job, Process.GetCurrentProcess().Handle)) {
            if (job != IntPtr.Zero) CloseHandle(job);
            throw new InvalidOperationException("display_process_ownership");
        }
        handle = job;
    }
}
