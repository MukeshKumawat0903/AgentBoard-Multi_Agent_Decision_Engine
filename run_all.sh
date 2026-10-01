#!/bin/bash

# Multi-Agent Decision Engine Run Script
# This script starts both the Python backend and Next.js frontend

# Function to handle cleanup on script exit
cleanup() {
    echo "Stopping servers..."
    kill $(jobs -p)
    exit
}

# Trap SIGINT and SIGTERM to cleanup processes
trap cleanup SIGINT SIGTERM

echo "--- Starting Multi-Agent Decision Engine ---"

# 1. Start Backend (FastAPI)
echo "Starting Backend (FastAPI)..."
ROOT_DIR="$(cd "$(dirname "$0")" && pwd)"
# The project venv lives at the repo root; Windows (Git Bash) uses Scripts/,
# Linux/macOS use bin/.
if [ -x "$ROOT_DIR/venv/Scripts/python" ] || [ -x "$ROOT_DIR/venv/Scripts/python.exe" ]; then
    PYTHON="$ROOT_DIR/venv/Scripts/python"
elif [ -x "$ROOT_DIR/venv/bin/python" ]; then
    PYTHON="$ROOT_DIR/venv/bin/python"
else
    echo "No virtual environment found at $ROOT_DIR/venv - create it and install backend/requirements.txt first."
    exit 1
fi
cd "$ROOT_DIR/backend"
"$PYTHON" -m uvicorn app.main:app --reload --host 0.0.0.0 --port 8000 &
BACKEND_PID=$!
cd "$ROOT_DIR"

# 2. Start Frontend (Next.js)
echo "Starting Frontend (Next.js)..."
cd frontend
npm run dev &
FRONTEND_PID=$!
cd ..

echo "--- Both servers are starting ---"
echo "Backend: http://localhost:8000"
echo "Frontend: http://localhost:3000 (standard) or 3001"
echo "Press Ctrl+C to stop both servers."

# Keep the script running to maintain child processes
wait
