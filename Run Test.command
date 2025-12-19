#!/bin/bash
cd "$(dirname "$0")/backend"
source venv/bin/activate
echo "🧪 테스트 실행중..."
echo ""
pytest -v
echo ""
echo "테스트 완료. 아무 키나 누르면 종료합니다."
read -n 1
