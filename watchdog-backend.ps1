<#
    BPO Adriene - backend watchdog.

    Checks the local Python API and restarts it when it is not answering.
    Designed to run from Task Scheduler (at logon and every few minutes) so
    the IIS reverse proxy always has a live backend to talk to.

    Usage:  powershell -ExecutionPolicy Bypass -File .\watchdog-backend.ps1
#>
param(
    [int]$Port = 8010,
    [int]$TimeoutSec = 5,
    [string]$ProjectRoot = "C:\Users\Wave\Downloads\AdrieneVoiceStudio"
)

$ErrorActionPreference = "Continue"
$log = Join-Path $ProjectRoot "backend-watchdog.log"
function Log($m) {
    $line = "[{0}] {1}" -f (Get-Date).ToString("yyyy-MM-dd HH:mm:ss"), $m
    Add-Content -Path $log -Value $line
}

function Test-Backend {
    try {
        $r = Invoke-RestMethod -Uri "http://127.0.0.1:$Port/api/health" -TimeoutSec $TimeoutSec
        return ($r.ok -eq $true)
    } catch {
        return $false
    }
}

if (Test-Backend) {
    Log "backend healthy on 127.0.0.1:$Port - nothing to do"
    exit 0
}

$python = (Get-Command python -ErrorAction SilentlyContinue).Source
if (-not $python) {
    Log "python not found on PATH - cannot restart the backend"
    exit 1
}

Log "backend not answering on 127.0.0.1:$Port - starting it"
Start-Process -FilePath $python `
    -ArgumentList "server.py", "--port", "$Port", "--no-open" `
    -WorkingDirectory $ProjectRoot -WindowStyle Minimized

for ($i = 0; $i -lt 15; $i++) {
    Start-Sleep -Seconds 1
    if (Test-Backend) {
        Log "backend restarted and healthy"
        exit 0
    }
}
Log "backend still not answering after the restart attempt"
exit 1
