"""Candidate scoring, selection and verdict (doc 31 §3-3 / §4, doc 35 §3-2) — library only.

    score(pred, target, lam=0.25) -> float                      lower = closer to target, narrower range
    select(preds, target, k=3, lam=0.25) -> [ClearRatePrediction] in-support candidates, best first
    verdict(pred_c, target, support, ...) -> ClearRateVerdict   PASS | FAIL | INSUFFICIENT_EVIDENCE

Not wired to any route and not used by the existing pass/fail paths (verification_passed, /generate/validated,
production sequential check stay as they are — doc 31 D14/D17).

The verdict keeps its inputs apart and reports each: target gap, uncertainty (80% range width + training error of
that predicted zone), training support, and seed confirmation. "Target inside the 80% range" is reported as
reference only and is never a pass condition. Seed confirmation (measurement re-taken on a separate seed band,
doc 35 C) only checks that the *bot measurement* is stable; it is not an independent real-user validation of a new
map — that needs live data (doc 35 §7-2). All thresholds below are PROPOSALS (doc 31 D5/D6, P-b), not validated.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence, Tuple

from . import guard
from .predict import ClearRatePrediction, segment_of

PROPOSED = {
    "half_width_logit": 0.7,   # doc 31 D5: target band = logit(t) ± 0.7
    "p_in_band_pass": 0.5,     # doc 31 D6
    "lam": 0.25,               # doc 31 §4-1: width penalty (±5%p hit 0.37 → 0.44 on the 410-level replay)
    "confirm_bands": ("C",),   # doc 35 P-a: confirmation seed band label(s)
}
Z90 = 1.2815515655446004


@dataclass
class ClearRateVerdict:
    verdict: str                                    # PASS | FAIL | INSUFFICIENT_EVIDENCE
    reason: str
    target: float
    band: Tuple[float, float]
    gap_prob: Optional[float] = None                # expected − target
    gap_logit: Optional[float] = None
    range80_width: Optional[float] = None
    p_in_band: Optional[float] = None               # decision quantity (two-piece normal on the 80% range)
    in_range80_reference: Optional[bool] = None     # reference only — never a pass condition
    in_support: bool = False
    support_reasons: List[str] = field(default_factory=list)
    bot_seed_confirmed: bool = False                # bot-measurement stability (separate seed band), not user validation
    confidence: Optional[str] = None
    target_flags: List[Dict[str, str]] = field(default_factory=list)
    thresholds: Dict[str, Any] = field(default_factory=lambda: dict(PROPOSED))


def _logit(p: float) -> float:
    p = min(max(p, 1e-6), 1 - 1e-6)
    return math.log(p / (1 - p))


def _expit(x: float) -> float:
    return 1.0 / (1.0 + math.exp(-x))


def _phi(x: float) -> float:
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def target_band(target: float, half_width_logit: float = PROPOSED["half_width_logit"]) -> Tuple[float, float]:
    t = _logit(target)
    return _expit(t - half_width_logit), _expit(t + half_width_logit)


def p_in_band(expected: float, range80: Tuple[float, float], band: Tuple[float, float]) -> float:
    """80% range read as 10%/90% points of a two-piece normal in logit space; a side at 0/1 (target clip)
    borrows the other side's spread. Approximation — no widening of the model's range is applied."""
    mu = _logit(expected)
    lo, hi = range80
    s_lo = (mu - _logit(lo)) / Z90 if 0 < lo < expected else None
    s_hi = (_logit(hi) - mu) / Z90 if expected < hi < 1 else None
    s_lo = s_lo or s_hi or 1e-6
    s_hi = s_hi or s_lo
    w = s_lo / (s_lo + s_hi)

    def cdf(p: float) -> float:
        if p <= 0:
            return 0.0
        if p >= 1:
            return 1.0
        x = _logit(p)
        return 2 * w * _phi((x - mu) / s_lo) if x <= mu else w + 2 * (1 - w) * (_phi((x - mu) / s_hi) - 0.5)

    return max(0.0, min(1.0, cdf(band[1]) - cdf(band[0])))


def score(pred: ClearRatePrediction, target: float, lam: float = PROPOSED["lam"]) -> float:
    lo, hi = pred.range80_ft_any
    width = _logit(hi) - _logit(lo)
    return abs(_logit(pred.expected_ft_any) - _logit(target)) + lam * width


def select(preds: Sequence[ClearRatePrediction], target: float, k: int = 3,
           lam: float = PROPOSED["lam"]) -> List[ClearRatePrediction]:
    """Drop candidates without support (no number), rank the rest by score. Selection only — the verdict must
    be made on a re-measurement with a confirmation seed band (doc 35 §3-2)."""
    ok = [p for p in preds if p.in_support and p.expected_ft_any is not None]
    return sorted(ok, key=lambda p: score(p, target, lam))[:k]


def verdict(pred: ClearRatePrediction, target: float, support: Dict[str, Any], *,
            half_width_logit: float = PROPOSED["half_width_logit"],
            p_pass: float = PROPOSED["p_in_band_pass"],
            confirm_bands: Sequence[str] = PROPOSED["confirm_bands"]) -> ClearRateVerdict:
    band = target_band(target, half_width_logit)
    seg = segment_of(pred.placement_level) if pred.placement_level else None
    tflags = guard.target_flags(target, support, seg)
    seed_ok = bool(pred.measurement and pred.measurement.get("seed_band") in set(confirm_bands))
    v = ClearRateVerdict(verdict="INSUFFICIENT_EVIDENCE", reason="", target=target,
                         band=(round(band[0], 4), round(band[1], 4)), in_support=pred.in_support,
                         support_reasons=list(pred.insufficient_reasons), bot_seed_confirmed=seed_ok,
                         confidence=pred.confidence, target_flags=tflags,
                         thresholds={**PROPOSED, "half_width_logit": half_width_logit, "p_in_band_pass": p_pass,
                                     "confirm_bands": tuple(confirm_bands)})
    if not pred.in_support or pred.expected_ft_any is None:
        v.reason = "학습 지원 범위 밖: " + ", ".join(pred.insufficient_reasons or [pred.status])
        return v
    lo, hi = pred.range80_ft_any
    v.gap_prob = round(pred.expected_ft_any - target, 4)
    v.gap_logit = round(_logit(pred.expected_ft_any) - _logit(target), 4)
    v.range80_width = round(hi - lo, 4)
    v.in_range80_reference = lo <= target <= hi
    v.p_in_band = round(p_in_band(pred.expected_ft_any, (lo, hi), band), 4)
    hard_t = [f["code"] for f in tflags if f["severity"] == "hard"]
    if hard_t:
        v.reason = "목표가 학습 범위 밖: " + ", ".join(hard_t)
    elif pred.confidence == "low" or any(f["code"] == "LOW_CONFIDENCE" for f in tflags):
        v.reason = "신뢰도 낮음(예측 구간 오차·유사 맵 수·새 기믹·목표 <0.85 중 하나) — 판정하지 않음"
    elif not seed_ok:
        v.reason = (f"확인 시드 묶음({'/'.join(confirm_bands)}) 측정이 아님 — SELECTION_UNCONFIRMED "
                    "(확인 측정은 봇 측정 안정성 확인이며 실유저 검증이 아님)")
        v.target_flags = tflags + [guard.flag("SELECTION_UNCONFIRMED", "hard", v.reason)]
    else:
        v.verdict = "PASS" if v.p_in_band >= p_pass else "FAIL"
        v.reason = f"목표 범위 안 확률 {v.p_in_band:.2f} {'≥' if v.verdict == 'PASS' else '<'} {p_pass} (제안 임계)"
    return v
