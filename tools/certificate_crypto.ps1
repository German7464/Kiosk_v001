param([switch]$LibraryOnly)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest
if ($PSVersionTable.PSVersion -lt [version]'7.6' -or [Environment]::Version.Major -lt 10) { throw 'PowerShell 7.6 and .NET 10 required' }
Add-Type -Path (Join-Path $PSScriptRoot 'certificate_crypto.cs')
if (-not $LibraryOnly) {
    try {
        $inputJson = [Console]::In.ReadToEnd()
        [Console]::Out.WriteLine([KioskCertificateCrypto]::Execute($inputJson))
    } catch {
        [Console]::Error.WriteLine('Certificate operation rejected.')
        exit 1
    } finally { $inputJson = $null }
}
