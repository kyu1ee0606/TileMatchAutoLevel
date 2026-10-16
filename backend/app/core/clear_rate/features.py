"""Clear-rate model features — pure Python (no numpy), one level at a time.

Port of `backend/scripts/residual_model.py` `map_features` / `build` (the E1 feature set, 48 columns) to a
single (map, placement_level, bot measurement) input. The training script
(`backend/scripts/train_clear_rate_model.py`) builds its training matrix with *this* module and asserts that
the result equals `residual_model.build` on every training level, so serving and training share one definition.

Inputs are the game ("townpop") map format — `{"layer": N, "layer_i": {"tiles": {pos: [tid, effect, [inner, ids]]}}}`
— i.e. a build shard map or `canonical_map(level_json)`.

This module must stay importable without the `app` package (the training script loads it by file path in an
analysis venv), so it imports nothing from `app`.
"""
from __future__ import annotations

import hashlib
import json
import math
import statistics
from collections import Counter
from typing import Any, Dict, Iterable, List, Optional

GIMMICKS = ("stack", "craft", "ice", "chain", "grass", "bomb", "curtain", "teleporter", "frog", "link", "unknown")
THETAS = (0.55, 0.65, 0.85, 1.0)
THETA_KEYS = ("lg055", "lg065", "lg085", "lg100")

F_SEG = ["seg101", "seg301", "logL"]
F_STRUCT = ["tiles", "layers", "types", "tiles_per_type", "unlockTile", "is_boss", "random_layout", "map2nd"]
F_GIM = ([f"has_{g}" for g in GIMMICKS] + [f"n_{g}" for g in GIMMICKS] +
         ["stack_inner", "craft_inner", "bomb_min", "bomb_sum", "n_gimmick_types"])
F_NOV = ["gimmick_first", "novel_any", "novelty"]
F_BOT = ["lg055", "lg065", "lg085", "lg100", "bot_bomb_share", "bot_grass_share", "bot_left_rel"]
FEATS = F_SEG + F_STRUCT + F_GIM + F_NOV + F_BOT  # same order as residual_model.FEATS_ALL (RM_EXTRA_FEATS unset)


def logit(p: float, eps: float = 0.01) -> float:
    """residual_model.logit: clip to [0.01, 0.99]."""
    p = min(1 - eps, max(eps, float(p)))
    return math.log(p / (1 - p))


def expit(x: float) -> float:
    return 1.0 / (1.0 + math.exp(-x))


def map_features(m: Dict[str, Any]) -> Counter:
    """Structure / gimmick counts of one map (residual_model.map_features, unchanged logic)."""
    f: Counter = Counter()
    bomb_counts: List[int] = []
    types = set()
    n_layers = int(m["layer"])
    for i in range(n_layers):
        tiles = (m.get(f"layer_{i}") or {}).get("tiles", {})
        if not isinstance(tiles, dict):
            tiles = {}
        for t in tiles.values():
            tid = str(t[0])
            eff = str(t[1]) if len(t) > 1 and t[1] else ""
            if tid.startswith(("stack", "craft")):
                kind = "stack" if tid.startswith("stack") else "craft"
                inner = int(t[2][0]) if len(t) > 2 and t[2] else 0
                f[kind] += 1
                f[kind + "_inner"] += inner
                f["tiles"] += inner
                if len(t) > 2 and t[2] and len(t[2]) > 1:
                    types.update(x for x in str(t[2][1]).split("_") if x)
            else:
                f["tiles"] += 1
                types.add(tid)
            if eff:
                base = eff.split("_")[0]
                f[base] += 1
                if base == "bomb":
                    bomb_counts.append(int(eff.split("_")[1]))
    f["layers"] = n_layers
    f["types"] = len(types - {"t0"})
    f["bomb_min"] = min(bomb_counts) if bomb_counts else 0
    f["bomb_sum"] = sum(bomb_counts)
    return f


def present_gimmicks(mf: Counter) -> List[str]:
    return [g for g in GIMMICKS if mf.get(g, 0) > 0]


def map_hash(m: Dict[str, Any]) -> str:
    """Cache key of a game-format map: layer count + per-layer col/row/tiles (other keys ignored)."""
    n = int(m["layer"])
    norm = {"layer": n}
    for i in range(n):
        layer = m.get(f"layer_{i}") or {}
        tiles = layer.get("tiles", {})
        norm[f"layer_{i}"] = {"col": str(layer.get("col", "")), "row": str(layer.get("row", "")),
                              "tiles": tiles if isinstance(tiles, dict) else {}}
    return hashlib.sha256(json.dumps(norm, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()[:16]


def bot_by_theta(rows: Iterable[Dict[str, Any]]) -> Dict[float, Dict[str, Any]]:
    return {round(float(r["theta"]), 2): r for r in rows}


def level_features(m: Dict[str, Any], *, placement_level: int, use_tile_count: int, unlock_tile: int,
                   is_boss: bool, random_layout: bool, map2nd: bool, exposure: Dict[str, int],
                   gimmick_first: bool, bot_rows: Optional[Iterable[Dict[str, Any]]]) -> Dict[str, float]:
    """48 E1 features for (map, placement). Bot features are NaN when the θ row is missing.

    exposure: number of live levels before `placement_level` (from L32) containing each gimmick.
    """
    L = int(placement_level)
    f = map_features(m)
    present = present_gimmicks(f)
    exps = [int(exposure.get(g, 0)) for g in present]
    r: Dict[str, float] = {
        "logL": math.log(L), "seg101": int(101 <= L <= 300), "seg301": int(L >= 301),
        "tiles": f["tiles"], "layers": f["layers"], "types": int(use_tile_count),
        "tiles_per_type": f["tiles"] / max(1, int(use_tile_count)),
        "unlockTile": int(unlock_tile or 0), "is_boss": int(bool(is_boss)),
        "random_layout": int(bool(random_layout)), "map2nd": int(bool(map2nd)),
        "n_gimmick_types": len([g for g in present if g != "craft"]),
        "gimmick_first": int(bool(gimmick_first)),
        "novel_any": int(any(e == 0 for e in exps)),
        "novelty": float(sum(math.exp(-e / 15) for e in exps)),
        "bomb_min": f["bomb_min"] if f.get("bomb", 0) else 6, "bomb_sum": f["bomb_sum"],
        "stack_inner": f.get("stack_inner", 0), "craft_inner": f.get("craft_inner", 0),
    }
    for g in GIMMICKS:
        r["has_" + g] = int(f.get(g, 0) > 0)
        r["n_" + g] = math.log1p(f.get(g, 0))
    b = bot_by_theta(bot_rows or [])
    nan = float("nan")
    for t, k in zip(THETAS, THETA_KEYS):
        rr = b.get(t)
        r[k] = logit(rr["wins"] / rr["games"]) if rr and rr.get("games") else nan
    rr = b.get(1.0)
    if rr and rr.get("games"):
        fails = max(1, rr["games"] - rr["wins"])
        fr = rr.get("fail_reasons") or {}
        r["bot_bomb_share"] = fr.get("Bomb", 0) / fails
        r["bot_grass_share"] = fr.get("Grass", 0) / fails
        left = rr.get("fail_tiles_left_board") or [max(0, x - 7) for x in rr.get("fail_tiles_left", [])]
        r["bot_left_rel"] = float(statistics.median(left)) / max(1, f["tiles"]) if left else 0.0
    else:
        r["bot_bomb_share"] = r["bot_grass_share"] = r["bot_left_rel"] = nan
    return {k: float(r[k]) for k in FEATS}
