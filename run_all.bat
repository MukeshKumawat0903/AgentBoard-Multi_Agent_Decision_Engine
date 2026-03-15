@echo off
setlocal

echo --- Starting Multi-Agent Decision Engine ---

REM 1. Start Backend (FastAPI)
echo Starting Backend (FastAPI)...
start "Backend" cmd /c "cd backend && venv\Scripts\python.exe -m uvicorn app.main:app --reload --port 8000"

REM 2. Start Frontend (Next.js)
echo Starting Frontend (Next.js)...
start "Frontend" cmd /c "cd frontend && npm run dev"

echo --- Both servers are starting in separate windows ---
echo Backend: http://localhost:8000
echo Frontend: http://localhost:3000

pause
