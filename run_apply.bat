@echo off
setlocal enabledelayedexpansion
cd /d "%~dp0"
echo ============================================
echo  SGSC Course Registration - LIVE RUN
echo  (this will actually submit the application)
echo ============================================
echo.

set "COURSE_NAME="
set /p COURSE_NAME=Course name filter (blank = take the first open class in config.yaml's category):

set "OPEN_AT="
set /p OPEN_AT=Open date/time as YYYY-MM-DD HH:MM:SS (blank = use config.yaml's value):

set "ARGS=apply_bot\config.yaml --env-file apply_bot\.env"
if not "!COURSE_NAME!"=="" set "ARGS=!ARGS! --name-contains "!COURSE_NAME!""
if not "!OPEN_AT!"=="" set "ARGS=!ARGS! --open-at "!OPEN_AT!""

echo.
echo Running: python -m apply_bot.sgsc_apply !ARGS!
echo.

python -m apply_bot.sgsc_apply !ARGS!

echo.
echo Script finished. Press any key to close this window.
pause >nul
