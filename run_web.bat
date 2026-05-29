@echo off
chcp 65001 >nul
title 번역 도구 웹 서버

echo ========================================
echo   번역 도구 웹 UI 시작
echo ========================================
echo.

:: Python 확인
python --version >nul 2>&1
if errorlevel 1 (
    echo [오류] Python이 설치되어 있지 않습니다.
    echo https://www.python.org/downloads/ 에서 설치 후 다시 실행하세요.
    echo 설치 시 "Add python.exe to PATH" 를 반드시 체크하세요.
    pause
    exit /b 1
)

:: API 키 확인
if "%ANTHROPIC_API_KEY%"=="" (
    echo ANTHROPIC_API_KEY 가 설정되어 있지 않습니다.
    echo.
    set /p ANTHROPIC_API_KEY="API 키를 입력하세요 (sk-ant-...): "
    echo.
)

:: 패키지 설치
echo [1/2] 패키지 설치 중...
pip install -r requirements.txt -q
if errorlevel 1 (
    echo [오류] 패키지 설치 실패
    pause
    exit /b 1
)

:: 브라우저 자동으로 열기
echo [2/2] 서버 시작 중...
echo.
echo ========================================
echo   브라우저에서 열리면 사용 가능합니다.
echo   http://localhost:5000
echo   (종료: 이 창을 닫거나 Ctrl+C)
echo ========================================
echo.

:: 3초 후 브라우저 열기
start /b cmd /c "timeout /t 3 >nul && start http://localhost:5000"

:: Flask 서버 실행
python src/app.py

pause
