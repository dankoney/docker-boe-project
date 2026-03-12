@echo off
REM Run boe_header_loader.py - use this if PowerShell scripts are disabled.
REM Usage: scripts\run-boe-header-loader.cmd

cd /d "%~dp0.."
set "ROOT=%CD%"
set "LOADER_DIR=%ROOT%\api\other_uploaded_json\boe_header_xml"
set "INPUT_DIR=%LOADER_DIR%\boe_header_load"

if not defined DB_HOST set DB_HOST=localhost
if not defined DB_PORT set DB_PORT=5432
if not defined DB_NAME set DB_NAME=postgres
if not defined DB_USER set DB_USER=postgres
if not defined DB_PASS set DB_PASS=postgres

if not exist "%INPUT_DIR%" (
    mkdir "%INPUT_DIR%" 2>nul
    echo Created: %INPUT_DIR%
    echo Add XML files there, then run this script again.
    exit /b 0
)

dir /b "%INPUT_DIR%\*.xml" 2>nul | find "." >nul
if errorlevel 1 (
    echo No XML files in: %INPUT_DIR%
    echo Add .xml files and run this script again.
    exit /b 1
)

echo DB: %DB_HOST%:%DB_PORT% / %DB_NAME%
echo XML input: %INPUT_DIR%
echo.

cd /d "%LOADER_DIR%"

where py >nul 2>nul
if %errorlevel% equ 0 (
    py boe_header_loader.py
) else (
    where python >nul 2>nul
    if %errorlevel% equ 0 (
        python boe_header_loader.py
    ) else (
        echo Python not in PATH. Running via Docker...
        docker run --rm -v "%ROOT%:/app" -w /app/api/other_uploaded_json/boe_header_xml -e DB_HOST=host.docker.internal -e DB_PORT=5432 -e DB_NAME=postgres -e DB_USER=postgres -e DB_PASS=postgres python:3.11-slim bash -c "pip install -q psycopg2-binary && python boe_header_loader.py"
    )
)
