"""목표 지표(⑤ 첫 시도 전체, 도움 포함) 비교·선별 재현 — 문서 31 §2-0/§4 피드백 반영 재현용 스크립트.

같은 목표 정의(⑤ ft_clear_rate_any_help) · 같은 레벨 집합(bot_v23 410레벨 ∩ map_match=="same"
∩ 레거시 predicted_clear_rate 있음, n=379) · 같은 검증 조건(맵해시 group K-fold, 5겹×REPS반복)에서
4가지를 비교한다:
  (a) 기존 predicted_clear_rate 원값 (배치 메타, 재학습 없음)
  (b) (a)를 학습 폴드에서만 logit-선형 재보정한 공정 기준선
  (c) 봇 없는 기준선 (학습 폴드 구간 평균)
  (d) E1(Ridge+LightGBM 단조), 목표 열 = ⑤로 재학습

그리고 ⑤ 목표로 "기존 410레벨을 후보로 선별" 재현을 고정 확률 폭(±5/±10%p) 및 logit 폭(±0.7)
각각에서 무작위·(a)·(b) 기준선과 비교한다(§4-1/§4-2를 ⑤ 기준으로 확장, 천장(0.95+) 구간 별도).

새 봇 측정은 하지 않는다(기존 bot_v23 측정 재사용). 백엔드 venv가 아니라 analysis_venv로 돌린다:
  analysis_venv/bin/python backend/scripts/target_metric_eval.py
출력: backend/data/pv_sandbox/af_calibration/target_metric/target_metric_eval_result.json (+ .md 요약)
      (pv_sandbox 는 git 제외 샌드박스. 이 스크립트 자체만 저장소에 커밋한다.)
"""
import os

os.environ.setdefault("OMP_NUM_THREADS", "1")

import json
import random
import sys
import time
from pathlib import Path

import numpy as np
from scipy.stats import spearmanr

sys.path.insert(0, str(Path(__file__).resolve().parent))
import residual_model as rm  # noqa: E402
import residual_model_lib as lib  # noqa: E402

BACKEND = Path(__file__).resolve().parents[1]
CAL = rm.CAL
LEGACY_BATCH = BACKEND / "data/production/batch_1792056041502_cn5e4ny66.json"
OUT = CAL / "target_metric"
OUT.mkdir(parents=True, exist_ok=True)

REPS = 4  # 5겹 × REPS 반복 (sd 표기용)
K = lib.K
N_CAND = 20
DRAWS = 3000
METHODS = ["a_raw", "b_recal", "c_segmean", "d_e1"]

T0 = time.time()


def log(*a):
    print(f"[{time.time() - T0:6.0f}s]", *a, flush=True)


def lg(p, eps=0.005):
    p = np.clip(np.asarray(p, float), eps, 1 - eps)
    return np.log(p / (1 - p))


# ── 1) 데이터: bot_v23 410레벨 ∩ AF map_match=="same" ∩ 레거시 predicted_clear_rate 있음 ──────────
def load_base(bot_path=str(CAL / "bot_v23/bot_v2.3.json")):
    recs, X, _ = lib.load_data(bot_path)
    LM = {r["level"]: r for r in json.load(open(CAL / "level_metrics.json", encoding="utf-8"))["levels"]}
    leg = json.load(open(LEGACY_BATCH, encoding="utf-8"))
    legm = {lv["meta"]["level_number"]: lv["meta"].get("predicted_clear_rate") for lv in leg["levels"]}
    base, idx = [], []
    for i, r in enumerate(recs):
        m = LM.get(r["L"])
        if not m or m.get("map_match") != "same":
            continue
        if (m.get("first_try_ended") or 0) < 100:
            continue
        tgt = m.get("ft_clear_rate_any_help")
        pcr = legm.get(r["L"])
        if tgt is None or not pcr:  # pcr 0/None = 미계산 (문서 31 §2-0, L34 사례)
            continue
        idx.append(i)
        base.append({**r, "ft_any": tgt, "lb_af": m.get("unaided_clear_lower_bound"),
                     "help_rate": m.get("ft_help_rate"), "noend_rate": m.get("ft_noend_rate"),
                     "legacy_pred": float(pcr)})
    return base, X[idx]


def fit_logit_linear(x_prob, y_prob):
    x, y = lg(x_prob), lg(y_prob)
    sl, ic = np.polyfit(x, y, 1)
    if sl < 0:  # 단조성 보장: 역방향이면 상수(평균)로 후퇴
        return 0.0, float(y.mean())
    return float(sl), float(ic)


def apply_logit_linear(sl, ic, x_prob):
    return rm.expit(ic + sl * lg(x_prob))


def seg_means(train_base):
    segs = sorted({r["seg"] for r in train_base})
    m = {s: float(np.mean([r["ft_any"] for r in train_base if r["seg"] == s])) for s in segs}
    m["_all"] = float(np.mean([r["ft_any"] for r in train_base]))
    return m


# ── 2) K-fold OOF: (a)(b)(c)(d) 4가지 ──────────────────────────────────────────────────────────────
def run_eval(base, Xb, reps=REPS):
    n = len(base)
    y_true = np.array([r["ft_any"] for r in base])
    y_logit = rm.logit(np.clip(y_true, 0.005, 0.995))
    legacy = np.array([r["legacy_pred"] for r in base])
    oof = {m: np.zeros((reps, n)) for m in METHODS}
    for rep in range(reps):
        folds = lib.kfolds(base, rep)
        for k in range(K):
            tr, te = folds != k, folds == k
            tr_base = [base[i] for i in range(n) if tr[i]]
            oof["a_raw"][rep, te] = legacy[te]
            sl, ic = fit_logit_linear(legacy[tr], y_true[tr])
            oof["b_recal"][rep, te] = apply_logit_linear(sl, ic, legacy[te])
            sm = seg_means(tr_base)
            oof["c_segmean"][rep, te] = [sm.get(base[i]["seg"], sm["_all"]) for i in np.where(te)[0]]
            m = lib.Avg(lib.SkRidge(), lib.LGBM(mono=True)).fit(Xb[tr], y_logit[tr], lib.FEATS)
            oof["d_e1"][rep, te] = rm.expit(m.predict(Xb[te], lib.FEATS))
        log(f"rep {rep}/{reps} done")
    return y_true, oof


def metrics_for(y_true, pred, mask=None):
    if mask is not None:
        y_true, pred = y_true[mask], pred[mask]
    if len(y_true) < 3:
        return None
    err = pred - y_true
    rho = float(spearmanr(pred, y_true)[0])
    return {"n": int(len(y_true)), "mae": float(np.abs(err).mean()), "bias": float(err.mean()),
            "rho": rho, "hit05": float((np.abs(err) <= 0.05).mean()), "hit10": float((np.abs(err) <= 0.10).mean())}


def agg_reps(rep_metrics):
    ks = [k for k in rep_metrics[0] if k != "n"]
    out = {"n": rep_metrics[0]["n"]}
    for k in ks:
        vals = [rm_[k] for rm_ in rep_metrics]
        out[k] = round(float(np.mean(vals)), 4)
    out["sd"] = {k: round(float(np.std([rm_[k] for rm_ in rep_metrics])), 4) for k in ks}
    return out


def summarize(base, y_true, oof, reps):
    segs = sorted({r["seg"] for r in base})
    out = {"reps": reps, "overall": {}, "by_segment": {s: {} for s in segs}}
    for m in METHODS:
        reps_m = [metrics_for(y_true, oof[m][rep]) for rep in range(reps)]
        out["overall"][m] = agg_reps(reps_m)
        for s in segs:
            mask = np.array([r["seg"] == s for r in base])
            reps_s = [metrics_for(y_true, oof[m][rep], mask) for rep in range(reps)]
            if any(r is None for r in reps_s):
                continue
            out["by_segment"][s][m] = agg_reps(reps_s)
    return out


# ── 3) 501+ 참고 (봇 측정 없음 → (a)(c)만) ───────────────────────────────────────────────────────────
def ref_501(base_main):
    LM = {r["level"]: r for r in json.load(open(CAL / "level_metrics.json", encoding="utf-8"))["levels"]}
    leg = json.load(open(LEGACY_BATCH, encoding="utf-8"))
    legm = {lv["meta"]["level_number"]: lv["meta"].get("predicted_clear_rate") for lv in leg["levels"]}
    overall_mean = float(np.mean([r["ft_any"] for r in base_main]))
    rows = []
    for L in range(501, 1001):
        m = LM.get(L)
        if not m or m.get("map_match") != "same" or (m.get("first_try_ended") or 0) < 100:
            continue
        tgt = m.get("ft_clear_rate_any_help")
        pcr = legm.get(L)
        if tgt is None or not pcr:
            continue
        rows.append((float(pcr), tgt))
    if not rows:
        return {"n": 0}
    pred_a = np.array([r[0] for r in rows]); act = np.array([r[1] for r in rows])
    pred_c = np.full(len(rows), overall_mean)
    return {"n": len(rows), "a_raw": metrics_for(act, pred_a), "c_segmean(전체평균)": metrics_for(act, pred_c),
            "note": "참고용 — 이 구간은 봇 측정이 없어 (b)(d)는 계산하지 않음"}


# ── 4) 선별 재현: ⑤ 목표, 고정 확률 폭(±5/±10%p) + logit 폭(±0.7), 천장 구간 별도 ──────────────────
def replay_ftany(base, y_true, oof):
    predA, predB, predD = oof["a_raw"][0], oof["b_recal"][0], oof["d_e1"][0]
    rows = [{"L": base[i]["L"], "actual": float(y_true[i]), "predA": float(predA[i]),
             "predB": float(predB[i]), "predD": float(predD[i])} for i in range(len(base))]
    targets = {"t0.92_p25_일반": 0.92, "t0.963_p50_천장": 0.963, "t0.983_p75_천장": 0.983}
    widths = {"prob_pm05": ("prob", 0.05), "prob_pm10": ("prob", 0.10), "logit_pm0.7": ("logit", 0.7)}
    rules = ["random", "nearest_A", "nearest_B", "nearest_D", "oracle"]

    def band(t, kind, w):
        if kind == "prob":
            return t - w, t + w
        lo, hi = rm.logit(np.array([t]))[0] - w, rm.logit(np.array([t]))[0] + w
        return float(rm.expit(np.array([lo]))[0]), float(rm.expit(np.array([hi]))[0])

    def pick(cands, t, rule):
        if rule == "random":
            return random.choice(cands)
        if rule == "nearest_A":
            return min(cands, key=lambda r: abs(r["predA"] - t))
        if rule == "nearest_B":
            return min(cands, key=lambda r: abs(r["predB"] - t))
        if rule == "nearest_D":
            return min(cands, key=lambda r: abs(r["predD"] - t))
        if rule == "oracle":
            return min(cands, key=lambda r: abs(r["actual"] - t))

    random.seed(7)
    out = {}
    for tname, t in targets.items():
        for wname, (kind, w) in widths.items():
            a, b = band(t, kind, w)
            acc = {ru: {"hit": 0, "n": 0, "curse_sum": 0.0, "curse_n": 0} for ru in rules}
            for _ in range(DRAWS):
                cands = random.sample(rows, N_CAND)
                for ru in rules:
                    s = pick(cands, t, ru)
                    A = acc[ru]
                    A["n"] += 1
                    A["hit"] += (a <= s["actual"] <= b)
                    if ru == "nearest_D":
                        A["curse_sum"] += s["actual"] - s["predD"]; A["curse_n"] += 1
                    elif ru == "nearest_A":
                        A["curse_sum"] += s["actual"] - s["predA"]; A["curse_n"] += 1
            out[f"{tname}__{wname}"] = {ru: {"hit": round(acc[ru]["hit"] / acc[ru]["n"], 3),
                                              "actual_minus_pred": round(acc[ru]["curse_sum"] / acc[ru]["curse_n"], 3)
                                              if acc[ru]["curse_n"] else None}
                                        for ru in rules}
            log(f"replay {tname} {wname} band=[{a:.3f},{b:.3f}]")
    return targets, out


def main():
    log("load_base")
    base, Xb = load_base()
    log("n_base", len(base))
    y_true, oof = run_eval(base, Xb, REPS)
    cmp4 = summarize(base, y_true, oof, REPS)
    ref5 = ref_501(base)
    targets, sel = replay_ftany(base, y_true, oof)
    res = {"meta": {"n_base": len(base), "reps": REPS, "n_cand_replay": N_CAND, "draws": DRAWS,
                    "legacy_batch": str(LEGACY_BATCH), "bot": "bot_v23/bot_v2.3.json",
                    "target_metric": "ft_clear_rate_any_help (⑤ 첫 시도 전체, 도움 포함, no_end 제외)",
                    "warning": "기존 410레벨 재현 결과는 신규 생성 맵의 보장 성능이 아니다. "
                               "승자의 저주·분포 이탈로 신규 맵은 더 나쁠 수 있고, 라이브 검증으로만 확인된다."},
           "compare_4way": cmp4, "ref_501_1000": ref5, "selection_targets": targets, "selection_replay": sel}
    json.dump(res, open(OUT / "target_metric_eval_result.json", "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    log("done →", OUT / "target_metric_eval_result.json")


if __name__ == "__main__":
    main()
