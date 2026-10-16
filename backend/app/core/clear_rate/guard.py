"""Evidence flags + confidence for the clear-rate prediction (doc 31 §3-2 codes + measurement-condition codes).

A "suppressing" flag (SUPPRESS) means the model has no support for this input, so the prediction carries the
reason instead of a number (user decision (e), doc 33 §11). PASS/FAIL lives in select.verdict.
Target flags (target_flags) belong to the verdict (select.py), not to the prediction.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

from .features import FEATS, THETAS

LOW_CONF_BELOW = 0.85    # doc 26 §11-9: actual < 0.85 → mean easy bias +0.12. Kept, but NOT a safety line: an actual
                         # 0.80 map predicted 0.90 passes it — the support-based rules below cover that case
CEILING_FROM = 0.95      # doc 31 §3-2 NEAR_CEILING (⑤ median 0.963: selection ≈ random)
NOVELTY_HIGH = 0.5
SUPPRESS = {"PLACEMENT_MISSING", "LEVEL_OUT_OF_RANGE", "GIMMICK_UNSEEN", "GIMMICK_LOW_TRAIN", "FEATURE_OOD",
            "BOT_PROTOCOL_MISMATCH", "BOT_CONDITION_MISMATCH", "BOT_SOURCE_UNKNOWN", "MEASUREMENT_MISSING", "UNSOLVED",
            "CAT_HELP_UNSUPPORTED", "TIME_LIMIT_UNSUPPORTED"}


def flag(code: str, severity: str, detail: str = "") -> Dict[str, str]:
    return {"code": code, "severity": severity, "detail": detail}


def input_flags(support: Dict[str, Any], *, placement_level: Optional[int], gimmicks: List[str],
                conditions: Optional[Dict[str, Any]] = None) -> List[Dict[str, str]]:
    """Flags decidable from the map, final game conditions and position alone (before any bot data)."""
    out = []
    if placement_level is None:
        return [flag("PLACEMENT_MISSING", "hard", "배치 레벨 번호가 없어 도달 유저 분포를 정할 수 없음")]
    cond = conditions or {}
    have, need = support.get("condition_train_levels", {}), support.get("min_condition_levels", 10)
    if int(cond.get("autoCollectCount") or 0) > 0 and have.get("cat_help", 0) < need:
        out.append(flag("CAT_HELP_UNSUPPORTED", "hard", f"냥이 자동 수집(autoCollectCount={cond['autoCollectCount']}) "
                                                        f"레벨: 학습 {have.get('cat_help', 0)}개 (< {need})"))
    if int(cond.get("timea") or 0) > 0 and have.get("time_limit", 0) < need:
        out.append(flag("TIME_LIMIT_UNSUPPORTED", "hard", f"시간 제한(timea={cond['timea']}) 레벨: "
                                                          f"학습 {have.get('time_limit', 0)}개 (< {need})"))
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


def bot_flags(manifest: Dict[str, Any], m: Any, current_hash: str) -> List[Dict[str, str]]:
    """Same checks for cached and caller-supplied measurements (m: predict.BotMeasurement): game-condition hash,
    bot version, protocol (θ grid × games), seed-band provenance."""
    out, rows = [], list(m.rows)
    if m.bot_version != manifest["bot_version"] or m.protocol != manifest["bot_protocol"]:
        out.append(flag("BOT_PROTOCOL_MISMATCH", "hard",
                        f"측정 {m.bot_version or '?'}/{m.protocol or '?'} ≠ 모델 {manifest['bot_version']}/{manifest['bot_protocol']}"))
    if not m.cond_hash:
        out.append(flag("BOT_CONDITION_MISMATCH", "hard", "측정에 게임 조건 해시가 없음 — 어떤 맵·조건에서 잰 값인지 확인 불가"))
    elif m.cond_hash != current_hash:
        out.append(flag("BOT_CONDITION_MISMATCH", "hard",
                        f"측정한 게임 조건 {m.cond_hash} ≠ 현재 {current_hash} (맵·useTileCount·시드 등이 바뀜)"))
    if not m.seed_band:
        out.append(flag("BOT_SOURCE_UNKNOWN", "hard", "측정 시드 묶음(seed_band) 출처가 없음"))
    if any(int(r.get("wins", 0)) > int(r.get("games", 0)) or int(r.get("wins", 0)) < 0 for r in rows):
        out.append(flag("BOT_PROTOCOL_MISMATCH", "hard", "승수가 판 수보다 크거나 음수"))
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
    """Flags about a target value (used by select.verdict, never by the prediction itself)."""
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


# Support-based reliability (doc 35 / user rule: judge trust from what is known before release — never from the
# map's actual clear or help rate). Thresholds are PROPOSALS from the training OOF tables (model support
# "reliability"), not guarantees.
ZONE_LOW = {"mae_ge": 0.045, "coverage80_lt": 0.75}   # OOF: pred < 0.88 MAE 0.091 / cov 0.66; 0.88–0.92 0.047 / 0.73
ZONE_MEDIUM = {"mae_ge": 0.035}                        # 0.92–0.95 MAE 0.039
COMBO_FEW_LT = 5                                       # same gimmick combination in training
COMBO_MAE_GE = 0.05                                    # e.g. grass+link 0.059, stack+chain 0.110


def reliability(support: Dict[str, Any], expected: float, combo: str, segment: Optional[str],
                range80: Tuple[float, float]) -> Dict[str, Any]:
    rel = support.get("reliability") or {}
    zone = next((b for b in rel.get("pred_bins", []) if b["lo"] <= expected < b["hi"] or
                 (b["hi"] >= 1.0 and expected >= b["lo"])), None)
    return {"pred_zone": zone, "combo": {"key": combo, **(rel.get("combo", {}).get(combo) or {"n": 0})},
            "segment": rel.get("segment", {}).get(segment or ""), "range80_width": round(range80[1] - range80[0], 4)}


def reliability_flags(rel: Dict[str, Any]) -> List[Dict[str, str]]:
    out = []
    z = rel.get("pred_zone")
    if z:
        d = (f"예측 {z['lo']:.2f}~{z['hi']:.2f} 구간 학습 OOF: n {z['n']}, MAE {z['mae']:.3f}, 편향 {z['bias']:+.3f}, "
             f"80% 범위 포함 {z['coverage80']:.2f}")
        if z["mae"] >= ZONE_LOW["mae_ge"] or z["coverage80"] < ZONE_LOW["coverage80_lt"]:
            out.append(flag("PRED_ZONE_HIGH_ERROR", "soft", d + " — 오차 큼·범위가 좁게 나옴(넓히는 보정은 하지 않음)"))
        elif z["mae"] >= ZONE_MEDIUM["mae_ge"]:
            out.append(flag("PRED_ZONE_MID_ERROR", "soft", d))
    c = rel["combo"]
    if c["n"] < COMBO_FEW_LT:
        out.append(flag("SIMILAR_MAPS_FEW", "soft", f"같은 기믹 조합({c['key']}) 학습 {c['n']}레벨 (< {COMBO_FEW_LT})"))
    elif c["mae"] >= COMBO_MAE_GE:
        out.append(flag("COMBO_HIGH_ERROR", "soft", f"기믹 조합 {c['key']} 학습 OOF MAE {c['mae']:.3f} (n {c['n']})"))
    return out


def suppressed(flags: List[Dict[str, str]]) -> bool:
    return any(f["code"] in SUPPRESS for f in flags)


def confidence(flags: List[Dict[str, str]]) -> str:
    codes = {f["code"] for f in flags}
    if codes & {"LOW_CONFIDENCE", "GIMMICK_FIRST", "NOVELTY_HIGH", "PRED_ZONE_HIGH_ERROR", "SIMILAR_MAPS_FEW",
                 "COMBO_HIGH_ERROR"}:
        return "low"
    if codes & {"GIMMICK_BOT_WEAK", "PRED_ZONE_MID_ERROR"}:
        return "medium"
    return "high"

