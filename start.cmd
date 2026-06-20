@echo off
setlocal enabledelayedexpansion
cd /d "%~dp0"

REM --- Check Python ---
where python >nul 2>nul
if errorlevel 1 (
    echo [X] Python 3.11+ is required. Install it from https://python.org first.
    exit /b 1
)

REM --- Auto-setup on first run ---
if not exist ".venv" (
    echo [*] First run - setting up virtual environment...
    python -m venv .venv
    call .venv\Scripts\activate.bat
    python -m pip install -q --upgrade pip
    pip install -q -r requirements.txt
    echo [OK] Dependencies installed.
) else (
    call .venv\Scripts\activate.bat
)

REM --- Create config from example if missing ---
if not exist "config.yaml" (
    copy /y config.example.yaml config.yaml >nul
    echo.
    echo [*] Created config.yaml - edit it to set your location
    echo     ^(and optionally your Discord webhook^). Then run this script again.
    echo.
    start "" notepad config.yaml
    exit /b 0
)

REM --- Friendly check: location must be set ---
findstr /r /c:"^[ ]*latitude:[ ]*0" config.yaml >nul && findstr /r /c:"^[ ]*longitude:[ ]*0" config.yaml >nul
if not errorlevel 1 (
    echo [!] Please set your latitude and longitude in config.yaml before starting.
    exit /b 1
)

if not exist "data" mkdir data
if not exist "logs" mkdir logs

echo [^>] Starting Sky Watch on http://localhost:8080
python -m backend.main
