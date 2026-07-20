@echo off
cd /d "%~dp0"
echo ============================================
echo  SGSC Course Registration - DRY RUN
echo  (rehearsal only, will NOT submit)
echo ============================================
python -m apply_bot.sgsc_apply apply_bot\config.yaml --dry-run --env-file apply_bot\.env
echo.
echo Script finished. Press any key to close this window.
pause >nul
