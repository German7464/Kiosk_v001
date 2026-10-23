using System;
using System.IO;
using System.Linq;
using System.Net;
using System.Formats.Asn1;
using System.Security.AccessControl;
using System.Security.Principal;
using System.Security.Cryptography;
using System.Security.Cryptography.X509Certificates;
using System.Text;
using System.Text.Json;
using System.Text.RegularExpressions;

public static class KioskCertificateCrypto {
    static readonly HashAlgorithmName Hash = HashAlgorithmName.SHA256;
    static readonly RSASignaturePadding Padding = RSASignaturePadding.Pkcs1;
    static string Value(JsonElement input, string name) => input.GetProperty(name).GetString();
    static string Digest(byte[] bytes) => Convert.ToHexString(SHA256.HashData(bytes)).ToLowerInvariant();
    static string Installation(JsonElement input) => Guid.ParseExact(Value(input, "installation"), "D").ToString("D");
    static X500DistinguishedName Subject(string role, string installation) => new X500DistinguishedName("CN=Kiosk " + role + " " + installation);
    static byte[] Pem(string text, string label) {
        if (text.Length > 65536) throw new ArgumentException("Input too large");
        var fields = PemEncoding.Find(text);
        if (text[fields.Label] != label || text[..fields.Location.Start].Trim().Length != 0 || text[fields.Location.End..].Trim().Length != 0)
            throw new ArgumentException("Single PEM required");
        return Convert.FromBase64String(text[fields.Base64Data]);
    }
    static string[] Names(byte[] raw) {
        var reader = new AsnReader(raw, AsnEncodingRules.DER);
        var sequence = reader.ReadSequence();
        var names = new System.Collections.Generic.List<string>();
        while (sequence.HasData) {
            var tag = sequence.PeekTag();
            string name;
            if (tag.HasSameClassAndValue(new Asn1Tag(TagClass.ContextSpecific, 2))) {
                name = sequence.ReadCharacterString(UniversalTagNumber.IA5String, new Asn1Tag(TagClass.ContextSpecific, 2));
                if (name != name.ToLowerInvariant() || name.Length > 253 || IPAddress.TryParse(name, out _) ||
                    !name.Split('.').All(part => Regex.IsMatch(part, "^[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?$")))
                    throw new ArgumentException("Invalid DNS name");
            } else if (tag.HasSameClassAndValue(new Asn1Tag(TagClass.ContextSpecific, 7))) {
                var bytes = sequence.ReadOctetString(new Asn1Tag(TagClass.ContextSpecific, 7));
                if (bytes.Length != 4 || bytes[0] == 0 || bytes[0] >= 224 || bytes.All(item => item == 255)) throw new ArgumentException("Invalid IPv4");
                name = new IPAddress(bytes).ToString();
            } else throw new ArgumentException("Unsupported SAN");
            names.Add(name);
        }
        reader.ThrowIfNotEmpty();
        if (names.Count == 0 || names.Count > 16 || names.Distinct().Count() != names.Count) throw new ArgumentException("Invalid SAN count");
        return names.OrderBy(item => item, StringComparer.Ordinal).ToArray();
    }
    static X509Extension San(string[] names) {
        var builder = new SubjectAlternativeNameBuilder();
        foreach (var name in names) {
            if (IPAddress.TryParse(name, out var address)) builder.AddIpAddress(address);
            else builder.AddDnsName(name);
        }
        var result = builder.Build();
        Names(result.RawData);
        return result;
    }
    static CertificateRequest Request(JsonElement input) {
        var pem = Value(input, "csr");
        var raw = Pem(pem, "CERTIFICATE REQUEST");
        var outer = new AsnReader(raw, AsnEncodingRules.DER);
        var sequence = outer.ReadSequence();
        sequence.ReadEncodedValue();
        var algorithm = sequence.ReadSequence();
        if (algorithm.ReadObjectIdentifier() != "1.2.840.113549.1.1.11") throw new ArgumentException("SHA256 RSA required");
        algorithm.ReadNull(); algorithm.ThrowIfNotEmpty();
        sequence.ReadBitString(out var unusedBits);
        if (unusedBits != 0) throw new ArgumentException("Invalid signature encoding");
        sequence.ThrowIfNotEmpty(); outer.ThrowIfNotEmpty();
        var request = CertificateRequest.LoadSigningRequestPem(pem, Hash, CertificateRequestLoadOptions.UnsafeLoadCertificateExtensions, Padding);
        if (!request.SubjectName.RawData.SequenceEqual(Subject("server", Installation(input)).RawData) || request.OtherRequestAttributes.Count != 0 ||
            request.CertificateExtensions.Count != 1 || request.CertificateExtensions[0].Oid.Value != "2.5.29.17") throw new ArgumentException("CSR profile rejected");
        using (var key = request.PublicKey.GetRSAPublicKey()) {
            if (key == null || key.KeySize != 3072) throw new ArgumentException("RSA3072 required");
        }
        Names(request.CertificateExtensions[0].RawData);
        return request;
    }
    static object Inspect(JsonElement input) {
        var request = Request(input);
        return new { installation = Installation(input), names = Names(request.CertificateExtensions[0].RawData),
            request_sha256 = Digest(Pem(Value(input, "csr"), "CERTIFICATE REQUEST")), public_key_sha256 = Digest(request.PublicKey.ExportSubjectPublicKeyInfo()) };
    }
    static void LeafExtensions(CertificateRequest request, string[] names) {
        request.CertificateExtensions.Add(new X509BasicConstraintsExtension(false, false, 0, true));
        request.CertificateExtensions.Add(new X509KeyUsageExtension(X509KeyUsageFlags.DigitalSignature | X509KeyUsageFlags.KeyEncipherment, true));
        var purposes = new OidCollection(); purposes.Add(new Oid("1.3.6.1.5.5.7.3.1"));
        request.CertificateExtensions.Add(new X509EnhancedKeyUsageExtension(purposes, true));
        request.CertificateExtensions.Add(new X509SubjectKeyIdentifierExtension(request.PublicKey, false));
        request.CertificateExtensions.Add(San(names));
    }
    static object CreateRequest(JsonElement input) {
        using (var key = RSA.Create(3072)) {
            var names = input.GetProperty("names").EnumerateArray().Select(item => item.GetString()).ToArray();
            var request = new CertificateRequest(Subject("server", Installation(input)), key, Hash, Padding);
            request.CertificateExtensions.Add(San(names));
            return new { key = key.ExportPkcs8PrivateKeyPem(), csr = request.CreateSigningRequestPem() };
        }
    }
    static object CreateAuthority(JsonElement input) {
        var password = Value(input, "password");
        if (password.Length < 16 || password.Length > 1024) throw new ArgumentException("Password length");
        using (var key = RSA.Create(3072)) {
            var request = new CertificateRequest(Subject("authority", Installation(input)), key, Hash, Padding);
            request.CertificateExtensions.Add(new X509BasicConstraintsExtension(true, true, 0, true));
            request.CertificateExtensions.Add(new X509KeyUsageExtension(X509KeyUsageFlags.KeyCertSign, true));
            request.CertificateExtensions.Add(new X509SubjectKeyIdentifierExtension(request.PublicKey, false));
            var now = DateTimeOffset.UtcNow;
            using (var certificate = request.CreateSelfSigned(now.AddMinutes(-5), now.AddDays(3650)))
                return new { authority = certificate.ExportCertificatePem(), encrypted_key = key.ExportEncryptedPkcs8PrivateKeyPem(password.AsSpan(),
                    new PbeParameters(PbeEncryptionAlgorithm.Aes256Cbc, Hash, 600000)) };
        }
    }
    static X509Certificate2 Authority(JsonElement input) {
        var publicPem = Value(input, "authority");
        Pem(publicPem, "CERTIFICATE");
        var encrypted = Value(input, "encrypted_key");
        Pem(encrypted, "ENCRYPTED PRIVATE KEY");
        using (var key = RSA.Create()) {
            key.ImportFromEncryptedPem(encrypted, Value(input, "password"));
            using (var certificate = X509Certificate2.CreateFromPem(publicPem)) {
                var constraint = certificate.Extensions["2.5.29.19"] as X509BasicConstraintsExtension;
                var usage = certificate.Extensions["2.5.29.15"] as X509KeyUsageExtension;
                if (constraint == null || !constraint.CertificateAuthority || !constraint.HasPathLengthConstraint || constraint.PathLengthConstraint != 0 ||
                    usage == null || usage.KeyUsages != X509KeyUsageFlags.KeyCertSign || key.KeySize != 3072 ||
                    !certificate.SubjectName.RawData.SequenceEqual(Subject("authority", Installation(input)).RawData)) throw new ArgumentException("Wrong authority");
                return certificate.CopyWithPrivateKey(key);
            }
        }
    }
    static object Sign(JsonElement input) {
        var csr = Request(input);
        using (var authority = Authority(input)) {
            var now = DateTimeOffset.UtcNow;
            if (authority.NotBefore.ToUniversalTime() > now.UtcDateTime || authority.NotAfter.ToUniversalTime() < now.AddDays(365).UtcDateTime) throw new ArgumentException("Authority lifetime insufficient");
            var request = new CertificateRequest(csr.SubjectName, csr.PublicKey, Hash, Padding);
            LeafExtensions(request, Names(csr.CertificateExtensions[0].RawData));
            request.CertificateExtensions.Add(X509AuthorityKeyIdentifierExtension.CreateFromCertificate(authority, true, false));
            var serial = RandomNumberGenerator.GetBytes(20); serial[0] = (byte)((serial[0] & 0x7f) | 1);
            using (var certificate = request.Create(authority, now.AddMinutes(-5), now.AddDays(365), serial))
                return new { certificate = certificate.ExportCertificatePem(), authority = authority.ExportCertificatePem() };
        }
    }
    static object Verify(JsonElement input) {
        var request = Request(input);
        var authorityPem = Value(input, "authority");
        Pem(authorityPem, "CERTIFICATE"); Pem(Value(input, "certificate"), "CERTIFICATE"); Pem(Value(input, "key"), "PRIVATE KEY");
        using (var root = X509Certificate2.CreateFromPem(authorityPem))
        using (var leaf = X509Certificate2.CreateFromPem(Value(input, "certificate"), Value(input, "key")))
        using (var chain = new X509Chain()) {
            if (Digest(root.RawData) != Value(input, "fingerprint") || !leaf.PublicKey.ExportSubjectPublicKeyInfo().SequenceEqual(request.PublicKey.ExportSubjectPublicKeyInfo()) ||
                !leaf.SubjectName.RawData.SequenceEqual(request.SubjectName.RawData)) throw new ArgumentException("Certificate identity mismatch");
            var constraints = leaf.Extensions["2.5.29.19"] as X509BasicConstraintsExtension;
            var purposes = leaf.Extensions["2.5.29.37"] as X509EnhancedKeyUsageExtension;
            var usage = leaf.Extensions["2.5.29.15"] as X509KeyUsageExtension;
            if (constraints == null || constraints.CertificateAuthority || purposes == null || purposes.EnhancedKeyUsages.Count != 1 ||
                purposes.EnhancedKeyUsages[0].Value != "1.3.6.1.5.5.7.3.1" || usage == null ||
                usage.KeyUsages != (X509KeyUsageFlags.DigitalSignature | X509KeyUsageFlags.KeyEncipherment) || leaf.Extensions["2.5.29.17"] == null ||
                !Names(leaf.Extensions["2.5.29.17"].RawData).SequenceEqual(Names(request.CertificateExtensions[0].RawData))) throw new ArgumentException("Leaf profile mismatch");
            chain.ChainPolicy.TrustMode = X509ChainTrustMode.CustomRootTrust;
            chain.ChainPolicy.CustomTrustStore.Add(root);
            chain.ChainPolicy.RevocationMode = X509RevocationMode.NoCheck;
            chain.ChainPolicy.DisableCertificateDownloads = true;
            chain.ChainPolicy.ApplicationPolicy.Add(new Oid("1.3.6.1.5.5.7.3.1"));
            if (!chain.Build(leaf) || chain.ChainElements.Count != 2 || !chain.ChainElements[1].Certificate.RawData.SequenceEqual(root.RawData)) throw new ArgumentException("Certificate chain rejected");
            return new { authority_sha256 = Digest(root.RawData), certificate_sha256 = Digest(leaf.RawData), expires_utc = leaf.NotAfter.ToUniversalTime().ToString("O") };
        }
    }
    static object SecureDirectory(JsonElement input) {
        var path = Value(input, "path");
        var directory = new DirectoryInfo(path);
        if (!directory.Exists || (directory.Attributes & FileAttributes.ReparsePoint) != 0 || directory.EnumerateFileSystemInfos().Any()) throw new ArgumentException("New empty directory required");
        var security = new DirectorySecurity();
        var owner = WindowsIdentity.GetCurrent().User;
        security.SetOwner(owner); security.SetAccessRuleProtection(true, false);
        foreach (var identity in new[] { owner, new SecurityIdentifier(WellKnownSidType.LocalSystemSid, null), new SecurityIdentifier(WellKnownSidType.BuiltinAdministratorsSid, null) }.Distinct())
            security.AddAccessRule(new FileSystemAccessRule(identity, FileSystemRights.FullControl, InheritanceFlags.ContainerInherit | InheritanceFlags.ObjectInherit, PropagationFlags.None, AccessControlType.Allow));
        directory.SetAccessControl(security);
        return new { secured = true };
    }
    public static string Execute(string json) {
        using (var document = JsonDocument.Parse(json)) {
            var input = document.RootElement;
            object result;
            switch (Value(input, "action")) {
                case "request": result = CreateRequest(input); break;
                case "inspect": result = Inspect(input); break;
                case "initialize": result = CreateAuthority(input); break;
                case "sign": result = Sign(input); break;
                case "verify": result = Verify(input); break;
                case "secure": result = SecureDirectory(input); break;
                default: throw new ArgumentException("Unknown operation");
            }
            return JsonSerializer.Serialize(result);
        }
    }
}
