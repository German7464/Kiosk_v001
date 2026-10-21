param(
    [Parameter(Mandatory = $true)][string]$OutputDirectory,
    [string]$LanAddress
)

$ErrorActionPreference = 'Stop'
$lanIp = $null
if ($LanAddress) {
    $lanIp = [Net.IPAddress]::Parse($LanAddress)
    if ($lanIp.AddressFamily -ne [Net.Sockets.AddressFamily]::InterNetwork -or
        [Net.IPAddress]::IsLoopback($lanIp) -or $lanIp.Equals([Net.IPAddress]::Any) -or
        $lanIp.GetAddressBytes()[0] -ge 224 -or $lanIp.GetAddressBytes()[0] -eq 0) { throw 'Unicast LAN IPv4 required' }
}
$outputRoot = [IO.Path]::GetFullPath($OutputDirectory)
[IO.Directory]::CreateDirectory($outputRoot) | Out-Null
$now = [DateTimeOffset]::UtcNow
$hash = [Security.Cryptography.HashAlgorithmName]::SHA256
$padding = [Security.Cryptography.RSASignaturePadding]::Pkcs1
$authorityKey = [Security.Cryptography.RSA]::Create(2048)
$authorityRequest = [Security.Cryptography.X509Certificates.CertificateRequest]::new('CN=Kiosk temporary HTTPS authority', $authorityKey, $hash, $padding)
$authorityRequest.CertificateExtensions.Add([Security.Cryptography.X509Certificates.X509BasicConstraintsExtension]::new($true, $false, 0, $true))
$authorityRequest.CertificateExtensions.Add([Security.Cryptography.X509Certificates.X509KeyUsageExtension]::new([Security.Cryptography.X509Certificates.X509KeyUsageFlags]::KeyCertSign, $true))
$authorityRequest.CertificateExtensions.Add([Security.Cryptography.X509Certificates.X509SubjectKeyIdentifierExtension]::new($authorityRequest.PublicKey, $false))
$authority = $authorityRequest.CreateSelfSigned($now.AddDays(-7), $now.AddDays(7))
[IO.File]::WriteAllText([IO.Path]::Combine($outputRoot, 'authority.pem'), $authority.ExportCertificatePem())

try {
    foreach ($name in @('valid', 'renewed', 'wrong-name', 'expired')) {
        $serverKey = [Security.Cryptography.RSA]::Create(2048)
        try {
            $request = [Security.Cryptography.X509Certificates.CertificateRequest]::new('CN=Kiosk temporary HTTPS server', $serverKey, $hash, $padding)
            $request.CertificateExtensions.Add([Security.Cryptography.X509Certificates.X509BasicConstraintsExtension]::new($false, $false, 0, $true))
            $request.CertificateExtensions.Add([Security.Cryptography.X509Certificates.X509SubjectKeyIdentifierExtension]::new($request.PublicKey, $false))
            $request.CertificateExtensions.Add([Security.Cryptography.X509Certificates.X509AuthorityKeyIdentifierExtension]::CreateFromCertificate($authority, $true, $false))
            $request.CertificateExtensions.Add([Security.Cryptography.X509Certificates.X509KeyUsageExtension]::new([Security.Cryptography.X509Certificates.X509KeyUsageFlags]::DigitalSignature -bor [Security.Cryptography.X509Certificates.X509KeyUsageFlags]::KeyEncipherment, $true))
            $purposes = [Security.Cryptography.OidCollection]::new()
            $purposes.Add([Security.Cryptography.Oid]::new('1.3.6.1.5.5.7.3.1')) | Out-Null
            $request.CertificateExtensions.Add([Security.Cryptography.X509Certificates.X509EnhancedKeyUsageExtension]::new($purposes, $true))
            $names = [Security.Cryptography.X509Certificates.SubjectAlternativeNameBuilder]::new()
            if ($name -eq 'wrong-name') {
                $names.AddDnsName('wrong.invalid')
            } else {
                $names.AddDnsName('localhost')
                $names.AddIpAddress([Net.IPAddress]::Parse('127.0.0.1'))
                if ($lanIp) { $names.AddIpAddress($lanIp) }
            }
            $request.CertificateExtensions.Add($names.Build())
            $start = $now.AddMinutes(-5)
            $end = $now.AddDays(1)
            if ($name -eq 'expired') {
                $start = $now.AddDays(-2)
                $end = $now.AddDays(-1)
            }
            $serial = [Security.Cryptography.RandomNumberGenerator]::GetBytes(16)
            $serial[0] = $serial[0] -band 127
            $certificate = $request.Create($authority, $start, $end, $serial)
            try {
                [IO.File]::WriteAllText([IO.Path]::Combine($outputRoot, "$name.pem"), $certificate.ExportCertificatePem())
                [IO.File]::WriteAllText([IO.Path]::Combine($outputRoot, "$name.key"), $serverKey.ExportPkcs8PrivateKeyPem())
            } finally {
                $certificate.Dispose()
            }
        } finally {
            $serverKey.Dispose()
        }
    }
} finally {
    $authority.Dispose()
    $authorityKey.Dispose()
}
