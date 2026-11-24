# Restore Kiosk Flash

The notebook needs PowerShell 7.3+ and Codex CLI 0.171.0 or a compatible newer version. The single named profile is `kiosk-flash`. It selects [DeepSeek V4.1 Flash](https://api-docs.deepseek.com/quick_start/pricing/) via the direct [Responses API](https://api-docs.deepseek.com/guides/responses_api/). The existing elevated Windows sandbox driver must be provisioned to enforce credential-file denials. Preserve the default OpenAI profile and base `config.toml` intact.

From the published working-branch checkout, run the following in PowerShell on the notebook. Change `$repo` to the local checkout path. Keep the backup private. Existing `DEEPSEEK_API_KEY`, SSH host keys and Android setup stay local. Set the API key via the existing process or Windows user environment. Never put its value in a file from this repository.

```powershell
$repo = 'C:\path\to\Kiosk_v001'
$codexDir = if ($env:CODEX_HOME) { $env:CODEX_HOME } else { Join-Path $env:USERPROFILE '.codex' }
$source = Join-Path $repo 'tools\kiosk-flash'
$names = @('kiosk-flash.config.toml', 'Invoke-KioskFlash.ps1', 'ds.config.toml', 'ds-kiosk.config.toml')
$backup = Join-Path $codexDir ('kiosk-profile-backup-' + (Get-Date -Format 'yyyyMMdd-HHmmssfff'))
New-Item -ItemType Directory -Path $backup -ErrorAction Stop | Out-Null
foreach ($name in $names) {
    $path = Join-Path $codexDir $name
    if (Test-Path -LiteralPath $path -PathType Leaf) {
        Copy-Item -LiteralPath $path -Destination $backup -ErrorAction Stop
    }
}
foreach ($name in $names[0..1]) {
    Copy-Item -LiteralPath (Join-Path $source $name) -Destination $codexDir -Force -ErrorAction Stop
}
$task = New-TemporaryFile
try {
    Set-Content -LiteralPath $task.FullName -Value 'Offline launcher configuration check.'
    & (Join-Path $codexDir 'Invoke-KioskFlash.ps1') -RepoRoot $repo -TaskFile $task.FullName -Check
    & (Join-Path $codexDir 'Invoke-KioskFlash.ps1') -RepoRoot $repo -TaskFile $task.FullName -Lab -Check
} finally {
    Remove-Item -LiteralPath $task.FullName
}
```

Check the profile template match, checkout, protected paths and both shell-network settings. The Git directory is readable for diff and status and stays outside the write scope. Then check active Kiosk wrappers and shortcuts for `-p ds` or `-p ds-kiosk`. Point any remaining Kiosk launcher to this profile before retiring its old profile. If an active dependency cannot be migrated, leave that profile in place and report its exact consumer and blocker. Where safe, remove just the superseded files from `$codexDir`, retaining their backup.

```powershell
foreach ($name in @('ds.config.toml', 'ds-kiosk.config.toml')) {
    $path = Join-Path $codexDir $name
    if (Test-Path -LiteralPath $path -PathType Leaf) {
        Remove-Item -LiteralPath $path -ErrorAction Stop
    }
}
```

For real assignments use the launcher with `-RepoRoot` and a non-secret `-TaskFile` outside writable directories. Use `-Lab` only when the assignment needs the existing test network, SSH or ADB. The launcher enables sandboxed shell networking for that run. Endpoint scope still comes from the [lab policy](../../docs/TEST_LAB_POLICY.md) and task. Windows CLI 0.171.0 exposes a network enable flag, so the launcher does not claim host/port filtering. Use `-WriteDir` for existing output subdirectories below `%LOCALAPPDATA%\KioskFlash` when the checkout is unsuitable for output. Local checks may still be limited by sandbox and Windows ACLs. Keep required environment confirmations. Hand back blocked operations to primary Codex.

To restore the previous local state, restore the affected files from the private backup and remove the new named profile only if the backup had no previous copy. To undo a published group, revert its commit normally. Old records and evidence remain historical.
