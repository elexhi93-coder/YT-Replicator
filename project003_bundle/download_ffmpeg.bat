@echo off
title Auto-Download FFmpeg for IDM
color 0A
cls

echo.
echo ================================================================
echo   Automatic FFmpeg Download for IDM Video Downloader
echo ================================================================
echo.

set "FFMPEG_DIR=%~dp0ffmpeg"
set "FFMPEG_EXE=%FFMPEG_DIR%\bin\ffmpeg.exe"

REM Check if ffmpeg already exists
if exist "%FFMPEG_EXE%" (
    echo [OK] FFmpeg is already installed in the app folder!
    echo Location: %FFMPEG_EXE%
    echo.
    pause
    exit /b 0
)

echo This will download a portable FFmpeg (~100MB) to the app folder.
echo No system installation required!
echo.
echo Download location: %FFMPEG_DIR%
echo.
set /p continue="Continue? (Y/N): "
if /i not "%continue%"=="Y" exit /b 0

echo.
echo [1/3] Creating ffmpeg directory...
if not exist "%FFMPEG_DIR%" mkdir "%FFMPEG_DIR%"
if not exist "%FFMPEG_DIR%\bin" mkdir "%FFMPEG_DIR%\bin"

echo.
echo [2/3] Downloading portable FFmpeg...
echo This may take a few minutes depending on your internet speed...
echo.

REM Download using PowerShell (built-in on Windows)
powershell -Command "& {[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12; $url = 'https://www.gyan.dev/ffmpeg/builds/ffmpeg-release-essentials.zip'; $output = '%TEMP%\ffmpeg.zip'; Write-Host 'Downloading FFmpeg...'; (New-Object System.Net.WebClient).DownloadFile($url, $output); Write-Host 'Download complete!'; Write-Host 'Extracting...'; Expand-Archive -Path $output -DestinationPath '%TEMP%\ffmpeg_extract' -Force; $extracted = Get-ChildItem '%TEMP%\ffmpeg_extract' -Directory | Select-Object -First 1; Copy-Item -Path ($extracted.FullName + '\bin\*') -Destination '%FFMPEG_DIR%\bin\' -Force; Remove-Item '%TEMP%\ffmpeg.zip' -Force; Remove-Item '%TEMP%\ffmpeg_extract' -Recurse -Force; Write-Host 'FFmpeg installed successfully!'}"

if errorlevel 1 (
    echo.
    echo ERROR: Download failed!
    echo.
    echo Alternative method:
    echo 1. Go to: https://www.gyan.dev/ffmpeg/builds/
    echo 2. Download: ffmpeg-release-essentials.zip
    echo 3. Extract ffmpeg.exe to: %FFMPEG_DIR%\bin\
    echo.
    pause
    exit /b 1
)

echo.
echo [3/3] Verifying installation...
if exist "%FFMPEG_EXE%" (
    echo.
    echo ================================================================
    echo   SUCCESS!
    echo ================================================================
    echo.
    echo FFmpeg has been installed to:
    echo %FFMPEG_DIR%
    echo.
    echo The IDM Video Downloader will now use this FFmpeg for:
    echo - Converting audio to MP3
    echo - Merging high-quality video streams
    echo - Format conversions
    echo.
    echo You can now:
    echo 1. Close this window
    echo 2. Restart the IDM Video Downloader
    echo 3. Download audio as MP3!
    echo.
    echo Note: This FFmpeg is portable and only for this app.
    echo      It won't affect your system.
    echo.
) else (
    echo.
    echo ERROR: Installation failed!
    echo Please try the manual installation method.
    echo.
)

pause
