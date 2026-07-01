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

## 비주얼 타일 시드 (visualTileSeed) — 배치/비주얼 인덱스 분리

배치(어느 위치가 같은 종류=매칭 트리플)는 `randSeed`로 고정하고, **각 종류가 쓸 스프라이트 인덱스(t1~t15)만** 별도 `visualTileSeed`로 결정. `useTileCount=6`이어도 풀이 t1~15 전체 → t13~15 비주얼 등장 가능. 구체 시드면 **에디터 미리보기 == 인게임**.

> 게임측 정본: `sp_meowsgarden/.../DESIGN_LEVEL_MAP_SCHEMA.md §4-1` + `DESIGN_TILE_COLOR_BALANCE.md §4-1`.

### 필드 (레벨 JSON)
- `visualTileSeed`: `>=0` 결정적 / `-1` 런타임랜덤 / **없음 = 리맵 안 함(하위호환)**.

### 알고리즘 (인게임 `ApplyVisualTileRemap`과 100% 동일)
`assignT0Tiles`가 배치+셔플 끝낸 뒤(배치 rng 소비 완료) **별도 RNG**로 재매핑:
1. assignments에서 사용 인덱스(1~15) 수집 → **오름차순 distinct** (key/t16 제외)
2. `vSeed = seed<0 ? 0(런타임랜덤) : (seed+1)>>>0`  // WELL512 seed 0(=시간기반) 회피
3. `pool=[1..15]`, 부분 Fisher-Yates로 `usedTypes.length`개 distinct 선택 (`rand(i,14)` inclusive)
4. `map[usedTypes[k]] = pool[k]` (1:1)
5. assignments의 `t{1..15}`만 `t{map[id]}`로 재기록 (key/스택/크래프트 무관)

골든값(usedTypes=[1..6]): seed 459838 → `4,1,7,9,12,3` / seed 12345 → `9,5,3,8,2,14`. (인게임·에디터 동일 확인)

### 프로덕션 기본값 판단 — **구체 랜덤 시드 베이크**
- `-1`(런타임랜덤): 매 실행 비주얼 변동 → **미리보기≠인게임** (핵심 요구 위반) → ❌
- `0`(전 레벨 고정 시드): 결정적이나 모든 레벨 동일 시드 → 같은 useTileCount끼리 스프라이트 단조 → 현행보다 다양성 저하 → ❌
- **구체 랜덤 베이크(>=0)**: 결정적(미리보기==인게임) + 레벨별 다양성 → ✅ 채택. `ProductionDashboard.bakeVisualTileSeed`가 생성/재생성 시 `1~2e9` 굽고 level_json에 고정 저장.

### 적용 지점
- `frontend/src/engine/tileDistributor.ts` `applyVisualTileRemap` + `assignT0Tiles(visualTileSeed)`
- `frontend/src/engine/gameEngine.ts` `distributeT0Tiles`/`initializeFromLevel` 패스스루 + `resolveT0TileTypes`(미리보기 공유)
- `frontend/src/utils/levelPreview.ts` 평면 t0 셀을 분배 결과로 해소(미리보기 일치)
- `frontend/src/components/ProductionDashboard/index.tsx` `bakeVisualTileSeed` (생성/재생성 3곳)
- `backend/app/api/routes/gboost.py` `townpop_level`에 `visualTileSeed` 조건부 emit(있을 때만 → 레거시 하위호환)
- **백엔드 봇/솔버는 무변경**: 리맵은 bijective(1:1) → 난이도/솔버블 동일하므로 시뮬레이션 불필요.

## 관련 파일

| 파일 | 설명 |
|------|------|
| `backend/app/core/bot_simulator.py` | TileDistributor, zWellRandom 클래스 |
| `backend/app/api/routes/simulate.py` | stack_craft_types_map 생성 |
| `backend/app/api/routes/gboost.py` | 게임 export(townpop_level) — visualTileSeed 운반 |
| `frontend/src/engine/tileDistributor.ts` | 프론트엔드 TileDistributor + applyVisualTileRemap |
| `frontend/src/engine/gameEngine.ts` | t0 분배 패스스루 + resolveT0TileTypes |
| `frontend/src/utils/levelPreview.ts` | 미리보기 캔버스(평면 t0 해소) |
| `frontend/src/components/ProductionDashboard/index.tsx` | bakeVisualTileSeed (프로덕션 베이크) |
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
