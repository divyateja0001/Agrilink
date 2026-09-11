param(
    [ValidateSet("supabase", "local")]
    [string]$Database = "supabase",
    [switch]$SkipMigration,
    [switch]$PhoneHttps,
    [string]$LanAddress,
    [string]$CertificatePath = "$PSScriptRoot\certs\agrilink-local.pem",
    [string]$CertificateKeyPath = "$PSScriptRoot\certs\agrilink-local-key.pem"
)

$ErrorActionPreference = "Stop"
$root = $PSScriptRoot
$python = Join-Path $root ".venv\Scripts\python.exe"

if (-not (Test-Path -LiteralPath $python)) {
    Write-Host "AgriLink preflight: Python venv missing. Run py -3.13 -m venv .venv." -ForegroundColor Red
    exit 1
}
if (-not (Test-Path -LiteralPath "$root\backend\.env")) {
    Write-Host "AgriLink preflight: backend\.env is missing." -ForegroundColor Red
    exit 1
}

$arguments = @("$root\scripts\dev_supervisor.py", "--database", $Database)
if ($SkipMigration) { $arguments += "--skip-migration" }
if ($PhoneHttps) {
    if (-not $LanAddress) {
        Write-Host "AgriLink preflight: -PhoneHttps requires -LanAddress with this laptop's Wi-Fi IPv4 address." -ForegroundColor Red
        exit 1
    }
    if (-not (Test-Path -LiteralPath $CertificatePath) -or -not (Test-Path -LiteralPath $CertificateKeyPath)) {
        Write-Host "AgriLink preflight: HTTPS certificate files are missing. Follow README > Phone GPS over HTTPS." -ForegroundColor Red
        exit 1
    }
    $arguments += @("--phone-https", "--lan-address", $LanAddress, "--certificate", $CertificatePath, "--certificate-key", $CertificateKeyPath)
}
& $python -u @arguments
exit $LASTEXITCODE
