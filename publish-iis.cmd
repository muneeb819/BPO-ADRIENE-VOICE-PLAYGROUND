@echo off
REM ---------------------------------------------------------------------------
REM  BPO Adriene - publish to IIS and bind the local LAN address.
REM  Approve the UAC prompt. A log is written to publish-iis.log.
REM ---------------------------------------------------------------------------
cd /d "%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0publish-iis.ps1" %*
if errorlevel 1 (
  echo.
  echo Publish failed - see publish-iis.log
)
pause
