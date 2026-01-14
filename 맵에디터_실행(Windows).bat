@echo off
chcp 65001 > nul
setlocal enabledelayedexpansion

echo ==========================================
echo   🎮 TileMatch 맵 에디터 시작중...
echo ==========================================
echo.

cd /d "%~dp0"

REM ===== 의존성 체크 =====
echo [1/4] 필수 프로그램 확인

where node >nul 2>nul
if %ERRORLEVEL% NEQ 0 (
    echo.
    echo [오류] Node.js가 설치되어 있지 않습니다.
    echo.
    echo    설치 방법:
    echo    1. https://nodejs.org 접속
    echo    2. LTS 버전 다운로드 및 설치
    echo.
    pause
    exit /b 1
)
for /f "tokens=*" %%i in ('node --version') do echo    [OK] Node.js %%i

where python >nul 2>nul
if %ERRORLEVEL% NEQ 0 (
    echo.
    echo [오류] Python이 설치되어 있지 않습니다.
    echo.
    echo    설치 방법:
    echo    1. https://python.org 접속
    echo    2. Python 3.11+ 다운로드
    echo    3. 설치시 "Add Python to PATH" 반드시 체크!
    echo.
    pause
    exit /b 1
)
for /f "tokens=*" %%i in ('python --version') do echo    [OK] %%i

REM ===== Frontend 설정 =====
echo.
echo [2/4] 프론트엔드 설정

if not exist "frontend\node_modules" (
    echo    패키지 설치중... ^(최초 1회만^)
    cd frontend
    call npm install --silent
    cd ..
    echo    [OK] 프론트엔드 패키지 설치 완료
) else (
    echo    [OK] 프론트엔드 패키지 확인됨
)

REM ===== Backend 설정 =====
echo.
echo [3/4] 백엔드 설정

if not exist "backend\venv" (
    echo    가상환경 생성중... ^(최초 1회만^)
    cd backend
    python -m venv venv
    cd ..
)

cd backend
call venv\Scripts\activate.bat

pip show fastapi >nul 2>nul
if %ERRORLEVEL% NEQ 0 (
    echo    패키지 설치중... ^(최초 1회만^)
    pip install -r requirements.txt -q
    echo    [OK] 백엔드 패키지 설치 완료
) else (
    echo    [OK] 백엔드 패키지 확인됨
)
cd ..

REM ===== 서버 시작 =====
echo.
echo [4/4] 서버 시작

echo    백엔드 서버 시작중...
start "TileMatch-Backend" /min cmd /c "cd backend && call venv\Scripts\activate.bat && uvicorn app.main:app --host 0.0.0.0 --port 8000"

echo    백엔드 준비 대기중...
timeout /t 5 /nobreak > nul
echo    [OK] 백엔드 준비 완료 (포트 8000)

echo    프론트엔드 서버 시작중...
start "TileMatch-Frontend" /min cmd /c "cd frontend && npm run dev"

timeout /t 3 /nobreak > nul
echo    [OK] 프론트엔드 준비 완료 (포트 5173)

REM ===== 완료 =====
echo.
echo ==========================================
echo   [완료] 맵 에디터 준비 완료!
echo ==========================================
echo.
echo   에디터 주소: http://localhost:5173
echo   API 문서:    http://localhost:8000/docs
echo.
echo   종료 방법: 이 창과 백그라운드 창 모두 닫기
echo.

start http://localhost:5173

echo.
echo 이 창을 닫으면 서버가 종료되지 않습니다.
echo 서버 종료시 작업관리자에서 node.exe, python.exe 종료
echo.
pause
