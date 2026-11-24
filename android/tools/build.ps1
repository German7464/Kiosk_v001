# android/tools/build.ps1
#
# Single entry point for the Android development workflow. Reproducible offline-capable
# check / build / deploy / journey without manually reconstructing Gradle/ADB commands,
# replacing signing keys, or resetting application data.
#
# Modes:
#   gradle   - run arbitrary Gradle tasks (previous thin wrapper; see -Tasks).
#   check    - selected fast JVM/static/fixture checks. No install, no launch, no device.
#   build    - assemble debug + sandbox + sandbox test APKs; report package id, version,
#              signer, SHA256 and a source fingerprint. No install, no launch.
#   deploy   - compatible same-signer sandbox replacement on an explicit device, preserving
#              application data. Refuses the retained original (org.kiosk.harness.debug)
#              app, a wrong device/package/signer, and a downgrade; verifies the installed
#              identity afterwards and FAILS (nonzero, without uninstalling) if preserved
#              state is not byte-identical.
#   journey  - consolidated local-fixture physical/instrumentation workflow: fixture
#              validation, build, data-preserving A->B sandbox replacement, affected sandbox
#              instrumentation, WebView process/data isolation, authoritative offline
#              content state, and original-app preservation. Local fixtures only; the live
#              18543 lab TLS has expired and is NOT exercised or bypassed here.
#   selftest - offline negative/positive gate self-test (mocked tool failures + pure gate
#              logic). No device, no Gradle. Proves the corrected gates reject failures
#              that the previous implementation silently accepted.
#
# Runtime requirements (see also android/README.md):
#   - Windows PowerShell 5.1 or PowerShell 7 (Core). Git on PATH.
#   - An existing full JDK (with keytool), an Android SDK with platform android-35,
#     build-tools 36.0.0 (aapt2/apksigner) and platform-tools (adb), a Gradle wrapper
#     with an offline dependency cache, and the existing debug keystore.
#   - selftest additionally uses the .NET Framework C# compiler (csc.exe) to build a mock
#     aapt2 that exits nonzero while still printing output; it is skipped with a note if
#     csc.exe is unavailable.
#
# Machine paths are supplied as arguments or via -Config (external JSON); they are never
# committed. A missing signer is never regenerated. check/build never install or launch.

param(
    [ValidateSet('gradle', 'check', 'build', 'deploy', 'journey', 'selftest')]
    [string]$Mode = 'gradle',

    # Machine/toolchain paths (external; keep out of Git).
    [string]$BuildJdk = '',
    [string]$AndroidSdk = '',
    [string]$ReadOnlyDependencyCache = '',
    [string]$DebugKeystore = '',
    [string]$JavaToolOptions = '',
    [string]$GradleUserHome = '',
    [string]$TestBuildType = '',

    # gradle mode pass-through tasks.
    [string[]]$Tasks = @(),

    # deploy / journey.
    [string]$Device = '',
    [string]$Package = '',
    [string]$Apk = '',
    [string]$ResultsDir = '',
    [string]$Config = '',

    # journey: authoritative offline content identity (defaults to the pinned "valid" bundle).
    [string]$ExpectedVisibleIdentity = ''
)

$ErrorActionPreference = 'Stop'

$RepoRoot = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)   # repository root
$HarnessRoot = Split-Path -Parent $PSScriptRoot                     # android/

$RetainedPackage = 'org.kiosk.harness.debug'
$SandboxPackage = 'org.kiosk.harness.sandbox'
$DefaultResultsDir = Join-Path $RepoRoot 'logs/android-workflow-consolidation-20261112'
$BuildToolsVersion = '36.0.0'

# Pinned content identities (mirror android/tools/check-fixtures.py IDENTITIES).
$ValidContentIdentity = '3658670566f16d0cb77e0f58facc10bcb2ec518100764421d3510ef1a604edfa'
$EmptyContentIdentity = 'bd6397715c21fb23d7d14a8052caa52fc8b6c53d83416db401e6b52ca6ccc7fd'

# Check-mode JVM subset: these classes must actually execute (tests >= 1 each).
$ExpectedCheckClasses = @(
    'org.kiosk.harness.admin.AdminNavigationPolicyTest',
    'org.kiosk.harness.pairing.PairingPayloadTest',
    'org.kiosk.harness.delivery.DeliveryClientRecoveryTest'
)


# ---------------------------------------------------------------------------
# External config merge (machine paths only; nothing secret is written here).
# ---------------------------------------------------------------------------
if ($Config) {
    if (!(Test-Path -LiteralPath $Config -PathType Leaf)) { throw "Config file not found: $Config" }
    $cfg = Get-Content -LiteralPath $Config -Raw | ConvertFrom-Json
    if (!$BuildJdk) { $BuildJdk = $cfg.buildJdk }
    if (!$AndroidSdk) { $AndroidSdk = $cfg.androidSdk }
    if (!$ReadOnlyDependencyCache) { $ReadOnlyDependencyCache = $cfg.readOnlyDependencyCache }
    if (!$DebugKeystore) { $DebugKeystore = $cfg.debugKeystore }
    if (!$JavaToolOptions) { $JavaToolOptions = $cfg.javaToolOptions }
    if (!$GradleUserHome) { $GradleUserHome = $cfg.gradleUserHome }
    if (!$Device) { $Device = $cfg.device }
    if (!$Package) { $Package = $cfg.package }
    if (!$ResultsDir) { $ResultsDir = $cfg.resultsDir }
    if (!$ExpectedVisibleIdentity) { $ExpectedVisibleIdentity = $cfg.expectedVisibleIdentity }
}

if (!$DebugKeystore) { $DebugKeystore = Join-Path $HarnessRoot '.gradle/debug.keystore' }
if (!$ResultsDir) { $ResultsDir = $DefaultResultsDir }
if (!$ExpectedVisibleIdentity) { $ExpectedVisibleIdentity = $ValidContentIdentity }

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
function Invoke-Native([string]$Program, [string[]]$Arguments) {
    & $Program @Arguments
    if ($LASTEXITCODE -ne 0) { throw "$Program failed: $LASTEXITCODE" }
}

function Get-StringSha256([string]$s) {
    $sha = [System.Security.Cryptography.SHA256]::Create()
    $bytes = [System.Text.Encoding]::UTF8.GetBytes($s)
    $hash = $sha.ComputeHash($bytes)
    return ($hash | ForEach-Object { $_.ToString('x2') }) -join ''
}

function Write-FailureRecord([string]$message, [int]$code) {
    try {
        $runDir = Join-Path $ResultsDir 'runs'
        New-Item -ItemType Directory -Force -Path $runDir | Out-Null
        $ts = (Get-Date).ToUniversalTime().ToString('yyyyMMdd-HHmmss-fff')
        $rec = [ordered]@{
            status = 'failed'
            mode = $Mode
            branch = (& git -C $RepoRoot branch --show-current 2>$null).Trim()
            head = (& git -C $RepoRoot rev-parse HEAD 2>$null).Trim()
            generated_at_utc = (Get-Date).ToUniversalTime().ToString('o')
            exit_code = $code
            error = $message
        }
        $rec | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath (Join-Path $runDir "failed-$Mode-$ts.json") -Encoding utf8
        Set-Content -LiteralPath (Join-Path $ResultsDir 'last-run.json') -Value ($rec | ConvertTo-Json -Depth 8) -Encoding utf8
    } catch { }
}

function Fail([string]$message, [int]$code = 2) {
    Write-Host "ERROR: $message" -ForegroundColor Red
    Write-FailureRecord $message $code
    exit $code
}

function Resolve-Tool([string]$relative, [string]$name) {
    $path = Join-Path $AndroidSdk $relative
    if (!(Test-Path -LiteralPath $path)) { Fail "Missing tool $name at $path" 2 }
    return $path
}

function Get-ApkIdentity([string]$apkPath) {
    # Throws (not exit) so callers can catch and turn it into a structured refusal.
    if (!(Test-Path -LiteralPath $apkPath -PathType Leaf)) { throw "APK not found: $apkPath" }
    $aapt2 = Resolve-Tool "build-tools/$BuildToolsVersion/aapt2.exe" 'aapt2'
    $apksigner = Resolve-Tool "build-tools/$BuildToolsVersion/apksigner.bat" 'apksigner'

    # aapt2 exit status is authoritative, not merely the parseability of its output.
    $badgingOut = & $aapt2 dump badging $apkPath 2>&1
    if ($LASTEXITCODE -ne 0) { throw "aapt2 dump badging failed (exit $LASTEXITCODE) for $apkPath" }
    $badging = $badgingOut -join "`n"
    $pkgLine = [regex]::Match($badging, "package: name='([^']+)' versionCode='([^']*)' versionName='([^']*)'")
    if (!$pkgLine.Success) { throw "aapt2 output did not include package id/version for $apkPath" }

    # apksigner must exit 0 for a validly-signed APK; do not accept a digest on a failed verify.
    $certsOut = & $apksigner verify --print-certs $apkPath 2>&1
    if ($LASTEXITCODE -ne 0) { throw "apksigner verify failed (exit $LASTEXITCODE) for $apkPath" }
    $certs = $certsOut -join "`n"
    $signer = [regex]::Match($certs, 'SHA-256 digest:\s*([0-9a-fA-F]+)').Groups[1].Value.ToLowerInvariant()
    if (!$signer) { throw "apksigner output did not include a signer digest for $apkPath" }

    $bytes = (Get-Item -LiteralPath $apkPath).Length
    $sha256 = (Get-FileHash -LiteralPath $apkPath -Algorithm SHA256).Hash.ToLowerInvariant()
    $vcRaw = $pkgLine.Groups[2].Value
    return [ordered]@{
        path = $apkPath
        package = $pkgLine.Groups[1].Value
        versionCode = if ($vcRaw -eq '') { 0 } else { [int]$vcRaw }
        versionName = $pkgLine.Groups[3].Value
        signerSha256 = $signer
        sha256 = $sha256
        bytes = $bytes
    }
}

function Get-SourceFingerprint {
    # SHA-256 of raw working-tree file bytes for every tracked android/ file plus every
    # untracked non-ignored android/ file. These are content hashes, NOT Git blob object IDs
    # (which are SHA-1), so the fingerprint reflects the actual working tree regardless of
    # core.autocrlf or object-format. HEAD + dirty flag are folded in to distinguish a clean
    # checkout from a dirty one with an unchanged HEAD.
    $head = (& git -C $RepoRoot rev-parse HEAD 2>$null).Trim()
    $status = & git -C $RepoRoot status --porcelain -- android 2>$null
    $dirty = [bool]$status
    $tracked = & git -C $RepoRoot ls-files -- android 2>$null
    $others = & git -C $RepoRoot ls-files --others --exclude-standard -- android 2>$null
    $lines = New-Object System.Collections.Generic.List[string]
    foreach ($f in $tracked) {
        $full = Join-Path $RepoRoot $f
        if (Test-Path -LiteralPath $full -PathType Leaf) {
            $h = (Get-FileHash -LiteralPath $full -Algorithm SHA256).Hash.ToLowerInvariant()
            $lines.Add("T`t$f`t$h")
        }
    }
    foreach ($f in $others) {
        $full = Join-Path $RepoRoot $f
        if (Test-Path -LiteralPath $full -PathType Leaf) {
            $h = (Get-FileHash -LiteralPath $full -Algorithm SHA256).Hash.ToLowerInvariant()
            $lines.Add("U`t$f`t$h")
        }
    }
    $sorted = $lines | Sort-Object
    $all = (("head=$head", "dirty=$dirty") + $sorted) -join "`n"
    return [ordered]@{
        head = $head
        dirty = $dirty
        trackedFiles = @($tracked).Count
        untrackedNonIgnoredFiles = @($others).Count
        algorithm = 'sha256'
        algorithmNote = 'SHA-256 of raw working-tree file bytes (CRLF preserved); NOT Git blob object IDs.'
        sha256 = Get-StringSha256 $all
    }
}

function Get-JvmTestResult([string[]]$expectedClasses) {
    $dir = Join-Path $HarnessRoot 'app/build/test-results/testDebugUnitTest'
    $tests = 0; $failures = 0; $errors = 0; $skipped = 0
    $suites = @{}
    if (Test-Path -LiteralPath $dir) {
        foreach ($file in Get-ChildItem -LiteralPath $dir -Filter 'TEST-*.xml') {
            try {
                [xml]$x = Get-Content -LiteralPath $file.FullName -Raw
                $name = $x.testsuite.name
                $n = [int]$x.testsuite.tests
                $tests += $n
                $failures += [int]$x.testsuite.failures
                $errors += [int]$x.testsuite.errors
                $skipped += [int]$x.testsuite.skipped
                $suites[$name] = [ordered]@{
                    tests = $n
                    failures = [int]$x.testsuite.failures
                    errors = [int]$x.testsuite.errors
                    skipped = [int]$x.testsuite.skipped
                    file = $file.Name
                }
            } catch { }
        }
    }
    $missing = @()
    foreach ($c in $expectedClasses) { if (!$suites.ContainsKey($c)) { $missing += $c } }
    return [ordered]@{
        totals = [ordered]@{ tests = $tests; failures = $failures; errors = $errors; skipped = $skipped }
        suites = $suites
        missingExpected = $missing
        expectedClasses = $expectedClasses
    }
}

function Test-JvmGate($jvm, [int]$minTests) {
    $t = $jvm.totals
    if ($t.tests -lt $minTests) { return [ordered]@{ ok = $false; reason = "parsed $($t.tests) tests (expected >= $minTests)" } }
    if ($t.failures -ne 0) { return [ordered]@{ ok = $false; reason = "$($t.failures) test failure(s)" } }
    if ($t.errors -ne 0) { return [ordered]@{ ok = $false; reason = "$($t.errors) test error(s)" } }
    if ($jvm.missingExpected.Count -gt 0) { return [ordered]@{ ok = $false; reason = "expected suites missing: $($jvm.missingExpected -join ', ')" } }
    foreach ($c in $jvm.expectedClasses) {
        if ($jvm.suites[$c].tests -lt 1) { return [ordered]@{ ok = $false; reason = "$c executed 0 tests" } }
    }
    return [ordered]@{ ok = $true; reason = '' }
}

function Assert-Prerequisites([switch]$NeedDevice) {
    if (!$BuildJdk -or !(Test-Path -LiteralPath (Join-Path $BuildJdk 'bin/javac.exe'))) {
        Fail 'A full compatible build JDK is required (-BuildJdk or -Config).' 2
    }
    if (!$AndroidSdk -or !(Test-Path -LiteralPath (Join-Path $AndroidSdk 'platforms/android-35/android.jar'))) {
        Fail 'SDK platform 35 is required (-AndroidSdk or -Config).' 2
    }
    $env:JAVA_HOME = $BuildJdk
    # Host-specific JVM networking options belong in external configuration.
    # Apply to the wrapper, daemon and test workers without changing OS networking.
    if ($JavaToolOptions -and $env:JAVA_TOOL_OPTIONS -notlike "*$JavaToolOptions*") {
        $env:JAVA_TOOL_OPTIONS = ($env:JAVA_TOOL_OPTIONS + ' ' + $JavaToolOptions).Trim()
    }
    $env:ANDROID_HOME = $AndroidSdk
    $env:GRADLE_USER_HOME = if ($GradleUserHome) { $GradleUserHome } else { Join-Path $HarnessRoot '.gradle/user-home' }
    if ($ReadOnlyDependencyCache) { $env:GRADLE_RO_DEP_CACHE = $ReadOnlyDependencyCache }
    New-Item -ItemType Directory -Force -Path (Join-Path $HarnessRoot '.gradle') | Out-Null
    if (!(Test-Path -LiteralPath $DebugKeystore -PathType Leaf)) {
        Fail 'Existing debug signer required; never regenerate a lost device signer during build.' 2
    }
    if ($NeedDevice) {
        if (!$Device) { Fail 'A device serial is required (-Device or -Config).' 2 }
        $adb = Resolve-Tool 'platform-tools/adb.exe' 'adb'
        $state = (& $adb -s $Device get-state 2>&1 | Select-Object -Last 1)
        if ($state -ne 'device') { Fail "Device $Device is not in 'device' state (got '$state')." 3 }
    }
}

function Invoke-Gradle([string[]]$gradleTasks, [string[]]$extra) {
    $resolved = (Resolve-Path -LiteralPath $DebugKeystore).Path
    $arguments = @('-p', $HarnessRoot, "-PkioskDebugKeystore=$resolved")
    if ($TestBuildType) { $arguments += "-PkioskTestBuildType=$TestBuildType" }
    $arguments += $gradleTasks
    $arguments += $extra
    Invoke-Native (Join-Path $HarnessRoot 'gradlew.bat') $arguments
}

function Get-AppState([string]$pkg) {
    # Distinguishes a legitimate fresh/empty sandbox from an unreadable one. A read is only
    # accepted when the data directory is reachable and the sentinels are present; run-as
    # failures and missing markers produce readable=false instead of silently-empty values.
    $adb = Resolve-Tool 'platform-tools/adb.exe' 'adb'
    $template = 'cd /data/user/0/{0} || {{ echo __RUNAS_FAIL__; exit 7; }}; echo __READ_OK__; if [ -f no_backup/delivery-v1.enc ]; then echo __ENC_PRESENT__; sha256sum no_backup/delivery-v1.enc; else echo __ENC_ABSENT__; fi; if [ -d files ]; then echo __FILES_PRESENT__; find files -type f | wc -l; find files -type f | sort | xargs sha256sum | sha256sum; else echo __FILES_ABSENT__; fi'
    $script = $template -f $pkg
    $out = & $adb -s $Device shell "run-as $pkg sh -c '$script'" 2>&1
    $code = $LASTEXITCODE
    $joined = ($out | ForEach-Object { $_.ToString() }) -join "`n"

    if ($joined -match '__RUNAS_FAIL__') {
        return [ordered]@{ readable = $false; error = "data directory unreachable: $($joined.Trim())"; deliveryStatePresent = $false; deliveryStateSha256 = $null; filesPresent = $false; filesCount = $null; filesTreeSha256 = $null }
    }
    if ($joined -notmatch '__READ_OK__') {
        return [ordered]@{ readable = $false; error = "run-as produced no READ_OK marker (adb exit $code): $($joined.Trim())"; deliveryStatePresent = $false; deliveryStateSha256 = $null; filesPresent = $false; filesCount = $null; filesTreeSha256 = $null }
    }

    $deliveryPresent = $joined -match '__ENC_PRESENT__'
    $filesPresent = $joined -match '__FILES_PRESENT__'
    $encSha = $null; $filesCount = $null; $treeSha = $null
    $mode = ''
    foreach ($raw in $out) {
        $line = ($raw -as [string]).Trim()
        if ($line -eq '__ENC_PRESENT__') { $mode = 'enc' }
        elseif ($line -eq '__ENC_ABSENT__') { $mode = '' }
        elseif ($line -eq '__FILES_PRESENT__') { $mode = 'count' }
        elseif ($line -eq '__FILES_ABSENT__') { $mode = '' }
        elseif ($mode -eq 'enc') { $encSha = ($line -split '\s+')[0]; $mode = '' }
        elseif ($mode -eq 'count') { $filesCount = ($line -replace '\s', ''); $mode = 'tree' }
        elseif ($mode -eq 'tree') { $treeSha = ($line -split '\s+')[0]; $mode = '' }
    }

    return [ordered]@{
        readable = $true
        error = ''
        deliveryStatePresent = $deliveryPresent
        deliveryStateSha256 = $encSha
        filesPresent = $filesPresent
        filesCount = $filesCount
        filesTreeSha256 = $treeSha
    }
}

function Get-InstalledSigner([string]$pkg) {
    $id = Get-InstalledIdentity $pkg
    if (!$id.installed -or $id.error) { return '' }
    return $id.signerSha256
}

function Get-InstalledIdentity([string]$pkg) {
    $adb = Resolve-Tool 'platform-tools/adb.exe' 'adb'
    $empty = [ordered]@{ installed = $false; error = ''; package = $pkg; signerSha256 = ''; sha256 = ''; versionCode = 0; versionName = ''; bytes = 0 }
    $pathOut = & $adb -s $Device shell "pm path $pkg" 2>&1
    $pathLine = $pathOut | Where-Object { $_ -match '^package:' } | Select-Object -First 1
    if (!$pathLine) { $empty['error'] = "pm path returned no package line: $(($pathOut -join ' ').Trim())"; return $empty }
    $remote = $pathLine.ToString().Trim().Replace('package:', '')
    $tmp = Join-Path ([System.IO.Path]::GetTempPath()) ("kiosk-" + [guid]::NewGuid().ToString('n') + '.apk')
    & $adb -s $Device pull $remote $tmp 2>&1 | Out-Null
    if (!(Test-Path -LiteralPath $tmp) -or (Get-Item -LiteralPath $tmp).Length -eq 0) {
        $empty['installed'] = $true; $empty['error'] = "pull failed for $remote"; return $empty
    }
    try {
        $id = Get-ApkIdentity $tmp
        $id['installed'] = $true
        $id['error'] = ''
        return $id
    } catch {
        $empty['installed'] = $true; $empty['error'] = $_.Exception.Message; return $empty
    } finally {
        Remove-Item -LiteralPath $tmp -Force -ErrorAction SilentlyContinue
    }
}

function Get-LastUpdateTime([string]$pkg) {
    $adb = Resolve-Tool 'platform-tools/adb.exe' 'adb'
    $out = & $adb -s $Device shell "dumpsys package $pkg | grep lastUpdateTime" 2>&1
    $txt = $out -join "`n"
    if ($txt -match 'lastUpdateTime=([0-9-]+ [0-9:]+)') { return $Matches[1] }
    return ''
}

function Get-DeviceClock {
    # Delivery validates bootstrap/renewal windows against the DEVICE clock, so acceptance evidence
    # must record that clock instead of the PC's. auto_time shows whether it is network-derived; the
    # offset is reported, never "corrected", since changing device time is out of scope here.
    $adb = Resolve-Tool 'platform-tools/adb.exe' 'adb'
    $raw = (& $adb -s $Device shell 'date +%s' 2>&1 | Select-Object -Last 1)
    $txt = ($raw -as [string]).Trim()
    $deviceEpoch = 0L
    $pcEpoch = [DateTimeOffset]::UtcNow.ToUnixTimeSeconds()
    if (![long]::TryParse($txt, [ref]$deviceEpoch) -or $deviceEpoch -le 0) {
        return [ordered]@{ ok = $false; error = "unreadable device clock: '$txt'"; deviceEpoch = $null; deviceUtc = ''; pcEpoch = $pcEpoch; offsetSeconds = $null; autoTime = ''; autoTimeZone = '' }
    }
    $autoTime = ((& $adb -s $Device shell 'settings get global auto_time' 2>&1 | Select-Object -Last 1) -as [string]).Trim()
    $autoZone = ((& $adb -s $Device shell 'settings get global auto_time_zone' 2>&1 | Select-Object -Last 1) -as [string]).Trim()
    return [ordered]@{
        ok = $true
        error = ''
        deviceEpoch = $deviceEpoch
        deviceUtc = [DateTimeOffset]::FromUnixTimeSeconds($deviceEpoch).ToString('o')
        pcEpoch = $pcEpoch
        offsetSeconds = $deviceEpoch - $pcEpoch
        autoTime = $autoTime
        autoTimeZone = $autoZone
    }
}

function Test-DeployPreconditions($candidate, $installed, [string]$originalSigner) {
    if (!$originalSigner) { return [ordered]@{ ok = $false; reason = 'original signer unreadable' } }
    if ($candidate.signerSha256 -ne $originalSigner) { return [ordered]@{ ok = $false; reason = 'candidate signer does not match original signer' } }
    if ($installed -and $installed.installed) {
        if ($installed.error) { return [ordered]@{ ok = $false; reason = "installed target unverifiable: $($installed.error)" } }
        if ($installed.signerSha256 -ne $originalSigner) { return [ordered]@{ ok = $false; reason = 'installed target has a different signer (destructive replacement refused)' } }
        if ($candidate.versionCode -lt $installed.versionCode) { return [ordered]@{ ok = $false; reason = "downgrade refused ($($candidate.versionCode) < $($installed.versionCode))" } }
    }
    return [ordered]@{ ok = $true; reason = '' }
}

function Test-Preservation($before, $after) {
    if (!$after.readable) { return [ordered]@{ ok = $false; reason = "post-deploy state unreadable: $($after.error)" } }
    if ($before.deliveryStatePresent) {
        if (!$after.deliveryStatePresent) { return [ordered]@{ ok = $false; reason = 'delivery state lost' } }
        if ($before.deliveryStateSha256 -ne $after.deliveryStateSha256) { return [ordered]@{ ok = $false; reason = 'delivery state changed' } }
    }
    if ($before.filesPresent) {
        if (!$after.filesPresent) { return [ordered]@{ ok = $false; reason = 'files directory lost' } }
        if ($before.filesCount -ne $after.filesCount) { return [ordered]@{ ok = $false; reason = "files count changed ($($before.filesCount) -> $($after.filesCount))" } }
        if ($before.filesTreeSha256 -ne $after.filesTreeSha256) { return [ordered]@{ ok = $false; reason = 'files tree changed' } }
    }
    return [ordered]@{ ok = $true; reason = '' }
}

function Test-OfflineContent([string]$uiText, [string]$expectedVisible) {
    $n = $uiText -replace '&#10;', ' ' -replace '&#xA;', ' ' -replace "`r", ' ' -replace "`n", ' '
    $st = [regex]::Match($n, '(?:^|\s)state=([A-Za-z]+)')
    $vis = [regex]::Match($n, '(?:^|\s)visible=([0-9a-fA-F]+|none)')
    $state = if ($st.Success) { $st.Groups[1].Value } else { '' }
    $visible = if ($vis.Success) { $vis.Groups[1].Value.ToLowerInvariant() } else { '' }
    if ($state -ne 'ready') { return [ordered]@{ ok = $false; state = $state; visible = $visible; reason = "state not ready (state='$state')" } }
    if ($visible -eq '' -or $visible -eq 'none') { return [ordered]@{ ok = $false; state = $state; visible = $visible; reason = 'no visible content identity' } }
    if ($visible -ne $expectedVisible) { return [ordered]@{ ok = $false; state = $state; visible = $visible; reason = "visible identity '$visible' != expected '$expectedVisible'" } }
    return [ordered]@{ ok = $true; state = $state; visible = $visible; reason = '' }
}

function Test-ManifestAdminProcess([string]$apkPath) {
    $aapt2 = Resolve-Tool "build-tools/$BuildToolsVersion/aapt2.exe" 'aapt2'
    $out = & $aapt2 dump xmltree $apkPath --file AndroidManifest.xml 2>&1
    if ($LASTEXITCODE -ne 0) { $out = & $aapt2 dump xmltree $apkPath AndroidManifest.xml 2>&1 }
    if ($LASTEXITCODE -ne 0) { return [ordered]@{ ok = $false; reason = "aapt2 xmltree failed (exit $LASTEXITCODE)" } }
    $inAdmin = $false; $hasProcess = $false
    foreach ($raw in $out) {
        $l = $raw.ToString()
        if ($l -match 'E: activity') { $inAdmin = $false; $hasProcess = $false }
        if ($l -match 'AdminActivity') { $inAdmin = $true }
        if ($inAdmin -and $l -match 'android:process' -and $l -match ':admin') { $hasProcess = $true; break }
    }
    if ($inAdmin -and $hasProcess) { return [ordered]@{ ok = $true; reason = ''; evidence = 'AdminActivity declared with android:process=":admin"' } }
    return [ordered]@{ ok = $false; reason = 'AdminActivity not found with android:process=":admin" in the built manifest' }
}

function Test-WebViewIsolation([string]$pkg, [hashtable]$manifestCheck) {
    $adb = Resolve-Tool 'platform-tools/adb.exe' 'adb'
    $display = (& $adb -s $Device shell "run-as $pkg sh -c 'test -d app_webview && echo yes || echo no'" 2>&1) -join ''
    $admin = (& $adb -s $Device shell "run-as $pkg sh -c 'test -d app_webview_admin && echo yes || echo no'" 2>&1) -join ''
    $displayObserved = $display -match 'yes'
    $adminObserved = $admin -match 'yes'
    $processOk = $manifestCheck.ok
    $dirsDistinct = $displayObserved -and $adminObserved
    # Isolation is proven by the private ":admin" process plus a distinct admin data directory
    # (setDataDirectorySuffix("admin")). No cookie values or other private state are read.
    $ok = $processOk -and $dirsDistinct
    $note = if (!$processOk) { $manifestCheck.reason } elseif (!$dirsDistinct) { 'admin WebView data directory not observed (requires a prior admin launch)' } else { '' }
    return [ordered]@{ ok = $ok; processIsolation = $processOk; displayDirObserved = $displayObserved; adminDirObserved = $adminObserved; dirsDistinct = $dirsDistinct; note = $note }
}

function Get-KeytoolSha256([string[]]$arguments) {
    $kt = Join-Path $BuildJdk 'bin/keytool.exe'
    if (!(Test-Path -LiteralPath $kt -PathType Leaf)) { return '' }
    $out = & $kt @arguments 2>&1
    if ($LASTEXITCODE -ne 0) { return '' }
    $m = [regex]::Match(($out -join "`n"), 'SHA256:\s*((?:[0-9A-Fa-f]{2}:?)+)')
    if (!$m.Success) { return '' }
    return ($m.Groups[1].Value -replace ':', '').ToLowerInvariant()
}

function Get-KeytoolFirstIssuer([string[]]$arguments) {
    $kt = Join-Path $BuildJdk 'bin/keytool.exe'
    if (!(Test-Path -LiteralPath $kt -PathType Leaf)) { return '' }
    $out = & $kt @arguments 2>&1
    if ($LASTEXITCODE -ne 0) { return '' }
    foreach ($line in $out) {
        if ($line -match 'Issuer:\s*(.+)$') { return $Matches[1].Trim() }
    }
    return ''
}

function Assert-AdminTlsFixtures {
    $kt = Join-Path $BuildJdk 'bin/keytool.exe'
    if (!(Test-Path -LiteralPath $kt -PathType Leaf)) { return [ordered]@{ ok = $false; reason = "keytool not found under $BuildJdk/bin" } }
    $trusted = Join-Path $HarnessRoot 'app/src/androidTest/assets/admin-tls/trusted.p12'
    $untrusted = Join-Path $HarnessRoot 'app/src/androidTest/assets/admin-tls/untrusted.p12'
    $caPem = Join-Path $HarnessRoot 'app/src/sandbox/res/raw/admin_fixture_ca.pem'
    $labCa = Join-Path $HarnessRoot 'app/src/sandbox/res/raw/lab_ca.pem'
    $nsc = Join-Path $HarnessRoot 'app/src/sandbox/res/xml/network_security_config.xml'
    $missing = @()
    foreach ($p in @($trusted, $untrusted, $caPem, $labCa, $nsc)) { if (!(Test-Path -LiteralPath $p -PathType Leaf)) { $missing += $p } }
    if ($missing.Count) { return [ordered]@{ ok = $false; reason = "missing fixture: $($missing -join ', ')" } }

    $caFp = Get-KeytoolSha256 @('-printcert', '-file', $caPem)
    $labFp = Get-KeytoolSha256 @('-printcert', '-file', $labCa)
    if (!$caFp) { return [ordered]@{ ok = $false; reason = 'admin_fixture_ca.pem has no readable certificate' } }
    if (!$labFp) { return [ordered]@{ ok = $false; reason = 'lab_ca.pem has no readable certificate' } }
    if ($caFp -eq $labFp) { return [ordered]@{ ok = $false; reason = 'admin_fixture_ca.pem equals lab_ca.pem (fixture CA must be distinct)' } }

    $trustedCaFp = Get-KeytoolSha256 @('-list', '-v', '-keystore', $trusted, '-storepass', 'changeit', '-alias', 'ca')
    $trustedIssuer = Get-KeytoolFirstIssuer @('-list', '-v', '-keystore', $trusted, '-storepass', 'changeit', '-alias', 'server')
    if ($trustedCaFp -and $trustedCaFp -ne $caFp) { return [ordered]@{ ok = $false; reason = 'trusted.p12 CA alias does not match admin_fixture_ca.pem' } }
    if ($trustedIssuer -and $trustedIssuer -notmatch 'Admin fixture CA') { return [ordered]@{ ok = $false; reason = "trusted.p12 server not issued by fixture CA (issuer='$trustedIssuer')" } }

    $untrustedIssuer = Get-KeytoolFirstIssuer @('-list', '-v', '-keystore', $untrusted, '-storepass', 'changeit', '-alias', 'server')
    if ($untrustedIssuer -and $untrustedIssuer -match 'Admin fixture CA') { return [ordered]@{ ok = $false; reason = 'untrusted.p12 is issued by the fixture CA (must be self-signed)' } }

    $nscText = Get-Content -LiteralPath $nsc -Raw
    if ($nscText -notmatch '@raw/admin_fixture_ca') { return [ordered]@{ ok = $false; reason = 'sandbox network_security_config does not reference @raw/admin_fixture_ca' } }
    if ($nscText -notmatch 'debug-overrides') { return [ordered]@{ ok = $false; reason = 'sandbox network_security_config does not scope the fixture CA under debug-overrides' } }

    return [ordered]@{ ok = $true; reason = ''; caFp = $caFp; labFp = $labFp; trustedIssuer = $trustedIssuer; untrustedIssuer = $untrustedIssuer }
}

function Get-PemCertificateSha256([string]$pem, [string]$what) {
    if (([regex]::Matches($pem, '-----BEGIN CERTIFICATE-----')).Count -ne 1) { throw "$what must contain exactly one CERTIFICATE block" }
    $body = (($pem -split "`n") | Where-Object { $_ -notmatch '-----' }) -join ''
    $der = [Convert]::FromBase64String($body)
    $sha = [System.Security.Cryptography.SHA256]::Create()
    try { return (($sha.ComputeHash($der) | ForEach-Object { $_.ToString('x2') }) -join '') } finally { $sha.Dispose() }
}

function Assert-SandboxBootstrapAnchor {
    # The sandbox WebView trusts exactly the raw anchor resource named in its debug-overrides. The
    # packaged bootstrap must name that same single root: a stale or mixed CA set would make WebView
    # TLS and the native bootstrap disagree. This proves fixture consistency, not production trust,
    # and never installs anything outside the disposable app.
    $asset = Join-Path $HarnessRoot 'app/src/sandbox/assets/delivery-bootstrap-sandbox.json'
    $anchor = Join-Path $HarnessRoot 'app/src/sandbox/res/raw/lab_ca.pem'
    $nsc = Join-Path $HarnessRoot 'app/src/sandbox/res/xml/network_security_config.xml'
    $missing = @()
    foreach ($p in @($asset, $anchor, $nsc)) { if (!(Test-Path -LiteralPath $p -PathType Leaf)) { $missing += $p } }
    if ($missing.Count) { return [ordered]@{ ok = $false; reason = "missing sandbox anchor input: $($missing -join ', ')" } }
    if ((Get-Content -LiteralPath $nsc -Raw) -notmatch '@raw/lab_ca') { return [ordered]@{ ok = $false; reason = 'sandbox network_security_config does not anchor @raw/lab_ca' } }
    try {
        $json = Get-Content -LiteralPath $asset -Raw | ConvertFrom-Json
        $bootstrapFp = Get-PemCertificateSha256 ([string]$json.tls_ca_pem) 'sandbox bootstrap tls_ca_pem'
        $anchorFp = Get-PemCertificateSha256 ([string](Get-Content -LiteralPath $anchor -Raw)) 'lab_ca.pem'
        $issued = 0L; $expires = 0L
        $issuedOk = [long]::TryParse([string]$json.issued_at, [ref]$issued)
        $expiresOk = [long]::TryParse([string]$json.expires_at, [ref]$expires)
    } catch { return [ordered]@{ ok = $false; reason = "sandbox anchor unreadable: $($_.Exception.Message)" } }
    if ($bootstrapFp -ne $anchorFp) { return [ordered]@{ ok = $false; reason = "sandbox bootstrap CA $bootstrapFp differs from WebView anchor $anchorFp" } }
    if (!$issuedOk -or !$expiresOk) { return [ordered]@{ ok = $false; reason = 'sandbox bootstrap issued_at/expires_at are not integers' } }

    # Name the exact public inputs the packaged fixture carries, so acceptance evidence identifies
    # the tested bundle instead of an unnamed "current" file. File facts only: whether the window is
    # still open is decided against the DEVICE clock by Test-BootstrapWindow in journey.
    return [ordered]@{
        ok = $true
        reason = ''
        caFp = $bootstrapFp
        bootstrapId = [string]$json.bootstrap_id
        groupId = [string]$json.group_id
        serverId = [string]$json.server_id
        origin = [string]$json.origin
        issuedAt = $issued
        expiresAt = $expires
        issuedAtUtc = [DateTimeOffset]::FromUnixTimeSeconds($issued).ToUniversalTime().ToString('o')
        expiresAtUtc = [DateTimeOffset]::FromUnixTimeSeconds($expires).ToUniversalTime().ToString('o')
        fileSha256 = (Get-FileHash -LiteralPath $asset -Algorithm SHA256).Hash.ToLowerInvariant()
        scope = 'isolated pilot fixture from the public handoff, not production trust provisioning'
    }
}

function Test-BootstrapWindow($bootstrap, [long]$nowSeconds) {
    # Mirrors DeliveryProtocol.bootstrap's window rule (issued <= now < expires, issued < expires).
    # It only decides whether the packaged fixture can be exercised at all: the app re-validates the
    # real bootstrap bytes itself and stays authoritative. Expiry is never bypassed here.
    $issued = 0L; $expires = 0L
    if (![long]::TryParse([string]$bootstrap.issued_at, [ref]$issued)) { return [ordered]@{ ok = $false; reason = 'issued_at is not an integer' } }
    if (![long]::TryParse([string]$bootstrap.expires_at, [ref]$expires)) { return [ordered]@{ ok = $false; reason = 'expires_at is not an integer' } }
    if ($issued -ge $expires) { return [ordered]@{ ok = $false; reason = "issued_at $issued is not before expires_at $expires" } }
    if ($nowSeconds -lt $issued) { return [ordered]@{ ok = $false; reason = "device clock $nowSeconds precedes issued_at $issued" } }
    if ($nowSeconds -ge $expires) { return [ordered]@{ ok = $false; reason = "expired at $([DateTimeOffset]::FromUnixTimeSeconds($expires).ToUniversalTime().ToString('o')); device clock $nowSeconds" } }
    return [ordered]@{ ok = $true; reason = ''; remainingSeconds = $expires - $nowSeconds }
}

function Write-Results([hashtable]$result) {
    $result['generated_at_utc'] = (Get-Date).ToUniversalTime().ToString('o')
    $result['branch'] = (& git -C $RepoRoot branch --show-current 2>$null).Trim()
    $result['head'] = (& git -C $RepoRoot rev-parse HEAD 2>$null).Trim()
    $result['mode'] = $Mode
    $ts = (Get-Date).ToUniversalTime().ToString('yyyyMMdd-HHmmss-fff')
    $runDir = Join-Path $ResultsDir 'runs'
    New-Item -ItemType Directory -Force -Path $runDir | Out-Null
    $json = $result | ConvertTo-Json -Depth 14
    $runFile = Join-Path $runDir "$Mode-$ts.json"
    Set-Content -LiteralPath $runFile -Value $json -Encoding utf8
    Set-Content -LiteralPath (Join-Path $ResultsDir 'last-run.json') -Value $json -Encoding utf8
    Write-Host ''
    Write-Host "results written: $runFile" -ForegroundColor Green
}

# ---------------------------------------------------------------------------
# Mode dispatch (wrapped so run-time throws become structured nonzero failures).
# ---------------------------------------------------------------------------
try {

if ($Mode -eq 'gradle') {
    Assert-Prerequisites
    if (!$Tasks -or $Tasks.Count -eq 0) {
        $Tasks = @(':app:testDebugUnitTest', ':app:assembleDebug', ':app:assembleDebugAndroidTest')
    }
    Invoke-Gradle $Tasks @('--offline')
    exit 0
}

if ($Mode -eq 'check') {
    Assert-Prerequisites
    $result = [ordered]@{}
    $result['source'] = Get-SourceFingerprint
    $result['toolchain'] = [ordered]@{ jdk = $BuildJdk; sdk = $AndroidSdk; buildTools = $BuildToolsVersion }

    $diffCheck = & git -C $RepoRoot diff --check -- android 2>$null
    $diffExit = $LASTEXITCODE
    $result['static_diff_check'] = [ordered]@{ passed = ($diffExit -eq 0 -and !$diffCheck); exitCode = $diffExit; notes = ($diffCheck -join "`n") }

    $python = (Get-Command python -ErrorAction SilentlyContinue).Source
    if (!$python) { $python = 'python' }
    & $python (Join-Path $HarnessRoot 'tools/check-fixtures.py') 2>&1 | Write-Host
    $result['static_fixtures'] = [ordered]@{ passed = ($LASTEXITCODE -eq 0) }

    Invoke-Gradle @(':app:testDebugUnitTest') @('--tests', 'org.kiosk.harness.admin.AdminNavigationPolicyTest',
        '--tests', 'org.kiosk.harness.pairing.PairingPayloadTest',
        '--tests', 'org.kiosk.harness.delivery.DeliveryClientRecoveryTest', '--offline')
    $jvm = Get-JvmTestResult $ExpectedCheckClasses
    $jvmGate = Test-JvmGate $jvm $ExpectedCheckClasses.Count
    $result['check_jvm'] = $jvm
    $result['check_jvm_gate'] = $jvmGate

    $anchorCheck = Assert-SandboxBootstrapAnchor
    $result['sandbox_bootstrap_anchor'] = $anchorCheck
    if ($anchorCheck.ok) { Write-Host "sandbox bootstrap CA matches WebView anchor $($anchorCheck.caFp)" }
    else { Write-Host "sandbox bootstrap/anchor invalid: $($anchorCheck.reason)" -ForegroundColor Red }

    Write-Results $result
    $ok = $result['static_diff_check'].passed -and $result['static_fixtures'].passed -and $jvmGate.ok -and $anchorCheck.ok
    if (!$ok) { Write-Host 'check FAILED' -ForegroundColor Red; exit 1 }
    Write-Host 'check PASSED' -ForegroundColor Green
    exit 0
}
if ($Mode -eq 'build') {
    Assert-Prerequisites
    if (!$TestBuildType) { $TestBuildType = 'sandbox' }
    Invoke-Gradle @(':app:assembleDebug', ':app:assembleSandbox', ':app:assembleSandboxAndroidTest') @('--offline')

    $out = Join-Path $HarnessRoot 'app/build/outputs/apk'
    $apks = [ordered]@{
        debug = Get-ApkIdentity (Join-Path $out 'debug/app-debug.apk')
        sandbox = Get-ApkIdentity (Join-Path $out 'sandbox/app-sandbox.apk')
        sandboxTest = Get-ApkIdentity (Join-Path $out 'androidTest/sandbox/app-sandbox-androidTest.apk')
    }

    $result = [ordered]@{}
    $result['source'] = Get-SourceFingerprint
    $result['toolchain'] = [ordered]@{ jdk = $BuildJdk; sdk = $AndroidSdk; buildTools = $BuildToolsVersion; testBuildType = $(if ($TestBuildType) { $TestBuildType } else { 'sandbox' }) }
    $result['apks'] = $apks
    $result['apk_bytes_total'] = ($apks.Values | Measure-Object -Property bytes -Sum).Sum
    $result['status'] = 'passed'

    Write-Results $result
    foreach ($name in @('debug', 'sandbox', 'sandboxTest')) {
        $a = $apks[$name]
        Write-Host ("{0,-12} {1} v{2} ({3}) signer={4} sha256={5}" -f $name, $a.package, $a.versionName, $a.versionCode, $a.signerSha256, $a.sha256)
    }
    exit 0
}

if ($Mode -eq 'deploy') {
    Assert-Prerequisites -NeedDevice
    if (!$Package) { $Package = $SandboxPackage }
    if ($Package -eq $RetainedPackage) {
        Fail "Refusing to deploy to the retained original app '$RetainedPackage'. Target the sandbox ($SandboxPackage)." 3
    }
    if (!$Apk) { $Apk = Join-Path $HarnessRoot 'app/build/outputs/apk/sandbox/app-sandbox.apk' }

    $id = Get-ApkIdentity $Apk
    if ($id.package -ne $Package) { Fail "APK package '$($id.package)' does not match requested target '$Package'." 3 }

    $originalSigner = Get-InstalledSigner $RetainedPackage
    if (!$originalSigner) { Fail "Cannot read the original signer from installed '$RetainedPackage'; deployment is refused." 3 }

    $installed = Get-InstalledIdentity $Package
    $pre = Test-DeployPreconditions $id $installed $originalSigner
    if (!$pre.ok) { Fail "Deployment refused (no mutation): $($pre.reason)" 3 }

    $before = $null
    if ($installed.installed) {
        $before = Get-AppState $Package
        if (!$before.readable) { Fail "Cannot read '$Package' state before deployment: $($before.error). Refusing (no mutation)." 3 }
    }

    $adb = Resolve-Tool 'platform-tools/adb.exe' 'adb'
    $install = & $adb -s $Device install -r $Apk 2>&1
    Write-Host ($install -join "`n")
    if ($LASTEXITCODE -ne 0) { Fail "adb install -r failed (exit $LASTEXITCODE); no uninstall performed." 1 }

    $afterInstalled = Get-InstalledIdentity $Package
    if (!$afterInstalled.installed) { Fail "Post-install verification failed: '$Package' not found." 1 }
    if ($afterInstalled.error) { Fail "Post-install verification failed: $($afterInstalled.error)" 1 }
    if ($afterInstalled.package -ne $Package) { Fail "Post-install package mismatch: $($afterInstalled.package)" 1 }
    if ($afterInstalled.signerSha256 -ne $id.signerSha256) { Fail "Post-install signer mismatch: $($afterInstalled.signerSha256) vs $($id.signerSha256)" 1 }
    if ($afterInstalled.versionCode -ne $id.versionCode) { Fail "Post-install versionCode mismatch: $($afterInstalled.versionCode) vs $($id.versionCode)" 1 }
    if ($afterInstalled.sha256 -ne $id.sha256) { Fail "Post-install APK hash mismatch: $($afterInstalled.sha256) vs $($id.sha256)" 1 }

    $after = Get-AppState $Package
    $preserved = if ($before) { Test-Preservation $before $after } else { [ordered]@{ ok = $true; reason = 'fresh install (no prior state to preserve)' } }
    if (!$preserved.ok) { Fail "State preservation FAILED after replacement: $($preserved.reason). (No uninstall; state left as-is.)" 1 }

    $result = [ordered]@{
        status = 'passed'
        source = Get-SourceFingerprint
        deployed = [ordered]@{ package = $Package; apk = $id; signerMatchedOriginal = $true; installed = $afterInstalled }
        before = $before
        after = $after
        statePreserved = $preserved
    }
    Write-Results $result
    Write-Host ("deployed {0} v{1} (signer {2}); state preserved: {3}" -f $id.package, $id.versionName, $id.signerSha256, $preserved.ok) -ForegroundColor Green
    exit 0
}

if ($Mode -eq 'journey') {
    Assert-Prerequisites -NeedDevice
    if (!$Package) { $Package = $SandboxPackage }
    if ($Package -eq $RetainedPackage) { Fail "Journey target must be the disposable sandbox, not '$RetainedPackage'." 3 }
    $adb = Resolve-Tool 'platform-tools/adb.exe' 'adb'

    # 0) Fixture prerequisites: matching public CA / private test material.
    $fixtures = Assert-AdminTlsFixtures
    if (!$fixtures.ok) { Fail "Admin TLS fixtures invalid: $($fixtures.reason). Regenerate with generate-admin-tls-fixtures.ps1 -Force." 2 }
    $anchorCheck = Assert-SandboxBootstrapAnchor
    if (!$anchorCheck.ok) { Fail "Sandbox bootstrap/WebView anchor invalid: $($anchorCheck.reason)" 2 }

    # 0b) The packaged fixture must still be usable on THIS device: Delivery validates issued/expires
    # against the device clock, so an expired or not-yet-issued bootstrap cannot produce first trust.
    # Refuse before any install, instead of reporting a stale-state journey as a pass.
    $deviceClock = Get-DeviceClock
    if (!$deviceClock.ok) { Fail "journey: $($deviceClock.error)" 3 }
    $windowCheck = Test-BootstrapWindow ([ordered]@{ issued_at = $anchorCheck.issuedAt; expires_at = $anchorCheck.expiresAt }) $deviceClock.deviceEpoch
    if (!$windowCheck.ok) { Fail "journey: packaged sandbox bootstrap unusable ($($anchorCheck.bootstrapId)): $($windowCheck.reason). Install a fresh pilot bootstrap from the coordinator; expiry is not bypassed." 2 }

    # 1) Retained original app baseline (must stay untouched).
    $retainedBefore = Get-InstalledIdentity $RetainedPackage
    if (!$retainedBefore.installed -or $retainedBefore.error) { Fail "Cannot read retained '$RetainedPackage' identity before journey: $($retainedBefore.error)" 3 }
    $retainedBeforeState = Get-AppState $RetainedPackage
    if (!$retainedBeforeState.readable) { Fail "Cannot read retained '$RetainedPackage' state: $($retainedBeforeState.error)" 3 }
    if (!$retainedBeforeState.deliveryStatePresent) { Fail "Retained '$RetainedPackage' delivery state missing/unreadable; expected state not present." 3 }
    $retainedBeforeLast = Get-LastUpdateTime $RetainedPackage

    # 2) Build fresh sandbox APK + test APK.
    if (!$TestBuildType) { $TestBuildType = 'sandbox' }
    Invoke-Gradle @(':app:assembleSandbox', ':app:assembleSandboxAndroidTest') @('--offline')
    $mainApk = Join-Path $HarnessRoot 'app/build/outputs/apk/sandbox/app-sandbox.apk'
    $testApk = Join-Path $HarnessRoot 'app/build/outputs/apk/androidTest/sandbox/app-sandbox-androidTest.apk'
    $mainId = Get-ApkIdentity $mainApk
    $testId = Get-ApkIdentity $testApk

    # 3) Data-preserving A -> B replacement.
    $originalSigner = $retainedBefore.signerSha256
    if ($mainId.signerSha256 -ne $originalSigner) { Fail "Sandbox signer mismatch vs original; journey aborted." 3 }
    if ($mainId.package -ne $Package) { Fail "Sandbox APK package mismatch: $($mainId.package)." 3 }
    $before = Get-AppState $Package
    if (!$before.readable) { Fail "Cannot read '$Package' state before replacement: $($before.error)" 3 }
    & $adb -s $Device install -r $mainApk 2>&1 | Out-Null
    if ($LASTEXITCODE -ne 0) { Fail "journey: sandbox install failed." 1 }
    $after = Get-AppState $Package
    if (!$after.readable) { Fail "Cannot read '$Package' state after replacement: $($after.error)" 1 }
    $statePreserved = Test-Preservation $before $after
    if (!$statePreserved.ok) { Fail "journey: state preservation FAILED: $($statePreserved.reason)" 1 }

    # 4) Affected sandbox instrumentation (local TLS fixtures; no live server).
    & $adb -s $Device install -r $testApk 2>&1 | Out-Null
    if ($LASTEXITCODE -ne 0) { Fail "journey: sandbox test APK install failed." 1 }
    $instrument = & $adb -s $Device shell 'am instrument -w -e class org.kiosk.harness.admin.AdminTlsSandboxTest org.kiosk.harness.sandbox.test/org.kiosk.harness.HarnessTestRunner' 2>&1
    $instrumentText = $instrument -join "`n"
    Write-Host $instrumentText
    $instrumentOk = ($instrumentText -match 'OK \(1 test\)')

    # 5) WebView process/data isolation (structural; no cookie values or private state read).
    $manifestCheck = Test-ManifestAdminProcess $mainApk
    $isolation = Test-WebViewIsolation $Package $manifestCheck

    # 6) Offline content usability (authoritative ready/visible package identity).
    & $adb -s $Device shell "am force-stop $Package" 2>&1 | Out-Null
    & $adb -s $Device shell "am start -n $Package/org.kiosk.harness.StoredHarnessActivity" 2>&1 | Out-Null
    Start-Sleep -Seconds 4
    & $adb -s $Device shell 'uiautomator dump /data/local/tmp/kiosk-journey-ui.xml' 2>&1 | Out-Null
    $ui = (& $adb -s $Device shell 'cat /data/local/tmp/kiosk-journey-ui.xml' 2>&1) -join "`n"
    $offline = Test-OfflineContent $ui $ExpectedVisibleIdentity

    # 7) Original app still untouched.
    $retainedAfter = Get-InstalledIdentity $RetainedPackage
    $retainedAfterState = Get-AppState $RetainedPackage
    $retainedAfterLast = Get-LastUpdateTime $RetainedPackage
    $retainedUntouched = $retainedAfter.installed -and !$retainedAfter.error -and
                          ($retainedAfter.signerSha256 -eq $retainedBefore.signerSha256) -and
                          $retainedAfterState.readable -and
                          ($retainedAfterState.deliveryStateSha256 -eq $retainedBeforeState.deliveryStateSha256) -and
                          ($retainedAfterLast -eq $retainedBeforeLast)

    $result = [ordered]@{
        source = Get-SourceFingerprint
        fixtures = $fixtures
        sandboxBootstrapAnchor = $anchorCheck
        sandboxBootstrapWindow = $windowCheck
        deviceClock = $deviceClock
        built = [ordered]@{ main = $mainId; test = $testId }
        before = $before
        after = $after
        statePreserved = $statePreserved
        instrumentation = [ordered]@{ command = 'AdminTlsSandboxTest'; ok = $instrumentOk; output = $instrumentText }
        manifestAdminProcess = $manifestCheck
        webviewIsolation = $isolation
        offlineDisplay = $offline
        offlineExpectedVisible = $ExpectedVisibleIdentity
        retainedOriginalUntouched = $retainedUntouched
        retainedOriginal = [ordered]@{ signer = $retainedAfter.signerSha256; deliveryStateSha256 = $retainedAfterState.deliveryStateSha256; lastUpdateTime = $retainedAfterLast }
        liveServer = [ordered]@{ exercised = $false; note = 'Old 18543 lab TLS/trust has expired; not bypassed. Local fixtures used instead.' }
    }

    $overall = $statePreserved.ok -and $instrumentOk -and $isolation.ok -and $offline.ok -and $retainedUntouched -and $anchorCheck.ok -and $windowCheck.ok -and $deviceClock.ok
    $result['status'] = if ($overall) { 'passed' } else { 'failed' }
    Write-Results $result
    if (!$overall) {
        $why = @()
        if (!$statePreserved.ok) { $why += "state: $($statePreserved.reason)" }
        if (!$instrumentOk) { $why += 'instrumentation' }
        if (!$isolation.ok) { $why += "isolation: $($isolation.note)" }
        if (!$offline.ok) { $why += "offline: $($offline.reason)" }
        if (!$retainedUntouched) { $why += 'original app changed' }
        Write-Host ('journey FAILED: ' + ($why -join '; ')) -ForegroundColor Red
        exit 1
    }
    Write-Host 'journey PASSED (local fixtures)' -ForegroundColor Green
    exit 0
}

if ($Mode -eq 'selftest') {
    # Offline negative/positive gate self-test. No device, no Gradle.
    if (!$BuildJdk) { Fail 'selftest requires -BuildJdk for keytool-based fixture validation.' 2 }
    $cases = New-Object System.Collections.Generic.List[object]
    function Add-Case([string]$name, [bool]$pass, [string]$detail) {
        $script:cases.Add([ordered]@{ name = $name; pass = $pass; detail = $detail })
    }

    # Mock aapt2/apksigner that exit nonzero while still printing parseable output, to prove
    # Get-ApkIdentity now gates on exit status rather than parseability.
    $fakeSdk = Join-Path ([System.IO.Path]::GetTempPath()) ("kiosk-fake-sdk-" + [guid]::NewGuid().ToString('n'))
    $bt = Join-Path $fakeSdk "build-tools/$BuildToolsVersion"
    New-Item -ItemType Directory -Force -Path $bt | Out-Null
    $dummyApk = Join-Path $fakeSdk 'dummy.apk'
    Set-Content -LiteralPath $dummyApk -Value 'not a real apk'
    $prevSdk = $AndroidSdk
    $AndroidSdk = $fakeSdk
    try {
        $csc = 'C:\Windows\Microsoft.NET\Framework64\v4.0.30319\csc.exe'
        $aapt2exe = Join-Path $bt 'aapt2.exe'
        $apksignerBat = Join-Path $bt 'apksigner.bat'
        if (Test-Path -LiteralPath $csc) {
            $cs = Join-Path $fakeSdk 'mock.cs'
            Set-Content -LiteralPath $cs -Value 'public class P { public static int Main(string[] a){ System.Console.WriteLine("package: name=\u0027com.fake\u0027 versionCode=\u00271\u0027 versionName=\u00271.0\u0027"); return 1; } }'
            & $csc /nologo ("/out:" + $aapt2exe) /target:exe $cs 2>&1 | Out-Null
        }
        Set-Content -LiteralPath $apksignerBat -Value "@echo off`r`necho Signer #1 certificate SHA-256 digest: 00112233445566778899aabbccddeeff00112233445566778899aabbccddeeff`r`nexit /b 1"

        # 1) aapt2 exits nonzero with parseable badging -> Get-ApkIdentity must throw.
        $threw = $false
        if (Test-Path -LiteralPath $aapt2exe) {
            try { Get-ApkIdentity $dummyApk | Out-Null } catch { $threw = $true }
            Add-Case 'aapt2 nonzero exit is rejected (not merely parsed)' $threw ($(if ($threw) { 'threw as required' } else { 'returned an identity despite exit != 0' }))
        } else {
            Add-Case 'aapt2 nonzero exit is rejected (not merely parsed)' $false 'csc.exe unavailable; mock aapt2 not built'
        }

        # 2) apksigner exits nonzero with a valid digest -> Get-ApkIdentity must throw. Swap in a passing aapt2 mock first.
        $cs2 = Join-Path $fakeSdk 'mock-ok.cs'
        Set-Content -LiteralPath $cs2 -Value 'public class P { public static int Main(string[] a){ System.Console.WriteLine("package: name=\u0027com.fake\u0027 versionCode=\u00271\u0027 versionName=\u00271.0\u0027"); return 0; } }'
        if (Test-Path -LiteralPath $csc) { & $csc /nologo ("/out:" + $aapt2exe) /target:exe $cs2 2>&1 | Out-Null }
        $threw = $false
        try { Get-ApkIdentity $dummyApk | Out-Null } catch { $threw = $true }
        Add-Case 'apksigner nonzero exit is rejected (not merely parsed)' $threw ($(if ($threw) { 'threw as required' } else { 'returned a digest despite exit != 0' }))
    } finally {
        $AndroidSdk = $prevSdk
        Remove-Item -LiteralPath $fakeSdk -Recurse -Force -ErrorAction SilentlyContinue
    }

    # 3) JVM gate: zero parsed tests must be rejected.
    $emptyJvm = [ordered]@{ totals = [ordered]@{ tests = 0; failures = 0; errors = 0; skipped = 0 }; suites = @{}; missingExpected = @($ExpectedCheckClasses); expectedClasses = $ExpectedCheckClasses }
    Add-Case 'check gate rejects 0 parsed tests' (!(Test-JvmGate $emptyJvm $ExpectedCheckClasses.Count).ok) '0 tests + missing expected suites'

    # 4) Preservation: changed/lost/unreadable state must be rejected.
    $b = [ordered]@{ readable = $true; deliveryStatePresent = $true; deliveryStateSha256 = 'aaaa'; filesPresent = $true; filesCount = '2'; filesTreeSha256 = 'bbbb' }
    $a1 = [ordered]@{ readable = $true; deliveryStatePresent = $true; deliveryStateSha256 = 'cccc'; filesPresent = $true; filesCount = '2'; filesTreeSha256 = 'bbbb' }
    $a2 = [ordered]@{ readable = $true; deliveryStatePresent = $true; deliveryStateSha256 = 'aaaa'; filesPresent = $false; filesCount = $null; filesTreeSha256 = $null }
    $a3 = [ordered]@{ readable = $false; error = 'run-as failed'; deliveryStatePresent = $false; deliveryStateSha256 = $null; filesPresent = $false; filesCount = $null; filesTreeSha256 = $null }
    Add-Case 'preservation rejects changed delivery state' (!(Test-Preservation $b $a1).ok) 'delivery sha changed'
    Add-Case 'preservation rejects lost files dir' (!(Test-Preservation $b $a2).ok) 'files dir lost'
    Add-Case 'preservation rejects unreadable after-state' (!(Test-Preservation $b $a3).ok) 'after not readable'
    $b2 = [ordered]@{ readable = $true; deliveryStatePresent = $false; deliveryStateSha256 = $null; filesPresent = $false; filesCount = $null; filesTreeSha256 = $null }
    Add-Case 'preservation allows fresh empty sandbox' (Test-Preservation $b2 $b2).ok 'no prior state, none after'
    Add-Case 'preservation passes identical state' (Test-Preservation $b (($b | ConvertTo-Json | ConvertFrom-Json))).ok 'identical before/after'

    # 5) Offline content gate (strict): loose button/state text must not pass.
    $good = "DEVELOPMENT playback; admission unverified&#10;state=ready selected=tv&#10;visible=$ValidContentIdentity mode=tv"
    Add-Case 'offline gate rejects state=failed' (!(Test-OfflineContent "state=failed selected=tv&#10;visible=$ValidContentIdentity" $ValidContentIdentity).ok) 'state not ready'
    Add-Case 'offline gate rejects visible=none' (!(Test-OfflineContent 'state=ready selected=tv&#10;visible=none mode=tv' $ValidContentIdentity).ok) 'no visible identity'
    Add-Case 'offline gate rejects wrong identity' (!(Test-OfflineContent "state=ready selected=tv&#10;visible=$EmptyContentIdentity" $ValidContentIdentity).ok) 'empty identity'
    Add-Case 'offline gate rejects arbitrary button/state text' (!(Test-OfflineContent 'CONNECT SERVER ADMINISTRATION state=' $ValidContentIdentity).ok) 'loose match must fail'
    Add-Case 'offline gate passes ready+valid identity' (Test-OfflineContent $good $ValidContentIdentity).ok 'ready + valid visible'

    # 6) Deploy preconditions (pure logic): refusals must hold.
    $cand = [ordered]@{ package = 'org.kiosk.harness.sandbox'; versionCode = 2; signerSha256 = 'ff95' }
    $candOld = [ordered]@{ package = 'org.kiosk.harness.sandbox'; versionCode = 1; signerSha256 = 'ff95' }
    $candBadSigner = [ordered]@{ package = 'org.kiosk.harness.sandbox'; versionCode = 2; signerSha256 = 'ffff' }
    $installedV2 = [ordered]@{ installed = $true; error = ''; package = 'org.kiosk.harness.sandbox'; versionCode = 2; signerSha256 = 'ff95' }
    $installedBad = [ordered]@{ installed = $true; error = ''; package = 'org.kiosk.harness.sandbox'; versionCode = 1; signerSha256 = 'ffff' }
    $notInstalled = [ordered]@{ installed = $false; error = ''; package = 'org.kiosk.harness.sandbox'; versionCode = 0; signerSha256 = '' }
    Add-Case 'deploy refuses signer mismatch' (!(Test-DeployPreconditions $candBadSigner $installedV2 'ff95').ok) 'candidate signer != original'
    Add-Case 'deploy refuses downgrade' (!(Test-DeployPreconditions $candOld $installedV2 'ff95').ok) 'versionCode 1 < 2'
    Add-Case 'deploy refuses installed signer mismatch' (!(Test-DeployPreconditions $cand $installedBad 'ff95').ok) 'installed signer != original'
    Add-Case 'deploy refuses unreadable original signer' (!(Test-DeployPreconditions $cand $installedV2 '').ok) 'no original signer'
    Add-Case 'deploy accepts valid replacement' (Test-DeployPreconditions $cand $installedV2 'ff95').ok 'same signer, no downgrade'
    Add-Case 'deploy accepts fresh install' (Test-DeployPreconditions $cand $notInstalled 'ff95').ok 'not installed yet'

    # 7) Fixture validation (real fixtures, positive): matching CA / private test material.
    $fx = Assert-AdminTlsFixtures
    Add-Case 'admin TLS fixtures valid (CA matches test material)' $fx.ok ($(if ($fx.ok) { "ca=$($fx.caFp)" } else { $fx.reason }))

    # 8) Bootstrap window gate: journey must not run on a dead or future-dated fixture.
    $now = 1763000000L
    Add-Case 'bootstrap window rejects expired fixture' (!(Test-BootstrapWindow ([ordered]@{ issued_at = $now - 1000; expires_at = $now - 1 }) $now).ok) 'expires_at in the past'
    Add-Case 'bootstrap window rejects not-yet-issued fixture' (!(Test-BootstrapWindow ([ordered]@{ issued_at = $now + 1; expires_at = $now + 1000 }) $now).ok) 'issued_at in the future'
    Add-Case 'bootstrap window rejects inverted window' (!(Test-BootstrapWindow ([ordered]@{ issued_at = $now + 5; expires_at = $now + 5 }) $now).ok) 'issued_at >= expires_at'
    Add-Case 'bootstrap window rejects non-integer timestamps' (!(Test-BootstrapWindow ([ordered]@{ issued_at = 'soon'; expires_at = $now + 10 }) $now).ok) 'issued_at not numeric'
    Add-Case 'bootstrap window rejects missing timestamps' (!(Test-BootstrapWindow ([ordered]@{}) $now).ok) 'no timestamps'
    Add-Case 'bootstrap window accepts now inside window' (Test-BootstrapWindow ([ordered]@{ issued_at = $now - 10; expires_at = $now + 10 }) $now).ok 'now inside [issued, expires)'

    $passed = @($cases | Where-Object { $_.pass }).Count
    $total = $cases.Count
    $result = [ordered]@{
        status = if ($passed -eq $total) { 'passed' } else { 'failed' }
        source = Get-SourceFingerprint
        selftest = [ordered]@{ total = $total; passed = $passed; failed = ($total - $passed); cases = $cases }
    }
    Write-Results $result
    $cases | ForEach-Object { Write-Host ("[{0}] {1} : {2}" -f $(if ($_.pass) { 'PASS' } else { 'FAIL' }), $_.name, $_.detail) }
    if ($passed -ne $total) { Write-Host "selftest FAILED ($passed/$total)" -ForegroundColor Red; exit 1 }
    Write-Host "selftest PASSED ($passed/$total)" -ForegroundColor Green
    exit 0
}

Fail "Unknown mode '$Mode'." 2

} catch {
    Fail $_.Exception.Message 1
}
