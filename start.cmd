@echo off
setlocal EnableExtensions
cd /d "%~dp0"
title BPO Adriene Voice Playground

echo.
echo   BPO ADRIENE - LOCAL VOICE PLAYGROUND
echo   ------------------------------------
echo.

set "PY=python"
py -3.12 -c "import sys" >nul 2>&1
if not errorlevel 1 set "PY=py -3.12"

%PY% -c "import sys; raise SystemExit(0 if sys.version_info >= (3, 10) else 1)" >nul 2>&1
if errorlevel 1 (
  echo   Python 3.10+ was not found.
  echo   Install Python 3.12 from https://www.python.org/downloads/
  echo   and enable "Add python.exe to PATH".
  echo.
  pause
  exit /b 1
)

if not exist ".env" (
  if exist ".env.example" (
    copy /Y ".env.example" ".env" >nul
    echo   Created .env from .env.example.
    echo   Add DEEPGRAM_API_KEY to .env for Aura TTS + Nova-2 STT.
    echo.
  )
)

echo   URL: http://localhost:8000 (next free port if busy)
echo   Stop: Ctrl+C
echo.

%PY% server.py %*
set "EXITCODE=%ERRORLEVEL%"

if not "%EXITCODE%"=="0" (
  echo.
  echo   The server exited with code %EXITCODE%.
  pause
)

endlocal & exit /b %EXITCODE%
