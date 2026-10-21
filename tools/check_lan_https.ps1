param(
    [string]$SessionFile = "$PSScriptRoot/session.json",
    [string]$ExpectedSha256,
    [string]$ReportFile = "$PSScriptRoot/client-report.json",
    [switch]$LibraryOnly
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest
if ($PSVersionTable.PSVersion.Major -lt 7) { throw 'PowerShell 7 required' }
if (-not ('KioskLanTls' -as [type])) {
    Add-Type -TypeDefinition @'
using System;
using System.Net;
using System.Net.Http;
using System.Net.Security;
using System.Security.Cryptography;
using System.Security.Cryptography.X509Certificates;

public sealed class KioskLanTls : IDisposable {
    public HttpClient Client;
    public CookieContainer Cookies = new CookieContainer();
    public SslPolicyErrors LastErrors;
    public bool CallbackSeen;
    private X509Certificate2 root;
    private bool trustRoot;
    public KioskLanTls(string pem, string digest, bool trusted) {
        root = X509Certificate2.CreateFromPem(pem);
        string actual = Convert.ToHexString(SHA256.HashData(root.RawData)).ToLowerInvariant();
        if (actual != digest || root.HasPrivateKey) throw new ArgumentException("Authority digest mismatch");
        var constraints = root.Extensions["2.5.29.19"] as X509BasicConstraintsExtension;
        if (constraints == null || !constraints.CertificateAuthority) throw new ArgumentException("Authority required");
        trustRoot = trusted;
        var handler = new HttpClientHandler();
        handler.UseProxy = false;
        handler.AllowAutoRedirect = false;
        handler.CookieContainer = Cookies;
        handler.ServerCertificateCustomValidationCallback = Validate;
        Client = new HttpClient(handler);
        Client.Timeout = TimeSpan.FromSeconds(15);
    }
    private bool Validate(HttpRequestMessage request, X509Certificate2 leaf, X509Chain unused, SslPolicyErrors errors) {
        LastErrors = errors;
        CallbackSeen = true;
        if (!trustRoot) return errors == SslPolicyErrors.None;
        if (leaf == null || (errors & (SslPolicyErrors.RemoteCertificateNameMismatch | SslPolicyErrors.RemoteCertificateNotAvailable)) != 0) return false;
        using (var chain = new X509Chain()) {
            chain.ChainPolicy.TrustMode = X509ChainTrustMode.CustomRootTrust;
            chain.ChainPolicy.CustomTrustStore.Add(root);
            chain.ChainPolicy.RevocationMode = X509RevocationMode.NoCheck;
            chain.ChainPolicy.DisableCertificateDownloads = true;
            chain.ChainPolicy.ApplicationPolicy.Add(new Oid("1.3.6.1.5.5.7.3.1"));
            return chain.Build(leaf);
        }
    }
    public void Dispose() { Client.Dispose(); root.Dispose(); }
}
'@
}

function Invoke-LanRequest {
    param([KioskLanTls]$Transport, [string]$Path, [int]$Expected = 200,
          [Net.Http.HttpContent]$Content = $null, [hashtable]$Headers = @{})
    if (-not $Path.StartsWith('/') -or $Path.StartsWith('//')) { throw 'Relative origin path required' }
    $request = [Net.Http.HttpRequestMessage]::new()
    $request.RequestUri = [uri]::new($script:origin + $Path)
    $request.Method = if ($null -eq $Content) { [Net.Http.HttpMethod]::Get } else { [Net.Http.HttpMethod]::Post }
    $request.Content = $Content
    foreach ($key in $Headers.Keys) { $null = $request.Headers.TryAddWithoutValidation($key, [string]$Headers[$key]) }
    $response = $null
    try {
        $response = $Transport.Client.SendAsync($request).GetAwaiter().GetResult()
        $code = [string][int]$response.StatusCode
        if (-not $script:codes.ContainsKey($code)) { $script:codes[$code] = 0 }
        $script:codes[$code]++
        if ([int]$code -ne $Expected) { throw 'Unexpected HTTP status' }
        $body = $response.Content.ReadAsByteArrayAsync().GetAwaiter().GetResult()
        $headersOut = @{}
        foreach ($entry in $response.Headers) { $headersOut[$entry.Key] = ($entry.Value -join ',') }
        return @{ Bytes = $body; Text = [Text.Encoding]::UTF8.GetString($body); Headers = $headersOut }
    } finally {
        if ($null -ne $response) { $response.Dispose() }
        $request.Dispose()
    }
}

function Get-LanToken {
    param([KioskLanTls]$Transport)
    $page = Invoke-LanRequest $Transport '/kiosk'
    $match = [regex]::Match($page.Text, 'name="csrf-token" content="([a-f0-9]{64})"')
    if (-not $match.Success) { throw 'CSRF token missing' }
    return $match.Groups[1].Value
}

function Send-LanForm {
    param([KioskLanTls]$Transport, [string]$Path, [hashtable]$Values, [int]$Expected = 302, [hashtable]$Headers = @{})
    $pairs = [Collections.Generic.Dictionary[string,string]]::new()
    foreach ($key in $Values.Keys) { $pairs.Add($key, [string]$Values[$key]) }
    $Headers = $Headers.Clone()
    $Headers['X-CSRF-Token'] = Get-LanToken $Transport
    $content = [Net.Http.FormUrlEncodedContent]::new($pairs)
    return Invoke-LanRequest $Transport $Path $Expected $content $Headers
}

function Test-LanPortClosed {
    param([string]$Address, [int]$Port)
    $tcp = [Net.Sockets.TcpClient]::new()
    try {
        $task = $tcp.ConnectAsync($Address, $Port)
        try { $connected = $task.Wait(3000) -and $tcp.Connected } catch { $connected = $false }
        if ($connected) { throw 'Internal port accessible over LAN' }
    } finally { $tcp.Dispose() }
}

if ($LibraryOnly) { return }

$report = @{ schema_version = 1; session = ''; success = $false; checks = @(); http_statuses = @{}; error = $null }
$trusted = $null
$untrusted = $null
$stale = $null
$plain = $null
$authority = $null
try {
    if (Test-Path -LiteralPath $ReportFile) { throw 'Report already exists; choose a new report path' }
    if ($ExpectedSha256 -cnotmatch '^[a-f0-9]{64}$') { throw 'Independent lowercase SHA-256 required' }
    $sessionPath = (Resolve-Path -LiteralPath $SessionFile).Path
    $bundle = Split-Path -Parent $sessionPath
    if ((Get-Item -LiteralPath $sessionPath).Length -gt 16384) { throw 'Manifest too large' }
    $manifest = Get-Content -Raw -LiteralPath $sessionPath | ConvertFrom-Json
    $fields = @($manifest.PSObject.Properties.Name | Sort-Object)
    if (($fields -join ',') -ne 'admin_port,backend_port,client_ip,origin,schema_version,session' -or
        $manifest.schema_version -ne 1 -or $manifest.session -cnotmatch '^[a-f0-9]{32}$') { throw 'Invalid session manifest' }
    $originUri = [uri]$manifest.origin
    if ($originUri.Scheme -ne 'https' -or $originUri.AbsolutePath -ne '/' -or $originUri.Query -or $originUri.Fragment -or $originUri.UserInfo -or
        $originUri.HostNameType -ne [UriHostNameType]::IPv4 -or [Net.IPAddress]::IsLoopback([Net.IPAddress]::Parse($originUri.Host))) { throw 'LAN IPv4 HTTPS origin required' }
    foreach ($port in @($manifest.backend_port, $manifest.admin_port)) {
        if ($port -lt 1 -or $port -gt 65535 -or $port -eq $originUri.Port) { throw 'Invalid internal port' }
    }
    $clientAddress = [Net.IPAddress]::Parse($manifest.client_ip)
    $localAddresses = @([Net.NetworkInformation.NetworkInterface]::GetAllNetworkInterfaces() | ForEach-Object { $_.GetIPProperties().UnicastAddresses.Address.IPAddressToString })
    if ($clientAddress.AddressFamily -ne [Net.Sockets.AddressFamily]::InterNetwork -or $manifest.client_ip -notin $localAddresses -or $manifest.client_ip -eq $originUri.Host) { throw 'Run on the selected second PC' }
    $report.session = $manifest.session
    $script:origin = $originUri.GetLeftPart([UriPartial]::Authority)
    $script:codes = $report.http_statuses
    $pem = [IO.File]::ReadAllText((Join-Path $bundle 'authority.pem'))
    $authority = [Security.Cryptography.X509Certificates.X509Certificate2]::CreateFromPem($pem)
    $actualDigest = [Convert]::ToHexString([Security.Cryptography.SHA256]::HashData($authority.RawData)).ToLowerInvariant()
    if ($actualDigest -cne $ExpectedSha256) { throw 'Authority digest mismatch' }
    $untrusted = [KioskLanTls]::new($pem, $ExpectedSha256, $false)
    $failed = $false
    try { $null = Invoke-LanRequest $untrusted '/api/version' } catch {
        $failed = $untrusted.CallbackSeen -and (($untrusted.LastErrors -band [Net.Security.SslPolicyErrors]::RemoteCertificateChainErrors) -ne 0)
    }
    if (-not $failed) { throw 'Expected an unknown-authority TLS rejection before browser trust' }
    $report.checks += 'unknown_authority'
    $trusted = [KioskLanTls]::new($pem, $ExpectedSha256, $true)
    $stale = [KioskLanTls]::new($pem, $ExpectedSha256, $true)
    foreach ($path in @('/kiosk', '/kiosk/events', '/tv', '/preview', '/admin/login', '/api/version', '/api/events', '/api/tags')) {
        $response = Invoke-LanRequest $trusted $path
        if ($path -in @('/kiosk', '/kiosk/events', '/tv', '/preview') -and $response.Text.Contains('http://')) { throw 'Plaintext display URL' }
    }
    $null = Invoke-LanRequest $trusted '/admin' 302
    $report.checks += 'routes'
    $loginPage = Invoke-LanRequest $trusted '/admin/login'
    if (-not $loginPage.Headers.ContainsKey('Set-Cookie') -or $loginPage.Headers['Set-Cookie'] -notmatch '(?i)secure' -or
        $loginPage.Headers['Set-Cookie'] -notmatch '(?i)httponly' -or $loginPage.Headers['Set-Cookie'] -notmatch '(?i)samesite=lax') { throw 'Secure cookie attributes missing' }
    $passwordSecure = Read-Host 'Disposable admin password (same as on test server)' -AsSecureString
    $password = [Net.NetworkCredential]::new('', $passwordSecure).Password
    $passwordSecure.Dispose()
    $null = Invoke-LanRequest $trusted '/admin/login' 403 ([Net.Http.StringContent]::new('username=admin&password=invalid', [Text.Encoding]::UTF8, 'application/x-www-form-urlencoded'))
    $null = Send-LanForm $trusted '/admin/login' @{username = 'admin'; password = $password}
    $null = Invoke-LanRequest $trusted '/admin'
    $report.checks += 'csrf_cookie_login'
    $before = (Invoke-LanRequest $trusted '/api/version').Text | ConvertFrom-Json
    $multipart = [Net.Http.MultipartFormDataContent]::new()
    foreach ($item in @{title = 'LAN fixture'; short_description = 'Temporary event'; full_description = 'LAN image verification'; status = 'active'; sort_order = '0'}.GetEnumerator()) {
        $multipart.Add([Net.Http.StringContent]::new($item.Value), $item.Key)
    }
    $image = [Net.Http.ByteArrayContent]::new([IO.File]::ReadAllBytes((Join-Path $bundle 'fixture.png')))
    $image.Headers.ContentType = [Net.Http.Headers.MediaTypeHeaderValue]::new('image/png')
    $multipart.Add($image, 'event_image', 'fixture.png')
    $null = Invoke-LanRequest $trusted '/admin/events/create' 302 $multipart @{'X-CSRF-Token' = (Get-LanToken $trusted)}
    $events = (Invoke-LanRequest $trusted '/api/events').Text | ConvertFrom-Json
    if (@($events.events).Count -ne 1 -or $events.events[0].title -ne 'LAN fixture') { throw 'Event fixture missing' }
    foreach ($field in @('image_kiosk', 'image_tv', 'image_thumb')) {
        $media = Invoke-LanRequest $trusted $events.events[0].$field
        if ($media.Bytes.Length -lt 4 -or $media.Bytes[0] -ne 255 -or $media.Bytes[1] -ne 216) { throw 'JPEG derivative missing' }
    }
    $after = (Invoke-LanRequest $trusted '/api/version').Text | ConvertFrom-Json
    if ($after.content_version -le $before.content_version) { throw 'Content version did not advance' }
    $fullscreen = (Send-LanForm $trusted '/admin/fullscreen/validate' @{username = 'admin'; password = $password} 200).Text | ConvertFrom-Json
    if ($fullscreen.success -ne $true) { throw 'Fullscreen authentication failed' }
    $report.checks += 'upload_images_version_fullscreen'
    foreach ($cookie in $trusted.Cookies.GetCookies($originUri)) { $stale.Cookies.Add($originUri, [Net.Cookie]::new($cookie.Name, $cookie.Value, $cookie.Path)) }
    $replacement = Read-Host 'New disposable password (remember for Chrome fullscreen; 12-128 characters)' -AsSecureString
    $newPassword = [Net.NetworkCredential]::new('', $replacement).Password
    $replacement.Dispose()
    $confirmation = Read-Host 'Confirm new disposable password' -AsSecureString
    try {
        if ($newPassword.Length -lt 12 -or $newPassword.Length -gt 128 -or $newPassword -cne [Net.NetworkCredential]::new('', $confirmation).Password) { throw 'Invalid new disposable password' }
    } finally { $confirmation.Dispose() }
    $null = Send-LanForm $trusted '/admin/password/change' @{current_password = $password; new_password = $newPassword; confirm_password = $newPassword}
    $password = $null
    $null = Invoke-LanRequest $stale '/admin' 302
    $null = Send-LanForm $trusted '/admin/login' @{username = 'admin'; password = $newPassword}
    $null = Invoke-LanRequest $trusted '/admin'
    $newPassword = $null
    $report.checks += 'password_revocation'
    foreach ($port in @($manifest.backend_port, $manifest.admin_port)) { Test-LanPortClosed $originUri.Host $port }
    $report.checks += 'internal_ports_closed'
    $plainHandler = [Net.Http.HttpClientHandler]::new()
    $plainHandler.UseProxy = $false
    $plainHandler.AllowAutoRedirect = $false
    $plain = [Net.Http.HttpClient]::new($plainHandler)
    $plain.Timeout = [TimeSpan]::FromSeconds(5)
    $plaintext = $plain.GetAsync("http://$($originUri.Authority)/admin/login").GetAwaiter().GetResult()
    try {
        if ([int]$plaintext.StatusCode -ne 400 -or $plaintext.Headers.Contains('Set-Cookie')) { throw 'Plaintext service accepted request' }
        $report.http_statuses['400'] = 1
    } finally { $plaintext.Dispose() }
    $report.checks += 'plaintext_rejected'
    $identity = (Invoke-LanRequest $trusted '/api/version').Headers['X-Kiosk-Instance']
    if (-not $identity) { throw 'Managed identity missing' }
    $null = Read-Host 'On SERVER enter restart; after readiness press Enter here (no browser trust yet)'
    $null = Invoke-LanRequest $trusted '/admin'
    $newIdentity = (Invoke-LanRequest $trusted '/api/version').Headers['X-Kiosk-Instance']
    if (-not $newIdentity -or $newIdentity -eq $identity) { throw 'Managed restart not observed' }
    $report.checks += 'restart_session'
    $spoof = @{'Forwarded' = 'for=198.51.100.1;proto=http;host=evil.invalid'; 'X-Forwarded-For' = '198.51.100.2';
        'X-Forwarded-Proto' = 'http'; 'X-Forwarded-Host' = 'evil.invalid'; 'X-Forwarded-Port' = '80'; 'X-Real-IP' = '198.51.100.3'}
    $null = Invoke-LanRequest $trusted '/api/version' 200 $null $spoof
    $null = Invoke-LanRequest $trusted '/api/version' 400 $null @{Host = 'evil.invalid'}
    $report.checks += 'forwarding_host'
    $null = Read-Host 'Prepare SERVER budget command; press Enter to run remote authentication limits'
    for ($index = 0; $index -lt 10; $index++) { $null = Send-LanForm $trusted '/admin/login' @{username = 'lan-pair'; password = 'invalid'} 401 }
    $limited = Send-LanForm $trusted '/admin/login' @{username = 'lan-pair'; password = 'invalid'} 429 $spoof
    if ([int]$limited.Headers['Retry-After'] -lt 1) { throw 'Missing Retry-After' }
    for ($index = 0; $index -lt 30; $index++) {
        $spoof['X-Forwarded-For'] = "198.51.100.$($index + 10)"
        $null = Send-LanForm $trusted '/admin/login' @{username = "lan-source-$index"; password = 'invalid'} 401 $spoof
    }
    $limited = Send-LanForm $trusted '/admin/login' @{username = 'lan-exhausted'; password = 'invalid'} 429 $spoof
    if ([int]$limited.Headers['Retry-After'] -lt 1) { throw 'Missing source Retry-After' }
    $null = Invoke-LanRequest $trusted "/api/version?lan_budget=$($manifest.session)"
    $report.checks += 'source_budget'
    $budgetTimer = [Diagnostics.Stopwatch]::StartNew()
    $null = Read-Host 'Within 30 seconds enter budget on SERVER; after success press Enter here'
    if ($budgetTimer.Elapsed.TotalSeconds -ge 30) { throw 'Budget comparison window expired; repeat a fresh session' }
    $null = Send-LanForm $trusted '/admin/login' @{username = 'lan-still-exhausted'; password = 'invalid'} 429 $spoof
    $report.checks += 'remote_budget_after_local'
    $report.success = $true
} catch {
    $report.error = $_.Exception.GetType().Name
} finally {
    $password = $null
    $newPassword = $null
    foreach ($resource in @($trusted, $untrusted, $stale, $plain, $authority)) { if ($null -ne $resource) { $resource.Dispose() } }
    $json = $report | ConvertTo-Json -Depth 6
    $stream = [IO.File]::Open([IO.Path]::GetFullPath($ReportFile), [IO.FileMode]::CreateNew, [IO.FileAccess]::Write)
    try {
        $bytes = [Text.Encoding]::UTF8.GetBytes($json)
        $stream.Write($bytes, 0, $bytes.Length)
    } finally { $stream.Dispose() }
    @{success = $report.success; error = $report.error; report = $ReportFile} | ConvertTo-Json -Compress
}
if (-not $report.success) { exit 1 }
