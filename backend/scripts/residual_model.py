"""④ Residual calibration model — bot output + level features → AF unaided clear rate (L32~500).

Reads only existing measurements (no new bot simulation):
  AF   : data/pv_sandbox/af_calibration/bot_v21/af.json   (13 definitions; LB/UB/mid)
  maps : data/pv_sandbox/af_calibration/bot_v21/prep.json (build shard maps = played maps, exclude flags)
  bot  : --bot rows file (default bot_v21/bot_v2.1.json = v2.1 on bomb/grass levels + v2 elsewhere)
         Rows {L, theta, games, wins, fail_reasons, fail_tiles_left[, fail_tiles_left_board]}.
         When the rule-alignment session produces a new bot, point --bot at its rows file and re-run.

Usage (system python with numpy; no sklearn needed):
  /usr/bin/python3 backend/scripts/residual_model.py all [--bot PATH] [--out DIR] [--fast]
Outputs (DIR, default data/pv_sandbox/af_calibration/residual_model/):
  features.csv   per-level feature table (+ AF target columns)
  oof.csv        out-of-fold predictions per model (repeated K-fold, first repeat)
  results.json   all metrics (K-fold / extrapolation / combo holdout / tables / importance / coefficients)
  tables.md      markdown tables used in claudedocs 20
"""
import argparse
import csv
import hashlib
import json
import math
import os
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path

import numpy as np

BACKEND = Path(__file__).resolve().parents[1]
CAL = BACKEND / "data/pv_sandbox/af_calibration"
SEGS = ((32, 100), (101, 300), (301, 500))
GIMMICKS = ("stack", "craft", "ice", "chain", "grass", "bomb", "curtain", "teleporter", "frog", "link", "unknown")
THETAS = (0.55, 0.65, 0.85, 1.0)
MIN_N = 100
Z = 1.96


# ── utils ───────────────────────────────────────────────────────────────────────────────────────
def load(p):
    with open(p, encoding="utf-8") as f:
        return json.load(f)


def seg_of(L):
    for lo, hi in SEGS:
        if lo <= L <= hi:
            return f"{lo}-{hi}"
    return None


def wilson(k, n):
    p = k / n
    den = 1 + Z * Z / n
    c = (p + Z * Z / (2 * n)) / den
    hw = Z * math.sqrt(p * (1 - p) / n + Z * Z / (4 * n * n)) / den
    return max(0.0, c - hw), min(1.0, c + hw)


def logit(p):
    p = np.clip(np.asarray(p, float), 0.01, 0.99)
    return np.log(p / (1 - p))


def expit(x):
    return 1 / (1 + np.exp(-np.asarray(x, float)))


def rank(a):
    a = np.asarray(a, float)
    order = a.argsort(kind="mergesort")
    r = np.empty(len(a))
    r[order] = np.arange(len(a))
    for v in np.unique(a):  # average ties
        m = a == v
        if m.sum() > 1:
            r[m] = r[m].mean()
    return r


def spearman(a, b):
    if len(a) < 3:
        return float("nan")
    return float(np.corrcoef(rank(a), rank(b))[0, 1])


# ── features ────────────────────────────────────────────────────────────────────────────────────
def map_features(m):
    f = Counter()
    bomb_counts, types = [], set()
    n_layers = int(m["layer"])
    for i in range(n_layers):
        for t in (m.get(f"layer_{i}") or {}).get("tiles", {}).values():
            tid = str(t[0])
            eff = str(t[1]) if len(t) > 1 and t[1] else ""
            if tid.startswith(("stack", "craft")):
                kind = "stack" if tid.startswith("stack") else "craft"
                inner = int(t[2][0]) if len(t) > 2 and t[2] else 0
                f[kind] += 1
                f[kind + "_inner"] += inner
                f["tiles"] += inner
                if len(t) > 2 and t[2] and len(t[2]) > 1:
                    types.update(x for x in str(t[2][1]).split("_") if x)
            else:
                f["tiles"] += 1
                types.add(tid)
            if eff:
                base = eff.split("_")[0]
                f[base] += 1
                if base == "bomb":
                    bomb_counts.append(int(eff.split("_")[1]))
    f["layers"] = n_layers
    f["types"] = len(types - {"t0"})
    f["bomb_min"] = min(bomb_counts) if bomb_counts else 0
    f["bomb_sum"] = sum(bomb_counts)
    return f


def combo_of(f):
    effs = [g for g in GIMMICKS if g not in ("craft",) and f.get(g, 0) > 0]
    return "+".join(effs) if effs else "none"


def bot_table(path):
    rows = load(path)["rows"]
    out = defaultdict(dict)
    for r in rows:
        out[r["L"]][round(float(r["theta"]), 2)] = r
    return out


def build(bot_path):
    prep = {int(k): v for k, v in load(CAL / "bot_v21/prep.json").items()}
    af = {int(k): v for k, v in load(CAL / "bot_v21/af.json").items()}
    bot = bot_table(bot_path)
    mf = {L: map_features(prep[L]["map"]) for L in prep}
    # exposure: number of earlier levels (L32..L-1, incl. cat-help levels) that contain the gimmick
    seen, expo = Counter(), {}
    for L in sorted(prep):
        expo[L] = {g: seen[g] for g in GIMMICKS}
        for g in GIMMICKS:
            if mf[L].get(g, 0) > 0:
                seen[g] += 1
    maphash = {L: hashlib.sha1(json.dumps(prep[L]["map"], sort_keys=True).encode()).hexdigest()[:12] for L in prep}
    recs = []
    for L in sorted(prep):
        p, a, f = prep[L], af[L], mf[L]
        lb, ub, n = a["unaided_clear_lower_bound"], a["unaided_clear_upper_bound"], a["first_try_ended"]
        if lb is None or not n:
            continue
        present = [g for g in GIMMICKS if f.get(g, 0) > 0]
        exps = [expo[L][g] for g in present]
        r = {"L": L, "seg": seg_of(L), "exclude": p["exclude"] or "", "n_ft": n, "clean_n": a["clean_ft_n"] or 0,
             "lb": lb, "ub": ub, "mid": (lb + ub) / 2, "lo_w": wilson(round(lb * n), n)[0],
             "hi_w": wilson(round(ub * n), n)[1], "combo": combo_of(f), "maphash": maphash[L],
             # structure
             "logL": math.log(L), "seg101": int(101 <= L <= 300), "seg301": int(L >= 301),
             "tiles": f["tiles"], "layers": f["layers"], "types": p["row"]["useTileCount"],
             "tiles_per_type": f["tiles"] / max(1, p["row"]["useTileCount"]),
             "unlockTile": int(p["row"]["unlockTile"] or 0), "is_boss": int(bool(a.get("is_boss"))),
             "random_layout": int(p["mode"] == "random"), "map2nd": int(p["map_match_editor"] == "mismatch"),
             "cat_help": int(float(p["row"]["autoCollectCount"] or 0) > 0),
             "n_gimmick_types": len([g for g in present if g != "craft"]),
             # exposure / novelty
             "gimmick_first": int(bool(a.get("is_gimmick_first"))),
             "novel_any": int(any(e == 0 for e in exps)),
             "novelty": float(sum(math.exp(-e / 15) for e in exps)),
             "bomb_min": f["bomb_min"] if f.get("bomb", 0) else 6, "bomb_sum": f["bomb_sum"],
             "stack_inner": f.get("stack_inner", 0), "craft_inner": f.get("craft_inner", 0)}
        for g in GIMMICKS:
            r["has_" + g] = int(f.get(g, 0) > 0)
            r["n_" + g] = math.log1p(f.get(g, 0))
        # bot
        b = bot.get(L, {})
        r["has_bot"] = int(all(t in b for t in THETAS))
        for t in THETAS:
            rr = b.get(t)
            k = f"r{int(round(t * 100)):03d}"
            r[k] = rr["wins"] / rr["games"] if rr else float("nan")
        rr = b.get(1.0)
        if rr:
            fails = max(1, rr["games"] - rr["wins"])
            fr = rr["fail_reasons"]
            r["bot_bomb_share"] = fr.get("Bomb", 0) / fails
            r["bot_grass_share"] = fr.get("Grass", 0) / fails
            left = rr.get("fail_tiles_left_board") or [max(0, x - 7) for x in rr.get("fail_tiles_left", [])]
            r["bot_left_rel"] = float(np.median(left)) / max(1, f["tiles"]) if left else 0.0
        else:
            r["bot_bomb_share"] = r["bot_grass_share"] = r["bot_left_rel"] = float("nan")
        recs.append(r)
    return recs


LOGO_MODELS = ("a: logit맵 θ0.65", "b: ridge 봇+구간+기믹", "c+: ridge·GBM 평균", "d: ridge 특징만(봇 없음)")
F_SEG = ["seg101", "seg301", "logL"]
F_STRUCT = ["tiles", "layers", "types", "tiles_per_type", "unlockTile", "is_boss", "random_layout", "map2nd"]
F_GIM = ([f"has_{g}" for g in GIMMICKS] + [f"n_{g}" for g in GIMMICKS] +
         ["stack_inner", "craft_inner", "bomb_min", "bomb_sum", "n_gimmick_types"])
F_NOV = ["gimmick_first", "novel_any", "novelty"]
F_BOT = ["lg055", "lg065", "lg085", "lg100", "bot_bomb_share", "bot_grass_share", "bot_left_rel"]
FEATS_ALL = F_SEG + F_STRUCT + F_GIM + F_NOV + F_BOT
FEATS_NOBOT = F_SEG + F_STRUCT + F_GIM + F_NOV


def matrix(recs, cols):
    X = np.array([[r[c] for c in cols] for r in recs], float)
    return X


def add_logits(recs):
    for r in recs:
        for t, k in zip(THETAS, ("lg055", "lg065", "lg085", "lg100")):
            v = r[f"r{int(round(t * 100)):03d}"]
            r[k] = float(logit(v)) if v == v else float("nan")


# ── models ──────────────────────────────────────────────────────────────────────────────────────
class LogitMap:
    """(a) 15/16 baseline: logit(mid) = a + b·logit(bot rate at θ)."""
    def __init__(self, col):
        self.col = col

    def fit(self, X, y, cols):
        x = X[:, cols.index(self.col)]
        b = np.cov(x, y, bias=True)[0, 1] / max(1e-9, x.var())
        self.a, self.b = y.mean() - b * x.mean(), b
        return self

    def predict(self, X, cols):
        return self.a + self.b * X[:, cols.index(self.col)]


class SegMean:
    def fit(self, X, y, cols):
        s = X[:, cols.index("seg101")] + 2 * X[:, cols.index("seg301")]
        self.m = {k: y[s == k].mean() if (s == k).any() else y.mean() for k in (0, 1, 2)}
        return self

    def predict(self, X, cols):
        s = X[:, cols.index("seg101")] + 2 * X[:, cols.index("seg301")]
        return np.array([self.m[int(k)] for k in s])


class Ridge:
    """(b)/(d) ridge on standardized features; λ by inner 5-fold CV."""
    GRID = (0.3, 1, 3, 10, 30, 100, 300)

    def __init__(self, feats, lam=None):
        self.feats, self.lam = feats, lam

    def _solve(self, Xs, y, lam):
        n, p = Xs.shape
        A = np.hstack([np.ones((n, 1)), Xs])
        R = lam * np.eye(p + 1)
        R[0, 0] = 0
        return np.linalg.solve(A.T @ A + R, A.T @ y)

    def _std(self, X):
        return (X - self.mu) / self.sd

    def fit(self, X, y, cols):
        idx = [cols.index(c) for c in self.feats]
        Xf = X[:, idx]
        self.idx = idx
        self.mu, self.sd = Xf.mean(0), Xf.std(0)
        self.sd[self.sd < 1e-9] = 1
        Xs = self._std(Xf)
        lam = self.lam
        if lam is None:
            rng = np.random.RandomState(7)
            fold = rng.permutation(len(y)) % 5
            err = []
            for l in self.GRID:
                e = 0
                for k in range(5):
                    tr, te = fold != k, fold == k
                    w = self._solve(Xs[tr], y[tr], l)
                    e += np.abs(expit(w[0] + Xs[te] @ w[1:]) - expit(y[te])).sum()
                err.append(e)
            lam = self.GRID[int(np.argmin(err))]
        self.lam_used = lam
        self.w = self._solve(Xs, y, lam)
        return self

    def predict(self, X, cols):
        return self.w[0] + self._std(X[:, self.idx]) @ self.w[1:]


class GBM:
    """(c) gradient-boosted regression trees (squared loss on logit target), numpy only."""
    def __init__(self, feats, n_est=250, lr=0.04, depth=3, min_leaf=8, subsample=0.8, colsample=0.7, seed=0):
        self.feats, self.n_est, self.lr, self.depth = feats, n_est, lr, depth
        self.min_leaf, self.subsample, self.colsample, self.seed = min_leaf, subsample, colsample, seed

    def _best_split(self, X, g, cols):
        n = len(g)
        if n < 2 * self.min_leaf:
            return None
        Xc = X[:, cols]
        order = Xc.argsort(axis=0, kind="mergesort")
        xs = np.take_along_axis(Xc, order, 0)
        gs = g[order]
        cs = gs.cumsum(0)[:-1]
        tot = g.sum()
        nl = np.arange(1, n)[:, None]
        nr = n - nl
        gain = cs ** 2 / nl + (tot - cs) ** 2 / nr - tot ** 2 / n
        valid = (xs[1:] > xs[:-1]) & (nl >= self.min_leaf) & (nr >= self.min_leaf)
        gain = np.where(valid, gain, -np.inf)
        k = np.unravel_index(np.argmax(gain), gain.shape)
        if not np.isfinite(gain[k]) or gain[k] <= 1e-12:
            return None
        j = cols[k[1]]
        thr = (xs[k[0], k[1]] + xs[k[0] + 1, k[1]]) / 2
        return j, thr, float(gain[k])

    def _grow(self, X, g, depth, cols):
        sp = self._best_split(X, g, cols) if depth < self.depth else None
        if sp is None:
            return ("leaf", float(g.mean()))
        j, thr, gain = sp
        self.gain[j] += gain
        m = X[:, j] <= thr
        return ("node", j, thr, self._grow(X[m], g[m], depth + 1, cols), self._grow(X[~m], g[~m], depth + 1, cols))

    @staticmethod
    def _pred_tree(t, X):
        if t[0] == "leaf":
            return np.full(len(X), t[1])
        out = np.empty(len(X))
        m = X[:, t[1]] <= t[2]
        out[m] = GBM._pred_tree(t[3], X[m])
        out[~m] = GBM._pred_tree(t[4], X[~m])
        return out

    def fit(self, X, y, cols):
        self.idx = [cols.index(c) for c in self.feats]
        Xf = X[:, self.idx]
        rng = np.random.RandomState(self.seed)
        self.base = float(y.mean())
        self.gain = np.zeros(len(self.idx))
        F = np.full(len(y), self.base)
        self.trees = []
        p = len(self.idx)
        for _ in range(self.n_est):
            rows = rng.rand(len(y)) < self.subsample
            cols = sorted(rng.choice(p, max(1, int(p * self.colsample)), replace=False))
            t = self._grow(Xf[rows], (y - F)[rows], 0, cols)
            self.trees.append(t)
            F += self.lr * self._pred_tree(t, Xf)
        return self

    def predict(self, X, cols):
        Xf = X[:, self.idx]
        F = np.full(len(X), self.base)
        for t in self.trees:
            F += self.lr * self._pred_tree(t, Xf)
        return F


class Blend:
    def __init__(self, *models):
        self.models = models

    def fit(self, X, y, cols):
        for m in self.models:
            m.fit(X, y, cols)
        return self

    def predict(self, X, cols):
        return np.mean([m.predict(X, cols) for m in self.models], axis=0)


class MeanMatch:
    """Jensen fix: shift logit output so mean predicted prob on train = mean train target prob."""
    def __init__(self, model):
        self.model = model

    def fit(self, X, y, cols):
        self.model.fit(X, y, cols)
        p, t = self.model.predict(X, cols), expit(y).mean()
        lo, hi = -2.0, 2.0
        for _ in range(40):
            d = (lo + hi) / 2
            lo, hi = (d, hi) if expit(p + d).mean() < t else (lo, d)
        self.d = (lo + hi) / 2
        return self

    def predict(self, X, cols):
        return self.model.predict(X, cols) + self.d


def make_models():
    return {
        "seg_mean (봇 없음 기준선)": lambda: SegMean(),
        "a: logit맵 θ0.65": lambda: LogitMap("lg065"),
        "a: logit맵 θ0.55": lambda: LogitMap("lg055"),
        "b: ridge 봇+구간+기믹": lambda: Ridge(FEATS_ALL),
        "b0: ridge 봇+구간만": lambda: Ridge(F_BOT + F_SEG),
        "c: GBM 전체": lambda: GBM(FEATS_ALL),
        "c+: ridge·GBM 평균": lambda: Blend(Ridge(FEATS_ALL), GBM(FEATS_ALL)),
        "c+mm: 평균 + 평균보정": lambda: MeanMatch(Blend(Ridge(FEATS_ALL), GBM(FEATS_ALL))),
        "d: ridge 특징만(봇 없음)": lambda: Ridge(FEATS_NOBOT),
        "d: GBM 특징만(봇 없음)": lambda: GBM(FEATS_NOBOT),
    }


# ── evaluation ──────────────────────────────────────────────────────────────────────────────────
def metrics(recs, pred):
    pred = np.asarray(pred, float)
    lb = np.array([r["lb"] for r in recs])
    ub = np.array([r["ub"] for r in recs])
    lo = np.array([r["lo_w"] for r in recs])
    hi = np.array([r["hi_w"] for r in recs])
    mid = np.array([r["mid"] for r in recs])
    return {"n": len(recs), "strict": float(((pred >= lb) & (pred <= ub)).mean()),
            "tolAF": float(((pred >= lo) & (pred <= hi)).mean()), "mae": float(np.abs(pred - mid).mean()),
            "bias": float((pred - mid).mean()), "rho": spearman(pred, mid)}


def oof_predict(make, X, y, cols, folds):
    out = np.full(len(y), np.nan)
    for k in np.unique(folds):
        te = folds == k
        m = make().fit(X[~te], y[~te], cols)
        out[te] = m.predict(X[te], cols)
    return out


def r3(d):
    return {k: (round(v, 3) if isinstance(v, float) else v) for k, v in d.items()}


def noise_floor(recs, reps=400):
    """Sampling noise of the AF target: resample LB/UB counts (binomial) and score the *true* mid against them."""
    rng = np.random.RandomState(11)
    n = np.array([r["n_ft"] for r in recs])
    lb = np.array([r["lb"] for r in recs])
    ub = np.array([r["ub"] for r in recs])
    mid = (lb + ub) / 2
    mae, strict, tol = [], [], []
    for _ in range(reps):
        lb2 = rng.binomial(n, lb) / n
        extra = rng.binomial(n, np.clip(ub - lb, 0, 1)) / n
        ub2 = np.minimum(1, lb2 + extra)
        mae.append(np.abs((lb2 + ub2) / 2 - mid).mean())
        strict.append(((mid >= lb2) & (mid <= ub2)).mean())
        lo = np.array([wilson(round(a * b), b)[0] for a, b in zip(lb2, n)])
        hi = np.array([wilson(round(a * b), b)[1] for a, b in zip(ub2, n)])
        tol.append(((mid >= lo) & (mid <= hi)).mean())
        if len(mae) >= 60:
            break
    return {"mae_noise": float(np.mean(mae)), "strict_ceiling": float(np.mean(strict)),
            "tolAF_ceiling": float(np.mean(tol)), "mean_half_width": float(((ub - lb) / 2).mean())}


def group_table(recs, preds, key):
    groups = defaultdict(list)
    for i, r in enumerate(recs):
        for g in key(r):
            groups[g].append(i)
    out = {}
    for g, ix in sorted(groups.items(), key=lambda kv: -len(kv[1])):
        sub = [recs[i] for i in ix]
        out[g] = {name: r3(metrics(sub, p[ix])) for name, p in preds.items()}
    return out


def gim_keys(r):
    ks = [g for g in GIMMICKS if r["has_" + g]]
    ks += ["(기믹 없음)"] if not any(r["has_" + g] for g in GIMMICKS if g != "craft") else []
    ks += ["(첫 등장)"] if r["gimmick_first"] else []
    ks += ["(2차배치 맵)"] if r["map2nd"] else []
    ks += ["(보스)"] if r["is_boss"] else []
    return ks


def perm_importance(make, X, y, cols, folds, feats, recs, reps=3):
    """Permutation importance on held-out folds: Δ MAE (prob. scale) when one feature group is shuffled."""
    rng = np.random.RandomState(5)
    mid = np.array([r["mid"] for r in recs])
    base_err, perm_err = 0.0, defaultdict(float)
    for k in np.unique(folds):
        te = folds == k
        m = make().fit(X[~te], y[~te], cols)
        Xt = X[te]
        base_err += np.abs(expit(m.predict(Xt, cols)) - mid[te]).sum()
        for name, fs in feats.items():
            for _ in range(reps):
                Xp = Xt.copy()
                perm = rng.permutation(len(Xt))
                for c in fs:
                    Xp[:, cols.index(c)] = Xt[perm, cols.index(c)]
                perm_err[name] += np.abs(expit(m.predict(Xp, cols)) - mid[te]).sum() / reps
    n = len(y)
    return {name: round((v - base_err) / n, 4) for name, v in sorted(perm_err.items(), key=lambda kv: -kv[1])}


def conformal(make, X, y, cols, folds, q=0.8):
    """Prediction interval = pred ± q-quantile of inner-CV |logit residual| (per outer fold)."""
    lo = np.full(len(y), np.nan)
    hi = np.full(len(y), np.nan)
    mid_hat = np.full(len(y), np.nan)
    for k in np.unique(folds):
        te = folds == k
        tr_idx = np.where(~te)[0]
        inner = np.random.RandomState(k).permutation(len(tr_idx)) % 5
        res = []
        for j in range(5):
            a, b = tr_idx[inner != j], tr_idx[inner == j]
            m = make().fit(X[a], y[a], cols)
            res.append(np.abs(m.predict(X[b], cols) - y[b]))
        w = np.quantile(np.concatenate(res), q)
        m = make().fit(X[~te], y[~te], cols)
        p = m.predict(X[te], cols)
        mid_hat[te], lo[te], hi[te] = p, p - w, p + w
    return expit(mid_hat), expit(lo), expit(hi)


GRADES = ((0.90, "S"), (0.80, "A"), (0.65, "B"), (0.50, "C"), (0.0, "D"))


def grade(p):
    for t, g in GRADES:
        if p >= t:
            return g
    return "D"


def md_table(title, rows, cols):
    s = [f"#### {title}", "", "| " + " | ".join(cols) + " |", "|" + "---|" * len(cols)]
    s += ["| " + " | ".join(str(x) for x in r) + " |" for r in rows]
    return "\n".join(s) + "\n"


def run_all(a):
    t0 = time.time()
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    recs_all = build(Path(a.bot))
    add_logits(recs_all)
    cols = FEATS_ALL
    # feature table
    keys = list(recs_all[0].keys())
    with open(out / "features.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, keys)
        w.writeheader()
        for r in recs_all:
            w.writerow({k: (round(v, 5) if isinstance(v, float) else v) for k, v in r.items()})
    # main set: same as 15/16 (no exclude, n_ft-based clean_n ≥ 100, bot present)
    recs = [r for r in recs_all if not r["exclude"] and r["clean_n"] >= MIN_N and r["has_bot"]]
    X, y = matrix(recs, cols), logit([r["mid"] for r in recs])
    assert not np.isnan(X).any(), "NaN in feature matrix"
    res = {"bot_file": str(a.bot), "levels": len(recs), "n_features": len(cols), "features": cols}
    # leakage / duplication checks
    hc = Counter(r["maphash"] for r in recs_all)
    res["dup_maps"] = {h: [r["L"] for r in recs_all if r["maphash"] == h] for h, c in hc.items() if c > 1}
    res["dup_levels"] = len(recs) - len({r["L"] for r in recs})
    res["noise"] = r3(noise_floor(recs))
    models = make_models()
    if a.fast:
        models = {k: v for k, v in models.items() if not k.startswith(("c", "d: GBM"))}
    # 1) repeated K-fold (groups = duplicate-map clusters so identical maps never straddle folds)
    reps, K = (2, 5) if a.fast else (4, 5)
    grp = np.array([r["maphash"] for r in recs])
    ug = sorted(set(grp))
    kf = {}
    oof_first = {}
    for name, mk in models.items():
        ms = []
        for rep in range(reps):
            gperm = {g: i % K for i, g in enumerate(np.random.RandomState(100 + rep).permutation(ug))}
            folds = np.array([gperm[g] for g in grp])
            p = expit(oof_predict(mk, X, y, cols, folds))
            ms.append(metrics(recs, p))
            if rep == 0:
                oof_first[name] = p
        kf[name] = r3({k: float(np.mean([m[k] for m in ms])) for k in ms[0]})
        kf[name]["mae_sd_reps"] = round(float(np.std([m["mae"] for m in ms])), 4)
        print(f"[kfold] {name:28s} {kf[name]}  t={time.time()-t0:.0f}s", flush=True)
    res["kfold"] = kf
    # 2) extrapolation: train L32~300 → test 301~500
    tr = np.array([r["L"] <= 300 for r in recs])
    ext = {}
    for name, mk in models.items():
        m = mk().fit(X[tr], y[tr], cols)
        p = expit(m.predict(X[~tr], cols))
        ext[name] = r3(metrics([r for r, t in zip(recs, tr) if not t], p))
        # recentred variant: level offset re-estimated from 10 random 301+ levels (cheap "pilot" anchor)
    res["extrap"] = ext
    print("[extrap] done", flush=True)
    # 2b) extrapolation with a small anchor sample (10 levels of 301~500 measured with AF) → bias correction
    rng = np.random.RandomState(3)
    te_idx = np.where(~tr)[0]
    anc = {}
    for name in ("b: ridge 봇+구간+기믹", "c+: ridge·GBM 평균", "a: logit맵 θ0.65", "d: ridge 특징만(봇 없음)"):
        if name not in models:
            continue
        m = models[name]().fit(X[tr], y[tr], cols)
        pl = m.predict(X[te_idx], cols)
        ms = []
        for _ in range(30):
            pick = rng.choice(len(te_idx), 10, replace=False)
            shift = (y[te_idx][pick] - pl[pick]).mean()
            rest = np.setdiff1d(np.arange(len(te_idx)), pick)
            ms.append(metrics([recs[i] for i in te_idx[rest]], expit(pl[rest] + shift)))
        anc[name] = r3({k: float(np.mean([x[k] for x in ms])) for k in ms[0]})
    res["extrap_anchor10"] = anc
    # 3) gimmick-combo holdout (leave-one-combo-out)
    combos = np.array([r["combo"] for r in recs])
    uc = sorted(set(combos))
    cfold = np.array([uc.index(c) for c in combos])
    ch = {}
    oof_combo = {}
    for name, mk in models.items():
        p = expit(oof_predict(mk, X, y, cols, cfold))
        oof_combo[name] = p
        ch[name] = r3(metrics(recs, p))
    res["combo_holdout"] = ch
    res["combo_sizes"] = dict(Counter(combos).most_common())
    print(f"[combo] done t={time.time()-t0:.0f}s", flush=True)
    # 3b) leave-one-gimmick-out: every level containing gimmick g is held out, model never saw g
    log = {}
    for g in ("bomb", "grass", "chain", "ice", "curtain", "teleporter", "frog", "unknown", "stack"):
        te = np.array([r["has_" + g] == 1 for r in recs])
        log[g] = {"n": int(te.sum())}
        for name in LOGO_MODELS:
            if name not in models:
                continue
            m = models[name]().fit(X[~te], y[~te], cols)
            mm = metrics([r for r, t in zip(recs, te) if t], expit(m.predict(X[te], cols)))
            log[g][name] = r3(mm)
    res["gimmick_holdout"] = log
    print(f"[gimmick-out] done t={time.time()-t0:.0f}s", flush=True)
    # tables: segment / gimmick (first-repeat OOF)
    show = [k for k in ("a: logit맵 θ0.65", "b: ridge 봇+구간+기믹", "c+: ridge·GBM 평균", "d: ridge 특징만(봇 없음)")
            if k in oof_first]
    res["by_segment"] = group_table(recs, {k: oof_first[k] for k in show}, lambda r: [r["seg"]])
    res["by_gimmick"] = group_table(recs, {k: oof_first[k] for k in show}, gim_keys)
    res["combo_by_gimmick"] = group_table(recs, {k: oof_combo[k] for k in show}, gim_keys)
    # importance & coefficients (fit on all levels)
    folds0 = np.array([{g: i % K for i, g in enumerate(np.random.RandomState(100).permutation(ug))}[g] for g in grp])
    groups = {"봇 성공률(θ0.55~1.0)": ["lg055", "lg065", "lg085", "lg100"],
              "봇 실패형태(폭탄·풀 비중, 잔여)": ["bot_bomb_share", "bot_grass_share", "bot_left_rel"],
              "구간·레벨번호": F_SEG, "구조(타일·층·종류·보스)": F_STRUCT,
              "stack": ["has_stack", "n_stack", "stack_inner"], "craft": ["has_craft", "n_craft", "craft_inner"],
              "bomb": ["has_bomb", "n_bomb", "bomb_min", "bomb_sum"], "grass": ["has_grass", "n_grass"],
              "기타 효과기믹": [f"{p}_{g}" for g in ("ice", "chain", "curtain", "teleporter", "frog", "link", "unknown")
                           for p in ("has", "n")] + ["n_gimmick_types"],
              "첫 등장·노출": F_NOV}
    if not a.fast:
        res["perm_importance_ridge"] = perm_importance(lambda: Ridge(FEATS_ALL), X, y, cols, folds0, groups, recs)
        res["perm_importance_gbm"] = perm_importance(lambda: GBM(FEATS_ALL), X, y, cols, folds0, groups, recs)
        g = GBM(FEATS_ALL).fit(X, y, cols)
        res["gbm_split_gain_top"] = {FEATS_ALL[i]: round(float(v / g.gain.sum()), 3)
                                     for i, v in sorted(enumerate(g.gain), key=lambda kv: -kv[1])[:15]}
    rd = Ridge(FEATS_ALL).fit(X, y, cols)
    res["ridge_lambda"] = rd.lam_used
    res["ridge_coef_std"] = {c: round(float(w), 4) for c, w in sorted(zip(FEATS_ALL, rd.w[1:]), key=lambda kv: -abs(kv[1]))}
    res["ridge_intercept"] = round(float(rd.w[0]), 4)
    # interpretable compact model: logit map + offsets (few terms, unstandardized)
    compact = ["lg065", "lg100", "seg101", "seg301", "has_stack", "has_bomb", "has_grass", "has_teleporter",
               "has_frog", "has_ice", "has_chain", "has_curtain", "has_unknown", "has_link", "has_craft",
               "gimmick_first", "is_boss", "map2nd", "bot_bomb_share", "bot_grass_share"]
    cm = Ridge(compact, lam=3).fit(X, y, cols)
    raw = cm.w[1:] / cm.sd
    res["compact_coef_raw_logit"] = {c: round(float(w), 3) for c, w in zip(compact, raw)}
    res["compact_intercept_raw"] = round(float(cm.w[0] - (cm.w[1:] * cm.mu / cm.sd).sum()), 3)
    res["compact_kfold"] = r3(metrics(recs, expit(oof_predict(lambda: Ridge(compact, lam=3), X, y, cols, folds0))))
    # prediction interval (final candidate) + grade agreement + confidence tiers
    fin_name = a.final
    fin = models.get(fin_name) or models["b: ridge 봇+구간+기믹"]
    ph, lo, hi = conformal(fin, X, y, cols, folds0, q=0.8)
    mid = np.array([r["mid"] for r in recs])
    lbv = np.array([r["lb"] for r in recs])
    ubv = np.array([r["ub"] for r in recs])
    ga = np.mean([grade(p) == grade(m) for p, m in zip(ph, mid)])
    order = "SABCD"
    ga1 = np.mean([abs(order.index(grade(p)) - order.index(grade(m))) <= 1 for p, m in zip(ph, mid)])
    # [수정 23] `x > 0.5 or gimmick_first` 는 gimmick_first(int)를 그대로 돌려줘 int 배열이 됐고, 그 배열로 인덱싱하면
    # 0번·1번 레벨만 반복 선택됐다(21 §0-5). bool 로 강제해 마스크로 쓴다.
    nov = np.array([bool(r["novelty"] > 0.5 or r["gimmick_first"]) for r in recs], dtype=bool)
    err = np.abs(ph - mid)
    res["interval80"] = {"model": fin_name if fin_name in models else "b: ridge 봇+구간+기믹",
                         "coverage_mid": round(float(((mid >= lo) & (mid <= hi)).mean()), 3),
                         "overlap_LBUB": round(float(((lo <= ubv) & (hi >= lbv)).mean()), 3),
                         "mean_width": round(float((hi - lo).mean()), 3),
                         "grade_exact": round(float(ga), 3), "grade_within1": round(float(ga1), 3),
                         "grade_dist_af": dict(Counter(grade(m) for m in mid)),
                         "mae_novel": round(float(err[nov].mean()), 3), "n_novel": int(nov.sum()),
                         "mae_familiar": round(float(err[~nov].mean()), 3)}
    # extended set for (d): include cat-help levels (no bot needed)
    ext_recs = [r for r in recs_all if r["exclude"] in ("", "cat_help") and r["clean_n"] >= MIN_N]
    Xe, ye = matrix(ext_recs, FEATS_NOBOT + ["cat_help"]), logit([r["mid"] for r in ext_recs])
    ef = np.array([i % 5 for i in np.random.RandomState(9).permutation(len(ye))])
    cE = FEATS_NOBOT + ["cat_help"]
    pe = expit(oof_predict(lambda: Ridge(cE), Xe, ye, cE, ef))
    isc = np.array([r["cat_help"] == 1 for r in ext_recs])
    rr = Ridge(cE).fit(Xe, ye, cE)
    res["catset_d_ridge"] = {"levels": len(ext_recs), "cat_levels": int(isc.sum()),
                             "all": r3(metrics(ext_recs, pe)),
                             "cat_only": r3(metrics([r for r, c in zip(ext_recs, isc) if c], pe[isc])),
                             "cat_help_coef_std": round(float(rr.w[1:][cE.index("cat_help")]), 3),
                             "cat_mid_mean": round(float(np.mean([r["mid"] for r, c in zip(ext_recs, isc) if c])), 3),
                             "noncat_mid_mean": round(float(np.mean([r["mid"] for r, c in zip(ext_recs, isc) if not c])), 3)}
    # largest residuals of the final model (OOF)
    resid = ph - mid
    top = np.argsort(-np.abs(resid))[:15]
    res["top_residuals"] = [{"L": recs[i]["L"], "combo": recs[i]["combo"], "af_lb": recs[i]["lb"], "af_ub": recs[i]["ub"],
                             "pred": round(float(ph[i]), 3), "resid": round(float(resid[i]), 3),
                             "bot065": round(recs[i]["r065"], 3), "bot100": round(recs[i]["r100"], 3)} for i in top]
    res["runtime_sec"] = round(time.time() - t0, 1)
    with open(out / "results.json", "w", encoding="utf-8") as f:
        json.dump(res, f, ensure_ascii=False, indent=1)
    with open(out / "oof.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        names = list(oof_first)
        w.writerow(["L", "seg", "combo", "lb", "ub", "mid"] + names + ["final_lo80", "final_hi80"])
        for i, r in enumerate(recs):
            w.writerow([r["L"], r["seg"], r["combo"], r["lb"], r["ub"], round(r["mid"], 4)] +
                       [round(float(oof_first[n][i]), 4) for n in names] + [round(float(lo[i]), 4), round(float(hi[i]), 4)])
    write_tables(res, out / "tables.md")
    print(f"done {res['runtime_sec']}s → {out}")


def write_tables(res, path):
    cols = ["모델", "적중(엄격)", "tolAF", "MAE", "편향", "ρ"]

    def rows(d):
        return [[k, v["strict"], v["tolAF"], v["mae"], v["bias"], v["rho"]] for k, v in d.items()]
    s = [md_table(f"K-fold (5겹×반복, {res['levels']}레벨)", rows(res["kfold"]), cols),
         md_table("외삽 L32~300 → 301~500", rows(res["extrap"]), cols),
         md_table("외삽 + 301~500 앵커 10레벨로 편향만 보정 (30회 평균)", rows(res["extrap_anchor10"]), cols),
         md_table("기믹 조합 홀드아웃 (leave-one-combo-out)", rows(res["combo_holdout"]), cols)]
    gm = list(LOGO_MODELS)
    s.append(md_table("기믹 단위 홀드아웃 (그 기믹이 든 레벨 전부 제외 학습) — MAE/편향/엄격적중",
                      [[g, d["n"]] + [f"{d[n]['mae']}/{d[n]['bias']:+.3f}/{d[n]['strict']}" if n in d else "-" for n in gm]
                       for g, d in res["gimmick_holdout"].items()], ["기믹", "n"] + gm))
    for key, title in (("by_segment", "구간별 (K-fold OOF)"), ("by_gimmick", "기믹별 (K-fold OOF)"),
                       ("combo_by_gimmick", "기믹별 (조합 홀드아웃 OOF)")):
        names = list(next(iter(res[key].values())).keys())
        rr = [[g, d[names[0]]["n"]] + [f"{d[n]['mae']}/{d[n]['bias']:+.3f}/{d[n]['strict']}" for n in names]
              for g, d in res[key].items()]
        s.append(md_table(title + " — MAE/편향/엄격적중", rr, ["그룹", "n"] + names))
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(s))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["all"])
    ap.add_argument("--bot", default=str(CAL / "bot_v21/bot_v2.1.json"))
    ap.add_argument("--out", default=str(CAL / "residual_model"))
    ap.add_argument("--final", default="c+: ridge·GBM 평균")
    ap.add_argument("--fast", action="store_true")
    a = ap.parse_args()
    run_all(a)


if __name__ == "__main__":
    main()
