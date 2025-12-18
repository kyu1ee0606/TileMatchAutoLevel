# TileMatch Level Designer - 문서 인덱스

## 프로젝트 개요

TileMatch Level Designer는 타일 매칭 게임의 레벨을 디자인하고 분석하는 풀스택 도구입니다.

### 기술 스택
- **Frontend**: React 18 + TypeScript + Vite + TailwindCSS
- **Backend**: Python 3.11 + FastAPI
- **State Management**: Zustand
- **External Integration**: GBoost (townpop API 패턴)

---

## 문서 목록

| 문서 | 설명 |
|------|------|
| [CHANGELOG.md](./CHANGELOG.md) | 변경 이력 및 수정 내역 |
| [SPECIFICATION.md](../SPECIFICATION.md) | 프로젝트 상세 명세서 |
| [README.md](../README.md) | 프로젝트 메인 README |

---

## 주요 기능

### 1. 그리드 에디터
- 레이어별 타일 배치/수정/삭제
- 다양한 타일 타입 및 속성 지원
- 레이어 선택 및 관리

### 2. 서버 레벨 관리 (GBoost 연동)
- 서버 레벨 목록 조회
- 검색 및 정렬 (번호, 날짜, 난이도)
- 클릭으로 즉시 레벨 로드
- 레벨 저장 및 새 레벨 생성

### 3. 난이도 분석
- 레벨 난이도 자동 분석
- 시각적 난이도 리포트

### 4. 자동 생성
- AI 기반 레벨 자동 생성 (개발 중)

---

## 디렉토리 구조

```
TileMatchAutoLevel/
├── backend/                    # FastAPI 백엔드
│   ├── app/
│   │   ├── api/routes/        # API 라우트
│   │   │   ├── gboost.py      # GBoost 연동 API
│   │   │   └── ...
│   │   ├── clients/           # 외부 서비스 클라이언트
│   │   │   └── gboost.py      # GBoost 클라이언트
│   │   └── main.py
│   └── requirements.txt
│
├── frontend/                   # React 프론트엔드
│   ├── src/
│   │   ├── components/
│   │   │   ├── GridEditor/    # 그리드 에디터 컴포넌트
│   │   │   │   ├── index.tsx
│   │   │   │   ├── TileGrid.tsx
│   │   │   │   ├── LayerSelector.tsx
│   │   │   │   └── LevelBrowser.tsx  # 서버 레벨 브라우저
│   │   │   ├── GBoostPanel/   # GBoost 설정 패널
│   │   │   └── ...
│   │   ├── stores/            # Zustand 상태 관리
│   │   │   ├── levelStore.ts  # 레벨 데이터 상태
│   │   │   └── uiStore.ts     # UI 상태
│   │   ├── api/               # API 클라이언트
│   │   ├── utils/             # 유틸리티 함수
│   │   │   └── helpers.ts     # 데이터 변환 함수 포함
│   │   └── types/             # TypeScript 타입 정의
│   └── package.json
│
├── docs/                       # 문서
│   ├── README.md              # 이 파일
│   └── CHANGELOG.md           # 변경 이력
│
└── docker-compose.yml          # Docker 설정
```

---

## 개발 환경 설정

### Backend
```bash
cd backend
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000
```

### Frontend
```bash
cd frontend
npm install
npm run dev
```

---

## GBoost 연동 설정

1. **설정 탭** 이동
2. 서버 정보 입력:
   - Server URL: GBoost 서버 주소
   - API Key: 인증 키
   - Project ID (AppID): 프로젝트 식별자
3. **연결 테스트** 클릭하여 확인
4. **설정 저장** 클릭

---

## 데이터 형식

### 서버 레벨 JSON (GBoost)
```json
{
  "layer": 4,
  "map": {
    "layer_0": { "col": "12", "row": "12", "tiles": {...}, "num": "10" },
    "layer_1": { "col": "11", "row": "11", "tiles": {...}, "num": "5" }
  }
}
```

### 프론트엔드 레벨 JSON
```json
{
  "layer": 4,
  "layer_0": { "col": "12", "row": "12", "tiles": {...}, "num": "10" },
  "layer_1": { "col": "11", "row": "11", "tiles": {...}, "num": "5" }
}
```

데이터 변환은 `frontend/src/utils/helpers.ts`의 함수들이 처리합니다:
- `convertServerLevelToFrontend()`: 서버 → 프론트엔드
- `convertFrontendLevelToServer()`: 프론트엔드 → 서버

---

## 최근 업데이트

최신 변경 사항은 [CHANGELOG.md](./CHANGELOG.md)를 참조하세요.

### 2024-12-18 주요 변경
- GBoost API 연동 수정 (townpop 패턴 적용)
- 에디터 탭 레이아웃 개선 (서버 레벨 목록 통합)
- 다양한 레벨 크기 지원 (동적 레이어 선택)
- 서버-프론트엔드 데이터 변환 로직 추가
