@echo off
setlocal
cd /d "%~dp0"
title IRON-AI
echo.
echo   IRON-AI is starting. Keep this window open while you use the site.
echo.

set "PY="
where py >nul 2>nul && set "PY=py -3"
if not defined PY where python >nul 2>nul && set "PY=python"
if not defined PY goto :nopython

if exist ".venv\Scripts\python.exe" goto :haveenv
echo   Creating the environment, first run only...
%PY% -m venv .venv
if errorlevel 1 goto :fail
:haveenv

echo   Installing packages, the first run takes 1 to 2 minutes...
".venv\Scripts\python.exe" -m pip install -q -r requirements.txt
if errorlevel 1 goto :fail
if not exist ".env" copy /y ".env.example" ".env" >nul

set "OPEN_BROWSER=1"

echo.
echo   Site:  http://localhost:8000
echo   The admin email and password are printed below the first time you run this.
echo   Press Ctrl+C to stop the server.
echo.
".venv\Scripts\python.exe" -m uvicorn app.main:app --port 8000
echo.
echo   The server stopped. Scroll up to see why, or send me the last lines.
pause
exit /b 0

:nopython
echo   Python was not found.
echo   1. Install Python 3.11 or newer from https://www.python.org/downloads/
echo   2. On the first installer screen, tick "Add python.exe to PATH"
echo   3. Double-click run.bat again
pause
exit /b 1

:fail
echo.
echo   Something failed above. Copy the last lines and send them to me.
pause
exit /b 1
