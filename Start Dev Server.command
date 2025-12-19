#!/bin/bash
cd "$(dirname "$0")"

echo "🚀 타일매치 레벨 디자이너 시작중..."
echo ""

# 백엔드 시작 (백그라운드)
echo "1. 백엔드 서버 시작..."
cd backend
source venv/bin/activate
uvicorn app.main:app --reload --port 8000 &
BACKEND_PID=$!
cd ..

# 잠시 대기
sleep 2

# 프론트엔드 시작 (백그라운드)
echo "2. 프론트엔드 서버 시작..."
cd frontend
npm run dev &
FRONTEND_PID=$!
cd ..

# 잠시 대기 후 브라우저 열기
sleep 3
echo ""
echo "3. 브라우저 열기..."
open http://localhost:5173

echo ""
echo "=========================================="
echo "✅ 서버 실행중!"
echo "   - 프론트엔드: http://localhost:5173"
echo "   - 백엔드 API: http://localhost:8000"
echo "   - API 문서:   http://localhost:8000/docs"
echo ""
echo "종료하려면 이 창을 닫거나 Ctrl+C를 누르세요"
echo "=========================================="

# 종료 시 모든 프로세스 정리
trap "kill $BACKEND_PID $FRONTEND_PID 2>/dev/null; exit" INT TERM

# 대기
wait
