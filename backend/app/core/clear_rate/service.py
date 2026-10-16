"""Editor entry point: editor level_json + placement → final game conditions → measurement → predict_level.

Bot measurement: the caller's (must carry cond_hash / seed_band) → else the model's cache of live-build
measurements keyed by cond_hash. Both go through the same checks in predict_level (guard.bot_flags). Neither →
status measurement_required (no automatic measurement in the display MVP, doc 33 §1).
"""
from __future__ import annotations

import copy
from typing import Any, Dict, Optional

from .conditions import cond_hash, finalize_game_conditions
from .model import ClearRateModel, load_model
from .predict import BotMeasurement, ClearRatePrediction, predict_level


def random_layout(game_map: Dict[str, Any]) -> bool:
    from app.core.pv.cs_shuffle import build_level_model, get_empty_tile_list
    return bool(get_empty_tile_list(build_level_model(copy.deepcopy(game_map))))


def predict_editor_level(level_json: Dict[str, Any], placement_level: Optional[int], *,
                         bot_measurement: Optional[Dict[str, Any]] = None,
                         upload_opts: Optional[Dict[str, Any]] = None,
                         model: Optional[ClearRateModel] = None) -> ClearRatePrediction:
    mdl = model or load_model()
    game_map, cond = finalize_game_conditions(level_json, placement_level, upload_opts)
    if bot_measurement is not None:
        meas: Optional[BotMeasurement] = BotMeasurement.from_dict(bot_measurement, source="request")
    else:
        hit = mdl.bot_cache.get(cond_hash(game_map, cond))
        meas = BotMeasurement.from_dict(hit, source="cache") if hit else None
    return predict_level(mdl, game_map, cond, placement_level, meas, random_layout=random_layout(game_map))
