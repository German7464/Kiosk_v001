param(
    [Parameter(Mandatory=$true)][string]$LabRoot,
    [string]$Address = '192.168.1.165',
    [int]$Port = 8443,
    [int]$BackendPort = 8765,
    [string]$OperatorAccount = ''
)
$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest
$labPath = [IO.Path]::GetFullPath($LabRoot)
$logsPath = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '../logs')) + [IO.Path]::DirectorySeparatorChar
if (-not $labPath.StartsWith($logsPath, [StringComparison]::OrdinalIgnoreCase) -or (Test-Path -LiteralPath $labPath)) {
    throw 'Use a NEW directory under this checkout logs; existing identities are never overwritten.'
}
$ip = [Net.IPAddress]::Parse($Address)
if ($Port -lt 1024 -or $Port -gt 65535 -or $BackendPort -lt 1024 -or $BackendPort -gt 65535 -or $Port -eq $BackendPort) { throw 'Invalid isolated port.' }
[void][IO.Directory]::CreateDirectory($labPath)
$adminPath = Join-Path $labPath 'admin-private'
$serverPath = Join-Path $labPath 'server'
$publicPath = Join-Path $labPath 'public'
foreach ($folder in @($adminPath,$serverPath,$publicPath)) { [void][IO.Directory]::CreateDirectory($folder) }
# Test private material is confined to this user; no certificate/trust store is modified.
foreach ($folder in @($adminPath,$serverPath)) {
    $acl = [Security.AccessControl.DirectorySecurity]::new()
    $acl.SetAccessRuleProtection($true,$false)
    $sid = [Security.Principal.WindowsIdentity]::GetCurrent().User
    $rule = [Security.AccessControl.FileSystemAccessRule]::new($sid,'FullControl','ContainerInherit,ObjectInherit','None','Allow')
    $acl.AddAccessRule($rule)
    if ($OperatorAccount) {
        $operator = [Security.Principal.NTAccount]::new($OperatorAccount)
        $operatorRule = [Security.AccessControl.FileSystemAccessRule]::new($operator,'FullControl','ContainerInherit,ObjectInherit','None','Allow')
        $acl.AddAccessRule($operatorRule)
    }
    Set-Acl -LiteralPath $folder -AclObject $acl
}
$hash = [Security.Cryptography.HashAlgorithmName]::SHA256
$padding = [Security.Cryptography.RSASignaturePadding]::Pkcs1
$now = [DateTimeOffset]::UtcNow
$caKey = [Security.Cryptography.RSA]::Create(3072)
$tlsKey = [Security.Cryptography.RSA]::Create(3072)
$groupKey = [Security.Cryptography.RSA]::Create(3072)
$ca = $null
$leaf = $null
try {
    $caRequest = [Security.Cryptography.X509Certificates.CertificateRequest]::new('CN=Kiosk disposable lab CA',$caKey,$hash,$padding)
    $caRequest.CertificateExtensions.Add([Security.Cryptography.X509Certificates.X509BasicConstraintsExtension]::new($true,$false,0,$true))
    $caRequest.CertificateExtensions.Add([Security.Cryptography.X509Certificates.X509KeyUsageExtension]::new([Security.Cryptography.X509Certificates.X509KeyUsageFlags]::KeyCertSign,$true))
    $caSki = [Security.Cryptography.X509Certificates.X509SubjectKeyIdentifierExtension]::new($caRequest.PublicKey,$false)
    $caRequest.CertificateExtensions.Add($caSki)
    $authorityKey = [byte[]](@(0x30,0x16,0x80,0x14) + [Convert]::FromHexString($caSki.SubjectKeyIdentifier))
    $caRequest.CertificateExtensions.Add([Security.Cryptography.X509Certificates.X509Extension]::new('2.5.29.35',$authorityKey,$false))
    $ca = $caRequest.CreateSelfSigned($now.AddMinutes(-5),$now.AddDays(14))
    $request = [Security.Cryptography.X509Certificates.CertificateRequest]::new('CN=Kiosk disposable lab server',$tlsKey,$hash,$padding)
    $san = [Security.Cryptography.X509Certificates.SubjectAlternativeNameBuilder]::new()
    $san.AddIpAddress($ip)
    $san.AddIpAddress([Net.IPAddress]::Loopback)
    $san.AddDnsName('localhost')
    $request.CertificateExtensions.Add($san.Build())
    $request.CertificateExtensions.Add([Security.Cryptography.X509Certificates.X509SubjectKeyIdentifierExtension]::new($request.PublicKey,$false))
    $request.CertificateExtensions.Add([Security.Cryptography.X509Certificates.X509Extension]::new('2.5.29.35',$authorityKey,$false))
    $request.CertificateExtensions.Add([Security.Cryptography.X509Certificates.X509BasicConstraintsExtension]::new($false,$false,0,$true))
    $request.CertificateExtensions.Add([Security.Cryptography.X509Certificates.X509KeyUsageExtension]::new([Security.Cryptography.X509Certificates.X509KeyUsageFlags]::DigitalSignature -bor [Security.Cryptography.X509Certificates.X509KeyUsageFlags]::KeyEncipherment,$true))
    $oids = [Security.Cryptography.OidCollection]::new()
    [void]$oids.Add([Security.Cryptography.Oid]::new('1.3.6.1.5.5.7.3.1'))
    $request.CertificateExtensions.Add([Security.Cryptography.X509Certificates.X509EnhancedKeyUsageExtension]::new($oids,$true))
    $serial = [Security.Cryptography.RandomNumberGenerator]::GetBytes(16)
    $leaf = $request.Create($ca,$now.AddMinutes(-4),$now.AddDays(7),$serial)
    $origin = 'https://' + $Address + ':' + $Port
    $groupId = [Guid]::NewGuid().ToString()
    $serverId = [Guid]::NewGuid().ToString()
    $keyId = [Convert]::ToHexStringLower([Security.Cryptography.SHA256]::HashData($groupKey.ExportSubjectPublicKeyInfo()))
    $tlsPin = [Convert]::ToHexStringLower([Security.Cryptography.SHA256]::HashData($tlsKey.ExportSubjectPublicKeyInfo()))
    $trustPayload = [ordered]@{version=1;group_id=$groupId;generation=1;issued_at=$now.ToUnixTimeSeconds();expires_at=$now.AddDays(7).ToUnixTimeSeconds();servers=@([ordered]@{server_id=$serverId;origin=$origin;tls_spki_sha256=$tlsPin;roles=@('publisher')})}
    $payloadBytes = [Text.Encoding]::UTF8.GetBytes(($trustPayload | ConvertTo-Json -Compress -Depth 10))
    $prefix = [Text.Encoding]::ASCII.GetBytes("Kiosk/GroupTrust/v1`0")
    $signedBytes = [byte[]]::new($prefix.Length+$payloadBytes.Length)
    [Array]::Copy($prefix,0,$signedBytes,0,$prefix.Length)
    [Array]::Copy($payloadBytes,0,$signedBytes,$prefix.Length,$payloadBytes.Length)
    $signature = $groupKey.SignData($signedBytes,$hash,$padding)
    if (-not $groupKey.VerifyData($signedBytes,$signature,$hash,$padding)) {throw 'Signature self-check failed.'}
    $envelope = [ordered]@{version=1;key_id=$keyId;algorithm='RSA3072-SHA256-PKCS1-v1_5';payload_base64=[Convert]::ToBase64String($payloadBytes);signature_base64=[Convert]::ToBase64String($signature)}
    $bootstrap = [ordered]@{version=1;bootstrap_id=[Guid]::NewGuid().ToString();group_id=$groupId;server_id=$serverId;origin=$origin;tls_ca_pem=$ca.ExportCertificatePem();group_key_id=$keyId;group_spki_base64=[Convert]::ToBase64String($groupKey.ExportSubjectPublicKeyInfo());issued_at=$now.ToUnixTimeSeconds();expires_at=$now.AddDays(1).ToUnixTimeSeconds()}
    $public = [ordered]@{version=1;group_id=$groupId;server_id=$serverId;origin=$origin;bootstrap=$bootstrap;trust=$envelope}
    [IO.File]::WriteAllText((Join-Path $serverPath 'public.json'),($public | ConvertTo-Json -Depth 12 -Compress))
    [IO.File]::WriteAllText((Join-Path $publicPath 'bootstrap.json'),($bootstrap | ConvertTo-Json -Depth 10 -Compress))
    [IO.File]::WriteAllText((Join-Path $publicPath 'trust.json'),($envelope | ConvertTo-Json -Depth 10 -Compress))
    [IO.File]::WriteAllText((Join-Path $publicPath 'lab-ca.pem'),$ca.ExportCertificatePem())
    [IO.File]::WriteAllText((Join-Path $serverPath 'tls-cert.pem'),$leaf.ExportCertificatePem()+"`n"+$ca.ExportCertificatePem())
    [IO.File]::WriteAllText((Join-Path $serverPath 'tls-key.pem'),$tlsKey.ExportPkcs8PrivateKeyPem())
    [IO.File]::WriteAllText((Join-Path $adminPath 'group-key.pem'),$groupKey.ExportPkcs8PrivateKeyPem())
    [IO.File]::WriteAllText((Join-Path $adminPath 'ca-key.pem'),$caKey.ExportPkcs8PrivateKeyPem())
    $portableRoot = $labPath.Replace('\','/')
    $caddy = @"
{
    admin off
    persist_config off
    auto_https off
    storage file_system {
        root $portableRoot/caddy-storage
    }
    servers {
        protocols h1 h2
    }
}
$origin {
    bind $Address 127.0.0.1
    tls $portableRoot/server/tls-cert.pem $portableRoot/server/tls-key.pem
    request_header -X-Forwarded-*
    request_header -X-Real-IP
    reverse_proxy 127.0.0.1:$BackendPort
}
"@
    [IO.File]::WriteAllText((Join-Path $labPath 'Caddyfile'),$caddy)
    Write-Output ('Created disposable lab at '+$labPath+'; origin '+$origin+'; public bootstrap only may be transferred.')
} finally {
    if ($null -ne $leaf) {$leaf.Dispose()}
    if ($null -ne $ca) {$ca.Dispose()}
    $caKey.Dispose();$tlsKey.Dispose();$groupKey.Dispose()
}
