"""Clear-rate model artifact — load + predict only (pure Python, no numpy).

Artifact layout (`backend/data/models/clear_rate/<version>/`, written by `scripts/train_clear_rate_model.py`):
  manifest.json   provenance + validation metrics (bot version, shard commit, target definition, trained_at, ...)
  model.json      heads (ridge coefficients + gradient-boosted trees), CQR width, support summary, position table
  bot_cache.json  bot measurements of the training (live) maps keyed by `features.map_hash`
Active version: `backend/data/models/clear_rate/active.json` {"version": "<version>"}.

Model = residual_model "c+" (direct ridge + direct GBM, mean of the two logits; doc 21 — same accuracy as the
library E1). 80% range = conformalized quantile regression (direct quantile GBM q0.1/q0.9 ± inner-CV width).
"""
from __future__ import annotations

import json
import math
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, List, Sequence, Tuple


MODELS_DIR = Path(__file__).resolve().parents[3] / "data" / "models" / "clear_rate"
TARGET_LOGIT_CLIP = (math.log(0.01 / 0.99), math.log(0.99 / 0.01))


def ridge_predict(R: Dict[str, Any], x: Sequence[float]) -> float:
    s = R["w0"]
    for xi, mu, sd, w in zip(x, R["mu"], R["sd"], R["w"]):
        s += (xi - mu) / sd * w
    return s


def _tree_value(t: List[Any], x: Sequence[float]) -> float:
    while t[0] == "node":
        t = t[3] if x[t[1]] <= t[2] else t[4]
    return t[1]


def gbm_predict(G: Dict[str, Any], x: Sequence[float]) -> float:
    F = G["base"]
    lr = G["lr"]
    for t in G["trees"]:
        F += lr * _tree_value(t, x)
    return F


class ClearRateModel:
    def __init__(self, directory: Path):
        self.dir = Path(directory)
        self.manifest = json.loads((self.dir / "manifest.json").read_text(encoding="utf-8"))
        self.model = json.loads((self.dir / "model.json").read_text(encoding="utf-8"))
        self.bot_cache = json.loads((self.dir / "bot_cache.json").read_text(encoding="utf-8"))
        self.features: List[str] = self.model["features"]
        self.version: str = self.manifest["model_version"]

    def _vec(self, feats: Dict[str, float], names: Sequence[str]) -> List[float]:
        return [feats[n] for n in names]

    def _point(self, head: Dict[str, Any], feats: Dict[str, float]) -> float:
        R, G = head["ridge"], head["gbm"]
        return 0.5 * (ridge_predict(R, self._vec(feats, R["feats"])) + gbm_predict(G, self._vec(feats, G["feats"])))

    def predict_logit(self, head: str, feats: Dict[str, float]) -> float:
        return self._point(self.model["heads"][head]["point"], feats)

    def predict(self, head: str, feats: Dict[str, float]) -> float:
        return expit(self.predict_logit(head, feats))

    def range80(self, head: str, feats: Dict[str, float]) -> Tuple[float, float]:
        h = self.model["heads"][head]
        a = gbm_predict(h["q_lo"], self._vec(feats, h["q_lo"]["feats"]))
        b = gbm_predict(h["q_hi"], self._vec(feats, h["q_hi"]["feats"]))
        return range_to_prob(min(a, b) - h["cqr_w"], max(a, b) + h["cqr_w"])


def range_to_prob(lo: float, hi: float) -> Tuple[float, float]:
    """Logit range → probability range. The training target is clipped to [0.01, 0.99] in logit
    (residual_model.logit), so a bound at/over the clip means "up to 0 / 1" (censored), not the clip value."""
    return (0.0 if lo <= TARGET_LOGIT_CLIP[0] + 1e-9 else expit(lo),
            1.0 if hi >= TARGET_LOGIT_CLIP[1] - 1e-9 else expit(hi))


def active_version(models_dir: Path = MODELS_DIR) -> str:
    return json.loads((models_dir / "active.json").read_text(encoding="utf-8"))["version"]


@lru_cache(maxsize=4)
def load_model(version: str = "", models_dir: str = str(MODELS_DIR)) -> ClearRateModel:
    d = Path(models_dir)
    return ClearRateModel(d / (version or active_version(d)))


def expit(x: float) -> float:
    return 1.0 / (1.0 + math.exp(-x))
