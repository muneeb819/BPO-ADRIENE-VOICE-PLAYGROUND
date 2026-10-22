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
    [string]$ProjectRoot = "C:\Users\Wave\Downloads\AdrieneVoiceStudio",
    [switch]$Restart
)

# Hide our own console immediately if the host started us with a visible one
# (Task Scheduler / manual runs). Keeps the watchdog silent in the background.
try {
    Add-Type -Namespace Win32 -Name ConsoleHost -MemberDefinition @'
[DllImport("kernel32.dll")] public static extern IntPtr GetConsoleWindow();
[DllImport("user32.dll")] public static extern bool ShowWindow(IntPtr hWnd, int nCmdShow);
'@ -ErrorAction Stop
    $console = [Win32.ConsoleHost]::GetConsoleWindow()
    if ($console -ne [IntPtr]::Zero) { [void][Win32.ConsoleHost]::ShowWindow($console, 0) }
} catch { }

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

if ($Restart) {
    $owners = @(Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue |
                Select-Object -ExpandProperty OwningProcess -Unique)
    foreach ($owner in $owners) {
        if ($owner) {
            Stop-Process -Id $owner -Force -ErrorAction SilentlyContinue
            Log "stopped backend pid $owner (restart requested)"
        }
    }
    Start-Sleep -Seconds 1
}
else {
    # Auto-restart when server.py changed after the running process started.
    $code = Join-Path $ProjectRoot "server.py"
    $owners = @(Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue |
                Select-Object -ExpandProperty OwningProcess -Unique)
    if ($owners -and (Test-Path $code)) {
        $codeTime = (Get-Item $code).LastWriteTime
        foreach ($owner in $owners) {
            $proc = Get-Process -Id $owner -ErrorAction SilentlyContinue
            if ($proc -and $proc.StartTime -lt $codeTime) {
                Log "code changed - restarting backend pid $owner"
                Stop-Process -Id $owner -Force -ErrorAction SilentlyContinue
                Start-Sleep -Seconds 1
            }
        }
    }
}

if (Test-Backend) {
    Log "backend healthy on 127.0.0.1:$Port - nothing to do"
    exit 0
}

# Prefer pythonw.exe: it has no console subsystem at all, so the backend can
# never pop up a CMD window. Fall back to python.exe started hidden.
$python = (Get-Command pythonw -ErrorAction SilentlyContinue).Source
if (-not $python) {
    $python = (Get-Command python -ErrorAction SilentlyContinue).Source
}
if (-not $python) {
    Log "python not found on PATH - cannot restart the backend"
    exit 1
}

Log "backend not answering on 127.0.0.1:$Port - starting it ($python)"
Start-Process -FilePath $python `
    -ArgumentList "server.py", "--port", "$Port", "--no-open" `
    -WorkingDirectory $ProjectRoot -WindowStyle Hidden

for ($i = 0; $i -lt 15; $i++) {
    Start-Sleep -Seconds 1
    if (Test-Backend) {
        Log "backend restarted and healthy"
        exit 0
    }
}
Log "backend still not answering after the restart attempt"
exit 1
