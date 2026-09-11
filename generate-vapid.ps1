$ErrorActionPreference = "Stop"
$root = $PSScriptRoot
$python = Join-Path $root ".venv\Scripts\python.exe"

if (-not (Test-Path -LiteralPath $python)) {
    Write-Host "AgriLink VAPID setup: Python venv missing. Complete the backend setup first." -ForegroundColor Red
    exit 1
}

& $python (Join-Path $root "scripts\generate_vapid.py")
exit $LASTEXITCODE
