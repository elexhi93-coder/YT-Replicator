@echo off
setlocal enabledelayedexpansion

echo ==============================================
echo project003 one-click Docker startup
echo ==============================================

cd /d "%~dp0"

if not exist "docker-compose.yml" (
  echo ERROR: This script must be run from the project root folder where docker-compose.yml lives.
  pause
  exit /b 1
)

if not exist ".env" (
  if exist ".env.example" (
    copy /Y ".env.example" ".env" >nul
    echo Created .env from .env.example
  ) else (
    echo WARNING: .env.example not found. Please create .env manually.
  )
)

mkdir "db" 2>nul
mkdir "downloads" 2>nul
mkdir "cookies" 2>nul

if not exist "cookies\cookies.txt" (
  echo WARNING: cookies\cookies.txt not found. If you need YouTube cookies, copy them into cookies\cookies.txt.
)

where docker >nul 2>&1
if errorlevel 1 (
  echo ERROR: Docker is not installed or not on PATH.
  echo Install Docker Desktop or Docker Engine, then try again.
  pause
  exit /b 1
)

echo Starting Docker Compose stack...
docker compose up -d --build
if errorlevel 1 (
  echo ERROR: docker compose failed.
  pause
  exit /b 1
)

echo.
echo ✅ project003 stack started successfully.
echo Open http://localhost:5678 for n8n and http://localhost:8080 for the dashboard.
start "" http://localhost:5678
start "" http://localhost:8080

pause
