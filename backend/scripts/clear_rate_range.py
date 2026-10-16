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


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("diag").set_defaults(f=cmd_diag)
    a = ap.parse_args()
    a.f(a)


if __name__ == "__main__":
    main()
