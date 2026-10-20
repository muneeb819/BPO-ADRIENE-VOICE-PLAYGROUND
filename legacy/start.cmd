@echo off
setlocal
cd /d "%~dp0"

where python >nul 2>nul
if errorlevel 1 (
    echo Python 3 was not found on this computer.
    echo Install it from https://www.python.org/downloads/ and try again.
    pause
    exit /b 1
)

python server.py %*
if errorlevel 1 pause
