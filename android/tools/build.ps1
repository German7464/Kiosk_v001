param(
    [Parameter(Mandatory=$true)][string]$BuildJdk,
    [Parameter(Mandatory=$true)][string]$AndroidSdk,
    [string]$ReadOnlyDependencyCache = '',
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
if (!(Test-Path -LiteralPath "$harnessRoot/.gradle/debug.keystore")) {
    # Disposable harness signing identity, never a product/release key or machine trust change.
    Invoke-HarnessNative "$BuildJdk/bin/keytool.exe" @('-genkeypair', '-keystore', "$harnessRoot/.gradle/debug.keystore", '-storepass', 'android', '-alias', 'androiddebugkey', '-keypass', 'android', '-dname', 'CN=Android Debug,O=Android,C=US', '-keyalg', 'RSA', '-keysize', '2048', '-validity', '3650')
}
Invoke-HarnessNative "$harnessRoot/gradlew.bat" (@('-p', $harnessRoot) + $Tasks)
