# TileMatchAutoLevel 프로젝트 아키텍처

## 프로젝트 구조

### 백엔드 (Python/FastAPI)
- `backend/app/core/generator.py` - 레벨 생성 엔진
- `backend/app/core/analyzer.py` - 난이도 분석기
- `backend/app/core/simulator.py` - 봇 시뮬레이션
- `backend/app/models/level.py` - 레벨 데이터 모델
- `backend/app/api/` - REST API 엔드포인트

### 프론트엔드 (React/TypeScript/Vite)
- `frontend/src/components/LevelSetGenerator/` - 레벨 세트 생성 UI
  - `index.tsx` - 메인 생성 로직
  - `DifficultyGraph.tsx` - 난이도 그래프 편집기
  - `GenerationProgress.tsx` - 생성 진행 표시
  - `LevelSetConfig.tsx` - 설정 패널
- `frontend/src/types/levelSet.ts` - 레벨 세트 타입 정의
- `frontend/src/api/generate.ts` - API 클라이언트

## 핵심 흐름

### 레벨 생성 프로세스
1. 사용자가 난이도 그래프 설정
2. 등급 분포 계산 (S/A/B/C/D)
3. 등급별 생성 계획 수립
4. 각 레벨 생성 + 등급 일치 재시도
5. 후처리: 난이도 곡선에 맞게 재배치

### 난이도 계산 요소
- total_tiles (0.5)
- active_layers (4.0)
- chain_count (3.0)
- frog_count (4.0)
- link_count (2.0)
- ice_count (2.5)
- goal_amount (1.5)
- layer_blocking (0.15)

## API 엔드포인트
- `POST /generate` - 단일 레벨 생성
- `POST /generate/validated` - 검증 포함 레벨 생성
- `POST /simulate` - 레벨 시뮬레이션
- `POST /level-set` - 레벨 세트 저장

## 기술 스택
- Backend: Python 3.x, FastAPI, Uvicorn
- Frontend: React 18, TypeScript, Vite, TailwindCSS
- State: Zustand (uiStore)
