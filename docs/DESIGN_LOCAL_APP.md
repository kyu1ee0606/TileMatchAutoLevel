# TileMatch Level Designer - 로컬 실행 설계

## 목표
폴더를 받아서 **한 번의 클릭/명령**으로 맵 에디터를 실행할 수 있도록 설계

---

## 설계 옵션 비교

| 옵션 | 장점 | 단점 | 복잡도 | 추천 |
|------|------|------|--------|------|
| **A. 통합 런처 스크립트** | 간단, 추가 설치 없음 | 의존성 설치 필요 | ⭐⭐ | ✅ |
| **B. Electron 앱** | 단일 exe, 브라우저 내장 | 빌드 복잡, 용량 큼 | ⭐⭐⭐⭐ | |
| **C. Docker Compose** | 환경 격리, 일관성 | Docker 필수 설치 | ⭐⭐⭐ | |
| **D. Tauri 앱** | 작은 용량, 네이티브 | Rust 빌드 필요 | ⭐⭐⭐⭐⭐ | |

---

## 추천안: A. 통합 런처 스크립트

### 실행 플로우

```
사용자가 폴더 받음
    ↓
macOS: 더블클릭 Start.command
Windows: 더블클릭 Start.bat
    ↓
자동으로 의존성 설치 확인
    ↓
백엔드 + 프론트엔드 동시 실행
    ↓
자동으로 브라우저 열림 → http://localhost:5173
```

### 폴더 구조

```
TileMatchAutoLevel/
├── Start.command          # macOS 더블클릭 실행
├── Start.bat              # Windows 더블클릭 실행
├── launcher/
│   ├── setup.sh           # macOS/Linux 환경 설정
│   ├── setup.bat          # Windows 환경 설정
│   └── config.json        # 런처 설정
├── backend/
│   └── ...
├── frontend/
│   └── ...
└── docs/
    └── QUICK_START.md     # 빠른 시작 가이드
```

---

## 상세 설계

### 1. Start.command (macOS)

```bash
#!/bin/bash
# TileMatch Level Designer 시작 스크립트

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

echo "=========================================="
echo "  TileMatch Level Designer 시작중..."
echo "=========================================="

# 색상 정의
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# 종료 시 cleanup
cleanup() {
    echo ""
    echo "종료중..."
    kill $BACKEND_PID 2>/dev/null
    kill $FRONTEND_PID 2>/dev/null
    exit 0
}
trap cleanup SIGINT SIGTERM

# ===== 의존성 체크 =====

# Node.js 체크
if ! command -v node &> /dev/null; then
    echo -e "${RED}❌ Node.js가 설치되어 있지 않습니다.${NC}"
    echo "   https://nodejs.org 에서 설치 후 다시 실행하세요."
    read -p "Press Enter to exit..."
    exit 1
fi
echo -e "${GREEN}✓${NC} Node.js $(node --version)"

# Python 체크
if ! command -v python3 &> /dev/null; then
    echo -e "${RED}❌ Python 3가 설치되어 있지 않습니다.${NC}"
    echo "   https://python.org 에서 설치 후 다시 실행하세요."
    read -p "Press Enter to exit..."
    exit 1
fi
echo -e "${GREEN}✓${NC} Python $(python3 --version)"

# ===== 환경 설정 =====

# Frontend 의존성 설치 (node_modules 없으면)
if [ ! -d "frontend/node_modules" ]; then
    echo -e "${YELLOW}📦 프론트엔드 패키지 설치중...${NC}"
    cd frontend && npm install && cd ..
fi

# Backend 가상환경 설정 (venv 없으면)
if [ ! -d "backend/venv" ]; then
    echo -e "${YELLOW}🐍 백엔드 가상환경 생성중...${NC}"
    cd backend && python3 -m venv venv && cd ..
fi

# Backend 패키지 설치
echo -e "${YELLOW}📦 백엔드 패키지 확인중...${NC}"
cd backend
source venv/bin/activate
pip install -r requirements.txt -q
cd ..

# ===== 서버 시작 =====

# 백엔드 시작
echo ""
echo -e "${GREEN}🚀 백엔드 서버 시작 (포트 8000)${NC}"
cd backend
source venv/bin/activate
uvicorn app.main:app --host 0.0.0.0 --port 8000 &
BACKEND_PID=$!
cd ..

# 백엔드 준비 대기
echo "   백엔드 준비중..."
for i in {1..30}; do
    if curl -s http://localhost:8000/health > /dev/null 2>&1; then
        echo -e "   ${GREEN}✓${NC} 백엔드 준비 완료"
        break
    fi
    sleep 1
done

# 프론트엔드 시작
echo ""
echo -e "${GREEN}🌐 프론트엔드 서버 시작 (포트 5173)${NC}"
cd frontend
npm run dev &
FRONTEND_PID=$!
cd ..

# 프론트엔드 준비 대기
echo "   프론트엔드 준비중..."
sleep 3

# ===== 브라우저 열기 =====
echo ""
echo -e "${GREEN}=========================================="
echo "  ✅ 준비 완료!"
echo "==========================================${NC}"
echo ""
echo "  📍 주소: http://localhost:5173"
echo "  📖 API 문서: http://localhost:8000/docs"
echo ""
echo "  종료하려면 이 창을 닫거나 Ctrl+C를 누르세요."
echo ""

# 브라우저 열기
open http://localhost:5173

# 프로세스 대기
wait $BACKEND_PID $FRONTEND_PID
```

### 2. Start.bat (Windows)

```batch
@echo off
chcp 65001 > nul
setlocal enabledelayedexpansion

echo ==========================================
echo   TileMatch Level Designer 시작중...
echo ==========================================

cd /d "%~dp0"

REM ===== 의존성 체크 =====

where node >nul 2>nul
if %ERRORLEVEL% NEQ 0 (
    echo [오류] Node.js가 설치되어 있지 않습니다.
    echo        https://nodejs.org 에서 설치 후 다시 실행하세요.
    pause
    exit /b 1
)
for /f "tokens=*" %%i in ('node --version') do echo [OK] Node.js %%i

where python >nul 2>nul
if %ERRORLEVEL% NEQ 0 (
    echo [오류] Python이 설치되어 있지 않습니다.
    echo        https://python.org 에서 설치 후 다시 실행하세요.
    pause
    exit /b 1
)
for /f "tokens=*" %%i in ('python --version') do echo [OK] %%i

REM ===== 환경 설정 =====

if not exist "frontend\node_modules" (
    echo [설치] 프론트엔드 패키지 설치중...
    cd frontend
    call npm install
    cd ..
)

if not exist "backend\venv" (
    echo [설치] 백엔드 가상환경 생성중...
    cd backend
    python -m venv venv
    cd ..
)

echo [설치] 백엔드 패키지 확인중...
cd backend
call venv\Scripts\activate.bat
pip install -r requirements.txt -q
cd ..

REM ===== 서버 시작 =====

echo.
echo [시작] 백엔드 서버 (포트 8000)
start "Backend" /min cmd /c "cd backend && venv\Scripts\activate.bat && uvicorn app.main:app --host 0.0.0.0 --port 8000"

timeout /t 5 /nobreak > nul

echo [시작] 프론트엔드 서버 (포트 5173)
start "Frontend" /min cmd /c "cd frontend && npm run dev"

timeout /t 3 /nobreak > nul

REM ===== 브라우저 열기 =====

echo.
echo ==========================================
echo   준비 완료!
echo ==========================================
echo.
echo   주소: http://localhost:5173
echo   API 문서: http://localhost:8000/docs
echo.
echo   종료하려면 이 창과 백그라운드 창을 닫으세요.
echo.

start http://localhost:5173

pause
```

### 3. QUICK_START.md (빠른 시작 가이드)

```markdown
# TileMatch Level Designer - 빠른 시작

## 필수 설치 프로그램

시작 전 아래 프로그램을 설치하세요:

1. **Node.js** (v18 이상)
   - 다운로드: https://nodejs.org
   - "LTS" 버전 추천

2. **Python** (v3.11 이상)
   - 다운로드: https://python.org
   - 설치 시 "Add Python to PATH" 체크 필수

## 실행 방법

### macOS
1. `Start.command` 파일을 더블클릭
2. 자동으로 브라우저가 열림

### Windows
1. `Start.bat` 파일을 더블클릭
2. 자동으로 브라우저가 열림

## 문제 해결

### "Node.js가 설치되어 있지 않습니다"
→ https://nodejs.org 에서 LTS 버전 설치

### "Python이 설치되어 있지 않습니다"
→ https://python.org 에서 설치, PATH 추가 확인

### 포트 충돌 오류
→ 이미 8000 또는 5173 포트를 사용하는 프로그램 종료

### 브라우저가 자동으로 안 열림
→ 수동으로 http://localhost:5173 접속

## 종료 방법

- macOS: 터미널 창 닫기 또는 Ctrl+C
- Windows: 콘솔 창들 모두 닫기
```

---

## 대안: 완전 독립 실행 (Electron)

더 간편한 배포를 원한다면 Electron으로 패키징 가능:

### 장점
- Node.js/Python 별도 설치 불필요
- 단일 `.app` (macOS) 또는 `.exe` (Windows) 파일
- 자체 브라우저 내장

### 단점
- 빌드 시간 증가
- 배포 파일 크기 ~200MB 이상
- Python 런타임 번들링 복잡

### 구현 개요
```
TileMatchAutoLevel.app/
├── Electron 브라우저 (Chromium)
├── Node.js 런타임
├── Python 런타임 (번들)
├── Backend (FastAPI)
└── Frontend (빌드된 정적 파일)
```

---

## 권장 구현 순서

1. **Phase 1**: 런처 스크립트 구현 (1-2시간)
   - `Start.command`, `Start.bat` 생성
   - `QUICK_START.md` 작성
   - 팀 내부 테스트

2. **Phase 2**: 안정화 (선택)
   - 오류 처리 강화
   - 자동 업데이트 기능
   - 로그 파일 저장

3. **Phase 3**: Electron 패키징 (선택, 필요시)
   - 완전 독립 실행 앱 빌드
   - 외부 배포용

---

## 결론

**즉시 구현 추천**: 옵션 A (통합 런처 스크립트)
- 구현 시간: 1-2시간
- 사용자 요구사항: Node.js + Python 설치 필요
- 실행 방법: 더블클릭 한 번
