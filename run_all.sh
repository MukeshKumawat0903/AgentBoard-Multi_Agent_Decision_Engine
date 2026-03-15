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
cd backend
# Use the virtual environment python to run the application
# Assuming main.py is the entry point
# Change to the absolute path or relative path from project root
./venv/Scripts/python -m uvicorn app.main:app --reload --port 8000 &
BACKEND_PID=$!
cd ..

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
