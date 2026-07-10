@echo off
title Fund Prism
cd /d "%~dp0"

echo ============================================
echo   Fund Prism
echo ============================================
echo.

REM ---- Environment ----
set FUND_DB_PATH=%~dp0data\fund_research.sqlite
set FUND_PRISM_API_URL=http://127.0.0.1:8000

if not exist ".venv\Scripts\python.exe" (
    echo [ERROR] .venv not found. Run: python -m venv .venv
    echo         Then run: .venv\Scripts\pip install -e ".[dev]"
    pause
    exit /b 1
)

if not exist "data\fund_research.sqlite" (
    echo [WARNING] data\fund_research.sqlite not found!
    echo [WARNING] Please copy it or run: fund-research init
    echo.
)

if not exist "frontend\node_modules" (
    echo [INFO] Installing frontend dependencies...
    cd frontend
    call npm install
    cd ..
    echo.
)

REM ---- Kill existing processes on ports ----
echo [0/2] Releasing ports 8000 and 3000...
for /f "tokens=5" %%a in ('netstat -ano ^| findstr :8000 ^| findstr LISTENING') do (
    echo       Killing PID %%a on port 8000
    taskkill /F /PID %%a >nul 2>&1
)
for /f "tokens=5" %%a in ('netstat -ano ^| findstr :3000 ^| findstr LISTENING') do (
    echo       Killing PID %%a on port 3000
    taskkill /F /PID %%a >nul 2>&1
)
timeout /t 1 /nobreak >nul

echo [1/2] Starting API server on http://127.0.0.1:8000 ...
start "Fund-Prism-API" cmd /k .venv\Scripts\python.exe -m uvicorn fund_research.api.app:create_app --host 127.0.0.1 --port 8000 --factory

echo Waiting for API to start...
timeout /t 5 /nobreak >nul

echo [2/2] Starting frontend on http://localhost:3000 ...
start "Fund-Prism-UI" /D "%~dp0frontend" cmd /k npx vite --host

echo Waiting for frontend to be ready...
timeout /t 6 /nobreak >nul

echo.
echo ============================================
echo   API:      http://127.0.0.1:8000/docs
echo   Frontend: http://localhost:3000
echo ============================================
echo.
echo Tip: Data updates silently in background after startup.
echo      Watch the "updating" indicator in the top bar.
echo If the API window shows an error, copy the error text.
echo.

start http://localhost:3000

pause
