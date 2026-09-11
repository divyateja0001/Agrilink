$ErrorActionPreference = "Stop"
$root = $PSScriptRoot
$python = Join-Path $root ".venv\Scripts\python.exe"

function Fail([string]$Message) {
    Write-Host "AgriLink Supabase setup: $Message" -ForegroundColor Red
    exit 1
}

if (-not (Test-Path -LiteralPath $python)) {
    Fail "Python virtual environment missing. Create .venv and install backend requirements first."
}
if (-not (Test-Path -LiteralPath "$root\backend\.env")) {
    Fail "backend\.env is missing. Copy backend\.env.example and add your Supabase values."
}

Push-Location "$root\backend"
try {
    & $python ".\scripts\bootstrap_supabase.py"
    if ($LASTEXITCODE -ne 0) { Fail "role/schema bootstrap failed." }

    & $python -m alembic upgrade head
    if ($LASTEXITCODE -ne 0) { Fail "Alembic migration failed." }

    $previousDemoMode = $env:DEMO_MODE
    try {
        $env:DEMO_MODE = "true"
        & $python ".\seed.py" --seed-demo --confirm-demo-seed
    } finally {
        $env:DEMO_MODE = $previousDemoMode
    }
    if ($LASTEXITCODE -ne 0) { Fail "demo seed failed." }
}
finally {
    Pop-Location
}

Write-Host "Supabase schema, migrations, and fictional demo data are ready." -ForegroundColor Green
