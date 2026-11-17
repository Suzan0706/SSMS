@echo off
rem Connect SSMS to your PostgreSQL database (default smart_school_db) without losing data.
rem Usage:  setup.bat                       (database smart_school_db)
rem         setup.bat my_db_name
rem         setup.bat smart_school_db --demo   (sample school, empty database only)
setlocal
set DB=%1
if "%DB%"=="" set DB=smart_school_db
cd /d "%~dp0..\api" || exit /b 1

where python >nul 2>nul || (echo Python 3.12+ is needed: https://www.python.org/downloads/ & exit /b 1)
if not exist .venv\Scripts\python.exe (
  echo Creating the Python environment...
  python -m venv .venv || exit /b 1
)
echo Installing the API packages (first time takes a few minutes)...
.venv\Scripts\python.exe -m pip install --quiet --upgrade pip
.venv\Scripts\python.exe -m pip install --quiet -e . || exit /b 1

if exist "C:\Program Files\PostgreSQL\18\bin" set PATH=C:\Program Files\PostgreSQL\18\bin;%PATH%
.venv\Scripts\python.exe scripts\setup_database.py --db %DB% %2 %3 %4 || exit /b 1

where npm >nul 2>nul
if errorlevel 1 (
  echo Node.js 20+ is needed for the web app: https://nodejs.org/ - install it, then run setup.bat again.
  exit /b 1
)
echo Installing the web app packages...
cd /d "%~dp0..\web"
call npm install --no-audit --no-fund || exit /b 1
echo.
echo Setup finished. Now run start.bat
endlocal
