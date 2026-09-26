@echo off
title Video Uploader
cd /d "%~dp0"

:: Check for Python
python --version >nul 2>&1
if errorlevel 1 (
    echo Python is not installed or not in PATH.
    echo Please install Python 3.8+ from https://www.python.org/
    pause
    exit /b 1
)

:: Run the Video Uploader
echo Starting Video Uploader...
python video_uploader.py

if errorlevel 1 (
    echo.
    echo An error occurred. Press any key to exit.
    pause >nul
)
