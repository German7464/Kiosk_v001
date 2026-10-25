using System;
using System.Collections.Generic;
using System.ComponentModel;
using System.IO;
using System.Runtime.InteropServices;
using System.Security.Principal;
using System.ServiceProcess;
using System.Threading;
using System.Web.Script.Serialization;
using Microsoft.Win32.SafeHandles;

public class Spec {
    public string Path { get; set; }
    public uint Access { get; set; }
    public bool Directory { get; set; }
    public bool Expected { get; set; }
}
public class AccessService : ServiceBase {
    string specifications;
    string output;
    string expectedSid;
    Thread worker;
    [DllImport("kernel32.dll", SetLastError=true, CharSet=CharSet.Unicode)]
    static extern SafeFileHandle CreateFileW(string path, uint access, uint share, IntPtr security, uint disposition, uint flags, IntPtr template);
    [DllImport("advapi32.dll", SetLastError=true)]
    static extern bool GetTokenInformation(IntPtr token, int type, IntPtr buffer, int length, out int required);
    [StructLayout(LayoutKind.Sequential)] struct Luid { public uint Low; public int High; }
    [StructLayout(LayoutKind.Sequential)] struct Privilege { public Luid Id; public uint Attributes; }
    [DllImport("advapi32.dll", SetLastError=true, CharSet=CharSet.Unicode)]
    static extern bool LookupPrivilegeValue(string system, string name, out Luid value);
    static bool Enabled(IntPtr token, string name) {
        Luid wanted;
        if (!LookupPrivilegeValue(null,name,out wanted)) throw new Win32Exception(Marshal.GetLastWin32Error());
        int required;
        GetTokenInformation(token,3,IntPtr.Zero,0,out required);
        IntPtr buffer=Marshal.AllocHGlobal(required);
        try {
            if (!GetTokenInformation(token,3,buffer,required,out required)) throw new Win32Exception(Marshal.GetLastWin32Error());
            int count=Marshal.ReadInt32(buffer);
            for (int index=0;index<count;index++) {
                Privilege entry=(Privilege)Marshal.PtrToStructure(IntPtr.Add(buffer,4+index*Marshal.SizeOf(typeof(Privilege))),typeof(Privilege));
                if (entry.Id.Low==wanted.Low && entry.Id.High==wanted.High) return (entry.Attributes&2)!=0;
            }
            return false;
        } finally { Marshal.FreeHGlobal(buffer); }
    }
    public AccessService(string[] args) {
        ServiceName=args[0];
        specifications=args[1];
        output=args[2];
        expectedSid=args[3];
    }
    protected override void OnStart(string[] args) {
        worker=new Thread(Probe);
        worker.Start();
    }
    protected override void OnStop() {
        if (worker!=null && Thread.CurrentThread!=worker) worker.Join(10000);
    }
    void Probe() {
        var json=new JavaScriptSerializer();
        var report=new Dictionary<string,object>();
        try {
            using (var identity=WindowsIdentity.GetCurrent()) {
                report["identity"]=identity.Name;
                report["sid"]=identity.User.Value;
                report["session_id"]=System.Diagnostics.Process.GetCurrentProcess().SessionId;
                report["program_data"]=Environment.GetEnvironmentVariable("PROGRAMDATA");
                bool backup=Enabled(identity.Token,"SeBackupPrivilege");
                bool restore=Enabled(identity.Token,"SeRestorePrivilege");
                report["backup_enabled"]=backup;
                report["restore_enabled"]=restore;
                if (identity.User.Value!=expectedSid || backup || restore) throw new InvalidOperationException("Unexpected identity or bypass privilege");
            }
            Spec[] specs=json.Deserialize<Spec[]>(File.ReadAllText(specifications));
            var results=new List<object>();
            int failed=0;
            foreach (var spec in specs) {
                using (var handle=CreateFileW(spec.Path,spec.Access,7,IntPtr.Zero,3,spec.Directory?0x02000000u:0u,IntPtr.Zero)) {
                    int error=Marshal.GetLastWin32Error();
                    bool granted=!handle.IsInvalid;
                    error=granted?0:error;
                    if (granted!=spec.Expected || (!granted && error!=5)) failed++;
                    results.Add(new {path=spec.Path,access=spec.Access,expected=spec.Expected,granted=granted,error=error});
                }
            }
            report["results"]=results;
            report["checks"]=specs.Length;
            report["failed"]=failed;
            report["passed"]=failed==0;
        } catch(Exception error) {
            report["passed"]=false;
            report["error"]=error.ToString();
        }
        File.WriteAllText(output,json.Serialize(report));
        Thread.Sleep(500);
        Stop();
    }
    public static void Main(string[] args) {
        if (args.Length!=4) throw new ArgumentException("Expected service name, specification file, report file and SID");
        ServiceBase.Run(new AccessService(args));
    }
}
