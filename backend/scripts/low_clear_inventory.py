"""[분석 전용, 읽기 전용] 저성공률 레벨 조사 — 문서 35a 산출.

기존 산출물만 읽어서 집계한다. 새 봇 측정·AF 재수집 없음.

입력 (모두 읽기만 함):
  - backend/data/pv_sandbox/af_calibration/level_metrics.json (af_level_metrics.py 산출, 1~1500)
  - backend/data/pv_sandbox/af_calibration/bot_v23/{prep.json, bot_v2.3.json} (rm.build, L32~500)
  - backend/data/pv_sandbox/af_calibration/bot_v24/bot_v2.4.json (botv2.4 측정 여부만 확인)
  - backend/data/production/batch_1792056041502_cn5e4ny66.json (레거시 예측값, L1~1530)

정의 (문서 31 §1-5 / target_metric_eval.py 와 동일):
  - 379레벨 = bot_v23 410(=rm.build 결과 중 not exclude & clean_ft_n>=100 & has_bot, L32~500)
    ∩ level_metrics map_match=="same" ∩ first_try_ended>=100 ∩ 레거시 predicted_clear_rate 존재(truthy)
  - 목표 지표 ft_any = level_metrics.json 의 ft_clear_rate_any_help (첫 시도 전체, 도움 포함, no_end 제외)

사용 (backend 디렉터리에서, numpy 필요 → analysis_venv):
    ../analysis_venv/bin/python scripts/low_clear_inventory.py
출력: backend/data/pv_sandbox/af_calibration/low_clear_inventory.json
"""
from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path

BACKEND = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND / "scripts"))
import residual_model as rm  # noqa: E402

CAL = rm.CAL
LEGACY_BATCH = BACKEND / "data/production/batch_1792056041502_cn5e4ny66.json"
OUT = CAL / "low_clear_inventory.json"
MAX_AF_LEVEL = 1500
MAX_LEGACY_LEVEL = 1530
MIN_N = rm.MIN_N  # 100

BUCKETS = [
    ("<0.30", 0.0, 0.30), ("0.30-0.50", 0.30, 0.50), ("0.50-0.70", 0.50, 0.70),
    ("0.70-0.85", 0.70, 0.85), ("0.85-0.92", 0.85, 0.92), ("0.92-0.96", 0.92, 0.96),
    (">=0.96", 0.96, 1.0001),
]


def bucket_of(v):
    for name, lo, hi in BUCKETS:
        if lo <= v < hi:
            return name
    return ">=0.96"


def gimmick_tag(L):
    if L in (5, 15, 35, 45):
        return "booster_forced"
    if L == 341:
        return "time_limit"
    if L % 10 == 0:
        return "cat_help"
    return None


def main():
    lm_raw = json.load(open(CAL / "level_metrics.json", encoding="utf-8"))
    LM = {r["level"]: r for r in lm_raw["levels"]}

    leg = json.load(open(LEGACY_BATCH, encoding="utf-8"))
    LEG = {lv["meta"]["level_number"]: lv["meta"].get("predicted_clear_rate") for lv in leg["levels"]}

    # bot_v23 410 세트 (rm.build 와 동일한 필터) — L32~500
    recs23 = rm.build(CAL / "bot_v23/bot_v2.3.json")
    REC23 = {r["L"]: r for r in recs23}
    SET410 = {L for L, r in REC23.items() if not r["exclude"] and r["clean_n"] >= MIN_N and r["has_bot"]}
    SET_V23_RAW = {L for L, r in REC23.items() if r["has_bot"]}  # exclude/clean_n 무시, 측정만 존재

    # bot_v24 측정 존재 여부 (같은 L32~500 prep 기준)
    bot24 = rm.bot_table(CAL / "bot_v24/bot_v2.4.json")
    SET_V24_RAW = {L for L, b in bot24.items() if all(t in b for t in rm.THETAS)}

    # 379 세트
    SET379 = set()
    for L in SET410:
        m = LM.get(L)
        if not m or m.get("map_match") != "same":
            continue
        if (m.get("first_try_ended") or 0) < MIN_N:
            continue
        if not LEG.get(L):
            continue
        SET379.add(L)

    print("check n_379 =", len(SET379), "(기대 379)", flush=True)

    rows = []
    for L in range(1, MAX_LEGACY_LEVEL + 1):
        m = LM.get(L) if L <= MAX_AF_LEVEL else None
        ft_any = m.get("ft_clear_rate_any_help") if m else None
        n_fte = m.get("first_try_ended") if m else None
        row = {
            "L": L,
            "has_af_data": m is not None,
            "ft_any": ft_any,
            "n_first_try_ended": n_fte,
            "clean_ft_n": m.get("clean_ft_n") if m else None,
            "map_match": m.get("map_match") if m else None,
            "help_rate": m.get("ft_help_rate") if m else None,
            "noend_rate": m.get("ft_noend_rate") if m else None,
            "lb_unaided": m.get("unaided_clear_lower_bound") if m else None,
            "ub_unaided": m.get("unaided_clear_upper_bound") if m else None,
            "bucket": bucket_of(ft_any) if ft_any is not None else None,
            "in_bot_v23_raw": L in SET_V23_RAW,
            "in_bot_v23_410": L in SET410,
            "in_bot_v24_raw": L in SET_V24_RAW,
            "has_legacy_pred": bool(LEG.get(L)),
            "legacy_pred": LEG.get(L),
            "gimmick_tag": gimmick_tag(L),
            "in_379": L in SET379,
            "clean_ft_by_version": m.get("clean_ft_by_version") if m else None,
        }
        rows.append(row)

    # 제외 사유 분류 (379 아닌 레벨만, 우선순위 하향)
    def exclusion_reason(r):
        L = r["L"]
        if r["in_379"]:
            return None
        if not r["has_af_data"]:
            return "range_1501_1530_no_af_data"
        if L < 32 or L > 500:
            return "range_out_of_bot_scope_L1-31_or_L501+"
        if (r["n_first_try_ended"] or 0) < MIN_N or (r["clean_ft_n"] or 0) < MIN_N:
            return f"sample_insufficient(<{MIN_N})"
        if r["map_match"] != "same":
            return f"map_mismatch({r['map_match']})"
        if r["gimmick_tag"]:
            return f"gimmick_exclusion({r['gimmick_tag']})"
        if not r["in_bot_v23_410"]:
            return "no_bot_measurement_other"
        if not r["has_legacy_pred"]:
            return "no_legacy_pred_only(구모델비교용, 신규학습제외아님)"
        return "unknown"

    for r in rows:
        r["exclusion_reason"] = exclusion_reason(r)

    # 구간별 인벤토리 (1~1500, AF 데이터 있는 것만 ft_any 기준 버킷)
    bucket_table = []
    for name, lo, hi in BUCKETS:
        sub = [r for r in rows if r["ft_any"] is not None and lo <= r["ft_any"] < hi]
        ns = [r["n_first_try_ended"] for r in sub if r["n_first_try_ended"]]
        ns_sorted = sorted(ns)
        median_n = ns_sorted[len(ns_sorted) // 2] if ns_sorted else None
        bucket_table.append({
            "bucket": name, "n_levels": len(sub),
            "n_first_try_ended_sum": sum(ns), "n_first_try_ended_median": median_n,
            "map_match_same": sum(1 for r in sub if r["map_match"] == "same"),
            "bot_v23_measured": sum(1 for r in sub if r["in_bot_v23_raw"]),
            "bot_v24_measured": sum(1 for r in sub if r["in_bot_v24_raw"]),
            "has_legacy_pred": sum(1 for r in sub if r["has_legacy_pred"]),
            "in_379": sum(1 for r in sub if r["in_379"]),
            "analyzable_af(n>=100&map_same)": sum(
                1 for r in sub if r["map_match"] == "same" and (r["n_first_try_ended"] or 0) >= MIN_N),
        })

    exclusion_summary = Counter(r["exclusion_reason"] for r in rows if r["exclusion_reason"])

    low = sorted([r for r in rows if r["ft_any"] is not None and r["ft_any"] < 0.85],
                 key=lambda r: r["ft_any"])

    out = {
        "meta": {
            "n_379_check": len(SET379), "min_n": MIN_N, "max_af_level": MAX_AF_LEVEL,
            "max_legacy_level": MAX_LEGACY_LEVEL,
            "level_metrics_generated_at": lm_raw.get("generated_at"),
            "target_metric": "ft_clear_rate_any_help (첫 시도 전체, 도움 포함, no_end 제외)",
        },
        "bucket_table": bucket_table,
        "exclusion_summary": dict(sorted(exclusion_summary.items(), key=lambda x: -x[1])),
        "low_clear_levels_lt_085": low,
        "all_levels": rows,
    }
    OUT.write_text(json.dumps(out, ensure_ascii=False, indent=1))
    print("done ->", OUT, "n_low<0.85 =", len(low), flush=True)


if __name__ == "__main__":
    main()
