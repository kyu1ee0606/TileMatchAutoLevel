# Bot Simulation Accuracy Improvement Plan

> **작성일**: 2026-02-10
> **목적**: 봇 시뮬레이션과 실제 플레이어 행동 간 Gap 분석 및 개선 계획
> **롤백 가능**: 각 개선 항목별 독립 적용/롤백 가능하도록 설계

---

## 1. 현재 상태 스냅샷 (Before State)

### 1.1 봇 프로필 현재 설정

**파일**: `backend/app/models/bot_profile.py`

| Bot Type | mistake_rate | lookahead_depth | goal_priority | blocking_awareness | chain_preference | patience | risk_tolerance | pattern_recognition | weight |
|----------|--------------|-----------------|---------------|-------------------|------------------|----------|----------------|---------------------|--------|
| NOVICE | 0.4 | 0 | 0.3 | 0.2 | 0.1 | 0.3 | 0.7 | 0.2 | 0.5 |
| CASUAL | 0.2 | 1 | 0.5 | 0.4 | 0.3 | 0.4 | 0.5 | 0.4 | 1.0 |
| AVERAGE | 0.1 | 2 | 0.7 | 0.7 | 0.6 | 0.5 | 0.4 | 0.6 | 1.5 |
| EXPERT | 0.02 | 5 | 0.95 | 0.95 | 0.8 | 0.8 | 0.25 | 0.85 | 0.8 |
| OPTIMAL | 0.0 | 10 | 1.0 | 1.0 | 1.0 | 1.0 | 0.1 | 0.99 | 0.3 |

### 1.2 현재 동작 방식

**무브 선택 로직** (`bot_simulator.py:2782-2835`):
```python
def _select_move_with_profile(self, moves, state, profile):
    # 1. 실수 확률 체크 → 랜덤 선택
    if self._rng.random() < profile.mistake_rate:
        return self._rng.choice(moves)

    # 2. 매칭 무브 우선
    matching_moves = [m for m in moves if m.will_match]
    if matching_moves:
        return max(matching_moves, key=lambda m: m.score)

    # 3. 점수순 정렬
    sorted_moves = sorted(moves, key=lambda m: m.score, reverse=True)

    # 4. Optimal 봇: perfect information 전략
    if profile.pattern_recognition >= 1.0:
        return self._optimal_perfect_information_strategy(sorted_moves, state, profile)

    # 5. Expert 봇: lookahead 전략
    if profile.lookahead_depth > 0:
        # adaptive depth + candidate pruning
        ...

    return sorted_moves[0]
```

**무브 점수 계산** (`bot_simulator.py:2355-2504`):
- 매칭 보너스: +100.0
- 2-in-dock 셋업: +20.0 * pattern_recognition
- Dock 위험 페널티: -50.0 (6개), -20.0 (5개)
- Optimal 봇: hidden 타일 정보 활용 (`state.all_tile_type_counts`)

### 1.3 현재 문제점 요약

| 문제 | 설명 | 영향 |
|------|------|------|
| **Perfect Information** | Optimal 봇이 숨겨진 타일 정보까지 알고 있음 | 비현실적 클리어율 |
| **Attention 미반영** | 모든 accessible 타일을 동등하게 인식 | 클리어율 과대평가 |
| **기믹 인식률 없음** | Bomb, Curtain 등 모든 기믹 100% 인식 | 기믹 난이도 과소평가 |
| **감정 상태 미반영** | Dock panic 시 단순 점수 감점만 적용 | 실제 행동 불일치 |
| **인지 부하 없음** | 복잡한 레벨도 동일한 성능 | 복잡도 난이도 미반영 |

---

## 2. 개선 계획

### 2.1 Phase 1: Attention Zone 도입 (CRITICAL)

**목적**: 플레이어가 실제로 인식할 수 있는 타일만 선택 후보로 제한

**변경 파일**: `backend/app/core/bot_simulator.py`

**현재 동작**:
```python
# _get_available_moves(): 모든 accessible 타일 반환
moves = []
for layer_idx in sorted(state.tiles.keys(), reverse=True):
    for tile in layer.values():
        if not tile.picked and tile.can_pick() and not self._is_blocked_by_upper(state, tile):
            moves.append(Move(...))
```

**개선 후 동작**:
```python
def _filter_by_attention(self, moves: List[Move], state: GameState, profile: BotProfile) -> List[Move]:
    """플레이어 attention zone 기반 필터링"""
    if profile.pattern_recognition >= 0.99:  # Optimal은 전체 인식
        return moves

    visible_moves = []
    max_layer = state._max_layer_idx

    for move in moves:
        # 1. 상위 레이어 가시성 (0~1)
        layer_factor = max(0, (move.layer_idx - max_layer + 3)) / 3

        # 2. Dock 매칭 타입 주목
        dock_match = any(t.tile_type == move.tile_type for t in state.dock_tiles)

        # 3. 매칭 가능(3개째)이면 무조건 인식
        if move.will_match:
            visible_moves.append(move)
            continue

        # 4. 인식 확률 계산
        visibility = layer_factor * 0.5 + (0.4 if dock_match else 0) + 0.1
        notice_prob = min(1.0, visibility * (0.5 + profile.pattern_recognition * 0.5))

        if self._rng.random() < notice_prob:
            visible_moves.append(move)

    # 최소 1개 보장
    return visible_moves if visible_moves else [self._rng.choice(moves)]
```

**호출 위치 변경**:
```python
# _select_move_with_profile() 시작 부분에 추가
def _select_move_with_profile(self, moves, state, profile):
    if not moves:
        return None

    # NEW: Attention 필터링 적용
    visible_moves = self._filter_by_attention(moves, state, profile)

    # 이후 로직은 visible_moves 사용
    ...
```

**롤백 방법**:
- `_filter_by_attention()` 함수 제거
- `_select_move_with_profile()`에서 `visible_moves = moves` 로 변경

**예상 효과**:
- NOVICE/CASUAL 클리어율 10-15% 하향
- AVERAGE 클리어율 5-10% 하향
- EXPERT 이상 영향 미미 (pattern_recognition 높음)

---

### 2.2 Phase 2: 기믹 인식률 차등 적용 (CRITICAL)

**목적**: 기믹별로 봇 스킬에 따른 인식 확률 차등 적용

**변경 파일**: `backend/app/core/bot_simulator.py`

**신규 상수 추가**:
```python
# 기믹 인식률 테이블: (NOVICE, CASUAL, AVERAGE, EXPERT, OPTIMAL)
GIMMICK_NOTICE_RATES = {
    TileEffectType.NONE: (1.0, 1.0, 1.0, 1.0, 1.0),
    TileEffectType.ICE: (0.9, 0.95, 1.0, 1.0, 1.0),       # 패시브 - 잘 보임
    TileEffectType.CHAIN: (0.9, 0.95, 1.0, 1.0, 1.0),     # 패시브
    TileEffectType.GRASS: (0.85, 0.92, 0.98, 1.0, 1.0),   # 패시브
    TileEffectType.BOMB: (0.3, 0.6, 0.85, 0.95, 1.0),     # 액티브 - 주의 필요
    TileEffectType.CURTAIN: (0.4, 0.65, 0.8, 0.95, 1.0),  # 상태 추적 필요
    TileEffectType.FROG: (0.5, 0.7, 0.85, 0.95, 1.0),     # 이동 예측 필요
    TileEffectType.TELEPORT: (0.4, 0.6, 0.8, 0.9, 1.0),   # 셔플 예측 어려움
    TileEffectType.LINK_EAST: (0.6, 0.75, 0.9, 0.98, 1.0),
    TileEffectType.LINK_WEST: (0.6, 0.75, 0.9, 0.98, 1.0),
    TileEffectType.LINK_SOUTH: (0.6, 0.75, 0.9, 0.98, 1.0),
    TileEffectType.LINK_NORTH: (0.6, 0.75, 0.9, 0.98, 1.0),
    TileEffectType.CRAFT: (0.7, 0.8, 0.9, 0.98, 1.0),
    TileEffectType.STACK_NORTH: (0.7, 0.8, 0.9, 0.98, 1.0),
    TileEffectType.STACK_SOUTH: (0.7, 0.8, 0.9, 0.98, 1.0),
    TileEffectType.STACK_EAST: (0.7, 0.8, 0.9, 0.98, 1.0),
    TileEffectType.STACK_WEST: (0.7, 0.8, 0.9, 0.98, 1.0),
}
```

**신규 메서드 추가**:
```python
def _is_gimmick_noticed(self, effect_type: TileEffectType, profile: BotProfile) -> bool:
    """해당 기믹을 플레이어가 인식했는지 확률적 판단"""
    rates = GIMMICK_NOTICE_RATES.get(effect_type, (1.0, 1.0, 1.0, 1.0, 1.0))
    bot_index = BotType.all_types().index(profile.bot_type)
    return self._rng.random() < rates[bot_index]
```

**적용 위치**: `_score_move_with_profile()` 내 기믹 관련 점수 계산 시
```python
# Bomb 처리 예시
if move.tile_state and move.tile_state.effect_type == TileEffectType.BOMB:
    if self._is_gimmick_noticed(TileEffectType.BOMB, profile):
        # 기존 bomb 우선 처리 로직
        base_score += bomb_urgency_bonus
    # else: bomb 인식 못함 - 보너스 없음
```

**롤백 방법**:
- `GIMMICK_NOTICE_RATES` 상수 제거
- `_is_gimmick_noticed()` 함수 제거
- 기믹 관련 점수 계산에서 조건문 제거

**예상 효과**:
- Bomb 레벨: NOVICE/CASUAL 클리어율 15-25% 하향
- Curtain 레벨: 클리어율 10-20% 하향
- 기믹 없는 레벨: 영향 없음

---

### 2.3 Phase 3: Perfect Information 제거 (CRITICAL)

**목적**: Optimal 봇의 비현실적인 hidden 타일 정보 활용 제거

**변경 파일**: `backend/app/core/bot_simulator.py`

**현재 문제 코드** (`_score_move_with_profile` 약 2393-2404줄):
```python
# 현재: Optimal 봇이 hidden 타일 정보 사용
if profile.pattern_recognition >= 1.0:
    total_of_type = state.all_tile_type_counts.get(move.tile_type, 0)  # 숨겨진 타일 포함!
    ...
    remaining_hidden = total_of_type - same_type_accessible - in_dock - 1
    if remaining_hidden >= 1:
        base_score += 15.0  # Hidden 타일 있으니 안전
```

**개선 후**:
```python
# 개선: pattern_recognition < 1.0 기준으로 hidden 정보 차단
HIDDEN_INFO_THRESHOLD = 0.99  # 이 값 이상이면 hidden 정보 사용 (테스트용)

if profile.pattern_recognition >= HIDDEN_INFO_THRESHOLD:
    # 이론적 상한 테스트용 - 기본적으로 비활성화
    total_of_type = state.all_tile_type_counts.get(move.tile_type, 0)
else:
    # 현실적: 보이는 타일만 사용
    type_counts = self._get_accessible_type_counts(state)
    total_of_type = type_counts.get(move.tile_type, 0)
```

**bot_profile.py 변경**:
```python
# OPTIMAL 프로필 수정
BotType.OPTIMAL: BotProfile(
    ...
    pattern_recognition=0.95,  # 0.99 → 0.95 (hidden 정보 사용 안함)
    ...
)
```

**롤백 방법**:
- `HIDDEN_INFO_THRESHOLD = 0.95` 로 변경하면 기존 동작 복원
- 또는 `pattern_recognition=0.99` 로 복원

**예상 효과**:
- OPTIMAL 클리어율: 100% → 95-98%
- 더 현실적인 상한선 제공

---

### 2.4 Phase 4: Dock Panic 메커니즘 강화 (IMPORTANT)

**목적**: Dock이 차면 실수율 증가, 판단력 저하 시뮬레이션

**변경 파일**: `backend/app/core/bot_simulator.py`

**신규 메서드 추가**:
```python
def _apply_dock_panic(self, profile: BotProfile, dock_count: int) -> Tuple[float, int]:
    """Dock 상황에 따른 panic 수치 반환

    Returns:
        (adjusted_mistake_rate, adjusted_lookahead_depth)
    """
    # Panic 시작 임계값 (봇별로 다름)
    panic_thresholds = {
        BotType.NOVICE: 7,   # 거의 패닉 안함 (이미 실수 많음)
        BotType.CASUAL: 5,
        BotType.AVERAGE: 4,
        BotType.EXPERT: 3,
        BotType.OPTIMAL: 2,
    }

    threshold = panic_thresholds.get(profile.bot_type, 5)

    if dock_count < threshold:
        return profile.mistake_rate, profile.lookahead_depth

    # Panic level: 0.0 ~ 1.0
    panic_level = min(1.0, (dock_count - threshold + 1) / (7 - threshold + 1))

    # 실수율 증가 (최대 2배)
    adjusted_mistake = min(0.6, profile.mistake_rate * (1 + panic_level))

    # 선읽기 깊이 감소
    depth_reduction = int(panic_level * 2)
    adjusted_depth = max(0, profile.lookahead_depth - depth_reduction)

    return adjusted_mistake, adjusted_depth
```

**적용 위치**: `_select_move_with_profile()` 시작 부분
```python
def _select_move_with_profile(self, moves, state, profile):
    if not moves:
        return None

    # NEW: Dock panic 적용
    dock_count = len(state.dock_tiles)
    adjusted_mistake, adjusted_depth = self._apply_dock_panic(profile, dock_count)

    # 실수 확률 체크 (adjusted 값 사용)
    if self._rng.random() < adjusted_mistake:
        return self._rng.choice(moves)

    # lookahead 시 adjusted_depth 사용
    ...
```

**롤백 방법**:
- `_apply_dock_panic()` 함수 제거
- 기존 `profile.mistake_rate`, `profile.lookahead_depth` 직접 사용

**예상 효과**:
- Dock 5+ 상황에서 클리어율 5-10% 추가 하향
- 더 현실적인 "위기 상황" 시뮬레이션

---

### 2.5 Phase 5: Curtain 상태 기억 제한 (IMPORTANT)

**목적**: Curtain 상태를 완벽히 추적하지 않고 기억에 의존

**변경 파일**: `backend/app/core/bot_simulator.py`

**GameState에 추가**:
```python
@dataclass
class GameState:
    ...
    # NEW: Curtain 기억 시스템
    curtain_memory: Dict[str, Tuple[bool, int]] = field(default_factory=dict)
    # key: curtain_key, value: (remembered_state, moves_since_seen)
```

**신규 메서드**:
```python
def _update_curtain_memory(self, state: GameState, profile: BotProfile):
    """Curtain 상태 기억 업데이트"""
    memory_duration = {
        BotType.NOVICE: 1,
        BotType.CASUAL: 2,
        BotType.AVERAGE: 3,
        BotType.EXPERT: 5,
        BotType.OPTIMAL: 10,
    }.get(profile.bot_type, 3)

    # 보이는 curtain 상태 기억
    for curtain_key, is_open in state.curtain_tiles.items():
        parts = curtain_key.split('_')
        layer_idx, pos = int(parts[0]), f"{parts[1]}_{parts[2]}"

        layer = state.tiles.get(layer_idx, {})
        tile = layer.get(pos)

        if tile and not self._is_blocked_by_upper(state, tile):
            # 보이는 curtain - 기억 갱신
            state.curtain_memory[curtain_key] = (is_open, 0)
        else:
            # 안 보이는 curtain - 기억 소멸
            if curtain_key in state.curtain_memory:
                remembered, age = state.curtain_memory[curtain_key]
                if age >= memory_duration:
                    del state.curtain_memory[curtain_key]
                else:
                    state.curtain_memory[curtain_key] = (remembered, age + 1)

def _get_perceived_curtain_state(
    self,
    state: GameState,
    curtain_key: str,
    profile: BotProfile
) -> Optional[bool]:
    """플레이어가 인식하는 curtain 상태 (실제와 다를 수 있음)"""
    if curtain_key in state.curtain_memory:
        remembered, age = state.curtain_memory[curtain_key]
        # 기억 정확도: pattern_recognition에 비례
        if self._rng.random() < profile.pattern_recognition:
            return remembered
        else:
            return not remembered  # 잘못된 기억
    return None  # 모름
```

**롤백 방법**:
- `curtain_memory` 필드 제거
- 관련 메서드 제거
- 기존 `state.curtain_tiles` 직접 사용

**예상 효과**:
- Curtain 레벨에서 NOVICE/CASUAL 클리어율 5-10% 하향

---

## 3. 구현 순서 및 체크리스트

### 3.1 권장 구현 순서

```
Phase 1 (Attention Zone) → Phase 3 (Perfect Info 제거) → Phase 2 (기믹 인식률)
→ Phase 4 (Dock Panic) → Phase 5 (Curtain 기억)
```

**이유**:
1. Attention Zone: 가장 기본적인 개선, 다른 개선과 독립적
2. Perfect Info: Optimal 봇 현실화, 상한선 조정
3. 기믹 인식률: 기믹 난이도 정확도 개선
4. Dock Panic: 위기 상황 현실화
5. Curtain 기억: 세부 조정

### 3.2 구현 체크리스트

```markdown
## Phase 1: Attention Zone
- [ ] `_filter_by_attention()` 메서드 추가
- [ ] `_select_move_with_profile()`에서 호출
- [ ] 단위 테스트 작성
- [ ] 클리어율 변화 측정

## Phase 2: 기믹 인식률
- [ ] `GIMMICK_NOTICE_RATES` 상수 추가
- [ ] `_is_gimmick_noticed()` 메서드 추가
- [ ] `_score_move_with_profile()`에 적용
- [ ] 기믹별 테스트

## Phase 3: Perfect Information 제거
- [ ] `HIDDEN_INFO_THRESHOLD` 상수 추가
- [ ] `_score_move_with_profile()` 수정
- [ ] OPTIMAL 프로필 `pattern_recognition` 조정
- [ ] 클리어율 상한 테스트

## Phase 4: Dock Panic
- [ ] `_apply_dock_panic()` 메서드 추가
- [ ] `_select_move_with_profile()`에 적용
- [ ] Dock 상황별 테스트

## Phase 5: Curtain 기억
- [ ] `curtain_memory` 필드 추가
- [ ] `_update_curtain_memory()` 메서드 추가
- [ ] `_get_perceived_curtain_state()` 메서드 추가
- [ ] Curtain 레벨 테스트
```

---

## 4. 롤백 가이드

### 4.1 전체 롤백

모든 개선을 롤백하려면:

```bash
git checkout HEAD~N -- backend/app/core/bot_simulator.py
git checkout HEAD~N -- backend/app/models/bot_profile.py
```

### 4.2 개별 롤백

각 Phase별로 독립적 롤백 가능:

| Phase | 롤백 대상 | 방법 |
|-------|----------|------|
| 1 | Attention Zone | `_filter_by_attention()` 삭제, `visible_moves = moves` |
| 2 | 기믹 인식률 | `GIMMICK_NOTICE_RATES` 삭제, 조건문 제거 |
| 3 | Perfect Info | `HIDDEN_INFO_THRESHOLD = 0.95`, `pattern_recognition=0.99` |
| 4 | Dock Panic | `_apply_dock_panic()` 삭제 |
| 5 | Curtain 기억 | `curtain_memory` 필드 및 관련 메서드 삭제 |

### 4.3 Feature Flag 방식 (권장)

```python
# bot_simulator.py 상단에 추가
class BotSimulatorConfig:
    ENABLE_ATTENTION_ZONE = True      # Phase 1
    ENABLE_GIMMICK_NOTICE = True      # Phase 2
    ENABLE_HIDDEN_INFO_BLOCK = True   # Phase 3
    ENABLE_DOCK_PANIC = True          # Phase 4
    ENABLE_CURTAIN_MEMORY = True      # Phase 5

# 사용 예시
def _select_move_with_profile(self, moves, state, profile):
    if BotSimulatorConfig.ENABLE_ATTENTION_ZONE:
        moves = self._filter_by_attention(moves, state, profile)
    ...
```

이 방식으로 런타임에 개별 기능 ON/OFF 가능.

---

## 5. 테스트 계획

### 5.1 기준 레벨 세트

개선 전후 비교를 위한 표준 테스트 레벨:

| 레벨 ID | 특성 | 기대 클리어율 (AVERAGE) |
|---------|------|------------------------|
| test_simple | 기믹 없음, 3레이어 | 85-95% |
| test_ice_basic | Ice만 존재 | 75-85% |
| test_bomb_urgent | Bomb countdown 3 | 60-75% |
| test_curtain_complex | Curtain 다수 | 65-80% |
| test_mixed_gimmick | 복합 기믹 | 55-70% |

### 5.2 A/B 테스트 메트릭

```python
# 개선 전후 비교 스크립트
def compare_before_after(level_json, iterations=500):
    # Before (현재)
    before_results = run_simulation_v1(level_json, iterations)

    # After (개선)
    after_results = run_simulation_v2(level_json, iterations)

    return {
        'clear_rate_delta': {
            bot: after_results[bot].clear_rate - before_results[bot].clear_rate
            for bot in BotType.all_types()
        },
        'moves_delta': {...},
        'variance_change': {...}
    }
```

---

## 6. 예상 결과 요약

### 6.1 클리어율 변화 예측

| Bot Type | 현재 (추정) | 개선 후 (목표) | 변화량 |
|----------|-------------|----------------|--------|
| NOVICE | 45-55% | 30-40% | -15% |
| CASUAL | 65-75% | 55-65% | -10% |
| AVERAGE | 80-88% | 70-80% | -10% |
| EXPERT | 92-97% | 85-95% | -5% |
| OPTIMAL | 99-100% | 95-98% | -3% |

### 6.2 기믹별 난이도 반영 개선

| 기믹 | 현재 난이도 반영 | 개선 후 |
|------|------------------|---------|
| Ice | 적절 | 유지 |
| Chain | 적절 | 유지 |
| Bomb | 과소평가 | 정상화 (+15-25% 난이도) |
| Curtain | 과소평가 | 정상화 (+10-20% 난이도) |
| Teleport | 과소평가 | 정상화 (+10-15% 난이도) |
| Frog | 과소평가 | 정상화 (+5-10% 난이도) |

---

## 7. 관련 문서

- `claudedocs/bot_simulation_improvement_design.md` - 성능 최적화 설계 (별도)
- `backend/app/models/bot_profile.py` - 봇 프로필 정의
- `backend/app/core/bot_simulator.py` - 시뮬레이터 구현

---

## Appendix A: 현재 코드 백업 위치

구현 전 현재 상태 백업:
```bash
# 백업 명령어
cp backend/app/core/bot_simulator.py backend/app/core/bot_simulator.py.backup_20260210
cp backend/app/models/bot_profile.py backend/app/models/bot_profile.py.backup_20260210
```

## Appendix B: 변경 이력

| 날짜 | 버전 | 변경 내용 |
|------|------|----------|
| 2026-02-10 | v1.0 | 초안 작성 |
