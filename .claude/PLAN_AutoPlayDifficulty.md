# Auto-Play Difficulty Measurement System - Technical Specification

## Overview
봇 시뮬레이션을 **N회 반복 실행**하여 레벨의 실제 난이도를 통계적으로 측정하는 시스템.

현재 시각화 시뮬레이션(`/api/simulate/visual`)은 **봇당 1회**만 실행하지만,
AutoPlay 분석은 **봇당 N회(기본 100회)** 실행하여 통계적으로 유의미한 클리어율을 계산.

---

## Current System Analysis

### Existing Components

| Component | Status | Description |
|-----------|--------|-------------|
| `BotSimulator.simulate_with_profile()` | ✅ | 반복 시뮬레이션 지원 (iterations 파라미터) |
| `BotProfile` (5종) | ✅ | NOVICE/CASUAL/AVERAGE/EXPERT/OPTIMAL |
| `BotTeam` | ✅ | 봇 그룹화 및 iterations_per_bot 설정 |
| `/api/simulate/visual` | ✅ | 시각화용 (봇당 1회) |

### Bot Profile Target Clear Rates

```
┌─────────┬─────────────┬────────────────────────────────────────┐
│ Profile │ Target Rate │ Characteristics                        │
├─────────┼─────────────┼────────────────────────────────────────┤
│ NOVICE  │ 40%         │ 랜덤 선택, 높은 실수율 (0.4)            │
│ CASUAL  │ 60%         │ 기본 전략, 가끔 실수 (0.2)              │
│ AVERAGE │ 75%         │ 그리디 전략, 적은 실수 (0.1) - 주타겟   │
│ EXPERT  │ 90%         │ 최적화 전략, 매우 적은 실수 (0.03)      │
│ OPTIMAL │ 98%         │ 완벽 플레이 (실수율 0)                  │
└─────────┴─────────────┴────────────────────────────────────────┘
```

### Bot Weights for Difficulty Calculation
```python
NOVICE:  0.5  (낮은 가중치 - 타겟 유저 아님)
CASUAL:  1.0  (주요 타겟)
AVERAGE: 1.5  (가장 중요)
EXPERT:  0.8  (중간)
OPTIMAL: 0.3  (낮은 가중치 - 비현실적)
```

---

## Feature Request: Multiple Iterations per Bot

### Current Problem
- `/api/simulate/visual`: 봇당 1회 실행 → 시각화용
- 통계적 난이도 측정 불가 (1회는 우연에 좌우됨)

### Solution: AutoPlay Analysis Endpoint

**새 엔드포인트**: `POST /api/analyze/autoplay`

봇당 N회(기본 100회) 반복 실행하여:
1. 클리어율 계산
2. 평균/최소/최대 무브 수
3. 난이도 점수 산출
4. 정적 분석과 비교

---

## API Specification

### Request Schema

```python
class AutoPlayRequest(BaseModel):
    """자동 플레이 난이도 분석 요청"""
    level_json: Dict[str, Any]           # 레벨 JSON
    iterations: int = 100                # 봇당 반복 횟수 (10~1000)
    bot_profiles: Optional[List[str]]    # 사용할 봇 (기본: 전체 5종)
    seed: Optional[int] = None           # 재현용 시드

# Example Request
{
    "level_json": { ... },
    "iterations": 100,
    "bot_profiles": ["novice", "casual", "average", "expert", "optimal"],
    "seed": 42
}
```

### Response Schema

```python
class BotClearStats(BaseModel):
    """봇별 시뮬레이션 통계"""
    profile: str                    # "novice" | "casual" | ...
    profile_display: str            # "초보자" | "캐주얼" | ...
    clear_rate: float               # 실제 클리어율 (0.0~1.0)
    target_clear_rate: float        # 목표 클리어율
    avg_moves: float                # 평균 무브 수
    min_moves: int                  # 최소 무브
    max_moves: int                  # 최대 무브
    std_moves: float                # 표준편차
    avg_combo: float                # 평균 콤보
    iterations: int                 # 실행 횟수

class AutoPlayResponse(BaseModel):
    """자동 플레이 분석 결과"""
    # 봇별 통계
    bot_stats: List[BotClearStats]

    # 종합 난이도 지표
    autoplay_score: float           # 0~100 (높을수록 어려움)
    autoplay_grade: str             # S/A/B/C/D

    # 정적 분석 비교
    static_score: float             # 정적 분석 점수
    static_grade: str               # 정적 분석 등급
    score_difference: float         # autoplay - static

    # 밸런스 평가
    balance_status: str             # "balanced" | "too_easy" | "too_hard"
    recommendations: List[str]      # 조정 권장사항

    # 메타데이터
    total_simulations: int          # 전체 시뮬레이션 횟수
    execution_time_ms: int          # 실행 시간
```

### Example Response
```json
{
    "bot_stats": [
        {
            "profile": "novice",
            "profile_display": "초보자",
            "clear_rate": 0.35,
            "target_clear_rate": 0.40,
            "avg_moves": 28.5,
            "min_moves": 18,
            "max_moves": 45,
            "std_moves": 8.2,
            "avg_combo": 1.2,
            "iterations": 100
        }
    ],
    "autoplay_score": 58.0,
    "autoplay_grade": "B",
    "static_score": 52.0,
    "static_grade": "B",
    "score_difference": 6.0,
    "balance_status": "balanced",
    "recommendations": [
        "초보자 클리어율이 목표보다 5% 낮음 - 기믹 감소 검토",
        "전문가 클리어율 적정 범위"
    ],
    "total_simulations": 500,
    "execution_time_ms": 3200
}
```

---

## Difficulty Calculation Algorithm

### Core Logic

```python
def calculate_autoplay_difficulty(bot_stats: List[BotClearStats]) -> float:
    """
    봇 클리어율과 목표율의 차이를 가중 평균하여 난이도 계산.

    - 모든 봇이 목표에 부합: 50점 (균형)
    - 목표보다 낮은 클리어율: 점수 증가 (더 어려움)
    - 목표보다 높은 클리어율: 점수 감소 (더 쉬움)
    """
    BOT_WEIGHTS = {
        "novice": 0.5,
        "casual": 1.0,
        "average": 1.5,  # 가장 중요
        "expert": 0.8,
        "optimal": 0.3,
    }

    TARGET_RATES = {
        "novice": 0.40,
        "casual": 0.60,
        "average": 0.75,
        "expert": 0.90,
        "optimal": 0.98,
    }

    weighted_score = 0.0
    total_weight = 0.0

    for stats in bot_stats:
        weight = BOT_WEIGHTS[stats.profile]
        target = TARGET_RATES[stats.profile]
        gap = target - stats.clear_rate  # 양수 = 더 어려움

        weighted_score += gap * weight * 100
        total_weight += weight

    base_score = 50.0  # 균형 기준점
    adjustment = weighted_score / total_weight if total_weight > 0 else 0

    return max(0, min(100, base_score + adjustment))
```

### Grade Mapping

```python
def score_to_grade(score: float) -> str:
    """점수를 등급으로 변환"""
    if score >= 80: return "D"   # 매우 어려움
    if score >= 65: return "C"   # 어려움
    if score >= 45: return "B"   # 보통 (균형)
    if score >= 30: return "A"   # 쉬움
    return "S"                    # 매우 쉬움
```

### Balance Assessment

```python
def assess_balance(bot_stats: List[BotClearStats]) -> tuple[str, List[str]]:
    """밸런스 상태 및 권장사항 생성"""
    recommendations = []
    issues = {"too_easy": 0, "too_hard": 0}

    for stats in bot_stats:
        target = TARGET_RATES[stats.profile]
        diff = stats.clear_rate - target

        if diff > 0.15:  # 15% 이상 높으면
            issues["too_easy"] += 1
            recommendations.append(
                f"{stats.profile_display} 클리어율 {diff*100:.0f}% 초과 - 난이도 상향 검토"
            )
        elif diff < -0.15:  # 15% 이상 낮으면
            issues["too_hard"] += 1
            recommendations.append(
                f"{stats.profile_display} 클리어율 {abs(diff)*100:.0f}% 미달 - 난이도 하향 검토"
            )

    if issues["too_easy"] >= 3:
        return "too_easy", recommendations
    elif issues["too_hard"] >= 3:
        return "too_hard", recommendations
    elif issues["too_easy"] >= 2 and issues["too_hard"] >= 2:
        return "unbalanced", recommendations
    else:
        return "balanced", recommendations
```

---

## Performance Optimization

### Parallel Execution

```python
from concurrent.futures import ThreadPoolExecutor, as_completed

async def run_autoplay_analysis(
    level_json: Dict,
    iterations: int,
    bot_profiles: List[str],
    seed: Optional[int]
) -> AutoPlayResponse:
    """병렬 실행으로 성능 최적화"""

    simulator = BotSimulator()
    bot_stats = []

    # ThreadPoolExecutor로 봇별 병렬 실행
    with ThreadPoolExecutor(max_workers=5) as executor:
        futures = {}
        for i, profile_name in enumerate(bot_profiles):
            profile = get_profile_by_name(profile_name)
            bot_seed = seed + i if seed else None

            future = executor.submit(
                simulator.simulate_with_profile,
                level_json,
                profile,
                iterations,
                bot_seed
            )
            futures[future] = profile_name

        for future in as_completed(futures):
            profile_name = futures[future]
            result = future.result()
            bot_stats.append(result_to_stats(result, profile_name))

    return calculate_response(bot_stats)
```

### Expected Performance

| Iterations | Bots | Total Runs | Est. Time |
|------------|------|------------|-----------|
| 10 | 5 | 50 | ~0.5s |
| 50 | 5 | 250 | ~2s |
| 100 | 5 | 500 | ~4s |
| 500 | 5 | 2500 | ~15s |
| 1000 | 5 | 5000 | ~30s |

### Caching (Optional)

```python
# 같은 level_json + seed 조합 캐시
CACHE_TTL = 300  # 5분

@cache(ttl=CACHE_TTL)
def get_cached_analysis(level_hash: str, iterations: int, seed: int):
    ...
```

---

## Frontend Integration

### New API Function

```typescript
// frontend/src/api/analyze.ts

export interface AutoPlayRequest {
  level_json: LevelJSON;
  iterations?: number;  // default: 100
  bot_profiles?: string[];
  seed?: number;
}

export interface BotClearStats {
  profile: string;
  profile_display: string;
  clear_rate: number;
  target_clear_rate: number;
  avg_moves: number;
  min_moves: number;
  max_moves: number;
  std_moves: number;
  avg_combo: number;
  iterations: number;
}

export interface AutoPlayResponse {
  bot_stats: BotClearStats[];
  autoplay_score: number;
  autoplay_grade: string;
  static_score: number;
  static_grade: string;
  score_difference: number;
  balance_status: 'balanced' | 'too_easy' | 'too_hard' | 'unbalanced';
  recommendations: string[];
  total_simulations: number;
  execution_time_ms: number;
}

export async function analyzeAutoPlay(
  request: AutoPlayRequest
): Promise<AutoPlayResponse> {
  const response = await fetch('/api/analyze/autoplay', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      level_json: request.level_json,
      iterations: request.iterations ?? 100,
      bot_profiles: request.bot_profiles,
      seed: request.seed,
    }),
  });

  if (!response.ok) {
    throw new Error(\`AutoPlay analysis failed: \${response.statusText}\`);
  }

  return response.json();
}
```

### UI Component: AutoPlayPanel

**Location**: `frontend/src/components/AutoPlayPanel/`

```
┌────────────────────────────────────────────────────────────────┐
│ 🎮 자동 플레이 난이도 분석                                       │
├────────────────────────────────────────────────────────────────┤
│ 반복 횟수: [100 ▼]  봇 선택: [✓전체 ▼]  [🚀 분석 시작]          │
├────────────────────────────────────────────────────────────────┤
│ 📊 봇별 클리어율 (100회 시뮬레이션)                              │
│                                                                │
│ 초보자   ███████░░░░░░░░░░░░░  35% │ 목표 40% │ -5%  ⚠️       │
│ 캐주얼   ██████████░░░░░░░░░░  52% │ 목표 60% │ -8%  ⚠️       │
│ 평균     ████████████████░░░░  78% │ 목표 75% │ +3%  ✓        │
│ 전문가   ██████████████████░░  88% │ 목표 90% │ -2%  ✓        │
│ 최적     ███████████████████░  95% │ 목표 98% │ -3%  ✓        │
├────────────────────────────────────────────────────────────────┤
│ 🎯 난이도 분석 결과                                             │
│                                                                │
│ ┌──────────────┬──────────────┬──────────────┐                │
│ │ 자동플레이    │ 정적분석     │ 차이         │                │
│ ├──────────────┼──────────────┼──────────────┤                │
│ │ 58점 (B등급) │ 52점 (B등급) │ +6점         │                │
│ └──────────────┴──────────────┴──────────────┘                │
│                                                                │
│ 상태: ⚖️ 약간 어려움 (실제 플레이가 예상보다 어려움)             │
├────────────────────────────────────────────────────────────────┤
│ 💡 권장 사항                                                    │
│ • 초보자/캐주얼 클리어율이 목표 대비 낮음                        │
│ • 초반 레이어 타일 수 감소 또는 기믹 완화 검토                    │
│ • 전문가급은 적정 범위 내 - 상위 난이도는 유지                    │
└────────────────────────────────────────────────────────────────┘
```

### Integration with DifficultyPanel

기존 `DifficultyPanel`에 AutoPlay 분석 버튼 추가:

```typescript
// DifficultyPanel/index.tsx

export function DifficultyPanel({ levelJson, ... }) {
  const [autoPlayResult, setAutoPlayResult] = useState<AutoPlayResponse | null>(null);
  const [isAnalyzing, setIsAnalyzing] = useState(false);

  const handleAutoPlayAnalysis = async () => {
    setIsAnalyzing(true);
    try {
      const result = await analyzeAutoPlay({ level_json: levelJson, iterations: 100 });
      setAutoPlayResult(result);
    } finally {
      setIsAnalyzing(false);
    }
  };

  return (
    <div>
      {/* 기존 정적 분석 결과 */}
      <StaticAnalysisSection ... />

      {/* 자동 플레이 분석 섹션 */}
      <AutoPlaySection
        result={autoPlayResult}
        isLoading={isAnalyzing}
        onAnalyze={handleAutoPlayAnalysis}
      />
    </div>
  );
}
```

---

## Implementation Plan

### Phase 1: Backend (Priority: High)

| Step | Task | Files | Est. |
|------|------|-------|------|
| 1.1 | Schema 추가 | `models/schemas.py` | 20min |
| 1.2 | Endpoint 구현 | `api/routes/analyze.py` | 1hr |
| 1.3 | 난이도 계산 로직 | `core/difficulty.py` | 30min |
| 1.4 | 테스트 | `tests/test_autoplay.py` | 30min |

### Phase 2: Frontend (Priority: Medium)

| Step | Task | Files | Est. |
|------|------|-------|------|
| 2.1 | API 클라이언트 | `api/analyze.ts` | 15min |
| 2.2 | Types 추가 | `types/index.ts` | 10min |
| 2.3 | AutoPlayPanel 컴포넌트 | `components/AutoPlayPanel/` | 1.5hr |
| 2.4 | DifficultyPanel 통합 | `components/DifficultyPanel/` | 30min |

### Phase 3: Optimization (Priority: Low)

| Step | Task | Est. |
|------|------|------|
| 3.1 | 캐싱 구현 | 30min |
| 3.2 | Progress SSE (실시간 진행률) | 1hr |
| 3.3 | 성능 튜닝 | 30min |

**Total Estimated Time: ~6-7 hours**

---

## Questions for Clarification

1. **반복 횟수 기본값**: 100회 적절한가? (더 높으면 정확, 더 낮으면 빠름)
2. **실시간 진행률**: SSE로 실시간 업데이트 필요한가? (500회 이상일 때 유용)
3. **결과 캐싱**: 같은 레벨의 반복 분석 시 캐싱 필요한가?
4. **병렬 처리**: ThreadPoolExecutor vs AsyncIO - 선호하는 방식?
5. **UI 배치**: DifficultyPanel 내 통합 vs 별도 탭?

---

## Gimmick Implementation Status

| Gimmick | Backend | Frontend | AutoPlay |
|---------|---------|----------|----------|
| Ice | ✅ | ✅ | ✅ 지원 |
| Chain | ✅ | ✅ | ✅ 지원 |
| Grass | ✅ | ✅ | ✅ 지원 |
| Link | ✅ | ✅ | ✅ 지원 |
| Frog | ✅ | ✅ | ✅ 지원 |
| Bomb | ✅ | ✅ | ✅ 지원 |
| Curtain | ✅ | ✅ | ✅ 지원 |
| Stack | ✅ | ✅ | ✅ 지원 |
| Craft | ✅ | ✅ | ✅ 지원 |
| Teleport | ✅ | ✅ | ✅ 지원 |

모든 기믹이 구현되어 있어 AutoPlay 분석에서 정확한 시뮬레이션 가능.
