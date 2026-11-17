@echo off
rem Start SSMS: the API (http://127.0.0.1:8000/docs) and the web app (http://localhost:5173).
cd /d "%~dp0..\api" || exit /b 1
if not exist .env (echo Run setup.bat first. & exit /b 1)
start "SSMS API" cmd /k .venv\Scripts\python.exe scripts\run_api.py
cd /d "%~dp0..\web"
start "SSMS Web" cmd /k npm run dev
timeout /t 6 >nul
start http://localhost:5173
