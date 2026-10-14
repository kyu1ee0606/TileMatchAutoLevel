"""[분석 전용, 읽기 전용] AF 레벨별 클리어율 test-retest(재현성) 측정.

질문: 같은 레벨인데 기간/표본을 나눠 다시 재면 클리어율이 얼마나 다른가(=예측 모델이 못 넘는 노이즈 바닥)?
그 값으로 검증 게이트(MAE≤6.7%p, 범위적중≥69%, ρ≥0.74, 80%구간 포함률 75~85%)가 현실적인지 판정한다.

판 재구성·첫 시도 판정·clean_ft 정의는 scripts/af_level_metrics.py (이하 alm) 를 그대로 import 해서 쓴다.
이 스크립트는 그 판들을 두 가지 방식으로 반으로 쪼개 반-반 차이만 잰다. 규칙을 새로 만들지 않는다.

맵 일치: VERSION_SHARD_COMMIT(3개 버전)별 빌드 샤드 vs 에디터 LIVE3 비교는 alm 이 이미 계산해
backend/data/pv_sandbox/af_calibration/level_metrics.json 의 level.map_match 에 들어 있다. 여기서는
그 결과를 그대로 읽어 map_match=="same" 레벨만 비교 대상으로 쓴다(재계산 안 함 — git show 반복 회피).

분할 2가지:
  (a) 시간 분할: 판 시작(t0) 중앙값 날짜로 앞/뒤 반 — 시간 변화(드리프트) + 표본 잡음.
  (b) 유저 분할: 기기 해시 짝/홀 — 같은 기간, 다른 유저 → 순수 표본 잡음 바닥.

출력: backend/data/pv_sandbox/af_calibration/test_retest/{time_split,user_split}.{json,csv}, summary.json.

사용 (backend 디렉터리에서):
    .venv/bin/python scripts/af_test_retest.py
"""
from __future__ import annotations

import argparse
import csv
import json
import math
import sys
from collections import defaultdict
from pathlib import Path

BACKEND = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND))
sys.path.insert(0, str(BACKEND / "scripts"))

import af_level_metrics as alm  # noqa: E402  (판 재구성·첫 시도 판정 재사용)

OUT_DIR = BACKEND / "data/pv_sandbox/af_calibration/test_retest"
EXISTING_METRICS = BACKEND / "data/pv_sandbox/af_calibration/level_metrics.json"

MIN_N = 30  # 레벨당 반쪽 표본 n 최소값
SEG_BINS = [(1, 31), (32, 100), (101, 300), (301, 500), (501, alm.MAX_LEVEL)]
N_BUCKETS = [(30, 100), (100, 300), (300, 1000), (1000, 10 ** 9)]
SQRT_2_OVER_PI = math.sqrt(2 / math.pi)


# ---------------------------------------------------------------------------
# 순위상관 (의존성 없이 — scipy/numpy 미설치)
# ---------------------------------------------------------------------------

def _ranks(vals):
    order = sorted(range(len(vals)), key=lambda i: vals[i])
    out = [0.0] * len(vals)
    i = 0
    while i < len(order):
        j = i
        while j + 1 < len(order) and vals[order[j + 1]] == vals[order[i]]:
            j += 1
        avg = (i + j) / 2 + 1
        for k in range(i, j + 1):
            out[order[k]] = avg
        i = j + 1
    return out


def spearman(xs, ys):
    n = len(xs)
    if n < 2:
        return None
    rx, ry = _ranks(xs), _ranks(ys)
    mx, my = sum(rx) / n, sum(ry) / n
    cov = sum((rx[i] - mx) * (ry[i] - my) for i in range(n))
    sx = math.sqrt(sum((v - mx) ** 2 for v in rx))
    sy = math.sqrt(sum((v - my) ** 2 for v in ry))
    if sx == 0 or sy == 0:
        return None
    return round(cov / (sx * sy), 4)


def seg_of(L):
    for a, b in SEG_BINS:
        if a <= L <= b:
            return f"{a}-{b}" if b != alm.MAX_LEVEL else f"{a}+"
    return None


def n_bucket_of(n):
    for lo, hi in N_BUCKETS:
        if lo <= n < hi:
            return f"{lo}-{hi if hi < 10 ** 9 else '+'}"
    return "<30"


# ---------------------------------------------------------------------------
# 분할
# ---------------------------------------------------------------------------

def split_time(runs):
    ts = sorted(r["t0"] for r in runs)
    median_t = ts[len(ts) // 2]
    early = [r for r in runs if r["t0"] <= median_t]
    late = [r for r in runs if r["t0"] > median_t]
    return early, late, median_t


def split_user(runs):
    even = [r for r in runs if int(r["dev"][-1], 16) % 2 == 0]
    odd = [r for r in runs if int(r["dev"][-1], 16) % 2 == 1]
    return even, odd


def group_by_level(runs):
    by = defaultdict(list)
    for r in runs:
        by[r["L"]].append(r)
    return by


# ---------------------------------------------------------------------------
# 반-반 비교
# ---------------------------------------------------------------------------

def compute_rows(by_a, by_b, by_full, map_same_levels):
    rows = []
    for L in sorted(map_same_levels):
        a = alm.level_block(by_a.get(L, []))
        b = alm.level_block(by_b.get(L, []))
        n_a, n_b = a["clean_ft_n"], b["clean_ft_n"]
        full = alm.level_block(by_full.get(L, []))
        full_n, full_rate = full["clean_ft_n"], full["clean_ft_rate"]
        row = {
            "level": L, "segment": seg_of(L),
            "n_a": n_a, "n_b": n_b, "rate_a": a["clean_ft_rate"], "rate_b": b["clean_ft_rate"],
            "full_n": full_n, "full_rate": full_rate,
            "included": n_a >= MIN_N and n_b >= MIN_N and a["clean_ft_rate"] is not None
                        and b["clean_ft_rate"] is not None and full_rate is not None and full_n,
        }
        if row["included"]:
            row["diff"] = round(row["rate_a"] - row["rate_b"], 4)
            row["abs_diff"] = round(abs(row["diff"]), 4)
            row["n_min"] = min(n_a, n_b)
            row["n_bucket"] = n_bucket_of(row["n_min"])
            # 이항분산 기반 이론 표본잡음(이 반-반 n 기준): Var(D) = p(1-p)*(1/n_a+1/n_b)
            row["var_sampling_theory"] = full_rate * (1 - full_rate) * (1 / n_a + 1 / n_b)
            # 전체표본 기준 노이즈 바닥(단일 전체표본 측정 1회의 SE): sqrt(p(1-p)/full_n)
            row["full_sample_se"] = math.sqrt(full_rate * (1 - full_rate) / full_n)
        rows.append(row)
    return rows


def aggregate(rows, key_fn, label):
    groups = defaultdict(list)
    for r in rows:
        if r["included"]:
            groups[key_fn(r)].append(r)
    out = {}
    for k, grp in sorted(groups.items()):
        n_levels = len(grp)
        mae = round(sum(r["abs_diff"] for r in grp) / n_levels, 4)
        rho = spearman([r["rate_a"] for r in grp], [r["rate_b"] for r in grp])
        var_obs = sum(r["diff"] ** 2 for r in grp) / n_levels
        var_theory = sum(r["var_sampling_theory"] for r in grp) / n_levels
        theory_mae = round(SQRT_2_OVER_PI * math.sqrt(var_theory), 4)
        var_drift = max(0.0, var_obs - var_theory)
        drift_mae_equiv = round(SQRT_2_OVER_PI * math.sqrt(var_drift), 4)
        full_floor_mae = round(SQRT_2_OVER_PI * sum(r["full_sample_se"] for r in grp) / n_levels, 4)
        out[k] = {
            "levels": n_levels, "half_half_mae": mae, "spearman_rho": rho,
            "theory_sampling_mae_half": theory_mae,  # 이 n(반쪽)에서 기대되는 순수표본잡음 MAE
            "drift_mae_equiv": drift_mae_equiv,       # 관측 - 표본잡음(분산 차) → 드리프트 성분(근사)
            "full_sample_noise_floor_mae": full_floor_mae,  # 전체표본 1회 측정의 기대오차(≈노이즈 바닥)
        }
    return out


def run_split(name, half_a, half_b, by_full, map_same_levels, out_dir):
    by_a, by_b = group_by_level(half_a), group_by_level(half_b)
    rows = compute_rows(by_a, by_b, by_full, map_same_levels)
    overall = aggregate(rows, lambda r: "ALL", name)
    by_seg = aggregate(rows, lambda r: r["segment"], name)
    by_nbucket = aggregate(rows, lambda r: r["n_bucket"], name)
    n_excluded = sum(1 for r in rows if not r["included"])
    result = {
        "split": name,
        "n_a_runs": len(half_a), "n_b_runs": len(half_b),
        "levels_total_map_same": len(map_same_levels),
        "levels_excluded_n_lt_min": n_excluded,
        "min_n": MIN_N,
        "overall": overall.get("ALL"),
        "by_segment": by_seg,
        "by_n_bucket": by_nbucket,
    }
    (out_dir / f"{name}.json").write_text(json.dumps({"summary": result, "levels": rows}, ensure_ascii=False, indent=1))
    cols = ["level", "segment", "n_a", "n_b", "rate_a", "rate_b", "diff", "abs_diff", "n_min", "n_bucket",
            "full_n", "full_rate", "included"]
    with open(out_dir / f"{name}.csv", "w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(cols)
        for r in rows:
            w.writerow([r.get(c) for c in cols])
    return result


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data-dir", default=str(alm.AF_DATA))
    ap.add_argument("--out-dir", default=str(OUT_DIR))
    a = ap.parse_args()

    out_dir = Path(a.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    per_dev, meta = alm.load_events(Path(a.data_dir))
    print(f"events kept {meta['rows_kept']} dup {meta['dup_dropped']} range {meta['min_time']}~{meta['max_time']}",
          flush=True)
    runs, _ties, _orphan, _mismatch = alm.build_runs(per_dev)
    del per_dev
    alm.mark_first_try(runs)
    runs = [r for r in runs if not r["infinite"] and 1 <= r["L"] <= alm.MAX_LEVEL]
    print(f"official runs {len(runs)}", flush=True)

    existing = json.loads(EXISTING_METRICS.read_text())
    map_same_levels = {x["level"] for x in existing["levels"] if x.get("map_match") == "same"}
    print(f"map_match==same levels: {len(map_same_levels)}", flush=True)

    by_full = group_by_level(runs)

    time_a, time_b, median_t = split_time(runs)
    user_a, user_b = split_user(runs)
    print(f"time split median_t0={median_t} sizes={len(time_a)}/{len(time_b)}", flush=True)
    print(f"user split sizes={len(user_a)}/{len(user_b)}", flush=True)

    time_res = run_split("time_split", time_a, time_b, by_full, map_same_levels, out_dir)
    user_res = run_split("user_split", user_a, user_b, by_full, map_same_levels, out_dir)

    # 전체표본(L32~500, 보정 1단계 대상 구간) 기준 노이즈 바닥 — split 과 무관, full 데이터에서 직접
    gate_segs = {"32-100", "101-300", "301-500"}
    gate_rows_time = [r for r in json.loads((out_dir / "time_split.json").read_text())["levels"]
                      if r["included"] and r["segment"] in gate_segs]
    full_floor_mae = round(SQRT_2_OVER_PI * sum(r["full_sample_se"] for r in gate_rows_time) / len(gate_rows_time), 4) \
        if gate_rows_time else None

    summary = {
        "generated_from": {"data_files": meta["files"], "event_time_range_kst": [meta["min_time"], meta["max_time"]]},
        "method": {
            "min_n_per_half": MIN_N,
            "map_filter": "level_metrics.json 의 map_match=='same' 레벨만 비교",
            "time_split_median_t0": median_t,
        },
        "time_split": time_res, "user_split": user_res,
        "gate_relevant_L32_500_full_sample_noise_floor_mae": full_floor_mae,
        "gate": {"mae_le": 0.067, "range_hit_ge": 0.69, "spearman_ge": 0.74,
                 "pi80_coverage_in": [0.75, 0.85]},
    }
    (out_dir / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=1))
    print(json.dumps({"time_overall": time_res["overall"], "user_overall": user_res["overall"],
                       "full_floor_L32_500": full_floor_mae}, ensure_ascii=False, indent=1))
    print("done", out_dir, flush=True)


if __name__ == "__main__":
    main()
