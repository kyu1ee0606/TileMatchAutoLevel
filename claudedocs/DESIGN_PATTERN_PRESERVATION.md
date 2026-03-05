# Pattern Preservation Refactoring Design

## 1. Problem Analysis

### Current Issue
`pattern_index` 지정 시 패턴 형태가 생성 후 후처리 단계에서 훼손됨

### Observed Symptoms
- 기대 위치 30개 → 실제 40개 (의도하지 않은 타일 추가)
- 레이어별 타일 수 불일치 (30, 30, 40)
- 시각적으로 패턴 형태 불분명

### Root Cause Analysis

```
generate() 함수 흐름:
┌─────────────────────────────────────────────────────────────┐
│ 1. _create_base_structure()                                 │
│ 2. _populate_layers()         ✓ 패턴 생성 (수정됨)           │
│ 3. _add_obstacles()           ○ 타일 위치 변경 없음          │
│ 4. _add_goals()               ✗ 새 타일 추가 가능 (문제)     │
│ 5. _fix_goal_counts()         △ 내부 타일 수 조정            │
│ 6. _adjust_difficulty()       ✓ 패턴 시 타일 변경 금지 (수정됨)│
│ 7. _ensure_tile_count_divisible_by_3() ✗ 타일 추가/제거 (문제)│
│ 8. _validate_and_fix_obstacles()    △ 타일 제거 가능         │
│ 9. _ensure_tile_count_divisible_by_3() ✗ 2차 타일 추가 (문제)│
│ 10. _relocate_tiles_from_goal_outputs() △ 타일 이동          │
│ 11. _validate_and_fix_frog_positions() △ 위치 조정           │
└─────────────────────────────────────────────────────────────┘
```

**문제 함수들:**
1. `_add_goals()` - 목표 타일을 패턴 외 위치에 추가할 수 있음
2. `_ensure_tile_count_divisible_by_3()` - 3의 배수 맞추기 위해 랜덤 위치에 타일 추가

---

## 2. Solution Architecture

### 2.1 Core Principle: Pattern Position Lock

```
┌─────────────────────────────────────────────────────────────┐
│  PATTERN MODE (pattern_index is not None)                   │
├─────────────────────────────────────────────────────────────┤
│  1. Master Pattern Generation (locked positions)            │
│  2. All post-processing respects locked positions           │
│  3. Difficulty adjustment via gimmicks ONLY                 │
│  4. Tile count divisibility via type redistribution ONLY    │
│  5. Goals placed within pattern positions                   │
└─────────────────────────────────────────────────────────────┘
```

### 2.2 State Flag: `preserve_pattern_positions`

```python
# GenerationParams에 추가 (또는 generate() 내부 변수)
preserve_pattern_positions: bool = False
pattern_locked_positions: Set[str] = set()  # 패턴에서 허용된 위치들
```

### 2.3 Modified Function Behaviors

| 함수 | 현재 동작 | 패턴 모드 동작 |
|------|----------|---------------|
| `_populate_layers` | 패턴/랜덤 위치 생성 | 마스터 패턴 위치 생성 + 잠금 |
| `_add_goals` | 빈 위치에 목표 추가 | **패턴 위치 내**에서 목표 배치 |
| `_adjust_difficulty` | 타일 추가/제거 | 기믹으로만 조정 (수정됨) |
| `_ensure_divisible_by_3` | 타일 추가/제거 | **타입 재분배**로만 조정 |
| `_validate_obstacles` | 필요시 타일 제거 | 기믹만 제거, 타일 유지 |

---

## 3. Detailed Implementation

### 3.1 `_populate_layers` 수정 (이미 부분 완료)

```python
if params.pattern_index is not None:
    # 1. 마스터 패턴 생성
    master_positions = self._generate_aesthetic_positions(
        cols, rows,
        target_count=1000,  # 전체 패턴
        pattern_index=params.pattern_index
    )

    # 2. 3의 배수로 조정 (여기서 미리 처리!)
    pattern_count = (len(master_positions) // 3) * 3
    master_positions = master_positions[:pattern_count]

    # 3. 패턴 위치 잠금 (level 메타데이터에 저장)
    level["_pattern_locked_positions"] = set(master_positions)
    level["_preserve_pattern"] = True

    # 4. 모든 레이어에 동일 위치 할당
    for layer_idx in active_layers:
        # ... 기존 로직
```

### 3.2 `_add_goals` 수정

```python
def _add_goals(self, level, params, strict_mode=False):
    preserve_pattern = level.get("_preserve_pattern", False)
    locked_positions = level.get("_pattern_locked_positions", set())

    if preserve_pattern:
        # 패턴 모드: 기존 패턴 위치 중에서 목표 배치
        # 새 위치 추가 금지, 기존 타일을 목표로 교체
        available_positions = [...]  # 패턴 위치 중 목표 배치 가능한 곳
        # 목표는 기존 타일 위치에서 선택
    else:
        # 기존 로직
```

### 3.3 `_ensure_tile_count_divisible_by_3` 수정

```python
def _ensure_tile_count_divisible_by_3(self, level, params):
    preserve_pattern = level.get("_preserve_pattern", False)

    if preserve_pattern:
        # 패턴 모드: 타일 추가/제거 금지
        # 타입 재분배로만 3의 배수 맞추기
        return self._redistribute_tile_types_for_divisibility(level, params)
    else:
        # 기존 로직
```

### 3.4 새 함수: `_redistribute_tile_types_for_divisibility`

```python
def _redistribute_tile_types_for_divisibility(self, level, params):
    """
    타일 위치는 유지하면서 타입만 재분배하여 3의 배수 맞추기

    알고리즘:
    1. 각 타입별 개수 계산
    2. 나머지가 있는 타입 식별 (remainder 1 또는 2)
    3. 타입 간 재분배:
       - remainder=1 타입의 타일 1개를 remainder=2 타입으로 변경
       - 또는 remainder=1 타입의 타일 2개를 다른 타입으로 변경
    4. 위치는 절대 변경하지 않음
    """
    # ... 구현
```

### 3.5 `_validate_and_fix_obstacles` 수정

```python
def _validate_and_fix_obstacles(self, level):
    preserve_pattern = level.get("_preserve_pattern", False)

    if preserve_pattern:
        # 패턴 모드: 타일 삭제 대신 기믹만 제거
        # 유효하지 않은 chain/link/grass는 기믹 속성만 제거
        for invalid_obstacle in invalid_obstacles:
            tile_data[1] = ""  # 기믹만 제거, 타일은 유지
    else:
        # 기존 로직 (타일 삭제 가능)
```

---

## 4. Implementation Priority

### Phase 1: Critical (즉시)
1. `_ensure_tile_count_divisible_by_3` 수정
   - 패턴 모드에서 타입 재분배만 사용
   - 위치 추가/삭제 완전 금지

### Phase 2: Important
2. `_add_goals` 수정
   - 패턴 모드에서 패턴 위치 내 목표 배치

### Phase 3: Enhancement
3. `_validate_and_fix_obstacles` 수정
4. 메타데이터 정리 (최종 출력에서 `_pattern_*` 제거)

---

## 5. Validation Checklist

```
□ 모든 64개 패턴이 시각적으로 정확히 표시됨
□ Heart 패턴 = 하트 모양 (30개 위치)
□ Stairs 패턴 = 계단 모양 (36개 위치)
□ 레이어별 타일 수 동일 (패턴 위치 수)
□ 총 고유 위치 = 패턴 위치 수 (추가 없음)
□ 3의 배수 조건 충족
□ 게임 플레이 가능 (클리어 가능)
```

---

## 6. Code Changes Summary

| 파일 | 함수 | 변경 내용 |
|------|------|----------|
| generator.py | `_populate_layers` | 패턴 위치 잠금 플래그 추가 |
| generator.py | `_ensure_tile_count_divisible_by_3` | 패턴 모드 분기 추가 |
| generator.py | `_redistribute_tile_types_for_divisibility` | 새 함수 추가 |
| generator.py | `_add_goals` | 패턴 모드 분기 추가 |
| generator.py | `_validate_and_fix_obstacles` | 패턴 모드 분기 추가 |
| generator.py | `generate` | 최종 출력 전 메타데이터 정리 |
