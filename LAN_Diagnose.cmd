@echo off
setlocal
chcp 65001 >nul
cd /d "%~dp0"
where pwsh.exe >nul 2>nul
if errorlevel 1 (
    echo PowerShell 7 is required. No settings have been changed.
    pause
    exit /b 1
)
pwsh.exe -NoProfile -NonInteractive -Command "if ((Get-ExecutionPolicy) -in @('Restricted','AllSigned')) { Write-Host 'PowerShell policy blocks local product scripts on this PC. An administrator must permit them (for example RemoteSigned); this helper never changes the policy.'; exit 3 }"
if errorlevel 1 (
    echo This helper needs PowerShell 7 and a policy that permits local product scripts.
    pause
    exit /b 3
)
pwsh.exe -NoProfile -NonInteractive -File "%~dp0check_lan_https.ps1" -PreflightOnly
set "LAN_EXIT=%ERRORLEVEL%"
pause
exit /b %LAN_EXIT%
