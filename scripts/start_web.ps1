param(
    [ValidateSet("demo", "private")]
    [string]$Mode = "demo",
    [switch]$Build
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
$env:CROSSBORDER_APP_MODE = $Mode

if ($Build -or -not (Test-Path (Join-Path $root "frontend\dist\index.html"))) {
    Push-Location (Join-Path $root "frontend")
    try {
        npm install
        npm run build
    } finally {
        Pop-Location
    }
}

Push-Location $root
try {
    python -m uvicorn crossborder_api.main:app --host 127.0.0.1 --port 8000
} finally {
    Pop-Location
}
