param(
    [string]$SessionFile = "$PSScriptRoot/session.json",
    [string]$ExpectedSha256,
    [string]$ReportFile = "$PSScriptRoot/client-report.json",
    [switch]$LibraryOnly,
    [switch]$Wizard,
    [switch]$PreflightOnly
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
using System.Net.Sockets;
using System.IO;
using System.Text;
using System.Threading;
using System.Threading.Tasks;
using System.Security.Authentication;
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
        var handler = CreateIPv4Handler();
        handler.CookieContainer = Cookies;
        handler.SslOptions.RemoteCertificateValidationCallback = (sender, certificate, chain, errors) =>
            Validate(null, certificate as X509Certificate2, chain, errors);
        Client = new HttpClient(handler);
        Client.Timeout = TimeSpan.FromSeconds(15);
    }
    public static IPAddress ParseIPv4(string host) {
        IPAddress address;
        if (!IPAddress.TryParse(host, out address) || address.AddressFamily != AddressFamily.InterNetwork)
            throw new ArgumentException("Numeric IPv4 required");
        return address;
    }
    public static async ValueTask<Stream> ConnectIPv4(string host, int port, CancellationToken cancellation) {
        var address = ParseIPv4(host);
        var socket = new Socket(AddressFamily.InterNetwork, SocketType.Stream, ProtocolType.Tcp);
        try {
            await socket.ConnectAsync(address, port, cancellation);
            return new NetworkStream(socket, true);
        } catch { socket.Dispose(); throw; }
    }
    public static SocketsHttpHandler CreateIPv4Handler() {
        var handler = new SocketsHttpHandler();
        handler.UseProxy = false;
        handler.AllowAutoRedirect = false;
        handler.ConnectCallback = (context, cancellation) =>
            ConnectIPv4(context.DnsEndPoint.Host, context.DnsEndPoint.Port, cancellation);
        return handler;
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
    public int ProbeHost(Uri origin) {
        if (origin.Scheme != "https" || origin.UserInfo.Length != 0 || origin.AbsolutePath != "/" || origin.Query.Length != 0 || origin.Fragment.Length != 0)
            throw new ArgumentException("HTTPS origin required");
        var address = ParseIPv4(origin.DnsSafeHost);
        using (var tcp = new TcpClient(AddressFamily.InterNetwork)) {
            var connecting = tcp.ConnectAsync(address, origin.Port);
            if (!connecting.Wait(15000)) throw new TimeoutException("TCP connection timed out");
            connecting.GetAwaiter().GetResult();
            using (var tls = new SslStream(tcp.GetStream(), false, (sender, certificate, chain, errors) =>
                Validate(null, certificate as X509Certificate2, chain, errors))) {
                tls.ReadTimeout = 15000;
                tls.WriteTimeout = 15000;
                tls.AuthenticateAsClient(new SslClientAuthenticationOptions {
                    TargetHost = origin.DnsSafeHost,
                    EnabledSslProtocols = SslProtocols.Tls12 | SslProtocols.Tls13,
                    CertificateRevocationCheckMode = X509RevocationMode.NoCheck
                });
                byte[] request = Encoding.ASCII.GetBytes("GET /api/version HTTP/1.1\r\nHost: evil.invalid\r\nConnection: close\r\n\r\n");
                tls.Write(request, 0, request.Length);
                tls.Flush();
                var line = new StringBuilder();
                for (int index = 0; index < 256; index++) {
                    int current = tls.ReadByte();
                    if (current < 0) throw new IOException("Incomplete HTTP status");
                    if (current == '\n') {
                        string[] fields = line.ToString().TrimEnd('\r').Split(' ');
                        int status;
                        if (fields.Length >= 2 && (fields[0] == "HTTP/1.1" || fields[0] == "HTTP/1.0") &&
                            int.TryParse(fields[1], out status) && status >= 100 && status <= 599) return status;
                        throw new IOException("Invalid HTTP status");
                    }
                    line.Append((char)current);
                }
                throw new IOException("HTTP status too long");
            }
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
    $script:LanResponseStatus = 0
    try {
        $response = $Transport.Client.SendAsync($request).GetAwaiter().GetResult()
        $code = [string][int]$response.StatusCode
        $script:LanResponseStatus = [int]$code
        if ($Path -ne '/_lan-test/control') {
            if (-not $script:codes.ContainsKey($code)) { $script:codes[$code] = 0 }
            $script:codes[$code]++
        }
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

function Test-LanHostRejection {
    param([KioskLanTls]$Transport)
    $script:LanResponseStatus = 0
    $status = $Transport.ProbeHost([uri]$script:origin)
    $script:LanResponseStatus = $status
    $code = [string]$status
    if (-not $script:codes.ContainsKey($code)) { $script:codes[$code] = 0 }
    $script:codes[$code]++
    if ($status -ne 400) { throw 'Unexpected HTTP status' }
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
    $ipv4 = [KioskLanTls]::ParseIPv4($Address)
    $tcp = [Net.Sockets.TcpClient]::new([Net.Sockets.AddressFamily]::InterNetwork)
    try {
        $task = $tcp.ConnectAsync($ipv4, $Port)
        try { $connected = $task.Wait(3000) -and $tcp.Connected } catch {
            $leaf = $_.Exception
            while ($null -ne $leaf.InnerException) { $leaf = $leaf.InnerException }
            if ($leaf -isnot [Net.Sockets.SocketException] -or $leaf.SocketErrorCode -notin @([Net.Sockets.SocketError]::ConnectionRefused, [Net.Sockets.SocketError]::TimedOut)) { throw }
            $connected = $false
        }
        if ($connected) { throw 'Internal port accessible over LAN' }
    } finally { $tcp.Dispose() }
}

function Get-LanClientSession {
    $script:LanStage = 'manifest_file'
    $sessionPath = (Resolve-Path -LiteralPath $SessionFile).Path
    if ((Get-Item -LiteralPath $sessionPath).Length -gt 16384) { throw 'Manifest too large' }
    $manifest = Get-Content -Raw -LiteralPath $sessionPath | ConvertFrom-Json
    $script:LanStage = 'manifest_schema'
    $fields = @($manifest.PSObject.Properties.Name | Sort-Object)
    if (($fields -join ',') -ne 'admin_port,backend_port,client_ip,origin,schema_version,session' -or
        $manifest.schema_version -ne 1 -or $manifest.session -cnotmatch '^[a-f0-9]{32}$') { throw 'Invalid session manifest' }
    $script:LanStage = 'origin'
    $originUri = [uri]$manifest.origin
    if ($originUri.Scheme -ne 'https' -or $originUri.AbsolutePath -ne '/' -or $originUri.Query -or $originUri.Fragment -or $originUri.UserInfo -or
        $originUri.HostNameType -ne [UriHostNameType]::IPv4 -or [Net.IPAddress]::IsLoopback([Net.IPAddress]::Parse($originUri.Host))) { throw 'LAN IPv4 HTTPS origin required' }
    $script:LanStage = 'internal_ports'
    foreach ($port in @($manifest.backend_port, $manifest.admin_port)) {
        if ($port -lt 1 -or $port -gt 65535 -or $port -eq $originUri.Port) { throw 'Invalid internal port' }
    }
    $script:LanStage = 'client_address'
    $clientAddress = [Net.IPAddress]::Parse($manifest.client_ip)
    $localAddresses = @([Net.NetworkInformation.NetworkInterface]::GetAllNetworkInterfaces() |
        ForEach-Object { $_.GetIPProperties().UnicastAddresses } |
        ForEach-Object { $_.Address.IPAddressToString })
    Write-Host "Сервер из настроек: $($originUri.Host)"
    Write-Host "Ожидаемый IP второго ПК: $($manifest.client_ip)"
    Write-Host "Адреса этого компьютера: $($localAddresses -join ', ')"
    if ($clientAddress.AddressFamily -ne [Net.Sockets.AddressFamily]::InterNetwork -or $manifest.client_ip -notin $localAddresses -or $manifest.client_ip -eq $originUri.Host) { throw 'Run on the selected second PC' }
    return @{Manifest=$manifest; Origin=$originUri; Bundle=(Split-Path -Parent $sessionPath)}
}

function Write-LanFailure {
    param([Management.Automation.ErrorRecord]$Failure)
    $reasons = @{
        'Run on the selected second PC' = @('wrong_client_pc','IP этого компьютера не совпадает с IP второго ПК, указанным на сервере. Создайте новый архив с правильным IP.')
        'Invalid session manifest' = @('invalid_manifest','Файл session.json не соответствует ожидаемому формату. Получите новый архив с сервера и распакуйте в отдельную папку.')
        'Manifest too large' = @('invalid_manifest','Файл session.json слишком большой. Используйте исходный архив сервера.')
        'LAN IPv4 HTTPS origin required' = @('invalid_origin','В настройках указан неподходящий адрес сервера. Нужен HTTPS-адрес его локального IPv4.')
        'Invalid internal port' = @('invalid_ports','В архиве некорректные номера внутренних портов. Получите новый архив сервера.')
        'invalid_wizard_bundle' = @('invalid_wizard_bundle','Настройки мастера не совпадают с сеансом. Не смешивайте файлы из разных архивов.')
        'invalid_cleanup_state' = @('invalid_cleanup_state','Данные предыдущей очистки не соответствуют этому архиву. Сохраните папку и сообщите код ошибки.')
        'operator_check_failed' = @('operator_rejected','Вы выбрали «нет» на контрольном вопросе. Этап остановлен без обхода проверки.')
        'Report already exists; choose a new report path' = @('report_exists','В папке уже есть отчёт предыдущей попытки. Для новой проверки нужен новый архив и отдельная папка.')
        'Independent lowercase SHA-256 required' = @('invalid_fingerprint','Мастер получил некорректный отпечаток сертификата. Сохраните диагностический файл.')
        'Authority digest mismatch' = @('fingerprint_mismatch','Отпечаток сертификата не совпал. Проверка остановлена; не обходите её.')
        'Expected an unknown-authority TLS rejection before browser trust' = @('untrusted_tls_probe_failed','Не подтверждён ожидаемый отказ TLS до установки доверия. Сервер может быть недоступен либо сертификат уже доверенный.')
        'Unexpected HTTP status' = @('unexpected_http_status','Сервер вернул неожиданный HTTP-код. Он записан в диагностике.')
        'server_stage_failed' = @('server_stage_failed','Сервер не завершил запрошенный этап. Сохраните вывод обоих мастеров.')
        'server_stage_timeout' = @('server_stage_timeout','Сервер не подтвердил этап за отведённое время. Сохраните вывод обоих мастеров.')
    }
    $reason = 'unexpected_error'
    $message = 'Неожиданная ошибка. Пришлите диагностический файл: в нём указан этап и номер строки, без паролей и ключей.'
    if ($reasons.ContainsKey($Failure.Exception.Message)) { $reason, $message = $reasons[$Failure.Exception.Message] }
    $stage = if (Get-Variable -Name LanStage -Scope Script -ErrorAction SilentlyContinue) { $script:LanStage } else { 'startup' }
    $source = [IO.Path]::GetFileName($Failure.InvocationInfo.ScriptName)
    if ($source -notin @('check_lan_https.ps1','lan_wizard.ps1')) { $source = 'unknown' }
    $diagnostic = @{schema_version=1;stage=$stage;reason=$reason;error=$Failure.Exception.GetType().Name;
        source=$source;line=[int]$Failure.InvocationInfo.ScriptLineNumber}
    $status = Get-Variable -Name LanResponseStatus -Scope Script -ErrorAction SilentlyContinue
    if ($null -ne $status -and [int]$status.Value -ge 100 -and [int]$status.Value -le 599) { $diagnostic.http_status = [int]$status.Value }
    Write-Host "`nЭтап: $stage. Причина: $reason." -ForegroundColor Red
    Write-Host $message
    $destination = Join-Path (Split-Path -Parent ([IO.Path]::GetFullPath($ReportFile))) ('client-diagnostics-' + [DateTime]::UtcNow.ToString('yyyyMMddTHHmmssfff') + '.json')
    try {
        $stream = [IO.File]::Open($destination, [IO.FileMode]::CreateNew, [IO.FileAccess]::Write)
        try { $bytes = [Text.Encoding]::UTF8.GetBytes(($diagnostic | ConvertTo-Json)); $stream.Write($bytes,0,$bytes.Length) } finally { $stream.Dispose() }
        Write-Host "Диагностика сохранена: $destination"
    } catch { Write-Host 'Не удалось сохранить диагностику. Сфотографируйте сообщение с этапом и причиной.' }
}

if ($LibraryOnly) { return }
if ($PreflightOnly) {
    try {
        $null = Get-LanClientSession
        Write-Host 'Настройки и IP этого ПК подходят. Сеть, TLS и пароль этой командой не проверялись.' -ForegroundColor Green
    } catch { Write-LanFailure $_; exit 1 }
    return
}
if ($Wizard) { . "$PSScriptRoot/lan_wizard.ps1" }

$report = @{ schema_version = 1; session = ''; success = $false; checks = @(); http_statuses = @{}; error = $null }
$trusted = $null
$untrusted = $null
$stale = $null
$plain = $null
$authority = $null
$cleanupOnly = $false
try {
    $script:LanStage = 'wizard_initialization'
    if ($Wizard) {
        $ExpectedSha256 = Initialize-LanWizard
        if (-not $ExpectedSha256) { $cleanupOnly = $true; return }
    }
    $script:LanStage = 'report_file'
    if (Test-Path -LiteralPath $ReportFile) { throw 'Report already exists; choose a new report path' }
    $script:LanStage = 'fingerprint_format'
    if ($ExpectedSha256 -cnotmatch '^[a-f0-9]{64}$') { throw 'Independent lowercase SHA-256 required' }
    $settings = Get-LanClientSession
    $manifest, $originUri, $bundle = $settings.Manifest, $settings.Origin, $settings.Bundle
    $report.session = $manifest.session
    $script:origin = $originUri.GetLeftPart([UriPartial]::Authority)
    $script:codes = $report.http_statuses
    $script:LanStage = 'authority'
    $pem = [IO.File]::ReadAllText((Join-Path $bundle 'authority.pem'))
    $authority = [Security.Cryptography.X509Certificates.X509Certificate2]::CreateFromPem($pem)
    $actualDigest = [Convert]::ToHexString([Security.Cryptography.SHA256]::HashData($authority.RawData)).ToLowerInvariant()
    if ($actualDigest -cne $ExpectedSha256) { throw 'Authority digest mismatch' }
    $script:LanStage = 'unknown_authority'
    $untrusted = [KioskLanTls]::new($pem, $ExpectedSha256, $false)
    $failed = $false
    try { $null = Invoke-LanRequest $untrusted '/api/version' } catch {
        $failed = $untrusted.CallbackSeen -and (($untrusted.LastErrors -band [Net.Security.SslPolicyErrors]::RemoteCertificateChainErrors) -ne 0)
    }
    if (-not $failed) { throw 'Expected an unknown-authority TLS rejection before browser trust' }
    $report.checks += 'unknown_authority'
    $trusted = [KioskLanTls]::new($pem, $ExpectedSha256, $true)
    $stale = [KioskLanTls]::new($pem, $ExpectedSha256, $true)
    $script:LanStage = 'routes'
    foreach ($path in @('/kiosk', '/kiosk/events', '/tv', '/preview', '/admin/login', '/api/version', '/api/events', '/api/tags')) {
        $response = Invoke-LanRequest $trusted $path
        if ($path -in @('/kiosk', '/kiosk/events', '/tv', '/preview') -and $response.Text.Contains('http://')) { throw 'Plaintext display URL' }
    }
    $null = Invoke-LanRequest $trusted '/admin' 302
    $report.checks += 'routes'
    $script:LanStage = 'login'
    $loginPage = Invoke-LanRequest $trusted '/admin/login'
    if (-not $loginPage.Headers.ContainsKey('Set-Cookie') -or $loginPage.Headers['Set-Cookie'] -notmatch '(?i)secure' -or
        $loginPage.Headers['Set-Cookie'] -notmatch '(?i)httponly' -or $loginPage.Headers['Set-Cookie'] -notmatch '(?i)samesite=lax') { throw 'Secure cookie attributes missing' }
    $passwordSecure = if ($Wizard) { Read-LanPassword 'initial' } else { Read-Host 'Disposable admin password (same as on test server)' -AsSecureString }
    $password = [Net.NetworkCredential]::new('', $passwordSecure).Password
    $passwordSecure.Dispose()
    $null = Invoke-LanRequest $trusted '/admin/login' 403 ([Net.Http.StringContent]::new('username=admin&password=invalid', [Text.Encoding]::UTF8, 'application/x-www-form-urlencoded'))
    for ($attempt = 1; $attempt -le 3; $attempt++) {
        try {
            $null = Send-LanForm $trusted '/admin/login' @{username = 'admin'; password = $password}
            break
        } catch {
            if (-not $Wizard -or $script:LanResponseStatus -ne 401 -or $attempt -eq 3) { throw }
            Write-Host 'Пароль не подошёл. Введите первоначальный пароль из окна сервера ещё раз.' -ForegroundColor Yellow
            $retry = Read-LanPassword 'initial'
            try { $password = [Net.NetworkCredential]::new('', $retry).Password } finally { $retry.Dispose() }
        }
    }
    $null = Invoke-LanRequest $trusted '/admin'
    $report.checks += 'csrf_cookie_login'
    $script:LanStage = 'upload'
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
    $script:LanStage = 'password_revocation'
    foreach ($cookie in $trusted.Cookies.GetCookies($originUri)) { $stale.Cookies.Add($originUri, [Net.Cookie]::new($cookie.Name, $cookie.Value, $cookie.Path)) }
    if ($Wizard) { $newPassword = Read-LanReplacementPassword }
    else {
        $replacement = Read-Host 'New disposable password (remember for Chrome fullscreen; 12-128 characters)' -AsSecureString
        $newPassword = [Net.NetworkCredential]::new('', $replacement).Password
        $replacement.Dispose()
        $confirmation = Read-Host 'Confirm new disposable password' -AsSecureString
        try {
            if ($newPassword.Length -lt 12 -or $newPassword.Length -gt 128 -or $newPassword -cne [Net.NetworkCredential]::new('', $confirmation).Password) { throw 'Invalid new disposable password' }
        } finally { $confirmation.Dispose() }
    }
    $null = Send-LanForm $trusted '/admin/password/change' @{current_password = $password; new_password = $newPassword; confirm_password = $newPassword}
    $password = $null
    $null = Invoke-LanRequest $stale '/admin' 302
    $null = Send-LanForm $trusted '/admin/login' @{username = 'admin'; password = $newPassword}
    $null = Invoke-LanRequest $trusted '/admin'
    $newPassword = $null
    $report.checks += 'password_revocation'
    $script:LanStage = 'internal_ports_probe'
    foreach ($port in @($manifest.backend_port, $manifest.admin_port)) { Test-LanPortClosed $originUri.Host $port }
    $report.checks += 'internal_ports_closed'
    $script:LanStage = 'plaintext_probe'
    $plainHandler = [KioskLanTls]::CreateIPv4Handler()
    $plain = [Net.Http.HttpClient]::new($plainHandler)
    $plain.Timeout = [TimeSpan]::FromSeconds(5)
    $plaintext = $plain.GetAsync("http://$($originUri.Authority)/admin/login").GetAwaiter().GetResult()
    try {
        if ([int]$plaintext.StatusCode -ne 400 -or $plaintext.Headers.Contains('Set-Cookie')) { throw 'Plaintext service accepted request' }
        $report.http_statuses['400'] = 1
    } finally { $plaintext.Dispose() }
    $report.checks += 'plaintext_rejected'
    $script:LanStage = 'restart'
    $identity = (Invoke-LanRequest $trusted '/api/version').Headers['X-Kiosk-Instance']
    if (-not $identity) { throw 'Managed identity missing' }
    if ($Wizard) {
        Write-Host 'Перезапускаю тестовый сервер и проверяю сохранение входа…'
        Invoke-LanWizardCommand $trusted 'restart'
    } else { $null = Read-Host 'On SERVER enter restart; after readiness press Enter here (no browser trust yet)' }
    $null = Invoke-LanRequest $trusted '/admin'
    $newIdentity = (Invoke-LanRequest $trusted '/api/version').Headers['X-Kiosk-Instance']
    if (-not $newIdentity -or $newIdentity -eq $identity) { throw 'Managed restart not observed' }
    $report.checks += 'restart_session'
    $script:LanStage = 'forwarding'
    $spoof = @{'Forwarded' = 'for=198.51.100.1;proto=http;host=evil.invalid'; 'X-Forwarded-For' = '198.51.100.2';
        'X-Forwarded-Proto' = 'http'; 'X-Forwarded-Host' = 'evil.invalid'; 'X-Forwarded-Port' = '80'; 'X-Real-IP' = '198.51.100.3'}
    $null = Invoke-LanRequest $trusted '/api/version' 200 $null $spoof
    Test-LanHostRejection $trusted
    $report.checks += 'forwarding_host'
    $script:LanStage = 'authentication_budgets'
    if ($Wizard) { Write-Host 'Проверяю защиту входа и независимость двух компьютеров…' }
    else { $null = Read-Host 'Prepare SERVER budget command; press Enter to run remote authentication limits' }
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
    if ($Wizard) { Invoke-LanWizardCommand $trusted 'budget' }
    else { $null = Read-Host 'Within 30 seconds enter budget on SERVER; after success press Enter here' }
    if ($budgetTimer.Elapsed.TotalSeconds -ge 30) { throw 'Budget comparison window expired; repeat a fresh session' }
    $lastLimited = Send-LanForm $trusted '/admin/login' @{username = 'lan-still-exhausted'; password = 'invalid'} 429 $spoof
    if ($Wizard) { $script:LanBudgetWait = [int]$lastLimited.Headers['Retry-After'] }
    $report.checks += 'remote_budget_after_local'
    $report.success = $true
} catch {
    $report.error = $_.Exception.GetType().Name
    Write-LanFailure $_
    if ($Wizard) {
        Write-Host "`nЭтап не пройден. Не продолжайте проверку. Код: $($report.error)." -ForegroundColor Red
        Write-Host 'Проверьте адреса, пароль и доступ по сети. Сохраните это сообщение.'
        if ($null -ne $trusted) { try { Invoke-LanWizardCommand $trusted 'abort' } catch {} }
    }
} finally {
    $password = $null
    $newPassword = $null
    foreach ($resource in @($trusted, $untrusted, $stale, $plain, $authority)) { if ($null -ne $resource) { $resource.Dispose() } }
    if (-not $cleanupOnly) {
        $json = $report | ConvertTo-Json -Depth 6
        $stream = [IO.File]::Open([IO.Path]::GetFullPath($ReportFile), [IO.FileMode]::CreateNew, [IO.FileAccess]::Write)
        try {
            $bytes = [Text.Encoding]::UTF8.GetBytes($json)
            $stream.Write($bytes, 0, $bytes.Length)
        } finally { $stream.Dispose() }
        @{success = $report.success; error = $report.error; report = $ReportFile} | ConvertTo-Json -Compress
    }
}
if ($Wizard -and $report.success) {
    try { $script:LanStage = 'browser_wizard'; Complete-LanWizard $report $pem $ExpectedSha256 } catch {
        Write-LanFailure $_
        Write-Host 'Мастер не завершён. Сохраните папку клиента; повторный запуск предложит очистку.' -ForegroundColor Red
        exit 1
    }
}
if (-not $report.success) { exit 1 }
