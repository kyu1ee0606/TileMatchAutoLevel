# Changelog: 타일 분포 균등화 및 Tutorial Gimmick 수정

**날짜**: 2026-03-16
**버전**: v15.26 ~ v15.28

---

## 개요

이번 업데이트는 두 가지 주요 개선사항을 포함합니다:
1. **Tutorial Gimmick Goals 자동 설정** - 레벨 21 스택 미사용 버그 수정
2. **난이도 연동 타일 분포 균등화 시스템** - 난이도별 타일 분배 최적화
3. **기믹 언락 정보 팝업 UI** - 프로덕션 대시보드 UX 개선

---

## v15.26: Tutorial Gimmick Goals 자동 설정

### 문제점
- 레벨 21 재생성 시 stack이 아닌 craft가 생성됨
- 원인: `goals` 파라미터가 None일 때 generator.py에서 기본값 `craft_s` 사용
- 이전 언락된 기믹(craft)이 우선 사용되어 tutorial_gimmick(stack) 무시됨

### 해결 방법
`filter_goals_by_unlock_level` 함수에 `tutorial_gimmick` 파라미터 추가

```python
def filter_goals_by_unlock_level(
    goals: List[Dict] | None,
    level_number: int | None,
    unlock_levels: Dict[str, int] | None,
    tutorial_gimmick: str | None = None  # NEW PARAMETER
) -> List[Dict] | None:
    # CRITICAL: If tutorial_gimmick is craft or stack, force use that goal type
    if tutorial_gimmick in ("craft", "stack"):
        goal_type = f"{tutorial_gimmick}_s"
        logger.info(f"[GOALS_FILTER] Level {level_number}: Tutorial gimmick '{tutorial_gimmick}' "
                   f"→ forcing goal type '{goal_type}'")
        return [{"type": goal_type, "count": 3}]
```

### 수정 파일
- `backend/app/api/routes/generate.py`
  - `filter_goals_by_unlock_level()` 함수 수정
  - `generate_level` 엔드포인트에서 tutorial_gimmick 전달
  - `generate_validated_level` 엔드포인트에서 tutorial_gimmick 전달

### 영향받는 레벨
| 레벨 | 필수 기믹 | 목표 타입 |
|------|----------|----------|
| 11 | craft | craft_s |
| 21 | stack | stack_s |

---

## v15.27: 기믹 언락 정보 팝업 UI

### 추가 기능
프로덕션 대시보드 헤더에 "📋 기믹 언락 정보" 버튼 추가

### 구현 내용

```typescript
const GIMMICK_TUTORIAL_INFO: Array<{
  level: number;
  gimmick: string;
  name: string;
  type: 'goal' | 'obstacle';
  difficulty: string;
  description: string;
}> = [
  { level: 11, gimmick: 'craft', name: '공예', type: 'goal', ... },
  { level: 21, gimmick: 'stack', name: '스택', type: 'goal', ... },
  { level: 31, gimmick: 'ice', name: '얼음', type: 'obstacle', ... },
  // ... 총 13개 기믹
];
```

### 팝업 내용
| 레벨 | 기믹 | 유형 | 난이도 | 설명 |
|------|------|------|--------|------|
| 11 | craft | 목표 | ⭐⭐⭐ | 여러 타일을 모아 완성하는 목표 타일 |
| 21 | stack | 목표 | ⭐⭐⭐ | 쌓인 타일을 순서대로 제거 |
| 31 | ice | 장애물 | ⭐⭐ | 얼음 속 타일 해방 |
| 51 | link | 장애물 | ⭐⭐⭐ | 연결된 타일 동시 제거 |
| 81 | chain | 장애물 | ⭐⭐⭐⭐ | 사슬 해제 후 타일 접근 |
| 111 | key | 장애물 | ⭐⭐ | 버퍼 잠금 해제용 키 |
| 151 | grass | 장애물 | ⭐⭐ | 풀 위의 타일 제거 |
| 191 | unknown | 장애물 | ⭐⭐⭐ | 숨겨진 타일 공개 |
| 241 | curtain | 장애물 | ⭐⭐ | 커튼 뒤 타일 공개 |
| 291 | bomb | 장애물 | ⭐⭐⭐⭐⭐ | 제한 시간 내 제거 필수 |
| 341 | time_attack | 장애물 | ⭐⭐⭐⭐ | 전체 시간 제한 |
| 391 | frog | 장애물 | ⭐⭐⭐ | 개구리가 타일 점유 |
| 441 | teleport | 장애물 | ⭐⭐⭐⭐ | 타일 위치 이동 |

### 수정 파일
- `frontend/src/components/ProductionDashboard/index.tsx`

---

## v15.28: 난이도 연동 타일 분포 균등화 시스템

### 배경
- 기존: `random.choice`로 타일 타입 할당 → 타입별 불균등 분포
- 문제: 랜덤 분배로 인해 특정 타입 과다/부족 발생, 난이도 예측 어려움

### 설계 원칙
- **쉬운 레벨(S/A등급)**: 높은 균등도 → 안정적인 게임플레이
- **어려운 레벨(D/E등급)**: 낮은 균등도 → 의도적 불균형으로 난이도 상승

### 구현

#### 난이도별 균등도 설정
```python
TILE_UNIFORMITY_BY_DIFFICULTY = {
    (0.0, 0.2): 1.0,    # S등급: 완전 균등
    (0.2, 0.35): 0.95,  # A등급: 거의 균등
    (0.35, 0.5): 0.85,  # B등급: 약간 불균형 허용
    (0.5, 0.7): 0.75,   # C등급: 불균형 허용
    (0.7, 0.85): 0.65,  # D등급: 상당한 불균형
    (0.85, 1.0): 0.50,  # E등급: 의도적 불균형
}
```

#### 분배 알고리즘
```python
if uniformity >= 0.9:
    # 높은 균등도: Round-robin 분배
    for tile_type in tile_types:
        tile_assignments.extend([tile_type] * base_tiles_per_type)
else:
    # 낮은 균등도: 차등 분배 with variance_strength
    variance_strength = int((1.0 - uniformity) * 4) + 1  # 1 ~ 3

    shuffled_types = list(tile_types)
    random.shuffle(shuffled_types)
    half = len(shuffled_types) // 2

    for i, tile_type in enumerate(shuffled_types):
        if i < half:
            adjustment = random.randint(1, variance_strength) * 3
        else:
            adjustment = -random.randint(1, variance_strength) * 3

        allocation = max(3, base_tiles_per_type + adjustment)
        allocation = (allocation // 3) * 3
        type_allocations[tile_type] = allocation
```

### 테스트 결과

#### API 테스트 (curl)
```bash
# S등급 테스트 (target_difficulty: 0.15)
curl -X POST http://localhost:8000/api/generate/validated \
  -H "Content-Type: application/json" \
  -d '{"level_number":226, "target_difficulty":0.15}'

# D등급 테스트 (target_difficulty: 0.75)
curl -X POST http://localhost:8000/api/generate/validated \
  -H "Content-Type: application/json" \
  -d '{"level_number":226, "target_difficulty":0.75}'
```

#### 결과 비교
| 등급 | 목표 난이도 | 균등도 설정 | 실제 균등도 | 분포 특성 |
|------|------------|------------|------------|----------|
| S | 0.15 | 1.0 | 71.6% | t4:24, t3:24, t5:21, t6:21, t2:21, t1:18 |
| D | 0.75 | 0.65 | 54.8% | t1:30, t4:27, t2:18, t3:18, t6:18, t5:15 |

#### 상관관계 확인
- S등급(높은 균등도): 타입간 편차 최대 6개 (24-18)
- D등급(낮은 균등도): 타입간 편차 최대 15개 (30-15)
- **결론**: 난이도가 높을수록 타일 분포 불균형 증가 → 난이도 상승 효과 확인

### 수정 파일
- `backend/app/core/generator.py`
  - `TILE_UNIFORMITY_BY_DIFFICULTY` 상수 추가
  - `get_tile_uniformity()` 함수 추가
  - `_build_level_tiles()` 내 분배 로직 수정

---

## v15.28 개선: 분산 강도 조정

### 문제점
- 초기 구현에서 variance 계산이 3으로 나눈 후 다시 3을 곱하면서 0이 됨
- D등급에서도 높은 균등도(실제로 S등급 수준) 발생

### 해결
```python
# 변경 전 (문제)
variance = int(base_tiles_per_type * variance_factor)
variance = (variance // 3) * 3  # 결과: 0

# 변경 후 (해결)
variance_strength = int((1.0 - uniformity) * 4) + 1  # 최소 1 보장
adjustment = random.randint(1, variance_strength) * 3  # 3의 배수 보장
```

---

## 요약

| 버전 | 변경사항 | 영향 범위 |
|------|---------|----------|
| v15.26 | tutorial_gimmick goals 자동 설정 | 레벨 11, 21 |
| v15.27 | 기믹 언락 정보 팝업 | 프로덕션 UI |
| v15.28 | 타일 분포 균등화 시스템 | 전체 레벨 생성 |
| v15.28 개선 | 분산 강도 조정 | 난이도별 분포 |

---

## 관련 커밋

```bash
git log --oneline -5
# 96aa00c Improve: 타일 분포 불균형 강도 조정 (v15.28 개선)
# 2a029b9 Feat: 난이도 연동 타일 분포 균등화 시스템 (v15.28)
# 18c3192 Feat: 프로덕션 대시보드에 기믹 언락 정보 팝업 추가 (v15.27)
# afef0a0 Fix: tutorial_gimmick에 따른 goals 자동 설정 (v15.26)
# 8dbe6dc Fix: tutorial_gimmick 강제 적용 로직 근본 수정 (v15.25)
```
