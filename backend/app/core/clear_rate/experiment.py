"""Experimental target-evaluation path for the two modes (doc 35 §9) — explicit opt-in only.

    require_mode(mode)                                          no default: missing / unknown mode is rejected
    user_expected_precheck(model, target, placement_level)      A: refuse before generating when no support
    evaluate_user_expected(model, game_map, cond, L, meas, target)   A: predict_level + select.verdict
    evaluate_bot_virtual(game_map, cond, meas_s, meas_c, target, d)  B: virtual_rate + virtual_verdict (no model)

Not used by /api/generate, /api/generate/validated, production verification, upload or the legacy
predicted_clear_rate. Mode A never falls back to mode B; results are returned under separate keys
("user_expected" / "bot_virtual") with separate field names. Pass thresholds are the doc 31/35 proposals and are
experiment criteria, not validated operating rules.
"""
from __future__ import annotations

from typing import Any, Dict, Optional

from . import guard
from .conditions import cond_hash
from .predict import BotMeasurement, predict_level, segment_of
from .select import verdict
from .virtual import DEFAULT_DEF, VirtualDef, measurement_problems, virtual_rate, virtual_verdict

USER_EXPECTED, BOT_VIRTUAL = "user_expected", "bot_virtual"
TARGET_MODES = (USER_EXPECTED, BOT_VIRTUAL)


class TargetModeError(ValueError):
    pass


def require_mode(mode: Optional[str]) -> str:
    if mode not in TARGET_MODES:
        raise TargetModeError(f"target_mode must be one of {TARGET_MODES} (no default); got {mode!r}")
    return mode


def user_expected_precheck(model: Any, target: float, placement_level: Optional[int]) -> list:
    """Hard reasons that make a mode-A target unsupported before any candidate is generated: target below 0.85
    (doc 26 §11-9, not trusted), target outside the segment's training p5–p95, placement outside the training range."""
    sup = model.model["support"]
    out = []
    if placement_level is None:
        return ["PLACEMENT_MISSING"]
    lo, hi = sup["level_range"]
    if not lo <= placement_level <= hi:
        out.append("LEVEL_OUT_OF_RANGE")
    tf = guard.target_flags(target, sup, segment_of(placement_level))
    out += [f["code"] for f in tf if f["severity"] == "hard" or f["code"] == "LOW_CONFIDENCE"]
    return out


# Low-confidence codes decidable from the map, final conditions and placement alone (no bot data). A candidate carrying
# any of these (or a hard input / structural FEATURE_OOD flag) cannot get a normal verdict whatever its measurement,
# so the generation search may skip measuring it. Same guard functions and inputs as predict_level — nothing relaxed.
STRUCTURAL_LOW_CONF = ("GIMMICK_FIRST", "NOVELTY_HIGH", "SIMILAR_MAPS_FEW", "COMBO_HIGH_ERROR")


def structural_screen(model: Any, game_map: Dict[str, Any], cond: Dict[str, Any], placement_level: int, *,
                      random_layout: bool) -> Dict[str, Any]:
    """Pre-measurement screen for mode A: the bot-independent part of predict_level's checks on the real map.
    Bot features are left NaN (never compared, never fed to the model), so the screen only reports flags that the
    full prediction would also raise; it does not produce or replace a prediction."""
    from .features import level_features, map_features, present_gimmicks
    from .predict import _exposure
    sup, pos = model.model["support"], model.model["position"]
    gims = present_gimmicks(map_features(game_map))
    flags = guard.input_flags(sup, placement_level=placement_level, gimmicks=gims, conditions=cond)
    L, acc = int(placement_level), int(cond["autoCollectCount"])
    feats = level_features(game_map, placement_level=L, use_tile_count=cond["useTileCount"],
                           unlock_tile=cond["unlockTile"], is_boss=1 <= acc <= 3, random_layout=random_layout,
                           map2nd=False, exposure=_exposure(pos, L), gimmick_first=L in set(pos["gimmick_first_levels"]),
                           bot_rows=None)
    flags += guard.feature_flags(sup, feats)
    combo = "+".join(g for g in gims if g != "craft") or "none"
    flags += guard.reliability_flags({"pred_zone": None, "combo": {"key": combo, **(
        (sup.get("reliability") or {}).get("combo", {}).get(combo) or {"n": 0})}})
    codes = [f["code"] for f in flags]
    blocking = [c for c in codes if c in guard.SUPPRESS or c in STRUCTURAL_LOW_CONF]
    return {"codes": codes, "blocking": blocking, "combo": combo, "gimmicks": gims,
            "structure": {k: feats[k] for k in ("tiles", "layers", "types", "tiles_per_type", "novelty")}}


def evaluate_user_expected(model: Any, game_map: Dict[str, Any], cond: Dict[str, Any], placement_level: int,
                           meas: Optional[BotMeasurement], target: float, *, random_layout: bool,
                           confirm_bands=None) -> Dict[str, Any]:
    pred = predict_level(model, game_map, cond, placement_level, meas, random_layout=random_layout)
    v = (verdict(pred, target, model.model["support"]) if confirm_bands is None else
         verdict(pred, target, model.model["support"], confirm_bands=confirm_bands))
    vd = dict(v.__dict__)
    vd["band"], vd["thresholds"] = list(v.band), {k: (list(x) if isinstance(x, tuple) else x)
                                                   for k, x in v.thresholds.items()}
    return {"target_mode": USER_EXPECTED, "target_metric": pred.target_metric, "target": target,
            "prediction": pred.to_dict(), "verdict": vd, "criteria": "experiment (doc 31/35 proposals, not validated)"}


def evaluate_bot_virtual(game_map: Dict[str, Any], cond: Dict[str, Any], meas_s: Optional[BotMeasurement],
                         meas_c: Optional[BotMeasurement], target: float,
                         d: VirtualDef = DEFAULT_DEF) -> Dict[str, Any]:
    h = cond_hash(game_map, cond)
    s_probs = measurement_problems(meas_s, d, h, stage="S") if meas_s is not None else ["S 측정 없음"]
    vs = virtual_rate(meas_s, d) if meas_s is not None and not s_probs else None
    vv = virtual_verdict(meas_c, d, target, h)
    return {"target_mode": BOT_VIRTUAL, "bot_virtual_def": d.to_dict(), "bot_virtual_def_id": d.def_id,
            "cond_hash": h, "bot_virtual_target": target, "bot_virtual_s": vs, "bot_virtual_s_problems": s_probs,
            "bot_virtual_c": virtual_rate(meas_c, d) if meas_c is not None and vv.bot_virtual_games_c else None,
            **vv.to_dict()}


__all__ = ["USER_EXPECTED", "BOT_VIRTUAL", "TARGET_MODES", "TargetModeError", "require_mode",
           "user_expected_precheck", "evaluate_user_expected", "evaluate_bot_virtual"]
