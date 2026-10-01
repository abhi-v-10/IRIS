@echo off
REM Invoice & Receipt Intelligence System - one-click start for Windows
cd /d "%~dp0"
title Invoice ^& Receipt Intelligence System

where python >nul 2>nul
if errorlevel 1 (
  echo Python was not found. Install Python 3.10 or newer from https://www.python.org/downloads/
  echo and tick "Add python.exe to PATH" during installation. Then run this file again.
  pause
  exit /b 1
)

if not exist venv (
  echo First run: creating a virtual environment and installing packages. This takes a few minutes...
  python -m venv venv || goto :fail
  venv\Scripts\python -m pip install --upgrade pip >nul
  venv\Scripts\python -m pip install -r requirements.txt || goto :fail
)

start "" http://127.0.0.1:5000
venv\Scripts\python run.py %*
pause
exit /b 0

:fail
echo.
echo Setup failed. Check your internet connection and try again, or see README.md.
pause
exit /b 1
