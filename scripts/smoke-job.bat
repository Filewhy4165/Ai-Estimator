@echo off
setlocal

set "SCRIPT_DIR=%~dp0"

if "%~1"=="" (
  echo Usage: smoke-job.bat "C:\path\to\drawing.pdf" [--ApiBase http://127.0.0.1:8000] [--StartApi]
  exit /b 1
)

powershell -NoProfile -ExecutionPolicy Bypass -File "%SCRIPT_DIR%smoke-job.ps1" %*
exit /b %ERRORLEVEL%
