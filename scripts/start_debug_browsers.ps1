[CmdletBinding()]
param(
    [string]$Url = "http://localhost:8501",
    [int]$ChromePort = 9222,
    [int]$EdgePort = 9223,
    [int]$WaitSeconds = 15,
    [switch]$SkipChrome,
    [switch]$SkipEdge
)

$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent $PSScriptRoot
$StateRoot = Join-Path $ProjectRoot ".cache\browser-debug"

function Find-BrowserExecutable {
    param([ValidateSet("chrome", "edge")][string]$Browser)

    $candidates = if ($Browser -eq "chrome") {
        @(
            "$env:ProgramFiles\Google\Chrome\Application\chrome.exe",
            "${env:ProgramFiles(x86)}\Google\Chrome\Application\chrome.exe",
            "$env:LOCALAPPDATA\Google\Chrome\Application\chrome.exe"
        )
    } else {
        @(
            "${env:ProgramFiles(x86)}\Microsoft\Edge\Application\msedge.exe",
            "$env:ProgramFiles\Microsoft\Edge\Application\msedge.exe",
            "$env:LOCALAPPDATA\Microsoft\Edge\Application\msedge.exe"
        )
    }

    $executable = $candidates | Where-Object { $_ -and (Test-Path -LiteralPath $_) } | Select-Object -First 1
    if (-not $executable) {
        throw "Could not find $Browser. Checked: $($candidates -join ', ')"
    }
    return $executable
}

function Test-DebugEndpoint {
    param([int]$Port)
    try {
        $response = Invoke-RestMethod -Uri "http://127.0.0.1:$Port/json/version" -TimeoutSec 1
        return $null -ne $response.webSocketDebuggerUrl
    } catch {
        return $false
    }
}

function Assert-PortAvailable {
    param([int]$Port)
    if (Test-DebugEndpoint -Port $Port) {
        return
    }
    $listener = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue
    if ($listener) {
        throw "Port $Port is already used by process $($listener.OwningProcess), but it is not a Chromium debug endpoint."
    }
}

function Start-DebugBrowser {
    param(
        [ValidateSet("chrome", "edge")][string]$Browser,
        [int]$Port
    )

    if (Test-DebugEndpoint -Port $Port) {
        Write-Host "$Browser debug endpoint already available at http://127.0.0.1:$Port"
        return
    }

    Assert-PortAvailable -Port $Port
    $executable = Find-BrowserExecutable -Browser $Browser
    $profilePath = Join-Path $StateRoot "$Browser-profile"
    New-Item -ItemType Directory -Path $profilePath -Force | Out-Null

    $arguments = @(
        "--remote-debugging-address=127.0.0.1",
        "--remote-debugging-port=$Port",
        "--user-data-dir=$profilePath",
        "--no-first-run",
        "--no-default-browser-check",
        "--disable-sync",
        "--new-window",
        $Url
    )
    $process = Start-Process -FilePath $executable -ArgumentList $arguments -PassThru -WindowStyle Hidden
    Set-Content -LiteralPath (Join-Path $StateRoot "$Browser.pid") -Value $process.Id

    $deadline = (Get-Date).AddSeconds($WaitSeconds)
    while ((Get-Date) -lt $deadline) {
        if (Test-DebugEndpoint -Port $Port) {
            Write-Host "$browser ready: http://127.0.0.1:$Port (PID $($process.Id))"
            return
        }
        Start-Sleep -Milliseconds 250
    }
    throw "$browser started as PID $($process.Id), but debug endpoint $Port did not become ready within $WaitSeconds seconds."
}

New-Item -ItemType Directory -Path $StateRoot -Force | Out-Null
if (-not $SkipChrome) { Start-DebugBrowser -Browser "chrome" -Port $ChromePort }
if (-not $SkipEdge) { Start-DebugBrowser -Browser "edge" -Port $EdgePort }

Write-Host "Browser debug sessions are ready."
Write-Host "Chrome: http://127.0.0.1:$ChromePort"
Write-Host "Edge:   http://127.0.0.1:$EdgePort"
