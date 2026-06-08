@echo off
title Fund Prism
cd /d "%~dp0"

echo ============================================
echo   Fund Prism
echo ============================================
echo.

if not exist ".venv\Scripts\python.exe" (
    echo [ERROR] .venv not found. Run: python -m venv .venv
    pause
    exit /b 1
)

if not exist "frontend\node_modules" (
    echo [INFO] Installing frontend dependencies...
    cd frontend
    call npm install
    cd ..
    echo.
)

echo [1/2] Starting API server on http://127.0.0.1:8000 ...
start "Fund-Prism-API" cmd /c ".venv\Scripts\python.exe -m uvicorn fund_research.api.app:create_app --host 127.0.0.1 --port 8000 --factory"

timeout /t 3 /nobreak >nul

echo [2/2] Starting frontend on http://localhost:3000 ...
start "Fund-Prism-UI" cmd /c "cd frontend && npx vite --host"

timeout /t 4 /nobreak >nul

echo [OK] Opening browser...
start http://localhost:3000

echo.
echo ============================================
echo   API:      http://127.0.0.1:8000/docs
echo   Frontend: http://localhost:3000
echo ============================================

pause
