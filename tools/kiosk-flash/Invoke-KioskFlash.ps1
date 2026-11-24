#Requires -Version 7.3
[CmdletBinding()]
param(
    [Parameter(Mandatory)]
    [string]$RepoRoot,

    [Parameter(Mandatory)]
    [string]$TaskFile,

    [string[]]$WriteDir = @(),

    [guid]$ResumeSession,

    [switch]$Lab,

    [switch]$Check
)

$ErrorActionPreference = 'Stop'

function Get-PlainDirectoryPath([string]$Path) {
    if (![IO.Path]::IsPathFullyQualified($Path)) {
        throw "Use an absolute directory path: $Path"
    }
    $dir = Get-Item -LiteralPath $Path
    if ($dir -isnot [IO.DirectoryInfo] -or $null -eq $dir.Parent) {
        throw "Expected a non-root directory: $Path"
    }
    for ($parent = $dir; $null -ne $parent; $parent = $parent.Parent) {
        if ($parent.Attributes.HasFlag([IO.FileAttributes]::ReparsePoint)) {
            throw "Directory passes through a junction or symbolic link: $($parent.FullName)"
        }
    }
    $dir.FullName
}

function Test-InDirectory([string]$Path, [string]$Root) {
    $Path.Equals($Root, [StringComparison]::OrdinalIgnoreCase) -or
        $Path.StartsWith("$Root\", [StringComparison]::OrdinalIgnoreCase)
}

function ConvertTo-TomlString([string]$Value) {
    '"' + $Value.Replace('\', '\\').Replace('"', '\"') + '"'
}

function Enter-KioskFlashSlot {
    foreach ($number in 1..5) {
        $slot = [System.Threading.Mutex]::new($false, "Global\Kiosk_v001.Flash.Worker.$number")
        $acquired = $false
        try {
            try {
                $acquired = $slot.WaitOne(0)
            } catch [System.Threading.AbandonedMutexException] {
                $acquired = $true
            }
            if ($acquired) {
                return $slot
            }
        } finally {
            if (!$acquired) {
                $slot.Dispose()
            }
        }
    }

    throw 'All five Kiosk Flash worker slots are occupied. Wait for an active worker to exit.'
}

$repo = Get-PlainDirectoryPath $RepoRoot
if (!(Test-Path -LiteralPath (Join-Path $repo 'AGENTS.md') -PathType Leaf) -or
    !(Test-Path -LiteralPath (Join-Path $repo 'docs\TZ_RECONCILED.md') -PathType Leaf)) {
    throw "Expected a Kiosk checkout: $repo"
}

$task = Get-Item -LiteralPath $TaskFile
if ($task -isnot [IO.FileInfo] -or $task.Attributes.HasFlag([IO.FileAttributes]::ReparsePoint)) {
    throw 'Pass a plain task file.'
}
$taskParent = Get-PlainDirectoryPath $task.DirectoryName
$prompt = Get-Content -Raw -LiteralPath (Join-Path $taskParent $task.Name)
if ([string]::IsNullOrWhiteSpace($prompt)) {
    throw 'Pass a nonempty task brief.'
}

$codexDir = if ($env:CODEX_HOME) { $env:CODEX_HOME } else { Join-Path $env:USERPROFILE '.codex' }
$profilePath = Join-Path $codexDir 'kiosk-flash.config.toml'
if (!(Test-Path -LiteralPath $profilePath -PathType Leaf)) {
    throw "Install the Kiosk Flash profile first: $profilePath"
}
$template = Join-Path $repo 'tools\kiosk-flash\kiosk-flash.config.toml'
if ((Get-FileHash -LiteralPath $profilePath).Hash -ne (Get-FileHash -LiteralPath $template).Hash) {
    throw 'Installed Kiosk Flash profile differs from the checkout template. Restore it from the checkout.'
}
# The npm batch shim strips the double quotes in the TOML overrides.
$codex = Get-Command codex.exe, codex.ps1, codex -CommandType Application, ExternalScript -ErrorAction SilentlyContinue |
    Select-Object -First 1
if (!$codex) { throw 'Codex CLI was not found on PATH.' }

$workspace = if ($WriteDir.Count) { Join-Path $env:LOCALAPPDATA 'KioskFlash' }
$writable = @($repo)
foreach ($dir in $WriteDir) {
    $full = Get-PlainDirectoryPath $dir
    if (!(Test-InDirectory $full $repo) -and
        (!(Test-InDirectory $full $workspace) -or $full -ieq $workspace)) {
        throw "Use a checkout directory or a subdirectory of $workspace"
    }
    if ($full -match '(?i)\\\.(git|agents|codex|aws)(\\|$)') {
        throw "Protected directory: $full"
    }
    if ($writable -notcontains $full -and !(Test-InDirectory $full $repo)) {
        $writable += $full
    }
}
foreach ($root in $writable) {
    if (Test-InDirectory $task.FullName $root) {
        throw 'Keep the task brief outside writable directories.'
    }
}

$fileRules = @('":root" = "read"')
$fileRules += $writable | ForEach-Object { "$(ConvertTo-TomlString $_) = 'write'" }
$protected = @(
    (Join-Path $codexDir 'auth.json'),
    (Join-Path $repo '.git'),
    (Join-Path $repo '.agents'),
    (Join-Path $repo '.codex'),
    (Join-Path $repo '.aws')
)
$fileRules += "$(ConvertTo-TomlString (Join-Path $repo '.git')) = 'read'"
$fileRules += $protected | Where-Object { $_ -ne (Join-Path $repo '.git') } | ForEach-Object { "$(ConvertTo-TomlString $_) = 'deny'" }
$network = $Lab.IsPresent.ToString().ToLowerInvariant()
$overrides = @(
    '-c', 'model_reasoning_effort="high"',
    '-c', "permissions.kiosk-task.filesystem={$($fileRules -join ', ')}",
    '-c', "permissions.kiosk-task.network.enabled=$network"
)
$argsForCodex = @('-p', 'kiosk-flash', '-m', 'deepseek-flash', '--strict-config', '--no-daemon', '-C', $repo) + $overrides
if ($PSBoundParameters.ContainsKey('ResumeSession')) {
    $argsForCodex += @('resume', $ResumeSession.ToString())
}
if ($Check) {
    [pscustomobject]@{
        Profile = 'kiosk-flash'
        Model = 'deepseek-flash'
        ReasoningEffort = 'high'
        Checkout = $repo
        WritableDirectories = $writable
        ProtectedPaths = $protected
        ShellNetwork = $Lab.IsPresent
        ConfigOverrides = $overrides
    }
    return
}

$previousKey = $env:DEEPSEEK_API_KEY
$workerSlot = Enter-KioskFlashSlot
try {
    if ([string]::IsNullOrWhiteSpace($previousKey)) {
        $env:DEEPSEEK_API_KEY = [Environment]::GetEnvironmentVariable('DEEPSEEK_API_KEY', 'User')
    }
    if ([string]::IsNullOrWhiteSpace($env:DEEPSEEK_API_KEY)) {
        throw 'DEEPSEEK_API_KEY is missing.'
    }
    $labScope = if ($Lab) { 'Use network only for the named lab targets and operations in the brief.' }
        else { 'This is a local task. Shell network access stays off.' }
    $prompt = @($labScope, 'Task brief:', $prompt) -join [Environment]::NewLine
    & $codex.Source @argsForCodex -- $prompt
    exit $LASTEXITCODE
} finally {
    $env:DEEPSEEK_API_KEY = $previousKey
    $workerSlot.ReleaseMutex()
    $workerSlot.Dispose()
}
