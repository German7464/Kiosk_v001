param(
    [Parameter(Mandatory=$true)][string]$BuildJdk,
    [Parameter(Mandatory=$true)][string]$AndroidSdk,
    [string]$ReadOnlyDependencyCache = '',
    [string]$DebugKeystore = '',
    [string[]]$Tasks = @(':app:testDebugUnitTest', ':app:assembleDebug', ':app:assembleDebugAndroidTest')
)
$ErrorActionPreference = 'Stop'
function Invoke-HarnessNative([string]$Program, [string[]]$Arguments) {
    # Windows PowerShell represents ordinary native stderr (including keytool progress) as ErrorRecord.
    $ErrorActionPreference = 'Continue'
    & $Program @Arguments
    if ($LASTEXITCODE -ne 0) { throw "$Program failed: $LASTEXITCODE" }
}
$harnessRoot = Split-Path -Parent $PSScriptRoot
if (!(Test-Path -LiteralPath "$BuildJdk/bin/javac.exe")) { throw 'A full compatible build JDK is required' }
if (!(Test-Path -LiteralPath "$AndroidSdk/platforms/android-35/android.jar")) { throw 'SDK platform 35 is required' }
$env:JAVA_HOME = $BuildJdk
$env:ANDROID_HOME = $AndroidSdk
$env:GRADLE_USER_HOME = "$harnessRoot/.gradle/user-home"
if ($ReadOnlyDependencyCache) { $env:GRADLE_RO_DEP_CACHE = $ReadOnlyDependencyCache }
New-Item -ItemType Directory -Force -Path "$harnessRoot/.gradle" | Out-Null
if (!$DebugKeystore) { $DebugKeystore = "$harnessRoot/.gradle/debug.keystore" }
if (!(Test-Path -LiteralPath $DebugKeystore -PathType Leaf)) { throw 'Existing debug signer required; never regenerate a lost device signer during build' }
$resolvedDebugKeystore = (Resolve-Path -LiteralPath $DebugKeystore).Path
Invoke-HarnessNative "$harnessRoot/gradlew.bat" (@('-p', $harnessRoot, "-PkioskDebugKeystore=$resolvedDebugKeystore") + $Tasks)
