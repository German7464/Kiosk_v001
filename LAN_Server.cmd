@echo off
setlocal
chcp 65001 >nul
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
    echo Project Python environment not found. Run this file from the Kiosk project folder.
    pause
    exit /b 1
)
".venv\Scripts\python.exe" -m tools.lan_wizard
set "LAN_EXIT=%ERRORLEVEL%"
pause
exit /b %LAN_EXIT%
