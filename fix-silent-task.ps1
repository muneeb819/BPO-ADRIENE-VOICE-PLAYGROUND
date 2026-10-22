# Run this once as Administrator.
# Repoints the 5-minute backend watchdog task at wscript.exe, which has no
# console subsystem, so no PowerShell/CMD window ever appears.
$ErrorActionPreference = "Stop"
$resultFile = Join-Path $PSScriptRoot "silent-task-result.txt"

try {
    $vbs = Join-Path $PSScriptRoot "watchdog-backend.vbs"
    if (-not (Test-Path $vbs)) { throw "Missing launcher: $vbs" }

    $action = New-ScheduledTaskAction -Execute "wscript.exe" -Argument "//B `"$vbs`""
    Set-ScheduledTask -TaskName "AdrienneVoiceBackend" -Action $action | Out-Null

    $lines = @("OK - watchdog task repointed to the silent launcher")
    Get-ScheduledTask -TaskName "AdrienneVoiceBackend" |
        ForEach-Object { $_.Actions | ForEach-Object { $lines += "RUN: $($_.Execute) $($_.Arguments)" } }
    $lines | Set-Content -Path $resultFile -Encoding utf8
} catch {
    @("ERROR: $($_.Exception.Message)") | Set-Content -Path $resultFile -Encoding utf8
    exit 1
}
