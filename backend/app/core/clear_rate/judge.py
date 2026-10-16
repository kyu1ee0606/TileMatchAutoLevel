"""Verdict for a (prediction, target) pair — doc 31 §3-3. Library only, for the later generation / selection path.

    judge(prediction, target, support, half_width_logit=0.7) -> ClearRateVerdict   PASS | FAIL | INSUFFICIENT_EVIDENCE

Not wired to any route and not used by the existing pass/fail paths (verification_passed, /generate/validated,
production sequential check stay as they are — doc 31 D14/D17).
Rules: no support (any suppressing flag) or a hard target flag → INSUFFICIENT_EVIDENCE; confidence low (prediction
or target < 0.85) → INSUFFICIENT_EVIDENCE; else P(actual in target band) ≥ 0.5 → PASS, otherwise FAIL.
P(in band) treats the 80% range as a two-piece normal in logit space (lo/hi = 10%/90% points); a side at the
target clip (0 or 1) borrows the other side's spread.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

from . import guard
from .predict import ClearRatePrediction, segment_of

Z90 = 1.2815515655446004  # standard-normal 90% point
P_IN_PASS = 0.5
DEFAULT_HALF_WIDTH_LOGIT = 0.7  # doc 31 D5


@dataclass
class ClearRateVerdict:
    verdict: str                                   # PASS | FAIL | INSUFFICIENT_EVIDENCE
    reason: str
    target: float
    band: Tuple[float, float]
    p_in_band: Optional[float]
    target_flags: List[Dict[str, str]] = field(default_factory=list)


def _logit(p: float) -> float:
    return math.log(p / (1 - p))


def _expit(x: float) -> float:
    return 1.0 / (1.0 + math.exp(-x))


def _phi(x: float) -> float:
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def target_band(target: float, half_width_logit: float = DEFAULT_HALF_WIDTH_LOGIT) -> Tuple[float, float]:
    t = _logit(min(max(target, 1e-6), 1 - 1e-6))
    return _expit(t - half_width_logit), _expit(t + half_width_logit)


def p_in_band(expected: float, range80: Tuple[float, float], band: Tuple[float, float]) -> float:
    mu = _logit(expected)
    lo, hi = range80
    s_lo = (mu - _logit(lo)) / Z90 if 0 < lo < expected else None
    s_hi = (_logit(hi) - mu) / Z90 if expected < hi < 1 else None
    s_lo = s_lo or s_hi or 1e-6
    s_hi = s_hi or s_lo

    def cdf(p: float) -> float:  # two-piece normal CDF at probability p (mass split at mu by spread ratio)
        if p <= 0:
            return 0.0
        if p >= 1:
            return 1.0
        x = _logit(p)
        w = s_lo / (s_lo + s_hi)
        return 2 * w * _phi((x - mu) / s_lo) if x <= mu else w + 2 * (1 - w) * (_phi((x - mu) / s_hi) - 0.5)

    return max(0.0, min(1.0, cdf(band[1]) - cdf(band[0])))


def judge(pred: ClearRatePrediction, target: float, support: Dict[str, Any],
          half_width_logit: float = DEFAULT_HALF_WIDTH_LOGIT) -> ClearRateVerdict:
    band = target_band(target, half_width_logit)
    seg = segment_of(pred.placement_level) if pred.placement_level else None
    tflags = guard.target_flags(target, support, seg)
    res = ClearRateVerdict(verdict="INSUFFICIENT_EVIDENCE", reason="", target=target,
                           band=(round(band[0], 4), round(band[1], 4)), p_in_band=None, target_flags=tflags)
    if not pred.in_support or pred.expected_ft_any is None:
        res.reason = "예측 근거 부족: " + ", ".join(pred.insufficient_reasons or [pred.status])
        return res
    hard_t = [f["code"] for f in tflags if f["severity"] == "hard"]
    if hard_t:
        res.reason = "목표 근거 부족: " + ", ".join(hard_t)
        return res
    p = p_in_band(pred.expected_ft_any, pred.range80_ft_any, band)
    res.p_in_band = round(p, 4)
    if pred.confidence == "low" or any(f["code"] == "LOW_CONFIDENCE" for f in tflags):
        res.reason = "신뢰도 낮음 — 판정에 쓰지 않음"
        return res
    res.verdict = "PASS" if p >= P_IN_PASS else "FAIL"
    res.reason = f"목표 범위 안 확률 {p:.2f} {'≥' if p >= P_IN_PASS else '<'} {P_IN_PASS}"
    return res
