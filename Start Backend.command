#!/bin/bash
cd "$(dirname "$0")/backend"
source venv/bin/activate
echo "🚀 백엔드 서버 시작중... (http://localhost:8000)"
echo "종료: Ctrl+C"
echo ""
uvicorn app.main:app --reload --port 8000
