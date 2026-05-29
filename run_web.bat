@echo off
title Translation Tool
chcp 65001 >nul 2>&1

echo ========================================
echo   Translation Web UI Starting...
echo ========================================
echo.

:: ── Python check ──
python --version >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Python not found.
    echo Please install from https://www.python.org/downloads/
    echo Make sure to check "Add python.exe to PATH"
    pause
    exit /b 1
)

:: ── Load API key from .env if present ──
if exist ".env" (
    for /f "usebackq tokens=1,* delims==" %%A in (".env") do (
        if /i "%%A"=="ANTHROPIC_API_KEY" set "ANTHROPIC_API_KEY=%%B"
    )
)

:: ── Prompt only if still not set ──
if "%ANTHROPIC_API_KEY%"=="" (
    echo ANTHROPIC_API_KEY is not set.
    echo.
    set /p ANTHROPIC_API_KEY="Enter your API key (sk-ant-...): "
    echo.

    :: Save to .env for next time
    echo ANTHROPIC_API_KEY=%ANTHROPIC_API_KEY%> .env
    echo [OK] API key saved to .env  ^(next time this step will be skipped^)
    echo.
)

:: ── Install packages (skip if already installed) ──
python -c "import anthropic,flask,docx,fitz,openpyxl" >nul 2>&1
if errorlevel 1 (
    echo Installing packages...
    pip install anthropic pyyaml flask python-docx pymupdf openpyxl -q
    if errorlevel 1 (
        echo [ERROR] Package installation failed.
        pause
        exit /b 1
    )
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
