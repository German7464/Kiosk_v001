param(
    [Parameter(Mandatory = $true)][ValidateSet('inspect', 'add', 'remove')][string]$Action,
    [Parameter(Mandatory = $true)][string]$CertificateFile,
    [Parameter(Mandatory = $true)][string]$ExpectedSha256
)

$ErrorActionPreference = 'Stop'
$certificate = [Security.Cryptography.X509Certificates.X509Certificate2]::CreateFromPem([IO.File]::ReadAllText($CertificateFile))
$store = [Security.Cryptography.X509Certificates.X509Store]::new('Root', 'CurrentUser')
try {
    $digest = [Convert]::ToHexString([Security.Cryptography.SHA256]::HashData($certificate.RawData)).ToLowerInvariant()
    if ($digest -cne $ExpectedSha256 -or $certificate.HasPrivateKey) { throw 'Invalid public authority' }
    $constraints = @($certificate.Extensions | Where-Object { $_ -is [Security.Cryptography.X509Certificates.X509BasicConstraintsExtension] })
    if ($constraints.Count -ne 1 -or -not $constraints[0].CertificateAuthority) { throw 'Authority required' }
    $store.Open([Security.Cryptography.X509Certificates.OpenFlags]::ReadWrite)
    $matches = @($store.Certificates | Where-Object {
        [Convert]::ToHexString([Security.Cryptography.SHA256]::HashData($_.RawData)).ToLowerInvariant() -ceq $ExpectedSha256
    })
    if ($Action -eq 'add') {
        if ($matches.Count -ne 0) { throw 'Authority already present' }
        $store.Add($certificate)
    } elseif ($Action -eq 'remove') {
        foreach ($match in $matches) { $store.Remove($match) }
    }
    $present = @($store.Certificates | Where-Object {
        [Convert]::ToHexString([Security.Cryptography.SHA256]::HashData($_.RawData)).ToLowerInvariant() -ceq $ExpectedSha256
    }).Count
    if ($Action -eq 'add' -and $present -ne 1) { throw 'Enrollment not verified' }
    if ($Action -eq 'remove' -and $present -ne 0) { throw 'Removal not verified' }
    @{ present = $present; sha256 = $digest } | ConvertTo-Json -Compress
} finally {
    $store.Close()
    $store.Dispose()
    $certificate.Dispose()
}
