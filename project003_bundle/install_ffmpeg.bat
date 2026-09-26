@echo off
title FFmpeg Installation Helper
color 0A
echo.
echo ========================================
echo   FFmpeg Installation Helper
echo ========================================
echo.
echo FFmpeg is required for audio downloads (MP3 conversion)
echo.
echo Choose your installation method:
echo.
echo [1] Install using Chocolatey (Recommended if you have it)
echo [2] Install using Winget (Windows 10/11)
echo [3] Manual Installation Instructions
echo [4] Check if FFmpeg is already installed
echo [5] Exit
echo.
set /p choice="Enter your choice (1-5): "

if "%choice%"=="1" goto choco
if "%choice%"=="2" goto winget
if "%choice%"=="3" goto manual
if "%choice%"=="4" goto check
if "%choice%"=="5" goto exit
goto menu

:choco
echo.
echo Installing FFmpeg using Chocolatey...
echo.
choco install ffmpeg -y
if errorlevel 1 (
    echo.
    echo Error: Chocolatey is not installed or the installation failed.
    echo Please install Chocolatey first from: https://chocolatey.org/install
    pause
    goto menu
) else (
    echo.
    echo FFmpeg installed successfully!
    echo Please restart the IDM Video Downloader application.
    pause
    goto exit
)

:winget
echo.
echo Installing FFmpeg using Winget...
echo.
winget install ffmpeg
if errorlevel 1 (
    echo.
    echo Error: Winget is not available or the installation failed.
    echo Please try another method.
    pause
    goto menu
) else (
    echo.
    echo FFmpeg installed successfully!
    echo Please restart the IDM Video Downloader application.
    pause
    goto exit
)

:manual
echo.
echo ========================================
echo   Manual Installation Instructions
echo ========================================
echo.
echo 1. Open your web browser and go to:
echo    https://ffmpeg.org/download.html
echo.
echo 2. Click on "Windows builds from gyan.dev"
echo    Or go directly to: https://www.gyan.dev/ffmpeg/builds/
echo.
echo 3. Download "ffmpeg-release-essentials.zip"
echo.
echo 4. Extract the ZIP file to a folder (e.g., C:\ffmpeg)
echo.
echo 5. Add FFmpeg to your system PATH:
echo    a. Right-click "This PC" ^> Properties
echo    b. Click "Advanced system settings"
echo    c. Click "Environment Variables"
echo    d. Under "System variables", find and select "Path"
echo    e. Click "Edit" ^> "New"
echo    f. Add the path to FFmpeg bin folder (e.g., C:\ffmpeg\bin)
echo    g. Click OK on all windows
echo.
echo 6. Restart your computer or at least close and reopen the terminal
echo.
echo 7. Run this script again and choose option 4 to verify installation
echo.
pause
goto menu

:check
echo.
echo Checking for FFmpeg installation...
echo.
ffmpeg -version >nul 2>&1
if errorlevel 1 (
    echo [X] FFmpeg is NOT installed or not in PATH
    echo.
    echo Please install FFmpeg using one of the methods above.
) else (
    echo [OK] FFmpeg is installed and working!
    echo.
    ffmpeg -version | findstr /i "ffmpeg version"
    echo.
    echo You can now use audio downloads in the IDM Video Downloader.
)
echo.
pause
goto menu

:exit
exit