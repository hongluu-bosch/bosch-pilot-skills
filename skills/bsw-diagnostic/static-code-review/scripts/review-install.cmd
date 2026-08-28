@echo off
setlocal
set SCRIPT_DIR=%~dp0
powershell -NoProfile -ExecutionPolicy Bypass -File "%SCRIPT_DIR%..\tools\install_cline_integration.ps1"
exit /b %ERRORLEVEL%