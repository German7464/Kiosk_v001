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
pwsh.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0check_lan_https.ps1" -PreflightOnly
set "LAN_EXIT=%ERRORLEVEL%"
pause
exit /b %LAN_EXIT%
