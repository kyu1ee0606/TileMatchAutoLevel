"""Evidence flags + confidence for the clear-rate prediction (doc 31 §3-2 codes + measurement-condition codes).

A "suppressing" flag (SUPPRESS) means the model has no support for this input, so the prediction carries the
reason instead of a number (user decision (e), doc 33 §11). PASS/FAIL lives in judge.py.
Target flags (target_flags) belong to the verdict (judge.py), not to the prediction.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from .features import FEATS, THETAS

LOW_CONF_BELOW = 0.85    # doc 26 §11-9: actual < 0.85 → mean easy bias +0.12, unreliable
CEILING_FROM = 0.95      # doc 31 §3-2 NEAR_CEILING (⑤ median 0.963: selection ≈ random)
NOVELTY_HIGH = 0.5
SUPPRESS = {"PLACEMENT_MISSING", "LEVEL_OUT_OF_RANGE", "GIMMICK_UNSEEN", "GIMMICK_LOW_TRAIN", "FEATURE_OOD",
            "BOT_PROTOCOL_MISMATCH", "MEASUREMENT_MISSING", "MEASUREMENT_CONDITION_MISMATCH", "UNSOLVED"}


def flag(code: str, severity: str, detail: str = "") -> Dict[str, str]:
    return {"code": code, "severity": severity, "detail": detail}


def input_flags(support: Dict[str, Any], *, placement_level: Optional[int], gimmicks: List[str]) -> List[Dict[str, str]]:
    """Flags decidable from the map and position alone (before any bot data)."""
    out = []
    if placement_level is None:
        return [flag("PLACEMENT_MISSING", "hard", "배치 레벨 번호가 없어 도달 유저 분포를 정할 수 없음")]
    lo, hi = support["level_range"]
    if not lo <= placement_level <= hi:
        out.append(flag("LEVEL_OUT_OF_RANGE", "hard", f"학습 범위 L{lo}~{hi} 밖 (L{placement_level})"))
    counts, need = support["gimmick_train_levels"], support["min_gimmick_levels"]
    for g in gimmicks:
        n = counts.get(g, 0)
        if n == 0:
            out.append(flag("GIMMICK_UNSEEN", "hard", f"{g}: 학습 레벨 0개"))
        elif n < need:
            out.append(flag("GIMMICK_LOW_TRAIN", "hard", f"{g}: 학습 레벨 {n}개 (< {need})"))
    return out


def bot_flags(manifest: Dict[str, Any], bot_version: str, protocol: str, measured_hash: str, current_hash: str,
              rows: List[Dict[str, Any]]) -> List[Dict[str, str]]:
    out = []
    if bot_version != manifest["bot_version"] or protocol != manifest["bot_protocol"]:
        out.append(flag("BOT_PROTOCOL_MISMATCH", "hard",
                        f"측정 {bot_version}/{protocol} ≠ 모델 {manifest['bot_version']}/{manifest['bot_protocol']}"))
    if measured_hash != current_hash:
        out.append(flag("MEASUREMENT_CONDITION_MISMATCH", "hard",
                        f"측정한 게임 조건 {measured_hash} ≠ 현재 {current_hash} (맵·useTileCount·시드 등이 바뀜)"))
    by_t = {round(float(r["theta"]), 2): r for r in rows}
    missing = [t for t in THETAS if t not in by_t]
    short = [t for t in THETAS if t in by_t and int(by_t[t]["games"]) < manifest["bot_games_per_theta"]]
    if missing or short:
        out.append(flag("BOT_PROTOCOL_MISMATCH", "hard",
                        f"θ 누락 {missing} / 판 수 부족 {short} (θ당 {manifest['bot_games_per_theta']}판 필요)"))
    if rows and not missing and all(int(by_t[t]["wins"]) == 0 for t in THETAS):
        out.append(flag("UNSOLVED", "hard", "모든 θ에서 봇 클리어 0"))
    return out


def feature_flags(support: Dict[str, Any], feats: Dict[str, float]) -> List[Dict[str, str]]:
    """FEATURE_OOD: ≥ ood_min_features features outside the training 1st–99th percentile.
    (doc 31 also lists a Mahalanobis-distance rule — not implemented: 48 features / 379 levels, singular covariance.)"""
    outside = [c for c, lo, hi in zip(FEATS, support["feature_p01"], support["feature_p99"])
               if feats[c] < lo or feats[c] > hi]
    out = []
    if len(outside) >= support["ood_min_features"]:
        out.append(flag("FEATURE_OOD", "hard", "학습 1~99분위 밖 특징: " + ", ".join(outside)))
    if feats["gimmick_first"] >= 1:
        out.append(flag("GIMMICK_FIRST", "soft", "기믹 첫 등장 위치"))
    elif feats["novelty"] > NOVELTY_HIGH:
        out.append(flag("NOVELTY_HIGH", "soft", f"novelty {feats['novelty']:.2f} > {NOVELTY_HIGH}"))
    weak = [g for g in ("grass", "chain") if feats["has_" + g] >= 1]
    if weak:
        out.append(flag("GIMMICK_BOT_WEAK", "soft", f"{'+'.join(weak)}: 봇이 실패 경로를 재현 못 함"))
    return out


def value_flags(expected: float) -> List[Dict[str, str]]:
    out = []
    if expected < LOW_CONF_BELOW:
        out.append(flag("LOW_CONFIDENCE", "soft", f"예상 {expected:.3f} < {LOW_CONF_BELOW} — 이 구간은 평균 12%p 쉽게 예측됨"))
    if expected >= CEILING_FROM:
        out.append(flag("NEAR_CEILING", "soft", f"예상 {expected:.3f} ≥ {CEILING_FROM} — 천장, 구분력 낮음"))
    return out


def target_flags(target: float, support: Dict[str, Any], segment: Optional[str]) -> List[Dict[str, str]]:
    """Flags about a target value (used by judge.judge, never by the prediction itself)."""
    out = []
    if target < LOW_CONF_BELOW:
        out.append(flag("LOW_CONFIDENCE", "soft", f"목표 {target:.3f} < {LOW_CONF_BELOW} — 이 구간 예측은 신뢰 불가"))
    if target >= CEILING_FROM:
        out.append(flag("NEAR_CEILING", "soft", f"목표 {target:.3f} ≥ {CEILING_FROM} — 천장, 선별이 무작위와 비슷"))
    band = support["target_p05_p95_by_segment"].get(segment or "")
    if band and not band[0] <= target <= band[1]:
        out.append(flag("TARGET_OUT_OF_SUPPORT", "hard", f"목표 {target:.3f}가 구간 {segment} 학습 p5~p95 "
                                                         f"[{band[0]:.3f}, {band[1]:.3f}] 밖"))
    return out


def suppressed(flags: List[Dict[str, str]]) -> bool:
    return any(f["code"] in SUPPRESS for f in flags)


def confidence(flags: List[Dict[str, str]]) -> str:
    codes = {f["code"] for f in flags}
    if codes & {"LOW_CONFIDENCE", "GIMMICK_FIRST", "NOVELTY_HIGH"}:
        return "low"
    if "GIMMICK_BOT_WEAK" in codes:
        return "medium"
    return "high"

