@echo off
REM ---------------------------------------------------------------------------
REM  BPO Adriene - open the published app with microphone access enabled.
REM
REM  Browsers only expose microphone capture in a secure context. The app is
REM  published on plain HTTP (http://192.168.18.29:8088), so Chrome/Edge are
REM  started with that origin explicitly treated as secure. No admin rights
REM  and no HTTPS certificate are required.
REM
REM  Usage:  start-mic-browser.cmd [origin] [path]
REM          start-mic-browser.cmd                       (defaults below)
REM ---------------------------------------------------------------------------
setlocal

if "%~1"=="" (set "ORIGIN=http://192.168.18.29:8088") else (set "ORIGIN=%~1")
if "%~2"=="" (set "PAGE=/playground") else (set "PAGE=%~2")
set "URL=%ORIGIN%%PAGE%"
set "PROFILE=%LOCALAPPDATA%\AdrienneMicProfile"
set "FLAG=--unsafely-treat-insecure-origin-as-secure=%ORIGIN%"

echo.
echo   Adriene Voice Playground - microphone mode
echo   URL     : %URL%
echo   Profile : %PROFILE%
echo.

where chrome.exe >nul 2>&1
if %ERRORLEVEL%==0 (
    start "" "chrome.exe" --user-data-dir="%PROFILE%" %FLAG% --app="%URL%"
    echo   Chrome started with the LAN origin treated as secure.
    goto :done
)

where msedge.exe >nul 2>&1
if %ERRORLEVEL%==0 (
    start "" "msedge.exe" --user-data-dir="%PROFILE%" %FLAG% --app="%URL%"
    echo   Edge started with the LAN origin treated as secure.
    goto :done
)

for %%P in (
    "%ProgramFiles%\Google\Chrome\Application\chrome.exe"
    "%ProgramFiles(x86)%\Google\Chrome\Application\chrome.exe"
    "%ProgramFiles(x86)%\Microsoft\Edge\Application\msedge.exe"
    "%ProgramFiles%\Microsoft\Edge\Application\msedge.exe"
) do (
    if exist %%P (
        start "" %%P --user-data-dir="%PROFILE%" %FLAG% --app="%URL%"
        echo   Browser started with the LAN origin treated as secure.
        goto :done
    )
)

echo   No Chrome/Edge found - opening the default browser.
echo   Note: the default browser will not allow microphone capture over plain HTTP.
start "" "%URL%"

:done
echo.
echo   Tip: http://localhost is always treated as secure, so the mic also works
echo   at http://localhost:8088 when the app is opened through the local host.
echo.
endlocal
