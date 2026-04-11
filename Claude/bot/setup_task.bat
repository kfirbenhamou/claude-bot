@echo off
setlocal EnableDelayedExpansion
echo ================================================
echo   Good Morning Agent - Task Scheduler Setup
echo ================================================
echo.

REM ── Configuration ────────────────────────────────
set TASK_NAME=GoodMorningAgent
set SCRIPT_PATH=C:\ai\Claude\bot\good_morning_agent.py
set XML_PATH=C:\ai\Claude\bot\task_definition.xml
set LOG_DIR=C:\ai\Claude\bot\logs
REM ─────────────────────────────────────────────────


REM ── Step 1: Check admin rights ───────────────────
echo [1/6] Checking administrator rights...
net session >nul 2>&1
if %ERRORLEVEL% NEQ 0 (
    echo ❌ ERROR: This script must be run as Administrator.
    echo    Right-click the .bat file and choose "Run as administrator"
    echo.
    pause
    exit /b 1
)
echo     ✅ Running as administrator.
echo.


REM ── Step 2: Check Python is installed ────────────
echo [2/6] Checking Python installation...
python --version >nul 2>&1
if %ERRORLEVEL% NEQ 0 (
    echo ❌ ERROR: Python is not installed or not in PATH.
    echo    Download it from https://www.python.org/downloads/
    echo    Make sure to check "Add Python to PATH" during install.
    echo.
    pause
    exit /b 1
)
for /f "tokens=*" %%v in ('python --version 2^>^&1') do set PY_VERSION=%%v
echo     ✅ %PY_VERSION% found.
echo.


REM ── Step 3: Check script file exists ─────────────
echo [3/6] Checking script file exists...
if not exist "%SCRIPT_PATH%" (
    echo ❌ ERROR: Script not found at:
    echo    %SCRIPT_PATH%
    echo    Make sure good_morning_agent.py is in C:\ai\Claude\bot\
    echo.
    pause
    exit /b 1
)
echo     ✅ Script found.
echo.


REM ── Step 4: Check XML task definition exists ─────
echo [4/6] Checking task definition XML...
if not exist "%XML_PATH%" (
    echo ❌ ERROR: task_definition.xml not found at:
    echo    %XML_PATH%
    echo    Make sure task_definition.xml is in C:\ai\Claude\bot\
    echo.
    pause
    exit /b 1
)
echo     ✅ task_definition.xml found.
echo.


REM ── Step 5: Create logs folder ───────────────────
echo [5/6] Creating logs folder...
if not exist "%LOG_DIR%" (
    mkdir "%LOG_DIR%"
    echo     ✅ Logs folder created.
) else (
    echo     ✅ Logs folder already exists.
)
echo.


REM ── Step 6: Register scheduled task ──────────────
echo [6/6] Registering scheduled task...

REM Delete existing task cleanly if it exists
schtasks /delete /tn "%TASK_NAME%" /f >nul 2>&1

REM Register from hardcoded XML
schtasks /create /tn "%TASK_NAME%" /xml "%XML_PATH%" /f >nul 2>&1
set CREATE_ERR=%ERRORLEVEL%

if %CREATE_ERR% NEQ 0 (
    echo ❌ ERROR: Failed to register the task ^(error code: %CREATE_ERR%^).
    echo    Make sure task_definition.xml is valid and you are running as Administrator.
    echo.
    pause
    exit /b 1
)

REM Verify task actually appears in Task Scheduler
schtasks /query /tn "%TASK_NAME%" >nul 2>&1
if %ERRORLEVEL% NEQ 0 (
    echo ❌ ERROR: Task was registered but cannot be found — something went wrong.
    echo    Open Task Scheduler manually and check for errors.
    echo.
    pause
    exit /b 1
)
echo     ✅ Task "%TASK_NAME%" registered and verified.
echo.

REM Enable Task Scheduler history (off by default on Windows)
wevtutil set-log "Microsoft-Windows-TaskScheduler/Operational" /enabled:true >nul 2>&1
echo     ✅ Task Scheduler history enabled.
echo.


REM ── Summary ──────────────────────────────────────
echo ================================================
echo   ✅ Setup completed successfully!
echo ================================================
echo.
echo   Task name  : %TASK_NAME%
echo   Runs daily : 08:00 (catches up if PC was off)
echo   Runs as    : Administrator
echo   Log files  : %LOG_DIR%\agent.log
echo                %LOG_DIR%\scheduler.log
echo.

REM ── Optional test run ────────────────────────────
set /p RUN_NOW=   Run the task now to test it? (y/n): 
if /i "!RUN_NOW!"=="y" (
    echo.
    echo   Triggering task...
    schtasks /run /tn "%TASK_NAME%"
    if %ERRORLEVEL% EQU 0 (
        echo   ✅ Task triggered. Wait a few seconds then check logs:
        echo   type "%LOG_DIR%\agent.log"
    ) else (
        echo   ❌ Failed to trigger task. Check Task Scheduler for details.
    )
)
echo.
echo ── Useful commands ──────────────────────────────
echo   Run now  : schtasks /run /tn "%TASK_NAME%"
echo   Status   : schtasks /query /tn "%TASK_NAME%" /fo LIST
echo   Logs     : type "%LOG_DIR%\agent.log"
echo   Delete   : schtasks /delete /tn "%TASK_NAME%" /f
echo.
pause