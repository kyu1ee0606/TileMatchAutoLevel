# 타일매치 레벨 디자이너 도구 - 구현 명세서

> **프로젝트명**: TileMatch Level Designer Tool
> **버전**: 1.0.0
> **작성일**: 2025-12-18
> **목적**: 타일매치 게임 레벨의 난이도 분석, 자동 생성, 게임부스트 연동을 위한 웹 기반 도구

---

## 📋 목차

1. [개요](#1-개요)
2. [참고 프로젝트](#2-참고-프로젝트)
3. [시스템 아키텍처](#3-시스템-아키텍처)
4. [레벨 JSON 구조](#4-레벨-json-구조)
5. [핵심 기능 상세](#5-핵심-기능-상세)
6. [API 명세](#6-api-명세)
7. [데이터 모델](#7-데이터-모델)
8. [프론트엔드 UI 명세](#8-프론트엔드-ui-명세)
9. [게임부스트 연동](#9-게임부스트-연동)
10. [구현 계획](#10-구현-계획)
11. [기술 스택](#11-기술-스택)

---

## 1. 개요

### 1.1 프로젝트 배경

타운팝 게임의 레벨 시스템은 맵에디터와 연동되어 서버(게임부스트)에서 JSON 형식으로 레벨 데이터를 가져오는 방식입니다. 현재 레벨 디자인은 수동으로 진행되며, 난이도 측정이 주관적이고 일관성이 부족합니다.

### 1.2 목표

| 목표 | 설명 |
|------|------|
| **난이도 자동 분석** | 레벨 JSON을 분석하여 객관적인 난이도 점수/등급 산출 |
| **레벨 자동 생성** | 목표 난이도에 맞는 레벨을 자동으로 생성 |
| **게임부스트 연동** | 웹에서 직접 레벨 데이터를 저장/불러오기/배포 |

### 1.3 핵심 기능 요약

```
┌─────────────────────────────────────────────────────────────┐
│                    Level Designer Tool                       │
├─────────────────────────────────────────────────────────────┤
│  ① 난이도 분석기    - JSON → 점수/등급/메트릭스/권장사항     │
│  ② 레벨 생성기      - 목표 난이도 → 레벨 JSON 자동 생성      │
│  ③ 게임부스트 연동  - 웹 ↔ 서버 직접 저장/불러오기           │
└─────────────────────────────────────────────────────────────┘
```

---

## 2. 참고 프로젝트

본 프로젝트 구현 시 아래 기존 프로젝트들을 참고합니다.

### 2.1 프로젝트 목록

| 프로젝트 | 별명 | 경로 | 용도 |
|----------|------|------|------|
| **sp_hellotown** | 헬로타운 | `/Users/casualdev/Documents/sp_hellotown` | 실 운영 게임, GBoost 연동 패턴 참고 |
| **sp_template** | 타운팝 | `/Users/casualdev/Documents/sp_template` | 레벨 시스템, 맵에디터, 타일매치 로직 참고 |
| **sp_outgame_template** | 아웃게임 템플릿 | `/Users/casualdev/sp_outgame_template` | 현재 템플릿 프로젝트, 브릿지 패턴 참고 |

### 2.2 참고 항목별 프로젝트

| 참고 항목 | 주 참고 프로젝트 | 관련 파일/경로 |
|----------|-----------------|----------------|
| **레벨 JSON 구조** | 타운팝 | `Assets/Resources/Levels/` |
| **타일 타입 정의** | 타운팝 | `Assets/Scripts/Game/TileTypes.cs` |
| **맵에디터** | 타운팝 | `Assets/Editor/MapEditor/` |
| **GBoost 클라이언트** | 헬로타운 | `Assets/08.Scripts/spGBoostMng.cs` |
| **서버 데이터 형식** | 헬로타운 | `spGBoostMng.GetObjectArray()` |
| **브릿지 패턴** | 아웃게임 템플릿 | `Assets/Template/Scripts/Core/` |
| **인터페이스 설계** | 아웃게임 템플릿 | `Assets/Template/Scripts/Interfaces/` |

### 2.3 주요 참고 코드

#### 타운팝 - 레벨 로더

```csharp
// 참고 경로: sp_template/Assets/Scripts/Game/LevelLoader.cs
// 레벨 JSON 파싱 및 게임 오브젝트 생성 로직
```

#### 헬로타운 - GBoost 데이터 조회

```csharp
// 참고 경로: sp_hellotown/Assets/08.Scripts/spGBoostMng.cs
// spGBoostMng.inst.GetObjectArray("level_data") 패턴
```

#### 아웃게임 템플릿 - 서비스 인터페이스 패턴

```csharp
// 참고 경로: sp_outgame_template/Assets/Template/Scripts/Interfaces/IGameDataBridge.cs
// 데이터 서비스 추상화 패턴
```

### 2.4 참고 시 주의사항

1. **보안**: 실제 API 키, 서버 URL 등 민감 정보는 복사하지 않음
2. **라이선스**: 코드 직접 복사 대신 패턴과 구조만 참고
3. **버전**: 각 프로젝트의 Unity 버전 차이 고려 (헬로타운: 2021.x, 타운팝: 2022.x)
4. **의존성**: spComponents 등 공통 라이브러리 의존성 확인 필요

---

## 3. 시스템 아키텍처

### 3.1 전체 구조

```
┌─────────────────────────────────────────────────────────────┐
│                     Web Frontend (React)                     │
│  ┌─────────────┐ ┌─────────────┐ ┌─────────────────────────┐│
│  │ Grid Editor │ │ Difficulty  │ │ GBoost Manager          ││
│  │ & Visualizer│ │ Dashboard   │ │ (Load/Save/Publish)     ││
│  └─────────────┘ └─────────────┘ └─────────────────────────┘│
└─────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────┐
│                   FastAPI Backend (Python)                   │
├─────────────────────────────────────────────────────────────┤
│  POST /api/analyze      ← 난이도 분석                        │
│  POST /api/generate     ← 레벨 자동 생성                     │
│  POST /api/simulate     ← Monte Carlo 시뮬레이션 (선택)      │
│  POST /api/gboost/save  ← 게임부스트 저장                    │
│  GET  /api/gboost/load  ← 게임부스트 불러오기                │
└─────────────────────────────────────────────────────────────┘
          │                    │                    │
          ▼                    ▼                    ▼
   ┌────────────┐      ┌────────────┐      ┌────────────────┐
   │ Analyzer   │      │ Generator  │      │ GBoost Client  │
   │ Engine     │      │ Engine     │      │ (HTTP API)     │
   └────────────┘      └────────────┘      └────────────────┘
```

### 3.2 컴포넌트 역할

| 컴포넌트 | 역할 | 기술 |
|----------|------|------|
| **Web Frontend** | UI, 시각화, 사용자 인터랙션 | React + TypeScript |
| **FastAPI Backend** | API 서버, 비즈니스 로직 | Python + FastAPI |
| **Analyzer Engine** | 레벨 난이도 정적 분석 | Python |
| **Generator Engine** | 절차적 레벨 생성 + 난이도 조정 | Python |
| **GBoost Client** | 게임부스트 서버 HTTP 통신 | aiohttp |

---

## 4. 레벨 JSON 구조

### 4.1 전체 구조

```json
{
  "layer": 8,
  "layer_0": { "col": "8", "row": "8", "tiles": {}, "num": "0" },
  "layer_1": { "col": "7", "row": "7", "tiles": {}, "num": "0" },
  "layer_2": { "col": "8", "row": "8", "tiles": {}, "num": "0" },
  "layer_3": { "col": "7", "row": "7", "tiles": {...}, "num": "1" },
  "layer_4": { "col": "8", "row": "8", "tiles": {...}, "num": "4" },
  "layer_5": { "col": "7", "row": "7", "tiles": {...}, "num": "32" },
  "layer_6": { "col": "8", "row": "8", "tiles": {...}, "num": "16" },
  "layer_7": { "col": "7", "row": "7", "tiles": {...}, "num": "52" }
}
```

### 4.2 레이어 구조

```
layer_7 (최상위) ─ 52타일: 메인 플레이 영역, 목표 배치
layer_6          ─ 16타일: 중간층 장애물
layer_5          ─ 32타일: 하위층
layer_4          ─  4타일: 기반층
layer_3          ─  1타일: 최하위
layer_0~2        ─  비어있음
```

### 4.3 타일 데이터 형식

```json
"x_y": ["타일타입", "속성", [추가데이터]]
```

**예시:**
```json
{
  "3_3": ["t0", ""],           // 기본 타일
  "2_0": ["t2", "chain"],      // 체인 속성
  "5_1": ["t0", "frog"],       // 개구리 장애물
  "1_0": ["t2", "link_w"],     // 링크 타일
  "3_6": ["craft_s", "", [3]], // 목표: 3개 수집
  "6_6": ["stack_s", "", [6]]  // 목표: 6개 수집
}
```

### 4.4 타일 타입 정의

| 타입 | 설명 | 비고 |
|------|------|------|
| `t0` | 기본 매칭 타일 | 가장 일반적 |
| `t2`, `t4`, `t5`, `t6` | 특수 타일 A~D | 색상/모양 변형 |
| `t8`, `t9` | 장애물 타일 | 파괴 불가 또는 조건부 파괴 |
| `t10`, `t11`, `t12` | 특수 타일 E~G | 레이어별 특성 |
| `t14`, `t15` | 고급 특수 타일 | 특수 능력 |
| `craft_s` | 크래프트 목표 | [수집개수] 필요 |
| `stack_s` | 스택 목표 | [수집개수] 필요 |

### 4.5 속성(Attribute) 정의

| 속성 | 설명 | 난이도 영향 |
|------|------|------------|
| `""` (빈 문자열) | 속성 없음 | - |
| `chain` | 체인으로 묶임 | +3점/개 |
| `frog` | 개구리 장애물 | +4점/개 |
| `link_w`, `link_n` | 연결된 타일 | +2점/개 |

---

## 5. 핵심 기능 상세

### 5.1 난이도 분석기 (Analyzer)

#### 5.1.1 분석 메트릭스

| 메트릭 | 설명 | 가중치 |
|--------|------|--------|
| `total_tiles` | 총 타일 수 | 0.3 |
| `active_layers` | 활성 레이어 수 | 5.0 |
| `chain_count` | 체인 타일 수 | 3.0 |
| `frog_count` | 개구리 장애물 수 | 4.0 |
| `link_count` | 링크 타일 수 | 2.0 |
| `goal_amount` | 목표 수집 총량 | 2.0 |
| `layer_blocking` | 레이어 차단 점수 | 1.5 |

#### 5.1.2 난이도 등급 체계

| 등급 | 점수 범위 | 설명 |
|------|----------|------|
| **S** | 0 ~ 20 | 매우 쉬움 |
| **A** | 21 ~ 40 | 쉬움 |
| **B** | 41 ~ 60 | 보통 |
| **C** | 61 ~ 80 | 어려움 |
| **D** | 81 ~ 100 | 매우 어려움 |

#### 5.1.3 분석 알고리즘

```python
def calculate_difficulty_score(metrics: dict) -> float:
    score = 0
    score += metrics["total_tiles"] * 0.3
    score += metrics["active_layers"] * 5.0
    score += metrics["chain_count"] * 3.0
    score += metrics["frog_count"] * 4.0
    score += metrics["link_count"] * 2.0
    score += metrics["goal_amount"] * 2.0
    score += metrics["layer_blocking"] * 1.5

    # 0-100 범위로 정규화
    return min(100, max(0, score / 3))
```

#### 5.1.4 레이어 차단 점수 계산

```python
def calculate_layer_blocking(level: dict) -> float:
    """상위 레이어가 하위 레이어를 얼마나 가리는지 계산"""
    blocking_score = 0

    for i in range(7, 0, -1):  # layer_7 → layer_1
        upper_tiles = level.get(f"layer_{i}", {}).get("tiles", {})
        lower_tiles = level.get(f"layer_{i-1}", {}).get("tiles", {})

        for pos in upper_tiles.keys():
            if pos in lower_tiles:
                # 상위 레이어일수록 가중치 높음
                blocking_score += (8 - i) * 0.5

    return blocking_score
```

### 5.2 레벨 생성기 (Generator)

#### 5.2.1 생성 파라미터

```python
@dataclass
class GenerationParams:
    target_difficulty: float  # 0.0 ~ 1.0 (목표 난이도)
    grid_size: tuple = (7, 7)  # 그리드 크기
    max_layers: int = 8        # 최대 레이어 수
    tile_types: List[str] = None  # 사용할 타일 타입
    obstacle_types: List[str] = None  # 사용할 장애물
    goals: List[dict] = None  # 목표 설정
```

#### 5.2.2 생성 프로세스

```
1. 기본 구조 생성
   └─ 레이어 프레임워크 초기화

2. 레이어별 타일 배치
   └─ 난이도에 따른 밀도 조정
   └─ 상위 레이어 = 높은 밀도

3. 장애물 배치
   └─ 목표 장애물 수 계산
   └─ 상위 레이어부터 배치

4. 목표 배치
   └─ layer_7 하단에 배치
   └─ craft_s, stack_s

5. 난이도 조정 루프
   └─ 분석 → 비교 → 조정
   └─ 목표 ±5% 이내까지 반복
```

#### 5.2.3 난이도 조정 알고리즘

```python
def adjust_difficulty(level: dict, target: float) -> dict:
    """목표 난이도에 맞게 레벨 조정"""

    target_score = target * 100
    tolerance = 5.0  # ±5점 허용
    max_iterations = 30

    for _ in range(max_iterations):
        current_score = analyze(level).score
        diff = target_score - current_score

        if abs(diff) <= tolerance:
            break

        if diff > 0:
            # 난이도 증가
            level = random.choice([
                add_chain,
                add_obstacle,
                add_tile_to_layer,
            ])(level)
        else:
            # 난이도 감소
            level = random.choice([
                remove_chain,
                remove_obstacle,
                remove_tile_from_layer,
            ])(level)

    return level
```

### 5.3 시뮬레이션 (선택적 기능)

#### 5.3.1 Monte Carlo 시뮬레이션

```python
def simulate_level(level: dict, iterations: int = 500) -> SimulationResult:
    """랜덤/그리디 전략으로 레벨 클리어율 추정"""

    results = []

    for _ in range(iterations):
        game = GameSimulator(level)
        result = game.play(strategy="greedy", max_moves=30)
        results.append(result)

    return SimulationResult(
        clear_rate=sum(r.cleared for r in results) / len(results),
        avg_moves=statistics.mean(r.moves_used for r in results),
        min_moves=min(r.moves_used for r in results),
        max_moves=max(r.moves_used for r in results),
    )
```

#### 5.3.2 시뮬레이션 전략

| 전략 | 설명 | 용도 |
|------|------|------|
| `random` | 완전 랜덤 이동 | 하한선 추정 |
| `greedy` | 최대 매칭 우선 | 일반 플레이어 추정 |
| `optimal` | 최적해 탐색 (MCTS) | 상한선 추정 |

---

## 6. API 명세

### 6.1 난이도 분석 API

**POST `/api/analyze`**

```yaml
Request:
  Content-Type: application/json
  Body:
    level_json: object  # 레벨 JSON 데이터

Response:
  200 OK:
    score: number       # 0-100 난이도 점수
    grade: string       # S/A/B/C/D 등급
    metrics:
      total_tiles: number
      active_layers: number
      chain_count: number
      frog_count: number
      link_count: number
      goal_amount: number
      layer_blocking: number
      tile_types: object
      goals: array
    recommendations: array  # 권장사항 목록
```

**예시:**
```bash
curl -X POST http://localhost:8000/api/analyze \
  -H "Content-Type: application/json" \
  -d '{"level_json": {...}}'
```

### 6.2 레벨 생성 API

**POST `/api/generate`**

```yaml
Request:
  Content-Type: application/json
  Body:
    target_difficulty: number  # 0.0 ~ 1.0
    grid_size: [number, number]  # 기본값: [7, 7]
    max_layers: number  # 기본값: 8
    tile_types: array   # 선택, 기본값: ["t0", "t2", ...]
    obstacle_types: array  # 선택, 기본값: ["chain", "frog"]
    goals: array        # 선택, 기본값: [{"type": "craft_s", "count": 3}]

Response:
  200 OK:
    level_json: object  # 생성된 레벨 JSON
    actual_difficulty: number  # 실제 난이도 (0-1)
    grade: string       # 등급
```

**예시:**
```bash
curl -X POST http://localhost:8000/api/generate \
  -H "Content-Type: application/json" \
  -d '{
    "target_difficulty": 0.6,
    "goals": [
      {"type": "craft_s", "count": 3},
      {"type": "stack_s", "count": 6}
    ]
  }'
```

### 6.3 시뮬레이션 API (선택)

**POST `/api/simulate`**

```yaml
Request:
  Content-Type: application/json
  Body:
    level_json: object
    iterations: number  # 기본값: 500
    strategy: string    # random | greedy | optimal

Response:
  200 OK:
    clear_rate: number      # 클리어율 (0-1)
    avg_moves: number       # 평균 이동 수
    min_moves: number       # 최소 이동 수
    max_moves: number       # 최대 이동 수
    difficulty_estimate: number  # 시뮬레이션 기반 난이도
```

### 6.4 게임부스트 저장 API

**POST `/api/gboost/{board_id}/{level_id}`**

```yaml
Request:
  Content-Type: application/json
  Headers:
    Authorization: Bearer {token}
  Body:
    level_json: object

Response:
  200 OK:
    success: boolean
    saved_at: string  # ISO 8601 timestamp
    message: string

  401 Unauthorized:
    error: "Invalid or missing authentication"

  500 Internal Server Error:
    error: string
```

### 6.5 게임부스트 불러오기 API

**GET `/api/gboost/{board_id}/{level_id}`**

```yaml
Request:
  Headers:
    Authorization: Bearer {token}

Response:
  200 OK:
    level_json: object
    metadata:
      created_at: string
      updated_at: string
      version: string

  404 Not Found:
    error: "Level not found"
```

### 6.6 레벨 목록 조회 API

**GET `/api/gboost/{board_id}`**

```yaml
Request:
  Headers:
    Authorization: Bearer {token}
  Query:
    prefix: string  # 필터링 (기본값: "level_")
    limit: number   # 최대 개수 (기본값: 100)

Response:
  200 OK:
    levels: array
      - id: string
        created_at: string
        difficulty: number  # 캐시된 난이도
```

### 6.7 배치 분석 API

**POST `/api/levels/batch-analyze`**

```yaml
Request:
  Content-Type: application/json
  Body:
    levels: array  # 레벨 JSON 배열
    # 또는
    level_ids: array  # GBoost에서 불러올 레벨 ID 목록
    board_id: string

Response:
  200 OK:
    results: array
      - level_id: string
        score: number
        grade: string
        metrics: object
```

---

## 7. 데이터 모델

### 7.1 Python 데이터 클래스

```python
from dataclasses import dataclass
from typing import Dict, List, Any, Optional
from enum import Enum

class DifficultyGrade(Enum):
    S = "S"  # 매우 쉬움 (0-20)
    A = "A"  # 쉬움 (21-40)
    B = "B"  # 보통 (41-60)
    C = "C"  # 어려움 (61-80)
    D = "D"  # 매우 어려움 (81-100)

@dataclass
class LevelMetrics:
    total_tiles: int
    active_layers: int
    chain_count: int
    frog_count: int
    link_count: int
    goal_amount: int
    layer_blocking: float
    tile_types: Dict[str, int]
    goals: List[Dict[str, Any]]

@dataclass
class DifficultyReport:
    score: float
    grade: DifficultyGrade
    metrics: LevelMetrics
    recommendations: List[str]

@dataclass
class GenerationParams:
    target_difficulty: float
    grid_size: tuple = (7, 7)
    max_layers: int = 8
    tile_types: Optional[List[str]] = None
    obstacle_types: Optional[List[str]] = None
    goals: Optional[List[dict]] = None

@dataclass
class GenerationResult:
    level_json: Dict[str, Any]
    actual_difficulty: float
    grade: DifficultyGrade
    generation_time_ms: int

@dataclass
class SimulationResult:
    clear_rate: float
    avg_moves: float
    min_moves: int
    max_moves: int
    iterations: int
    strategy: str
```

### 7.2 TypeScript 인터페이스 (Frontend)

```typescript
// 난이도 등급
type DifficultyGrade = 'S' | 'A' | 'B' | 'C' | 'D';

// 레벨 메트릭스
interface LevelMetrics {
  total_tiles: number;
  active_layers: number;
  chain_count: number;
  frog_count: number;
  link_count: number;
  goal_amount: number;
  layer_blocking: number;
  tile_types: Record<string, number>;
  goals: Array<{ type: string; count: number }>;
}

// 난이도 분석 결과
interface DifficultyReport {
  score: number;
  grade: DifficultyGrade;
  metrics: LevelMetrics;
  recommendations: string[];
}

// 레벨 생성 파라미터
interface GenerationParams {
  target_difficulty: number;
  grid_size?: [number, number];
  max_layers?: number;
  tile_types?: string[];
  obstacle_types?: string[];
  goals?: Array<{ type: string; count: number }>;
}

// 레벨 JSON 구조
interface LevelJSON {
  layer: number;
  [key: `layer_${number}`]: {
    col: string;
    row: string;
    tiles: Record<string, [string, string, number[]?]>;
    num: string;
  };
}

// 타일 데이터
type TileData = [string, string, number[]?];  // [type, attribute, extra?]
```

---

## 8. 프론트엔드 UI 명세

### 8.1 화면 구성

```
┌─────────────────────────────────────────────────────────────────────┐
│  🎮 타일매치 레벨 디자이너                    [로그인] [설정] [저장]│
├─────────────────────────────────────────────────────────────────────┤
│                                                                     │
│  ┌─────────────────────────┐  ┌───────────────────────────────────┐│
│  │     그리드 에디터        │  │      난이도 분석 결과              ││
│  │                         │  │                                   ││
│  │  Layer: [7 ▼]           │  │  점수: ████████░░░░ 62.5/100      ││
│  │                         │  │  등급: C (어려움)                  ││
│  │  ┌─┬─┬─┬─┬─┬─┬─┐       │  │                                   ││
│  │  │ │🔗│⛓│ │🐸│ │ │       │  │  📊 상세 메트릭스                  ││
│  │  ├─┼─┼─┼─┼─┼─┼─┤       │  │  ├─ 총 타일: 105                   ││
│  │  │ │⛓│ │ │⛓│ │ │       │  │  ├─ 활성 레이어: 5                 ││
│  │  ├─┼─┼─┼─┼─┼─┼─┤       │  │  ├─ 체인: 12                       ││
│  │  │ │ │ │✨│ │ │ │       │  │  ├─ 개구리: 6                      ││
│  │  ├─┼─┼─┼─┼─┼─┼─┤       │  │  └─ 목표량: 15                     ││
│  │  │ │ │ │ │ │ │ │       │  │                                   ││
│  │  └─┴─┴─┴─┴─┴─┴─┘       │  │  💡 권장사항                        ││
│  │                         │  │  • 체인 타일이 다소 많습니다       ││
│  │  도구: [타일▼][속성▼]   │  │                                   ││
│  │  [지우기] [채우기]      │  │  [🔍 분석하기] [🎲 시뮬레이션]      ││
│  └─────────────────────────┘  └───────────────────────────────────┘│
│                                                                     │
│  ┌───────────────────────────────────────────────────────────────┐ │
│  │  🎲 자동 생성기                                                │ │
│  │                                                                │ │
│  │  목표 난이도: [░░░░████░░░░░░] 60%    등급: B (보통)           │ │
│  │                                                                │ │
│  │  설정: [그리드 7x7 ▼] [레이어 8 ▼] [목표 ▼]                    │ │
│  │  타일: [✓t0][✓t2][✓t4][✓t5][✓t6][✓t8][✓t9][✓t10]             │ │
│  │  장애물: [✓chain][✓frog][□link]                               │ │
│  │                                                                │ │
│  │  [🎯 레벨 1개 생성]  [📦 10개 일괄 생성]                        │ │
│  └───────────────────────────────────────────────────────────────┘ │
│                                                                     │
│  ┌───────────────────────────────────────────────────────────────┐ │
│  │  ☁️ 게임부스트 연동                                            │ │
│  │                                                                │ │
│  │  프로젝트: [townpop ▼]  보드: [levels ▼]                       │ │
│  │  레벨 ID: [level_001_______]                                   │ │
│  │                                                                │ │
│  │  [📥 불러오기] [📤 저장하기] [🚀 배포] [🗑️ 삭제]                 │ │
│  │                                                                │ │
│  │  최근 저장: 2025-12-18 15:30:22                                │ │
│  └───────────────────────────────────────────────────────────────┘ │
│                                                                     │
└─────────────────────────────────────────────────────────────────────┘
```

### 8.2 컴포넌트 구조

```
App
├── Header
│   ├── Logo
│   ├── AuthButton
│   └── SettingsButton
├── MainContent
│   ├── GridEditor
│   │   ├── LayerSelector
│   │   ├── TileGrid
│   │   ├── ToolPalette
│   │   └── TileInspector
│   ├── DifficultyPanel
│   │   ├── ScoreDisplay
│   │   ├── GradeDisplay
│   │   ├── MetricsTable
│   │   ├── RecommendationsList
│   │   └── ActionButtons
│   ├── GeneratorPanel
│   │   ├── DifficultySlider
│   │   ├── ConstraintsForm
│   │   ├── TileTypeSelector
│   │   └── GenerateButtons
│   └── GBoostPanel
│       ├── ProjectSelector
│       ├── BoardSelector
│       ├── LevelIdInput
│       ├── ActionButtons
│       └── StatusDisplay
└── Footer
```

### 8.3 주요 인터랙션

| 인터랙션 | 설명 |
|----------|------|
| **레이어 선택** | 드롭다운으로 layer_0 ~ layer_7 전환 |
| **타일 배치** | 클릭으로 타일 배치, 드래그로 연속 배치 |
| **속성 변경** | 우클릭 메뉴 또는 인스펙터에서 속성 변경 |
| **난이도 분석** | 버튼 클릭 시 API 호출, 결과 실시간 표시 |
| **레벨 생성** | 파라미터 설정 후 생성 버튼 클릭 |
| **GBoost 저장** | 레벨 ID 입력 후 저장 버튼 클릭 |

---

## 9. 게임부스트 연동

### 9.1 연동 방식

```
┌─────────────┐      ┌─────────────┐      ┌─────────────┐
│ Level Tool  │ ───▶ │ Proxy API   │ ───▶ │ GBoost      │
│ (Frontend)  │      │ (Backend)   │      │ Server      │
└─────────────┘      └─────────────┘      └─────────────┘
                            │
                     인증/권한 관리
                     요청 변환
                     에러 처리
```

### 9.2 GBoost 클라이언트 구현

```python
# gboost_client.py
import aiohttp
import json
from typing import Optional, Dict, Any

class GBoostClient:
    """게임부스트 서버 연동 클라이언트"""

    def __init__(self, base_url: str, api_key: str, project_id: str):
        self.base_url = base_url
        self.api_key = api_key
        self.project_id = project_id
        self.headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json"
        }

    async def save_level(self, board_id: str, level_id: str,
                         level_json: dict) -> dict:
        """레벨 데이터를 게임부스트에 저장"""
        endpoint = f"{self.base_url}/api/projects/{self.project_id}/boards/{board_id}/arrays"

        payload = {
            "array_id": f"level_{level_id}",
            "data": json.dumps(level_json),
            "metadata": {
                "type": "level",
                "version": "1.0",
                "created_by": "level_tool"
            }
        }

        async with aiohttp.ClientSession() as session:
            async with session.post(endpoint, json=payload,
                                   headers=self.headers) as response:
                result = await response.json()
                return {
                    "success": response.status == 200,
                    "data": result
                }

    async def load_level(self, board_id: str, level_id: str) -> Optional[dict]:
        """레벨 데이터 조회"""
        endpoint = f"{self.base_url}/api/projects/{self.project_id}/boards/{board_id}/arrays/level_{level_id}"

        async with aiohttp.ClientSession() as session:
            async with session.get(endpoint, headers=self.headers) as response:
                if response.status == 200:
                    result = await response.json()
                    return json.loads(result.get("data", "{}"))
                return None

    async def list_levels(self, board_id: str, prefix: str = "level_") -> list:
        """레벨 목록 조회"""
        endpoint = f"{self.base_url}/api/projects/{self.project_id}/boards/{board_id}/arrays"

        async with aiohttp.ClientSession() as session:
            async with session.get(endpoint, headers=self.headers,
                                  params={"prefix": prefix}) as response:
                if response.status == 200:
                    return await response.json()
                return []

    async def delete_level(self, board_id: str, level_id: str) -> bool:
        """레벨 삭제"""
        endpoint = f"{self.base_url}/api/projects/{self.project_id}/boards/{board_id}/arrays/level_{level_id}"

        async with aiohttp.ClientSession() as session:
            async with session.delete(endpoint, headers=self.headers) as response:
                return response.status == 200
```

### 9.3 환경 변수 설정

```bash
# .env
GBOOST_URL=https://api.gboost.example.com
GBOOST_API_KEY=your_api_key_here
GBOOST_PROJECT_ID=townpop
```

### 9.4 인증 흐름

```
1. 사용자 로그인 (Google/GitHub OAuth)
2. 백엔드에서 JWT 토큰 발급
3. 프론트엔드에서 토큰 저장 (HttpOnly Cookie)
4. API 요청 시 토큰 자동 포함
5. 백엔드에서 GBoost API 키로 변환하여 요청
```

---

## 10. 구현 계획

### 10.1 마일스톤

| 단계 | 기간 | 내용 |
|------|------|------|
| **Phase 1** | 1주 | 백엔드 기본 구조 + 난이도 분석기 |
| **Phase 2** | 1주 | 레벨 생성기 + API 완성 |
| **Phase 3** | 1주 | 프론트엔드 기본 UI |
| **Phase 4** | 1주 | 게임부스트 연동 + 배포 |
| **Phase 5** | 선택 | 시뮬레이션 + ML 모델 |

### 10.2 Phase 1 상세 (백엔드 기본 + 분석기)

```
□ 프로젝트 초기화
  ├─ FastAPI 프로젝트 구조 생성
  ├─ 의존성 설정 (requirements.txt)
  └─ Docker 설정

□ 난이도 분석기 구현
  ├─ LevelAnalyzer 클래스
  ├─ 메트릭스 추출 로직
  ├─ 점수 계산 알고리즘
  └─ 권장사항 생성 로직

□ API 엔드포인트
  ├─ POST /api/analyze
  └─ 테스트 케이스 작성
```

### 10.3 Phase 2 상세 (레벨 생성기)

```
□ 레벨 생성기 구현
  ├─ GenerationParams 정의
  ├─ 기본 구조 생성 로직
  ├─ 타일 배치 알고리즘
  ├─ 장애물/목표 배치 로직
  └─ 난이도 조정 루프

□ API 엔드포인트
  ├─ POST /api/generate
  ├─ POST /api/levels/batch-analyze
  └─ 통합 테스트
```

### 10.4 Phase 3 상세 (프론트엔드)

```
□ React 프로젝트 초기화
  ├─ Vite + TypeScript 설정
  ├─ TailwindCSS 설정
  └─ 상태 관리 (Zustand)

□ UI 컴포넌트 구현
  ├─ GridEditor
  ├─ DifficultyPanel
  ├─ GeneratorPanel
  └─ 반응형 레이아웃

□ API 연동
  ├─ axios 클라이언트 설정
  ├─ React Query 캐싱
  └─ 에러 처리
```

### 10.5 Phase 4 상세 (게임부스트 + 배포)

```
□ 게임부스트 연동
  ├─ GBoostClient 구현
  ├─ 인증 시스템
  ├─ GBoostPanel UI
  └─ CRUD 기능 테스트

□ 배포
  ├─ Docker Compose 설정
  ├─ CI/CD 파이프라인
  ├─ 도메인/SSL 설정
  └─ 모니터링 설정
```

---

## 11. 기술 스택

### 11.1 백엔드

| 기술 | 버전 | 용도 |
|------|------|------|
| Python | 3.11+ | 런타임 |
| FastAPI | 0.100+ | 웹 프레임워크 |
| Pydantic | 2.0+ | 데이터 검증 |
| aiohttp | 3.8+ | 비동기 HTTP 클라이언트 |
| uvicorn | 0.23+ | ASGI 서버 |
| pytest | 7.0+ | 테스트 |

### 11.2 프론트엔드

| 기술 | 버전 | 용도 |
|------|------|------|
| React | 18+ | UI 프레임워크 |
| TypeScript | 5.0+ | 타입 시스템 |
| Vite | 5.0+ | 빌드 도구 |
| TailwindCSS | 3.0+ | 스타일링 |
| Zustand | 4.0+ | 상태 관리 |
| React Query | 5.0+ | 서버 상태 관리 |
| axios | 1.5+ | HTTP 클라이언트 |

### 11.3 인프라

| 기술 | 용도 |
|------|------|
| Docker | 컨테이너화 |
| Docker Compose | 로컬 개발 환경 |
| Nginx | 리버스 프록시 |
| PostgreSQL | 메타데이터 저장 (선택) |
| Redis | 캐싱 (선택) |

### 11.4 디렉토리 구조

```
level-designer-tool/
├── backend/
│   ├── app/
│   │   ├── __init__.py
│   │   ├── main.py              # FastAPI 앱 진입점
│   │   ├── config.py            # 환경 설정
│   │   ├── api/
│   │   │   ├── __init__.py
│   │   │   ├── routes/
│   │   │   │   ├── analyze.py   # 분석 API
│   │   │   │   ├── generate.py  # 생성 API
│   │   │   │   └── gboost.py    # GBoost API
│   │   │   └── deps.py          # 의존성
│   │   ├── core/
│   │   │   ├── analyzer.py      # 난이도 분석기
│   │   │   ├── generator.py     # 레벨 생성기
│   │   │   └── simulator.py     # 시뮬레이터 (선택)
│   │   ├── clients/
│   │   │   └── gboost.py        # GBoost 클라이언트
│   │   ├── models/
│   │   │   ├── level.py         # 레벨 데이터 모델
│   │   │   └── schemas.py       # Pydantic 스키마
│   │   └── utils/
│   │       └── helpers.py
│   ├── tests/
│   │   ├── test_analyzer.py
│   │   ├── test_generator.py
│   │   └── test_api.py
│   ├── requirements.txt
│   ├── Dockerfile
│   └── .env.example
│
├── frontend/
│   ├── src/
│   │   ├── main.tsx
│   │   ├── App.tsx
│   │   ├── components/
│   │   │   ├── GridEditor/
│   │   │   │   ├── index.tsx
│   │   │   │   ├── TileGrid.tsx
│   │   │   │   ├── LayerSelector.tsx
│   │   │   │   └── ToolPalette.tsx
│   │   │   ├── DifficultyPanel/
│   │   │   │   ├── index.tsx
│   │   │   │   ├── ScoreDisplay.tsx
│   │   │   │   └── MetricsTable.tsx
│   │   │   ├── GeneratorPanel/
│   │   │   │   ├── index.tsx
│   │   │   │   └── DifficultySlider.tsx
│   │   │   └── GBoostPanel/
│   │   │       ├── index.tsx
│   │   │       └── LevelSelector.tsx
│   │   ├── api/
│   │   │   ├── client.ts
│   │   │   ├── analyze.ts
│   │   │   ├── generate.ts
│   │   │   └── gboost.ts
│   │   ├── stores/
│   │   │   ├── levelStore.ts
│   │   │   └── uiStore.ts
│   │   ├── types/
│   │   │   └── index.ts
│   │   └── utils/
│   │       └── helpers.ts
│   ├── public/
│   ├── package.json
│   ├── tsconfig.json
│   ├── vite.config.ts
│   ├── tailwind.config.js
│   └── Dockerfile
│
├── docker-compose.yml
├── docker-compose.prod.yml
├── .gitignore
└── README.md
```

---

## 부록 A. 샘플 레벨 JSON

```json
{
  "layer": 8,
  "layer_0": {"col": "8", "row": "8", "tiles": {}, "num": "0"},
  "layer_1": {"col": "7", "row": "7", "tiles": {}, "num": "0"},
  "layer_2": {"col": "8", "row": "8", "tiles": {}, "num": "0"},
  "layer_3": {"col": "7", "row": "7", "tiles": {"3_3": ["t0", ""]}, "num": "1"},
  "layer_4": {
    "col": "8", "row": "8",
    "tiles": {
      "3_3": ["t0", ""],
      "4_3": ["t11", ""],
      "3_4": ["t12", ""],
      "4_4": ["t0", ""]
    },
    "num": "4"
  },
  "layer_5": {
    "col": "7", "row": "7",
    "tiles": {
      "0_0": ["t8", ""], "1_0": ["t2", "link_w"], "2_0": ["t0", ""],
      "4_0": ["t0", ""], "5_0": ["t0", ""], "6_0": ["t0", ""],
      "0_1": ["t0", ""], "2_1": ["t0", ""], "4_1": ["t0", ""], "6_1": ["t0", ""],
      "0_2": ["t0", ""], "1_2": ["t0", ""], "2_2": ["t0", "chain"],
      "4_2": ["t0", ""], "5_2": ["t0", ""], "6_2": ["t0", "chain"],
      "0_4": ["t0", ""], "1_4": ["t0", ""], "2_4": ["t0", ""],
      "4_4": ["t0", ""], "5_4": ["t0", ""], "6_4": ["t0", ""],
      "0_5": ["t0", ""], "2_5": ["t0", ""], "4_5": ["t10", ""], "6_5": ["t0", ""],
      "0_6": ["t0", ""], "1_6": ["t0", ""], "2_6": ["t0", "chain"],
      "4_6": ["t14", "link_n"], "5_6": ["t0", ""], "6_6": ["t0", "chain"]
    },
    "num": "32"
  },
  "layer_6": {
    "col": "8", "row": "8",
    "tiles": {
      "1_1": ["t6", ""], "2_1": ["t2", "chain"], "5_1": ["t0", ""], "6_1": ["t0", "chain"],
      "1_2": ["t0", "chain"], "2_2": ["t0", ""], "5_2": ["t0", "chain"], "6_2": ["t0", ""],
      "1_5": ["t0", ""], "2_5": ["t0", "chain"], "5_5": ["t14", ""], "6_5": ["t9", "chain"],
      "1_6": ["t0", "chain"], "2_6": ["t0", ""], "5_6": ["t0", "chain"], "6_6": ["t0", ""]
    },
    "num": "16"
  },
  "layer_7": {
    "col": "7", "row": "7",
    "tiles": {
      "0_0": ["t4", ""], "1_0": ["t0", ""], "2_0": ["t0", "frog"],
      "3_0": ["t5", ""], "4_0": ["t2", ""], "5_0": ["t8", ""], "6_0": ["t8", ""],
      "0_1": ["t9", ""], "1_1": ["t14", ""], "2_1": ["t0", "frog"],
      "3_1": ["t5", ""], "4_1": ["t0", ""], "5_1": ["t0", "frog"], "6_1": ["t8", ""],
      "0_2": ["t9", ""], "1_2": ["t9", ""], "2_2": ["t10", ""],
      "3_2": ["t10", ""], "4_2": ["t10", ""], "6_2": ["t8", ""],
      "0_3": ["t0", ""], "2_3": ["t5", ""], "3_3": ["t6", ""],
      "4_3": ["t14", ""], "5_3": ["t0", "frog"], "6_3": ["t8", ""],
      "0_4": ["t0", ""], "1_4": ["t0", "frog"], "2_4": ["t0", ""],
      "3_4": ["t14", ""], "4_4": ["t0", ""], "5_4": ["t0", ""],
      "0_5": ["t0", ""], "1_5": ["t15", ""], "2_5": ["t0", ""],
      "3_5": ["t0", ""], "5_5": ["t0", ""],
      "3_6": ["craft_s", "", [3]],
      "4_6": ["craft_s", "", [6]],
      "6_6": ["stack_s", "", [6]]
    },
    "num": "52"
  }
}
```

---

## 부록 B. 분석 결과 예시

```json
{
  "score": 62.5,
  "grade": "C",
  "metrics": {
    "total_tiles": 105,
    "active_layers": 5,
    "chain_count": 12,
    "frog_count": 6,
    "link_count": 2,
    "goal_amount": 15,
    "layer_blocking": 8.5,
    "tile_types": {
      "t0": 45,
      "t2": 5,
      "t4": 1,
      "t5": 3,
      "t6": 2,
      "t8": 8,
      "t9": 5,
      "t10": 4,
      "t11": 1,
      "t12": 1,
      "t14": 5,
      "t15": 1,
      "craft_s": 2,
      "stack_s": 1
    },
    "goals": [
      {"type": "craft_s", "count": 3},
      {"type": "craft_s", "count": 6},
      {"type": "stack_s", "count": 6}
    ]
  },
  "recommendations": [
    "체인 타일이 많습니다. 10-12개로 줄이면 적절합니다.",
    "개구리 장애물이 6개로 상당히 많습니다.",
    "목표 수집량(15)이 높습니다. 이동 횟수와 균형을 확인하세요."
  ]
}
```

---

**문서 끝**

> **참고**: 이 문서는 초기 명세서이며, 개발 진행에 따라 업데이트될 수 있습니다.
