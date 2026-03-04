# Stack Tile Double-Counting Bug Fix

**Date**: 2026-03-03
**Files Modified**: `backend/app/core/bot_simulator.py`

## Problem
레벨에 stack_s 또는 stack_n 기믹이 있을 때, 봇 시뮬레이터에서 스택의 TOP 타일이 두 번 카운트되는 버그 발견.

### 증상
- 총 타일 수가 예상보다 많음 (예: 99개 대신 101개)
- 일부 타일 타입의 개수가 3의 배수가 아님
- 결과적으로 클리어율 0% (매칭 불가능)

### 근본 원인
`_process_stack_craft_tiles()` 함수에서:
- Stack TOP 타일이 `state.tiles`에 추가됨
- 하지만 `state.stacked_tiles`에서 제거되지 않음
- 결과: 동일 타일이 두 곳에서 카운트됨

## Solution

### Before (버그 코드)
```python
else:
    # For stack: all tiles are at the same position, only top is pickable
    top_tile = created_tiles[-1]
    if layer_idx not in state.tiles:
        state.tiles[layer_idx] = {}
    state.tiles[layer_idx][pos] = top_tile
    # TOP 타일이 stacked_tiles에 그대로 남아있음 (버그)
```

### After (수정된 코드)
```python
else:
    # For stack: all tiles are at the same position, only top is pickable
    top_tile = created_tiles[-1]
    if layer_idx not in state.tiles:
        state.tiles[layer_idx] = {}
    state.tiles[layer_idx][pos] = top_tile

    # CRITICAL: Remove the top tile from stacked_tiles to avoid double-counting
    top_tile_key = top_tile.original_full_key
    if top_tile_key in state.stacked_tiles:
        del state.stacked_tiles[top_tile_key]
    # Update the tile below
    if top_tile.under_stacked_tile_key:
        under_tile = state.stacked_tiles.get(top_tile.under_stacked_tile_key)
        if under_tile:
            under_tile.upper_stacked_tile_key = None
```

## Verification
간단한 테스트 레벨로 검증:
- stack_s 기믹 포함 레벨 생성
- 수정 전: 타일 수 불일치, 3의 배수 위반
- 수정 후: 18개 타일, 모든 타입 3의 배수, 클리어율 10%

## Note
원래 사용자 제공 레벨은 수정 후에도 0%인데, 이는 레벨 구조적 문제:
- 26개 unknown 기믹 (블로킹)
- 2개 curtain_close 기믹 (접근 불가)
- 초기 접근 가능 타일 18개 중 3개 타입만 매칭 가능

이는 코드 버그가 아닌 레벨 디자인 이슈임.
