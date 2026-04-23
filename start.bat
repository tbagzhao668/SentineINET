@echo off
setlocal

set "ROOT=%~dp0"
set "BACKEND=%ROOT%backend"
set "FRONTEND=%ROOT%frontend"

if not exist "%BACKEND%\.venv\Scripts\python.exe" (
  echo [ERROR] 未找到后端虚拟环境: "%BACKEND%\.venv\Scripts\python.exe"
  echo 请先在 backend 目录创建 .venv 并安装依赖。
  pause
  exit /b 1
)

where npm.cmd >nul 2>nul
if errorlevel 1 (
  echo [ERROR] 未找到 npm.cmd，请先安装 Node.js (包含 npm) 并确保加入 PATH。
  pause
  exit /b 1
)

start "Backend (uvicorn)" powershell -NoProfile -ExecutionPolicy Bypass -Command "Set-Location -LiteralPath '%BACKEND%'; .\.venv\Scripts\python.exe -m uvicorn app.main:app --reload --host 127.0.0.1 --port 8000"
start "Frontend (vite)" powershell -NoProfile -ExecutionPolicy Bypass -Command "Set-Location -LiteralPath '%FRONTEND%'; npm.cmd run dev"

echo 已启动：
echo - 后端: http://127.0.0.1:8000
echo - 前端: http://localhost:5175
