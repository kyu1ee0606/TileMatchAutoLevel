"""E-P1-2: t0-ize a production level (04_seed_variant_plan.md §A2, amended by 05 §3-3).

Keeps position / layer / covering / tile count / effects / containers; clears tile kinds so the
client's ShuffleEmptyTiles assigns them from randSeed. Output is a GB/townpop-style row whose
`map` is the canonical map (GB key order, 04 §A3-3) — exactly what the client would iterate.

Rules
- board t1..t15 -> "t0", effect untouched
- stack/craft explicit inner [cnt,"ids"] -> legacy [cnt] (all t0, live-proven format)
- key / t16 tiles, pre-existing t0 (count-only containers) -> PvT0izeError (excluded in P1)
- useTileCount = distinct explicit kinds of the ORIGINAL map (board + inner, key excluded), 1..15,
  always written explicitly (null/missing would become 0 -> skin default on the client)
- randSeed written explicitly (> 0), shuffleTile 0, typeImbalance "", visualTileSeed removed
- asserts: layer continuity, structHash unchanged, no explicit kind left, port strict run OK
"""
from __future__ import annotations

import copy
from typing import Any, Dict, List, Optional, Tuple

from app.api.routes.gboost import _convert_to_townpop_format
from app.core.pv.canonical import canonical_map, check_layer_continuity, struct_hash
from app.core.pv.cs_shuffle import shuffle_empty_tiles

T0IZE_VERSION = "t0ize@1"
_REGULAR = {f"t{i}" for i in range(1, 16)}


class PvT0izeError(Exception):
    pass


def _is_container(tile: Any) -> bool:
    return (
        isinstance(tile, list) and len(tile) >= 3 and isinstance(tile[0], str)
        and (tile[0].startswith("stack_") or tile[0].startswith("craft_"))
        and isinstance(tile[2], list) and len(tile[2]) >= 1
    )


def _iter_tiles(canon: Dict[str, Any]):
    n = int(canon.get("layer", 0))
    for i in range(n):
        layer = canon.get(f"layer_{i}")
        tiles = layer.get("tiles") if isinstance(layer, dict) else None
        if not isinstance(tiles, dict):
            continue
        for pos, tile in tiles.items():
            yield i, pos, tile


def original_kinds(canon: Dict[str, Any]) -> Tuple[Dict[str, int], int, int]:
    """(explicit kind counts incl. inner, key count, t0 count) of a canonical map."""
    kinds: Dict[str, int] = {}
    keys = 0
    t0 = 0

    def add(tid: str, effect: str = "") -> None:
        nonlocal keys, t0
        if tid in ("key", "t16") or (isinstance(effect, str) and effect.lower() == "key") or tid.lower() == "key":
            keys += 1
        elif tid == "t0":
            t0 += 1
        elif tid in _REGULAR:
            kinds[tid] = kinds.get(tid, 0) + 1
        else:
            raise PvT0izeError(f"unknown tile id {tid!r}")

    for _, pos, tile in _iter_tiles(canon):
        if not isinstance(tile, list) or not tile or not isinstance(tile[0], str):
            raise PvT0izeError(f"malformed tile at {pos}: {tile!r}")
        if _is_container(tile):
            cnt = int(tile[2][0])
            inner = tile[2][1] if len(tile[2]) >= 2 and isinstance(tile[2][1], str) and tile[2][1] else None
            ids = inner.split("_") if inner else None
            if ids is None or len(ids) != cnt:
                t0 += cnt  # count-only (client t0 fallback)
            else:
                for tid in ids:
                    add(tid)
        else:
            add(tile[0], tile[1] if len(tile) > 1 else "")
    return kinds, keys, t0


def t0ize_level(level_json: Dict[str, Any], rand_seed: int, *, verify_seed: Optional[int] = None) -> Dict[str, Any]:
    """Return {"row": townpop row (t0 map), "meta": {...}} for one production level_json."""
    if not isinstance(rand_seed, int) or not (1 <= rand_seed <= 2**31 - 1):
        raise PvT0izeError(f"randSeed must be in [1, 2^31-1]: {rand_seed!r}")

    canon = canonical_map(level_json)
    problems = check_layer_continuity(canon)
    if problems:
        raise PvT0izeError(f"layer continuity: {problems}")
    sh = struct_hash(canon)

    kinds, keys, t0 = original_kinds(canon)
    if keys:
        raise PvT0izeError(f"key tiles present ({keys}) — key levels excluded in P1")
    if t0:
        raise PvT0izeError(f"t0 already present ({t0}, count-only containers?) — excluded in P1")
    utc0 = len(kinds)
    if not 1 <= utc0 <= 15:
        raise PvT0izeError(f"useTileCount out of range: {utc0}")
    total = sum(kinds.values())
    if total % 3 or any(v % 3 for v in kinds.values()):
        raise PvT0izeError(f"original per-kind counts not divisible by 3: {kinds}")

    t0map = copy.deepcopy(canon)
    for i, pos, tile in _iter_tiles(t0map):
        if _is_container(tile):
            tile[2] = [tile[2][0]]  # legacy [cnt] -> client fills t0
        else:
            tile[0] = "t0"

    if struct_hash(t0map) != sh:
        raise PvT0izeError("structHash changed by t0-ize")
    k2, keys2, t02 = original_kinds(t0map)
    if k2 or keys2:
        raise PvT0izeError("explicit kinds left after t0-ize")
    if t02 != total:
        raise PvT0izeError(f"t0 count {t02} != original tile count {total}")

    row = _convert_to_townpop_format(_patch_empty_tiles(level_json))
    row.pop("etime", None)  # time.time() — not deterministic
    row.pop("visualTileSeed", None)
    row["map"] = t0map
    row["randSeed"] = str(rand_seed)
    row["useTileCount"] = str(utc0)
    row["unlockTile"] = "0"
    row["shuffleTile"] = "0"
    row["typeImbalance"] = ""

    # 05 §3-3: per-kind ÷3 of (explicit + assigned) == strict port run succeeds
    shuffle_empty_tiles(t0map, rand_seed=verify_seed or rand_seed, use_tile_count=utc0, strict=True)

    sets = sorted((v // 3 for v in kinds.values()), reverse=True)
    meta = {
        "t0izeVersion": T0IZE_VERSION,
        "structHash": sh,
        "utc0": utc0,
        "tileCount": total,
        "origKinds": dict(sorted(kinds.items(), key=lambda kv: int(kv[0][1:]))),
        "origSetSpread": (sets[0] - sets[-1]) if sets else 0,
    }
    return {"row": row, "meta": meta}


def _patch_empty_tiles(level_json: Dict[str, Any]) -> Dict[str, Any]:
    """`tiles: []` -> {} (same normalisation canonical_map applies; gboost assumes dicts)."""
    patched = {
        k: {**v, "tiles": {}}
        for k, v in level_json.items()
        if k.startswith("layer_") and isinstance(v, dict) and isinstance(v.get("tiles"), list)
    }
    return {**level_json, **patched} if patched else level_json


def bot_level_json(row: Dict[str, Any], resolved_map: Dict[str, Any]) -> Dict[str, Any]:
    """Editor-format level_json for BotSimulator / solver from a resolved (explicit) map.

    - "t16" -> "key" (bot only knows "key", 05 F-G5-1)
    - layer = max(declared, max layer_N + 1)  (client EffectiveLayerCount, 05 F-G5-2)
    - randSeed kept non-zero (bot's own t0 pass would otherwise use a time seed)
    """
    lj: Dict[str, Any] = copy.deepcopy(resolved_map)
    nums = [int(k[6:]) for k in lj if k.startswith("layer_") and k[6:].isdigit()]
    try:
        declared = int(lj.get("layer", 0) or 0)
    except (TypeError, ValueError):
        declared = 0
    lj["layer"] = max(declared, max(nums, default=-1) + 1)
    for k in list(lj):
        if not k.startswith("layer_"):
            continue
        tiles = lj[k].get("tiles")
        if isinstance(tiles, list):
            lj[k]["tiles"] = {}
            continue
        for tile in tiles.values():
            if tile and tile[0] == "t16":
                tile[0] = "key"
            if _is_container(tile) and len(tile[2]) >= 2 and isinstance(tile[2][1], str):
                tile[2][1] = "_".join("key" if x == "t16" else x for x in tile[2][1].split("_"))
    seed = int(row.get("randSeed") or 0)
    lj["randSeed"] = seed if seed > 0 else 1
    lj["useTileCount"] = int(row.get("useTileCount") or 0) or 6
    lj["unlockTile"] = int(row.get("unlockTile") or 0)
    total = 0
    for i in range(lj["layer"]):
        for tile in (lj.get(f"layer_{i}", {}).get("tiles") or {}).values():
            total += int(tile[2][0]) if _is_container(tile) else 1
    lj["max_moves"] = total + 50  # safety cap incl. container inner (no move limit in game)
    return lj
