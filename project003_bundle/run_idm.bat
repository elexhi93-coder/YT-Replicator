@echo off
title IDM Video Downloader
echo Starting IDM Video Downloader...
echo.

rem Check if Python is installed
python --version >nul 2>&1
if errorlevel 1 (
    echo Python is not installed or not in PATH.
    echo Please install Python 3.7 or higher from https://python.org
    pause
    exit /b 1
)

rem Install requirements if needed
if not exist "installed_flag.txt" (
    echo Installing required packages...
    pip install -r requirements.txt
    if errorlevel 0 (
        echo Installation successful > installed_flag.txt
    ) else (
        echo Failed to install requirements
        pause
        exit /b 1
    )
)

rem Run the application
echo Starting Video Downloader...
python video_downloader.py

pause