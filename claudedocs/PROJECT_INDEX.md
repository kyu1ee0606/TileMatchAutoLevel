# TileMatchAutoLevel 프로젝트 인덱스

**마지막 업데이트**: 2025-12-31
**프로젝트 버전**: MVP + 레벨 생성 자동화

---

## ⚠️ 작업 지침: 백엔드/프론트엔드 교차검증

**중요**: 백엔드와 프론트엔드를 수정할 때 반드시 다음 사항을 확인하세요:

### 스키마 수정 시 필수 체크리스트

1. **백엔드 스키마 변경** (`backend/app/models/schemas.py`)
   - Pydantic 모델 필드 추가/변경/삭제 시 프론트엔드 타입도 동시 수정

2. **프론트엔드 타입 동기화** (`frontend/src/types/simulation.ts`)
   - 백엔드 스키마와 1:1 매핑되는 TypeScript 인터페이스 수정
   - `VisualBotMove`, `VisualGameState` 등 관련 타입 모두 확인

3. **API 응답 처리 코드 수정** (`backend/app/api/routes/simulate.py`)
   - 스키마에 맞게 데이터 수집 로직 수정
   - 타입 어노테이션 일치 확인 (`List` → `Dict` 등)

4. **컴포넌트 Props 및 상태 수정**
   - `BotTileGrid.tsx` - Props 타입 및 기본값 수정
   - `BotViewer.tsx` - Props 전달 및 기본값 수정
   - `SimulationGrid.tsx` - API 응답 파싱 및 기본값 수정

5. **TypeScript 컴파일 체크**
   - 작업 완료 후 `npx tsc --noEmit` 실행하여 타입 오류 확인

### 예시: 텔레포트 셔플 타입 변경

```diff
# 백엔드 schemas.py
- teleport_states_after: List[str]
+ teleport_states_after: Dict[str, str]

# 프론트엔드 simulation.ts
- teleport_states_after: string[]
+ teleport_states_after: Record<string, string>

# 컴포넌트 기본값
- initialTeleportStates = []
+ initialTeleportStates = {}
```

---

## 📁 프로젝트 구조

```
TileMatchAutoLevel/
├── backend/                 # FastAPI 백엔드
│   ├── app/
│   │   ├── api/routes/     # API 라우터
│   │   │   ├── generate.py # 레벨 생성 API
│   │   │   ├── simulate.py # 봇 시뮬레이션 API
│   │   │   └── analyze.py  # 레벨 분석 API
│   │   ├── core/           # 핵심 로직
│   │   │   ├── generator.py     # 레벨 생성기 (장애물 생성 포함)
│   │   │   ├── bot_simulator.py # 봇 시뮬레이터 (기믹 처리)
│   │   │   └── analyzer.py      # 난이도 분석기
│   │   ├── models/         # 데이터 모델
│   │   │   ├── level.py    # 레벨 모델
│   │   │   ├── schemas.py  # Pydantic 스키마
│   │   │   └── bot_profile.py # 봇 프로필 정의
│   │   └── storage/        # 로컬 저장소
│   │       └── local_levels/ # 로컬 저장 레벨
│   └── main.py
├── frontend/                # React + TypeScript 프론트엔드
│   └── src/
│       ├── components/
│       │   ├── GeneratorPanel/  # 레벨 생성 패널
│       │   ├── GridEditor/      # 그리드 에디터
│       │   ├── DifficultyPanel/ # 난이도 분석 패널
│       │   └── BotViewer/       # 봇 시뮬레이션 뷰어
│       ├── stores/             # Zustand 상태 관리
│       │   ├── levelStore.ts   # 레벨 상태
│       │   └── uiStore.ts      # UI 상태
│       ├── api/                # API 클라이언트
│       ├── types/              # TypeScript 타입
│       └── utils/              # 유틸리티 함수
├── claudedocs/              # Claude 생성 문서
└── .claude/                 # Claude Code 설정
```

---

## 🎮 구현된 기믹 (15개)

### 기본 기믹
| 기믹 | 코드 | 설명 | 봇 지원 |
|------|------|------|---------|
| None | `none` | 기본 타일 | ✅ |
| Ice | `ice` | 1~3겹 얼음. 노출 시 다른 타일 선택마다 1겹씩 감소, 0이 되면 선택 가능 | ✅ |
| Chain | `chain` | 잠금 (좌우 인접 클리어로 해제) | ✅ |
| Grass | `grass` | 1~2겹. 인접 타일 클리어 시 1겹씩 제거 | ✅ |

### 연결 기믹
| 기믹 | 코드 | 설명 | 봇 지원 |
|------|------|------|---------|
| Link East | `link_e` | 동쪽 타일과 연결, 함께 선택됨 (독 2칸 사용) | ✅ |
| Link West | `link_w` | 서쪽 타일과 연결, 함께 선택됨 (독 2칸 사용) | ✅ |
| Link South | `link_s` | 남쪽 타일과 연결, 함께 선택됨 (독 2칸 사용) | ✅ |
| Link North | `link_n` | 북쪽 타일과 연결, 함께 선택됨 (독 2칸 사용) | ✅ |

### 이동/변환 기믹
| 기믹 | 코드 | 설명 | 봇 지원 |
|------|------|------|---------|
| Frog | `frog` | 랜덤 점프하여 다른 타일 위를 블로킹 | ⚠️ 확률적 |
| Teleport | `teleport` | 3회 클릭마다 텔레포트 타일끼리 위치 교환 | ✅ |
| Curtain | `curtain` | 열림/닫힘 토글, 닫혀있으면 선택 불가 | ✅ |

### 특수 기믹
| 기믹 | 코드 | 설명 | 봇 지원 |
|------|------|------|---------|
| Bomb | `bomb` | 카운트다운 보유. 노출 시 다른 타일 선택마다 1씩 감소, 0이 되면 게임오버 | ✅ |
| Craft | `craft` | 제작 박스, 타일 생성 | ✅ |

### 스택 기믹
| 기믹 | 코드 | 설명 | 봇 지원 |
|------|------|------|---------|
| Stack North | `stack_n` | 북쪽으로 밀림 | ✅ |
| Stack South | `stack_s` | 남쪽으로 밀림 | ✅ |
| Stack East | `stack_e` | 동쪽으로 밀림 | ✅ |
| Stack West | `stack_w` | 서쪽으로 밀림 | ✅ |

---

## 🤖 봇 프로필 (5종)

| 봇 | 실수율 | Lookahead | 클리어율 목표 | 가중치 |
|----|--------|-----------|--------------|--------|
| NOVICE | 40% | 0 | ~40% | 0.5 |
| CASUAL | 20% | 1 | ~60% | 1.0 |
| AVERAGE | 10% | 2 | ~75% | 1.5 |
| EXPERT | 2% | 5 | ~90% | 0.8 |
| OPTIMAL | 0% | 10 | ~98% | 0.3 |

---

## 📡 주요 API 엔드포인트

### 레벨 생성
| Method | Endpoint | 설명 |
|--------|----------|------|
| POST | `/api/generate` | 단일 레벨 생성 |
| POST | `/api/generate/multiple` | 다중 레벨 생성 |

### 봇 시뮬레이션
| Method | Endpoint | 설명 |
|--------|----------|------|
| POST | `/api/simulate/visual` | 시각적 시뮬레이션 (1회) |
| POST | `/api/simulate/multi-bot` | 다중 봇 통계 (N회) |
| GET | `/api/simulate/benchmark/list` | 벤치마크 레벨 목록 |

### 로컬 레벨 관리
| Method | Endpoint | 설명 |
|--------|----------|------|
| GET | `/api/simulate/local/list` | 로컬 레벨 목록 |
| GET | `/api/simulate/local/{id}` | 특정 레벨 조회 |
| POST | `/api/simulate/local/save` | 레벨 저장 |
| DELETE | `/api/simulate/local/{id}` | 레벨 삭제 |

---

## 🔄 최근 변경 사항 (2025-12-23)

### ✅ 레벨 생성기 개선 (generator.py)
- **Grass 장애물 추가**: 4방향 중 2개 이상 클리어 가능한 이웃 필요
- **Chain 규칙 수정**: 좌우(같은 행) 인접 타일만 체크하도록 수정
- **장애물 개수 설정**: min/max 범위로 장애물 수 직접 지정 가능
- **유효성 검증 강화**: 타일 수 조정 후 장애물 재검증

### ✅ GeneratorPanel UI 개선 (frontend)
- **장애물 개수 슬라이더**: 각 장애물별 min/max 설정 UI
- **Grass 장애물 옵션 추가**: 체크박스 + 개수 설정
- **API 파라미터 확장**: `obstacle_counts` 필드 추가

### ✅ GridEditor 개선 (frontend)
- **타일 정보 표시 개선**: effect_type 시각화
- **Dock 상태 유지**: 게임 오버 시에도 dock 타일 보존

### ✅ 타입 정의 확장 (types/index.ts)
- `ObstacleCountConfig` 인터페이스 추가
- `GenerationParams.obstacle_counts` 필드 추가

---

## 📚 문서 목록 (claudedocs/)

| 파일 | 설명 |
|------|------|
| [PROJECT_INDEX.md](PROJECT_INDEX.md) | 프로젝트 인덱스 (현재 문서) |
| [AUTOMATION_SUMMARY.md](AUTOMATION_SUMMARY.md) | 자동화 시스템 요약 |
| [LOCAL_LEVELS_GUIDE.md](LOCAL_LEVELS_GUIDE.md) | 로컬 레벨 관리 가이드 |
| [LEVEL_GENERATION_GUIDE.md](LEVEL_GENERATION_GUIDE.md) | 레벨 생성 도구 가이드 |
| [BENCHMARK_API_GUIDE.md](BENCHMARK_API_GUIDE.md) | 벤치마크 API 가이드 |
| [BENCHMARK_SYSTEM.md](BENCHMARK_SYSTEM.md) | 벤치마크 시스템 설명 |
| [FINAL_SUMMARY.md](FINAL_SUMMARY.md) | 최종 요약 |
| [AUDIT_Randomness_Removal.md](AUDIT_Randomness_Removal.md) | 랜덤성 제거 감사 |

---

## 🎯 향후 계획

### Phase 1: AutoPlay 난이도 분석 (계획됨)
- `POST /api/analyze/autoplay` 엔드포인트
- 100회 × 5봇 통계적 난이도 측정
- 밸런스 권장사항 자동 생성

### Phase 2: 레벨 자동화 파이프라인
- 목표 난이도 → 레벨 생성 → 봇 검증 → 자동 조정
- 피드백 루프 기반 레벨 밸런싱

### Phase 3: 고급 기능
- 기믹 조합 최적화
- 레벨 시각화 개선
- 게임 서버 연동

---

## 🔧 개발 환경

### 백엔드
```bash
cd backend
pip install -r requirements.txt
uvicorn main:app --reload --port 8000
```

### 프론트엔드
```bash
cd frontend
npm install
npm run dev  # http://localhost:5173
```

---

**문서 버전**: 1.0
**작성자**: Claude
