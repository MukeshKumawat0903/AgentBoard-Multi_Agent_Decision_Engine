@echo off
setlocal

echo --- Starting Multi-Agent Decision Engine ---

REM 1. Start Backend (FastAPI)
echo Starting Backend (FastAPI)...
REM Load env vars from backend\.env (ignore blank lines and comments starting with #)
set "ROOT=%~dp0"
set "BACKEND_DIR=%ROOT%backend"
setlocal enabledelayedexpansion
if exist "%BACKEND_DIR%\.env" (
	for /f "usebackq tokens=1* delims==" %%A in ("%BACKEND_DIR%\.env") do (
		set "key=%%A"
		set "value=%%B"
		if defined key (
			if not "!key:~0,1!"=="#" (
				set "!key!=!value!"
			)
		)
	)
)

REM Start backend using the ROOT venv Python (has all pip-installed deps incl. langgraph)
REM backend\venv is a separate, incomplete venv – always use %ROOT%venv\Scripts\python.exe
start "Backend" cmd /c "cd /d "%BACKEND_DIR%" && "%ROOT%venv\Scripts\python.exe" -m uvicorn app.main:app --reload --app-dir "%BACKEND_DIR%" --host 127.0.0.1 --port 8000"

REM 2. Start Frontend (Next.js)
echo Starting Frontend (Next.js)...
start "Frontend" cmd /c "cd frontend && npm run dev"

echo --- Both servers are starting in separate windows ---
echo Backend: http://localhost:8000
echo Frontend: http://localhost:3000

pause
