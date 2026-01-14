#!/bin/bash
# TileMatch Level Designer - Mac 실행 스크립트

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

echo "=========================================="
echo "  🎮 TileMatch 맵 에디터 시작중..."
echo "=========================================="
echo ""

# 색상 정의
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
NC='\033[0m'

# 종료 시 cleanup
cleanup() {
    echo ""
    echo -e "${YELLOW}종료중...${NC}"
    kill $BACKEND_PID 2>/dev/null
    kill $FRONTEND_PID 2>/dev/null
    exit 0
}
trap cleanup SIGINT SIGTERM

# ===== 의존성 체크 =====
echo -e "${CYAN}[1/4] 필수 프로그램 확인${NC}"

# Node.js 체크
if ! command -v node &> /dev/null; then
    echo -e "${RED}❌ Node.js가 설치되어 있지 않습니다.${NC}"
    echo ""
    echo "   설치 방법:"
    echo "   1. https://nodejs.org 접속"
    echo "   2. LTS 버전 다운로드 및 설치"
    echo ""
    read -p "Enter 키를 눌러 종료..."
    exit 1
fi
echo -e "   ${GREEN}✓${NC} Node.js $(node --version)"

# Python 체크
if ! command -v python3 &> /dev/null; then
    echo -e "${RED}❌ Python 3가 설치되어 있지 않습니다.${NC}"
    echo ""
    echo "   설치 방법:"
    echo "   1. https://python.org 접속"
    echo "   2. Python 3.11+ 다운로드 및 설치"
    echo ""
    read -p "Enter 키를 눌러 종료..."
    exit 1
fi
echo -e "   ${GREEN}✓${NC} $(python3 --version)"

# ===== Frontend 설정 =====
echo ""
echo -e "${CYAN}[2/4] 프론트엔드 설정${NC}"

if [ ! -d "frontend/node_modules" ]; then
    echo -e "   ${YELLOW}📦 패키지 설치중... (최초 1회만)${NC}"
    cd frontend && npm install --silent && cd ..
    echo -e "   ${GREEN}✓${NC} 프론트엔드 패키지 설치 완료"
else
    echo -e "   ${GREEN}✓${NC} 프론트엔드 패키지 확인됨"
fi

# ===== Backend 설정 =====
echo ""
echo -e "${CYAN}[3/4] 백엔드 설정${NC}"

if [ ! -d "backend/venv" ]; then
    echo -e "   ${YELLOW}🐍 가상환경 생성중... (최초 1회만)${NC}"
    cd backend && python3 -m venv venv && cd ..
fi

cd backend
source venv/bin/activate

# 패키지 설치 확인
if ! pip show fastapi > /dev/null 2>&1; then
    echo -e "   ${YELLOW}📦 패키지 설치중... (최초 1회만)${NC}"
    pip install -r requirements.txt -q
    echo -e "   ${GREEN}✓${NC} 백엔드 패키지 설치 완료"
else
    echo -e "   ${GREEN}✓${NC} 백엔드 패키지 확인됨"
fi
cd ..

# ===== 서버 시작 =====
echo ""
echo -e "${CYAN}[4/4] 서버 시작${NC}"

# 백엔드 시작
echo -e "   🚀 백엔드 서버 시작중..."
cd backend
source venv/bin/activate
uvicorn app.main:app --host 0.0.0.0 --port 8000 > /dev/null 2>&1 &
BACKEND_PID=$!
cd ..

# 백엔드 준비 대기
for i in {1..30}; do
    if curl -s http://localhost:8000/health > /dev/null 2>&1; then
        echo -e "   ${GREEN}✓${NC} 백엔드 준비 완료 (포트 8000)"
        break
    fi
    if [ $i -eq 30 ]; then
        echo -e "   ${RED}❌ 백엔드 시작 실패${NC}"
        exit 1
    fi
    sleep 1
done

# 프론트엔드 시작
echo -e "   🌐 프론트엔드 서버 시작중..."
cd frontend
npm run dev > /dev/null 2>&1 &
FRONTEND_PID=$!
cd ..

sleep 3
echo -e "   ${GREEN}✓${NC} 프론트엔드 준비 완료 (포트 5173)"

# ===== 완료 =====
echo ""
echo -e "${GREEN}=========================================="
echo "  ✅ 맵 에디터 준비 완료!"
echo "==========================================${NC}"
echo ""
echo "  📍 에디터 주소: http://localhost:5173"
echo "  📖 API 문서:    http://localhost:8000/docs"
echo ""
echo -e "  ${YELLOW}종료하려면 이 창을 닫거나 Ctrl+C${NC}"
echo ""

# 브라우저 열기
open http://localhost:5173

# 프로세스 대기
wait $BACKEND_PID $FRONTEND_PID
