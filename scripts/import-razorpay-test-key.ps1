param(
    [Parameter(Mandatory = $true)]
    [string]$CsvPath
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
$envPath = Join-Path $root "backend\.env"

if (-not (Test-Path -LiteralPath $CsvPath -PathType Leaf)) {
    throw "Razorpay key CSV was not found: $CsvPath"
}
if (-not (Test-Path -LiteralPath $envPath -PathType Leaf)) {
    throw "backend\.env is missing. Copy backend\.env.example first."
}

$rows = @(Import-Csv -LiteralPath $CsvPath)
if ($rows.Count -ne 1) {
    throw "The Razorpay CSV must contain exactly one credential row."
}

$keyId = [string]$rows[0].key_id
$keySecret = [string]$rows[0].key_secret
if (-not $keyId.StartsWith("rzp_test_")) {
    throw "Only a Razorpay Test Mode key beginning with rzp_test_ is accepted."
}
if ([string]::IsNullOrWhiteSpace($keySecret)) {
    throw "The Razorpay key_secret field is empty. Regenerate and download the test key."
}

$secretBytes = New-Object byte[] 32
$random = [Security.Cryptography.RandomNumberGenerator]::Create()
try {
    $random.GetBytes($secretBytes)
}
finally {
    $random.Dispose()
}
$webhookSecret = [Convert]::ToBase64String($secretBytes).TrimEnd('=').Replace('+', '-').Replace('/', '_')

$settings = [ordered]@{
    RAZORPAY_ENABLED = "true"
    RAZORPAY_KEY_ID = $keyId
    RAZORPAY_KEY_SECRET = $keySecret
    RAZORPAY_WEBHOOK_SECRET = $webhookSecret
}
$lines = [Collections.Generic.List[string]]@(Get-Content -LiteralPath $envPath)
foreach ($name in $settings.Keys) {
    $replacement = "$name=$($settings[$name])"
    $match = -1
    for ($index = 0; $index -lt $lines.Count; $index++) {
        if ($lines[$index] -match "^$([regex]::Escape($name))=") {
            $match = $index
            break
        }
    }
    if ($match -ge 0) {
        $lines[$match] = $replacement
    }
    else {
        $lines.Add($replacement)
    }
}

[IO.File]::WriteAllLines($envPath, $lines, (New-Object Text.UTF8Encoding($false)))
Write-Host "Razorpay Test Mode credentials imported into backend\.env. Values were not displayed."
Write-Host "A separate webhook secret was generated. Configure the matching secret in the Razorpay dashboard when a public webhook URL is available."
