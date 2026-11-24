# android/tools/generate-admin-tls-fixtures.ps1
#
# Regenerates the disposable, test-only TLS fixtures used by the administration
# WebView instrumentation (AdminTlsSandboxTest). These are NOT release signing
# material: a throwaway fixture CA, a server certificate it signs, and an
# unrelated self-signed server. The CA *private key* is ephemeral and discarded.
#
# The .p12 files are ignored by Git (private-key material), so a fresh checkout
# must run this once before the journey / instrumentation step. The sandbox
# network-security-config trusts @raw/admin_fixture_ca only under debug-overrides,
# so this never becomes production trust.
#
# Writes (matching the paths the build already expects):
#   android/app/src/sandbox/res/raw/admin_fixture_ca.pem   (CA certificate, tracked)
#   android/app/src/androidTest/assets/admin-tls/trusted.p12   (server signed by CA)
#   android/app/src/androidTest/assets/admin-tls/untrusted.p12 (self-signed server)
#
# Usage:
#   & ./android/tools/generate-admin-tls-fixtures.ps1 -BuildJdk '<existing full JDK>' -Force
#
# -OutputRoot is optional and only for exercising this script against an isolated
# (missing-fixture) layout without touching the real android/ fixtures. It must be
# a directory under which app/src/sandbox/res/raw and app/src/androidTest/assets/admin-tls
# will be created.

param(
    [Parameter(Mandatory = $true)][string]$BuildJdk,
    [switch]$Force,
    [string]$OutputRoot = ''
)

$ErrorActionPreference = 'Stop'
$HarnessRoot = Split-Path -Parent $PSScriptRoot           # android/
if (!$OutputRoot) { $OutputRoot = $HarnessRoot }

$keytool = Join-Path $BuildJdk 'bin/keytool.exe'
if (!(Test-Path -LiteralPath $keytool -PathType Leaf)) { throw "keytool not found under $BuildJdk/bin" }

$caPem = Join-Path $OutputRoot 'app/src/sandbox/res/raw/admin_fixture_ca.pem'
$trusted = Join-Path $OutputRoot 'app/src/androidTest/assets/admin-tls/trusted.p12'
$untrusted = Join-Path $OutputRoot 'app/src/androidTest/assets/admin-tls/untrusted.p12'

foreach ($target in @($caPem, $trusted, $untrusted)) {
    if ((Test-Path -LiteralPath $target) -and !$Force) {
        throw "Refusing to overwrite existing fixture '$target'; pass -Force to regenerate."
    }
}

$work = Join-Path ([System.IO.Path]::GetTempPath()) ("admin-tls-" + [guid]::NewGuid().ToString('n'))
New-Item -ItemType Directory -Force -Path $work | Out-Null
New-Item -ItemType Directory -Force -Path (Split-Path -Parent $caPem) | Out-Null
New-Item -ItemType Directory -Force -Path (Split-Path -Parent $trusted) | Out-Null

function Run-Keytool([string[]]$arguments) {
    & $keytool @arguments
    if ($LASTEXITCODE -ne 0) { throw "keytool failed: $($arguments -join ' ')" }
}

try {
    $caP12 = Join-Path $work 'ca.p12'
    $caPemWork = Join-Path $work 'ca.pem'
    $serverP12 = Join-Path $work 'server.p12'
    $serverCsr = Join-Path $work 'server.csr'
    $serverPem = Join-Path $work 'server.pem'
    $untrustedP12 = Join-Path $work 'untrusted.p12'
    $store = @('-storepass', 'changeit', '-keypass', 'changeit', '-noprompt')

    $args = @('-genkeypair', '-alias', 'ca', '-keyalg', 'RSA', '-keysize', '2048', '-validity', '3650',
        '-dname', 'CN=Admin fixture CA', '-ext', 'bc:c', '-storetype', 'PKCS12', '-keystore', $caP12) + $store
    Run-Keytool $args
    Run-Keytool @('-exportcert', '-alias', 'ca', '-keystore', $caP12, '-storepass', 'changeit', '-rfc', '-file', $caPemWork)

    $args = @('-genkeypair', '-alias', 'server', '-keyalg', 'RSA', '-keysize', '2048', '-validity', '3650',
        '-dname', 'CN=127.0.0.1', '-ext', 'SAN=ip:127.0.0.1', '-storetype', 'PKCS12', '-keystore', $serverP12) + $store
    Run-Keytool $args
    Run-Keytool @('-certreq', '-alias', 'server', '-keystore', $serverP12, '-storepass', 'changeit', '-file', $serverCsr)
    Run-Keytool @('-gencert', '-alias', 'ca', '-keystore', $caP12, '-storepass', 'changeit', '-infile', $serverCsr,
        '-outfile', $serverPem, '-rfc', '-ext', 'SAN=ip:127.0.0.1', '-ext', 'EKU=serverAuth')
    Run-Keytool @('-importcert', '-alias', 'ca', '-keystore', $serverP12, '-storepass', 'changeit', '-file', $caPemWork, '-noprompt')
    Run-Keytool @('-importcert', '-alias', 'server', '-keystore', $serverP12, '-storepass', 'changeit', '-file', $serverPem, '-noprompt')

    $args = @('-genkeypair', '-alias', 'server', '-keyalg', 'RSA', '-keysize', '2048', '-validity', '3650',
        '-dname', 'CN=127.0.0.1', '-ext', 'SAN=ip:127.0.0.1', '-storetype', 'PKCS12', '-keystore', $untrustedP12) + $store
    Run-Keytool $args

    Copy-Item -LiteralPath $caPemWork -Destination $caPem -Force
    Copy-Item -LiteralPath $serverP12 -Destination $trusted -Force
    Copy-Item -LiteralPath $untrustedP12 -Destination $untrusted -Force

    Write-Host "admin_fixture_ca.pem -> $caPem"
    Write-Host "trusted.p12        -> $trusted"
    Write-Host "untrusted.p12      -> $untrusted"
    Write-Host 'Test-only fixtures regenerated; the fixture CA private key was discarded.'
} finally {
    Remove-Item -LiteralPath $work -Recurse -Force -ErrorAction SilentlyContinue
}
