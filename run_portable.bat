@echo off
setlocal

set "SCRIPT_DIR=%~dp0"
rem Keep this pre-UTF-8 launcher ASCII-only; its error message is intentionally English-only.
rem START is async: ERRORLEVEL catches creation failure, not a child that starts and immediately exits.
start "Bashi Voice Factory" powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%SCRIPT_DIR%run_portable.ps1" %*
if errorlevel 1 (
    echo [ERROR] Could not start PowerShell. Please take a screenshot of this window and report it.
    pause
    exit /b 1
)
exit /b 0
