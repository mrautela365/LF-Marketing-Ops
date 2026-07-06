Set-Location $PSScriptRoot

if (-not (Test-Path ".venv")) {
    Write-Host "Creating virtual environment..." -ForegroundColor Cyan
    python -m venv .venv
}

Write-Host "Installing dependencies..." -ForegroundColor Cyan
& ".venv\Scripts\pip" install -q -r requirements.txt

Write-Host ""
Write-Host "  Starting at http://localhost:8081" -ForegroundColor Green
Write-Host ""

& ".venv\Scripts\python" run.py
