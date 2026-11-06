"""레벨 타일 수 하한 규칙 (DDA +2 단계에서도 종류 수 <= 세트 수 / 1.5 유지).

최소 타일 수 = 3 * ceil(1.5 * min(K + 2, 15)),  K = 레벨이 쓰는 타일 종류 수(useTileCount).
타일 수 세는 방식은 프론트 validateTileCount(frontend/src/utils/helpers.ts)와 동일:
stack_/craft_ 는 내부 장수(extra[0])를 더하고, 골 타일(craft_s, stack_s)은 제외한다.
프론트 getMinTileCount 와 값이 같아야 한다.
"""
from __future__ import annotations

import math
from typing import Any, Dict, Optional

GOAL_TILE_TYPES = ("craft_s", "stack_s")
MAX_K_FOR_FLOOR = 15


def min_tile_count_for_kinds(k: int) -> int:
    """K종 레벨의 최소 타일 수. K<=7 도 공식 그대로 (K=3 -> 24)."""
    k = max(0, int(k))
    return 3 * math.ceil(1.5 * min(k + 2, MAX_K_FOR_FLOOR))


def count_level_tiles(level_json: Dict[str, Any]) -> int:
    """validateTileCount 와 같은 방식의 총 타일 장수(골 타일 제외, stack/craft 내부 포함)."""
    total = 0
    for i in range(int(level_json.get("layer", 0) or 0)):
        tiles = (level_json.get(f"layer_{i}") or {}).get("tiles") or {}
        for tile_data in tiles.values():
            if not isinstance(tile_data, list) or not tile_data:
                total += 1
                continue
            tile_type = tile_data[0]
            if not isinstance(tile_type, str):
                total += 1
                continue
            if tile_type in GOAL_TILE_TYPES:
                continue
            if tile_type.startswith("stack_") or tile_type.startswith("craft_"):
                n = 1
                extra = tile_data[2] if len(tile_data) > 2 else None
                if isinstance(extra, list) and extra:
                    n = int(extra[0]) if isinstance(extra[0], (int, float)) else 1
                elif isinstance(extra, dict):
                    n = int(extra.get("totalCount", extra.get("count", 1)))
                elif isinstance(extra, (int, float)):
                    n = int(extra)
                total += n
            else:
                total += 1
    return total


def level_kind_count(level_json: Dict[str, Any]) -> int:
    """K: useTileCount(>0)가 있으면 그 값, 없으면 실제 쓰인 t1~t15 종류 수."""
    utc = level_json.get("useTileCount")
    if isinstance(utc, (int, float)) and utc > 0:
        return int(utc)
    kinds = set()
    for i in range(int(level_json.get("layer", 0) or 0)):
        tiles = (level_json.get(f"layer_{i}") or {}).get("tiles") or {}
        for tile_data in tiles.values():
            if isinstance(tile_data, list) and tile_data and isinstance(tile_data[0], str):
                t = tile_data[0]
                if t[:1] == "t" and t[1:].isdigit() and t != "t0":
                    kinds.add(t)
    return len(kinds)


def check_tile_floor(level_json: Dict[str, Any]) -> Optional[str]:
    """하한 미달이면 에러 메시지(K, 최소, 현재 포함), 충족이면 None."""
    k = level_kind_count(level_json)
    need = min_tile_count_for_kinds(k)
    have = count_level_tiles(level_json)
    if have < need:
        return (f"타일 수 하한 미달: 종류 K={k}, 최소 타일 수 {need}개, 현재 {have}개 "
                f"(최소 = 3×ceil(1.5×min(K+2,15)))")
    return None
