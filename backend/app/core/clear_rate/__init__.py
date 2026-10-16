"""Real-user clear-rate prediction (ft_any_v1) — common path for the parallel display and, later, generation /
validation / selection (docs 31 / 33).

  predict_level(model, game_map, conditions, placement_level, measurement)  pure, final game conditions in
  predict_editor_level(level_json, placement_level, bot_measurement=None, upload_opts=None)
  finalize_game_conditions(level_json, slot_number, upload_opts=None)        → (game_map, conditions) as uploaded
  cond_hash(game_map, conditions)                                            tag for bot measurements
  select(preds, target, k) / score(pred, target)                             rank in-support candidates
  verdict(pred_c, target, support)                                           PASS / FAIL / INSUFFICIENT_EVIDENCE
"""
from .conditions import GAME_FIELDS, cond_hash, finalize_game_conditions
from .select import ClearRateVerdict, score, select, verdict
from .model import ClearRateModel, load_model
from .predict import BotMeasurement, ClearRatePrediction, predict_level
from .service import predict_editor_level

__all__ = ["GAME_FIELDS", "cond_hash", "finalize_game_conditions", "score", "select", "verdict", "ClearRateVerdict", "ClearRateModel", "load_model",
           "BotMeasurement", "ClearRatePrediction", "predict_level", "predict_editor_level"]
