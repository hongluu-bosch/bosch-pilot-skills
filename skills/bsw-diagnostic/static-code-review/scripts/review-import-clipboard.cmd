@echo off
setlocal
set SCRIPT_DIR=%~dp0
set SOURCE=%~1

if "%SOURCE%"=="" (
    set /p SOURCE=Source file path (example: path\to\source.c): 
)

if "%SOURCE%"=="" (
    echo Source file is required.
    exit /b 1
)

powershell -NoProfile -ExecutionPolicy Bypass -File "%SCRIPT_DIR%..\tools\kimi_review.ps1" -Action ImportClipboard -Source "%SOURCE%"
exit /b %ERRORLEVEL%