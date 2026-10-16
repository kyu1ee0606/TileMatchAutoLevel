"""Real-user clear-rate prediction (ft_any_v1) — common path for the parallel display and, later, generation /
validation / selection (docs 31 / 33).

  predict_level(model, game_map, conditions, placement_level, measurement)  pure, final game conditions in
  predict_editor_level(level_json, placement_level, bot_measurement=None)    editor level_json → upload conditions
  judge(prediction, target, support, half_width_logit=0.7)                   PASS / FAIL / INSUFFICIENT_EVIDENCE
  condition_hash(game_map, conditions)                                       tag for bot measurements
"""
from .features import GAME_FIELDS, condition_hash
from .judge import ClearRateVerdict, judge
from .model import ClearRateModel, load_model
from .predict import BotMeasurement, ClearRatePrediction, predict_level
from .service import game_conditions, predict_editor_level

__all__ = ["GAME_FIELDS", "condition_hash", "judge", "ClearRateVerdict", "ClearRateModel", "load_model",
           "BotMeasurement", "ClearRatePrediction", "predict_level", "game_conditions", "predict_editor_level"]
