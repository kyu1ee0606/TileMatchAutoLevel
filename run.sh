#!/bin/bash

# 타일매치 레벨 디자이너 실행 스크립트
# 사용법: ./run.sh [command]

ROOT_DIR="$(cd "$(dirname "$0")" && pwd)"
BACKEND_DIR="$ROOT_DIR/backend"
FRONTEND_DIR="$ROOT_DIR/frontend"

case "$1" in
    # 백엔드 실행 (개발 모드 - hot reload, 1 worker)
    backend|b)
        echo "🚀 백엔드 서버 시작 - 개발 모드 (http://localhost:8000)..."
        cd "$BACKEND_DIR" && source .venv/bin/activate && uvicorn app.main:app --reload --port 8000
        ;;

    # 백엔드 실행 (프로덕션 모드 - multi-worker, 검증 생성 고속)
    backend-prod|bp)
        WORKERS=${2:-4}
        echo "🚀 백엔드 서버 시작 - 프로덕션 모드 (workers=$WORKERS, http://localhost:8000)..."
        cd "$BACKEND_DIR" && source .venv/bin/activate && uvicorn app.main:app --workers "$WORKERS" --port 8000
        ;;

    # 프론트엔드 실행
    frontend|f)
        echo "🎨 프론트엔드 서버 시작..."
        cd "$FRONTEND_DIR" && npm run dev
        ;;

    # 테스트 실행
    test|t)
        echo "🧪 테스트 실행..."
        cd "$BACKEND_DIR" && source venv/bin/activate && pytest -v
        ;;

    # 임포트 테스트 (빠른 검증)
    check|c)
        echo "✅ 임포트 검사..."
        cd "$BACKEND_DIR" && source venv/bin/activate && python -c "from app.main import app; print('Backend OK')"
        ;;

    # 의존성 설치
    install|i)
        echo "📦 의존성 설치..."
        cd "$BACKEND_DIR" && python -m venv venv && source venv/bin/activate && pip install -r requirements.txt
        cd "$FRONTEND_DIR" && npm install
        echo "✅ 설치 완료"
        ;;

    # 빌드
    build)
        echo "🏗️ 프로덕션 빌드..."
        cd "$FRONTEND_DIR" && npm run build
        ;;

    # 도움말
    *)
        echo "타일매치 레벨 디자이너 - 실행 스크립트"
        echo ""
        echo "사용법: ./run.sh [command]"
        echo ""
        echo "명령어:"
        echo "  backend, b          - 백엔드 서버 실행 - 개발 모드 (hot reload)"
        echo "  backend-prod, bp [N] - 백엔드 서버 실행 - 프로덕션 모드 (N workers)"
        echo "  frontend, f  - 프론트엔드 서버 실행"
        echo "  test, t      - pytest 테스트 실행"
        echo "  check, c     - 빠른 임포트 검사"
        echo "  install, i   - 의존성 설치"
        echo "  build        - 프로덕션 빌드"
        echo ""
        echo "예시:"
        echo "  ./run.sh b      # 백엔드 실행"
        echo "  ./run.sh t      # 테스트 실행"
        echo "  ./run.sh c      # 빠른 검사"
        ;;
esac
