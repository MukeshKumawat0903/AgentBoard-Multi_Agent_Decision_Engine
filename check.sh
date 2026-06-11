#!/usr/bin/env bash
# Local quality gate (macOS / Linux / Git Bash).
# Runs the backend lint + type + tests, then the frontend lint + type + tests.
# Usage:  ./check.sh
set -euo pipefail

echo "== Backend: ruff =="
( cd backend && python -m ruff check app )
echo "== Backend: mypy =="
( cd backend && python -m mypy app )
echo "== Backend: pytest =="
( cd backend && python -m pytest -m "not integration" -q )

echo "== Frontend: lint + typecheck + unit tests =="
( cd frontend && npm run verify )

echo "All checks passed."
