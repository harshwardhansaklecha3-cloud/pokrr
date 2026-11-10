# POKRR online: starts the game and a free Cloudflare quick tunnel, then
# shows the link to send to friends. Closing this window stops both.
# (Started by "Start POKRR online.bat".)

param([int]$Port = 8000)
$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root
$Host.UI.RawUI.WindowTitle = 'POKRR online - keep this window open'

function Say($text, $color = 'Gray') { Write-Host $text -ForegroundColor $color }

Say ''
Say '  POKRR online  (play chips only)' 'White'
Say '  ------------------------------------------------' 'DarkGray'

# --- 1. Cloudflare's tunnel app --------------------------------------------
$cf = $null
$cmd = Get-Command cloudflared -ErrorAction SilentlyContinue
if ($cmd) { $cf = $cmd.Source }
if (-not $cf) {
    foreach ($p in @("$env:ProgramFiles\cloudflared\cloudflared.exe",
                     "${env:ProgramFiles(x86)}\cloudflared\cloudflared.exe",
                     "$env:LOCALAPPDATA\Microsoft\WinGet\Links\cloudflared.exe")) {
        if ($p -and (Test-Path $p)) { $cf = $p; break }
    }
}
if (-not $cf) {
    Say ''
    Say '  Cloudflare''s tunnel app (cloudflared) is not installed yet.' 'Yellow'
    Say '  Install it once by running this in PowerShell, then start me again:' 'Yellow'
    Say ''
    Say '      winget install --id Cloudflare.cloudflared' 'White'
    Say ''
    Say '  (If it was just installed, close this window and open it again.)' 'DarkGray'
    exit 1
}

# --- 2. Keep the laptop awake while hosting ------------------------------------
try {
    Add-Type -Namespace Pokrr -Name Power -MemberDefinition '[DllImport("kernel32.dll")] public static extern uint SetThreadExecutionState(uint esFlags);'
    [void][Pokrr.Power]::SetThreadExecutionState([uint32]'0x80000001')   # continuous + system required
    Say '  Laptop will stay awake while this window is open.' 'DarkGray'
} catch { }

# --- 3. The game server ---------------------------------------------------------
$logs = Join-Path $env:TEMP 'pokrr'
New-Item -ItemType Directory -Force $logs | Out-Null
function Test-Up {
    try { (Invoke-WebRequest "http://127.0.0.1:$Port/" -UseBasicParsing -TimeoutSec 2).StatusCode -eq 200 }
    catch { $false }
}
$server = $null
if (Test-Up) {
    Say '  POKRR is already running on this laptop - using it.' 'DarkGray'
} else {
    Say '  Starting POKRR...'
    $py = Join-Path $root '.venv\Scripts\python.exe'
    if (-not (Test-Path $py)) { Say "  Can't find $py" 'Red'; exit 1 }
    # -NoNewWindow: tied to this window, so closing the window stops it too
    $server = Start-Process -FilePath $py -NoNewWindow -PassThru `
        -ArgumentList "-m uvicorn server.app:app --host 127.0.0.1 --port $Port" `
        -RedirectStandardOutput (Join-Path $logs 'server.log') `
        -RedirectStandardError (Join-Path $logs 'server-errors.log')
    $ok = $false
    for ($i = 0; $i -lt 40; $i++) { Start-Sleep -Milliseconds 500; if (Test-Up) { $ok = $true; break } }
    if (-not $ok) { Say "  POKRR did not start. Details: $logs\server-errors.log" 'Red'; exit 1 }
}

# --- 4. The tunnel ---------------------------------------------------------------
$tlog = Join-Path $logs "tunnel-$Port.log"
# Already online (launcher started twice)? Show that link instead of making a
# new one - a second start would make the first link stop working.
$running = Get-CimInstance Win32_Process -Filter "Name='cloudflared.exe'" -ErrorAction SilentlyContinue |
    Where-Object { $_.CommandLine -match "127\.0\.0\.1:$Port" }
if ($running -and (Test-Path $tlog)) {
    $m = Select-String -Path $tlog -Pattern 'https://[a-z0-9-]+\.trycloudflare\.com' | Select-Object -Last 1
    if ($m) {
        $old = $m.Matches[0].Value
        try { Set-Clipboard -Value $old } catch { }
        Say ''
        Say '  POKRR is ALREADY online (another POKRR online window is open).' 'Yellow'
        Say "  Your link is still:  $old   (copied)" 'White'
        Say '  Use that window to stop it. This window can be closed.' 'Yellow'
        if ($server -and -not $server.HasExited) { Stop-Process -Id $server.Id -Force }
        exit 0
    }
}
Say '  Opening a free Cloudflare tunnel...'
Remove-Item $tlog -ErrorAction SilentlyContinue
$tunnel = Start-Process -FilePath $cf -NoNewWindow -PassThru `
    -ArgumentList "tunnel --no-autoupdate --url http://127.0.0.1:$Port" `
    -RedirectStandardOutput (Join-Path $logs "tunnel-out-$Port.log") -RedirectStandardError $tlog
$url = $null
for ($i = 0; $i -lt 90 -and -not $url; $i++) {
    Start-Sleep -Milliseconds 500
    if ($tunnel.HasExited) { break }
    if (Test-Path $tlog) {
        $m = Select-String -Path $tlog -Pattern 'https://[a-z0-9-]+\.trycloudflare\.com' -ErrorAction SilentlyContinue |
             Select-Object -First 1
        if ($m) { $url = $m.Matches[0].Value }
    }
}
if (-not $url) {
    Say '  Could not open the tunnel (internet down, or Cloudflare busy). Try again in a minute.' 'Red'
    Say "  Details: $tlog" 'DarkGray'
    if ($tunnel -and -not $tunnel.HasExited) { Stop-Process -Id $tunnel.Id -Force }
    if ($server -and -not $server.HasExited) { Stop-Process -Id $server.Id -Force }
    exit 1
}

# A brand-new link takes a little while to exist on the internet. Asking for
# it too early makes the router and Windows remember "no such site" for
# minutes - so ask Cloudflare's own DNS first, and only then try the link.
$hostName = ([uri]$url).Host
Say '  Getting the link ready (this can take up to a minute)...'
$ready = $false
for ($i = 0; $i -lt 60 -and -not $ready; $i++) {
    try {
        $null = Resolve-DnsName $hostName -Server 1.1.1.1 -DnsOnly -Type A -ErrorAction Stop
        $ready = $true
    } catch { Start-Sleep -Seconds 1 }
}
Start-Sleep -Seconds 4
$works = $false
for ($i = 0; $i -lt 15 -and -not $works; $i++) {
    try {
        Clear-DnsClientCache -ErrorAction SilentlyContinue
        $r = Invoke-WebRequest $url -UseBasicParsing -TimeoutSec 10
        $works = $r.StatusCode -eq 200
    } catch { Start-Sleep -Seconds 3 }
}
if (-not $works) {
    Say '  The link is slow to appear on this network. It usually works within a' 'Yellow'
    Say '  couple of minutes - if a page says "can''t be reached", wait and reload.' 'Yellow'
}

$url = "$url/play"          # the game itself (the bare link opens the home page)
try { Set-Clipboard -Value $url } catch { }
Say ''
Say '  ================================================' 'Green'
Say '   POKRR is ONLINE. Send this link to your friends:' 'Green'
Say ''
Say "     $url" 'White'
Say ''
Say '   (already copied - just paste it in WhatsApp)' 'Green'
Say '  ================================================' 'Green'
Say ''
Say '  * Open the link yourself, Start a table, then use "Invite friends".'
Say '  * The link changes every time you start this - start it only once.'
Say '  * If a friend sees "site can''t be reached", ask them to wait a minute and reload.'
Say '  * Keep this window open while you play. Press Enter (or close it) to stop.'
Say ''
if (-not $env:POKRR_NO_BROWSER) { Start-Process $url }

# --- 5. Stay up; stop everything on Enter --------------------------------------
try {
    while ($true) {
        if ($tunnel.HasExited) { Say '  The tunnel stopped. Start me again for a new link.' 'Red'; break }
        if ($server -and $server.HasExited) { Say '  The game server stopped. Start me again.' 'Red'; break }
        $key = $false; try { $key = [Console]::KeyAvailable } catch { }
        if ($key) {
            $k = [Console]::ReadKey($true)
            if ($k.Key -eq 'Enter' -or $k.Key -eq 'Escape') { break }
        }
        Start-Sleep -Milliseconds 500
    }
} finally {
    Say '  Stopping...' 'DarkGray'
    if ($tunnel -and -not $tunnel.HasExited) { Stop-Process -Id $tunnel.Id -Force -ErrorAction SilentlyContinue }
    if ($server -and -not $server.HasExited) { Stop-Process -Id $server.Id -Force -ErrorAction SilentlyContinue }
}
