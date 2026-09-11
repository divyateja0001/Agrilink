param([string]$AdminUser="postgres",[string]$HostName="127.0.0.1",[int]$Port=5432,[Parameter(Mandatory=$true)][string]$AppPassword)
$ErrorActionPreference="Stop"
if(-not(Get-Command psql.exe -ErrorAction SilentlyContinue)){throw "psql.exe was not found. Install PostgreSQL and add its bin folder to PATH."}
if($AppPassword.Length -lt 12 -or $AppPassword -match "['`r`n]"){throw "AppPassword must be at least 12 characters and cannot contain quotes or newlines."}
& pg_isready.exe -h $HostName -p $Port | Out-Host;if($LASTEXITCODE -ne 0){throw "PostgreSQL is not accepting connections at ${HostName}:$Port."}
& psql.exe -X -v ON_ERROR_STOP=1 -h $HostName -p $Port -U $AdminUser -d postgres --set="app_password=$AppPassword" -f "$PSScriptRoot\scripts\create-db.sql"
if($LASTEXITCODE -ne 0){throw "Database creation failed."};Write-Host "AgriLink database and restricted account are ready." -ForegroundColor Green
