@echo off
cd /d "%~dp0"
title Voice Transcription

call venv\Scripts\activate.bat
if errorlevel 1 (
    echo [ERROR] Failed to activate venv. Please check the venv folder.
    pause
    exit /b 1
)

python run_all.py

echo.
echo Exited.
pause