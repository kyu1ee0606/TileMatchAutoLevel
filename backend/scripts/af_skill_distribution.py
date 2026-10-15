"""[분석 전용, 읽기 전용] AppsFlyer 로우 데이터 → 유저 실력(θ) 분포 추정 (봇 매핑 전 사전 조사).

목적: claudedocs/difficulty_personalization/30_af_player_skill_distribution.md 의 근거 데이터.
  첫 시도·무도움(booster/item/revive 없음) 판으로 1모수 Rasch(IRT) 모델을 적합해
  유저별 실력(theta)·레벨 난이도(b)를 함께 추정하고, 분포·생존 편향·보조지표 상관·신뢰도를 본다.
  식별자(AppsFlyer ID 등)는 af_level_metrics.py 와 동일하게 메모리 해시로만 쓰고 출력하지 않는다.
  봇 매핑/적용은 하지 않는다(사전 조사 단계).

재사용 (수정 금지): af_level_metrics.py 의 load_events/build_runs/mark_first_try/wilson/q/dist/
  seg_of/attempts_to_clear/SEGMENTS/RUN_VERSIONS/MAX_LEVEL/AF_DATA. 판 재구성 규칙은 그 파일 docstring 참조.

모델: P(clear_ul) = sigmoid(theta_u - b_l). 알터네이팅 뉴턴(JML) + theta 에 약한 사전분포 N(0,1)
  (소표본 유저 축소추정, Bayesian ridge). b_l 은 각 반복 후 평균 0 으로 재중심화(식별성).
  적합 대상: clean_ft(첫 시도·무도움·clear/final_fail) 판, 레벨 표본 수 >= --min-level-n 인 레벨만.

사용 (backend 디렉터리에서, af_level_metrics 와 같은 venv):
    .venv/bin/python scripts/af_skill_distribution.py
"""
from __future__ import annotations

import argparse
import csv
import gzip
import hashlib
import json
import math
import sys
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path

import numpy as np

csv.field_size_limit(10 ** 9)

sys.path.insert(0, str(Path(__file__).resolve().parent))
from af_level_metrics import (  # noqa: E402  (재사용, 수정 금지)
    AF_DATA, MAX_LEVEL, RUN_VERSIONS, SEGMENTS,
    build_runs, dist, load_events, mark_first_try, q, seg_of, wilson, attempts_to_clear, _int,
)

OUT_DIR = Path(__file__).resolve().parent.parent / "data/pv_sandbox/af_calibration/skill_dist"


# ---------------------------------------------------------------------------
# 설치(install) 파일에서 플랫폼/organic/매체 — af_level_metrics 와 동일한 dev 해시로 조인
# ---------------------------------------------------------------------------

def load_install_attrs(data_dir: Path):
    attrs = {}
    for plat in ("android", "ios"):
        for name, organic in ((f"{plat}_installs.csv.gz", False), (f"{plat}_organic_installs.csv.gz", True)):
            path = data_dir / name
            if not path.exists():
                continue
            with gzip.open(path, "rt", encoding="utf-8-sig", newline="", errors="replace") as fh:
                r = csv.reader(fh)
                h = next(r)
                iU, iM = h.index("AppsFlyer ID"), h.index("Media Source")
                for row in r:
                    dev = hashlib.sha1((plat + row[iU]).encode()).hexdigest()[:16]
                    if dev in attrs:
                        continue
                    attrs[dev] = {"plat": plat, "organic": organic,
                                  "media_source": (row[iM] or "organic") if not organic else "organic"}
    return attrs


# ---------------------------------------------------------------------------
# Rasch (1PL) JML 적합 — numpy bincount 벡터화
# ---------------------------------------------------------------------------

def sigmoid(x):
    return 1.0 / (1.0 + np.exp(-np.clip(x, -30, 30)))


def fit_rasch(y, uidx, lidx, n_users, n_levels, tau=1.0, iters=80, tol=1e-5):
    # 초기값: 레벨 난이도는 관측 클리어율의 로짓 음수, 유저는 0
    clear_l = np.bincount(lidx, weights=y, minlength=n_levels)
    n_l = np.bincount(lidx, minlength=n_levels)
    rate_l = np.clip(clear_l / np.maximum(n_l, 1), 0.02, 0.98)
    c = -np.log(rate_l / (1 - rate_l))
    c -= c.mean()
    a = np.zeros(n_users)
    for it in range(iters):
        a_prev, c_prev = a.copy(), c.copy()
        P = sigmoid(a[uidx] - c[lidx])
        resid = y - P
        s1 = np.bincount(uidx, weights=resid, minlength=n_users)
        s2 = np.bincount(uidx, weights=P * (1 - P), minlength=n_users)
        a = a + (s1 - tau * a) / (s2 + tau)
        P = sigmoid(a[uidx] - c[lidx])
        s3 = np.bincount(lidx, weights=(P - y), minlength=n_levels)
        s4 = np.bincount(lidx, weights=P * (1 - P), minlength=n_levels)
        c = c + s3 / np.maximum(s4, 1e-6)
        c -= c.mean()
        delta = max(np.max(np.abs(a - a_prev)), np.max(np.abs(c - c_prev)))
        if delta < tol:
            break
    n_obs_u = np.bincount(uidx, minlength=n_users)
    P = sigmoid(a[uidx] - c[lidx])
    se_den = np.bincount(uidx, weights=P * (1 - P), minlength=n_users) + tau
    se_a = 1.0 / np.sqrt(se_den)
    return a, c, n_obs_u, se_a, it + 1, delta


def solve_theta_fixed(y, uidx, lidx, c_fixed, n_users, tau=1.0, iters=40, tol=1e-6):
    """항목(c) 고정, 유저 능력만 뉴턴으로 푼다 (앞/뒤 절반 재추정용)."""
    a = np.zeros(n_users)
    for _ in range(iters):
        a_prev = a.copy()
        P = sigmoid(a[uidx] - c_fixed[lidx])
        resid = y - P
        s1 = np.bincount(uidx, weights=resid, minlength=n_users)
        s2 = np.bincount(uidx, weights=P * (1 - P), minlength=n_users)
        a = a + (s1 - tau * a) / (s2 + tau)
        if np.max(np.abs(a - a_prev)) < tol:
            break
    return a


# ---------------------------------------------------------------------------
# 분포 서술 도구
# ---------------------------------------------------------------------------

def quantile_table(vals):
    ps = [.01, .05, .1, .25, .5, .75, .9, .95, .99]
    out = {f"p{int(p * 100)}": q(vals, p) for p in ps}
    out["n"] = len(vals)
    out["mean"] = round(sum(vals) / len(vals), 4) if vals else None
    out["sd"] = round((sum((v - out["mean"]) ** 2 for v in vals) / (len(vals) - 1)) ** .5, 4) if len(vals) > 1 else None
    return out


def text_hist(vals, lo=-3.0, hi=3.0, step=0.25, width=50):
    if not vals:
        return []
    edges = np.arange(lo, hi + step, step)
    counts, _ = np.histogram(vals, bins=edges)
    below = int(sum(1 for v in vals if v < lo))
    above = int(sum(1 for v in vals if v >= hi))
    maxc = max(counts.max() if len(counts) else 0, below, above, 1)
    rows = []
    if below:
        rows.append({"bin_lo": None, "bin_hi": round(float(lo), 2), "n": below, "bar": "#" * round(below / maxc * width)})
    for i, c in enumerate(counts):
        bar = "#" * round(c / maxc * width)
        rows.append({"bin_lo": round(float(edges[i]), 2), "bin_hi": round(float(edges[i + 1]), 2),
                      "n": int(c), "bar": bar})
    if above:
        rows.append({"bin_lo": round(float(hi), 2), "bin_hi": None, "n": above, "bar": "#" * round(above / maxc * width)})
    return rows


def mixture_bic(vals):
    try:
        from sklearn.mixture import GaussianMixture
    except ImportError:
        return {"error": "sklearn 미설치"}
    X = np.array(vals).reshape(-1, 1)
    out = {}
    for k in (1, 2, 3):
        gm = GaussianMixture(n_components=k, n_init=5, random_state=0).fit(X)
        out[f"k{k}"] = {"bic": round(float(gm.bic(X)), 1),
                         "means": [round(float(m), 3) for m in sorted(gm.means_.ravel().tolist())]}
    best = min(out, key=lambda k: out[k]["bic"])
    out["best"] = best
    out["bic_gap_k1_minus_best"] = round(out["k1"]["bic"] - out[best]["bic"], 1)
    return out


def corr(xs, ys):
    xs, ys = np.array(xs, dtype=float), np.array(ys, dtype=float)
    if len(xs) < 3 or np.std(xs) == 0 or np.std(ys) == 0:
        return {"n": len(xs), "pearson": None, "spearman": None}
    try:
        from scipy.stats import pearsonr, spearmanr
        pr = pearsonr(xs, ys)
        sr = spearmanr(xs, ys)
        return {"n": len(xs), "pearson": round(float(pr[0]), 3), "pearson_p": round(float(pr[1]), 4),
                "spearman": round(float(sr[0]), 3), "spearman_p": round(float(sr[1]), 4)}
    except ImportError:
        return {"n": len(xs), "pearson": round(float(np.corrcoef(xs, ys)[0, 1]), 3), "spearman": None}


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data-dir", default=str(AF_DATA))
    ap.add_argument("--out-dir", default=str(OUT_DIR))
    ap.add_argument("--min-level-n", type=int, default=30, help="Rasch 적합에 포함할 레벨의 최소 clean_ft 판 수")
    ap.add_argument("--min-user-n", type=int, default=5, help="분포/상관 분석에 포함할 유저의 최소 clean_ft 판 수")
    ap.add_argument("--ridge-tau", type=float, default=1.0, help="theta 사전분포 N(0,1/tau) 정밀도 (축소추정)")
    a = ap.parse_args()

    per_dev, meta = load_events(Path(a.data_dir))
    print(f"events kept {meta['rows_kept']} dup {meta['dup_dropped']} range {meta['min_time']}~{meta['max_time']}",
          flush=True)
    runs, ties, orphan, level_mismatch = build_runs(per_dev)
    del per_dev
    mark_first_try(runs)
    all_runs_n = len(runs)
    runs = [r for r in runs if not r["infinite"] and 1 <= r["L"] <= MAX_LEVEL]
    print(f"runs {all_runs_n} -> official {len(runs)}", flush=True)

    install_attrs = load_install_attrs(Path(a.data_dir))
    print(f"install_attrs devices {len(install_attrs)}", flush=True)

    clean_ft = [r for r in runs if r["first_try"] and r["oc"] in ("clear", "final_fail") and not r["helped"]]
    print(f"clean_ft runs {len(clean_ft)}", flush=True)

    level_n = Counter(r["L"] for r in clean_ft)
    kept_levels = sorted(L for L, n in level_n.items() if n >= a.min_level_n)
    level_index = {L: i for i, L in enumerate(kept_levels)}
    obs = [r for r in clean_ft if r["L"] in level_index]
    devs = sorted({r["dev"] for r in obs})
    dev_index = {d: i for i, d in enumerate(devs)}
    n_users, n_levels = len(devs), len(kept_levels)
    print(f"model scope: users {n_users} levels {n_levels} obs {len(obs)}", flush=True)

    y = np.array([1.0 if r["oc"] == "clear" else 0.0 for r in obs])
    uidx = np.array([dev_index[r["dev"]] for r in obs], dtype=np.int64)
    lidx = np.array([level_index[r["L"]] for r in obs], dtype=np.int64)

    theta, b, n_obs_u, se_theta, n_iters, final_delta = fit_rasch(
        y, uidx, lidx, n_users, n_levels, tau=a.ridge_tau)
    print(f"rasch fit converged in {n_iters} iters, final delta {final_delta:.2e}", flush=True)

    # ---- 유저별 보조 정보 ----
    max_level_reached = defaultdict(int)
    by_dev_runs = defaultdict(list)
    for r in runs:
        max_level_reached[r["dev"]] = max(max_level_reached[r["dev"]], r["L"])
        by_dev_runs[r["dev"]].append(r)

    user_theta = {d: {"theta": round(float(theta[i]), 4), "se": round(float(se_theta[i]), 4),
                       "n_obs_model": int(n_obs_u[i]),
                       "plat_ver": Counter(f"{rr['plat']}|{rr['ver']}" for rr in by_dev_runs[d]
                                           if rr["first_try"] and not rr["helped"]).most_common(1),
                       "max_level_reached": max_level_reached[d],
                       "install": install_attrs.get(d)}
                  for d, i in dev_index.items()}

    pop_mask = [d for d, v in user_theta.items() if v["n_obs_model"] >= a.min_user_n]
    theta_pop = [user_theta[d]["theta"] for d in pop_mask]
    se_pop = [user_theta[d]["se"] for d in pop_mask]
    print(f"population (n_obs>={a.min_user_n}) users {len(theta_pop)}", flush=True)

    # 극단 theta 가 저정보(거의 전승/전패)로 인한 것인지 — se 를 theta 수준별로 비교
    se_by_abs_theta = {"abs_theta_lt1": [], "abs_theta_1to3": [], "abs_theta_gt3": []}
    for t, se in zip(theta_pop, se_pop):
        k = "abs_theta_lt1" if abs(t) < 1 else ("abs_theta_1to3" if abs(t) < 3 else "abs_theta_gt3")
        se_by_abs_theta[k].append(se)
    se_uncertainty_check = {k: quantile_table(v) for k, v in se_by_abs_theta.items()}

    # ---- 분포 ----
    distribution = {
        "scope": f"clean_ft(첫시도·무도움) 판 >= {a.min_level_n} 인 레벨 {n_levels}개로 적합, "
                 f"분포는 유저당 그 적합에 쓰인 판 수(n_obs_model) >= {a.min_user_n} 인 유저만",
        "n_users_total_fitted": n_users,
        "n_users_in_population": len(theta_pop),
        "quantiles": quantile_table(theta_pop),
        "se_quantiles": quantile_table(se_pop),
        "histogram": text_hist(theta_pop),
        "mixture_bic": mixture_bic(theta_pop) if len(theta_pop) >= 50 else {"error": "표본 부족"},
        "se_by_theta_level": se_uncertainty_check,
    }

    # 플랫폼/버전/organic 별
    def group_dist(keyfn):
        g = defaultdict(list)
        for d in pop_mask:
            g[keyfn(d)].append(user_theta[d]["theta"])
        return {k: quantile_table(v) for k, v in sorted(g.items())}

    breakdown = {
        "by_plat_ver": group_dist(lambda d: (user_theta[d]["plat_ver"][0][0] if user_theta[d]["plat_ver"] else "unknown")),
        "by_organic": group_dist(lambda d: ("organic" if (user_theta[d]["install"] or {}).get("organic")
                                             else ("paid" if user_theta[d]["install"] else "unknown"))),
        "by_media_source_top10": {},
    }
    ms_count = Counter((user_theta[d]["install"] or {}).get("media_source", "unknown") for d in pop_mask)
    top_ms = {k for k, _ in ms_count.most_common(10)}
    breakdown["by_media_source_top10"] = group_dist(
        lambda d: (user_theta[d]["install"] or {}).get("media_source", "unknown")
        if (user_theta[d]["install"] or {}).get("media_source", "unknown") in top_ms else "(기타)")

    # ---- 생존 편향: 구간별 도달 유저 실력 분포 + 이탈 vs 계속 ----
    seg_label = lambda L: seg_of(L)  # noqa: E731
    reached = defaultdict(set)
    for r in runs:
        s = seg_label(r["L"])
        if s:
            reached[s].add(r["dev"])

    survival = {}
    for lo, hi in SEGMENTS:
        s = f"{lo}-{hi}"
        devs_in = reached[s] & set(pop_mask)
        survival[s] = {"n_devices_reached_seg": len(reached[s]), "n_in_population": len(devs_in),
                        "theta": quantile_table([user_theta[d]["theta"] for d in devs_in])}
    leave_vs_continue = {}
    seg_list = SEGMENTS
    for i, (lo, hi) in enumerate(seg_list[:-1]):
        s = f"{lo}-{hi}"
        devs_in = reached[s] & set(pop_mask)
        continued = {d for d in devs_in if max_level_reached[d] > hi}
        left = devs_in - continued
        leave_vs_continue[s] = {
            "continued": {"n": len(continued), "theta": quantile_table([user_theta[d]["theta"] for d in continued])},
            "left": {"n": len(left), "theta": quantile_table([user_theta[d]["theta"] for d in left])},
        }

    # ---- 보조 지표 상관 ----
    aux = {}
    attempts_mean, booster_rate, revive_rate, play_sec_clear, tiles_left_fail = {}, {}, {}, {}, {}
    for d in pop_mask:
        rs = by_dev_runs[d]
        ft_ended = [r for r in rs if r["first_try"] and r["oc"] in ("clear", "final_fail")]
        if len(ft_ended) >= a.min_user_n:
            booster_rate[d] = sum(1 for r in ft_ended if r["helped"]) / len(ft_ended)
            revive_rate[d] = sum(1 for r in ft_ended if r["revives"] > 0) / len(ft_ended)
            at = attempts_to_clear(rs)
            if at.get("mean") is not None:
                attempts_mean[d] = at["mean"]
        clean = [r for r in rs if r["first_try"] and r["oc"] in ("clear", "final_fail") and not r["helped"]]
        ps = [v for v in (_int(r["clear_ev"] or {}, "play_sec") for r in clean if r["oc"] == "clear") if v]
        tl = [v for v in (_int(r["fail_ev"] or {}, "tiles_left") for r in clean if r["oc"] == "final_fail") if v]
        if ps:
            play_sec_clear[d] = sum(ps) / len(ps)
        if tl:
            tiles_left_fail[d] = sum(tl) / len(tl)

    def pair(dct):
        ks = list(dct.keys())
        return corr([user_theta[d]["theta"] for d in ks], [dct[d] for d in ks])

    aux["attempts_to_clear_mean_vs_theta"] = pair(attempts_mean)
    aux["booster_rate_vs_theta"] = pair(booster_rate)
    aux["revive_rate_vs_theta"] = pair(revive_rate)
    aux["play_sec_clear_mean_vs_theta"] = pair(play_sec_clear)
    aux["tiles_left_fail_mean_vs_theta"] = pair(tiles_left_fail)

    # ---- 안정성: 유저 자신이 플레이한 레벨을 앞/뒤 절반으로 나눠 재추정(항목 난이도는 고정) ----
    # (전체 유저 공통 레벨 기준 분할은 참여 레벨이 낮은쪽에 몰려 분할표본이 거의 안 남는다 → 유저별 자기 레벨 순위로 분할)
    kept_sorted = kept_levels
    obs_by_user = defaultdict(list)
    for i in range(len(obs)):
        obs_by_user[int(uidx[i])].append(i)
    front_idx_list, back_idx_list = [], []
    for idxs in obs_by_user.values():
        idxs.sort(key=lambda i: lidx[i])
        half = len(idxs) // 2
        front_idx_list.extend(idxs[:half])
        back_idx_list.extend(idxs[half:])
    front_idx = np.array(front_idx_list, dtype=np.int64)
    back_idx = np.array(back_idx_list, dtype=np.int64)
    theta_front = solve_theta_fixed(y[front_idx], uidx[front_idx], lidx[front_idx], b, n_users, tau=a.ridge_tau)
    theta_back = solve_theta_fixed(y[back_idx], uidx[back_idx], lidx[back_idx], b, n_users, tau=a.ridge_tau)
    n_front_u = np.bincount(uidx[front_idx], minlength=n_users)
    n_back_u = np.bincount(uidx[back_idx], minlength=n_users)
    qualify = np.where((n_front_u >= a.min_user_n) & (n_back_u >= a.min_user_n))[0]
    stability = {
        "split_method": "유저별 자기 레벨을 레벨 순서로 반 나눔(앞=낮은 레벨 절반, 뒤=높은 레벨 절반), 항목 난이도는 전체 적합값 고정",
        "n_qualifying_users": int(len(qualify)),
        "corr_front_back": corr(theta_front[qualify], theta_back[qualify]) if len(qualify) >= 3 else {"error": "표본 부족"},
    }
    # 항목 정보(discrimination) 구간별 평균 — P(1-P) 가 낮을수록(천장) 변별력 낮음
    P_full = sigmoid(theta[uidx] - b[lidx])
    info_sum = np.bincount(lidx, weights=P_full * (1 - P_full), minlength=n_levels)
    info_cnt = np.bincount(lidx, minlength=n_levels)
    info_mean = info_sum / np.maximum(info_cnt, 1)
    clear_rate_l = np.bincount(lidx, weights=y, minlength=n_levels) / np.maximum(info_cnt, 1)
    info_by_seg = defaultdict(list)
    ceiling_by_seg = defaultdict(lambda: [0, 0])
    for i, L in enumerate(kept_sorted):
        s = seg_of(L)
        if s:
            info_by_seg[s].append(float(info_mean[i]))
            ceiling_by_seg[s][1] += 1
            if clear_rate_l[i] >= 0.95:
                ceiling_by_seg[s][0] += 1
    stability["avg_item_info_by_segment"] = {s: round(sum(v) / len(v), 4) for s, v in sorted(info_by_seg.items())}
    stability["ceiling_level_share_by_segment"] = {s: round(c[0] / c[1], 3) for s, c in sorted(ceiling_by_seg.items())}

    out = {
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "scope": {
            "event_time_range_kst": [meta["min_time"], meta["max_time"]],
            "run_versions": sorted(f"{p}|{v}" for p, v in RUN_VERSIONS),
            "official_runs": len(runs), "clean_ft_runs": len(clean_ft),
            "min_level_n": a.min_level_n, "min_user_n": a.min_user_n, "ridge_tau": a.ridge_tau,
            "model_users": n_users, "model_levels": n_levels, "model_obs": len(obs),
            "rasch_iters": n_iters, "rasch_final_delta": final_delta,
        },
        "distribution": distribution,
        "breakdown": breakdown,
        "survival_bias": {"by_segment": survival, "leave_vs_continue": leave_vs_continue},
        "aux_indicator_correlations": aux,
        "stability": stability,
        "level_difficulty_sample": [{"level": L, "b": round(float(b[i]), 4), "clean_ft_n": level_n[L]}
                                     for i, L in enumerate(kept_sorted)],
    }
    od = Path(a.out_dir)
    od.mkdir(parents=True, exist_ok=True)
    (od / "skill_distribution.json").write_text(json.dumps(out, ensure_ascii=False, indent=1))
    print("done", od, flush=True)


if __name__ == "__main__":
    main()
