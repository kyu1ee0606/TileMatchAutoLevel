# Tile Type System Refactoring Design

> **Status**: ✅ **IMPLEMENTED** (2026-02-23)

## Changelog

### v2.0.0 (2026-02-23) - 타일 종류 수 확장

**배경**: 다른 타일 매칭 게임 분석 결과, 난이도에 따라 타일 종류 수가 증감하는 패턴 확인
- 보통 난이도: 10종류
- 어려움: 11종류
- 매우 어려움: 12종류

**변경 파일**:
- `backend/app/core/generator.py`
- `backend/app/models/leveling_config.py`

---

## 1. Overview

### 1.1 Before (v1)
- **기본 타일 종류**: 5종류 (t1-t5)
- **최대 타일 종류**: 15종류 (t1-t15)
- **레벨별 범위**: 4-8종류

### 1.2 After (v2) ✅
- **기본 타일 종류**: 10종류 (보통 난이도 기준)
- **쉬움**: 8-9종류
- **어려움**: 11종류
- **매우 어려움**: 12종류
- **튜토리얼 (1-10레벨)**: 특별 규칙 유지 (4-5종류)

---

## 2. Design Specification

### 2.1 New Tile Type Count by Difficulty

| 난이도 등급 | 레벨 구간 | 현재 | 변경 | 비고 |
|-------------|-----------|------|------|------|
| Tutorial | 1-10 | 4 | 4-5 | 특별 규칙 유지 |
| S (매우 쉬움) | 11-225 | 4-5 | 8 | +3-4 증가 |
| A (쉬움) | 226-600 | 5-6 | 9 | +3-4 증가 |
| B (보통) | 601-1125 | 6 | 10 | 기준선 (baseline) |
| C (어려움) | 1126-1425 | 7 | 11 | +1 증가 |
| D (매우 어려움) | 1426-1500 | 8 | 12 | +1 증가 |
| Master | 1501+ | 8 | 12 | 최대값 유지 |

### 2.2 Difficulty Scaling Formula

```python
def calculate_tile_type_count_v2(level_number: int, difficulty: float) -> int:
    """
    새로운 타일 종류 수 계산 공식

    Args:
        level_number: 레벨 번호 (1-based)
        difficulty: 난이도 (0.0-1.0)

    Returns:
        타일 종류 수 (4-12)
    """
    # 튜토리얼 레벨 (1-10): 특별 규칙
    if level_number <= 10:
        return 4 + (level_number // 4)  # 4-5종류

    # 기본 10종류 + 난이도 기반 조정
    # difficulty 0.0 → -2 (8종류)
    # difficulty 0.5 → 0 (10종류)
    # difficulty 1.0 → +2 (12종류)
    base = 10
    adjustment = int((difficulty - 0.5) * 4)  # -2 ~ +2

    return max(8, min(12, base + adjustment))
```

---

## 3. Files to Modify

### 3.1 Primary Changes

#### File 1: `backend/app/core/generator.py`

**Location**: Lines 375-377
```python
# BEFORE
DEFAULT_TILE_TYPES = ["t1", "t2", "t3", "t4", "t5"]

# AFTER
DEFAULT_TILE_TYPES = ["t1", "t2", "t3", "t4", "t5", "t6", "t7", "t8", "t9", "t10"]
```

**Location**: Lines 160-249 (`get_gboost_style_layer_config`)
```python
# BEFORE (example for level 601-1125)
"tile_types": 6,  # 6종류 (B등급)

# AFTER
"tile_types": 10,  # 10종류 (B등급 - 기준선)
```

**Full changes for `get_gboost_style_layer_config`:**
```python
def get_gboost_style_layer_config(level_number: int) -> Dict[str, Any]:
    if level_number <= 10:
        return {
            # ... other fields
            "tile_types": 4,  # 튜토리얼 유지
        }
    elif level_number <= 30:
        return {
            # ... other fields
            "tile_types": 5,  # 초반 유지 (점진적 증가)
        }
    elif level_number <= 60:
        return {
            # ... other fields
            "tile_types": 7,  # 5 → 7 증가
        }
    elif level_number <= 100:
        return {
            # ... other fields
            "tile_types": 8,  # 5 → 8 증가
        }
    elif level_number <= 225:
        return {
            # ... other fields
            "tile_types": 8,  # 5 → 8 증가 (S등급)
        }
    elif level_number <= 600:
        return {
            # ... other fields
            "tile_types": 9,  # 6 → 9 증가 (A등급)
        }
    elif level_number <= 1125:
        return {
            # ... other fields
            "tile_types": 10,  # 6 → 10 증가 (B등급 기준선)
        }
    elif level_number <= 1500:
        return {
            # ... other fields
            "tile_types": 11,  # 7 → 11 증가 (C/D등급)
        }
    else:
        return {
            # ... other fields
            "tile_types": 12,  # 8 → 12 증가 (Master)
        }
```

**Location**: Lines 284-335 (`get_tile_types_for_level`)
```python
def get_tile_types_for_level(level_number: int) -> List[str]:
    """
    레벨에 맞는 타일 타입 리스트 반환

    변경사항:
    - 기본 10종류 (t1-t10)
    - 난이도에 따라 8-12종류 사용
    """
    config = get_gboost_style_layer_config(level_number)
    tile_count = config.get("tile_types", 10)

    # 10레벨 주기 내 위치 (0~9)
    position_in_10 = (level_number - 1) % 10
    lowest_positions = _get_lowest_positions()

    if position_in_10 in lowest_positions:
        # 쉬운 레벨: 실제 타일 타입 사용 (t1-t{tile_count})
        return [f"t{i}" for i in range(1, tile_count + 1)]
    else:
        # 일반 레벨: t0 사용 (클라이언트에서 랜덤 타일로 변환)
        return ["t0"]
```

---

#### File 2: `backend/app/models/leveling_config.py`

**Location**: Lines 303-405 (`PHASE_CONFIGS`)

```python
PHASE_CONFIGS: Dict[LevelPhase, PhaseConfig] = {
    LevelPhase.TUTORIAL: PhaseConfig(
        phase=LevelPhase.TUTORIAL,
        level_range=(1, 225),
        min_tile_types=4,      # 유지
        max_tile_types=8,      # 5 → 8 (S등급 상한)
        # ... other fields
    ),

    LevelPhase.BASIC: PhaseConfig(
        phase=LevelPhase.BASIC,
        level_range=(226, 600),
        min_tile_types=8,      # 5 → 8
        max_tile_types=9,      # 6 → 9 (A등급)
        # ... other fields
    ),

    LevelPhase.INTERMEDIATE: PhaseConfig(
        phase=LevelPhase.INTERMEDIATE,
        level_range=(601, 1125),
        min_tile_types=9,      # 5 → 9
        max_tile_types=10,     # 7 → 10 (B등급 기준선)
        # ... other fields
    ),

    LevelPhase.ADVANCED: PhaseConfig(
        phase=LevelPhase.ADVANCED,
        level_range=(1126, 1425),
        min_tile_types=10,     # 6 → 10
        max_tile_types=11,     # 8 → 11 (C등급)
        # ... other fields
    ),

    LevelPhase.EXPERT: PhaseConfig(
        phase=LevelPhase.EXPERT,
        level_range=(1426, 1500),
        min_tile_types=11,     # 6 → 11
        max_tile_types=12,     # 8 → 12 (D등급)
        # ... other fields
    ),

    LevelPhase.MASTER: PhaseConfig(
        phase=LevelPhase.MASTER,
        level_range=(1501, 9999),
        min_tile_types=11,     # 6 → 11
        max_tile_types=12,     # 8 → 12 (Master)
        # ... other fields
    ),
}
```

---

## 4. Implementation Checklist

### Phase 1: Core Changes
- [ ] `generator.py`: Update `DEFAULT_TILE_TYPES` (line 375)
- [ ] `generator.py`: Update `get_gboost_style_layer_config()` (lines 160-249)
- [ ] `generator.py`: Update `get_tile_types_for_level()` (lines 284-335)

### Phase 2: Config Changes
- [ ] `leveling_config.py`: Update `PHASE_CONFIGS` tile type ranges (lines 303-405)
- [ ] `leveling_config.py`: Update `calculate_tile_types_count()` if needed (lines 626-637)

### Phase 3: Validation
- [ ] Run existing tests: `pytest backend/tests/`
- [ ] Test level generation API: `/api/generate`
- [ ] Test level analysis API: `/api/analyze`
- [ ] Verify with Playwright: Web UI level generation

---

## 5. Code Snippets for Implementation

### 5.1 generator.py - DEFAULT_TILE_TYPES

```python
# Line 375 - Replace
DEFAULT_TILE_TYPES = ["t1", "t2", "t3", "t4", "t5", "t6", "t7", "t8", "t9", "t10"]
```

### 5.2 generator.py - get_gboost_style_layer_config

```python
def get_gboost_style_layer_config(level_number: int) -> Dict[str, Any]:
    """
    Get recommended layer configuration based on level number.

    [v2] 타일 종류 수 업데이트:
    - 보통 난이도(B등급): 10종류 기준
    - 쉬움: 8-9종류
    - 어려움: 11종류
    - 매우 어려움: 12종류
    - 튜토리얼: 4-5종류 유지
    """
    if level_number <= 10:
        return {
            "min_layers": 1,
            "max_layers": 2,
            "cols": 7,
            "rows": 7,
            "total_tile_range": (9, 18),
            "tile_types": 4,  # 튜토리얼 유지
            "description": "Tutorial - minimal complexity"
        }
    elif level_number <= 30:
        return {
            "min_layers": 2,
            "max_layers": 3,
            "cols": 7,
            "rows": 7,
            "total_tile_range": (18, 36),
            "tile_types": 5,  # 초반 점진적 증가
            "description": "Early game - basic layering"
        }
    elif level_number <= 60:
        return {
            "min_layers": 3,
            "max_layers": 4,
            "cols": 7,
            "rows": 7,
            "total_tile_range": (30, 50),
            "tile_types": 7,  # 5 → 7 증가
            "description": "Early-mid game - moderate complexity"
        }
    elif level_number <= 100:
        return {
            "min_layers": 4,
            "max_layers": 5,
            "cols": 10,
            "rows": 10,
            "total_tile_range": (50, 80),
            "tile_types": 8,  # 5 → 8 증가
            "description": "Mid game - larger grid"
        }
    elif level_number <= 225:
        return {
            "min_layers": 4,
            "max_layers": 5,
            "cols": 10,
            "rows": 10,
            "total_tile_range": (60, 90),
            "tile_types": 8,  # 5 → 8 증가 (S등급 마무리)
            "description": "Mid-late game - S등급 마무리"
        }
    elif level_number <= 600:
        return {
            "min_layers": 4,
            "max_layers": 5,
            "cols": 10,
            "rows": 10,
            "total_tile_range": (70, 100),
            "tile_types": 9,  # 6 → 9 증가 (A등급)
            "description": "Standard game - A등급 주력"
        }
    elif level_number <= 1125:
        return {
            "min_layers": 5,
            "max_layers": 5,
            "cols": 10,
            "rows": 10,
            "total_tile_range": (75, 105),
            "tile_types": 10,  # 6 → 10 (B등급 기준선 ★)
            "description": "Advanced game - B등급 핵심 재미"
        }
    elif level_number <= 1500:
        return {
            "min_layers": 5,
            "max_layers": 6,
            "cols": 10,
            "rows": 10,
            "total_tile_range": (84, 120),
            "tile_types": 11,  # 7 → 11 (C/D등급)
            "description": "Expert game - C/D등급 도전"
        }
    else:
        return {
            "min_layers": 5,
            "max_layers": 6,
            "cols": 10,
            "rows": 10,
            "total_tile_range": (96, 120),
            "tile_types": 12,  # 8 → 12 (Master)
            "description": "Master game - 엔드게임"
        }
```

### 5.3 generator.py - get_tile_types_for_level

```python
def get_tile_types_for_level(level_number: int) -> List[str]:
    """
    Get recommended tile types list based on level number.

    [v2] 난이도별 타일 종류 수:
    - 튜토리얼 (1-10): 4-5종류
    - 쉬움 (S/A): 8-9종류
    - 보통 (B): 10종류 (기준선)
    - 어려움 (C/D): 11-12종류

    톱니바퀴 패턴(10레벨 순환) 기반:
    - 쉬운 레벨: 실제 타일 타입 사용
    - 일반 레벨: t0 사용 (클라이언트에서 랜덤 타일로 변환)
    """
    config = get_gboost_style_layer_config(level_number)
    tile_count = config.get("tile_types", 10)

    # 10레벨 주기 내 위치 (0~9)
    position_in_10 = (level_number - 1) % 10

    # 톱니바퀴 패턴에서 가장 낮은 난이도 3개 position에 해당하면 실제 타일 사용
    lowest_positions = _get_lowest_positions()
    if position_in_10 in lowest_positions:
        # 실제 타일 타입 사용: t1 ~ t{tile_count}
        return [f"t{i}" for i in range(1, tile_count + 1)]
    else:
        # 나머지 레벨은 t0 사용 (클라이언트에서 랜덤 타일로 변환)
        return ["t0"]
```

### 5.4 leveling_config.py - PHASE_CONFIGS

```python
PHASE_CONFIGS: Dict[LevelPhase, PhaseConfig] = {
    LevelPhase.TUTORIAL: PhaseConfig(
        phase=LevelPhase.TUTORIAL,
        level_range=(1, 225),
        min_tile_types=4,      # 튜토리얼 유지
        max_tile_types=8,      # 5 → 8 (S등급 상한)
        min_layers=1,
        max_layers=4,
        max_gimmick_types=2,
        base_difficulty=0.02,
        difficulty_increment=0.00071,
        min_tiles=9,
        max_tiles=60,
        has_milestone=True,
    ),

    LevelPhase.BASIC: PhaseConfig(
        phase=LevelPhase.BASIC,
        level_range=(226, 600),
        min_tile_types=8,      # 5 → 8
        max_tile_types=9,      # 6 → 9 (A등급)
        min_layers=3,
        max_layers=5,
        max_gimmick_types=3,
        base_difficulty=0.18,
        difficulty_increment=0.00053,
        min_tiles=45,
        max_tiles=84,
        has_milestone=True,
    ),

    LevelPhase.INTERMEDIATE: PhaseConfig(
        phase=LevelPhase.INTERMEDIATE,
        level_range=(601, 1125),
        min_tile_types=9,      # 5 → 9
        max_tile_types=10,     # 7 → 10 (B등급 기준선 ★)
        min_layers=4,
        max_layers=5,
        max_gimmick_types=4,
        base_difficulty=0.38,
        difficulty_increment=0.00038,
        min_tiles=60,
        max_tiles=100,
        has_milestone=True,
    ),

    LevelPhase.ADVANCED: PhaseConfig(
        phase=LevelPhase.ADVANCED,
        level_range=(1126, 1425),
        min_tile_types=10,     # 6 → 10
        max_tile_types=11,     # 8 → 11 (C등급)
        min_layers=5,
        max_layers=6,
        max_gimmick_types=5,
        base_difficulty=0.58,
        difficulty_increment=0.00067,
        min_tiles=72,
        max_tiles=108,
        has_milestone=True,
    ),

    LevelPhase.EXPERT: PhaseConfig(
        phase=LevelPhase.EXPERT,
        level_range=(1426, 1500),
        min_tile_types=11,     # 6 → 11
        max_tile_types=12,     # 8 → 12 (D등급)
        min_layers=5,
        max_layers=6,
        max_gimmick_types=6,
        base_difficulty=0.78,
        difficulty_increment=0.00187,
        min_tiles=84,
        max_tiles=120,
        has_milestone=True,
    ),

    LevelPhase.MASTER: PhaseConfig(
        phase=LevelPhase.MASTER,
        level_range=(1501, 9999),
        min_tile_types=11,     # 6 → 11
        max_tile_types=12,     # 8 → 12 (Master)
        min_layers=5,
        max_layers=6,
        max_gimmick_types=6,
        base_difficulty=0.92,
        difficulty_increment=0.0,
        min_tiles=96,
        max_tiles=120,
        has_milestone=True,
    ),
}
```

---

## 6. Risk Assessment

### Low Risk
- `DEFAULT_TILE_TYPES` 변경: 단순 배열 확장
- `PHASE_CONFIGS` 숫자 변경: 설정값만 수정

### Medium Risk
- `get_tile_types_for_level()` 로직 변경: 기존 그룹 순환 로직 단순화
- 봇 시뮬레이션 결과 변화: 타일 다양성 증가로 난이도 상승 가능

### Mitigation
- 변경 후 기존 테스트 모두 실행
- 레벨 100, 500, 1000 에서 생성 테스트
- 봇 시뮬레이션으로 클리어율 검증

---

## 7. Rollback Plan

모든 변경사항은 git commit으로 관리:
```bash
git checkout -- backend/app/core/generator.py
git checkout -- backend/app/models/leveling_config.py
```

---

## 8. Summary

| 항목 | 변경 전 | 변경 후 |
|------|---------|---------|
| DEFAULT_TILE_TYPES | 5종류 | 10종류 |
| 튜토리얼 (1-10) | 4종류 | 4-5종류 (유지) |
| S등급 (11-225) | 4-5종류 | 5-8종류 |
| A등급 (226-600) | 5-6종류 | 8-9종류 |
| B등급 (601-1125) | 6종류 | 10종류 (기준선) |
| C등급 (1126-1425) | 7종류 | 11종류 |
| D등급 (1426-1500) | 8종류 | 12종류 |
| Master (1501+) | 8종류 | 12종류 |

**구현 명령**: "이 설계대로 구현해줘"
