"""Mode B — bot virtual clear rate (doc 35 §9). Pure functions; imports no clear-rate model.

    VirtualDef / DEFAULT_DEF / def_id            fixed, hashable definition (bot v2.4 rules only, θ 0.85, no help)
    virtual_rate(measurement, d) -> dict         θ rate + Wilson 95% (bot trial error only)
    select_virtual(cands, target, k) -> list     |logit r_S − logit target| ascending, ties by candidate index
    virtual_verdict(meas_c, d, target, current_hash) -> BotVirtualVerdict
                                                 BOT_TARGET_MET | BOT_TARGET_NOT_MET | BOT_MEASUREMENT_INSUFFICIENT

The value is the success rate of the bot under this definition. It is NOT a real-user clear rate: the bot plays
without boosters / revives and its gap to real users is not modelled here (that is what mode A's calibration
model does). Every result carries real_user_status = "unverified". A bot target being met is not a user pass, and
B values must not be written to predicted_clear_rate / A fields / the display difficulty / upload. 0 wins does not
mean the map is impossible (solvability is not checked here) → measurement insufficient.
Thresholds are the pilot proposals of doc 35 P-h / P-i (absolute ±5%p, Wilson half-width > tolerance =
insufficient) — experiment criteria, not validated.
"""
from __future__ import annotations

import hashlib
import json
import math
from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Optional, Sequence, Tuple

REAL_USER_UNVERIFIED = "unverified"
MET, NOT_MET, INSUFFICIENT = "BOT_TARGET_MET", "BOT_TARGET_NOT_MET", "BOT_MEASUREMENT_INSUFFICIENT"
Z95 = 1.959963984540054


@dataclass(frozen=True)
class VirtualDef:
    metric: str = "bot_virtual_v1"
    bot_version: str = "v2.4"
    behavior: Tuple[str, ...] = ("unknown_hide", "curtain_hide", "unknown_nobonus", "ac_inner", "stack_hide",
                                 "dock_rel")   # = bot_simulator.V24_DEFAULT (rule-parity items only; test checks)
    aggregate: str = "single_theta"
    theta: float = 0.85
    search_protocol: str = "theta4x128_v1"      # S: shared with mode A (4 θ × 128)
    confirm_protocol: str = "theta085x512_v1"   # C: θ 0.85 × 512
    confirm_games: int = 512
    seed_bands: Tuple[str, str] = ("S", "C")    # S 15,000,000 / C 16,000,000 + layout*1000 + game
    help: str = "none"                          # no boosters / revives (cat auto-collect = game condition)
    random_layout: str = "bot_af_L32_500.level_layouts (32 layouts if empty slots)"
    max_moves: str = "level max_moves (t0ize.bot_level_json)"
    tolerance_abs: float = 0.05                 # pilot proposal (P-i)
    weights_basis: str = ""                     # only for aggregate="weighted" (not used)

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d["behavior"], d["seed_bands"] = list(self.behavior), list(self.seed_bands)
        return d

    @property
    def def_id(self) -> str:
        return hashlib.sha256(json.dumps(self.to_dict(), sort_keys=True).encode()).hexdigest()[:16]


DEFAULT_DEF = VirtualDef()
DISPLAY_NAME = "봇 가상 클리어율"
DISPLAY_NOTE = "봇 시행 오차만 반영 — 실유저 예측 범위 아님 · 봇 목표 충족 ≠ 유저 합격"


def wilson(wins: int, n: int, z: float = Z95) -> Tuple[float, float]:
    if n <= 0:
        return 0.0, 1.0
    p = wins / n
    den = 1 + z * z / n
    c = (p + z * z / (2 * n)) / den
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / den
    return max(0.0, c - h), min(1.0, c + h)


def _theta_row(rows: Sequence[Dict[str, Any]], theta: float) -> Optional[Dict[str, Any]]:
    return next((r for r in rows if round(float(r["theta"]), 2) == round(theta, 2)), None)


def virtual_rate(m: Any, d: VirtualDef = DEFAULT_DEF) -> Optional[Dict[str, Any]]:
    """m: predict.BotMeasurement (duck-typed). None when the definition's θ row is missing."""
    r = _theta_row(list(m.rows), d.theta)
    if not r or not int(r.get("games") or 0):
        return None
    w, n = int(r["wins"]), int(r["games"])
    lo, hi = wilson(w, n)
    return {"theta": d.theta, "wins": w, "games": n, "rate": round(w / n, 4), "ci95": (round(lo, 4), round(hi, 4)),
            "half_width": round((hi - lo) / 2, 4), "fail_reasons": dict(r.get("fail_reasons") or {}),
            "seed_band": m.seed_band, "cond_hash": m.cond_hash, "protocol": m.protocol}


def _logit(p: float, eps: float = 1e-3) -> float:
    p = min(1 - eps, max(eps, p))
    return math.log(p / (1 - p))


def select_virtual(cands: Sequence[Tuple[Any, float]], target: float, k: int = 1) -> List[Tuple[Any, float]]:
    """cands: (candidate key, S rate) in candidate-index order. Rank by |logit r − logit t|, stable (ties keep
    index order). 0-win candidates stay rankable but are never confirmed as met (see virtual_verdict)."""
    order = sorted(range(len(cands)), key=lambda i: (abs(_logit(cands[i][1]) - _logit(target)), i))
    return [cands[i] for i in order[:k]]


@dataclass
class BotVirtualVerdict:
    bot_virtual_verdict: str
    reason: str
    bot_virtual_def_id: str
    bot_virtual_target: float
    bot_virtual_tolerance: float
    bot_virtual_rate_c: Optional[float] = None
    bot_virtual_ci95_c: Optional[Tuple[float, float]] = None
    bot_virtual_half_width_c: Optional[float] = None
    bot_virtual_games_c: int = 0
    bot_virtual_gap: Optional[float] = None
    real_user_status: str = REAL_USER_UNVERIFIED       # always — bot result, never a real-user verification
    notes: List[str] = field(default_factory=lambda: [DISPLAY_NOTE])

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d["bot_virtual_ci95_c"] = list(self.bot_virtual_ci95_c) if self.bot_virtual_ci95_c else None
        return d


def measurement_problems(m: Any, d: VirtualDef, current_hash: str, *, stage: str) -> List[str]:
    """Reasons a measurement cannot be used for this definition (bot version / protocol / band / condition / aids)."""
    out = []
    if m is None:
        return [f"{stage} 측정 없음"]
    idx = 1 if stage == "C" else 0              # stage: "S" = search, "C" = confirmation (bands from the definition)
    proto = d.confirm_protocol if idx else d.search_protocol
    band = d.seed_bands[idx]
    if m.bot_version != d.bot_version:
        out.append(f"봇 버전 {m.bot_version or '?'} ≠ 정의 {d.bot_version}")
    if m.protocol != proto:
        out.append(f"프로토콜 {m.protocol or '?'} ≠ 정의 {proto}")
    if m.seed_band != band:
        out.append(f"시드 묶음 {m.seed_band or '?'} ≠ {band}")
    if not m.cond_hash or m.cond_hash != current_hash:
        out.append(f"조건 해시 {m.cond_hash or '?'} ≠ 현재 {current_hash}")
    if m.aids_simulated and any(m.aids_simulated.values()):
        out.append(f"도움 사용 측정 {m.aids_simulated} — 정의는 무도움")
    if any(int(r.get("wins", 0)) > int(r.get("games", 0)) or int(r.get("wins", 0)) < 0 for r in m.rows):
        out.append("승수가 판 수보다 크거나 음수")
    return out


def virtual_verdict(m_c: Any, d: VirtualDef, target: float, current_hash: str) -> BotVirtualVerdict:
    v = BotVirtualVerdict(bot_virtual_verdict=INSUFFICIENT, reason="", bot_virtual_def_id=d.def_id,
                          bot_virtual_target=target, bot_virtual_tolerance=d.tolerance_abs)
    probs = measurement_problems(m_c, d, current_hash, stage="C")
    vr = virtual_rate(m_c, d) if not probs else None
    if not probs and vr is None:
        probs = [f"θ{d.theta} 행 없음"]
    if probs:
        v.reason = "측정 부족: " + "; ".join(probs)
        return v
    v.bot_virtual_rate_c, v.bot_virtual_ci95_c = vr["rate"], vr["ci95"]
    v.bot_virtual_half_width_c, v.bot_virtual_games_c = vr["half_width"], vr["games"]
    v.bot_virtual_gap = round(vr["rate"] - target, 4)
    if vr["games"] < d.confirm_games:
        v.reason = f"측정 부족: θ{d.theta} {vr['games']}판 < {d.confirm_games}"
    elif vr["wins"] == 0:
        v.reason = "측정 부족: 봇 전원 실패 · 풀이 가능 여부 미확인 (0승 ≠ 불가능 맵)"
    elif vr["half_width"] > d.tolerance_abs:
        v.reason = f"측정 부족: Wilson 95% 반폭 {vr['half_width']:.3f} > 허용 폭 {d.tolerance_abs}"
    elif abs(v.bot_virtual_gap) <= d.tolerance_abs + 1e-12:
        v.bot_virtual_verdict = MET
        v.reason = f"봇 기준 목표 충족: |{vr['rate']:.3f} − {target:.3f}| ≤ {d.tolerance_abs} (실유저 기준: 실측 미검증)"
    else:
        v.bot_virtual_verdict = NOT_MET
        v.reason = f"봇 기준 목표 미충족: |{vr['rate']:.3f} − {target:.3f}| > {d.tolerance_abs} (실유저 기준: 실측 미검증)"
    return v


__all__ = ["VirtualDef", "DEFAULT_DEF", "BotVirtualVerdict", "virtual_rate", "select_virtual", "virtual_verdict",
           "measurement_problems", "wilson", "MET", "NOT_MET", "INSUFFICIENT", "REAL_USER_UNVERIFIED"]
