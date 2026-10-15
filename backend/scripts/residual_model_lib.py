"""④ Residual calibration model — library version (sklearn · LightGBM · SHAP).

Re-uses the feature table / folds / metrics of residual_model.py (numpy-only direct implementation, doc 20)
and adds: (1) reproduction check of the direct ridge against sklearn, (2) library model comparison on the
same validation schemes, (3) LightGBM quantile 80% intervals (+ CQR), (4) SHAP explanations.

Runs ONLY in the analysis venv (repo root analysis_venv/, see requirements-analysis.txt):
  analysis_venv/bin/python backend/scripts/residual_model_lib.py all [--bot PATH] [--out DIR] [--reps N]
  sub-commands: repro | compare | interval | explain | all
Bot v2.3 retrain: same command with --bot <new rows.json> (rows {L, theta, games, wins, fail_reasons, ...}).
Outputs (default data/pv_sandbox/af_calibration/residual_model_lib/):
  results_<cmd>.json, repro_diff.csv, oof_lib.csv, interval_oof.csv, shap_global.csv, level_drivers.csv,
  examples.json, tables_<cmd>.md
No new bot simulation; single-threaded (other sessions are running bot jobs).
"""
import os

os.environ.setdefault("OMP_NUM_THREADS", "1")

import argparse
import csv
import json
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
import residual_model as rm  # noqa: E402  (numpy-only: build / folds / metrics / direct models)

import lightgbm as lgb  # noqa: E402
import shap  # noqa: E402
from sklearn.ensemble import GradientBoostingRegressor, HistGradientBoostingRegressor, RandomForestRegressor  # noqa: E402
from sklearn.linear_model import LinearRegression, LogisticRegression  # noqa: E402
from sklearn.linear_model import Ridge as SkRidgeEst  # noqa: E402

FEATS = rm.FEATS_ALL
BOT_RATE = ["lg055", "lg065", "lg085", "lg100"]
MONO = [1 if c in BOT_RATE else 0 for c in FEATS]  # bot success ↑ → prediction ↑
K = 5
ORDER = "SABCD"
GROUPS = {"봇 성공률": BOT_RATE, "봇 풀 실패비중": ["bot_grass_share"], "봇 폭탄 실패비중": ["bot_bomb_share"],
          "봇 실패 잔여": ["bot_left_rel"], "구간·레벨번호": rm.F_SEG,
          "구조(타일·층·종류)": ["tiles", "layers", "types", "tiles_per_type", "unlockTile", "random_layout"],
          "보스": ["is_boss"], "2차배치 맵": ["map2nd"], "첫 등장·노출": rm.F_NOV,
          "기믹 종류 수": ["n_gimmick_types"], "bomb": ["has_bomb", "n_bomb", "bomb_min", "bomb_sum"],
          "stack": ["has_stack", "n_stack", "stack_inner"], "craft": ["has_craft", "n_craft", "craft_inner"]}
for _g in ("ice", "chain", "grass", "curtain", "teleporter", "frog", "link", "unknown"):
    GROUPS[_g] = [f"has_{_g}", f"n_{_g}"]
if rm.EXTRA_BOT:
    GROUPS["봇 실패형태 추가"] = list(rm.EXTRA_BOT)
assert sorted(sum(GROUPS.values(), [])) == sorted(FEATS)


# ── models: fit(X, y_logit, cols) / predict(X, cols) → logit ───────────────────────────────────────
def inner_folds(n):
    return np.random.RandomState(7).permutation(n) % 5  # same inner split as residual_model.Ridge


class Std:
    def _std_fit(self, X, cols):
        self.idx = [cols.index(c) for c in self.feats]
        Xf = X[:, self.idx]
        self.mu, self.sd = Xf.mean(0), Xf.std(0)
        self.sd[self.sd < 1e-9] = 1
        return (Xf - self.mu) / self.sd

    def _std(self, X):
        return (X[:, self.idx] - self.mu) / self.sd


class SkRidge(Std):
    """sklearn Ridge on standardized features; α picked by the same inner 5-fold prob-MAE rule as direct ridge."""
    GRID = rm.Ridge.GRID

    def __init__(self, feats=FEATS, lam=None):
        self.feats, self.lam = feats, lam

    def fit(self, X, y, cols):
        Xs = self._std_fit(X, cols)
        lam = self.lam
        if lam is None:
            fold, err = inner_folds(len(y)), []
            for a in self.GRID:
                e = 0.0
                for k in range(5):
                    tr, te = fold != k, fold == k
                    m = SkRidgeEst(alpha=a).fit(Xs[tr], y[tr])
                    e += np.abs(rm.expit(m.predict(Xs[te])) - rm.expit(y[te])).sum()
                err.append(e)
            lam = self.GRID[int(np.argmin(err))]
        self.lam_used = lam
        self.m = SkRidgeEst(alpha=lam).fit(Xs, y)
        return self

    def predict(self, X, cols):
        return self.m.predict(self._std(X))

    def contrib(self, X, cols):  # exact linear SHAP (relative to train mean), logit scale
        return self._std(X) * self.m.coef_, float(self.m.intercept_)


class SkLogitMap:
    def __init__(self, col="lg065"):
        self.col = col

    def fit(self, X, y, cols):
        self.m = LinearRegression().fit(X[:, [cols.index(self.col)]], y)
        return self

    def predict(self, X, cols):
        return self.m.predict(X[:, [cols.index(self.col)]])


class FracLogistic(Std):
    """Logistic regression on the fractional target mid (each level = y1 w=mid + y0 w=1-mid); C by inner CV."""
    GRID = (0.003, 0.01, 0.03, 0.1, 0.3, 1.0)

    def __init__(self, feats=FEATS):
        self.feats = feats

    @staticmethod
    def _fit(Xs, p, C):
        n = len(p)
        X2 = np.vstack([Xs, Xs])
        y2 = np.r_[np.ones(n), np.zeros(n)]
        return LogisticRegression(C=C, max_iter=3000).fit(X2, y2, sample_weight=np.r_[p, 1 - p])

    def fit(self, X, y, cols):
        Xs, p = self._std_fit(X, cols), rm.expit(y)
        fold, err = inner_folds(len(y)), []
        for C in self.GRID:
            e = 0.0
            for k in range(5):
                tr, te = fold != k, fold == k
                e += np.abs(self._fit(Xs[tr], p[tr], C).predict_proba(Xs[te])[:, 1] - p[te]).sum()
            err.append(e)
        self.C = self.GRID[int(np.argmin(err))]
        self.m = self._fit(Xs, p, self.C)
        return self

    def predict(self, X, cols):
        return self.m.decision_function(self._std(X))


class SkEst:
    """Generic sklearn regressor on raw features (trees: no scaling)."""
    def __init__(self, make, feats=FEATS):
        self.make, self.feats = make, feats

    def fit(self, X, y, cols):
        self.idx = [cols.index(c) for c in self.feats]
        self.m = self.make().fit(X[:, self.idx], y)
        return self

    def predict(self, X, cols):
        return self.m.predict(X[:, self.idx])


def rf():
    return RandomForestRegressor(n_estimators=300, min_samples_leaf=5, max_features=0.33, n_jobs=1, random_state=0)


def hgb():
    return HistGradientBoostingRegressor(max_depth=3, learning_rate=0.04, max_iter=500, min_samples_leaf=10,
                                         l2_regularization=1.0, early_stopping=True, validation_fraction=0.2,
                                         n_iter_no_change=30, monotonic_cst=MONO, random_state=0)


def skgbm():  # same hyper-parameters as the direct GBM (column subsample is per split here, per tree there)
    return GradientBoostingRegressor(n_estimators=250, learning_rate=0.04, max_depth=3, min_samples_leaf=8,
                                     subsample=0.8, max_features=0.7, random_state=0)


class LGBM:
    """LightGBM, shallow + L2, rounds by early stopping on an inner 20% split, then refit on all train rows."""
    def __init__(self, feats=FEATS, mono=True, objective="regression", alpha=None, seed=0):
        self.feats, self.mono, self.objective, self.alpha, self.seed = feats, mono, objective, alpha, seed

    def params(self):
        p = dict(objective=self.objective, learning_rate=0.03, num_leaves=7, max_depth=3, min_child_samples=10,
                 subsample=0.8, subsample_freq=1, colsample_bytree=0.7, reg_lambda=1.0, n_jobs=1, verbose=-1,
                 random_state=self.seed)
        if self.alpha is not None:
            p["alpha"] = self.alpha
        if self.mono:
            p["monotone_constraints"] = [1 if c in BOT_RATE else 0 for c in self.feats]
        return p

    def fit(self, X, y, cols):
        self.idx = [cols.index(c) for c in self.feats]
        Xf = X[:, self.idx]
        va = np.random.RandomState(self.seed + 1).rand(len(y)) < 0.2
        m = lgb.LGBMRegressor(n_estimators=1500, **self.params())
        m.fit(Xf[~va], y[~va], eval_set=[(Xf[va], y[va])],
              callbacks=[lgb.early_stopping(50, verbose=False)])
        self.best_iter = max(20, int(m.best_iteration_ or 1500))
        self.m = lgb.LGBMRegressor(n_estimators=self.best_iter, **self.params()).fit(Xf, y)
        return self

    def predict(self, X, cols):
        return self.m.predict(X[:, self.idx])


class Avg:
    def __init__(self, *models):
        self.models = models

    def fit(self, X, y, cols):
        for m in self.models:
            m.fit(X, y, cols)
        return self

    def predict(self, X, cols):
        return np.mean([m.predict(X, cols) for m in self.models], axis=0)


def lib_models():
    return {
        "a: logit맵 θ0.65 (sklearn LinearRegression)": lambda: SkLogitMap(),
        "L1 Ridge (sklearn)": lambda: SkRidge(),
        "L2 로지스틱 (분수 목표)": lambda: FracLogistic(),
        "L3 RandomForest": lambda: SkEst(rf),
        "L4 HistGB (단조·조기종료)": lambda: SkEst(hgb),
        "L5 LightGBM 단조": lambda: LGBM(mono=True),
        "L5u LightGBM 무제약": lambda: LGBM(mono=False),
        "E1 Ridge+LGBM단조": lambda: Avg(SkRidge(), LGBM(mono=True)),
        "E2 Ridge+로지스틱+HistGB+LGBM": lambda: Avg(SkRidge(), FracLogistic(), SkEst(hgb), LGBM(mono=True)),
        "ref c+: 직접 ridge·GBM 평균": lambda: rm.Blend(rm.Ridge(FEATS), rm.GBM(FEATS)),
    }


# ── data / folds / metrics ─────────────────────────────────────────────────────────────────────────
def load_data(bot):
    recs_all = rm.build(Path(bot))
    rm.add_logits(recs_all)
    recs = [r for r in recs_all if not r["exclude"] and r["clean_n"] >= rm.MIN_N and r["has_bot"]]
    X, y = rm.matrix(recs, FEATS), rm.logit([r["mid"] for r in recs])
    assert not np.isnan(X).any()
    return recs, X, y


def kfolds(recs, rep):
    grp = np.array([r["maphash"] for r in recs])
    gperm = {g: i % K for i, g in enumerate(np.random.RandomState(100 + rep).permutation(sorted(set(grp))))}
    return np.array([gperm[g] for g in grp])


def grade_acc(pred, mid):
    gp = [ORDER.index(rm.grade(p)) for p in pred]
    gm = [ORDER.index(rm.grade(m)) for m in mid]
    d = np.abs(np.array(gp) - np.array(gm))
    return float((d == 0).mean()), float((d <= 1).mean())


def score(recs, p):
    m = rm.metrics(recs, p)
    m["grade_exact"], m["grade_pm1"] = grade_acc(p, [r["mid"] for r in recs])
    return m


def avg_metrics(ms):
    return rm.r3({k: float(np.mean([m[k] for m in ms])) for k in ms[0]})


def md(title, rows, cols):
    return rm.md_table(title, rows, cols)


def mrow(name, v, extra=()):
    return [name, v["strict"], v["tolAF"], v["mae"], f"{v['bias']:+.3f}", v["rho"],
            v.get("grade_exact", "-"), v.get("grade_pm1", "-"), *extra]


MCOLS = ["모델", "엄격", "tolAF", "MAE", "편향", "ρ", "등급일치", "등급±1"]


# ── 1) reproduction ────────────────────────────────────────────────────────────────────────────────
def cmd_repro(recs, X, y, out, reps):
    res, rows, diff_rows = {}, [], []
    t0 = time.time()
    for rep in range(reps):
        folds = kfolds(recs, rep)
        for k in range(K):
            te = folds == k
            d = rm.Ridge(FEATS).fit(X[~te], y[~te], FEATS)
            s = SkRidge().fit(X[~te], y[~te], FEATS)
            d30 = rm.Ridge(FEATS, lam=30).fit(X[~te], y[~te], FEATS)
            s30 = SkRidge(lam=30).fit(X[~te], y[~te], FEATS)
            pd_, ps = rm.expit(d.predict(X[te], FEATS)), rm.expit(s.predict(X[te], FEATS))
            p30d, p30s = rm.expit(d30.predict(X[te], FEATS)), rm.expit(s30.predict(X[te], FEATS))
            dl, sl = rm.LogitMap("lg065").fit(X[~te], y[~te], FEATS), SkLogitMap().fit(X[~te], y[~te], FEATS)
            pa = np.abs(rm.expit(dl.predict(X[te], FEATS)) - rm.expit(sl.predict(X[te], FEATS))).max()
            rows.append({"rep": rep, "fold": k, "lam_direct": d.lam_used, "lam_sklearn": s.lam_used,
                         "maxdiff_auto": float(np.abs(pd_ - ps).max()), "maxdiff_lam30": float(np.abs(p30d - p30s).max()),
                         "coef_maxdiff_lam30": float(np.abs(d30.w[1:] - s30.m.coef_).max()),
                         "maxdiff_logitmap": float(pa)})
    res["per_fold"] = rows
    res["lambda_agree"] = float(np.mean([r["lam_direct"] == r["lam_sklearn"] for r in rows]))
    res["max_pred_diff_auto"] = max(r["maxdiff_auto"] for r in rows)
    res["max_pred_diff_lam30"] = max(r["maxdiff_lam30"] for r in rows)
    res["max_coef_diff_lam30"] = max(r["coef_maxdiff_lam30"] for r in rows)
    res["max_pred_diff_logitmap"] = max(r["maxdiff_logitmap"] for r in rows)
    # full-data fit
    d, s = rm.Ridge(FEATS).fit(X, y, FEATS), SkRidge().fit(X, y, FEATS)
    res["full_lambda"] = [d.lam_used, s.lam_used]
    res["full_coef_maxdiff"] = float(np.abs(d.w[1:] - s.m.coef_).max())
    res["full_intercept_diff"] = float(abs(d.w[0] - s.m.intercept_))
    # metrics side by side (direct vs sklearn ridge, direct GBM vs sklearn GBM)
    side = {}
    for name, mk in {"direct ridge (residual_model.Ridge)": lambda: rm.Ridge(FEATS), "sklearn Ridge": lambda: SkRidge(),
                     "direct logit맵 θ0.65": lambda: rm.LogitMap("lg065"), "sklearn LinearRegression θ0.65": lambda: SkLogitMap(),
                     "sklearn GradientBoosting (직접 GBM 동일 설정)": lambda: SkEst(skgbm)}.items():
        side[name] = avg_metrics([score(recs, rm.expit(rm.oof_predict(mk, X, y, FEATS, kfolds(recs, r))))
                                  for r in range(reps)])
    prev = json.load(open(rm.CAL / "residual_model/results.json", encoding="utf-8"))["kfold"]
    side["(20 문서) direct GBM — results.json"] = prev["c: GBM 전체"]
    res["side_by_side"] = side
    res["runtime_sec"] = round(time.time() - t0, 1)
    with open(out / "repro_diff.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, list(rows[0]))
        w.writeheader()
        w.writerows(rows)
    s = [md("재현: 직접 ridge vs sklearn Ridge (같은 특징·같은 폴드)",
            [["λ 선택 일치율 (폴드)", res["lambda_agree"]], ["예측 최대차 (λ 자동, 확률)", f"{res['max_pred_diff_auto']:.2e}"],
             ["예측 최대차 (λ=30 고정)", f"{res['max_pred_diff_lam30']:.2e}"],
             ["계수 최대차 (λ=30, 표준화)", f"{res['max_coef_diff_lam30']:.2e}"],
             ["logit맵 예측 최대차", f"{res['max_pred_diff_logitmap']:.2e}"],
             ["전체 적합 λ (직접/sklearn)", res["full_lambda"]], ["전체 적합 계수 최대차", f"{res['full_coef_maxdiff']:.2e}"]],
            ["항목", "값"]),
         md(f"지표 비교 (K-fold {reps}반복)", [mrow(k, v) for k, v in side.items()], MCOLS)]
    (out / "tables_repro.md").write_text("\n".join(s), encoding="utf-8")
    return res


# ── 2) model comparison ────────────────────────────────────────────────────────────────────────────
def cmd_compare(recs, X, y, out, reps):
    t0 = time.time()
    models = lib_models()
    res = {"kfold": {}, "overfit": {}, "extrap": {}, "extrap_anchor10": {}, "combo_holdout": {}, "gimmick_holdout": {}}
    oof0 = {}
    for name, mk in models.items():
        ms, gaps, iters = [], [], []
        for rep in range(reps):
            folds = kfolds(recs, rep)
            p = np.full(len(y), np.nan)
            for k in range(K):
                te = folds == k
                m = mk().fit(X[~te], y[~te], FEATS)
                p[te] = m.predict(X[te], FEATS)
                tr_mae = np.abs(rm.expit(m.predict(X[~te], FEATS)) - rm.expit(y[~te])).mean()
                gaps.append(tr_mae)
                for sub in getattr(m, "models", (m,)):
                    if hasattr(sub, "best_iter"):
                        iters.append(sub.best_iter)
            ms.append(score(recs, rm.expit(p)))
            if rep == 0:
                oof0[name] = rm.expit(p)
        res["kfold"][name] = avg_metrics(ms)
        res["kfold"][name]["mae_sd_reps"] = round(float(np.std([m["mae"] for m in ms])), 4)
        res["overfit"][name] = {"train_mae": round(float(np.mean(gaps)), 3), "oof_mae": res["kfold"][name]["mae"],
                                "lgbm_rounds_median": int(np.median(iters)) if iters else None}
        print(f"[kfold] {name:34s} mae={res['kfold'][name]['mae']} tol={res['kfold'][name]['tolAF']} "
              f"t={time.time() - t0:.0f}s", flush=True)
    # extrapolation L32~300 → 301~500 (+ 10-level anchor shift, 30 draws)
    tr = np.array([r["L"] <= 300 for r in recs])
    te_idx = np.where(~tr)[0]
    test_recs = [recs[i] for i in te_idx]
    for name, mk in models.items():
        m = mk().fit(X[tr], y[tr], FEATS)
        pl = m.predict(X[te_idx], FEATS)
        res["extrap"][name] = rm.r3(score(test_recs, rm.expit(pl)))
        rng, ms = np.random.RandomState(3), []
        for _ in range(30):
            pick = rng.choice(len(te_idx), 10, replace=False)
            rest = np.setdiff1d(np.arange(len(te_idx)), pick)
            shift = (y[te_idx][pick] - pl[pick]).mean()
            ms.append(score([test_recs[i] for i in rest], rm.expit(pl[rest] + shift)))
        res["extrap_anchor10"][name] = avg_metrics(ms)
    print(f"[extrap] t={time.time() - t0:.0f}s", flush=True)
    # leave-one-combo-out
    combos = np.array([r["combo"] for r in recs])
    uc = sorted(set(combos))
    cfold = np.array([uc.index(c) for c in combos])
    for name, mk in models.items():
        res["combo_holdout"][name] = rm.r3(score(recs, rm.expit(rm.oof_predict(mk, X, y, FEATS, cfold))))
    print(f"[combo] t={time.time() - t0:.0f}s", flush=True)
    # leave-one-gimmick-out
    for g in ("bomb", "grass", "chain", "ice", "curtain", "teleporter", "frog", "unknown", "stack"):
        te = np.array([r["has_" + g] == 1 for r in recs])
        res["gimmick_holdout"][g] = {"n": int(te.sum())}
        for name, mk in models.items():
            m = mk().fit(X[~te], y[~te], FEATS)
            res["gimmick_holdout"][g][name] = rm.r3(score([r for r, t in zip(recs, te) if t],
                                                          rm.expit(m.predict(X[te], FEATS))))
    print(f"[gimmick-out] t={time.time() - t0:.0f}s", flush=True)
    # group tables (first-repeat OOF)
    show = ["a: logit맵 θ0.65 (sklearn LinearRegression)", "L1 Ridge (sklearn)", "L5 LightGBM 단조", "E1 Ridge+LGBM단조",
            "ref c+: 직접 ridge·GBM 평균"]
    res["by_gimmick"] = rm.group_table(recs, {k: oof0[k] for k in show}, rm.gim_keys)
    res["by_segment"] = rm.group_table(recs, {k: oof0[k] for k in show}, lambda r: [r["seg"]])
    res["runtime_sec"] = round(time.time() - t0, 1)
    with open(out / "oof_lib.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["L", "seg", "combo", "lb", "ub", "mid"] + list(oof0))
        for i, r in enumerate(recs):
            w.writerow([r["L"], r["seg"], r["combo"], r["lb"], r["ub"], round(r["mid"], 4)] +
                       [round(float(oof0[n][i]), 4) for n in oof0])
    s = [md(f"K-fold (5겹×{reps}반복, {len(recs)}레벨)",
            [mrow(k, v, (v["mae_sd_reps"], res["overfit"][k]["train_mae"], res["overfit"][k]["lgbm_rounds_median"] or "-"))
             for k, v in res["kfold"].items()], MCOLS + ["MAE sd", "학습 MAE", "LGBM 라운드"]),
         md("외삽 L32~300 → 301~500", [mrow(k, v) for k, v in res["extrap"].items()], MCOLS),
         md("외삽 + 앵커 10레벨 편향 보정 (30회 평균)", [mrow(k, v) for k, v in res["extrap_anchor10"].items()], MCOLS),
         md("기믹 조합 홀드아웃", [mrow(k, v) for k, v in res["combo_holdout"].items()], MCOLS)]
    names = list(models)
    s.append(md("기믹 단위 홀드아웃 — MAE/편향", [[g, d["n"]] + [f"{d[n]['mae']}/{d[n]['bias']:+.3f}" for n in names]
                                          for g, d in res["gimmick_holdout"].items()], ["기믹", "n"] + names))
    for key, title in (("by_segment", "구간별 K-fold OOF"), ("by_gimmick", "기믹별 K-fold OOF")):
        rr = [[g, d[show[0]]["n"]] + [f"{d[n]['mae']}/{d[n]['bias']:+.3f}" for n in show] for g, d in res[key].items()]
        s.append(md(title + " — MAE/편향", rr, ["그룹", "n"] + show))
    (out / "tables_compare.md").write_text("\n".join(s), encoding="utf-8")
    return res


# ── 3) 80% interval: LightGBM quantile 0.1/0.9 (+ CQR from inner CV) ──────────────────────────────
class QuantPair:
    def __init__(self, lo=0.1, hi=0.9):  # LightGBM forbids monotone_constraints with the quantile objective
        self.lo = LGBM(mono=False, objective="quantile", alpha=lo)
        self.hi = LGBM(mono=False, objective="quantile", alpha=hi)

    def fit(self, X, y, cols):
        self.lo.fit(X, y, cols)
        self.hi.fit(X, y, cols)
        return self

    def predict(self, X, cols):
        a, b = self.lo.predict(X, cols), self.hi.predict(X, cols)
        return np.minimum(a, b), np.maximum(a, b)


def cqr_width(X, y, tr_idx, seed, q=0.8):
    """Conformalized quantile regression: inner 5-fold score E=max(lo−y, y−hi) → its q-quantile."""
    inner = np.random.RandomState(seed).permutation(len(tr_idx)) % 5
    E = []
    for j in range(5):
        a, b = tr_idx[inner != j], tr_idx[inner == j]
        lo, hi = QuantPair().fit(X[a], y[a], FEATS).predict(X[b], FEATS)
        E.append(np.maximum(lo - y[b], y[b] - hi))
    E = np.concatenate(E)
    return float(np.quantile(E, min(1.0, q * (1 + 1 / len(E)))))


def interval_stats(recs, lo, hi, mask=None):
    mask = np.ones(len(recs), bool) if mask is None else mask
    mid = np.array([r["mid"] for r in recs])[mask]
    lb = np.array([r["lb"] for r in recs])[mask]
    ub = np.array([r["ub"] for r in recs])[mask]
    lo, hi = lo[mask], hi[mask]
    return {"n": int(mask.sum()), "cover_mid": round(float(((mid >= lo) & (mid <= hi)).mean()), 3),
            "overlap_LBUB": round(float(((lo <= ub) & (hi >= lb)).mean()), 3),
            "width": round(float((hi - lo).mean()), 3), "width_med": round(float(np.median(hi - lo)), 3)}


def cmd_interval(recs, X, y, out, reps):
    t0 = time.time()
    folds = kfolds(recs, 0)
    n = len(y)
    raw_lo, raw_hi, cq_lo, cq_hi, pt = (np.full(n, np.nan) for _ in range(5))
    widths = []
    for k in range(K):
        te = folds == k
        tr_idx = np.where(~te)[0]
        lo, hi = QuantPair().fit(X[~te], y[~te], FEATS).predict(X[te], FEATS)
        raw_lo[te], raw_hi[te] = lo, hi
        w = cqr_width(X, y, tr_idx, seed=k)
        widths.append(w)
        cq_lo[te], cq_hi[te] = lo - w, hi + w
        pt[te] = Avg(SkRidge(), LGBM(mono=True)).fit(X[~te], y[~te], FEATS).predict(X[te], FEATS)
        print(f"[interval] fold {k} cqr_w={w:+.3f} t={time.time() - t0:.0f}s", flush=True)
    P = {k: rm.expit(v) for k, v in dict(raw_lo=raw_lo, raw_hi=raw_hi, cq_lo=cq_lo, cq_hi=cq_hi, pt=pt).items()}
    nov = np.array([r["novelty"] > 0.5 or r["gimmick_first"] == 1 for r in recs])
    segs = {s: np.array([r["seg"] == s for r in recs]) for s in ("32-100", "101-300", "301-500")}
    res = {"cqr_width_logit_per_fold": [round(w, 3) for w in widths]}
    for tag, (lo, hi) in {"LGBM 분위수 0.1/0.9 (원본)": (P["raw_lo"], P["raw_hi"]),
                          "LGBM 분위수 + CQR 보정": (P["cq_lo"], P["cq_hi"])}.items():
        res[tag] = {"all": interval_stats(recs, lo, hi), "novel": interval_stats(recs, lo, hi, nov),
                    "familiar": interval_stats(recs, lo, hi, ~nov),
                    **{s: interval_stats(recs, lo, hi, m) for s, m in segs.items()}}
    prev = json.load(open(rm.CAL / "residual_model/results.json", encoding="utf-8"))["interval80"]
    res["(20 문서) 직접 conformal ±w"] = {"all": {"cover_mid": prev["coverage_mid"], "overlap_LBUB": prev["overlap_LBUB"],
                                               "width": prev["mean_width"]}}
    # point + grade (E1) with interval-derived grade range
    mid = np.array([r["mid"] for r in recs])
    ge, g1 = grade_acc(P["pt"], mid)
    gi = np.array([ORDER.index(rm.grade(m)) for m in mid])
    glo = np.array([ORDER.index(rm.grade(p)) for p in P["cq_hi"]])  # high clear → better (lower index)
    ghi = np.array([ORDER.index(rm.grade(p)) for p in P["cq_lo"]])
    res["grade"] = {"point_model": "E1 Ridge+LGBM단조", "exact": round(ge, 3), "within1": round(g1, 3),
                    "af_grade_in_interval_grade_range": round(float(((gi >= glo) & (gi <= ghi)).mean()), 3),
                    "point_in_cqr_interval": round(float(((P["pt"] >= P["cq_lo"]) & (P["pt"] <= P["cq_hi"])).mean()), 3)}
    res["runtime_sec"] = round(time.time() - t0, 1)
    with open(out / "interval_oof.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["L", "lb", "ub", "mid", "pred_E1", "q10", "q90", "cqr_lo", "cqr_hi"])
        for i, r in enumerate(recs):
            w.writerow([r["L"], r["lb"], r["ub"], round(r["mid"], 4)] +
                       [round(float(P[k][i]), 4) for k in ("pt", "raw_lo", "raw_hi", "cq_lo", "cq_hi")])
    rows = []
    for tag in ("LGBM 분위수 0.1/0.9 (원본)", "LGBM 분위수 + CQR 보정"):
        for part in ("all", "familiar", "novel", "32-100", "101-300", "301-500"):
            v = res[tag][part]
            rows.append([tag, part, v["n"], v["cover_mid"], v["overlap_LBUB"], v["width"], v["width_med"]])
    v = res["(20 문서) 직접 conformal ±w"]["all"]
    rows.append(["(20) 직접 conformal", "all", len(recs), v["cover_mid"], v["overlap_LBUB"], v["width"], "-"])
    s = [md("80% 예측 구간 (K-fold rep0 OOF)", rows, ["방식", "부분", "n", "mid 포함", "[LB,UB] 겹침", "평균 폭", "중앙 폭"]),
         md("등급 (E1 점예측, 컷 S≥.90 A≥.80 B≥.65 C≥.50)", [[k, v] for k, v in res["grade"].items()], ["항목", "값"])]
    (out / "tables_interval.md").write_text("\n".join(s), encoding="utf-8")
    return res


# ── 4) SHAP explanations + example outputs ─────────────────────────────────────────────────────────
def e1_contrib(model, X):
    """Logit-scale additive contributions of E1 = ½·ridge + ½·LGBM (linear SHAP + TreeSHAP)."""
    rid, gb = model.models
    lin, b_lin = rid.contrib(X, FEATS)
    ex = shap.TreeExplainer(gb.m)
    tr = ex.shap_values(X[:, gb.idx])
    base = 0.5 * b_lin + 0.5 * float(np.ravel(ex.expected_value)[0])
    return 0.5 * lin + 0.5 * tr, base, tr


def group_contrib(C):
    return {g: C[:, [FEATS.index(c) for c in cs]].sum(1) for g, cs in GROUPS.items()}


def confidence(r, train_counts):
    present = [g for g in rm.GIMMICKS if r["has_" + g]]
    rare = [g for g in present if train_counts.get(g, 0) < 10]
    if r["gimmick_first"] or r["novelty"] > 0.5 or rare:  # doc 20: novel MAE 0.148 vs familiar 0.074
        return "low"
    if r["has_grass"] or r["has_chain"]:  # bot does not reproduce these failure paths (doc 20 §7)
        return "medium"
    return "high"


def cmd_explain(recs, X, y, out, reps):
    t0 = time.time()
    # global (fit on all levels)
    full = Avg(SkRidge(), LGBM(mono=True)).fit(X, y, FEATS)
    C, base, tr = e1_contrib(full, X)
    gC = group_contrib(C)
    glob_feat = sorted(((f, float(np.abs(C[:, i]).mean()), float(np.abs(tr[:, i]).mean())) for i, f in enumerate(FEATS)),
                       key=lambda t: -t[1])
    glob_grp = sorted(((g, float(np.abs(v).mean())) for g, v in gC.items()), key=lambda t: -t[1])
    with open(out / "shap_global.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["feature", "mean_abs_shap_E1_logit", "mean_abs_shap_LGBM_logit"])
        for row in glob_feat:
            w.writerow([row[0], round(row[1], 4), round(row[2], 4)])
    # per-level drivers from OOF fold models (each level explained by a model that never saw it)
    folds = kfolds(recs, 0)
    n = len(y)
    pred, lo, hi = np.full(n, np.nan), np.full(n, np.nan), np.full(n, np.nan)
    G = {g: np.full(n, np.nan) for g in GROUPS}
    fold_counts = {}
    for k in range(K):
        te = folds == k
        m = Avg(SkRidge(), LGBM(mono=True)).fit(X[~te], y[~te], FEATS)
        Ck, _, _ = e1_contrib(m, X[te])
        for g, v in group_contrib(Ck).items():
            G[g][te] = v
        pred[te] = m.predict(X[te], FEATS)
        ql, qh = QuantPair().fit(X[~te], y[~te], FEATS).predict(X[te], FEATS)
        w = cqr_width(X, y, np.where(~te)[0], seed=k)
        lo[te], hi[te] = ql - w, qh + w
        fold_counts[k] = Counter(g for i in np.where(~te)[0] for g in rm.GIMMICKS if recs[i]["has_" + g])
        print(f"[explain] fold {k} t={time.time() - t0:.0f}s", flush=True)
    P, PL, PH = rm.expit(pred), rm.expit(lo), rm.expit(hi)
    rows, conf = [], []
    for i, r in enumerate(recs):
        drivers = sorted(((g, float(G[g][i])) for g in GROUPS), key=lambda t: -abs(t[1]))[:3]
        # %p effect of each driver ≈ p(full) − p(full − contribution)
        eff = [(g, round(float(P[i] - rm.expit(pred[i] - v)) * 100, 1)) for g, v in drivers]
        c = confidence(r, fold_counts[folds[i]])
        conf.append(c)
        rows.append({"L": r["L"], "combo": r["combo"], "af_lb": r["lb"], "af_ub": r["ub"], "pred": round(float(P[i]), 3),
                     "lo80": round(float(PL[i]), 3), "hi80": round(float(PH[i]), 3), "grade": rm.grade(P[i]),
                     "af_grade": rm.grade(r["mid"]), "confidence": c,
                     **{f"driver{j + 1}": f"{g} {v:+.1f}%p" for j, (g, v) in enumerate(eff)}})
    with open(out / "level_drivers.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, list(rows[0]))
        w.writeheader()
        w.writerows(rows)
    mid = np.array([r["mid"] for r in recs])
    err = np.abs(P - mid)
    conf = np.array(conf)
    tiers = {c: {"n": int((conf == c).sum()), "mae": round(float(err[conf == c].mean()), 3),
                 "cover80": round(float(((mid >= PL) & (mid <= PH))[conf == c].mean()), 3)}
             for c in ("high", "medium", "low") if (conf == c).any()}
    # 5 examples: plain/familiar, grass, chain, first-appearance, 301+ bomb
    def pick(cond):
        ix = [i for i, r in enumerate(recs) if cond(r)]
        return ix[len(ix) // 2] if ix else None
    cand = [pick(lambda r: r["combo"] == "none" and r["seg"] == "101-300"),
            pick(lambda r: r["has_grass"] and not r["gimmick_first"]),
            pick(lambda r: r["has_chain"] and r["L"] >= 301),
            pick(lambda r: r["gimmick_first"] == 1),
            pick(lambda r: r["has_bomb"] and r["L"] >= 401 and not r["has_grass"] and not r["has_chain"])]
    examples = []
    for i in [c for c in cand if c is not None]:
        r = rows[i]
        examples.append({"L": r["L"], "combo": r["combo"], "expected_clear": r["pred"], "range80": [r["lo80"], r["hi80"]],
                         "grade": r["grade"], "grade_range": [rm.grade(r["hi80"]), rm.grade(r["lo80"])],
                         "confidence": r["confidence"], "drivers": [r["driver1"], r["driver2"], r["driver3"]],
                         "actual_af": [r["af_lb"], r["af_ub"]], "actual_grade": r["af_grade"]})
    json.dump(examples, open(out / "examples.json", "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    res = {"global_group": [[g, round(v, 4)] for g, v in glob_grp], "global_feature_top15": [
        [f, round(a, 4), round(b, 4)] for f, a, b in glob_feat[:15]], "base_logit": round(base, 3),
        "confidence_tiers": tiers, "examples": examples, "runtime_sec": round(time.time() - t0, 1)}
    s = [md("전역 중요도 — 묶음별 mean|SHAP| (E1, logit)", [[g, round(v, 4)] for g, v in glob_grp], ["묶음", "mean|SHAP|"]),
         md("전역 중요도 — 특징 상위 15", [[f, round(a, 4), round(b, 4)] for f, a, b in glob_feat[:15]],
            ["특징", "E1", "LGBM 단독"]),
         md("신뢰도 등급별 OOF 오차", [[c, v["n"], v["mae"], v["cover80"]] for c, v in tiers.items()],
            ["신뢰도", "n", "MAE", "80%구간 포함"])]
    (out / "tables_explain.md").write_text("\n".join(s), encoding="utf-8")
    return res


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["repro", "compare", "interval", "explain", "all"])
    ap.add_argument("--bot", default=str(rm.CAL / "bot_v21/bot_v2.1.json"))
    ap.add_argument("--out", default=str(rm.CAL / "residual_model_lib"))
    ap.add_argument("--reps", type=int, default=4, help="K-fold repeats (doc 20 used 4)")
    a = ap.parse_args()
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    recs, X, y = load_data(a.bot)
    meta = {"bot_file": a.bot, "levels": len(recs), "n_features": len(FEATS),
            "versions": {"sklearn": __import__("sklearn").__version__, "lightgbm": lgb.__version__,
                         "shap": shap.__version__, "numpy": np.__version__}}
    cmds = ["repro", "compare", "interval", "explain"] if a.cmd == "all" else [a.cmd]
    for c in cmds:
        t0 = time.time()
        res = {"meta": meta, **globals()["cmd_" + c](recs, X, y, out, a.reps)}
        json.dump(res, open(out / f"results_{c}.json", "w", encoding="utf-8"), ensure_ascii=False, indent=1,
                  default=lambda o: o.item() if hasattr(o, "item") else str(o))
        print(f"[{c}] done {time.time() - t0:.0f}s → {out}", flush=True)


if __name__ == "__main__":
    main()
