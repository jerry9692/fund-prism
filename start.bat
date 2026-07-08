@echo off
title Fund Prism
cd /d "%~dp0"

echo ============================================
echo   Fund Prism
echo ============================================
echo.

REM ---- 数据库路径（SQLite，与 macOS 开发环境一致）----
set "FUND_DB_PATH=%~dp0data\fund_research.sqlite"
set "FUND_PRISM_API_URL=http://127.0.0.1:8000"

if not exist ".venv\Scripts\python.exe" (
    echo [ERROR] .venv not found. Run: python -m venv .venv
    pause
    exit /b 1
)

if not exist "data\fund_research.sqlite" (
    echo [WARNING] data\fund_research.sqlite not found!
    echo [WARNING] Please copy it from your other machine or run: fund-research init-db
    echo.
)

if not exist "frontend\node_modules" (
    echo [INFO] Installing frontend dependencies...
    cd frontend
    call npm install
    cd ..
    echo.
)

echo [1/2] Starting API server on http://127.0.0.1:8000 ...
start "Fund-Prism-API" cmd /c "set FUND_DB_PATH=%FUND_DB_PATH% && .venv\Scripts\python.exe -m uvicorn fund_research.api.app:create_app --host 127.0.0.1 --port 8000 --factory"

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
