@echo off
chcp 65001 >nul
title Fund Prism

echo ============================================
echo   Fund Prism — AI-oriented 基金研究平台
echo ============================================
echo.

:: 检查 Python 虚拟环境
if not exist ".venv\Scripts\python.exe" (
    echo [错误] 未找到 .venv 虚拟环境
    echo 请先运行: python -m venv .venv
    pause
    exit /b 1
)

:: 检查前端依赖
if not exist "frontend\node_modules" (
    echo [提示] 前端依赖未安装，正在安装...
    cd frontend
    call npm install
    cd ..
    echo.
)

:: 启动后端
echo [1/2] 启动后端 API 服务 (http://127.0.0.1:8000) ...
start "Fund Prism API" cmd /c ".venv\Scripts\python.exe -m uvicorn fund_research.api.app:create_app --host 127.0.0.1 --port 8000 --factory"

:: 等后端就绪
echo [等待] 后端启动中...
timeout /t 3 /nobreak >nul

:: 启动前端
echo [2/2] 启动前端界面 (http://localhost:3000) ...
start "Fund Prism Frontend" cmd /c "cd frontend && npx vite --host"

:: 等前端就绪
echo [等待] 前端启动中...
timeout /t 4 /nobreak >nul

:: 打开浏览器
echo [OK] 正在打开浏览器...
start http://localhost:3000

echo.
echo ============================================
echo   平台已启动！
echo   后端 API:  http://127.0.0.1:8000/docs
echo   前端界面:  http://localhost:3000
echo ============================================
echo.
echo 关闭此窗口不会停止服务。
echo 要停止服务请关闭两个弹出的命令行窗口。
echo.

pause
