# TileMatch Level Designer Tool

## Project Overview
타일매치 게임 레벨의 난이도 분석, 자동 생성, 게임부스트 연동을 위한 웹 기반 도구

## Tech Stack

### Backend (Python)
- **Framework**: FastAPI
- **Validation**: Pydantic
- **HTTP Client**: aiohttp
- **Testing**: pytest

### Frontend (TypeScript/React)
- **Framework**: React 18 + TypeScript
- **Build**: Vite
- **State**: Zustand
- **Server State**: TanStack React Query
- **Styling**: TailwindCSS
- **HTTP**: axios

## Directory Structure

```
TileMatchAutoLevel/
├── backend/
│   ├── app/
│   │   ├── main.py              # FastAPI entry
│   │   ├── config.py            # Settings
│   │   ├── api/routes/          # API endpoints
│   │   ├── core/                # Business logic
│   │   ├── clients/gboost.py    # GBoost client
│   │   └── models/              # Data models
│   └── tests/
├── frontend/
│   ├── src/
│   │   ├── App.tsx              # Main app
│   │   ├── api/                 # API clients
│   │   ├── components/          # UI components
│   │   ├── stores/              # Zustand stores
│   │   └── types/               # TypeScript types
│   └── package.json
└── SPECIFICATION.md
```

## Core Features
1. **Difficulty Analyzer**: JSON → score/grade/metrics
2. **Level Generator**: target difficulty → level JSON
3. **Visual Simulation**: bot play step-by-step
4. **GBoost Integration**: load/save/delete levels

## API Endpoints
- POST /api/analyze - 난이도 분석
- POST /api/generate - 레벨 생성
- POST /api/simulate/visual - 시뮬레이션
- GET/POST/DELETE /api/gboost/{board}/{level}

## Level JSON Structure
```json
{
  "layer": 8,
  "randSeed": 12345,
  "useTileCount": 6,
  "layer_N": {
    "col": "8", "row": "8",
    "tiles": { "x_y": ["type", "attr", [extra]] },
    "num": "count"
  }
}
```

---

## Game Rules (sp_template 기반)

### Core Mechanics
```
1. 유저가 필드 타일 클릭 → dock(하단 7칸 버퍼)에 추가
2. dock에 동일 타일 3개 모이면 → 자동 제거(매칭)
3. dock이 7칸 다 차면 → 게임 오버
4. 모든 타일 제거 → 클리어
```

**중요**: 1 클릭 = 1 타일 이동 = **1 move**
- 60개 타일 클리어 → 최소 60 moves 필요

### Layer Blocking
- 상위 레이어 타일이 하위 레이어 타일을 가림
- 가려진 타일은 선택 불가
- 상위부터 제거해야 하위 접근 가능

---

## Tile Types

### Matchable Tiles
| Type | Description |
|------|-------------|
| t0 | 랜덤 타일 (초기화 시 t1-t15 중 하나로 변환) |
| t1-t15 | 일반 매칭 타일 (색상/모양 구분) |
| t16 | 키 타일 (특수 매칭) |

### t0 Random Distribution
- `useTileCount`: 사용할 타일 종류 수 (기본값: 6)
- `randSeed`: 랜덤 시드 (결정론적 분배)
- **3개씩 세트로 분배** → 매칭 보장

### Goal Tiles
| Type | Description |
|------|-------------|
| craft_s | 크래프트 목표 (수집 필요) |
| stack_s | 스택 목표 (수집 필요) |

---

## Gimmicks (장애물/효과)

### Ice (얼음)
- **속성**: `ice`
- **동작**: 3단계 얼음층, 인접 타일 제거 시 1층씩 녹음
- **효과**: 얼음 남아있으면 선택 불가

### Chain (체인)
- **속성**: `chain`
- **동작**: 수평 인접 타일 제거 시 해제
- **효과**: 해제 전까지 선택 불가

### Grass (풀)
- **속성**: `grass`
- **동작**: 2단계, 인접 타일 제거 시 1층씩 제거
- **효과**: 풀 남아있으면 선택 불가

### Link (연결)
- **속성**: `link_n`, `link_s`, `link_e`, `link_w`
- **동작**: 지정 방향의 타일과 연결
- **효과**: 연결된 타일 모두 unblocked 상태여야 선택 가능

### Frog (개구리)
- **속성**: `frog`
- **동작**:
  - 타일 위에 개구리가 앉아있음
  - **매 move마다 모든 개구리가 동시에 이동**
  - 이동 가능 조건: frog 타입 + 개구리 없음 + 상위 막힘 없음
- **효과**: 개구리가 앉아있으면 선택 불가

### Bomb (폭탄)
- **속성**: `bomb` 또는 숫자 (예: `10`)
- **동작**: 매 move마다 카운트 -1
- **효과**: 카운트 0 도달 시 게임 오버

### Curtain (커튼)
- **속성**: `curtain_open`, `curtain_close`
- **동작**: 매 move마다 토글 (상위 레이어에 막히지 않은 경우)
- **효과**: 닫혀있으면 선택 불가

### Stack (스택)
- **속성**: `stack_n`, `stack_s`, `stack_e`, `stack_w`
- **동작**: 타일 선택 시 지정 방향으로 블록 밀기
- **효과**: 레이아웃 변경

### Teleport (텔레포트)
- **속성**: `teleport`
- **동작**: 특정 위치로 타일 이동
- **효과**: 타일 위치 재배치

---

## Difficulty Calculation

### Metrics
| Metric | Weight | Description |
|--------|--------|-------------|
| total_tiles | 0.3 | 총 타일 수 |
| active_layers | 5.0 | 활성 레이어 수 |
| chain_count | 3.0 | 체인 타일 수 |
| frog_count | 4.0 | 개구리 장애물 수 |
| link_count | 2.0 | 링크 타일 수 |
| goal_amount | 2.0 | 목표 수집량 |
| layer_blocking | 1.5 | 레이어 차단 점수 |

### Grade System
| Grade | Score | Description |
|-------|-------|-------------|
| S | 0-20 | 매우 쉬움 (튜토리얼급) |
| A | 21-40 | 쉬움 |
| B | 41-60 | 보통 (적정 난이도) |
| C | 61-80 | 어려움 (챌린지급) |
| D | 81-100 | 매우 어려움 (극한) |

---

## Simulation Notes

### max_moves 계산
```python
# 올바른 계산
max_moves = total_tiles + buffer

# 예시: 72개 타일
max_moves = 72 + 10 = 82
```

### Bot Profiles
| Bot | Description | Clear Rate Target |
|-----|-------------|-------------------|
| NOVICE | 초보자 | 40% |
| CASUAL | 캐주얼 | 60% |
| AVERAGE | 일반 | 75% |
| EXPERT | 숙련자 | 90% |
| OPTIMAL | 최적 | 98% |
