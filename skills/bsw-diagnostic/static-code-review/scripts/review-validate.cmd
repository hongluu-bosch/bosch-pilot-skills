@echo off
setlocal
set SCRIPT_DIR=%~dp0
powershell -NoProfile -ExecutionPolicy Bypass -File "%SCRIPT_DIR%..\tools\kimi_review.ps1" -Action Validate
exit /b %ERRORLEVEL%