@echo off
title Translation Tool

echo ========================================
echo   Translation Web UI Starting...
echo ========================================
echo.

python --version >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Python not found.
    echo Please install from https://www.python.org/downloads/
    echo Make sure to check "Add python.exe to PATH"
    pause
    exit /b 1
)

if "%ANTHROPIC_API_KEY%"=="" (
    echo ANTHROPIC_API_KEY is not set.
    echo.
    set /p ANTHROPIC_API_KEY="Enter your API key (sk-ant-...): "
    echo.
)

echo Installing packages...
pip install anthropic pyyaml flask
if errorlevel 1 (
    echo [ERROR] Package installation failed.
    pause
    exit /b 1
)

echo.
echo ========================================
echo   Open browser: http://localhost:5000
echo   Press Ctrl+C to stop
echo ========================================
echo.

start "" http://localhost:5000

python src/app.py

pause
