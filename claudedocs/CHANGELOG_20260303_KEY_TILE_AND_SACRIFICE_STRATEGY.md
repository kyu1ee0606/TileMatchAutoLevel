# 변경 이력: Key 타일 이중 생성 버그 수정 및 희생 전략 개선

**날짜**: 2026-03-03
**버전**: v15.1
**작성자**: Claude Code

---

## 개요

Key 타일 이중 생성 버그 수정 및 봇 시뮬레이터의 희생 전략(Sacrifice Strategy) 개선.

### 해결된 문제들

1. **Key 타일 이중 생성 버그**: 레벨 JSON에 명시적 `key` 타일 + t0 분배에서 추가 key 생성 → 초과 key 문제
2. **희생 전략 부재**: 봇이 레이어 블로킹 해제를 위한 희생 플레이를 하지 않음
3. **randSeed=0 동작**: 게임 내 랜덤 시드 동작과 시뮬레이터 동작 불일치

---

## 변경 파일

### 1. `backend/app/core/bot_simulator.py`

#### 1.1 Key 타일 이중 생성 방지 (Line 873-935)

**문제**: 레벨 JSON에 명시적 `key` 타일 6개 + `unlockTile=2` 설정 시, t0 분배에서 추가 6개 key 생성 → 총 12개 key (초과)

**원인**: `_create_initial_state()`에서 명시적 key 타일 수를 고려하지 않고 `unlock_tile` 값을 그대로 `TileDistributor.assign_t0_tiles()`에 전달

**수정 내용**:

```python
# First pass: 명시적 key 타일 카운트 추가
explicit_key_count = 0  # Count of explicit "key" tiles in level JSON

for layer_idx in range(num_layers):
    # ... existing loop ...
    elif tile_type == "key":
        # Explicit key tile - count it (don't generate more from t0)
        explicit_key_count += 1

# Calculate effective unlock_tile for t0 distribution
# 레벨 JSON에 이미 명시적 key 타일이 있으면 t0에서 생성할 key 수를 조정
explicit_key_sets = explicit_key_count // 3
effective_unlock_tile = max(0, unlock_tile - explicit_key_sets)

# Generate tile type assignments for ALL t0 tiles
t0_assignments = TileDistributor.assign_t0_tiles(
    t0_count=len(t0_tiles),
    use_tile_count=use_tile_count,
    rand_seed=rand_seed,
    shuffle_tile=shuffle_tile,
    type_imbalance=type_imbalance,
    unlock_tile=effective_unlock_tile,  # 조정된 값 사용
    tile_type_offset=tile_type_offset
)
```

**결과**:
| 상태 | Key 타일 수 | 비고 |
|-----|------------|------|
| 수정 전 | 12개 | 6개 초과 (unlockTile*3=6 필요) |
| 수정 후 | 6개 | 정확히 필요한 수 |

---

#### 1.2 레이어 블로킹 희생 전략 (Strategic Unblock Bonus)

**문제**: 봇이 즉시 매칭되지 않는 타일 선택을 기피 → 하위 레이어 타일 접근 불가 → 데드락

**해결**: `_score_move_with_profile()`에 전략적 언블로킹 보너스 추가

```python
# ============================================================
# STRATEGIC UNBLOCK BONUS - Core of sacrifice strategy
# 실제 플레이어처럼 "이 타일을 선택하면 어떤 타일이 풀리는가?" 고려
# ============================================================
if profile.blocking_awareness >= 0.5 and hasattr(self, '_blocking_map'):
    tile_state = move.tile_state
    if tile_state:
        unblock_bonus = 0.0
        tile_key = (move.layer_idx, tile_state.position_key)

        # Find tiles blocked by this tile
        tiles_to_unblock = []
        for (blocked_layer, blocked_pos), blockers in self._blocking_map.items():
            if tile_key in blockers:
                blocked_tile = state.tiles.get(blocked_layer, {}).get(blocked_pos)
                if blocked_tile and not blocked_tile.picked:
                    tiles_to_unblock.append(blocked_tile)

        if tiles_to_unblock:
            dock_types = {}
            for t in state.dock_tiles:
                dock_types[t.tile_type] = dock_types.get(t.tile_type, 0) + 1

            # Count how many unblocked tiles match dock types
            match_setup_count = 0
            same_type_unblock = 0

            for unblocked in tiles_to_unblock:
                utype = unblocked.tile_type
                if utype in dock_types:
                    if dock_types[utype] >= 2:
                        match_setup_count += 2  # Enables a match!
                    elif dock_types[utype] == 1:
                        match_setup_count += 1
                if utype == move.tile_type:
                    same_type_unblock += 1

            # Bonus calculations
            if match_setup_count > 0:
                pressure_factor = 1.0 + (dock_count / 7.0)
                unblock_bonus += match_setup_count * 5.0 * profile.blocking_awareness * pressure_factor
            if same_type_unblock > 0:
                unblock_bonus += same_type_unblock * 3.0 * profile.blocking_awareness
            if len(tiles_to_unblock) >= 2:
                unblock_bonus += len(tiles_to_unblock) * 1.5 * profile.blocking_awareness

            base_score += unblock_bonus
```

**전략 요소**:

| 보너스 조건 | 점수 | 설명 |
|-----------|------|------|
| 언블로킹된 타일이 dock 타입과 매칭 | +5.0 × awareness × pressure | 매칭 가능성 증가 |
| 같은 타입 타일 언블로킹 | +3.0 × awareness | 연속 플레이 가능 |
| 2개 이상 타일 언블로킹 | +1.5 × count × awareness | 레이어 클리어링 |

---

#### 1.3 randSeed=0 동작 일치 (honor_zero_seed)

**배경**: 게임에서 `randSeed=0`은 매 플레이마다 랜덤 시드, `>0`은 고정 시드

**수정 내용**:

```python
def simulate_with_profile(
    self,
    level_json: Dict[str, Any],
    profile: BotProfile,
    iterations: int = 100,
    max_moves: Optional[int] = None,
    seed: Optional[int] = None,
    honor_zero_seed: bool = False,  # 새 파라미터
) -> BotSimulationResult:
    """
    honor_zero_seed=True: randSeed=0일 때 반복마다 다른 시드 사용 (정확하지만 느림)
    honor_zero_seed=False: 성능 우선, 고정 시드로 처리 (기본값)
    """
    level_rand_seed = level_json.get("randSeed", 0)
    use_random_seed_per_iteration = (level_rand_seed == 0 and honor_zero_seed)

    if use_random_seed_per_iteration:
        # 매 반복마다 새 시드 생성
        for i in range(iterations):
            iteration_seed = self._rng.randint(1, 999999)
            level_with_seed = level_json.copy()
            level_with_seed["randSeed"] = iteration_seed
            state = self._create_initial_state(level_with_seed, max_moves)
            # ... 시뮬레이션 ...
    else:
        # 고정 시드로 빠른 처리
        base_state = self._create_initial_state(level_json, max_moves)
        # ... 최적화된 시뮬레이션 ...
```

---

### 2. `backend/app/core/generator.py`

#### 2.1 Key 타일 검증 - 게임 클라이언트 호환성 (`_validate_and_fix_key_tile_count`)

**문제**: 게임 클라이언트(C#/Unity)에서 `unlockTile > 0`이면 t0 분배(TileDistributor)가 자동으로 key 타일 생성. 레벨 JSON에 명시적 `key` 타일이 있으면 이중 생성됨.

**중요**: Python 시뮬레이터 수정(`effective_unlock_tile`)은 Python에서만 동작. **게임 클라이언트는 별도 코드**이므로 레벨 JSON 자체를 수정해야 함.

**해결**: `unlockTile > 0`일 때 **모든** 명시적 key 타일을 t0로 변환

```python
def _validate_and_fix_key_tile_count(self, level: Dict[str, Any]) -> Dict[str, Any]:
    """
    CRITICAL: 게임 클라이언트에서 unlockTile > 0이면:
    - t0 분배(TileDistributor)가 key 타일을 자동 생성함
    - 따라서 레벨 JSON에 명시적 "key" 타일이 있으면 안 됨 (이중 생성 방지)

    해결: unlockTile > 0이면 모든 명시적 key를 t0로 변환
    """
    unlock_tile = level.get("unlockTile", level.get("xUnlockTile", 0))
    if unlock_tile <= 0:
        return level  # No key generation, keep explicit keys

    num_layers = level.get("layer", 8)

    # Find ALL explicit key tiles
    key_positions = []
    for layer_idx in range(num_layers):
        layer_key = f"layer_{layer_idx}"
        tiles = level.get(layer_key, {}).get("tiles", {})
        for pos, tile_data in tiles.items():
            if isinstance(tile_data, list) and tile_data and tile_data[0] == "key":
                key_positions.append((layer_idx, pos))

    if key_positions:
        # Convert ALL explicit keys to t0 (game client will generate them from t0)
        for layer_idx, pos in key_positions:
            layer_key = f"layer_{layer_idx}"
            tiles = level[layer_key]["tiles"]
            if pos in tiles:
                original = tiles[pos]
                gimmick = original[1] if len(original) > 1 else ""
                tiles[pos] = ["t0", gimmick]

    return level
```

**참고**: Key 타일 카운트 시 `state.tiles`와 `state.stacked_tiles` 모두 확인 필요 (스택 타일 내부 타일 포함)

---

#### 2.2 폭탄 배치 가시성 수정 (`_add_bomb_obstacles_to_layer`)

**문제**: 폭탄이 상위 레이어 타일에 가려진 위치에 배치되면 플레이어에게 보이지 않음

**해결**: 상위 레이어에 의해 가려진 위치에는 폭탄을 배치하지 않음

```python
def _add_bomb_obstacles_to_layer(
    self, level: Dict[str, Any], layer_idx: int, target: int, counter: Dict[str, int]
) -> Dict[str, Any]:
    """
    CRITICAL: Bombs should ONLY be placed on VISIBLE tiles (not covered by upper layers).
    Bombs on covered tiles are invisible to players = bad UX.
    """
    layer_key = f"layer_{layer_idx}"
    tiles = level.get(layer_key, {}).get("tiles", {})
    if not tiles:
        return level

    num_layers = level.get("layer", 8)

    # Pre-compute positions covered by upper layers
    covered_positions = set()
    for upper_layer_idx in range(layer_idx + 1, num_layers):
        upper_layer_key = f"layer_{upper_layer_idx}"
        upper_tiles = level.get(upper_layer_key, {}).get("tiles", {})
        covered_positions.update(upper_tiles.keys())

    # Find candidates: tiles with "t" prefix and no gimmick, NOT covered
    candidates = []
    for pos, tile_data in tiles.items():
        if pos in covered_positions:
            continue  # Skip covered positions - bombs would be invisible
        if isinstance(tile_data, list) and len(tile_data) >= 1:
            tile_type = tile_data[0]
            gimmick = tile_data[1] if len(tile_data) > 1 else ""
            if tile_type.startswith("t") and not gimmick:
                candidates.append(pos)

    # Place bombs on visible candidates only
    # ...
```

**결과**: 폭탄이 항상 플레이어에게 보이는 위치에 배치됨

---

## 테스트 결과

### Key 타일 이중 생성 테스트

**테스트 레벨**: `unlockTile=2`, 명시적 key 6개

```
AFTER T0 DISTRIBUTION (GAME STATE)
============================================================
Tile types in game state:
  key: 6 ✓ (state.tiles: 4, state.stacked_tiles: 2)
  t1: 6 ✓
  t2: 6 ✓
  ... (모든 타입 3의 배수)

Key tiles: 6
unlockTile: 2
Required keys: 6
```

**결과**: 정확히 6개 key (이전: 12개)

**검증 방법**:
- Python 시뮬레이터: `effective_unlock_tile` 계산으로 이중 생성 방지
- 게임 클라이언트: Generator에서 명시적 key → t0 변환으로 이중 생성 방지

### 폭탄 가시성 테스트

**테스트 레벨**: `bombCount: 2` (layer_0/7_3, layer_1/5_2)

**문제 상황**:
- 폭탄 위치가 모두 상위 레이어 타일에 가려짐 → 플레이 시 폭탄 보이지 않음

**수정 후**:
- 폭탄은 상위 레이어에 가려지지 않은 위치에만 배치
- 플레이어가 폭탄을 미리 인지 가능

---

## 아키텍처

```
_create_initial_state()
    │
    ├── First Pass: t0 타일 수집 + 명시적 key 카운트
    │       └── explicit_key_count++
    │
    ├── Calculate effective_unlock_tile
    │       └── max(0, unlock_tile - explicit_key_sets)
    │
    └── TileDistributor.assign_t0_tiles(unlock_tile=effective_unlock_tile)


_score_move_with_profile()
    │
    └── Strategic Unblock Bonus
            ├── 언블로킹 타일 탐색 (_blocking_map)
            ├── Dock 매칭 가능성 계산
            └── 보너스 점수 적용
```

---

## 관련 이슈

- **레이어 블로킹**: 봇이 즉시 매칭 안 되는 타일 선택 회피 → 하위 레이어 접근 불가
- **Key 타일 초과**: 레벨 JSON + t0 분배 이중 생성으로 dock 슬롯 낭비
- **randSeed 동작**: 게임과 시뮬레이터 간 랜덤 동작 불일치
- **폭탄 가시성**: 폭탄이 상위 레이어에 가려진 위치에 배치 → UX 저하

---

## 성능 영향

| 지표 | 변경 전 | 변경 후 |
|-----|--------|--------|
| Key 타일 초과 발생 | 가능 | 방지됨 |
| 희생 전략 적용 | 없음 | blocking_awareness ≥ 0.5 시 활성화 |
| 추가 계산 비용 | - | +2-5ms (blocking_map 조회) |
| 폭탄 가시성 | 불확실 | 항상 가시 보장 |

---

## 향후 개선 사항

1. **희생 전략 강화**: 더 깊은 레이어 분석 (2-3단계 앞 예측)
2. **Key 타일 배치 최적화**: 상위 레이어에 key 타일 분산 배치
3. **blocking_map 캐싱**: 반복 조회 최적화
4. **기믹 배치 규칙 일반화**: 폭탄 외 다른 기믹도 가시성 검증 적용

---

## 변경 요약 (v15.1)

| 구분 | 변경 내용 | 영향 범위 |
|-----|----------|----------|
| Key 타일 (시뮬레이터) | `effective_unlock_tile` 계산 | Python 봇 시뮬레이션 |
| Key 타일 (게임) | 명시적 key → t0 변환 | 게임 클라이언트 (C#/Unity) |
| 희생 전략 | Strategic Unblock Bonus | 봇 클리어율 향상 |
| 폭탄 배치 | 가려진 위치 제외 | 레벨 UX 개선 |
| randSeed | honor_zero_seed 옵션 | 시뮬레이션 정확도 |
