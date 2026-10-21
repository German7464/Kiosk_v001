$script:LanBrowser = $null
$script:LanWizardState = $null
$script:LanBudgetWait = 0

function Confirm-LanStep {
    param([string]$Message)
    Write-Host "`n$Message" -ForegroundColor Cyan
    do { $answer = Read-Host 'Получилось? 1 — да, 2 — нет' } while ($answer -notin @('1','2'))
    if ($answer -ne '1') { throw 'operator_check_failed' }
}

function Save-LanWizardState {
    $script:LanWizardState | ConvertTo-Json | Set-Content -LiteralPath $script:LanStateFile -Encoding utf8
}

function Get-LanProfilePath {
    param([ValidateSet('A','B','C')][string]$Stage)
    $temporary = [IO.Path]::GetFullPath([IO.Path]::GetTempPath()).TrimEnd('\','/')
    $profile = [IO.Path]::GetFullPath((Join-Path $temporary "Kiosk-LAN-$($script:LanWizardState.session)-$Stage"))
    if ([IO.Path]::GetDirectoryName($profile) -cne $temporary) { throw 'unsafe_profile_path' }
    return $profile
}

function Stop-LanBrowser {
    if ($null -ne $script:LanBrowser) {
        try {
            if (-not $script:LanBrowser.HasExited) {
                $script:LanBrowser.Kill($true)
                if (-not $script:LanBrowser.WaitForExit(10000)) { throw 'browser_not_stopped' }
            }
        } finally { $script:LanBrowser.Dispose(); $script:LanBrowser = $null }
    }
}

function Remove-LanRoot {
    if ($script:LanWizardState.root_owned) {
        & "$PSScriptRoot/browser_trust.ps1" -Action remove -CertificateFile "$PSScriptRoot/authority.pem" -ExpectedSha256 $script:LanWizardState.digest | Out-Null
        if (-not $?) { throw 'root_cleanup_failed' }
        $inspection = & "$PSScriptRoot/browser_trust.ps1" -Action inspect -CertificateFile "$PSScriptRoot/authority.pem" -ExpectedSha256 $script:LanWizardState.digest | ConvertFrom-Json
        if ($inspection.present -ne 0) { throw 'root_cleanup_failed' }
        $script:LanWizardState.root_owned = $false
        Save-LanWizardState
    }
}

function Clear-LanWizard {
    $failed = $false
    try { Stop-LanBrowser } catch { $failed = $true }
    try { Remove-LanRoot } catch { $failed = $true }
    foreach ($stage in @('A','B','C')) {
        try {
            $profile = Get-LanProfilePath $stage
            if (Test-Path -LiteralPath $profile) {
                if (((Get-Item -LiteralPath $profile).Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0) { throw 'unsafe_profile_link' }
                $marker = Join-Path $profile '.kiosk-lan-owner'
                if (-not (Test-Path -LiteralPath $marker) -or [IO.File]::ReadAllText($marker) -cne $script:LanWizardState.session) { throw 'profile_not_owned' }
                Remove-Item -LiteralPath $profile -Recurse -Force
                if (Test-Path -LiteralPath $profile) { throw 'profile_cleanup_failed' }
            }
        } catch { $failed = $true }
    }
    if ($failed) { throw 'cleanup_incomplete' }
}

function Initialize-LanWizard {
    $script:LanStage = 'wizard_files'
    Write-Host "`nПРОВЕРКА KIOSK — ВТОРОЙ КОМПЬЮТЕР" -ForegroundColor Cyan
    $configuration = Get-Content -Raw -LiteralPath "$PSScriptRoot/wizard.json" | ConvertFrom-Json
    $sessionData = Get-Content -Raw -LiteralPath $SessionFile | ConvertFrom-Json
    if ($configuration.schema_version -ne 1 -or $configuration.session -cnotmatch '^[a-f0-9]{32}$' -or
        $configuration.session -cne $sessionData.session -or $configuration.token -cnotmatch '^[a-f0-9]{64}$') { throw 'invalid_wizard_bundle' }
    $script:LanControlToken = $configuration.token
    $script:LanStateFile = "$PSScriptRoot/wizard-cleanup.json"
    $certificate = [Security.Cryptography.X509Certificates.X509Certificate2]::CreateFromPem([IO.File]::ReadAllText("$PSScriptRoot/authority.pem"))
    try { $digest = [Convert]::ToHexString([Security.Cryptography.SHA256]::HashData($certificate.RawData)).ToLowerInvariant() } finally { $certificate.Dispose() }
    if (Test-Path -LiteralPath $script:LanStateFile) {
        $script:LanStage = 'cleanup_recovery'
        $saved = Get-Content -Raw -LiteralPath $script:LanStateFile | ConvertFrom-Json
        if ($saved.session -cne $configuration.session -or $saved.digest -cne $digest -or $saved.root_owned -isnot [bool]) { throw 'invalid_cleanup_state' }
        $script:LanWizardState = $saved
        Write-Host 'Найдена предыдущая попытка. Закройте её тестовые окна Chrome.'
        $null = Read-Host 'Нажмите Enter — удалить только её временное доверие и тестовые профили'
        Clear-LanWizard
        Write-Host 'Очистка выполнена. Для новой проверки заново запустите мастер на сервере и получите новый архив.' -ForegroundColor Green
        return $null
    }
    Write-Host "`nШАГ 1. Сравните эту строку со строкой в окне сервера. Копировать её не нужно:"
    $script:LanStage = 'fingerprint_comparison'
    Write-Host (([regex]::Matches($digest, '.{8}') | ForEach-Object Value) -join ' ') -ForegroundColor Yellow
    Confirm-LanStep 'Все восемь групп цифр и букв полностью совпадают с окном сервера?'
    $script:LanWizardState = [pscustomobject]@{session=$configuration.session; digest=$digest; root_owned=$false}
    Save-LanWizardState
    Write-Host "`nШАГ 2. Выполняю автоматические проверки. Когда потребуется — введите временный пароль."
    return $digest
}

function Read-LanPassword {
    param([string]$Kind)
    $message = switch ($Kind) {
        'initial' { 'Введите временный пароль, который задали в окне сервера' }
        'new' { 'Придумайте НОВЫЙ временный пароль от 12 символов и запомните его для браузера' }
        'confirm' { 'Повторите НОВЫЙ пароль' }
    }
    return Read-Host $message -AsSecureString
}

function Read-LanReplacementPassword {
    while ($true) {
        $first = Read-LanPassword 'new'
        $second = Read-LanPassword 'confirm'
        try {
            $value = [Net.NetworkCredential]::new('', $first).Password
            if ($value.Length -ge 12 -and $value.Length -le 128 -and $value -ceq [Net.NetworkCredential]::new('', $second).Password) { return $value }
            Write-Host 'Пароли должны совпадать и содержать 12–128 символов. Введите заново.' -ForegroundColor Yellow
        } finally { $first.Dispose(); $second.Dispose() }
    }
}

function Invoke-LanWizardCommand {
    param([KioskLanTls]$Transport, [string]$Action, $Value = $null)
    $data = @{action=$Action}
    if ($null -ne $Value) { $data.value = $Value }
    $content = [Net.Http.StringContent]::new(($data | ConvertTo-Json -Depth 8 -Compress), [Text.Encoding]::UTF8, 'application/json')
    $reply = (Invoke-LanRequest $Transport '/_lan-test/control' 202 $content @{'X-Lan-Test-Token'=$script:LanControlToken}).Text | ConvertFrom-Json
    if ($Action -eq 'close' -or $Action -eq 'abort') { return }
    $watch = [Diagnostics.Stopwatch]::StartNew()
    while ($watch.Elapsed.TotalSeconds -lt 50) {
        Start-Sleep -Milliseconds 300
        $query = [Net.Http.StringContent]::new((@{action='status';value=$reply.id} | ConvertTo-Json -Compress), [Text.Encoding]::UTF8, 'application/json')
        try { $status = (Invoke-LanRequest $Transport '/_lan-test/control' 200 $query @{'X-Lan-Test-Token'=$script:LanControlToken}).Text | ConvertFrom-Json } catch {
            if ($Action -eq 'restart') { continue }
            throw
        }
        if ($status.state -eq 'done') { return }
        if ($status.state -ne 'pending') { throw 'server_stage_failed' }
    }
    throw 'server_stage_timeout'
}

function Open-LanBrowser {
    param([ValidateSet('A','B','C')][string]$Stage, [string[]]$Paths = @('/kiosk/events'))
    Stop-LanBrowser
    $locations = @("$env:ProgramFiles/Google/Chrome/Application/chrome.exe", "${env:ProgramFiles(x86)}/Google/Chrome/Application/chrome.exe", "$env:LOCALAPPDATA/Google/Chrome/Application/chrome.exe")
    $chrome = $locations | Where-Object { Test-Path -LiteralPath $_ } | Select-Object -First 1
    if (-not $chrome) { throw 'chrome_not_found' }
    $profile = Get-LanProfilePath $Stage
    if (Test-Path -LiteralPath $profile) { throw 'profile_already_exists' }
    $null = New-Item -ItemType Directory -Path $profile
    [IO.File]::WriteAllText((Join-Path $profile '.kiosk-lan-owner'), $script:LanWizardState.session)
    $arguments = @("--user-data-dir=`"$profile`"", '--no-first-run', '--no-default-browser-check')
    foreach ($path in $Paths) { $arguments += ($script:origin + $path) }
    $script:LanBrowser = Start-Process -FilePath $chrome -ArgumentList $arguments -WindowStyle Normal -PassThru
}

function Complete-LanWizard {
    param([hashtable]$ClientReport, [string]$Pem, [string]$Digest)
    $transport = [KioskLanTls]::new($Pem, $Digest, $true)
    $complete = $false
    try {
        Invoke-LanWizardCommand $transport 'report' $ClientReport
        Write-Host "`nАвтоматические проверки пройдены. Отчёт уже передан серверу." -ForegroundColor Green
        if ($script:LanBudgetWait -gt 0) {
            Write-Host 'Подождите минуту: снимается тестовое ограничение входа для проверки браузера.'
            Start-Sleep -Seconds ([Math]::Min(61, $script:LanBudgetWait + 1))
        }
        Write-Host "`nШАГ 3. Сейчас откроется тестовый Chrome. Обычные окна Chrome не закрываются."
        Open-LanBrowser 'A'
        Confirm-LanStep 'В Chrome появилась ошибка ERR_CERT_AUTHORITY_INVALID? Не нажимайте обход предупреждения.'
        Invoke-LanWizardCommand $transport 'record' @{stage='untrusted';result='ERR_CERT_AUTHORITY_INVALID'}
        Stop-LanBrowser
        Write-Host "`nШАГ 4. Для продолжения нужно временно добавить ОДИН тестовый сертификат в доверие вашего пользователя Windows. В конце мастер его удалит."
        Confirm-LanStep 'Разрешаете временную установку проверенного тестового сертификата?'
        $inspection = & "$PSScriptRoot/browser_trust.ps1" -Action inspect -CertificateFile "$PSScriptRoot/authority.pem" -ExpectedSha256 $Digest | ConvertFrom-Json
        if ($inspection.present -ne 0) { throw 'root_already_exists' }
        $script:LanWizardState.root_owned = $true
        Save-LanWizardState
        & "$PSScriptRoot/browser_trust.ps1" -Action add -CertificateFile "$PSScriptRoot/authority.pem" -ExpectedSha256 $Digest | Out-Null
        if (-not $?) { throw 'root_enrollment_failed' }
        Open-LanBrowser 'B' @('/kiosk/events','/kiosk','/tv','/preview','/admin/login','/api/version','/api/events','/api/tags')
        Write-Host 'Проверьте открывшиеся вкладки: страницы и картинка должны загрузиться без ошибки сертификата.'
        Write-Host 'На вкладке preview перейдите в администрирование: адрес должен оставаться https.'
        Write-Host 'На странице киоска проверьте полный экран и выход из него: admin и НОВЫЙ временный пароль. Пароль в Chrome не сохраняйте.'
        Confirm-LanStep 'Все страницы и картинки открылись, переходы и полный экран работают?'
        Invoke-LanWizardCommand $transport 'record' @{stage='trusted';result='pages_images_navigation_fullscreen'}
        Write-Host "`nШАГ 5. Переключитесь на вкладку со списком событий. Страницу вручную не обновляйте."
        $null = Read-Host 'Когда вкладка открыта, нажмите Enter'
        Invoke-LanWizardCommand $transport 'update'
        Confirm-LanStep 'Подождите обновления. Название события САМО изменилось на LAN updated?'
        Invoke-LanWizardCommand $transport 'record' @{stage='updated';result='LAN_updated_visible_without_reload'}
        Write-Host "`nШАГ 6. Удаляю временное доверие и проверяю, что защита снова работает."
        Stop-LanBrowser
        Remove-LanRoot
        Open-LanBrowser 'C'
        Confirm-LanStep 'В свежем тестовом Chrome снова появилась ERR_CERT_AUTHORITY_INVALID?'
        Invoke-LanWizardCommand $transport 'record' @{stage='removed';result='ERR_CERT_AUTHORITY_INVALID'}
        Clear-LanWizard
        Invoke-LanWizardCommand $transport 'complete' @{client_cleanup=$true}
        Invoke-LanWizardCommand $transport 'close'
        $complete = $true
        Write-Host "`nГОТОВО. Проверки пройдены. Тестовые окна, профили и доверие сертификату удалены. На сервере дождитесь итогового сообщения." -ForegroundColor Green
    } finally {
        try { Clear-LanWizard } finally {
            if (-not $complete) { try { Invoke-LanWizardCommand $transport 'abort' } catch {} }
            $transport.Dispose()
        }
    }
}
