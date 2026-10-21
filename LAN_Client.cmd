@echo off
setlocal
chcp 65001 >nul
cd /d "%~dp0"
where pwsh.exe >nul 2>nul
if errorlevel 1 (
    echo PowerShell 7 is required on this PC. Install it, then run this file again.
    pause
    exit /b 1
)
if not exist "session.json" (
    echo Run LAN_Client.cmd from the client ZIP prepared by LAN_Server.cmd.
    pause
    exit /b 1
)
pwsh.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0check_lan_https.ps1" -Wizard
set "LAN_EXIT=%ERRORLEVEL%"
pause
exit /b %LAN_EXIT%
