# Run boe_header_loader.py to load BOE header XML into PostgreSQL.
# Usage:
#   .\scripts\run-boe-header-loader.ps1
#
# Prerequisites:
#   - Put XML files in: boe-project\api\other_uploaded_json\boe_header_xml\boe_header_load\
#   - DB running (e.g. docker compose up -d) with postgres on localhost:5432
#
# DB connection uses env vars. Defaults below match docker-compose (local Postgres).
# Override with .env or: $env:DB_HOST="your-host"; .\scripts\run-boe-header-loader.ps1

$ErrorActionPreference = "Stop"
$root = Split-Path $PSScriptRoot -Parent
$loaderDir = Join-Path $root "api\other_uploaded_json\boe_header_xml"

# DB connection (defaults for Docker Postgres on laptop)
if (-not $env:DB_HOST) { $env:DB_HOST = "localhost" }
if (-not $env:DB_PORT) { $env:DB_PORT = "5432" }
if (-not $env:DB_NAME) { $env:DB_NAME = "postgres" }
if (-not $env:DB_USER) { $env:DB_USER = "postgres" }
if (-not $env:DB_PASS) { $env:DB_PASS = "postgres" }

# Ensure input dir exists
$inputDir = Join-Path $loaderDir "boe_header_load"
if (-not (Test-Path $inputDir)) {
    New-Item -ItemType Directory -Path $inputDir -Force | Out-Null
    Write-Host "Created empty folder: $inputDir"
    Write-Host "Add XML files there, then run this script again."
    exit 0
}

$xmlCount = (Get-ChildItem -Path $inputDir -Filter "*.xml" -ErrorAction SilentlyContinue).Count
if ($xmlCount -eq 0) {
    Write-Host "No XML files in: $inputDir"
    Write-Host "Add .xml files and run this script again."
    exit 0
}

Write-Host "DB: $env:DB_HOST`:$env:DB_PORT / $env:DB_NAME"
Write-Host "XML input: $inputDir ($xmlCount file(s))"
Write-Host ""

Push-Location $loaderDir
try {
    # Prefer Windows Python Launcher (py), then python
    if (Get-Command py -ErrorAction SilentlyContinue) {
        py boe_header_loader.py
    } elseif (Get-Command python -ErrorAction SilentlyContinue) {
        python boe_header_loader.py
    } else {
        Write-Host "Python not in PATH. Running via Docker (no local Python needed)..."
        docker run --rm -v "${root}:/app" -w /app/api/other_uploaded_json/boe_header_xml `
            -e DB_HOST=host.docker.internal -e DB_PORT=5432 -e DB_NAME=postgres -e DB_USER=postgres -e DB_PASS=postgres `
            python:3.11-slim bash -c "pip install -q psycopg2-binary && python boe_header_loader.py"
        if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
    }
} finally {
    Pop-Location
}
