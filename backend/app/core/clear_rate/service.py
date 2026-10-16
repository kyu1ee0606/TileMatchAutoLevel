"""Editor entry point: editor level_json + placement_level → final game conditions → measurement → predict_level.

Final game conditions = what the game will actually run, i.e. the upload conversion
(`gboost._convert_to_townpop_format`: tile order, useTileCount re-derived from the tiles, row fields) plus the
upload-panel default autoCollectCount rule (ProductionExport 'multiples10': 3 on every 10th level, else 0).
Bot measurement: the caller's (must carry the condition hash it was measured under) → else the model's cache of
live-build measurements keyed by condition hash → else status measurement_required (no automatic measurement in
the display MVP, doc 33 §1).
"""
from __future__ import annotations

import copy
from typing import Any, Dict, Optional, Tuple

from .features import GAME_FIELDS, condition_hash, normalize_conditions
from .model import ClearRateModel, load_model
from .predict import BotMeasurement, ClearRatePrediction, predict_level

UPLOAD_AUTO_COLLECT_VALUE = 3


def upload_auto_collect(placement_level: Optional[int]) -> int:
    return UPLOAD_AUTO_COLLECT_VALUE if placement_level and placement_level % 10 == 0 else 0


def game_conditions(level_json: Dict[str, Any], placement_level: Optional[int]) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """(game_map, conditions) as uploaded for this placement."""
    from app.core.pv.canonical import canonical_map
    from app.api.routes.gboost import _convert_to_townpop_format

    game_map = canonical_map(level_json)
    lj = dict(level_json)
    if isinstance(lj.get("layer"), str):
        lj["layer"] = int(lj["layer"])
    row = _convert_to_townpop_format(lj)
    cond = {k: row.get(k) for k in GAME_FIELDS}
    cond["autoCollectCount"] = upload_auto_collect(placement_level)
    return game_map, normalize_conditions(cond)


def random_layout(game_map: Dict[str, Any]) -> bool:
    from app.core.pv.cs_shuffle import build_level_model, get_empty_tile_list
    return bool(get_empty_tile_list(build_level_model(copy.deepcopy(game_map))))


def predict_editor_level(level_json: Dict[str, Any], placement_level: Optional[int], *,
                         bot_measurement: Optional[Dict[str, Any]] = None,
                         model: Optional[ClearRateModel] = None) -> ClearRatePrediction:
    mdl = model or load_model()
    game_map, cond = game_conditions(level_json, placement_level)
    if bot_measurement is not None:
        meas: Optional[BotMeasurement] = BotMeasurement.from_dict(bot_measurement, source="request")
    else:
        hit = mdl.bot_cache.get(condition_hash(game_map, cond))
        meas = BotMeasurement.from_dict(hit, source="cache") if hit else None
    return predict_level(mdl, game_map, cond, placement_level, meas, random_layout=random_layout(game_map))
