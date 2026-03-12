# Load boe_records from boe_data (pg_dump COPY block) into Docker Postgres.
# Run from repo root. Requires: Docker, boe-project stack running (docker compose up -d).
$ErrorActionPreference = "Stop"
$root = Split-Path $PSScriptRoot -Parent
$boeData = Join-Path $root "boe_data"
$outFile = Join-Path $root "boe_records_load.sql"
$container = "boe-project-db-1"

if (-not (Test-Path $boeData)) { Write-Error "Not found: $boeData"; exit 1 }
$lines = [System.IO.File]::ReadAllLines($boeData, [System.Text.Encoding]::UTF8)
# COPY public.boe_records is line 30; data until line 671 (\.)
[System.IO.File]::WriteAllLines($outFile, $lines[29..670], [System.Text.UTF8Encoding]::new($false))
docker cp $outFile "${container}:/tmp/boe_records_load.sql"
docker exec $container psql -U postgres -d postgres -f /tmp/boe_records_load.sql
docker exec $container psql -U postgres -d postgres -c "SELECT setval('public.boe_records_id_seq', (SELECT COALESCE(MAX(id), 1) FROM public.boe_records));"
docker exec $container rm /tmp/boe_records_load.sql
Remove-Item $outFile -Force -ErrorAction SilentlyContinue
Write-Host "Done. boe_records loaded from boe_data."
