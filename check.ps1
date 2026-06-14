# Local quality gate (Windows / PowerShell).
# Runs the backend lint + type + tests, then the frontend lint + type + tests.
# Usage:  ./check.ps1
$ErrorActionPreference = "Stop"

Write-Host "== Backend: ruff ==" -ForegroundColor Cyan
Push-Location backend
try {
    python -m ruff check app
    Write-Host "== Backend: mypy ==" -ForegroundColor Cyan
    python -m mypy app
    Write-Host "== Backend: pytest ==" -ForegroundColor Cyan
    python -m pytest -m "not integration" -q
}
finally { Pop-Location }

Write-Host "== Frontend: lint + typecheck + unit tests ==" -ForegroundColor Cyan
Push-Location frontend
try { npm run verify }
finally { Pop-Location }

Write-Host "All checks passed." -ForegroundColor Green
