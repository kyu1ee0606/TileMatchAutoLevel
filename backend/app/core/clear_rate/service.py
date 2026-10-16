"""Single-level clear-rate prediction: level_json + placement_level (+ optional bot measurement) → response dict.

Bot measurement source, in order: request `bot_measurement` → model bot cache (training/live maps, keyed by
map hash + useTileCount). Neither → status "measurement_required" (automatic measurement is not part of the
display MVP, doc 33 §1).
"""
from __future__ import annotations

import copy
from typing import Any, Dict, List, Optional

from . import guard
from .features import level_features, map_features, map_hash, present_gimmicks
from .model import ClearRateModel, load_model


def _seg(L: int) -> Optional[str]:
    for lo, hi in ((32, 100), (101, 300), (301, 500)):
        if lo <= L <= hi:
            return f"{lo}-{hi}"
    return None


def _game_map(level_json: Dict[str, Any]) -> Dict[str, Any]:
    from app.core.pv.canonical import canonical_map
    return canonical_map(level_json)


def _random_layout(m: Dict[str, Any]) -> bool:
    from app.core.pv.cs_shuffle import build_level_model, get_empty_tile_list
    return bool(get_empty_tile_list(build_level_model(copy.deepcopy(m))))


def _exposure(position: Dict[str, Any], L: int) -> Dict[str, int]:
    table = position["exposure"]
    keys = sorted(int(k) for k in table)
    k = min(max(L, keys[0]), keys[-1])
    return table[str(k)]


def predict(level_json: Dict[str, Any], placement_level: Optional[int], *, target: Optional[float] = None,
            bot_measurement: Optional[Dict[str, Any]] = None, model: Optional[ClearRateModel] = None) -> Dict[str, Any]:
    mdl = model or load_model()
    man, sup, pos = mdl.manifest, mdl.model["support"], mdl.model["position"]
    m = _game_map(level_json)
    use_tile_count = int(level_json.get("useTileCount") or 0)
    key = f"{map_hash(m)}:{use_tile_count}"
    out: Dict[str, Any] = {
        "model_version": mdl.version, "target_metric": man["target_metric"], "bot_version": man["bot_version"],
        "status": "ok", "placement_level": placement_level, "map_hash": key,
        "expected": None, "range80": None, "confidence": None, "evidence_flags": [],
        "aux": {"unaided_lb": None, "help_rate": None}, "target": None,
        "bot_source": None, "bot_success_reference": {},
    }
    flags: List[Dict[str, str]] = guard.input_flags(sup, placement_level=placement_level,
                                                    gimmicks=present_gimmicks(map_features(m)))
    if bot_measurement is not None:
        rows, out["bot_source"] = list(bot_measurement.get("rows") or []), "request"
    elif key in mdl.bot_cache:
        rows, out["bot_source"] = mdl.bot_cache[key]["rows"], "cache"
    else:
        rows = []
    if out["bot_source"] is not None:
        flags += guard.bot_flags(man, bot_measurement, rows)
        out["bot_success_reference"] = {f"theta{int(round(float(r['theta']) * 100)):03d}":
                                        round(r["wins"] / r["games"], 4) for r in rows if r.get("games")}

    if placement_level is None or guard.suppressed(flags):
        out.update(status="insufficient_evidence", evidence_flags=flags)
        return out
    if out["bot_source"] is None:
        out.update(status="measurement_required", evidence_flags=flags)
        return out

    L = int(placement_level)
    feats = level_features(
        m, placement_level=L, use_tile_count=use_tile_count, unlock_tile=int(level_json.get("unlockTile") or 0),
        is_boss=L % 10 == 0,  # upload default (ProductionExport 'multiples10'): autoCollectCount=3 on every 10th level
        random_layout=_random_layout(m), map2nd=False, exposure=_exposure(pos, L),
        gimmick_first=L in set(pos["gimmick_first_levels"]), bot_rows=rows)
    flags += guard.feature_flags(sup, feats)
    if guard.suppressed(flags):
        out.update(status="insufficient_evidence", evidence_flags=flags)
        return out

    expected = mdl.predict("ft_any", feats)
    lo, hi = mdl.range80("ft_any", feats)
    flags += guard.value_flags(expected, target, sup, _seg(L))
    out.update(expected=round(expected, 4), range80=[round(lo, 4), round(hi, 4)],
               aux={"unaided_lb": round(mdl.predict("unaided_lb", feats), 4),
                    "help_rate": round(mdl.predict("help_rate", feats), 4)},
               confidence=guard.confidence(flags), evidence_flags=flags)
    if target is not None:
        out["target"] = {"value": target, "in_range80": lo <= target <= hi}
    return out

