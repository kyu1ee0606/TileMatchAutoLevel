"""Evidence flags + confidence for the clear-rate prediction (doc 31 §3-2 codes + measurement-condition codes).

A "suppressing" flag (SUPPRESS) means the model has no support for this input, so the prediction carries the
reason instead of a number (user decision (e), doc 33 §11). PASS/FAIL lives in select.verdict.
Target flags (target_flags) belong to the verdict (select.py), not to the prediction.
"""
from __future__ import annotations

import hashlib
import json
from typing import Any, Dict, List, Optional, Tuple

from .features import FEATS, THETAS

LOW_CONF_BELOW = 0.85    # doc 26 §11-9: actual < 0.85 → mean easy bias +0.12. Kept, but NOT a safety line: an actual
                         # 0.80 map predicted 0.90 passes it — the support-based rules below cover that case
CEILING_FROM = 0.95      # doc 31 §3-2 NEAR_CEILING (⑤ median 0.963: selection ≈ random)
NOVELTY_HIGH = 0.5
SUPPRESS = {"PLACEMENT_MISSING", "LEVEL_OUT_OF_RANGE", "GIMMICK_UNSEEN", "GIMMICK_LOW_TRAIN", "FEATURE_OOD",
            "BOT_PROTOCOL_MISMATCH", "BOT_CONDITION_MISMATCH", "BOT_SOURCE_UNKNOWN", "MEASUREMENT_MISSING", "UNSOLVED",
            "CAT_HELP_UNSUPPORTED", "TIME_LIMIT_UNSUPPORTED", "BOT_CACHE_CONDITION_MISMATCH"}

# P5 (doc 42 §3 / §5): bot measurements in the active model's bot_cache taken under a different bot setting than the
# model protocol — the rules-only ablation re-measured only levels with clean_ft_n ≥ 100, so these 8 rows were copied
# from bot_v2.4f_no_covered_info.json (behaviour items on) while still labelled v2.4 / theta4x128_v1.
# Evidence: eval_inputs/20261019/protocol_review.json sha256 edab94289e702e39e5a210c29dcaca2e0afe64ebe6b1908bf626d80a64b90a67
# (main tree, doc 42). Matched on (model version, bot version, protocol, cond_hash [map + game conditions], rows
# sha256) — never on the level number: the same map at another slot still matches; a changed map (other cond_hash)
# or a new measurement (other rows) does not. seed_band is not in the key, so relabelling the same rows does not pass.
QUARANTINE_MODEL = "cr-ftany-v24r-20261016"
QUARANTINE_BOT = ("v2.4", "theta4x128_v1")
QUARANTINED_MEASUREMENTS = {  # cond_hash → (L measured at, rows sha256, canonical map sha256 [record only])
    "b8da6375a1eda55eb244": (429, "4ce6e075deca29b10c27a3e6d4c61a565572974b73f6ae3d7d55abaee9552176",
                             "9b110c79fec19bc082f7398fe50193f63ee27c09af7de0749eca6772554ebcb0"),
    "87abdec58af8245a37c9": (433, "ee7095e43cfb54b8353585457f56da641960a2893103847f050d920c1b5be94e",
                             "2ff0e490f22287af2cb504686e98791435c97317a5fdd38f065be8b4a4f0781f"),
    "d4532b050c07c9217038": (441, "0dc3dc20d9d85f22aec58fb9952ae3ad97fae38435c58d019ec4e249dcca883d",
                             "ce857d326866e084fa1f241a5908d03c3867f391d65b1dac9aab9c4856f7561c"),
    "25552b64400c77b21d82": (466, "0f88d8fc0b7de2c257c8f5f44bcc1fe571e499e3e71b1b0be8addd322263d646",
                             "d829f60ce5c2bd0308dc1670f52be8f6d787e5bb6be8ae6476b60c10d0a98572"),
    "16de259bbc57b338ce32": (479, "ddbaed5df4ab95872f067f2778111486036e619a2c06494a979cb8ca5a60f388",
                             "ea2d088eef1c82f6813f4b6560ec9acb07fdab2e3fdfb35d83f3066493f7b293"),
    "9853ef35ce9a074a17ca": (493, "e8f2a29bee5446ef783572c7a36ff863524a8118993eecfe339bbac0f451f2db",
                             "edf57568ef318c46e5352ab7b8243e40a3d03208fd301db5e195822d5e34f888"),
    "cecfd6d013a0d4b0f688": (494, "f14263624816ed9a282739ab758e2dd5ca2abf2c8415dc016d02f041ff2f9be2",
                             "69efeaffd8bc0a9413f13653439d2109d59fac06dfac2154842793a7135ed2c6"),
    "91d0ba6cf87f82cf012a": (499, "711ab12a69f4cfacce32f0580d1eeaa84f811e1961949183f024586855921464",
                             "476493808d75c0f34c0f5eefae6e52689182e5471900816ce2c04df661442b94"),
}


def rows_sha256(rows: Any) -> str:
    """Row content hash; None-valued keys dropped so a request copy (schema fills optional fields with None)
    hashes like the cache row."""
    norm = [{k: v for k, v in r.items() if v is not None} for r in rows]
    return hashlib.sha256(json.dumps(norm, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def quarantined(manifest: Dict[str, Any], m: Any) -> bool:
    """m (predict.BotMeasurement) is one of the P5 rows measured under a different bot setting."""
    q = QUARANTINED_MEASUREMENTS.get(m.cond_hash)
    return (bool(q) and manifest.get("model_version") == QUARANTINE_MODEL
            and (m.bot_version, m.protocol) == QUARANTINE_BOT and rows_sha256(m.rows) == q[1])


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
    if quarantined(manifest, m):
        out.append(flag("BOT_CACHE_CONDITION_MISMATCH", "hard",
                        "측정 조건 불일치 → 근거 부족: 이 봇 측정은 모델과 다른 봇 설정(행동 항목 켬)으로 잰 값 (문서 42 P5)"))
    if m.bot_version != manifest["bot_version"] or m.protocol != manifest["bot_protocol"]:
        out.append(flag("BOT_PROTOCOL_MISMATCH", "hard",
                        f"측정 {m.bot_version or '?'}/{m.protocol or '?'} ≠ 모델 {manifest['bot_version']}/{manifest['bot_protocol']}"))
    if not m.cond_hash:
        out.append(flag("BOT_CONDITION_MISMATCH", "hard", "측정에 게임 조건 해시가 없음 — 어떤 맵·조건에서 잰 값인지 확인 불가"))
    elif m.cond_hash != current_hash:
        out.append(flag("BOT_CONDITION_MISMATCH", "hard",
                        f"측정한 게임 조건 {m.cond_hash} ≠ 현재 {current_hash} (맵·useTileCount·시드 등이 바뀜)"))
    if m.aids_simulated and any(m.aids_simulated.values()):
        out.append(flag("BOT_PROTOCOL_MISMATCH", "hard",
                        f"부스터/부활을 쓴 봇 측정 {m.aids_simulated} — 모델은 무도움 봇 측정으로 학습됨"))
    if m.skill_config and m.skill_config != manifest.get("bot_skill_config", ""):
        out.append(flag("BOT_PROTOCOL_MISMATCH", "hard", f"봇 실력 설정 {m.skill_config} ≠ 모델 기본"))
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

