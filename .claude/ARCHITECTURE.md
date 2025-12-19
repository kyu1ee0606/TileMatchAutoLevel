# Architecture

## System
```
Frontend (React) → Backend (FastAPI) → GBoost
```

## Backend Modules
- `core/analyzer.py` - 난이도 분석
- `core/generator.py` - 레벨 생성
- `core/simulator.py` - 시뮬레이션
- `clients/gboost.py` - GBoost 연동

## Frontend Stores
- `levelStore` - 레벨 상태
- `uiStore` - UI 상태
- `simulationStore` - 시뮬레이션

## Components
- GridEditor - 레벨 편집
- DifficultyPanel - 분석 결과
- GeneratorPanel - 자동 생성
- SimulationViewer - 시뮬레이션 뷰어
