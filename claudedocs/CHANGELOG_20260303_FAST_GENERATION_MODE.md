# Fast Generation Mode (Ultra-Fast Level Generation)

**Date**: 2026-03-03
**Version**: v4 (독 용량 검증 추가)

**Files Modified**:
- `backend/app/models/schemas.py`
- `backend/app/models/level.py`
- `backend/app/models/bot_profile.py` (v3 추가)
- `backend/app/core/generator.py`
- `backend/app/core/bot_simulator.py` (v3 추가)
- `backend/app/api/routes/generate.py`
- `backend/app/api/routes/analyze.py`
- `frontend/src/api/analyze.ts`
- `frontend/src/types/production.ts`
- `frontend/src/storage/productionStorage.ts`
- `frontend/src/components/ProductionDashboard/index.tsx`
- `frontend/src/components/ProductionDashboard/BatchVerifyPanel.tsx` (신규)

---

## 개요

레벨 생성 및 검증 속도를 대폭 향상시키는 "빠른 생성 모드" 구현.

| 항목 | Before | After | 개선 |
|------|--------|-------|------|
| 레벨 생성 | 30초/레벨 | 100ms/레벨 | **300x** |
| 배치 검증 | 3초/4레벨 | 0.9초/4레벨 | **3.4x** |

---

## v1: 빠른 생성 모드

### 1. 시뮬레이션 기본값 변경
```python
# schemas.py - ValidatedGenerateRequest
simulation_iterations: int = Field(default=0, ...)  # 기존 30 → 0
```

### 2. 데드락 검증 스킵 옵션 추가
```python
# schemas.py - ValidatedGenerateRequest
skip_deadlock_check: bool = Field(default=True, ...)

# generator.py - generate()
if not params.skip_deadlock_check:
    level, deadlock_ok = self._ensure_no_deadlock(level, max_attempts=10)
else:
    logger.info("[generate] Skipping deadlock check (fast generation mode)")
```

### 3. 배치 검증 API 추가
```
POST /api/analyze/batch-verify

Request:
{
  "levels": [
    {"level_json": {...}, "level_id": "level_1", "target_difficulty": 0.1},
    ...
  ],
  "iterations": 20,
  "tolerance": 15.0,
  "use_core_bots_only": true
}

Response:
{
  "results": [{
    "level_id": "level_1",
    "passed": true,
    "bot_clear_rates": {"casual": 1.0, "average": 1.0, "expert": 1.0},
    "target_clear_rates": {...},
    "match_score": 97.33,
    "issues": []
  }],
  "total_levels": 10,
  "passed_count": 8,
  "failed_count": 2,
  "pass_rate": 0.8,
  "execution_time_ms": 5000
}
```

### 4. 프론트엔드 UI
- ProductionDashboard에 "검증" 탭 추가
- `BatchVerifyPanel` 컴포넌트: 미검증 레벨 일괄 검증

---

## v2: 구조적 데드락 방지

### Unknown 비율 제한
```python
# leveling_config.py
return 0.25  # 최대 25% (기존 60%에서 감소)
```
- 높은 unknown 비율은 봇 클리어율 급락 유발

### 최소 데드락 체크
```python
# generator.py
if params.skip_deadlock_check:
    level = self._ensure_tile_divisibility(level)
    level, _ = self._ensure_no_deadlock(level, max_attempts=1)  # 1회만 체크
```
- `skip_deadlock_check=true`여도 1회 빠른 체크 수행
- 구조적 데드락 방지 (0% 클리어 레벨 제거)
- 생성 시간: ~600ms/레벨 (여전히 빠름)

---

## v3: 봇 시뮬레이션 최적화

### 1. 조기 종료 (Early Termination)
```python
# bot_simulator.py
EARLY_TERM_MIN_ITERATIONS = 5   # 최소 5회 반복 후 판단
EARLY_TERM_CONFIDENCE_THRESHOLD = 0.90  # 90% 신뢰도

def _should_terminate_early(self, results, target_iterations):
    # 100% 또는 0% 클리어율에서 자동 종료
    if current_rate == 1.0 or current_rate == 0.0:
        return True
    # 극단값(90%+ 또는 10%-)에서도 종료
    if current_rate >= 0.90 or current_rate <= 0.10:
        return True
```

### 2. 빠른 검증 프로필 (Fast Mode)
```python
# bot_profile.py
FAST_VERIFICATION_PROFILES = {
    BotType.CASUAL: BotProfile(
        lookahead_depth=0,  # 기존 1 → 0
        ...
    ),
    BotType.AVERAGE: BotProfile(
        lookahead_depth=1,  # 기존 2 → 1
        ...
    ),
    BotType.EXPERT: BotProfile(
        lookahead_depth=2,  # 기존 5 → 2
        ...
    ),
}

def get_profile(bot_type, fast_mode=False):
    if fast_mode and bot_type in FAST_VERIFICATION_PROFILES:
        return FAST_VERIFICATION_PROFILES[bot_type]
    return PREDEFINED_PROFILES[bot_type]
```

### 3. 배치 검증 API 신규 옵션
```python
# schemas.py
class BatchVerifyRequest(BaseModel):
    levels: List[BatchVerifyLevelItem]
    iterations: int = 20
    tolerance: float = 15.0
    use_core_bots_only: bool = True
    fast_mode: bool = True           # 신규: 빠른 프로필 사용
    early_termination: bool = True   # 신규: 조기 종료 활성화
```

### 4. assess_difficulty 최적화 옵션
```python
# bot_simulator.py
def assess_difficulty(
    self,
    level_json,
    team=None,
    max_moves=30,
    parallel=True,
    seed=None,
    fast_mode=False,        # 신규
    early_termination=False # 신규
):
```

---

## 성능 비교

### 레벨 생성 (v1)
| 난이도 | Before (ms) | After (ms) | 개선 |
|--------|-------------|------------|------|
| 0.1 (S) | 3,147 | ~100 | 31x |
| 0.3 (A) | 16,354 | ~100 | 164x |
| 0.5 (B) | 29,684 | ~100 | 297x |
| 0.7 (D) | 29,893 | ~600 | 50x |

### 배치 검증 (v3)
| 설정 | 실행 시간 (4레벨) | 개선율 |
|------|------------------|--------|
| 최적화 OFF | 3,114ms | 기준 |
| fast_mode만 | 3,053ms | 1.0x |
| **모든 최적화** | **908ms** | **3.4x** |

---

## 워크플로우

```
┌─────────────────────────────────────┐
│  1. 빠른 생성 (기본값)               │
│     - simulation_iterations=0       │
│     - skip_deadlock_check=true      │
│     → 평균 100-600ms/레벨           │
└─────────────────────────────────────┘
                 ↓
┌─────────────────────────────────────┐
│  2. 사후 배치 검증 (검증 탭)         │
│     - POST /api/analyze/batch-verify│
│     - fast_mode=true                │
│     - early_termination=true        │
│     → 3.4배 빠른 검증               │
└─────────────────────────────────────┘
                 ↓
┌─────────────────────────────────────┐
│  3. 실패 레벨만 재생성               │
│     - 검증 실패 레벨 목록 확인       │
│     - 해당 레벨만 재생성             │
└─────────────────────────────────────┘
```

---

## 권장 설정

### 빠른 레벨 생성
```json
{
  "target_difficulty": 0.5,
  "level_number": 100,
  "skip_deadlock_check": true,
  "simulation_iterations": 0
}
```

### 배치 검증 (권장)
```json
{
  "iterations": 20,
  "tolerance": 15.0,
  "use_core_bots_only": true,
  "fast_mode": true,
  "early_termination": true
}
```

### 정밀 검증 (필요시)
```json
{
  "iterations": 50,
  "tolerance": 10.0,
  "use_core_bots_only": false,
  "fast_mode": false,
  "early_termination": false
}
```

---

## 주의 사항

1. **빠른 생성 모드 레벨도 최소 검증 포함**
   - 구조적 데드락은 v2에서 방지됨
   - 목표 클리어율 매칭은 배치 검증 필요

2. **조기 종료 시 iterations 수 변동**
   - 100%/0% 클리어 시 조기 종료로 실제 iterations < 설정값
   - 결과의 `iterations` 필드에서 실제 실행 횟수 확인 가능

3. **fast_mode 정확도**
   - lookahead 감소로 약간의 정확도 저하 가능
   - 중요 레벨은 `fast_mode=false`로 정밀 검증 권장

---

## v4: 독 용량 검증 (Dock Capacity Validation)

### 문제 상황
`useTileCount=11 + unlockTile=2` 조합의 레벨이 0% 클리어율 발생
- 사용 가능 독 슬롯: 7 - 2 = 5개
- 타일 종류: 11종
- 5개 슬롯으로 11종 타일 → **즉각 데드락**

### 원인 분석
기존 `_quick_deadlock_check`는 3회 시뮬레이션만 수행:
- optimal 봇으로 3회 시뮬레이션
- 1/3 이상 클리어 시 통과
- **하지만** useTileCount + unlockTile 호환성은 체크 안 함

### 해결책: `_validate_dock_tile_compatibility()`
```python
# generator.py
def _validate_dock_tile_compatibility(self, level: Dict[str, Any]) -> Dict[str, Any]:
    """
    Validate useTileCount is compatible with unlockTile (dock capacity).

    규칙: useTileCount <= (7 - unlockTile) + 2
    - 사용 가능 독 슬롯: 7 - unlockTile
    - 안전 여유: +2 (매칭으로 슬롯 회수 가능)
    - 예: unlockTile=2 → 독 5개 → 최대 7종 타일
    """
    unlock_tile = level.get("unlockTile", level.get("xUnlockTile", 0))
    use_tile_count = level.get("useTileCount", 6)

    available_dock = 7 - unlock_tile
    safe_max_tile_count = available_dock + 2

    if use_tile_count > safe_max_tile_count:
        # 방법 1: useTileCount 감소
        new_tile_count = safe_max_tile_count

        # 방법 2: 최소 5종 보장, unlockTile 감소로 보완
        if new_tile_count < 5:
            while new_tile_count < 5 and unlock_tile > 0:
                unlock_tile -= 1
                available_dock = 7 - unlock_tile
                safe_max_tile_count = available_dock + 2
                new_tile_count = min(original_tile_count, safe_max_tile_count)
            level["unlockTile"] = unlock_tile

        level["useTileCount"] = new_tile_count
    return level
```

### 적용 시점
```python
# generator.py - generate()
def generate(self, params):
    level = self._create_base_structure(...)

    # v4: 독 용량 검증 (기존 검증 전에 실행)
    level = self._validate_dock_tile_compatibility(level)

    # 기존 검증들...
    level = self._ensure_key_tile_exists(level)
    level = self._ensure_tile_divisibility(level)
```

### 검증 규칙 요약

| unlockTile | 사용 가능 독 | 최대 타일 종류 |
|------------|-------------|---------------|
| 0 | 7 | 9 |
| 1 | 6 | 8 |
| 2 | 5 | 7 |
| 3 | 4 | 6 |
| 4 | 3 | 5 |

### 효과
- **0% 클리어율 레벨 원천 방지**
- 재생성 레벨에서도 데드락 발생 안 함
- 빠른 생성 모드의 신뢰성 향상
