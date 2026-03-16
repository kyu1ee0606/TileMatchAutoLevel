# t0 타일 분배 로직 문서

## 개요

t0 타일은 레벨 JSON에서 "랜덤 타일"을 의미하며, 게임 시작 시 실제 타일 타입(t1~t15, key)으로 변환됩니다.
이 문서는 인게임 C# 로직과 동일하게 구현된 백엔드/프론트엔드 분배 로직을 설명합니다.

## 핵심 컴포넌트

### 1. TileDistributor 클래스

**위치**:
- Backend: `backend/app/core/bot_simulator.py`
- Frontend: `frontend/src/engine/tileDistributor.ts`

**주요 함수**:

#### `distribute_tiles(set_length, tile_type_count, specified_count, imbalance_slider_value)`
- 타일 세트를 타입별로 분배
- `set_length`: 총 세트 수 (t0 타일 수 / 3)
- `tile_type_count`: 사용할 타일 타입 수 (useTileCount)
- 반환: 타일 타입 인덱스 리스트 (예: [1, 1, 1, 2, 2, 2, 6])

#### `get_to_add_index_list(existing_tile_counts)`
- 기존 타일 카운트를 3의 배수로 맞추기 위해 추가할 타일 인덱스 반환
- C# `GetToAddIndexList()` 함수와 동일
- 예: `{t6: 1}` → `[6, 6]` (t6 2개 추가하여 3개로 맞춤)

#### `assign_t0_tiles(...)`
- 전체 t0 타일 할당 메인 함수
- 순서:
  1. `get_to_add_index_list()` - 기존 타일 밸런싱
  2. `distribute_tiles()` - 타입 분배
  3. `shuffle_tile_assignments()` - 위치 셔플

### 2. zWellRandom 클래스

- Unity C# WELL512 알고리즘 포팅
- 동일한 seed로 동일한 난수 시퀀스 보장
- 인게임과 정확히 일치하는 셔플 결과

## 분배 로직 상세

### 세트 기반 분배

```
t0_count = 9 (9개의 t0 타일)
set_count = 9 / 3 = 3 (3세트)
useTileCount = 6 (t1~t6 사용)

distribute_tiles(3, 6) 결과:
→ [6, 5, 4] (t6 1세트, t5 1세트, t4 1세트)

확장 후: [t6, t6, t6, t5, t5, t5, t4, t4, t4]
셔플 후: [t6, t5, t4, t6, t5, t4, t6, t5, t4] (seed에 따라 다름)
```

### Seed별 셔플 결과 예시

| Seed | 셔플 결과 (9개) | Stack 위치 (처음 3개) |
|------|-----------------|----------------------|
| 926524 | [t6,t6,t6,t5,t4,t5,t4,t5,t4] | 모두 t6 (1종류) |
| 12345 | [t4,t4,t6,t5,t5,t5,t6,t6,t4] | t4,t4,t6 (2종류) |
| 777777 | [t4,t6,t5,t4,t4,t6,t6,t5,t5] | t4,t6,t5 (3종류) |

**중요**: Stack/Craft 내부 타일이 모두 같은 타입인 것은 seed에 따른 우연한 결과이며, 버그가 아닙니다.

## Stack/Craft 타일 순서

### 저장 순서 vs 표시 순서

```
C# 내부 저장: [bottom, ..., top] (index 0 = bottom, index n-1 = top)
인게임 픽 순서: top → bottom (highestTile = Count - 1 먼저 픽)
```

### 프론트엔드 표시

```javascript
// stack_craft_types_map은 top-to-bottom 순서로 전달
// index 0 = top (먼저 픽되는 타일, 화면에 표시)
// index -1 = bottom (마지막에 픽되는 타일)
```

### 2024-03 수정사항

**문제**: Craft가 초기화 시 top 타일을 emit하면 `stacked_tiles`에서 삭제되어 `stack_craft_types_map`에 누락됨

**수정** (`simulate.py`):
```python
# Emitted 타일도 포함하도록 수정
emitted_tiles = {tile.original_full_key: tile for layer in state.tiles.values() for tile in layer.values() if tile.original_full_key}

for key in tile_keys:
    tile = state.stacked_tiles.get(key) or emitted_tiles.get(key)
    if tile:
        tile_types.append(tile.tile_type)

# 순서 뒤집기 (인게임 픽 순서와 일치)
stack_craft_types_map[craft_box_key] = tile_types[::-1]
```

## 관련 파일

| 파일 | 설명 |
|------|------|
| `backend/app/core/bot_simulator.py` | TileDistributor, zWellRandom 클래스 |
| `backend/app/api/routes/simulate.py` | stack_craft_types_map 생성 |
| `frontend/src/engine/tileDistributor.ts` | 프론트엔드 TileDistributor |
| `frontend/src/components/SimulationViewer/BotTileGrid.tsx` | 타일 표시 로직 |

## 디버깅 팁

### t0 분배 결과 확인
```python
from app.core.bot_simulator import TileDistributor

result = TileDistributor.assign_t0_tiles(
    t0_count=9,
    use_tile_count=6,
    rand_seed=926524,
    existing_tile_counts={}
)
print(result)  # ['t6', 't6', 't6', 't5', 't4', 't5', 't4', 't5', 't4']
```

### GetToAddIndexList 확인
```python
to_add = TileDistributor.get_to_add_index_list({"t6": 1, "t2": 2})
print(to_add)  # [2, 6, 6] - t2 1개, t6 2개 추가 필요
```
