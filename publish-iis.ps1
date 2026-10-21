<#
    BPO Adriene - IIS publish + LAN binding.

    Publishes the static front-end to IIS and reverse-proxies /api to the
    local Python backend, then binds the site to this machine's LAN address.

    Usage (self-elevates):
        powershell -ExecutionPolicy Bypass -File .\publish-iis.ps1

    Optional:
        -Port 8088              HTTP port for the IIS site
        -BindAddress 192.168.x  LAN address to bind (default: auto-detect)
        -BackendPort 8010       Port the Python backend listens on (loopback only)
        -RegisterStartup        Create a logon task that starts the backend
#>
param(
    [int]$Port = 8088,
    [string]$BindAddress = "",
    [int]$BackendPort = 8010,
    [string]$SiteName = "AdrienneVoice",
    [string]$AppPoolName = "AdriennePool",
    [string]$WebRoot = "C:\inetpub\AdrienneVoice",
    [string]$ProjectRoot = "C:\Users\Wave\Downloads\AdrieneVoiceStudio",
    [switch]$RegisterStartup
)

$ErrorActionPreference = "Stop"
$LogPath = Join-Path $ProjectRoot "publish-iis.log"
$AppCmd = Join-Path $env:windir "System32\inetsrv\appcmd.exe"

function Write-Log {
    param([string]$Message, [string]$Level = "INFO")
    $stamp = (Get-Date).ToString("yyyy-MM-dd HH:mm:ss")
    $line = "[$stamp] [$Level] $Message"
    Write-Host $line
    Add-Content -Path $LogPath -Value $line
}

function Test-Admin {
    $id = [Security.Principal.WindowsIdentity]::GetCurrent()
    return (New-Object Security.Principal.WindowsPrincipal $id).IsInRole(
        [Security.Principal.WindowsBuiltInRole]::Administrator)
}

# --- self elevation --------------------------------------------------------
if (-not (Test-Admin)) {
    Write-Host "Requesting administrator rights (approve the UAC prompt)..."
    $argList = @("-NoProfile", "-ExecutionPolicy", "Bypass", "-File", "`"$PSCommandPath`"",
                 "-Port", "$Port", "-BackendPort", "$BackendPort",
                 "-SiteName", $SiteName, "-AppPoolName", $AppPoolName,
                 "-WebRoot", "`"$WebRoot`"", "-ProjectRoot", "`"$ProjectRoot`"")
    if ($BindAddress) { $argList += @("-BindAddress", $BindAddress) }
    if ($RegisterStartup) { $argList += "-RegisterStartup" }
    try {
        Start-Process -FilePath "powershell.exe" -Verb RunAs -ArgumentList $argList -Wait
    } catch {
        Write-Host "Elevation was declined - IIS configuration needs administrator rights." -ForegroundColor Red
        exit 1
    }
    exit 0
}

Set-Content -Path $LogPath -Value "=== IIS publish $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss') ==="

function Invoke-AppCmd {
    param([string]$CommandLine, [string]$Description, [switch]$AllowFailure)
    $out = & cmd /c "`"$AppCmd`" $CommandLine" 2>&1
    $code = $LASTEXITCODE
    $text = (($out | Out-String) -replace "\s+", " ").Trim()
    if ($text) { Write-Log "appcmd $Description -> $text" }
    if ($code -ne 0 -and -not $AllowFailure) {
        throw "appcmd failed (exit $code): $Description :: $text"
    }
    return $code
}

function Get-LanAddresses {
    $skip = "vEthernet|Hyper-V|VMware|VirtualBox|Loopback|Bluetooth|Teredo"
    Get-NetIPAddress -AddressFamily IPv4 -ErrorAction SilentlyContinue |
        Where-Object {
            $_.IPAddress -notlike "127.*" -and
            $_.IPAddress -notlike "169.254.*" -and
            $_.InterfaceAlias -notmatch $skip -and
            $_.PrefixOrigin -ne "WellKnown"
        } |
        Sort-Object @{ Expression = {
            switch -Regex ($_.IPAddress) {
                "^192\.168\." { 0 }
                "^10\." { 1 }
                "^172\.(1[6-9]|2\d|3[01])\." { 2 }
                default { 3 }
            }
        } }
}

function Test-Http {
    param([string]$Url)
    try {
        $resp = Invoke-WebRequest -Uri $Url -UseBasicParsing -TimeoutSec 10
        return [pscustomobject]@{ status = $resp.StatusCode; bytes = $resp.RawContentLength; body = "" }
    } catch {
        $status = "ERR"; $body = ""
        if ($_.Exception.Response) {
            try { $status = [int]$_.Exception.Response.StatusCode } catch { }
            try {
                $sr = New-Object IO.StreamReader($_.Exception.Response.GetResponseStream())
                $body = $sr.ReadToEnd()
            } catch { }
        }
        return [pscustomobject]@{ status = $status; bytes = 0; body = $body }
    }
}

try {
    # --- 1. repair IIS config ACLs (blocks appcmd for non-admin readers) ---
    $configDir = Join-Path $env:windir "System32\inetsrv\config"
    foreach ($cfg in @("redirection.config", "applicationHost.config")) {
        $path = Join-Path $configDir $cfg
        if (Test-Path $path) {
            & icacls $path /grant "$env:USERDOMAIN\$env:USERNAME`:(R)" | Out-Null
            Write-Log "ACL repaired: $cfg"
        }
    }
    & icacls $configDir /grant "$env:USERDOMAIN\$env:USERNAME`:(RX)" | Out-Null

    # --- 2. pick the LAN address -------------------------------------------
    $candidates = @(Get-LanAddresses)
    if ($candidates.Count -eq 0) { throw "No usable IPv4 address found on this machine." }
    if ($BindAddress) {
        $chosen = $candidates | Where-Object { $_.IPAddress -eq $BindAddress } | Select-Object -First 1
        if (-not $chosen) { $chosen = [pscustomobject]@{ IPAddress = $BindAddress; InterfaceAlias = "manual" } }
    } else {
        $chosen = $candidates[0]
    }
    $BindAddress = $chosen.IPAddress
    Write-Log "LAN address: $BindAddress ($($chosen.InterfaceAlias))"

    # --- 3. make sure the Python backend is running (loopback only) --------
    $backendUp = $false
    try {
        $probe = Invoke-RestMethod -Uri "http://127.0.0.1:$BackendPort/api/health" -TimeoutSec 4
        $backendUp = ($probe.ok -eq $true)
    } catch { $backendUp = $false }

    if (-not $backendUp) {
        Write-Log "Starting Python backend on 127.0.0.1:$BackendPort"
        $python = (Get-Command python -ErrorAction SilentlyContinue).Source
        if (-not $python) { throw "python not found on PATH" }
        Start-Process -FilePath $python `
            -ArgumentList "server.py", "--port", "$BackendPort", "--no-open" `
            -WorkingDirectory $ProjectRoot -WindowStyle Minimized
        Start-Sleep -Seconds 3
        $probe = Invoke-RestMethod -Uri "http://127.0.0.1:$BackendPort/api/health" -TimeoutSec 8
        $backendUp = ($probe.ok -eq $true)
    }
    if (-not $backendUp) { throw "Backend did not come up on port $BackendPort" }
    Write-Log "Backend health: ok=$($probe.ok) deepgramTts=$($probe.capabilities.deepgramTts) deepgramStt=$($probe.capabilities.deepgramStt)"

    # --- 4. sanitised static publish folder --------------------------------
    if (Test-Path $WebRoot) { Remove-Item $WebRoot -Recurse -Force }
    New-Item -ItemType Directory -Path $WebRoot -Force | Out-Null
    Copy-Item (Join-Path $ProjectRoot "*.html") $WebRoot -Force
    Copy-Item (Join-Path $ProjectRoot "assets") $WebRoot -Recurse -Force
    $copied = (Get-ChildItem $WebRoot -Recurse -File).Count
    Write-Log "Published $copied static files to $WebRoot (no .env, no data, no .py)"

    # --- 5. web.config variants (bisected so a bad section is pinpointed) ---
    $head = @"
<?xml version="1.0" encoding="UTF-8"?>
<configuration>
  <system.webServer>
    <defaultDocument>
      <files>
        <clear />
        <add value="index.html" />
      </files>
    </defaultDocument>
    <httpErrors existingResponse="PassThrough" />
"@
    $static = @"
    <staticContent>
      <remove fileExtension=".woff2" />
      <mimeMap fileExtension=".woff2" mimeType="font/woff2" />
    </staticContent>
"@
    $security = @"
    <security>
      <requestFiltering>
        <fileExtensions>
          <add fileExtension=".env" allowed="false" />
          <add fileExtension=".py" allowed="false" />
          <add fileExtension=".db" allowed="false" />
        </fileExtensions>
      </requestFiltering>
      <headers>
        <add name="X-Content-Type-Options" value="nosniff" />
        <add name="X-Frame-Options" value="SAMEORIGIN" />
        <add name="Referrer-Policy" value="no-referrer" />
      </headers>
    </security>
"@
    $rewrite = @"
    <rewrite>
      <rules>
        <rule name="Adriene API proxy" stopProcessing="true">
          <match url="^api/(.*)" />
          <action type="Rewrite" url="http://127.0.0.1:$BackendPort/api/{R:1}" />
        </rule>
        <rule name="Adriene page routes" stopProcessing="true">
          <match url="^(agents|playground|lab|testing|analytics|security|telephony|docs)$" />
          <action type="Rewrite" url="{R:1}.html" />
        </rule>
        <rule name="Adriene foundation route" stopProcessing="true">
          <match url="^foundation$" />
          <action type="Rewrite" url="index.html" />
        </rule>
      </rules>
    </rewrite>
"@
    $tail = @"
  </system.webServer>
</configuration>
"@
    $variants = @(
        @{ name = "minimal";      body = $head + $tail },
        @{ name = "static+fonts"; body = $head + $static + $tail },
        @{ name = "security";     body = $head + $static + $security + $tail },
        @{ name = "rewrite+proxy"; body = $head + $static + $security + $rewrite + $tail }
    )

    # --- 6. create / refresh the IIS site ----------------------------------
    Invoke-AppCmd "delete site `"$SiteName`"" "delete old site" -AllowFailure | Out-Null
    Invoke-AppCmd "delete apppool `"$AppPoolName`"" "delete old pool" -AllowFailure | Out-Null

    Invoke-AppCmd "add apppool /name:$AppPoolName /managedRuntimeVersion:`"`"`" /managedPipelineMode:Integrated" "add apppool" | Out-Null
    Invoke-AppCmd "set config /section:applicationPools /[name='$AppPoolName'].processModel.idleTimeout /value:00:00:00" "pool idle timeout" -AllowFailure | Out-Null

    # Wildcard host binding so the site answers on the LAN IP and on localhost.
    $binding = "http/*:$Port`:"
    $code = Invoke-AppCmd "add site /name:$SiteName /bindings:`"$binding`" /physicalPath:`"$WebRoot`"" "add site (wildcard binding)" -AllowFailure
    if ($code -ne 0) {
        $binding = "http/*:$Port`:$BindAddress"
        Invoke-AppCmd "add site /name:$SiteName /bindings:`"$binding`" /physicalPath:`"$WebRoot`"" "add site (LAN binding)" | Out-Null
    }
    Invoke-AppCmd "set app `"$SiteName/`" /applicationPool:$AppPoolName" "assign app pool" -AllowFailure | Out-Null
    Invoke-AppCmd "start apppool `"$AppPoolName`"" "start app pool" -AllowFailure | Out-Null
    Invoke-AppCmd "start site `"$SiteName`"" "start site" -AllowFailure | Out-Null

    $sites = (& cmd /c "`"$AppCmd`" list site" 2>&1 | Out-String)
    Write-Log ("IIS sites: " + (($sites -replace "\s+", " ").Trim()))
    if ($sites -notmatch [regex]::Escape($SiteName)) {
        throw "Site '$SiteName' is not present in the IIS configuration."
    }
    & icacls $WebRoot /grant "IIS_IUSRS`:(OI)(CI)(RX)" /T | Out-Null

    # --- 7. firewall --------------------------------------------------------
    try {
        if (-not (Get-NetFirewallRule -DisplayName "Adriene IIS $Port" -ErrorAction SilentlyContinue)) {
            New-NetFirewallRule -DisplayName "Adriene IIS $Port" -Direction Inbound `
                -Protocol TCP -LocalPort $Port -Action Allow -Profile Any | Out-Null
            Write-Log "Firewall rule 'Adriene IIS $Port' added"
        } else {
            Write-Log "Firewall rule 'Adriene IIS $Port' already present"
        }
    } catch {
        Write-Log "Firewall rule skipped: $($_.Exception.Message)" "WARN"
    }

    # --- 8. optional startup task ------------------------------------------
    if ($RegisterStartup) {
        $python = (Get-Command python -ErrorAction SilentlyContinue).Source
        $action = New-ScheduledTaskAction -Execute $python `
            -Argument "server.py --port $BackendPort --no-open" -WorkingDirectory $ProjectRoot
        Register-ScheduledTask -TaskName "AdrienneVoiceBackend" -Action $action `
            -Trigger (New-ScheduledTaskTrigger -AtLogOn) -Force | Out-Null
        Write-Log "Scheduled task 'AdrienneVoiceBackend' registered"
    }

    # --- 9. find a working web.config, then verify every route -------------
    $lan = "http://$BindAddress`:$Port"
    $loop = "http://127.0.0.1`:$Port"
    $chosenVariant = $null
    foreach ($variant in $variants) {
        Set-Content -Path (Join-Path $WebRoot "web.config") -Value $variant.body -Encoding UTF8
        Start-Sleep -Milliseconds 1200
        $probe = Test-Http $lan
        Write-Log "config variant '$($variant.name)' -> GET / = $($probe.status)"
        if ($probe.status -eq 200) { $chosenVariant = $variant; break }
        if ($probe.body) { Write-Log "   body: $($probe.body.Substring(0, [Math]::Min(240, $probe.body.Length)))" }
    }
    if (-not $chosenVariant) {
        Write-Log "No web.config variant served the site - see the variant results above." "ERROR"
        throw "IIS site does not answer on $lan"
    }
    Write-Log "Using web.config variant '$($chosenVariant.name)'"

    $paths = @("/", "/agents", "/playground", "/lab", "/testing", "/analytics", "/security", "/telephony", "/docs", "/api/health")
    $results = @{}
    for ($attempt = 1; $attempt -le 12; $attempt++) {
        foreach ($path in $paths) {
            if ($results.ContainsKey($path)) { continue }
            $r = Test-Http "$lan$path"
            $results[$path] = $r
        }
        $ok = @($results.Values | Where-Object { $_.status -eq 200 }).Count
        Write-Log "Attempt $attempt : $ok/$($paths.Count) routes answering on $lan"
        if ($ok -eq $paths.Count) { break }
        Start-Sleep -Seconds 2
    }
    foreach ($path in $paths) {
        $r = $results[$path]
        $level = if ($r.status -eq 200) { "INFO" } else { "ERROR" }
        Write-Log "GET $path -> $($r.status) ($($r.bytes) bytes)" $level
    }
    $ok = @($results.Values | Where-Object { $_.status -eq 200 }).Count
    Write-Log "Verification: $ok/$($paths.Count) endpoints returned 200 on $lan (loopback alias $loop)"

    Write-Host ""
    Write-Host "  Adriene Voice Playground is published on IIS" -ForegroundColor Green
    Write-Host "  URL:  $lan" -ForegroundColor Green
    Write-Host "  Log:  $LogPath" -ForegroundColor DarkGray
    Write-Host ""
    exit 0
} catch {
    Write-Log "FAILED: $($_.Exception.Message)" "ERROR"
    Write-Host "Publish failed: $($_.Exception.Message)" -ForegroundColor Red
    exit 1
}
