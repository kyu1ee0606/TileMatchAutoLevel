"""Final game conditions + condition hash (doc 35 §4) — what the game actually runs, and the tag a bot
measurement must carry.

    finalize_game_conditions(level_json, slot_number, upload_opts=None) -> (game_map, conditions)
    cond_hash(game_map, conditions) -> str

Upload path (read, not changed): ProductionExport.tsx builds `uploadJson = level_json + rewardCoin +
autoCollectCount(slot rule)` → `POST /api/gboost/{board}/{level}` → `gboost._convert_to_townpop_format`.
finalize_game_conditions calls that same converter (read-only reuse) on the same override, so useTileCount
(re-derived from the tiles), randSeed, unlockTile, ... are the uploaded values. The only part not derivable from
the level itself is the upload-panel autoCollectCount option (UI-selectable) — passed as `upload_opts`, default =
the panel default ('multiples10', value 3), and echoed back so callers can see the assumption.

Module-level imports are stdlib only: the training script loads this file by path (analysis venv, no fastapi).
"""
from __future__ import annotations

import hashlib
import json
from typing import Any, Dict, Optional, Tuple

# Game-behaviour row fields a bot measurement depends on. Build-shard row keys (bot_af_L32_500.ROW_KEYS minus
# layer) + randomizer/teleport fields kept conservatively (doc 35 §4-1). Display-only fields (tileSkin,
# backgroundIndex, visualTileSeed, difficulty, rewardCoin) are excluded.
GAME_FIELDS = ("useTileCount", "unlockTile", "autoCollectCount", "randSeed", "shuffleTile", "typeImbalance", "timea",
               "shuffleLayer", "useInRandomizer", "useTeleportInRandomizer", "teleportRandSeed")
STR_FIELDS = ("typeImbalance",)
DEFAULT_UPLOAD_OPTS = {"auto_collect_mode": "multiples10", "auto_collect_value": 3}  # ProductionExport defaults


def _num(v: Any) -> int:
    try:
        return int(float(v))
    except (TypeError, ValueError):
        return 0


def normalize_conditions(cond: Dict[str, Any]) -> Dict[str, Any]:
    return {k: (str(cond.get(k) or "") if k in STR_FIELDS else _num(cond.get(k))) for k in GAME_FIELDS}


def cond_hash(game_map: Dict[str, Any], conditions: Dict[str, Any]) -> str:
    """Hash of final game conditions: map (layer count, per-layer col/row/tiles) + GAME_FIELDS."""
    n = int(game_map["layer"])
    norm: Dict[str, Any] = {"layer": n, "fields": normalize_conditions(conditions)}
    for i in range(n):
        layer = game_map.get(f"layer_{i}") or {}
        tiles = layer.get("tiles", {})
        norm[f"layer_{i}"] = {"col": str(layer.get("col", "")), "row": str(layer.get("row", "")),
                              "tiles": tiles if isinstance(tiles, dict) else {}}
    return hashlib.sha256(json.dumps(norm, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()[:20]


def upload_auto_collect(slot_number: Optional[int], level_json: Dict[str, Any],
                        upload_opts: Optional[Dict[str, Any]] = None) -> int:
    """ProductionExport.resolveAutoCollect mirror: 'preserve' keeps level_json.autoCollectCount (or 0);
    'multiples10' sets the value on every 10th slot and 0 elsewhere."""
    o = {**DEFAULT_UPLOAD_OPTS, **(upload_opts or {})}
    if o["auto_collect_mode"] == "preserve":
        return _num(level_json.get("autoCollectCount", 0))
    return max(0, int(o["auto_collect_value"])) if slot_number and slot_number > 0 and slot_number % 10 == 0 else 0


def finalize_game_conditions(level_json: Dict[str, Any], slot_number: Optional[int],
                             upload_opts: Optional[Dict[str, Any]] = None) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """(game_map, conditions) as the upload would send them for this slot (= placement level for originals)."""
    from app.api.routes.gboost import _convert_to_townpop_format
    from app.core.pv.canonical import canonical_map

    lj = dict(level_json)
    lj["autoCollectCount"] = upload_auto_collect(slot_number, level_json, upload_opts)
    if isinstance(lj.get("layer"), str):
        lj["layer"] = int(lj["layer"])
    row = _convert_to_townpop_format(canonical_map_input(lj))
    return canonical_map(lj), normalize_conditions({k: row.get(k) for k in GAME_FIELDS})


def canonical_map_input(lj: Dict[str, Any]) -> Dict[str, Any]:
    """Same empty-layer patch canonical_map applies (shard maps serialise empty tiles as [])."""
    patched = {k: {**v, "tiles": {}} for k, v in lj.items()
               if k.startswith("layer_") and isinstance(v, dict) and isinstance(v.get("tiles"), list)}
    return {**lj, **patched} if patched else lj


def stored_condition_diffs(level_json: Dict[str, Any], conditions: Dict[str, Any]) -> Dict[str, Tuple[Any, Any]]:
    """Fields whose saved level_json value differs from the uploaded value (e.g. useTileCount re-derived)."""
    out = {}
    for k in ("useTileCount",):
        if k in level_json and _num(level_json.get(k)) != conditions[k]:
            out[k] = (_num(level_json.get(k)), conditions[k])
    return out
