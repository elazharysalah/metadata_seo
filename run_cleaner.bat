@echo off
setlocal
cd /d "%~dp0"

powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%~dp0run_cleaner.ps1"
if errorlevel 1 (
    echo.
    echo Something went wrong. Exit code: %ERRORLEVEL%
    pause
)
endlocal
