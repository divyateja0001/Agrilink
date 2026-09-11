$ErrorActionPreference = "Stop"
$manifest = Join-Path $PSScriptRoot ".run\dev-processes.json"
if (-not (Test-Path -LiteralPath $manifest)) {
    Write-Host "No AgriLink run manifest; nothing stopped."
    exit 0
}

$data = Get-Content -Raw -LiteralPath $manifest | ConvertFrom-Json
if ([IO.Path]::GetFullPath($data.workspace) -ne [IO.Path]::GetFullPath($PSScriptRoot)) {
    throw "Manifest belongs to another workspace; nothing stopped."
}

$stopRequest = Join-Path $PSScriptRoot ".run\dev-stop.request"
Set-Content -LiteralPath $stopRequest -Value "stop" -Encoding ASCII
Start-Sleep -Milliseconds 1500

foreach ($entry in $data.processes) {
    $process = Get-Process -Id $entry.pid -ErrorAction SilentlyContinue
    if (-not $process) { continue }
    $expectedStart = [DateTimeOffset]::Parse($entry.started_at_utc).UtcDateTime
    $actualStart = $process.StartTime.ToUniversalTime()
    $sameStart = [Math]::Abs(($actualStart - $expectedStart).TotalSeconds) -lt 10
    if ($process.ProcessName -eq $entry.process_name -and $sameStart) {
        Stop-Process -Id $process.Id
        Write-Host "Stopped AgriLink $($entry.name) PID $($process.Id)"
    }
    else {
        Write-Warning "PID $($entry.pid) no longer matches the recorded AgriLink process; it was not stopped."
    }
}
Remove-Item -LiteralPath $manifest -Force -ErrorAction SilentlyContinue
Remove-Item -LiteralPath $stopRequest -Force -ErrorAction SilentlyContinue
