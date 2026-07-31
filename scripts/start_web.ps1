param(
    [ValidateSet("demo", "private")]
    [string]$Mode = "demo",
    [switch]$Build,
    [switch]$OpenBrowser,
    [ValidateRange(1, 65535)]
    [int]$Port = 8000
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
$env:CROSSBORDER_APP_MODE = $Mode
$root = (Resolve-Path -LiteralPath $root).Path
$url = "http://127.0.0.1:$Port"

if (-not (Get-Command python -ErrorAction SilentlyContinue)) {
    throw "[Python check] python was not found. Install Python 3.10+ and reopen the terminal."
}

try {
    python -c "import autoclean, fastapi, uvicorn" 2>$null
    if ($LASTEXITCODE -ne 0) { throw "missing dependency" }
} catch {
    throw "[Python dependencies] Required packages are missing. Run: python -m pip install -r requirements.txt"
}

$frontend = Join-Path $root "frontend"
$distIndex = Join-Path $frontend "dist\index.html"
$needsBuild = $Build -or -not (Test-Path $distIndex)
if (-not $needsBuild) {
    $distTime = (Get-Item $distIndex).LastWriteTimeUtc
    $newerSource = Get-ChildItem (Join-Path $frontend "src"), (Join-Path $frontend "package.json"), (Join-Path $frontend "package-lock.json") -Recurse -File | Where-Object { $_.LastWriteTimeUtc -gt $distTime } | Select-Object -First 1
    $needsBuild = $null -ne $newerSource
}

$expectedFingerprint = python -c "from crossborder_api.build_identity import current_build_fingerprint; print(current_build_fingerprint(r'$($root.Replace("'", "''"))'))"
if ($LASTEXITCODE -ne 0 -or -not $expectedFingerprint) {
    throw "[Build identity] Failed to calculate the current workspace fingerprint."
}
$expectedFingerprint = $expectedFingerprint.Trim()

$listener = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue | Select-Object -First 1
if ($listener) {
    $health = $null
    try {
        $health = Invoke-RestMethod -Uri "$url/api/v1/health" -TimeoutSec 3
    } catch {
        throw "[Port check] Port $Port is owned by PID $($listener.OwningProcess), but it is not a verifiable CrossBorder service. It was not stopped."
    }
    $sameWorkspace = [string]::Equals(
        [string]$health.workspace_root,
        $root,
        [System.StringComparison]::OrdinalIgnoreCase
    )
    $sameBuild = $health.build_fingerprint -eq $expectedFingerprint
    $sameMode = $health.mode -eq $Mode
    if ($sameWorkspace -and $sameBuild -and $sameMode) {
        if ($OpenBrowser) { Start-Process $url }
        Write-Host "CrossBorder is already running with the current build at $url"
        exit 0
    }
    if (-not $sameWorkspace) {
        throw "[Port check] Port $Port is owned by another workspace (PID $($listener.OwningProcess)). It was not stopped."
    }
    $processInfo = Get-Process -Id $listener.OwningProcess -ErrorAction Stop
    if ($processInfo.ProcessName -notmatch '^python') {
        throw "[Port check] The stale workspace service is not a Python process. PID $($listener.OwningProcess) was not stopped."
    }
    Write-Host "Restarting stale CrossBorder process PID $($listener.OwningProcess)..."
    Stop-Process -Id $listener.OwningProcess -ErrorAction Stop
    $deadline = (Get-Date).AddSeconds(15)
    do {
        Start-Sleep -Milliseconds 250
        $remaining = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue
    } while ($remaining -and (Get-Date) -lt $deadline)
    if ($remaining) {
        throw "[Port check] PID $($listener.OwningProcess) did not release port $Port."
    }
}

if ($needsBuild) {
    if (-not (Get-Command npm -ErrorAction SilentlyContinue)) {
        throw "[Frontend build] npm was not found. Install Node.js 20+ and reopen the terminal."
    }
    Push-Location (Join-Path $root "frontend")
    try {
        if (-not (Test-Path "node_modules")) { npm install }
        npm run build
        if ($LASTEXITCODE -ne 0) { throw "[Frontend build] npm run build failed. Run it in frontend/ for full diagnostics." }
    } finally {
        Pop-Location
    }
}

Push-Location $root
try {
    if ($OpenBrowser) {
        $helper = Join-Path $PSScriptRoot "open_when_ready.ps1"
        Start-Process powershell -ArgumentList @(
            "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", $helper,
            "-Url", $url, "-ExpectedMode", $Mode, "-ExpectedFingerprint", $expectedFingerprint
        ) -WindowStyle Hidden
    }
    python -m uvicorn crossborder_api.main:app --host 127.0.0.1 --port $Port
} finally {
    Pop-Location
}
