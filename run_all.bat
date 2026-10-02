@echo off
setlocal

echo --- Starting Multi-Agent Decision Engine ---

REM 1. Start Backend (FastAPI)
echo Starting Backend (FastAPI)...
REM The backend reads backend\.env itself (it starts in that folder), so the
REM values are not exported here: cmd would keep quotes and break JSON values.
set "ROOT=%~dp0"
set "BACKEND_DIR=%ROOT%backend"

REM Start backend using the ROOT venv Python (has all pip-installed deps incl. langgraph)
REM backend\venv is a separate, incomplete venv – always use %ROOT%venv\Scripts\python.exe
start "Backend" cmd /k "cd /d "%BACKEND_DIR%" && "%ROOT%venv\Scripts\python.exe" -m uvicorn app.main:app --reload --app-dir "%BACKEND_DIR%" --host 0.0.0.0 --port 8000"

REM 2. Start Frontend (Next.js)
echo Starting Frontend (Next.js)...
start "Frontend" cmd /k "cd /d "%ROOT%frontend" && npm run dev"

echo --- Both servers are starting in separate windows ---
echo Backend: http://localhost:8000
echo Frontend: http://localhost:3000

pause
