# CHANGELOG: 패턴 모양 보존 3배수 보정 (v15.9 → v15.10)

**날짜**: 2026-03-10
**버전**: v15.9 → v15.10
**영향 범위**: `backend/app/core/generator.py`

---

## 문제 정의

### 기존 동작
패턴 모드에서 3의 배수를 맞추기 위해 **타일을 삭제**하여 패턴 모양 손상

```
예: 삼각형 패턴 31개 타일
    ↓ 3배수 보정 (31 % 3 = 1)
    ↓ 1개 타일 삭제
결과: 30개 타일 (삼각형 일부 손상)
```

### 사용자 요구사항
> "3배수 보정으로 이미 생성된 모양에서 제거되면 안 되고 모양을 유지하며 3배수도 만족해야 함"

---

## 해결 방안

### 우선순위 기반 3배수 보정 전략

| 우선순위 | 방법 | 패턴 보존율 | 조건 |
|----------|------|-------------|------|
| **1순위** | Goal 내부 타일 수 조정 | 100% | craft/stack 타일 존재 시 |
| **2순위** | 인접 위치 타일 추가 | ~99% | Goal 없을 경우 Fallback |

### 1순위: Goal 내부 타일 조정

모든 Production 레벨에는 goal 타일(craft_s, stack_n 등)이 포함되어 있으며,
이 타일 내부에 t0 타일 카운트가 있음.

```python
# Goal 타일 구조: [tile_type, attribute, [internal_count, ...]]
# 예: ["craft_s", "", [5, ...]]  → 내부에 t0 5개

# 3배수 보정: 내부 카운트 조정
# 그리드 31개 + Goal 내부 5개 = 36개 (3의 배수 아님, 나머지 0... 잠깐)
# 그리드 31개 (나머지 1) → Goal 내부에 +2 추가
# 그리드 31개 + Goal 내부 7개 = 38개... 아니 이건 타입별 계산

# 실제 로직:
# total_matchable = 그리드 타일 + Goal 내부 타일
# 나머지 = total_matchable % 3
# 필요한 추가 = 3 - 나머지
# Goal 내부 카운트에 추가
```

**장점**: 그리드 타일 위치 변경 없음 → 패턴 모양 100% 유지

### 2순위: 인접 위치 타일 추가 (Fallback)

Goal 타일이 없는 경우에만 사용:

```python
def get_adjacent_empty_positions(layer_idx):
    # 기존 패턴 타일의 4방향 인접 빈 위치 탐색
    for pos in existing_tiles:
        for dx, dy in [(-1,0), (1,0), (0,-1), (0,1)]:
            neighbor = (x+dx, y+dy)
            if neighbor not in used:
                yield neighbor

# 인접 위치에 타일 추가
for pos in adjacent_positions[:tiles_needed]:
    layer["tiles"][pos] = ["t1", ""]
```

**장점**: 패턴 외곽에만 추가되어 모양 최소 변형

---

## 수정된 함수

### 1. `_ensure_tile_count_divisible_by_3`

```python
# 변경 전 (v15.8 이하)
if total_remainder != 0:
    # 타일 삭제로 3배수 맞춤
    for tile in removable[:remainder]:
        del level[layer]["tiles"][pos]

# 변경 후 (v15.10)
if preserve_pattern:
    # 1순위: Goal 내부 조정
    if goal_tiles_with_internal:
        for tile_data in goal_tiles:
            tile_data[2][0] += 1  # 내부 카운트 증가
    # 2순위: 인접 위치 추가 (Fallback)
    else:
        for pos in get_adjacent_empty_positions():
            level[layer]["tiles"][pos] = ["t1", ""]
```

### 2. `_force_fix_tile_counts`

동일한 우선순위 기반 로직 적용

---

## 테스트 시나리오

### 시나리오 1: Goal 타일 존재 (일반적인 경우)
```
입력: 삼각형 패턴 31개 + craft_s 내부 5개 = 36개 (나머지 0) ✓
결과: 변경 없음
```

### 시나리오 2: Goal 있지만 총합이 3배수 아님
```
입력: 삼각형 패턴 31개 + craft_s 내부 4개 = 35개 (나머지 2)
처리: craft_s 내부 +1 → 31 + 5 = 36개 ✓
결과: 패턴 모양 100% 유지
```

### 시나리오 3: Goal 없음 (드문 경우)
```
입력: 삼각형 패턴 31개, Goal 없음 (나머지 1)
처리: 인접 위치에 +2개 추가 → 33개 ✓
결과: 패턴 외곽에 2개 추가 (최소 변형)
```

---

## 버전별 변경사항

### v15.9 (ea17c3e)
- 패턴 모드에서 타일 삭제 완전 방지
- 인접 위치 타일 추가 방식 도입

### v15.10 (e6bcf5c)
- Goal 내부 타일 조정 1순위로 추가
- 인접 추가는 Fallback으로 변경
- 패턴 모양 100% 보존 가능

---

## 관련 파일

- `backend/app/core/generator.py`: 핵심 로직
- `claudedocs/PROJECT_INDEX.md`: 프로젝트 문서 (v15.10 업데이트)
