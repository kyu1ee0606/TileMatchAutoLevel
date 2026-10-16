"""Low clear-rate band (≈27–85 % ft_any) — data support + candidate models (doc 36). Offline only.

The active model (cr-ftany-v24r-20261016), active.json and every saved model directory are never written.
No bot measurement: stored AF aggregates (level_metrics / low_clear_inventory), stored bot v2.4 rows
(training file + cand_a1a2 A2 rows) and the doc 33 §12 comparison only.

  support  §1 table: per actual band — levels, first-try n, Wilson CI, map match, placement / gimmick / version
           skew, training inclusion and exclusion reasons → lowband/support.{json,md}
  eval     §2–3 pre-registered comparison (doc 36 §3, committed before this was run) → lowband/compare.{json,md}

Run from the worktree root with the analysis venv (numpy only); data are read from the main checkout's ignored
sandbox (CR_DATA_ROOT, default ../TileMatchAutoLevel/backend/data), outputs go to <CAL>/lowband/.
"""
import os

os.environ.setdefault("OMP_NUM_THREADS", "1")

import argparse
import json
import math
import sys
import time
from collections import Counter
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import clear_rate_cand_a1a2 as CA  # noqa: E402  (data paths, dataset(), tr())

CAL = CA.CAL
OUT = CAL / "lowband"
T0 = time.time()


def log(*a):
    print(f"[{time.time() - T0:6.0f}s]", *a, flush=True)


def save(path, obj):
    CA.save(path, obj)


# ── §1 data support ─────────────────────────────────────────────────────────────────────────────
BANDS = (("<0.50", -9, 0.50), ("0.50-0.70", 0.50, 0.70), ("0.70-0.85", 0.70, 0.85),
         ("0.85-0.92", 0.85, 0.92), ("0.92-0.96", 0.92, 0.96), (">=0.96", 0.96, 9))
PLACE = (("L1-31", 1, 31), ("L32-100", 32, 100), ("L101-300", 101, 300), ("L301-500", 301, 500),
         ("L501-1000", 501, 1000), ("L1001-1500", 1001, 1500))
MIN_N = 100


def wilson(k, n, z=1.96):
    if n <= 0:
        return (float("nan"), float("nan"))
    p = k / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return (c - h, c + h)


def version_z(v):
    a, b = v.get("android|1.0.162"), v.get("android|1.1.0")
    if not a or not b or not a["n"] or not b["n"]:
        return None
    p = (a["rate"] * a["n"] + b["rate"] * b["n"]) / (a["n"] + b["n"])
    se = math.sqrt(max(1e-12, p * (1 - p) * (1 / a["n"] + 1 / b["n"])))
    return (b["rate"] - a["rate"]) / se


def maps_all():
    """Played map per level: build-1.1.0 shard prep (L32..578, same as training); editor LIVE3 source otherwise
    (gimmick presence only — marked as such)."""
    P, _ = CA.prep_all()
    src = CA.load(CA.DATA / "pv_sandbox/pv_20261002_live3/source.json")["levels"]
    out = {}
    for lv in src:
        L = int(lv["meta"]["level_number"])
        out[L] = (lv["level_json"], "editor_live3")
    for L, p in P.items():
        out[int(L)] = (p["map"], "shard_110")
    return out


def cmd_support(a):
    TR = CA.tr()
    inv = CA.load(CAL / "low_clear_inventory.json")
    LM = {r["level"]: r for r in CA.load(CAL / "level_metrics.json")["levels"]}
    bot_L = {r["L"] for r in CA.load(CAL / TR.BOT_FILE)["rows"]} | {r["L"] for r in CA.load(CA.OUT / "bot_v24_rules_A2.json")["rows"]}
    added = set(CA.A1) | set(CA.A2)
    maps = maps_all()
    recs = []
    for x in inv["all_levels"]:
        L, ft, n = x["L"], x["ft_any"], x["n_first_try_ended"] or 0
        if not x["has_af_data"] or ft is None:
            continue
        k = round(ft * n)
        lo, hi = wilson(k, n)
        mf = TR.FE.map_features(maps[L][0]) if L in maps else None
        gims = TR.FE.present_gimmicks(mf) if mf else []
        lm = LM.get(L, {})
        recs.append({
            "L": L, "ft_any": ft, "n": n, "wilson": [round(lo, 4), round(hi, 4)], "half_width": round((hi - lo) / 2, 4),
            "map_match": x["map_match"], "analyzable": n >= MIN_N and x["map_match"] == "same",
            "in_379": x["in_379"], "in_394": x["in_379"] or L in added, "bot_measured": L in bot_L,
            "exclusion": x["exclusion_reason"], "help_rate": x["help_rate"], "noend_rate": x["noend_rate"],
            "combo": TR.combo_key(gims) if mf else None, "has_bomb": "bomb" in gims, "map_source": maps.get(L, (0, None))[1],
            "gimmick_first": bool(lm.get("is_gimmick_first")), "is_boss": bool(lm.get("is_boss")),
            "version_z": version_z(x["clean_ft_by_version"] or {}),
            "ver_n": {k2: v["n"] for k2, v in (x["clean_ft_by_version"] or {}).items()},
            "place": next(s for s, l0, h0 in PLACE if l0 <= L <= h0)})
    out = {"bands": {}, "levels_lt085_analyzable": [], "note": "ft_any = first-try clear incl. help, no_end excluded; "
           "Wilson on k=round(ft_any·n), n = first-try ended; analyzable = n ≥ 100 ∧ map_match == same"}
    for nm, lo, hi in BANDS:
        B = [r for r in recs if lo <= r["ft_any"] < hi]
        A = [r for r in B if r["analyzable"]]
        hw = sorted(r["half_width"] for r in A)
        vz = [r["version_z"] for r in A if r["version_z"] is not None]
        vn = Counter()
        for r in A:
            vn.update(r["ver_n"])
        tot_vn = sum(vn.values()) or 1
        excl = Counter(("in_394" if r["in_394"] else (r["exclusion"] or "none")) for r in A)
        out["bands"][nm] = {
            "levels_observed": len(B), "first_try_n_sum_observed": sum(r["n"] for r in B),
            "first_try_n_median_observed": sorted(r["n"] for r in B)[len(B) // 2] if B else None,
            "map_match_observed": dict(Counter(r["map_match"] for r in B)),
            "not_analyzable": {"n_lt_100": sum(r["n"] < MIN_N for r in B),
                               "map_not_same_n_ge_100": sum(r["n"] >= MIN_N and r["map_match"] != "same" for r in B)},
            "analyzable": len(A),
            "analyzable_first_try_n": {"min": min((r["n"] for r in A), default=None),
                                       "median": sorted(r["n"] for r in A)[len(A) // 2] if A else None,
                                       "max": max((r["n"] for r in A), default=None)},
            "analyzable_wilson_half_width": {"median": hw[len(hw) // 2] if hw else None, "max": hw[-1] if hw else None},
            "analyzable_wilson_upper_lt_band_hi": sum(r["wilson"][1] < hi for r in A),
            "analyzable_wilson_upper_lt_085": sum(r["wilson"][1] < 0.85 for r in A),
            "analyzable_by_place": dict(Counter(r["place"] for r in A)),
            "analyzable_in_379": sum(r["in_379"] for r in A), "analyzable_in_394": sum(r["in_394"] for r in A),
            "analyzable_bot_measured": sum(r["bot_measured"] for r in A),
            "analyzable_inclusion": dict(excl),
            "analyzable_has_bomb_share": round(sum(r["has_bomb"] for r in A) / len(A), 3) if A else None,
            "analyzable_gimmick_first_share": round(sum(r["gimmick_first"] for r in A) / len(A), 3) if A else None,
            "analyzable_top_combos": Counter(r["combo"] for r in A).most_common(5),
            "analyzable_help_rate_mean": round(sum(r["help_rate"] or 0 for r in A) / len(A), 4) if A else None,
            "analyzable_version_share": {k2: round(v / tot_vn, 3) for k2, v in sorted(vn.items())},
            "analyzable_version_abs_z_gt_1_96": sum(abs(z) > 1.96 for z in vz), "analyzable_version_z_n": len(vz),
            "analyzable_levels": [r["L"] for r in sorted(A, key=lambda r: r["ft_any"])] if hi <= 0.85 else None,
        }
    out["levels_lt085_analyzable"] = [r for r in sorted(recs, key=lambda r: r["ft_any"]) if r["analyzable"] and r["ft_any"] < 0.85]
    save(OUT / "support.json", out)
    (OUT / "support.md").write_text(render_support(out), encoding="utf-8")
    log("saved", OUT / "support.json")


def render_support(o):
    B = o["bands"]
    names = list(B)
    row = lambda title, f: f"| {title} | " + " | ".join(str(f(B[n])) for n in names) + " |"
    L = ["| 항목 | " + " | ".join(names) + " |", "|---|" + "---|" * len(names),
         row("관측 레벨(n 무관)", lambda b: b["levels_observed"]),
         row("관측 첫시도 n 합 / 중앙값", lambda b: f"{b['first_try_n_sum_observed']} / {b['first_try_n_median_observed']}"),
         row("분석 불가: n<100 / 맵 불일치", lambda b: f"{b['not_analyzable']['n_lt_100']} / {b['not_analyzable']['map_not_same_n_ge_100']}"),
         row("**분석 가능**(n≥100·맵 same)", lambda b: f"**{b['analyzable']}**"),
         row("분석 가능 n 최소/중앙/최대", lambda b: "{min}/{median}/{max}".format(**b["analyzable_first_try_n"])),
         row("Wilson 95% 반폭 중앙/최대", lambda b: "{median}/{max}".format(**b["analyzable_wilson_half_width"])),
         row("Wilson 상한 < 구간 상단", lambda b: b["analyzable_wilson_upper_lt_band_hi"]),
         row("Wilson 상한 < 0.85", lambda b: b["analyzable_wilson_upper_lt_085"]),
         row("379 포함 / 394 포함", lambda b: f"{b['analyzable_in_379']} / {b['analyzable_in_394']}"),
         row("봇 v2.4 측정 있음", lambda b: b["analyzable_bot_measured"]),
         row("394 밖 사유", lambda b: ", ".join(f"{k}:{v}" for k, v in b["analyzable_inclusion"].items() if k != "in_394") or "-"),
         row("배치 구간", lambda b: ", ".join(f"{k}:{v}" for k, v in sorted(b["analyzable_by_place"].items()))),
         row("폭탄 포함 비율", lambda b: b["analyzable_has_bomb_share"]),
         row("기믹 첫 등장 비율", lambda b: b["analyzable_gimmick_first_share"]),
         row("도움 사용률 평균", lambda b: b["analyzable_help_rate_mean"]),
         row("버전 n 비중(1.0.162/1.1.0/ios)", lambda b: "/".join(str(v) for v in b["analyzable_version_share"].values())),
         row("버전 |z|>1.96 / z 계산 레벨", lambda b: f"{b['analyzable_version_abs_z_gt_1_96']} / {b['analyzable_version_z_n']}")]
    return "\n".join(L) + "\n"


# ── §2–3 candidates (doc 36 §2–3, pre-registered in 2e50e13) ────────────────────────────────────
X_EXTRA = ["bomb_x_novelty", "weak_x_bot"]
CONFIGS_DEV = {"base": {"kind": "base"}, "W1": {"kind": "W", "alpha": 1.0}, "W3": {"kind": "W", "alpha": 3.0},
               "X": {"kind": "X"}, "Sfull": {"kind": "S", "half": False}, "Shalf": {"kind": "S", "half": True}}
SEAL_SEED, SEAL_FRAC = 20261016, 0.2
STRATA = ((-9, 0.85), (0.85, 0.96), (0.96, 9))
ACT = (("lt0.50", -9, 0.50), ("0.50-0.70", 0.50, 0.70), ("0.70-0.85", 0.70, 0.85), ("lt0.85", -9, 0.85),
       ("0.85-0.92", 0.85, 0.92), ("0.92-0.96", 0.92, 0.96), ("ge0.95", 0.95, 9), ("ge0.96", 0.96, 9))
PBINS = ((0.0, 0.88), (0.88, 0.92), (0.92, 0.95), (0.95, 0.97), (0.97, 1.01))
SEGS = (("32-100", 32, 100), ("101-300", 101, 300), ("301-500", 301, 500), ("501+", 501, 10 ** 6))
BOOT = 2000
# guard.py constants (app.core.clear_rate.guard — copied: that module imports the app package)
LOW_CONF_BELOW, NOVELTY_HIGH, ZONE_LOW_MAE, ZONE_LOW_COV, ZONE_MID_MAE, COMBO_FEW_LT, COMBO_MAE_GE = \
    0.85, 0.5, 0.045, 0.75, 0.035, 5, 0.05


def _np():
    import numpy as np
    return np


class WRidge:
    """residual_model.Ridge with per-row weights (weighted LS; inner λ CV error weighted the same way)."""
    GRID = (0.3, 1, 3, 10, 30, 100, 300)

    def __init__(self, feats, w):
        self.feats, self.w_row = feats, w

    def fit(self, X, y, cols):
        np, rm = _np(), CA.tr().rm
        idx = [cols.index(c) for c in self.feats]
        Xf = X[:, idx]
        self.idx = idx
        self.mu, self.sd = Xf.mean(0), Xf.std(0)
        self.sd[self.sd < 1e-9] = 1
        Xs = (Xf - self.mu) / self.sd
        w = self.w_row

        def solve(A_, y_, w_, lam):
            n, p = A_.shape
            A = np.hstack([np.ones((n, 1)), A_])
            R = lam * np.eye(p + 1)
            R[0, 0] = 0
            Aw = A * w_[:, None]
            return np.linalg.solve(A.T @ Aw + R, Aw.T @ y_)

        fold = np.random.RandomState(7).permutation(len(y)) % 5
        err = []
        for l in self.GRID:
            e = 0
            for k in range(5):
                tr_, te = fold != k, fold == k
                b = solve(Xs[tr_], y[tr_], w[tr_], l)
                e += (w[te] * np.abs(rm.expit(b[0] + Xs[te] @ b[1:]) - rm.expit(y[te]))).sum()
            err.append(e)
        self.lam_used = self.GRID[int(np.argmin(err))]
        self.w = solve(Xs, y, w, self.lam_used)
        return self

    def predict(self, X, cols):
        return self.w[0] + ((X[:, self.idx] - self.mu) / self.sd) @ self.w[1:]


def make_wgbm(feats, w):
    rm = CA.tr().rm

    class WGBM(rm.GBM):
        """residual_model.GBM, squared loss with row weights: split gain and leaf value use weighted sums.
        With w ≡ 1 it is the same model (checked in cmd_eval)."""

        def _best_split_w(self, X, r, w, cols):
            np = _np()
            n = len(r)
            if n < 2 * self.min_leaf:
                return None
            Xc = X[:, cols]
            order = Xc.argsort(axis=0, kind="mergesort")
            xs = np.take_along_axis(Xc, order, 0)
            wr, ww = (w * r)[order], w[order]
            cs, cw = wr.cumsum(0)[:-1], ww.cumsum(0)[:-1]
            tot, W = float((w * r).sum()), float(w.sum())
            nl = np.arange(1, n)[:, None]
            nr = n - nl
            gain = cs ** 2 / cw + (tot - cs) ** 2 / (W - cw) - tot ** 2 / W
            valid = (xs[1:] > xs[:-1]) & (nl >= self.min_leaf) & (nr >= self.min_leaf)
            gain = np.where(valid, gain, -np.inf)
            k = np.unravel_index(np.argmax(gain), gain.shape)
            if not np.isfinite(gain[k]) or gain[k] <= 1e-12:
                return None
            j = cols[k[1]]
            return j, (xs[k[0], k[1]] + xs[k[0] + 1, k[1]]) / 2, float(gain[k])

        def _grow_w(self, X, r, w, depth, cols):
            sp = self._best_split_w(X, r, w, cols) if depth < self.depth else None
            if sp is None:
                return ("leaf", float((w * r).sum() / w.sum()))
            j, thr, gain = sp
            self.gain[j] += gain
            m = X[:, j] <= thr
            return ("node", j, thr, self._grow_w(X[m], r[m], w[m], depth + 1, cols),
                    self._grow_w(X[~m], r[~m], w[~m], depth + 1, cols))

        def fit(self, X, y, cols):
            np = _np()
            self.idx = [cols.index(c) for c in self.feats]
            Xf = X[:, self.idx]
            rng = np.random.RandomState(self.seed)
            self.base = float((w * y).sum() / w.sum())
            self.gain = np.zeros(len(self.idx))
            F = np.full(len(y), self.base)
            self.trees = []
            p = len(self.idx)
            for _ in range(self.n_est):
                rows = rng.rand(len(y)) < self.subsample
                cs = sorted(rng.choice(p, max(1, int(p * self.colsample)), replace=False))
                t = self._grow_w(Xf[rows], (y - F)[rows], w[rows], 0, cs)
                self.trees.append(t)
                F += self.lr * self._pred_tree(t, Xf)
            return self

    return WGBM(feats)


def augment(X):
    np, F = _np(), CA.tr().FEATS
    c = {f: i for i, f in enumerate(F)}
    bxn = X[:, c["bomb_sum"]] * X[:, c["novelty"]]
    wk = np.maximum(X[:, c["has_grass"]], X[:, c["has_chain"]]) * X[:, c["lg065"]]
    return np.hstack([X, bxn[:, None], wk[:, None]])


def fit_ab(z, y, half):
    """p' = expit(a + b·z): least squares in probability space on a fixed grid (doc 36 §2-1 S)."""
    np, rm = _np(), CA.tr().rm
    A = np.round(np.arange(-1.50, 1.5001, 0.01), 2)
    Bs = np.round(np.arange(0.50, 2.5001, 0.01), 2)
    best = None
    for b in Bs:
        sse = ((rm.expit(A[:, None] + b * z[None, :]) - y[None, :]) ** 2).sum(1)
        i = int(np.argmin(sse))
        if best is None or sse[i] < best[0]:
            best = (float(sse[i]), float(A[i]), float(b))
    a, b = best[1], best[2]
    if half:
        b = 1 + (b - 1) / 2
        sse = ((rm.expit(A[:, None] + b * z[None, :]) - y[None, :]) ** 2).sum(1)
        a = float(A[int(np.argmin(sse))])
    return a, b


def fit_point(cfg, X, y, act, groups, seedkey):
    """→ predictor X ↦ logit. y = clipped-logit target (train_clear_rate_model.ytarget), act = actual ft_any."""
    np, TR = _np(), CA.tr()
    F, rm = TR.FEATS, TR.rm
    kind = cfg["kind"]
    if kind == "base":
        m = TR.point_model().fit(X, y, F)
        return lambda Z: m.predict(Z, F), {}
    if kind == "W":
        w = 1.0 + cfg["alpha"] * (act < 0.85)
        w = w / w.mean()
        R = WRidge(F, w).fit(X, y, F)
        G = make_wgbm(F, w).fit(X, y, F)
        return lambda Z: np.mean([R.predict(Z, F), G.predict(Z, F)], axis=0), {"lam": R.lam_used}
    if kind == "X":
        F2 = F + X_EXTRA
        m = rm.Blend(rm.Ridge(F2), rm.GBM(F2)).fit(augment(X), y, F2)
        return lambda Z: m.predict(augment(Z), F2), {}
    if kind == "S":
        m = TR.point_model().fit(X, y, F)
        ug = sorted(set(groups))
        perm = np.random.RandomState(seedkey).permutation(len(ug))
        gf = {g: int(perm[i]) % 5 for i, g in enumerate(ug)}
        inner = np.array([gf[g] for g in groups])
        z = np.zeros(len(y))
        for j in range(5):
            a_, b_ = inner != j, inner == j
            z[b_] = TR.point_model().fit(X[a_], y[a_], F).predict(X[b_], F)
        a, b = fit_ab(z, act, cfg["half"])
        return lambda Z: a + b * m.predict(Z, F), {"a": a, "b": b}
    raise ValueError(kind)


class Data:
    def __init__(self):
        np = _np()
        D = CA.dataset()
        self.base, self.add = D["rows"], [D["add"][L] for L in CA.A1 + CA.A2]
        self.rows = self.base + self.add
        self.n0, self.n = len(self.base), len(self.rows)
        self.X = np.vstack([D["X"], np.array([r["x"] for r in self.add])])
        self.TR = CA.tr()
        self.Y = self.TR.ytarget(self.rows, "ft_any")
        self.act = np.array([r["ft_any"] for r in self.rows])
        self.L = np.array([r["L"] for r in self.rows])
        self.groups = np.array([r["maphash"] for r in self.rows])
        assert len(set(self.groups)) == self.n, "a map group holds more than one level — sealing assumes 1:1"
        self.in_data = {"D379": np.arange(self.n) < self.n0, "D394": np.ones(self.n, bool)}
        F = self.TR.FEATS
        self.fc = {f: i for i, f in enumerate(F)}
        self.combo = np.array([self.TR.combo_key(r["gims"]) for r in self.rows])
        self.sealed = self._seal()

    def _seal(self):
        np = _np()
        sealed = np.zeros(self.n, bool)
        rng = np.random.RandomState(SEAL_SEED)
        for lo, hi in STRATA:
            g = sorted(self.groups[(self.act >= lo) & (self.act < hi)])
            k = int(round(SEAL_FRAC * len(g)))
            pick = set(np.array(g)[rng.permutation(len(g))[:k]])
            sealed |= np.isin(self.groups, list(pick))
        return sealed

    def folds(self, rep, setting):
        np = _np()
        f0 = self.TR.kfolds(self.base, rep)
        if setting == "S1":
            return np.concatenate([f0, np.full(len(self.add), -1)])
        return CA.folds_for(self.TR, self.base, self.add, rep, "S2")


def oof_cv(D, cfg, data, setting, log_tag):
    """Repeat-OOF logits → probabilities for every row that is ever tested (S1: 379, S2: 394)."""
    np = _np()
    out = np.full((D.TR.REPS, D.n), np.nan)
    extra = []
    for rep in range(D.TR.REPS):
        folds = D.folds(rep, setting)
        for k in range(D.TR.K):
            trn = (folds != k) & D.in_data[data]
            te = folds == k
            f, info = fit_point(cfg, D.X[trn], D.Y[trn], D.act[trn], D.groups[trn], 500 + 10 * rep + k)
            out[rep, te] = D.TR.rm.expit(f(D.X[te]))
            extra.append(info)
        log(f"  {log_tag} rep {rep + 1}/{D.TR.REPS}")
    return out, extra


_CQR = {}


def cqr(D, data, setting):
    """rep-0 CQR range (train_clear_rate_model procedure); depends only on the training data, not the method."""
    np = _np()
    key = (data, setting)
    if key not in _CQR:
        folds = D.folds(0, setting)
        lo_, hi_ = np.full(D.n, np.nan), np.full(D.n, np.nan)
        for k in range(D.TR.K):
            te = folds == k
            trn = (folds != k) & D.in_data[data]
            lo, hi = D.TR.qpredict(*D.TR.quant_pair(D.X[trn], D.Y[trn]), D.X[te])
            w = D.TR.cqr_width(D.X, D.Y, np.where(trn)[0], seed=k)
            lo_[te], hi_[te] = lo - w, hi + w
            log(f"  CQR {data} {setting} fold {k}: width {w:+.3f}")
        pr = [D.TR.MD.range_to_prob(a, b) if a == a else (np.nan, np.nan) for a, b in zip(lo_, hi_)]
        _CQR[key] = (np.array([v[0] for v in pr]), np.array([v[1] for v in pr]))
    return _CQR[key]


def masks(D, idx, pm):
    np = _np()
    y, L = D.act[idx], D.L[idx]
    m = {"all": np.ones(len(idx), bool)}
    for nm, lo, hi in ACT:
        m["act_" + nm] = (y >= lo) & (y < hi)
    for lo, hi in PBINS:
        m[f"pred_{lo:.2f}-{min(hi, 1.0):.2f}"] = (pm >= lo) & (pm < hi)
    for nm, lo, hi in SEGS:
        m["seg_" + nm] = (L >= lo) & (L <= hi)
    return m


def stats(y, p, plo=None, phi=None):
    np, rm = _np(), CA.tr().rm
    e = p - y
    s = {"n": int(len(y))}
    if not len(y):
        return s
    s.update(mae=float(np.abs(e).mean()), bias=float(e.mean()), hit05=float((np.abs(e) <= 0.05).mean()),
             big10=float((np.abs(e) > 0.10).mean()), big10_n=int((np.abs(e) > 0.10).sum()))
    if len(y) >= 3:
        s["rho"] = rm.spearman(p, y)
        s["slope"] = float(np.polyfit(y, e, 1)[0])
    if plo is not None:
        s["cov80"] = float(((y >= plo) & (y <= phi)).mean())
        s["width_mean"], s["width_median"] = float((phi - plo).mean()), float(np.median(phi - plo))
        s["point_inside"] = float(((p >= plo) & (p <= phi)).mean())
    return s


def confidence(D, idx, pm, plo, phi):
    """guard.confidence on each evaluated level, with the variant's own OOF reliability tables (as served)."""
    np = _np()
    rows = [D.rows[i] for i in idx]
    y = D.act[idx]
    rel = D.TR.reliability_tables(rows, pm, y, plo, phi)
    X = D.X[idx]
    c = D.fc
    out = []
    for i in range(len(idx)):
        codes = set()
        p = pm[i]
        if p < LOW_CONF_BELOW:
            codes.add("LOW_CONFIDENCE")
        if X[i, c["gimmick_first"]] >= 1:
            codes.add("GIMMICK_FIRST")
        elif X[i, c["novelty"]] > NOVELTY_HIGH:
            codes.add("NOVELTY_HIGH")
        if X[i, c["has_grass"]] >= 1 or X[i, c["has_chain"]] >= 1:
            codes.add("GIMMICK_BOT_WEAK")
        z = next((b for b in rel["pred_bins"] if b["lo"] <= p < b["hi"] or (b["hi"] >= 1.0 and p >= b["lo"])), None)
        if z:
            if z["mae"] >= ZONE_LOW_MAE or z["coverage80"] < ZONE_LOW_COV:
                codes.add("PRED_ZONE_HIGH_ERROR")
            elif z["mae"] >= ZONE_MID_MAE:
                codes.add("PRED_ZONE_MID_ERROR")
        cb = rel["combo"].get(D.combo[idx[i]], {"n": 0})
        if cb["n"] < COMBO_FEW_LT:
            codes.add("SIMILAR_MAPS_FEW")
        elif cb["mae"] >= COMBO_MAE_GE:
            codes.add("COMBO_HIGH_ERROR")
        if codes & {"LOW_CONFIDENCE", "GIMMICK_FIRST", "NOVELTY_HIGH", "PRED_ZONE_HIGH_ERROR", "SIMILAR_MAPS_FEW",
                    "COMBO_HIGH_ERROR"}:
            out.append("low")
        elif codes & {"GIMMICK_BOT_WEAK", "PRED_ZONE_MID_ERROR"}:
            out.append("medium")
        else:
            out.append("high")
    ok = np.array([v != "low" for v in out])
    s = stats(y[ok], pm[ok])
    s["levels_pass"] = int(ok.sum())
    s["by_conf"] = dict(Counter(out))
    s["pass_actual_lt085"] = int((ok & (y < 0.85)).sum())
    s["pass_actual_lt085_bias"] = float((pm[ok & (y < 0.85)] - y[ok & (y < 0.85)]).mean()) if (ok & (y < 0.85)).any() else None
    return s


def summarize(D, oof, idx, plo, phi):
    np = _np()
    idx = np.asarray(idx)
    y, pm = D.act[idx], np.nanmean(oof[:, idx], 0)
    out = {}
    for nm, mk in masks(D, idx, pm).items():
        if not mk.any():
            continue
        s = stats(y[mk], pm[mk], plo[idx][mk], phi[idx][mk])
        reps = [stats(y[mk], oof[r, idx][mk]) for r in range(oof.shape[0])]
        s["sd"] = {k: float(np.std([r[k] for r in reps])) for k in ("mae", "bias", "rho", "slope") if k in reps[0]}
        s["mae_rep_mean"] = float(np.mean([r["mae"] for r in reps]))
        out[nm] = s
    out["confidence"] = confidence(D, idx, pm, plo[idx], phi[idx])
    return out


def boot(D, oof_b, oof_c, idx, cov_b=None, cov_c=None, seed=12345):
    np, rm = _np(), CA.tr().rm
    idx = np.asarray(idx)
    rng = np.random.RandomState(seed)
    y = D.act[idx]
    pb, pc = np.nanmean(oof_b[:, idx], 0), np.nanmean(oof_c[:, idx], 0)
    mk = masks(D, idx, pb)  # pred bins on B0 prediction — only the actual/segment masks are used below
    keys = [k for k in mk if not k.startswith("pred_") and mk[k].any()]
    out = {f"{k}|{m}": [] for k in keys for m in ("mae", "bias", "big10")}
    out.update({"all|rho": [], "all|slope": [], "all|cov80": []})
    n = len(idx)
    for _ in range(BOOT):
        b = rng.randint(0, n, n)
        eb, ec = pb[b] - y[b], pc[b] - y[b]
        for k in keys:
            s = mk[k][b]
            if not s.any():
                continue
            out[f"{k}|mae"].append(np.abs(ec[s]).mean() - np.abs(eb[s]).mean())
            out[f"{k}|bias"].append(ec[s].mean() - eb[s].mean())
            out[f"{k}|big10"].append((np.abs(ec[s]) > .1).mean() - (np.abs(eb[s]) > .1).mean())
        out["all|rho"].append(rm.spearman(pc[b], y[b]) - rm.spearman(pb[b], y[b]))
        out["all|slope"].append(np.polyfit(y[b], ec, 1)[0] - np.polyfit(y[b], eb, 1)[0])
        if cov_b is not None:
            out["all|cov80"].append(cov_c[b].mean() - cov_b[b].mean())
    return {k: [round(float(np.percentile(v, 2.5)), 4), round(float(np.percentile(v, 97.5)), 4)] for k, v in out.items() if v}


def dev_oof(D, cfg, tag):
    """Tuning OOF on the development set (D394 − sealed): map-group 5-fold × 4, RandomState(300+rep)."""
    np = _np()
    dev = np.where(~D.sealed)[0]
    out = np.full((D.TR.REPS, len(dev)), np.nan)
    infos = []
    for rep in range(D.TR.REPS):
        g = sorted(set(D.groups[dev]))
        gp = {h: i % D.TR.K for i, h in enumerate(np.random.RandomState(300 + rep).permutation(g))}
        folds = np.array([gp[h] for h in D.groups[dev]])
        for k in range(D.TR.K):
            a_, b_ = dev[folds != k], dev[folds == k]
            f, info = fit_point(cfg, D.X[a_], D.Y[a_], D.act[a_], D.groups[a_], 500 + 10 * rep + k)
            out[rep, folds == k] = D.TR.rm.expit(f(D.X[b_]))
            infos.append(info)
        log(f"  dev {tag} rep {rep + 1}")
    pm, y = out.mean(0), D.act[dev]
    s = {}
    for nm, lo, hi in (("all", -9, 9), ("lt0.85", -9, 0.85), ("ge0.96", 0.96, 9)):
        mk = (y >= lo) & (y < hi)
        s[nm] = stats(y[mk], pm[mk])
    s["fit_info"] = infos
    return s


def sealed_fit(D, cfg, data):
    np = _np()
    trn = ~D.sealed & D.in_data[data]
    f, info = fit_point(cfg, D.X[trn], D.Y[trn], D.act[trn], D.groups[trn], 999)
    p = np.full(D.n, np.nan)
    p[D.sealed] = D.TR.rm.expit(f(D.X[D.sealed]))
    return p, info


def sealed_summary(D, p, pb):
    np = _np()
    idx = np.where(D.sealed)[0]
    y = D.act[idx]
    out = {}
    for nm, lo, hi in (("all", -9, 9), ("lt0.85", -9, 0.85), ("0.85-0.96", 0.85, 0.96), ("ge0.96", 0.96, 9)):
        mk = (y >= lo) & (y < hi)
        s = stats(y[mk], p[idx][mk])
        sb = stats(y[mk], pb[idx][mk])
        s["d_mae"], s["d_bias"] = s["mae"] - sb["mae"], s["bias"] - sb["bias"]
        rng = np.random.RandomState(4242)
        dm, db = [], []
        e, eb = p[idx][mk] - y[mk], pb[idx][mk] - y[mk]
        for _ in range(BOOT):
            b = rng.randint(0, mk.sum(), mk.sum())
            dm.append(np.abs(e[b]).mean() - np.abs(eb[b]).mean())
            db.append(e[b].mean() - eb[b].mean())
        s["ci_d_mae"] = [round(float(np.percentile(dm, 2.5)), 4), round(float(np.percentile(dm, 97.5)), 4)]
        s["ci_d_bias"] = [round(float(np.percentile(db, 2.5)), 4), round(float(np.percentile(db, 97.5)), 4)]
        out[nm] = s
    return out


def pick(dev_res, names):
    """doc 36 §2-3: allowed = dev ≥0.96 ΔMAE ≤ +0.0010 vs dev base; min dev <0.85 Δbias among allowed, else min ≥0.96 ΔMAE."""
    b = dev_res["base"]
    d = {n: {"d_ge096_mae": dev_res[n]["ge0.96"]["mae"] - b["ge0.96"]["mae"],
             "d_lt085_bias": dev_res[n]["lt0.85"]["bias"] - b["lt0.85"]["bias"]} for n in names}
    ok = [n for n in names if d[n]["d_ge096_mae"] <= 0.0010]
    ch = min(ok, key=lambda n: d[n]["d_lt085_bias"]) if ok else min(names, key=lambda n: d[n]["d_ge096_mae"])
    return ch, d


def judge(D, sb, sc, ci, seal):
    j = CA.judge(sb, sc, ci)
    lt = seal["lt0.85"]
    if lt["n"] < 10:
        k5, why = None, "sealed <0.85 n < 10"
    else:
        k5 = bool(lt["d_bias"] < 0 and seal["ge0.96"]["d_mae"] <= 0.0010 and seal["all"]["d_mae"] <= 0.0010)
        why = ""
    j["K5"], j["K5_note"] = k5, why
    if j["verdict"] == "채택 권고" and not k5:
        j["verdict"] = "보류"
    j["verdict_K1_K4_only"] = CA.judge(sb, sc, ci)["verdict"]
    return j


def cmd_eval(a):
    np = _np()
    D = Data()
    TR = D.TR
    res = {"prereg_commit": "2e50e13", "n379": D.n0, "n394": D.n, "sealed": {
        "levels": sorted(int(L) for L in D.L[D.sealed]), "n": int(D.sealed.sum()),
        "lt085": int((D.sealed & (D.act < 0.85)).sum()), "ge096": int((D.sealed & (D.act >= 0.96)).sum()),
        "added_levels_sealed": sorted(int(L) for L in D.L[D.sealed] if L in set(CA.A1 + CA.A2))}}
    log("sealed", res["sealed"])

    # sanity: weighted model with w ≡ 1 is the base model
    trn = np.arange(D.n0)[:200]
    f0, _ = fit_point({"kind": "base"}, D.X[trn], D.Y[trn], D.act[trn], D.groups[trn], 0)
    f1, _ = fit_point({"kind": "W", "alpha": 0.0}, D.X[trn], D.Y[trn], D.act[trn], D.groups[trn], 0)
    dmax = float(np.abs(f0(D.X) - f1(D.X)).max())
    assert dmax < 1e-9, f"W(α=0) differs from base by {dmax}"
    res["check_W_alpha0_equals_base"] = dmax
    log(f"W(α=0) == base (max |Δlogit| {dmax:.1e})")

    # 1) tuning on the development set
    dev = {}
    for nm, cfg in CONFIGS_DEV.items():
        dev[nm] = dev_oof(D, cfg, nm)
        log(f"dev {nm}: lt0.85 bias {dev[nm]['lt0.85']['bias']:+.4f} ge0.96 MAE {dev[nm]['ge0.96']['mae']:.4f}")
    chW, dW = pick(dev, ["W1", "W3"])
    chS, dS = pick(dev, ["Sfull", "Shalf"])
    res["dev"] = {k: {m: v for m, v in s.items() if m != "fit_info"} for k, s in dev.items()}
    res["dev_fit_info_S"] = {k: dev[k]["fit_info"] for k in ("Sfull", "Shalf")}
    res["tuning"] = {"W": {"chosen": chW, "deltas": dW}, "S": {"chosen": chS, "deltas": dS}}
    log("tuning chose", chW, chS)
    finals = {"W": CONFIGS_DEV[chW], "X": CONFIGS_DEV["X"], "S": CONFIGS_DEV[chS]}

    # 2) main comparison S1 (eval 379) + S2 (eval 394)
    variants = {"B0": ("base", "D379"), "C2": ("base", "D394")}
    for c in finals:
        for d in ("D379", "D394"):
            variants[f"{c}-{d}"] = (c, d)
    cfg_of = lambda c: {"kind": "base"} if c == "base" else finals[c]
    OOF, res["S1"], res["S2"], res["fit_info"] = {}, {}, {}, {}
    for v, (c, d) in variants.items():
        for st in ("S1", "S2"):
            OOF[(v, st)], info = oof_cv(D, cfg_of(c), d, st, f"{v} {st}")
            plo, phi = cqr(D, d, st)
            idx = list(range(D.n0)) if st == "S1" else list(range(D.n))
            res[st][v] = {"eval": summarize(D, OOF[(v, st)], idx, plo, phi)}
            if st == "S2":
                res[st][v]["eval_added"] = summarize(D, OOF[(v, st)], list(range(D.n0, D.n)), plo, phi)
            if st == "S1":
                res["fit_info"][v] = info
            log(f"{v} {st}: MAE {res[st][v]['eval']['all']['mae']:.4f} lt0.85 bias {res[st][v]['eval']['act_lt0.85']['bias']:+.4f}")
        if v == "B0":
            man = CA.load(TR.MODELS / TR.DEFAULT_VERSION / "manifest.json")["kfold"]
            b = res["S1"]["B0"]["eval"]["all"]
            res["B0_reproduces_manifest"] = [b["mae_rep_mean"], man["ft_any"]["mae"], b["cov80"], man["ft_any_range80"]["coverage"]]
            assert abs(b["mae_rep_mean"] - man["ft_any"]["mae"]) < 1e-4 and abs(b["cov80"] - man["ft_any_range80"]["coverage"]) < 1e-3, \
                res["B0_reproduces_manifest"]
            log("B0 reproduces the active model manifest", res["B0_reproduces_manifest"])

    # 3) sealed
    res["sealed_eval"] = {}
    SP = {}
    for v, (c, d) in variants.items():
        SP[v], info = sealed_fit(D, cfg_of(c), d)
        log(f"sealed fit {v} {info}")
    for v in variants:
        res["sealed_eval"][v] = sealed_summary(D, SP[v], SP["B0"])

    # 4) bootstrap + verdicts (vs B0)
    res["boot_S1"], res["boot_S2"], res["judge"] = {}, {}, {}
    plo1, phi1 = cqr(D, "D379", "S1")
    for v, (c, d) in variants.items():
        if v == "B0":
            continue
        plo, phi = cqr(D, d, "S1")
        y = D.act[:D.n0]
        cb = (y >= plo1[:D.n0]) & (y <= phi1[:D.n0])
        cc = (y >= plo[:D.n0]) & (y <= phi[:D.n0])
        ci = boot(D, OOF[("B0", "S1")], OOF[(v, "S1")], list(range(D.n0)), cb, cc)
        res["boot_S1"][v] = ci
        res["boot_S2"][v] = boot(D, OOF[("B0", "S2")], OOF[(v, "S2")], list(range(D.n)))
        res["judge"][v] = judge(D, res["S1"]["B0"]["eval"], res["S1"][v]["eval"], ci, res["sealed_eval"][v])
        log(v, {k: res["judge"][v][k] for k in ("K1", "K2", "K3", "K4", "K5", "verdict")})
    # C2 must reproduce doc 33 §12-3 (same data, same method, same folds)
    c2 = CA.load(CA.OUT / "compare.json")["S1"]["C2"]["eval379"]
    res["C2_reproduces_doc33"] = [res["S1"]["C2"]["eval"]["all"]["mae"], c2["all"]["mae"],
                                  res["S1"]["C2"]["eval"]["act_lt0.85"]["bias"], c2["act_lt0.85"]["bias"]]
    assert abs(res["C2_reproduces_doc33"][0] - c2["all"]["mae"]) < 1e-4 and \
        abs(res["C2_reproduces_doc33"][2] - c2["act_lt0.85"]["bias"]) < 1e-4, res["C2_reproduces_doc33"]
    log("C2 reproduces doc 33 §12-3", res["C2_reproduces_doc33"])
    save(OUT / "compare.json", res)
    log("saved", OUT / "compare.json")


Z90 = 1.2815515655446004  # select.py (10%/90% points of a normal)


def p_in_band(expected, rng, band):
    """app.core.clear_rate.select.p_in_band, copied (that module imports the app package)."""
    lg = lambda p: math.log(min(max(p, 1e-6), 1 - 1e-6) / (1 - min(max(p, 1e-6), 1 - 1e-6)))
    phi = lambda x: 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))
    mu = lg(expected)
    lo, hi = rng
    s_lo = (mu - lg(lo)) / Z90 if 0 < lo < expected else None
    s_hi = (lg(hi) - mu) / Z90 if expected < hi < 1 else None
    s_lo = s_lo or s_hi or 1e-6
    s_hi = s_hi or s_lo
    w = s_lo / (s_lo + s_hi)

    def cdf(p):
        if p <= 0:
            return 0.0
        if p >= 1:
            return 1.0
        x = lg(p)
        return 2 * w * phi((x - mu) / s_lo) if x <= mu else w + 2 * (1 - w) * (phi((x - mu) / s_hi) - 0.5)
    return max(0.0, min(1.0, cdf(band[1]) - cdf(band[0])))


def cmd_addenda(a):
    """Post-result diagnostics requested after the run (mother, doc 33 §15 findings). Report only — not part of
    the pre-registered verdict, no criterion changed. Re-runs the S1 OOF (deterministic; checked against
    compare.json) because per-level OOF were not stored."""
    np = _np()
    D = Data()
    TR, rm = D.TR, D.TR.rm
    r = CA.load(OUT / "compare.json")
    clip_hi, clip_lo = float(rm.logit(np.array([0.99]))[0]), float(rm.logit(np.array([0.01]))[0])
    res = {"note": "post-hoc diagnostics (doc 36 §5), not a verdict input", "quantile_heads": {}, "coverage_pre_post": {},
           "a85": {}}
    # (1) quantile-head degeneracy: full-data fit and rep-0 S1 fold fits, raw logit outputs on all 394 rows
    for d in ("D379", "D394"):
        m = D.in_data[d]
        lo_m, hi_m = TR.quant_pair(D.X[m], D.Y[m])
        a_, b_ = lo_m.predict(D.X, TR.FEATS), hi_m.predict(D.X, TR.FEATS)
        folds = D.folds(0, "S1")
        fq = []
        for k in range(TR.K):
            trn = (folds != k) & m
            l2, h2 = TR.quant_pair(D.X[trn], D.Y[trn])
            hk = h2.predict(D.X[folds == k], TR.FEATS)
            fq.append({"fold": k, "q_hi_base": round(h2.base, 4), "q_hi_min": round(float(hk.min()), 4),
                       "q_hi_max": round(float(hk.max()), 4), "q_hi_at_clip_share": round(float((hk >= clip_hi - 1e-9).mean()), 3)})
        res["quantile_heads"][d] = {
            "full_fit": {"q_hi_base": round(hi_m.base, 4), "q_hi_min": round(float(b_.min()), 4), "q_hi_max": round(float(b_.max()), 4),
                         "q_hi_at_clip_share": round(float((b_ >= clip_hi - 1e-9).mean()), 3),
                         "q_lo_base": round(lo_m.base, 4), "q_lo_min": round(float(a_.min()), 4), "q_lo_max": round(float(a_.max()), 4),
                         "q_lo_p10_p50_p90": [round(float(v), 3) for v in np.percentile(a_, [10, 50, 90])],
                         "q_lo_at_clip_share": round(float((a_ <= clip_lo + 1e-9).mean()), 3)},
            "rep0_S1_folds": fq, "clip_logit": [round(clip_lo, 4), round(clip_hi, 4)]}
        log(d, "q_hi", res["quantile_heads"][d]["full_fit"])
    # (2)(3) per variant: S1 OOF again, CQR raw (pre display) vs displayed, 85 % pass region
    tb = {"lo": 1 / (1 + math.exp(-(math.log(0.85 / 0.15) - 0.7))), "hi": 1 / (1 + math.exp(-(math.log(0.85 / 0.15) + 0.7)))}
    raw = {}
    for d in ("D379", "D394"):
        folds = D.folds(0, "S1")
        lo_, hi_ = np.full(D.n, np.nan), np.full(D.n, np.nan)
        for k in range(TR.K):
            te, trn = folds == k, (folds != k) & D.in_data[d]
            lo, hi = TR.qpredict(*TR.quant_pair(D.X[trn], D.Y[trn]), D.X[te])
            w = TR.cqr_width(D.X, D.Y, np.where(trn)[0], seed=k)
            lo_[te], hi_[te] = lo - w, hi + w
        raw[d] = (lo_, hi_)
        log("CQR raw", d)
    tuning = r["tuning"]
    finals = {"W": CONFIGS_DEV[tuning["W"]["chosen"]], "X": CONFIGS_DEV["X"], "S": CONFIGS_DEV[tuning["S"]["chosen"]]}
    variants = {"B0": ("base", "D379"), "C2": ("base", "D394")}
    for c in finals:
        for d in ("D379", "D394"):
            variants[f"{c}-{d}"] = (c, d)
    idx = np.arange(D.n0)
    y = D.act[idx]
    segs = np.array([D.rows[i]["seg"] for i in idx])
    for v, (c, d) in variants.items():
        oof, _ = oof_cv(D, {"kind": "base"} if c == "base" else finals[c], d, "S1", f"addenda {v}")
        pm = oof[:, idx].mean(0)
        chk = float(np.abs(pm - y).mean())
        assert abs(chk - r["S1"][v]["eval"]["all"]["mae"]) < 1e-9, (v, chk)
        lo_, hi_ = raw[d][0][idx], raw[d][1][idx]
        rp_lo, rp_hi = rm.expit(lo_), rm.expit(hi_)
        dp = [TR.MD.range_to_prob(x1, x2) for x1, x2 in zip(lo_, hi_)]
        dp_lo, dp_hi = np.array([q[0] for q in dp]), np.array([q[1] for q in dp])
        res["coverage_pre_post"][v] = {
            "pre_display": {"coverage": round(float(((y >= rp_lo) & (y <= rp_hi)).mean()), 3),
                            "mean_width": round(float((rp_hi - rp_lo).mean()), 3)},
            "post_display": {"coverage": round(float(((y >= dp_lo) & (y <= dp_hi)).mean()), 3),
                             "mean_width": round(float((dp_hi - dp_lo).mean()), 3),
                             "upper_is_1_share": round(float((dp_hi >= 1.0).mean()), 3)},
            "point_mae": round(chk, 4), "range_note": "range depends on the training data only (same for every method on the same data)"}
        # 85 % pass region on the 379 (own placement): support + target in segment p5–p95 + confidence ≠ low + P ≥ 0.5
        rel = TR.reliability_tables([D.rows[i] for i in idx], pm, y, dp_lo, dp_hi)
        trn_y = D.act[D.in_data[d]]
        trn_seg = np.array([D.rows[i]["seg"] for i in np.where(D.in_data[d])[0]])
        p595 = {s: np.percentile(trn_y[trn_seg == s], [5, 95]) for s in set(trn_seg)}
        conf = confidence_list(D, idx, pm, rel)
        P = np.array([p_in_band(pm[i], (dp_lo[i], dp_hi[i]), (tb["lo"], tb["hi"])) for i in range(len(idx))])
        tgt_ok = np.array([s in p595 and p595[s][0] <= 0.85 <= p595[s][1] for s in segs])
        ok = (np.array(conf) != "low") & tgt_ok
        passed = ok & (P >= 0.5)
        zones_ok = [f"{b['lo']:.2f}-{b['hi']:.2f}" for b in rel["pred_bins"]
                    if not (b["mae"] >= ZONE_LOW_MAE or b["coverage80"] < ZONE_LOW_COV)]
        res["a85"][v] = {"band": [round(tb["lo"], 4), round(tb["hi"], 4)], "pass_n": int(passed.sum()),
                         "gate_ok_n": int(ok.sum()), "gate_ok_pred_min": round(float(pm[ok].min()), 4) if ok.any() else None,
                         "P_max_gate_ok": round(float(P[ok].max()), 3) if ok.any() else None,
                         "pred_in_band_n": int(((pm >= tb["lo"]) & (pm <= tb["hi"])).sum()),
                         "pred_zones_not_high_error": zones_ok,
                         "pass_levels": [{"L": int(D.L[i]), "pred": round(float(pm[j]), 4), "actual": float(y[j]), "P": round(float(P[j]), 3)}
                                         for j, i in enumerate(idx) if passed[j]],
                         "note": "confirmation seed (C) not applicable to stored training rows; rules/thresholds unchanged"}
        log(v, "cov pre/post", res["coverage_pre_post"][v]["pre_display"]["coverage"],
            res["coverage_pre_post"][v]["post_display"]["coverage"], "a85 pass", res["a85"][v]["pass_n"])
    save(OUT / "addenda.json", res)
    log("saved", OUT / "addenda.json")


def confidence_list(D, idx, pm, rel):
    c, X, out = D.fc, D.X[idx], []
    for i in range(len(idx)):
        codes, p = set(), pm[i]
        if p < LOW_CONF_BELOW:
            codes.add("LOW")
        if X[i, c["gimmick_first"]] >= 1 or X[i, c["novelty"]] > NOVELTY_HIGH:
            codes.add("LOW")
        z = next((b for b in rel["pred_bins"] if b["lo"] <= p < b["hi"] or (b["hi"] >= 1.0 and p >= b["lo"])), None)
        if z and (z["mae"] >= ZONE_LOW_MAE or z["coverage80"] < ZONE_LOW_COV):
            codes.add("LOW")
        cb = rel["combo"].get(D.combo[idx[i]], {"n": 0})
        if cb["n"] < COMBO_FEW_LT or cb.get("mae", 0) >= COMBO_MAE_GE:
            codes.add("LOW")
        out.append("low" if codes else "ok")
    return out


def cmd_report(a):
    """compare.json → compare.md (tables only, no computation)."""
    r = CA.load(OUT / "compare.json")
    V = list(r["S1"])
    f = lambda s, k: f"{s[k]:.4f}" if k in s else "-"
    L = [f"prereg {r['prereg_commit']} · sealed n={r['sealed']['n']} (<0.85 {r['sealed']['lt085']}, ≥0.96 {r['sealed']['ge096']})",
         f"tuning: W → {r['tuning']['W']['chosen']} {r['tuning']['W']['deltas']} · S → {r['tuning']['S']['chosen']} {r['tuning']['S']['deltas']}", ""]
    for st, title in (("S1", "S1 평가 379 (MAE / 편향 / |e|>0.10 수)"), ("S2", "S2 평가 394")):
        L += [f"### {title}", "| 구간 | n | " + " | ".join(V) + " |", "|---|---|" + "---|" * len(V)]
        keys = [k for k in r[st]["B0"]["eval"] if k != "confidence"]
        for k in keys:
            b = r[st]["B0"]["eval"][k]
            L.append(f"| {k} | {b['n']} | " + " | ".join(
                f"{f(r[st][v]['eval'][k], 'mae')} / {r[st][v]['eval'][k].get('bias', 0):+.4f} / {r[st][v]['eval'][k].get('big10_n', '-')}"
                if k in r[st][v]["eval"] else "-" for v in V) + " |")
        L.append("| ρ / 기울기 | | " + " | ".join(f"{r[st][v]['eval']['all']['rho']:.3f} / {r[st][v]['eval']['all']['slope']:+.3f}" for v in V) + " |")
        L.append("| 포함80 / 평균폭 | | " + " | ".join(f"{r[st][v]['eval']['all']['cov80']:.3f} / {r[st][v]['eval']['all']['width_mean']:.3f}" for v in V) + " |")
        L.append("| 신뢰 통과 n / MAE / 큰오차 / 그중 실제<0.85 | | " + " | ".join(
            "{levels_pass} / {mae:.4f} / {big10_n} / {pass_actual_lt085}".format(**r[st][v]["eval"]["confidence"]) for v in V) + " |")
        L.append("")
    L += ["### 봉인 (ΔMAE / Δ편향 vs B0, 95% CI)", "| 변형 | 전체 | <0.85 | 0.85-0.96 | ≥0.96 |", "|---|---|---|---|---|"]
    for v in V:
        s = r["sealed_eval"][v]
        L.append(f"| {v} | " + " | ".join(f"{s[k]['mae']:.4f} ({s[k]['d_mae']:+.4f} {s[k]['ci_d_mae']}) / {s[k]['bias']:+.4f} ({s[k]['d_bias']:+.4f} {s[k]['ci_d_bias']})"
                                          for k in ("all", "lt0.85", "0.85-0.96", "ge0.96")) + " |")
    L += ["", "### 판정 (S1 vs B0)", "| 변형 | K1 Δ편향<0.85 [CI] | K2 ΔMAE / Δρ | K3 악화 | K4 | K5 | 판정 (K1~K4만) |", "|---|---|---|---|---|---|---|"]
    for v, j in r["judge"].items():
        ci = r["boot_S1"][v]
        L.append(f"| {v} | {j['d_lt085_bias']:+.4f} {ci['act_lt0.85|bias']} {'✔' if j['K1'] else '✗'} | {j['d_mae']:+.4f} (허용 {j['tol_mae']}) / {j['d_rho']:+.4f} {'✔' if j['K2'] else '✗'} | "
                 f"{[k for k, w in j['worse'].items() if w] or '없음'} | {'✔' if j['K4'] else '✗'} | {j['K5']} {j['K5_note']} | **{j['verdict']}** ({j['verdict_K1_K4_only']}) |")
    (OUT / "compare.md").write_text("\n".join(L) + "\n", encoding="utf-8")
    log("saved", OUT / "compare.md")


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("support").set_defaults(f=cmd_support)
    sub.add_parser("eval").set_defaults(f=cmd_eval)
    sub.add_parser("report").set_defaults(f=cmd_report)
    sub.add_parser("addenda").set_defaults(f=cmd_addenda)
    a = ap.parse_args()
    a.f(a)


if __name__ == "__main__":
    main()
