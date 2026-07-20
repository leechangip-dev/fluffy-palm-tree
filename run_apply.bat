@echo off
cd /d "%~dp0"
echo ============================================
echo  SGSC Course Registration - LIVE RUN
echo  (this will actually submit the application)
echo ============================================
python -m apply_bot.sgsc_apply apply_bot\config.yaml --env-file apply_bot\.env
echo.
echo Script finished. Press any key to close this window.
pause >nul
