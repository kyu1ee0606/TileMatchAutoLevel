.PHONY: help install dev backend frontend test lint clean build

# 기본 명령어
help:
	@echo "사용 가능한 명령어:"
	@echo "  make install    - 전체 의존성 설치"
	@echo "  make dev        - 백엔드 + 프론트엔드 동시 실행"
	@echo "  make backend    - 백엔드만 실행"
	@echo "  make frontend   - 프론트엔드만 실행"
	@echo "  make test       - 백엔드 테스트 실행"
	@echo "  make lint       - 코드 검사"
	@echo "  make build      - 프로덕션 빌드"
	@echo "  make clean      - 캐시 및 빌드 파일 정리"

# 의존성 설치
install:
	cd backend && python -m venv venv && source venv/bin/activate && pip install -r requirements.txt
	cd frontend && npm install

# 개발 서버 실행
dev:
	@echo "백엔드와 프론트엔드를 동시에 실행합니다..."
	@make backend & make frontend

backend:
	cd backend && source venv/bin/activate && uvicorn app.main:app --reload --port 8000

frontend:
	cd frontend && npm run dev

# 테스트
test:
	cd backend && source venv/bin/activate && pytest -v

test-watch:
	cd backend && source venv/bin/activate && pytest -v --watch

# 코드 검사
lint:
	cd backend && source venv/bin/activate && python -c "from app.main import app; print('Backend OK')"
	cd frontend && npm run build 2>&1 | head -20

# 빌드
build:
	cd frontend && npm run build

# 정리
clean:
	find . -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name ".pytest_cache" -exec rm -rf {} + 2>/dev/null || true
	rm -rf frontend/dist 2>/dev/null || true
	rm -rf backend/.coverage 2>/dev/null || true
