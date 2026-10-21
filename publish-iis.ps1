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
    [int]$HttpsPort = 443,
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
                 "-Port", "$Port", "-HttpsPort", "$HttpsPort", "-BackendPort", "$BackendPort",
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
    $headers = @"
    <httpProtocol>
      <customHeaders>
        <add name="X-Content-Type-Options" value="nosniff" />
        <add name="X-Frame-Options" value="SAMEORIGIN" />
        <add name="Referrer-Policy" value="no-referrer" />
      </customHeaders>
    </httpProtocol>
"@
    $securityHeaders = @"
    <security>
      <headers>
        <add name="X-Content-Type-Options" value="nosniff" />
        <add name="X-Frame-Options" value="SAMEORIGIN" />
        <add name="Referrer-Policy" value="no-referrer" />
      </headers>
    </security>
"@
    $requestFiltering = @"
    <security>
      <requestFiltering>
        <fileExtensions>
          <add fileExtension=".env" allowed="false" />
          <add fileExtension=".py" allowed="false" />
          <add fileExtension=".db" allowed="false" />
        </fileExtensions>
      </requestFiltering>
    </security>
"@
    $rewrite = @"
    <rewrite>
      <rules>
        <rule name="Adrienne app proxy" stopProcessing="true">
          <match url="^(.*)$" />
          <action type="Rewrite" url="http://127.0.0.1:$BackendPort/{R:1}" />
        </rule>
      </rules>
    </rewrite>
"@
    $tail = @"
  </system.webServer>
</configuration>
"@

    # --- 6. create / refresh the IIS site ----------------------------------
    Invoke-AppCmd "delete site `"$SiteName`"" "delete old site" -AllowFailure | Out-Null
    Invoke-AppCmd "delete apppool `"$AppPoolName`"" "delete old pool" -AllowFailure | Out-Null

    # "No Managed Code" pools leave the worker unable to pre-load a CLR, so the
    # pool is created with the standard v4.0 runtime (the site is static + proxy).
    Invoke-AppCmd "add apppool /name:$AppPoolName /managedRuntimeVersion:v4.0 /managedPipelineMode:Integrated" "add apppool" | Out-Null
    Invoke-AppCmd "set config -section:applicationPools /[name='$AppPoolName'].processModel.idleTimeout /value:00:00:00" "pool idle timeout" -AllowFailure | Out-Null

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

    # --- 7. HTTPS binding (microphone capture needs a secure context) ------
    $httpsUrl = $null
    if ($HttpsPort -gt 0) {
        try {
            $cert = Get-ChildItem Cert:\LocalMachine\My |
                    Where-Object { $_.Subject -eq "CN=$BindAddress" -and $_.HasPrivateKey -and $_.NotAfter -gt (Get-Date).AddDays(30) } |
                    Select-Object -First 1
            if (-not $cert) {
                # Windows PowerShell 5.1 has no -IpAddress switch, so the
                # subjectAltName extension is written explicitly (IP + DNS).
                $san = "ipaddress=$BindAddress&dns=localhost&dns=$($env:COMPUTERNAME.ToLower()).local"
                $cert = New-SelfSignedCertificate -Subject "CN=$BindAddress" `
                    -TextExtension @("2.5.29.37={text}1.3.6.1.5.5.7.3.1", "2.5.29.17={text}$san") `
                    -CertStoreLocation "Cert:\LocalMachine\My" `
                    -NotAfter (Get-Date).AddYears(3) -KeyUsage DigitalSignature, KeyEncipherment `
                    -FriendlyName "Adrienne Voice Playground"
                Write-Log "Created self-signed certificate CN=$BindAddress ($($cert.Thumbprint))"
            } else {
                Write-Log "Reusing certificate $($cert.Thumbprint)"
            }

            # Trust it machine-wide so browsers accept it without a warning.
            $rootStore = New-Object System.Security.Cryptography.X509Certificates.X509Store("Root", "LocalMachine")
            $rootStore.Open("ReadWrite")
            $alreadyTrusted = $rootStore.Certificates | Where-Object { $_.Thumbprint -eq $cert.Thumbprint }
            if (-not $alreadyTrusted) {
                $rootStore.Add((Get-Item "Cert:\LocalMachine\My\$($cert.Thumbprint)"))
                Write-Log "Certificate trusted in LocalMachine\Root"
            }
            $rootStore.Close()

            # The Windows client WebAdministration module cannot attach a
            # certificate, so the binding is written through the
            # Microsoft.Web.Administration API (CertificateHash is a byte[]).
            $dll = "C:\Windows\System32\WindowsPowerShell\v1.0\Modules\IISAdministration\Microsoft.Web.Administration.dll"
            $asm = [Reflection.Assembly]::LoadFrom($dll)
            $mgr = [Activator]::CreateInstance($asm.GetType("Microsoft.Web.Administration.ServerManager", $true))
            $site = $null
            foreach ($s in $mgr.Sites) { if ($s.Name -eq $SiteName) { $site = $s } }
            if (-not $site) { throw "IIS site '$SiteName' not found." }

            $hex = $cert.Thumbprint -replace '[^0-9A-Fa-f]', ''
            $hash = New-Object byte[] ($hex.Length / 2)
            for ($i = 0; $i -lt $hash.Length; $i++) { $hash[$i] = [Convert]::ToByte($hex.Substring($i * 2, 2), 16) }

            $httpsBindings = @($site.Bindings) | Where-Object { $_.protocol -eq "https" }
            if ($httpsBindings) {
                foreach ($b in $httpsBindings) {
                    $b.CertificateStoreName = "My"
                    $b.CertificateHash = $hash
                    $b.SslFlags = 0
                }
                Write-Log "certificate attached to the existing https binding"
            } else {
                # BindingCollection.Add takes (bindingInformation, protocol).
                $b = $site.Bindings.Add("$BindAddress`:$HttpsPort`:*", "https")
                $b.CertificateStoreName = "My"
                $b.CertificateHash = $hash
                $b.SslFlags = 0
                Write-Log "https binding created with the certificate"
            }
            $mgr.CommitChanges()
            Start-Sleep -Seconds 2
            $bindingXml = @($site.Bindings) | ForEach-Object { "$($_.protocol)|$($_.BindingInformation)|$($_.CertificateStoreName)|$($_.SslFlags)" }
            Write-Log ("bindings after commit :: " + ($bindingXml -join " ; "))
            & cmd /c "`"$AppCmd`" restart site `"$SiteName`"" 2>&1 | Out-Null
            Start-Sleep -Seconds 3
            Write-Log "HTTPS binding added on $BindAddress`:$HttpsPort (thumbprint $($cert.Thumbprint))"
            $httpsUrl = "https://$BindAddress`:$HttpsPort"
        } catch {
            Write-Log "HTTPS binding failed: $($_.Exception.Message)" "WARN"
        }
    }

    # --- 8. firewall --------------------------------------------------------
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

    # --- 9. optional startup task ------------------------------------------
    if ($RegisterStartup) {
        $python = (Get-Command python -ErrorAction SilentlyContinue).Source
        $action = New-ScheduledTaskAction -Execute $python `
            -Argument "server.py --port $BackendPort --no-open" -WorkingDirectory $ProjectRoot
        Register-ScheduledTask -TaskName "AdrienneVoiceBackend" -Action $action `
            -Trigger (New-ScheduledTaskTrigger -AtLogOn) -Force | Out-Null
        Write-Log "Scheduled task 'AdrienneVoiceBackend' registered"
    }

    # --- 10. find a working web.config, then verify every route ------------
    $lan = "http://$BindAddress`:$Port"
    $loop = "http://127.0.0.1`:$Port"
    $webConfigPath = Join-Path $WebRoot "web.config"

    # Each optional fragment is validated on its own; a fragment that IIS
    # rejects (locked section, bad value) is dropped instead of breaking the site.
    $assembled = $head
    $fragments = @(
        @{ name = "staticContent";        body = $static },
        @{ name = "httpProtocol headers"; body = $headers },
        @{ name = "security headers";     body = $securityHeaders },
        @{ name = "requestFiltering";     body = $requestFiltering }
    )
    foreach ($fragment in $fragments) {
        Set-Content -Path $webConfigPath -Value ($assembled + $fragment.body + $tail) -Encoding UTF8
        Start-Sleep -Milliseconds 1200
        $probe = Test-Http $lan
        if ($probe.status -eq 200) {
            $assembled += $fragment.body
            Write-Log "web.config fragment '$($fragment.name)' accepted"
        } else {
            Write-Log "web.config fragment '$($fragment.name)' rejected (HTTP $($probe.status)) - skipped" "WARN"
        }
    }

    # Finally the rewrite rules: page routes + the /api reverse proxy.
    Set-Content -Path $webConfigPath -Value ($assembled + $rewrite + $tail) -Encoding UTF8
    Start-Sleep -Milliseconds 1500
    $probePaths = @("/", "/agents", "/api/health")
    $probeResults = @()
    foreach ($p in $probePaths) { $probeResults += Test-Http "$lan$p" }
    Write-Log ("rewrite rules -> [" + (($probeResults | ForEach-Object { $_.status }) -join ",") + "]")
    if (@($probeResults | Where-Object { $_.status -ne 200 }).Count -gt 0) {
        Write-Log "Rewrite rules did not serve every probe route - falling back to static-only." "WARN"
        Set-Content -Path $webConfigPath -Value ($assembled + $tail) -Encoding UTF8
        Start-Sleep -Milliseconds 1200
    }

    $paths = @("/", "/agents", "/playground", "/lab", "/testing", "/analytics", "/security", "/telephony", "/docs", "/api/health")
    $targets = @()
    foreach ($p in $paths) { $targets += [pscustomobject]@{ label = "http $p"; url = "$lan$p" } }
    if ($httpsUrl) {
        foreach ($p in @("/", "/playground", "/lab", "/api/health")) {
            $targets += [pscustomobject]@{ label = "https $p"; url = "$httpsUrl$p" }
        }
    }
    $results = @{}
    for ($attempt = 1; $attempt -le 12; $attempt++) {
        foreach ($target in $targets) {
            if ($results.ContainsKey($target.label)) { continue }
            $results[$target.label] = Test-Http $target.url
        }
        $ok = @($results.Values | Where-Object { $_.status -eq 200 }).Count
        Write-Log "Attempt $attempt : $ok/$($targets.Count) routes answering"
        if ($ok -eq $targets.Count) { break }
        Start-Sleep -Seconds 2
    }
    foreach ($target in $targets) {
        $r = $results[$target.label]
        $level = if ($r.status -eq 200) { "INFO" } else { "ERROR" }
        Write-Log "GET $($target.label) -> $($r.status) ($($r.bytes) bytes)" $level
    }
    $ok = @($results.Values | Where-Object { $_.status -eq 200 }).Count
    Write-Log "Verification: $ok/$($targets.Count) endpoints returned 200"

    Write-Host ""
    Write-Host "  Adriene Voice Playground is published on IIS" -ForegroundColor Green
    Write-Host "  HTTP :  $lan" -ForegroundColor Green
    if ($httpsUrl) {
        Write-Host "  HTTPS:  $httpsUrl   (microphone capture works here)" -ForegroundColor Green
    }
    Write-Host "  Log:  $LogPath" -ForegroundColor DarkGray
    Write-Host ""
    exit 0
} catch {
    Write-Log "FAILED: $($_.Exception.Message)" "ERROR"
    Write-Host "Publish failed: $($_.Exception.Message)" -ForegroundColor Red
    exit 1
}
