"""80% range / target-band probability / pass verdict — consistency check and range-model candidates (doc 36 §8–).

The point model is the active one (cr-ftany-v24r-20261016, 379 levels) and is never changed here; only the range
part is examined. active.json and the active model directory are never written. No bot measurement.

  diag     current model: why the upper quantile head is constant (label clip, gradient, trees), the 0.99→1.0 display
           handling, train / CV / serving path agreement, calibration of P(in target band) on the 379 OOF
  eval     pre-registered range candidates R1 / R2 vs R0 (doc 36 §9, committed before running) → range/compare.json
  export   candidate model directories (point heads copied byte-for-byte from the active model) — not active
  reeval   saved pilot candidates (gen_pilot 20261016 / _p2 / _p3) re-judged with R0 / R1 / R2 (regression check)

Run from the worktree root with the analysis venv; data from CR_DATA_ROOT (main checkout sandbox), outputs to
<CAL>/range/.
"""
import os

os.environ.setdefault("OMP_NUM_THREADS", "1")

import argparse
import json
import math
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
BACKEND = HERE.parent
sys.path.insert(0, str(BACKEND))
sys.path.insert(0, str(HERE))
import clear_rate_cand_a1a2 as CA  # noqa: E402

CAL = CA.CAL
OUT = CAL / "range"
T0 = time.time()
TARGETS = (0.80, 0.85, 0.88, 0.90, 0.92, 0.95)
HALF = 0.7       # select.PROPOSED half_width_logit (unchanged)
Z90 = 1.2815515655446004
P_BINS = (0.0, 0.1, 0.3, 0.5, 0.7, 0.9, 1.0001)


def log(*a):
    print(f"[{time.time() - T0:6.0f}s]", *a, flush=True)


def np_():
    import numpy as np
    return np


def lg(p):
    p = min(max(p, 1e-6), 1 - 1e-6)
    return math.log(p / (1 - p))


def band_of(t):
    return 1 / (1 + math.exp(-(lg(t) - HALF))), 1 / (1 + math.exp(-(lg(t) + HALF)))


def clear_rate_pkg():
    """Import app.core.clear_rate (the served code) without app/__init__ and app/core/__init__ (they import the web
    stack, absent from the analysis venv). The clear_rate package itself only needs the stdlib at import time."""
    import types
    if "app.core.clear_rate" not in sys.modules:
        for name, path in (("app", BACKEND / "app"), ("app.core", BACKEND / "app/core")):
            if name not in sys.modules:
                m = types.ModuleType(name)
                m.__path__ = [str(path)]
                sys.modules[name] = m
    import app.core.clear_rate as cr
    return cr


def p_in_band(expected, rng, band):
    """select.p_in_band — the served function itself."""
    clear_rate_pkg()
    from app.core.clear_rate.select import p_in_band as f
    return f(expected, rng, band)


# ── shared data / OOF ─────────────────────────────────────────────────────────────────────────────
class Base:
    def __init__(self):
        TR = CA.tr()
        rows, X, prep, af, bot_rows, LM_doc, expo, _ = TR.build_dataset()
        self.TR, self.rows, self.X = TR, rows, X
        self.Y = TR.ytarget(rows, "ft_any")
        np = np_()
        self.y = np.array([r["ft_any"] for r in rows])
        self.L = np.array([r["L"] for r in rows])
        self.n = len(rows)
        self.groups = np.array([r["maphash"] for r in rows])
        self.prep, self.af, self.bot_rows, self.expo = prep, af, bot_rows, expo

    def folds(self, rep):
        return self.TR.kfolds(self.rows, rep)


def oof_point(B, rep):
    """Active point model, map-group fold `rep` → OOF logit (same as train_clear_rate_model.evaluate)."""
    np = np_()
    z = np.zeros(B.n)
    f = B.folds(rep)
    for k in range(B.TR.K):
        tr, te = f != k, f == k
        z[te] = B.TR.point_model().fit(B.X[tr], B.Y[tr], B.TR.FEATS).predict(B.X[te], B.TR.FEATS)
    return z


def r0_range(B, rep):
    """Current CQR (train_clear_rate_model.evaluate procedure) for fold `rep` → raw logit lo/hi."""
    np, TR = np_(), B.TR
    f = B.folds(rep)
    lo_, hi_ = np.zeros(B.n), np.zeros(B.n)
    info = []
    for k in range(TR.K):
        te = f == k
        trn = np.where(~te)[0]
        qlo, qhi = TR.quant_pair(B.X[~te], B.Y[~te])
        a, b = TR.qpredict(qlo, qhi, B.X[te])
        w = TR.cqr_width(B.X, B.Y, trn, seed=k)
        lo_[te], hi_[te] = a - w, b + w
        info.append({"fold": k, "w": round(w, 4), "q_hi_trees_with_split": sum(t[0] == "node" for t in qhi.trees),
                     "q_hi_out_min": round(float(qhi.predict(B.X[te], TR.FEATS).min()), 4)})
    return lo_, hi_, info


def to_prob(lo, hi):
    MD = CA.tr().MD
    pr = [MD.range_to_prob(a, b) for a, b in zip(lo, hi)]
    np = np_()
    return np.array([v[0] for v in pr]), np.array([v[1] for v in pr])


def calib(y, pred, plo, phi, targets=TARGETS):
    """P(in band) from (pred, displayed range) vs observed actual in band — per target and pooled."""
    np = np_()
    out = {}
    allP, allH = [], []
    for t in targets:
        b = band_of(t)
        P = np.array([p_in_band(float(p), (float(a), float(c)), b) for p, a, c in zip(pred, plo, phi)])
        H = ((y >= b[0]) & (y <= b[1])).astype(float)
        out[f"t{t:.2f}"] = calib_table(P, H)
        allP.append(P)
        allH.append(H)
    out["pooled"] = calib_table(np.concatenate(allP), np.concatenate(allH))
    return out


def calib_table(P, H):
    np = np_()
    rows = []
    ece = 0.0
    for lo, hi in zip(P_BINS[:-1], P_BINS[1:]):
        m = (P >= lo) & (P < hi)
        if m.any():
            rows.append({"P_bin": [lo, min(hi, 1.0)], "n": int(m.sum()), "mean_P": round(float(P[m].mean()), 3),
                         "hit_rate": round(float(H[m].mean()), 3)})
            ece += m.mean() * abs(P[m].mean() - H[m].mean())
    ge = P >= 0.5
    return {"n": int(len(P)), "brier": round(float(((P - H) ** 2).mean()), 4), "ece": round(float(ece), 4),
            "mean_P": round(float(P.mean()), 3), "hit_rate": round(float(H.mean()), 3),
            "P_ge_0.5": {"n": int(ge.sum()), "mean_P": round(float(P[ge].mean()), 3) if ge.any() else None,
                         "hit_rate": round(float(H[ge].mean()), 3) if ge.any() else None},
            "bins": rows}


def cov_stats(y, plo, phi, mask=None):
    np = np_()
    m = np.ones(len(y), bool) if mask is None else mask
    if not m.any():
        return {"n": 0}
    return {"n": int(m.sum()), "coverage": round(float(((y[m] >= plo[m]) & (y[m] <= phi[m])).mean()), 3),
            "width_mean": round(float((phi[m] - plo[m]).mean()), 4), "width_median": round(float(np.median(phi[m] - plo[m])), 4),
            "upper_is_1": round(float((phi[m] >= 1.0).mean()), 3), "lower_is_0": round(float((plo[m] <= 0.0).mean()), 3),
            "interval_score": round(float(interval_score(y[m], plo[m], phi[m]).mean()), 4)}


def interval_score(y, lo, hi, alpha=0.2):
    """Winkler / interval score for a central (1−α) interval — lower is better; penalises width and misses."""
    np = np_()
    return (hi - lo) + (2 / alpha) * np.maximum(0, lo - y) + (2 / alpha) * np.maximum(0, y - hi)


ACT = (("lt0.85", -9, 0.85), ("0.85-0.92", 0.85, 0.92), ("0.92-0.96", 0.92, 0.96), ("ge0.96", 0.96, 9))
PRED = ((0.0, 0.88), (0.88, 0.92), (0.92, 0.95), (0.95, 0.97), (0.97, 1.01))


def cov_report(y, pm, plo, phi):
    out = {"all": cov_stats(y, plo, phi)}
    for nm, lo, hi in ACT:
        out["act_" + nm] = cov_stats(y, plo, phi, (y >= lo) & (y < hi))
    for lo, hi in PRED:
        out[f"pred_{lo:.2f}-{min(hi, 1):.2f}"] = cov_stats(y, plo, phi, (pm >= lo) & (pm < hi))
    return out


# ── diag ──────────────────────────────────────────────────────────────────────────────────────────
def cmd_diag(a):
    np = np_()
    B = Base()
    TR, rm = B.TR, B.TR.rm
    clip = float(rm.logit(np.array([0.99]))[0])
    res = {"labels": {}, "full_fit": {}, "mechanism": {}, "cv": {}, "paths": {}, "p_rule": {}}
    # 1) labels
    res["labels"] = {"n": B.n, "share_ft_any_ge_0.99": round(float((B.y >= 0.99).mean()), 4),
                     "share_ft_any_gt_0.995": round(float((B.y > 0.995).mean()), 4),
                     "share_target_logit_at_clip": round(float((B.Y >= clip - 1e-9).mean()), 4),
                     "clip_logit": round(clip, 4), "q0.9_of_target_logit": round(float(np.quantile(B.Y, 0.9)), 4),
                     "q0.1_of_target_logit": round(float(np.quantile(B.Y, 0.1)), 4)}
    log("labels", res["labels"])
    # 2) full fit (as exported) — tree structure
    qlo, qhi = TR.quant_pair(B.X, B.Y)
    for nm, q in (("q_lo", qlo), ("q_hi", qhi)):
        out = q.predict(B.X, TR.FEATS)
        res["full_fit"][nm] = {"base": round(q.base, 4), "trees": len(q.trees),
                               "trees_with_split": sum(t[0] == "node" for t in q.trees),
                               "leaf_values_nonzero": sum(1 for t in q.trees if t[0] == "leaf" and abs(t[1]) > 0),
                               "out_min": round(float(out.min()), 4), "out_max": round(float(out.max()), 4)}
    man = CA.load(TR.MODELS / TR.DEFAULT_VERSION / "model.json")
    jh = man["heads"]["ft_any"]["q_hi"]
    res["full_fit"]["exported_q_hi"] = {"base": jh["base"], "trees_with_split": sum(t[0] == "node" for t in jh["trees"]),
                                        "leaf_values": sorted({t[1] for t in jh["trees"] if t[0] == "leaf"})[:5],
                                        "cqr_w": man["heads"]["ft_any"]["cqr_w"]}
    log("full fit", res["full_fit"])
    # 3) mechanism: first boosting step of the q_hi head on the full data
    r = B.Y - np.quantile(B.Y, 0.9)
    g = np.where(r > 0, 0.9, 0.9 - 1.0)
    res["mechanism"] = {"init_F0": round(float(np.quantile(B.Y, 0.9)), 4), "share_residual_gt_0": round(float((r > 0).mean()), 4),
                        "share_residual_eq_0": round(float((r == 0).mean()), 4),
                        "distinct_gradient_values": sorted({round(float(v), 3) for v in g}),
                        "note": "all gradients equal → every split has zero gain → stump leaves = 0.9-quantile of the "
                                "subsample residuals = 0 whenever ≥10 % of the subsample sits at the clip"}
    # what the 0.9 quantile would be with the looser 0.995 clip alone (diagnostic only — not used by any model)
    yc = np.clip(B.y, 0.005, 0.995)
    res["mechanism"]["q0.9_if_clip_0.995"] = round(float(np.quantile(np.log(yc / (1 - yc)), 0.9)), 4)
    res["mechanism"]["ytarget_effective_clip"] = "ytarget clips to [0.005, 0.995] then residual_model.logit clips to [0.01, 0.99]"
    # 4) CV: OOF point + R0 range, 4 reps; P calibration; served-structure variant (upper forced to 1)
    reps = []
    for rep in range(TR.REPS):
        z = oof_point(B, rep)
        lo_, hi_, info = r0_range(B, rep)
        reps.append((z, lo_, hi_, info))
        log(f"rep {rep} done", info)
    pm = rm.expit(np.mean([x[0] for x in reps], 0))
    res["cv"]["fold_info"] = [x[3] for x in reps]
    z0, lo0, hi0, _ = reps[0]
    p0 = rm.expit(z0)
    plo, phi = to_prob(lo0, hi0)
    rawlo, rawhi = rm.expit(lo0), rm.expit(hi0)
    res["cv"]["coverage_rep0_post_display"] = cov_report(B.y, p0, plo, phi)
    res["cv"]["coverage_rep0_pre_display"] = cov_report(B.y, p0, rawlo, rawhi)
    res["p_rule"]["oof_rep0"] = calib(B.y, p0, plo, phi)
    res["p_rule"]["oof_rep0_upper_forced_1"] = calib(B.y, p0, plo, np.ones(B.n))
    allc = [calib(B.y, rm.expit(x[0]), *to_prob(x[1], x[2]), targets=(0.85, 0.90)) for x in reps]
    res["p_rule"]["oof_4rep_t85_t90"] = [{k: {"brier": c[k]["brier"], "ece": c[k]["ece"], "P_ge_0.5": c[k]["P_ge_0.5"]}
                                         for k in ("t0.85", "t0.90")} for c in allc]
    # served path on the training maps (what doc 33 §15 used): full-model in-sample predictions
    mdl = clear_rate_pkg().load_model(TR.DEFAULT_VERSION)
    sp, slo, shi = [], [], []
    for r_ in B.rows:
        f = dict(zip(TR.FEATS, r_["x"]))
        sp.append(mdl.predict("ft_any", f))
        a_, b_ = mdl.range80("ft_any", f)
        slo.append(a_)
        shi.append(b_)
    sp, slo, shi = np.array(sp), np.array(slo), np.array(shi)
    res["paths"] = {
        "served_in_sample_vs_oof": {"served_mae_in_sample": round(float(np.abs(sp - B.y).mean()), 4),
                                    "oof_rep0_mae": round(float(np.abs(p0 - B.y).mean()), 4),
                                    "served_upper_is_1": round(float((shi >= 1).mean()), 3),
                                    "oof_rep0_upper_is_1": round(float((phi >= 1).mean()), 3),
                                    "served_coverage_in_sample": round(float(((B.y >= slo) & (B.y <= shi)).mean()), 3)},
        "note": "doc 33 §15 judged the training maps with the served full model (in-sample point + full-fit range: "
                "q_hi constant → upper always 1) and the manifest reliability table; lowband addenda used fold OOF "
                "points and fold CQR ranges (2 of 5 rep-0 folds have a non-constant q_hi)"}
    res["p_rule"]["served_in_sample"] = calib(B.y, sp, slo, shi, targets=(0.85, 0.90))
    # where the 2 OOF passes of the lowband addenda sit
    f0 = B.folds(0)
    res["paths"]["addenda_B0_pass_levels_fold"] = {int(L): int(f0[i]) for i, L in enumerate(B.L) if L in (313, 346)}
    # 5) two-piece normal: tail masses implied by the rule (analytic check on rep-0 rows)
    tails = []
    for p, a_, c_ in zip(p0, plo, phi):
        mu = lg(p)
        s_lo = (mu - lg(a_)) / Z90 if 0 < a_ < p else None
        s_hi = (lg(c_) - mu) / Z90 if p < c_ < 1 else None
        s_lo = s_lo or s_hi or 1e-6
        s_hi = s_hi or s_lo
        w = s_lo / (s_lo + s_hi)
        tails.append((0.2 * w, 0.2 * (1 - w), c_ >= 1.0, a_ <= 0 or a_ >= p))
    tl = np.array([t[0] for t in tails])
    res["p_rule"]["two_piece"] = {"lower_tail_mass_mean": round(float(tl.mean()), 4),
                                  "lower_tail_mass_min_max": [round(float(tl.min()), 4), round(float(tl.max()), 4)],
                                  "rows_upper_censored_symmetric": int(sum(t[2] for t in tails)),
                                  "rows_lower_not_below_pred": int(sum(t[3] for t in tails)),
                                  "note": "mass inside the range is 0.8 by construction; tails are 0.2·w / 0.2·(1−w), "
                                          "equal (0.1/0.1) only when w = 0.5"}
    OUT.mkdir(parents=True, exist_ok=True)
    CA.save(OUT / "diag.json", res)
    log("saved", OUT / "diag.json")


# ── range candidates (doc 36 §9, pre-registered in c11ce5e) ──────────────────────────────────────
def group_folds(groups, seed):
    np = np_()
    ug = sorted(set(groups))
    perm = np.random.RandomState(seed).permutation(len(ug))
    gf = {g: int(perm[i]) % 5 for i, g in enumerate(ug)}
    return np.array([gf[g] for g in groups])


def point_oof_inner(B, idx, seed):
    """Point-model OOF logit for the rows idx, from a map-group 5-fold inside idx."""
    np, TR = np_(), B.TR
    f = group_folds(B.groups[idx], seed)
    z = np.zeros(len(idx))
    for j in range(5):
        a, b = idx[f != j], idx[f == j]
        z[f == j] = TR.point_model().fit(B.X[a], B.Y[a], TR.FEATS).predict(B.X[b], TR.FEATS)
    return z


def make_qgbm_on_point(alpha):
    TR = CA.tr()

    class QOnPoint(TR.QGBM):
        """train_clear_rate_model.QGBM with the start F0 = z (point OOF logit) + Q_α(y − z) instead of Q_α(y)."""

        def fit_on(self, X, y, z, cols):
            np = np_()
            self.idx = [cols.index(c) for c in self.feats]
            Xf = X[:, self.idx]
            rng = np.random.RandomState(self.seed)
            self.base = float(np.quantile(y - z, self.alpha))
            self.gain = np.zeros(len(self.idx))
            F = z + self.base
            self.trees = []
            p = len(self.idx)
            for _ in range(self.n_est):
                rows = rng.rand(len(y)) < self.subsample
                cs = sorted(rng.choice(p, max(1, int(p * self.colsample)), replace=False))
                r = y - F
                g = np.where(r > 0, self.alpha, self.alpha - 1.0)
                t = self._relabel(self._grow(Xf[rows], g[rows], 0, cs), Xf[rows], r[rows])
                self.trees.append(t)
                F += self.lr * self._pred_tree(t, Xf)
            return self

        def predict_on(self, X, z, cols):
            return z + self.predict(X, cols)  # predict() = base + Σ trees

    return QOnPoint(TR.FEATS, alpha)


def r1_fit(B, idx, seed):
    """R1 heads on rows idx: point OOF inside idx (group 5-fold RandomState(seed)) → quantile GBMs started from it."""
    TR = B.TR
    z = point_oof_inner(B, idx, seed)
    lo = make_qgbm_on_point(0.1).fit_on(B.X[idx], B.Y[idx], z, TR.FEATS)
    hi = make_qgbm_on_point(0.9).fit_on(B.X[idx], B.Y[idx], z, TR.FEATS)
    return lo, hi


def r1_raw(lo, hi, X, z):
    np, F = np_(), CA.tr().FEATS
    a, b = lo.predict_on(X, z, F), hi.predict_on(X, z, F)
    return np.minimum(a, b), np.maximum(a, b)


def r1_width(B, idx, seed):
    """CQR width exactly as train_clear_rate_model.cqr_width (same inner splits), with R1 heads."""
    np, TR = np_(), B.TR
    E = []
    for s in range(TR.CQR_SEEDS):
        inner = np.random.RandomState(seed * 100 + s).permutation(len(idx)) % 5
        for j in range(5):
            a, b = idx[inner != j], idx[inner == j]
            lo, hi = r1_fit(B, a, 700 + 10 * seed + s)
            zb = TR.point_model().fit(B.X[a], B.Y[a], TR.FEATS).predict(B.X[b], TR.FEATS)
            l_, h_ = r1_raw(lo, hi, B.X[b], zb)
            E.append(np.maximum(l_ - B.Y[b], B.Y[b] - h_))
    E = np.concatenate(E)
    return float(np.quantile(E, min(1.0, 0.8 * (1 + 1 / len(E)))))


def r2_resid(B, idx, seed):
    """Pooled inner OOF residuals e = y − z (same inner splits as cqr_width: 3 × 5-fold)."""
    np, TR = np_(), B.TR
    E = []
    for s in range(TR.CQR_SEEDS):
        inner = np.random.RandomState(seed * 100 + s).permutation(len(idx)) % 5
        for j in range(5):
            a, b = idx[inner != j], idx[inner == j]
            zb = TR.point_model().fit(B.X[a], B.Y[a], TR.FEATS).predict(B.X[b], TR.FEATS)
            E.append(B.Y[b] - zb)
    return np.concatenate(E)


def r2_offsets(e):
    np = np_()
    q = min(1.0, 0.9 * (1 + 1 / len(e)))
    return float(np.quantile(-e, q)), float(np.quantile(e, q))


def fit_ranges(B, trn, te, k, z_te):
    """Raw logit (lo, hi) on te for R0 / R1 / R2 trained on trn (outer seed k). + residual pool for D1."""
    np, TR = np_(), B.TR
    out = {}
    qlo, qhi = TR.quant_pair(B.X[trn], B.Y[trn])
    a, b = TR.qpredict(qlo, qhi, B.X[te])
    w = TR.cqr_width(B.X, B.Y, trn, seed=k)
    out["R0"] = (a - w, b + w, {"w": w, "q_hi_split_trees": sum(t[0] == "node" for t in qhi.trees)})
    lo, hi = r1_fit(B, trn, 700 + k)
    a, b = r1_raw(lo, hi, B.X[te], z_te)
    w1 = r1_width(B, trn, k)
    out["R1"] = (a - w1, b + w1, {"w": w1, "q_hi_split_trees": sum(t[0] == "node" for t in hi.trees),
                                  "q_lo_base": lo.base, "q_hi_base": hi.base})
    e = r2_resid(B, trn, k)
    dlo, dhi = r2_offsets(e)
    out["R2"] = (z_te - dlo, z_te + dhi, {"d_lo": dlo, "d_hi": dhi})
    return out, e


def p_emp(z, e, band):
    """D1 (diagnostic only): share of pooled inner residuals that put z + e inside the band (logit)."""
    np = np_()
    lo, hi = lg(band[0]), lg(band[1])
    v = z + e
    return float(((v >= lo) & (v <= hi)).mean())


CANDS = ("R0", "R1", "R2")


def cmd_eval(a):
    np = np_()
    B = Base()
    TR, rm = B.TR, B.TR.rm
    res = {"prereg_commit": "c11ce5e", "reps": {}, "summary": {}}
    per = {c: {"plo": [], "phi": [], "rlo": [], "rhi": [], "p": []} for c in CANDS}
    d1 = {"P": [], "H": []}
    zs = []
    for rep in range(TR.REPS):
        f = B.folds(rep)
        z = np.zeros(B.n)
        raw = {c: (np.zeros(B.n), np.zeros(B.n)) for c in CANDS}
        info = {c: [] for c in CANDS}
        for k in range(TR.K):
            trn, te = np.where(f != k)[0], np.where(f == k)[0]
            z[te] = TR.point_model().fit(B.X[trn], B.Y[trn], TR.FEATS).predict(B.X[te], TR.FEATS)
            rng_, e = fit_ranges(B, trn, te, k, z[te])
            for c in CANDS:
                raw[c][0][te], raw[c][1][te] = rng_[c][0], rng_[c][1]
                info[c].append({kk: (round(v, 4) if isinstance(v, float) else v) for kk, v in rng_[c][2].items()})
            for t in TARGETS:
                b = band_of(t)
                d1["P"] += [p_emp(zz, e, b) for zz in z[te]]
                d1["H"] += list(((B.y[te] >= b[0]) & (B.y[te] <= b[1])).astype(float))
            log(f"rep {rep} fold {k}: " + " ".join(f"{c} {info[c][-1]}" for c in CANDS))
        zs.append(z)
        p = rm.expit(z)
        for c in CANDS:
            plo, phi = to_prob(*raw[c])
            per[c]["plo"].append(plo)
            per[c]["phi"].append(phi)
            per[c]["rlo"].append(rm.expit(raw[c][0]))
            per[c]["rhi"].append(rm.expit(raw[c][1]))
            per[c]["p"].append(p)
        res["reps"][rep] = {"point_mae": round(float(np.abs(p - B.y).mean()), 5), "fold_info": info}
    # point model must be the active model's OOF
    mae = float(np.mean([np.abs(rm.expit(z) - B.y).mean() for z in zs]))
    man = CA.load(TR.MODELS / TR.DEFAULT_VERSION / "manifest.json")["kfold"]
    assert abs(mae - man["ft_any"]["mae"]) < 1e-4, (mae, man["ft_any"]["mae"])
    res["point_mae_rep_mean"] = mae
    pm = np.mean([rm.expit(z) for z in zs], 0)  # train_clear_rate_model.evaluate: mean of probabilities
    IS = {}
    for c in CANDS:
        s = {"post": {}, "pre": {}, "calib": {}}
        for nm, lo, hi in [("all", -9, 9)] + list(ACT):
            m = (B.y >= lo) & (B.y < hi)
            for kind, L_, H_ in (("post", "plo", "phi"), ("pre", "rlo", "rhi")):
                st = [cov_stats(B.y, per[c][L_][r], per[c][H_][r], m) for r in range(TR.REPS)]
                s[kind][nm] = {k: round(float(np.mean([x[k] for x in st])), 4) for k in st[0] if k != "n"} | {"n": int(m.sum())}
        for lo, hi in PRED:
            m = (pm >= lo) & (pm < hi)
            st = [cov_stats(B.y, per[c]["plo"][r], per[c]["phi"][r], m) for r in range(TR.REPS)]
            s["post"][f"pred_{lo:.2f}-{min(hi, 1):.2f}"] = {k: round(float(np.mean([x[k] for x in st])), 4) for k in st[0] if k != "n"} | {"n": int(m.sum())}
        # calibration of P(in band) pooled over reps
        Pall, Hall, P85, H85, P90, H90 = [], [], [], [], [], []
        for r in range(TR.REPS):
            for t in TARGETS:
                b = band_of(t)
                P = np.array([p_in_band(float(x), (float(u), float(v)), b) for x, u, v in
                              zip(per[c]["p"][r], per[c]["plo"][r], per[c]["phi"][r])])
                H = ((B.y >= b[0]) & (B.y <= b[1])).astype(float)
                Pall.append(P)
                Hall.append(H)
                if t == 0.85:
                    P85.append(P), H85.append(H)
                if t == 0.90:
                    P90.append(P), H90.append(H)
        cat = lambda L_: np.concatenate(L_)
        s["calib"] = {"pooled": calib_table(cat(Pall), cat(Hall)), "t0.85": calib_table(cat(P85), cat(H85)),
                      "t0.90": calib_table(cat(P90), cat(H90))}
        IS[c] = np.mean([interval_score(B.y, per[c]["plo"][r], per[c]["phi"][r]) for r in range(TR.REPS)], 0)
        res["summary"][c] = s
        log(c, "post all", s["post"]["all"], "calib pooled brier", s["calib"]["pooled"]["brier"])
    res["D1_empirical_P"] = {"pooled_all_reps": calib_table(np.array(d1["P"]), np.array(d1["H"])),
                             "note": "diagnostic only — not a verdict input"}
    # bootstrap Δ interval score (per-level, rep-mean)
    rng = np.random.RandomState(12345)
    res["boot"] = {}
    for c in ("R1", "R2"):
        d = IS[c] - IS["R0"]
        bs = [d[rng.randint(0, B.n, B.n)].mean() for _ in range(2000)]
        res["boot"][c] = {"d_interval_score": round(float(d.mean()), 4),
                          "ci": [round(float(np.percentile(bs, 2.5)), 4), round(float(np.percentile(bs, 97.5)), 4)]}
    # sealed (doc 36 §2-2 ∩ 379): train on the other 302 once
    seal_L = set(CA.load(CAL / "lowband/compare.json")["sealed"]["levels"])
    sm = np.array([L in seal_L for L in B.L])
    trn, te = np.where(~sm)[0], np.where(sm)[0]
    z_te = TR.point_model().fit(B.X[trn], B.Y[trn], TR.FEATS).predict(B.X[te], TR.FEATS)
    rng_, _ = fit_ranges(B, trn, te, 0, z_te)
    res["sealed"] = {"n": int(sm.sum())}
    for c in CANDS:
        plo, phi = to_prob(rng_[c][0], rng_[c][1])
        res["sealed"][c] = cov_stats(B.y[te], plo, phi)
    # pre-registered judgement
    r0 = res["summary"]["R0"]
    res["judge"] = {}
    for c in ("R1", "R2"):
        s = res["summary"][c]
        q1 = res["boot"][c]["d_interval_score"] < 0 and res["boot"][c]["ci"][1] < 0
        q2 = 0.75 <= s["post"]["all"]["coverage"] <= 0.87 and all(
            s["post"][k]["coverage"] >= r0["post"][k]["coverage"] - 0.05 for k in ("lt0.85", "0.85-0.92", "0.92-0.96", "ge0.96"))
        q3 = s["post"]["all"]["width_mean"] <= 1.25 * r0["post"]["all"]["width_mean"]
        gap = lambda x: abs(x["calib"]["pooled"]["P_ge_0.5"]["mean_P"] - x["calib"]["pooled"]["P_ge_0.5"]["hit_rate"])
        q4 = s["calib"]["pooled"]["brier"] <= r0["calib"]["pooled"]["brier"] and gap(s) <= gap(r0)
        q5 = res["sealed"][c]["interval_score"] < res["sealed"]["R0"]["interval_score"]
        res["judge"][c] = {"Q1": bool(q1), "Q2": bool(q2), "Q3": bool(q3), "Q4": bool(q4), "Q5": bool(q5),
                           "propose": bool(q1 and q2 and q3 and q4 and q5)}
        log(c, res["judge"][c])
    # reliability tables (manifest convention: repeat-mean OOF point + rep-0 range) for export / diagnostics
    rows = B.rows
    res["reliability"] = {c: TR.reliability_tables(rows, pm, B.y, per[c]["plo"][0], per[c]["phi"][0]) for c in CANDS}
    man_rel = CA.load(TR.MODELS / TR.DEFAULT_VERSION / "model.json")["support"]["reliability"]
    res["R0_reliability_equals_active"] = json.dumps(res["reliability"]["R0"], sort_keys=True) == json.dumps(man_rel, sort_keys=True)
    log("R0 reliability table == active manifest:", res["R0_reliability_equals_active"])
    CA.save(OUT / "compare.json", res)
    # keep the per-level OOF for the 379 diagnostic pass counts
    CA.save(OUT / "oof.json", {"L": [int(x) for x in B.L], "y": B.y.tolist(), "pm": pm.tolist(),
                               **{c: {"p0": per[c]["p"][0].tolist(), "plo0": per[c]["plo"][0].tolist(),
                                      "phi0": per[c]["phi"][0].tolist()} for c in CANDS}})
    log("saved", OUT / "compare.json")


CAND_DIRS = {"R0": "cr-ftany-v24r-20261016", "R1": "cr-ftany-v24r-rng-20261016-r1",
             "R2": "cr-ftany-v24r-rng-20261016-r2"}


def cmd_export(a):
    """Candidate directories: active point/aux heads, bot cache and support copied unchanged except the ft_any
    range part and support.reliability (rebuilt from the candidate's own OOF, manifest convention)."""
    import hashlib
    import shutil
    np = np_()
    B = Base()
    TR = B.TR
    base_dir = TR.MODELS / TR.DEFAULT_VERSION
    active_before = (TR.MODELS / "active.json").read_bytes()
    base_bytes = {f: (base_dir / f).read_bytes() for f in ("model.json", "bot_cache.json", "manifest.json")}
    cmp_ = CA.load(OUT / "compare.json")
    idx = np.arange(B.n)
    cr = clear_rate_pkg()
    for c in ("R1", "R2"):
        model = json.loads(base_bytes["model.json"])
        h = model["heads"]["ft_any"]
        for k in ("q_lo", "q_hi", "cqr_w"):
            h.pop(k, None)
        if c == "R1":
            lo, hi = r1_fit(B, idx, 700)
            w = r1_width(B, idx, 0)
            h.update(range_kind="qgbm_on_point", q_lo=TR.j_gbm(lo), q_hi=TR.j_gbm(hi), cqr_w=w)
        else:
            dlo, dhi = r2_offsets(r2_resid(B, idx, 0))
            h.update(range_kind="resid_conformal", d_lo=dlo, d_hi=dhi)
        model["support"]["reliability"] = cmp_["reliability"][c]
        out = TR.MODELS / CAND_DIRS[c]
        out.mkdir(parents=True, exist_ok=True)
        ms = TR.dumps(model)
        (out / "model.json").write_text(ms, encoding="utf-8")
        shutil.copyfile(base_dir / "bot_cache.json", out / "bot_cache.json")
        man = json.loads(base_bytes["manifest.json"])
        man.update(model_version=CAND_DIRS[c], status="experimental range candidate — NOT active; point heads, aux heads, "
                   "bot cache identical to " + TR.DEFAULT_VERSION, range_candidate=c,
                   range_definition={"R1": "quantile GBM q0.1/q0.9 started at point OOF logit + residual quantile "
                                           "(inner map-group 5-fold RandomState(700)), CQR width as before",
                                     "R2": "asymmetric split conformal on pooled inner OOF point residuals "
                                           "(3 × 5-fold, finite-sample 0.9 quantiles)"}[c],
                   doc="claudedocs/difficulty_personalization/36 §9-10", prereg_commit="c11ce5e",
                   independent_validation=False, model_json_sha256=hashlib.sha256(ms.encode()).hexdigest())
        (out / "manifest.json").write_text(json.dumps(man, ensure_ascii=False, indent=1), encoding="utf-8")
        # parity: served pure-Python range == numpy on every training row
        cr.load_model.cache_clear()
        mdl = cr.load_model(CAND_DIRS[c], str(TR.MODELS))
        z = TR.point_model().fit(B.X, B.Y, TR.FEATS).predict(B.X, TR.FEATS)
        if c == "R1":
            rl, rh = r1_raw(lo, hi, B.X, z)
            rl, rh = rl - w, rh + w
        else:
            rl, rh = z - dlo, z + dhi
        plo, phi = to_prob(rl, rh)
        d = 0.0
        for i, r_ in enumerate(B.rows):
            f = dict(zip(TR.FEATS, r_["x"]))
            s_lo, s_hi = mdl.range80("ft_any", f)
            d = max(d, abs(s_lo - plo[i]), abs(s_hi - phi[i]), abs(mdl.predict_logit("ft_any", f) - z[i]))
        assert d < 1e-9, (c, d)
        log(c, "exported", out.name, "parity", f"{d:.1e}", "upper=1 share", round(float((phi >= 1).mean()), 3))
    assert (TR.MODELS / "active.json").read_bytes() == active_before
    assert all((base_dir / f).read_bytes() == b for f, b in base_bytes.items())
    log("active.json and active model files unchanged")


PILOTS = ("20261016", "20261016_p2", "20261016_p3")
TARGET_OF = {"A85": 0.85, "A90": 0.90, "A95": 0.95}
CONFIRM_BANDS = {"C", "C2", "C3"}


def cmd_reeval(a):
    """Run with a python that has the app deps (no numpy needed): saved user-expected pilot candidates × every stored
    full θ4×128 measurement, judged by predict_level + verdict (rule unchanged) under R0 / R1 / R2."""
    import glob
    from app.core.clear_rate import finalize_game_conditions, load_model, cond_hash
    from app.core.clear_rate.predict import BotMeasurement, predict_level
    from app.core.clear_rate.select import verdict
    from app.core.clear_rate.service import random_layout
    gp = CA.DATA / "pv_sandbox/gen_pilot"
    models = {c: load_model(v) for c, v in CAND_DIRS.items()}
    assert models["R0"].version == "cr-ftany-v24r-20261016"
    rows, stored = [], {}
    for pdir in PILOTS:
        store = CA.load(gp / pdir / "measurements.json")
        by_hash = {}
        for key, rec in store.items():
            h, proto, band, _cfg = key.split("|")
            m = rec["measurement"]
            full = proto == "theta4x128_v1" and len(m["rows"]) == 4 and all(r["games"] >= 128 for r in m["rows"])
            if full:
                by_hash.setdefault(h, []).append((band, m))
        for lv, t in TARGET_OF.items():
            d = gp / pdir / lv
            if not d.exists():
                continue
            res = CA.load(d / "result.json")
            ev = res.get("evaluation") or {}
            if ev.get("prediction"):
                stored[(pdir, lv, ev["prediction"]["cond_hash"], ev["prediction"]["measurement"]["seed_band"])] = {
                    "verdict": ev["verdict"]["verdict"], "p_in_band": ev["verdict"].get("p_in_band"),
                    "pred": ev["prediction"]["expected_ft_any"], "range80": ev["prediction"]["range80_ft_any"]}
            for f in sorted(glob.glob(str(d / "cand*.json")) + glob.glob(str(d / "gen*.json"))):
                doc = CA.load(f)
                L = doc.get("placement") or res.get("placement") or (res.get("spec") or {}).get("placement")
                gm, cond = finalize_game_conditions(doc["level_json"], L)
                h = cond_hash(gm, cond)
                rl = random_layout(gm)
                for band, m in by_hash.get(h, []):
                    meas = BotMeasurement.from_dict(m, source="store")
                    row = {"pilot": pdir, "level": lv, "file": Path(f).name, "placement": L, "target": t,
                           "cond_hash": h, "band": band, "confirm_band": band in CONFIRM_BANDS}
                    for c, mdl in models.items():
                        p = predict_level(mdl, gm, cond, L, meas, random_layout=rl)
                        v = verdict(p, t, mdl.model["support"], confirm_bands=(band,))
                        row[c] = {"pred": p.expected_ft_any, "range80": list(p.range80_ft_any) if p.range80_ft_any else None,
                                  "confidence": p.confidence, "in_support": p.in_support,
                                  "flags": sorted({x["code"] for x in p.evidence_flags}),
                                  "p_in_band": v.p_in_band, "verdict": v.verdict,
                                  "target_hard": [x["code"] for x in v.target_flags if x["severity"] == "hard"]}
                    rows.append(row)
        log(pdir, "rows so far", len(rows))
    # regression: R0 must reproduce the stored final evaluations
    reg = []
    for (pdir, lv, h, band), s in stored.items():
        r = next((x for x in rows if x["pilot"] == pdir and x["level"] == lv and x["cond_hash"] == h and x["band"] == band), None)
        ok = r is not None and r["R0"]["verdict"] == s["verdict"] and r["R0"]["p_in_band"] == s["p_in_band"] \
            and r["R0"]["pred"] == s["pred"]
        reg.append({"pilot": pdir, "level": lv, "band": band, "stored": s, "R0": r and r["R0"], "reproduced": ok})
    assert all(x["reproduced"] for x in reg), [x for x in reg if not x["reproduced"]]
    log(f"R0 reproduces all {len(reg)} stored final evaluations")
    # summary by pilot × level × band kind
    summ = {}
    for r in rows:
        k = f"{r['pilot']}|{r['level']}|{'confirm' if r['confirm_band'] else 'search'}"
        s = summ.setdefault(k, {"n": 0, **{c: {"PASS": 0, "FAIL": 0, "INSUFFICIENT_EVIDENCE": 0, "conf_not_low": 0,
                                                "pred_in_band": 0} for c in CAND_DIRS}})
        s["n"] += 1
        for c in CAND_DIRS:
            s[c][r[c]["verdict"]] = s[c].get(r[c]["verdict"], 0) + 1
            s[c]["conf_not_low"] += int(r[c]["confidence"] in ("high", "medium"))
    changed = [{"pilot": r["pilot"], "level": r["level"], "file": r["file"], "band": r["band"],
                **{c: {k: r[c][k] for k in ("pred", "range80", "confidence", "p_in_band", "verdict")} for c in CAND_DIRS}}
               for r in rows if len({r[c]["verdict"] for c in CAND_DIRS}) > 1]
    # doc 33 §15-1 procedure on the training maps (served model, own placement, training rows tagged C) — diagnostic
    import clear_rate_a85_a90 as A
    train = {}
    for c, mdl in models.items():
        items = A.training_items(mdl)
        for t in (0.85, 0.90):
            ev_ = A.eval_set(mdl, items, t)
            ok = [r for r in ev_ if r["class"] not in ("②", "④") and r["pred"] is not None]
            train[f"{c}|{t}"] = {"pass": sum(r["verdict"] == "PASS" for r in ev_), "gate_ok": len(ok),
                                 "gate_ok_pred_min": min((r["pred"] for r in ok), default=None),
                                 "gate_ok_hi_lt_1": sum(1 for r in ok if r["range80"][1] < 1.0),
                                 "pass_levels": [r["src"] for r in ev_ if r["verdict"] == "PASS"][:30]}
        log(c, {k: (v["pass"], v["gate_ok"], v["gate_ok_pred_min"]) for k, v in train.items() if k.startswith(c)})
    CA.save(OUT / "reeval.json", {"regression": reg, "summary": summ, "changed": changed, "rows": rows,
                                  "training_maps_served": train})
    log("saved", OUT / "reeval.json", "changed verdicts", len(changed))


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("reeval").set_defaults(f=cmd_reeval)
    sub.add_parser("diag").set_defaults(f=cmd_diag)
    sub.add_parser("eval").set_defaults(f=cmd_eval)
    sub.add_parser("export").set_defaults(f=cmd_export)
    a = ap.parse_args()
    a.f(a)


if __name__ == "__main__":
    main()
