# TileMatch Level Designer Tool

타일매치 게임 레벨의 난이도 분석, 자동 생성, 게임부스트 연동을 위한 웹 기반 도구

## 주요 기능

- **난이도 분석기**: 레벨 JSON을 분석하여 객관적인 난이도 점수/등급 산출
- **레벨 생성기**: 목표 난이도에 맞는 레벨을 자동으로 생성
- **게임부스트 연동**: 웹에서 직접 레벨 데이터를 저장/불러오기/배포

## 기술 스택

### Backend
- Python 3.11+
- FastAPI
- Pydantic 2.0
- aiohttp

### Frontend
- React 18
- TypeScript
- Vite
- TailwindCSS
- Zustand
- React Query

## 시작하기

### 개발 환경 설정

#### Backend

```bash
cd backend

# 가상환경 생성 및 활성화
python -m venv venv
source venv/bin/activate  # Windows: venv\Scripts\activate

# 의존성 설치
pip install -r requirements.txt

# 환경 변수 설정
cp .env.example .env
# .env 파일 수정

# 서버 실행
uvicorn app.main:app --reload --port 8000
```

#### Frontend

```bash
cd frontend

# 의존성 설치
npm install

# 개발 서버 실행
npm run dev
```

### Docker로 실행

```bash
# 개발 환경
docker-compose -f docker-compose.dev.yml up

# 프로덕션 환경
docker-compose up --build
```

## API 문서

서버 실행 후 다음 URL에서 API 문서를 확인할 수 있습니다:

- Swagger UI: http://localhost:8000/docs
- ReDoc: http://localhost:8000/redoc

### 주요 엔드포인트

| 엔드포인트 | 메서드 | 설명 |
|-----------|--------|------|
| `/api/analyze` | POST | 레벨 난이도 분석 |
| `/api/generate` | POST | 레벨 자동 생성 |
| `/api/simulate` | POST | Monte Carlo 시뮬레이션 |
| `/api/gboost/{board_id}/{level_id}` | GET/POST/DELETE | 게임부스트 연동 |

## 프로젝트 구조

```
TileMatchAutoLevel/
├── backend/
│   ├── app/
│   │   ├── api/routes/       # API 라우트
│   │   ├── core/             # 핵심 로직 (분석기, 생성기)
│   │   ├── clients/          # 외부 서비스 클라이언트
│   │   ├── models/           # 데이터 모델
│   │   └── utils/            # 유틸리티
│   ├── tests/                # 테스트
│   └── requirements.txt
├── frontend/
│   ├── src/
│   │   ├── components/       # React 컴포넌트
│   │   ├── api/              # API 클라이언트
│   │   ├── stores/           # Zustand 스토어
│   │   ├── types/            # TypeScript 타입
│   │   └── utils/            # 유틸리티
│   └── package.json
├── docker-compose.yml
└── README.md
```

## 난이도 등급

| 등급 | 점수 범위 | 설명 |
|------|----------|------|
| **S** | 0 ~ 20 | 매우 쉬움 |
| **A** | 21 ~ 40 | 쉬움 |
| **B** | 41 ~ 60 | 보통 |
| **C** | 61 ~ 80 | 어려움 |
| **D** | 81 ~ 100 | 매우 어려움 |

## 테스트

```bash
cd backend
pytest
```

## 라이선스

MIT License
