# 게임 로직 수정 사양서 (Modification Specification)

## 1. 개요

본 문서는 `sp_template` 참조 프로젝트의 게임 동작을 정확히 구현하기 위한 `bot_simulator.py` 수정 사양을 정의합니다.

### 참조 파일
- **sp_template 프로젝트**
  - `Dock.cs` - 독 시스템 및 매칭 로직
  - `TileGroup.cs` - 레벨 관리 및 레이어 블로킹
  - `TileEffect.cs` - 기믹 효과 처리
  - `Tile.cs` - 타일 상태 및 동작
  - `TileCraft.cs` - Craft 기믹 처리
  - `FrogManager.cs` - 개구리 이동 로직

- **수정 대상**
  - `backend/app/core/bot_simulator.py`

---

## 2. 수정 항목 요약

| ID | 항목 | 우선순위 | 영향도 | 상태 |
|----|------|---------|-------|------|
| MOD-001 | 레이어 블로킹 로직 | 🔴 Critical | High | 수정 필요 |
| MOD-002 | 커튼(Curtain) 토글 동작 | 🔴 Critical | High | 수정 필요 |
| MOD-003 | 개구리(Frog) 이동 조건 | 🟡 Important | Medium | 확인 필요 |
| MOD-004 | 얼음(Ice) 초기값 | 🟢 Minor | Low | 구현 완료 |
| MOD-005 | 풀(Grass) 초기값 | 🟢 Minor | Low | 구현 완료 |
| MOD-006 | 폭탄(Bomb) 카운트 파싱 | 🟡 Important | Medium | 확인 필요 |
| MOD-007 | 체인(Chain) 해제 조건 | 🟢 Minor | Low | 구현 완료 |
| MOD-008 | 독 풀 체크 타이밍 | 🟡 Important | Medium | 확인 필요 |

---

## 3. 상세 수정 사양

### MOD-001: 레이어 블로킹 로직 수정

#### 현재 구현 (bot_simulator.py:959-979)
```python
def _is_blocked_by_upper(self, state: GameState, tile: TileState) -> bool:
    blocking_positions = [
        (tile.x_idx, tile.y_idx),
        (tile.x_idx - 1, tile.y_idx),
        (tile.x_idx, tile.y_idx - 1),
        (tile.x_idx - 1, tile.y_idx - 1),
    ]
    # 모든 상위 레이어에 대해 동일한 오프셋 적용
```

#### sp_template 참조 (TileGroup.cs:274-329)
```csharp
public List<Tile> FindAllUpperTiles(int layerIndex, int xIndex, int yIndex)
{
    int curLayerIndexState = layerIndex % 2;  // 현재 레이어 홀짝 판별

    for (int i = layerIndex + 1; i < xLayer.AsInt; i++)
    {
        // 같은 패리티 (odd,odd 또는 even,even)
        if (curLayerIndexState == upperLayerIndex % 2)
        {
            checkTileList.Add(GetTile(upperLayerIndex, tileX, tileY));
        }
        else
        {
            if (cUpperLayer.xCol.AsInt > curLayer.xCol.AsInt)
            {
                // 상위 레이어가 더 큰 경우: (0,0), (1,0), (0,1), (1,1)
                checkTileList.Add(GetTile(upperLayerIndex, tileX, tileY));
                checkTileList.Add(GetTile(upperLayerIndex, tileX + 1, tileY));
                checkTileList.Add(GetTile(upperLayerIndex, tileX, tileY + 1));
                checkTileList.Add(GetTile(upperLayerIndex, tileX + 1, tileY + 1));
            }
            else
            {
                // 상위 레이어가 더 작은 경우: (-1,-1), (0,-1), (-1,0), (0,0)
                checkTileList.Add(GetTile(upperLayerIndex, tileX - 1, tileY - 1));
                checkTileList.Add(GetTile(upperLayerIndex, tileX, tileY - 1));
                checkTileList.Add(GetTile(upperLayerIndex, tileX - 1, tileY));
                checkTileList.Add(GetTile(upperLayerIndex, tileX, tileY));
            }
        }
    }
}
```

#### 수정 요구사항
1. **레이어 패리티 판별 추가**: 현재 레이어와 상위 레이어의 홀짝(parity) 비교
2. **레이어 크기 비교 로직 추가**: 레이어별 col 값을 저장하고 비교
3. **조건부 오프셋 적용**:
   - 같은 패리티: 동일 위치만 체크
   - 다른 패리티 + 상위가 큼: (0,0), (+1,0), (0,+1), (+1,+1)
   - 다른 패리티 + 상위가 작음: (-1,-1), (0,-1), (-1,0), (0,0)

#### 수정 코드
```python
def _is_blocked_by_upper(self, state: GameState, tile: TileState) -> bool:
    """Check if a tile is blocked by tiles in upper layers.

    Based on sp_template TileGroup.FindAllUpperTiles():
    - Same parity layers (odd-odd or even-even): check same position only
    - Different parity + upper larger: check (0,0), (+1,0), (0,+1), (+1,+1)
    - Different parity + upper smaller: check (-1,-1), (0,-1), (-1,0), (0,0)
    """
    cur_layer_parity = tile.layer_idx % 2
    cur_layer_col = self._get_layer_col_size(state, tile.layer_idx)

    for upper_layer_idx in range(tile.layer_idx + 1, max(state.tiles.keys()) + 1 if state.tiles else 0):
        upper_layer = state.tiles.get(upper_layer_idx, {})
        if not upper_layer:
            continue

        upper_layer_parity = upper_layer_idx % 2
        upper_layer_col = self._get_layer_col_size(state, upper_layer_idx)

        if cur_layer_parity == upper_layer_parity:
            # Same parity: check same position only
            blocking_positions = [(tile.x_idx, tile.y_idx)]
        elif upper_layer_col > cur_layer_col:
            # Upper layer is bigger
            blocking_positions = [
                (tile.x_idx, tile.y_idx),
                (tile.x_idx + 1, tile.y_idx),
                (tile.x_idx, tile.y_idx + 1),
                (tile.x_idx + 1, tile.y_idx + 1),
            ]
        else:
            # Upper layer is smaller
            blocking_positions = [
                (tile.x_idx - 1, tile.y_idx - 1),
                (tile.x_idx, tile.y_idx - 1),
                (tile.x_idx - 1, tile.y_idx),
                (tile.x_idx, tile.y_idx),
            ]

        for bx, by in blocking_positions:
            pos_key = f"{bx}_{by}"
            if pos_key in upper_layer and not upper_layer[pos_key].picked:
                return True

    return False

def _get_layer_col_size(self, state: GameState, layer_idx: int) -> int:
    """Get the column size for a specific layer."""
    return state.layer_col_sizes.get(layer_idx, 7)  # Default 7
```

#### 추가 필요 사항
- `GameState`에 `layer_col_sizes: Dict[int, int]` 필드 추가
- `_create_initial_state()`에서 레이어별 col 값 파싱하여 저장

---

### MOD-002: 커튼(Curtain) 토글 동작 수정

#### 현재 구현 (bot_simulator.py:1230-1236)
```python
# Toggle curtains (simplified)
for layer in state.tiles.values():
    for tile in layer.values():
        if tile.effect_type == TileEffectType.CURTAIN and not tile.picked:
            # 30% chance to toggle (랜덤)
            if self._rng.random() < 0.3:
                tile.effect_data["is_open"] = not tile.effect_data.get("is_open", True)
```

#### sp_template 참조 (TileEffect.cs:903-928)
```csharp
else if (e_TileEffectType == TileEffectType.Curtain)
{
    if (otherTile.m_Picked || tile.CheckUpperTileExist()) return;

    if (otherTile.m_selectedFirst == false)
    {
        return;
    }

    if (curtainActive)
    {
        curtainActive = false;
        canPick = true;
        SetCurtainAnim(CurtainAnimState.open);
    }
    else
    {
        curtainActive = true;
        canPick = false;
        SetCurtainAnim(CurtainAnimState.close);
    }
}
```

#### sp_template 초기 상태 (TileEffect.cs:488-507)
```csharp
else if (e_TileEffectType == TileEffectType.Curtain)
{
    // curtain_close 또는 curtain_open 값을 레벨 데이터에서 읽음
    string curtainString = tile.cTile.xEffect.AsString;

    if (curtainString == "curtain_close")
    {
        curtainActive = true;  // 닫힘 = 선택 불가
        canPick = false;
    }
    else  // curtain_open
    {
        curtainActive = false;  // 열림 = 선택 가능
        canPick = true;
    }
}
```

#### 수정 요구사항
1. **랜덤 토글 제거**: 30% 랜덤 토글 로직 삭제
2. **결정론적 동작**: 다른 타일 선택 시 **항상** 커튼 상태 토글
3. **초기 상태 보존**: `curtain_close` → 닫힘, `curtain_open` → 열림
4. **토글 조건**: 상위 타일에 막혀있지 않을 때만 토글

#### 수정 코드
```python
def _process_move_effects(self, state: GameState) -> None:
    """Process effects that trigger after each move."""
    # ... bomb, frog 처리 ...

    # Curtain toggle (deterministic based on sp_template)
    # All curtains that are not blocked by upper tiles toggle their state
    for layer in state.tiles.values():
        for tile in layer.values():
            if tile.effect_type == TileEffectType.CURTAIN and not tile.picked:
                # Only toggle if not blocked by upper layer
                if not self._is_blocked_by_upper(state, tile):
                    tile.effect_data["is_open"] = not tile.effect_data.get("is_open", True)
```

---

### MOD-003: 개구리(Frog) 이동 조건 확인

#### 현재 구현 (bot_simulator.py:1141-1176)
```python
def _get_frog_movable_tiles(self, state: GameState) -> List[Tuple[int, str, TileState]]:
    """Frogs can move to any selectable tile that:
    - Is not picked
    - Is not blocked by upper layer
    - Does not already have a frog on it
    - Is a matchable tile type (not goal tiles)
    """
```

#### sp_template 참조 (TileGroup.cs:1088-1105)
```csharp
public List<Tile> GetCanFrogMoveTileList(bool exceptUndoSetTile = true)
{
    canFrogMoveTileList.Clear();
    Tile checkTile;

    for (int i = 0; i < c_TileList.Count; i++)
    {
        checkTile = c_TileList[i];

        if (exceptUndoSetTile && checkTile.isUndoStackTile) continue;

        if (checkTile.tileEffect.onFrog || checkTile.onAnim) continue;

        // CheckMask() = 타일이 선택 가능한지 확인 (효과 + 블로킹)
        if (checkTile.CheckMask() == false &&
            checkTile.m_SelectedByHint == false &&
            checkTile.m_Picked == false)
            canFrogMoveTileList.Add(checkTile);
    }

    return canFrogMoveTileList;
}
```

#### 확인 필요 사항
- 현재 구현이 sp_template과 일치하는지 검증 필요
- `CheckMask()` 함수의 정확한 동작 확인 필요
- Undo 스택 타일 제외 로직이 필요한지 확인

#### 상태: ✅ 대부분 일치 (미세 조정 필요할 수 있음)

---

### MOD-004: 얼음(Ice) 초기값

#### sp_template 참조 (TileEffect.cs)
```csharp
iceEffectRemainCount = 3;  // 항상 3으로 시작
```

#### 현재 구현 상태
```python
# Ice: remaining layers (1-3)
adj_tile.effect_data.get("remaining", 0)
```

#### 상태: ✅ 구현 완료 (초기값 3으로 설정되어 있음)

---

### MOD-005: 풀(Grass) 초기값

#### sp_template 참조 (TileEffect.cs)
```csharp
grassEffectRemainCount = 2;  // 항상 2로 시작
```

#### 현재 구현 상태
```python
# Grass: remaining (1-2)
adj_tile.effect_data.get("remaining", 0)
```

#### 상태: ✅ 구현 완료 (초기값 2로 설정되어 있음)

---

### MOD-006: 폭탄(Bomb) 카운트 파싱

#### sp_template 참조 (TileEffect.cs:508-518)
```csharp
else if (e_TileEffectType == TileEffectType.Bomb)
{
    bombEffectRemainCount = spInteger.Parse(tile.cTile.xEffect.AsString);
    // "bomb_5" 또는 "5" 형태에서 숫자 파싱
}
```

#### 현재 구현 확인 필요
- `xEffect.AsString`에서 숫자를 정확히 파싱하는지 확인
- "bomb_5" 형태일 경우 언더스코어 이후 숫자 추출

#### 수정 코드 (필요시)
```python
def _parse_bomb_count(self, effect_string: str) -> int:
    """Parse bomb count from effect string like 'bomb_5' or just '5'."""
    if "_" in effect_string:
        parts = effect_string.split("_")
        return int(parts[-1]) if parts[-1].isdigit() else 5
    return int(effect_string) if effect_string.isdigit() else 5
```

---

### MOD-007: 체인(Chain) 해제 조건

#### sp_template 참조 (TileEffect.cs:883-902)
```csharp
else if (e_TileEffectType == TileEffectType.Chain)
{
    if (otherTile.m_Picked) return;
    if (chainRemoved) return;

    // IsNearTile(otherTile, true) = 수평(좌우) 인접만 체크
    if (tile.IsNearTile(otherTile, true) &&
        (tile.CheckUpperTileExist() == false || otherTile.m_SelectedByHint))
    {
        canPick = true;
        chainRemoved = true;
    }
}
```

#### 현재 구현 (bot_simulator.py:1099-1110)
```python
# Chain effect: horizontal only
for adj_x, adj_y in horizontal_positions:  # [(x+1, y), (x-1, y)]
    # ...
    if adj_tile.effect_type == TileEffectType.CHAIN:
        adj_tile.effect_data["unlocked"] = True
```

#### 상태: ✅ 구현 완료 (수평 인접 조건 적용됨)

---

### MOD-008: 독 풀 체크 타이밍

#### sp_template 참조 (Dock.cs)
```csharp
public void AddTile(Tile tile, bool checkOnChangeTileList = true)
{
    if (IsLevelEnd()) return;
    if (tile.m_Picked) return;
    tile.m_Picked = true;

    // ... 타일 추가 로직 ...
    tileList.Add(tile);

    if (checkOnChangeTileList) {
        OnChangeTileList();  // 매칭 체크
        CheckGameFail();     // 게임 실패 체크
    }
}
```

#### 현재 구현 확인 필요
- 타일 추가 후 매칭 처리 순서
- 게임 실패 체크 타이밍

#### 상태: 🟡 확인 필요 (기능적으로 동일할 가능성 높음)

---

## 4. GameState 데이터 구조 수정

### 추가 필드
```python
@dataclass
class GameState:
    # ... 기존 필드 ...

    # 레이어별 col 크기 (MOD-001 지원)
    layer_col_sizes: Dict[int, int] = field(default_factory=dict)

    # 레이어별 row 크기 (필요시)
    layer_row_sizes: Dict[int, int] = field(default_factory=dict)
```

### _create_initial_state 수정
```python
def _create_initial_state(self, level_json: Dict[str, Any], max_moves: int) -> GameState:
    state = GameState(max_moves=max_moves)

    # 레이어 크기 정보 파싱
    total_layers = level_json.get("layer", 0)
    for layer_idx in range(total_layers):
        layer_key = f"layer_{layer_idx}"
        layer_data = level_json.get(layer_key, {})

        col = int(layer_data.get("col", 7))
        row = int(layer_data.get("row", 7))

        state.layer_col_sizes[layer_idx] = col
        state.layer_row_sizes[layer_idx] = row

        # ... 기존 타일 파싱 로직 ...
```

---

## 5. 테스트 케이스

### TC-001: 레이어 블로킹 테스트
```python
def test_layer_blocking_same_parity():
    """같은 패리티 레이어 간 블로킹 테스트 (layer 0 → layer 2)"""
    # Expected: 동일 위치만 체크
    pass

def test_layer_blocking_different_parity_upper_bigger():
    """다른 패리티 + 상위가 큰 경우 테스트 (layer 0 → layer 1, col 7→8)"""
    # Expected: (0,0), (+1,0), (0,+1), (+1,+1) 체크
    pass

def test_layer_blocking_different_parity_upper_smaller():
    """다른 패리티 + 상위가 작은 경우 테스트 (layer 0 → layer 1, col 7→6)"""
    # Expected: (-1,-1), (0,-1), (-1,0), (0,0) 체크
    pass
```

### TC-002: 커튼 동작 테스트
```python
def test_curtain_deterministic_toggle():
    """커튼 결정론적 토글 테스트"""
    # Expected: 타일 선택 시 항상 토글 (랜덤 아님)
    pass

def test_curtain_initial_state():
    """커튼 초기 상태 테스트"""
    # curtain_close → is_open=False
    # curtain_open → is_open=True
    pass
```

---

## 6. 구현 우선순위

1. **Phase 1 (Critical)** - 즉시 수정
   - MOD-001: 레이어 블로킹 로직
   - MOD-002: 커튼 토글 동작

2. **Phase 2 (Important)** - 검증 후 수정
   - MOD-003: 개구리 이동 조건 검증
   - MOD-006: 폭탄 카운트 파싱 검증
   - MOD-008: 독 풀 체크 타이밍 검증

3. **Phase 3 (Minor)** - 확인/문서화
   - MOD-004, MOD-005, MOD-007: 구현 완료 확인

---

## 7. 참조 문서

- [SPECIFICATION.md](./SPECIFICATION.md) - 기술 사양서
- [sp_template 소스 코드](../Documents/sp_template/Assets/08.Scripts/Tile_Script/InGame/)
- [bot_simulator.py](./backend/app/core/bot_simulator.py)

---

*문서 버전: 1.0*
*작성일: 2025-12-19*
*작성자: Claude AI Assistant*
