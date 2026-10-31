using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Security.Cryptography;
using System.Text;
using System.Web.Script.Serialization;
using System.Windows.Forms;
using Microsoft.Web.WebView2.Core;
using Microsoft.Web.WebView2.WinForms;

public sealed class ViewFile {
    public string path { get; set; }
    public long size { get; set; }
    public string sha256 { get; set; }
}
public sealed class ViewDescriptor {
    public int schema_version { get; set; }
    public string renderer { get; set; }
    public string revision { get; set; }
    public string mode { get; set; }
    public string package_sha256 { get; set; }
    public List<ViewFile> files { get; set; }
}

public sealed class LocalView {
    public const string Origin = "https://kiosk.invalid";
    public readonly Dictionary<string, ViewFile> Files = new Dictionary<string, ViewFile>(StringComparer.Ordinal);
    readonly string root;
    public readonly string Key, PackageIdentity, Mode;

    public static string PlainDirectory(string value) {
        string full = Path.GetFullPath(value);
        for (DirectoryInfo item = new DirectoryInfo(full); item != null; item = item.Parent) {
            if (item.Exists && (item.Attributes & FileAttributes.ReparsePoint) != 0)
                throw new InvalidDataException("unsafe_directory");
        }
        return full;
    }

    public static string Digest(byte[] bytes) {
        using (SHA256 hash = SHA256.Create())
            return BitConverter.ToString(hash.ComputeHash(bytes)).Replace("-", "").ToLowerInvariant();
    }

    string FilePath(string relative) {
        if (String.IsNullOrEmpty(relative) || relative.Contains("\\") || relative.Contains(":"))
            throw new InvalidDataException("unsafe_file");
        string path = root;
        foreach (string part in relative.Split('/')) {
            if (part.Length == 0 || part == "." || part == ".." || part.EndsWith(".") || part.EndsWith(" "))
                throw new InvalidDataException("unsafe_file");
            path = Path.Combine(path, part);
            if ((File.GetAttributes(path) & FileAttributes.ReparsePoint) != 0)
                throw new InvalidDataException("unsafe_file");
        }
        return path;
    }

    public static string Mime(string path) {
        if (path == "index.html") return "text/html; charset=utf-8";
        if (path == "events.js") return "text/javascript; charset=utf-8";
        if (path == "events.css") return "text/css; charset=utf-8";
        if (!path.StartsWith("static/uploads/", StringComparison.Ordinal)) return null;
        switch (Path.GetExtension(path).ToLowerInvariant()) {
            case ".jpg": case ".jpeg": return "image/jpeg";
            case ".png": return "image/png";
            case ".webp": return "image/webp";
            case ".gif": return "image/gif";
            case ".bmp": return "image/bmp";
            case ".ico": return "image/x-icon";
            default: return null;
        }
    }

    public LocalView(string directory) {
        root = PlainDirectory(directory);
        string descriptor = FilePath("view.json");
        if (new FileInfo(descriptor).Length > 2 * 1024 * 1024) throw new InvalidDataException("view_limit");
        var serializer = new JavaScriptSerializer { MaxJsonLength = 2 * 1024 * 1024, RecursionLimit = 32 };
        var view = serializer.Deserialize<ViewDescriptor>(File.ReadAllText(descriptor, Encoding.UTF8));
        if (view == null || view.schema_version != 1 || view.renderer != "events-v1" ||
            (view.mode != "kiosk" && view.mode != "tv") || String.IsNullOrEmpty(view.revision) ||
            view.files == null || view.files.Count < 3 || view.files.Count > 10000)
            throw new InvalidDataException("invalid_view");
        Key = Path.GetFileName(root);
        PackageIdentity = view.package_sha256 ?? "";
        Mode = view.mode;
        long total = 0;
        var portable = new HashSet<string>(StringComparer.OrdinalIgnoreCase);
        foreach (ViewFile entry in view.files) {
            if (entry == null || entry.path == null || Mime(entry.path) == null || !portable.Add(entry.path) ||
                entry.size < 0 || entry.size > 64 * 1024 * 1024 || entry.sha256 == null ||
                !System.Text.RegularExpressions.Regex.IsMatch(entry.sha256, "\\A[0-9a-f]{64}\\z"))
                throw new InvalidDataException("invalid_inventory");
            total += entry.size;
            if (total > 128 * 1024 * 1024) throw new InvalidDataException("view_limit");
            Files.Add(entry.path, entry);
            Read(entry.path);
        }
        if (!Files.ContainsKey("index.html") || !Files.ContainsKey("events.js") || !Files.ContainsKey("events.css") ||
            Files["events.js"].sha256 != "@RENDERER_JS_SHA256@" || Files["events.css"].sha256 != "@RENDERER_CSS_SHA256@")
            throw new InvalidDataException("renderer_mismatch");
    }

    public byte[] Read(string relative) {
        ViewFile entry = Files[relative];
        string filename = FilePath(relative);
        using (FileStream input = File.OpenRead(filename)) {
            if (input.Length != entry.size) throw new InvalidDataException("view_integrity");
            byte[] bytes = new byte[(int)entry.size];
            int offset = 0;
            while (offset < bytes.Length) {
                int count = input.Read(bytes, offset, bytes.Length - offset);
                if (count == 0) throw new InvalidDataException("view_integrity");
                offset += count;
            }
            if (input.ReadByte() != -1 || Digest(bytes) != entry.sha256) throw new InvalidDataException("view_integrity");
            return bytes;
        }
    }

    public string AllowedPath(string address, string method) {
        Uri uri;
        if (method != "GET" || !Uri.TryCreate(address, UriKind.Absolute, out uri) || uri.Scheme != "https" ||
            uri.Host != "kiosk.invalid" || uri.Port != 443 || uri.UserInfo.Length != 0 ||
            uri.Query.Length != 0 || uri.Fragment.Length != 0) return null;
        string path = Uri.UnescapeDataString(uri.AbsolutePath).TrimStart('/');
        return Files.ContainsKey(path) ? path : null;
    }
}

public static class OfflineDisplay {
    [STAThread]
    public static int Main(string[] args) {
        try {
            if (args.Length == 2 && args[0] == "--check-view") {
                var view = new LocalView(args[1]);
                if (view.AllowedPath(LocalView.Origin + "/index.html", "GET") != "index.html" ||
                    view.AllowedPath("https://example.com/index.html", "GET") != null ||
                    view.AllowedPath("file:///C:/Windows/win.ini", "GET") != null ||
                    view.AllowedPath(LocalView.Origin + "/view.json", "GET") != null ||
                    view.AllowedPath(LocalView.Origin + "/index.html", "POST") != null ||
                    view.AllowedPath(LocalView.Origin + "/index.html?x=1", "GET") != null ||
                    view.AllowedPath(LocalView.Origin + "/%2e%2e/secrets.txt", "GET") != null)
                    throw new InvalidDataException("policy_failed");
                Console.WriteLine("view_integrity_and_origin_policy_pass");
                return 0;
            }
            if (args.Length < 4 || args[0] != "--view" || args[2] != "--profile") return 2;
            bool diagnostics = false;
            string session = "", cacheRoot = "";
            for (int i = 4; i < args.Length; i++) {
                if (args[i] == "--diagnostics" && !diagnostics) diagnostics = true;
                else if (args[i] == "--session" && session.Length == 0 && i + 1 < args.Length) {
                    session = args[++i];
                    if (!System.Text.RegularExpressions.Regex.IsMatch(session, "\\A[0-9a-f]{32}\\z")) return 2;
                } else if (args[i] == "--cache-root" && cacheRoot.Length == 0 && i + 1 < args.Length) {
                    cacheRoot = LocalView.PlainDirectory(args[++i]);
                } else return 2;
            }
            if (cacheRoot.Length != 0 && (session.Length == 0 ||
                !String.Equals(Path.GetDirectoryName(Path.GetFullPath(args[1])), cacheRoot, StringComparison.OrdinalIgnoreCase))) return 2;
            var content = new LocalView(args[1]);
            Application.EnableVisualStyles();
            Application.SetCompatibleTextRenderingDefault(false);
            string profile = LocalView.PlainDirectory(args[3]);
            Directory.CreateDirectory(profile);
            using (var lease = new FileStream(Path.Combine(profile, "display.lock"), FileMode.OpenOrCreate,
                                              FileAccess.ReadWrite, FileShare.None)) {
                var window = new DisplayWindow(content, profile, diagnostics, session, cacheRoot);
                Application.Run(window);
                return window.StartupFailed ? 1 : 0;
            }
        } catch {
            Console.Error.WriteLine("offline_display_failed");
            return 1;
        }
    }
}
