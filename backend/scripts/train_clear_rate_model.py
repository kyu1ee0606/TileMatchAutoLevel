"""Train + export the clear-rate model (new real-user clear-rate prediction, parallel display — docs 31 / 33).

Reproduces the target-metric E1 setup of doc 26 §11 with the *direct* (numpy-only) c+ model of
`residual_model.py` (doc 21: same accuracy as the lightgbm E1), so the server can predict in pure Python:
  data   : bot_v24 "rules only" rows (v2.4 = rule-parity 6 items, merge 26dd967 V24_DEFAULT), 128 games × θ{.55,.65,.85,1.0}
           ∩ AF level_metrics map_match=="same" ∩ first-try ended ≥100 ∩ legacy predicted_clear_rate present (n=379,
           same level set as target_metric_eval.py / bot_v24_target_eval.py)
  target : ft_any = first-try clear rate incl. help, ended runs only (no_end excluded)  [head "ft_any"]
           aux heads: unaided LB (unaided_clear_lower_bound) and first-try help rate (ft_help_rate)
  model  : mean of ridge + GBM logits (residual_model.Ridge / GBM, unchanged hyper-parameters)
  range  : CQR 80% — direct quantile GBM q0.1/q0.9 widened by the inner 5-fold conformity-score quantile
  check  : map-group K-fold 5 × 4 repeats, compared with the doc-26 §11-2 baseline (v2.3 + E1 MAE 0.0320, ρ 0.758)

No new bot measurement. Run with a python that has numpy (no lightgbm/sklearn needed), from the repo root:
  analysis_venv/bin/python backend/scripts/train_clear_rate_model.py            # evaluate + export + activate
  analysis_venv/bin/python backend/scripts/train_clear_rate_model.py --check    # retrain, compare with saved model.json
Writes backend/data/models/clear_rate/<version>/{model.json, bot_cache.json, manifest.json} and active.json.
"""
import os

os.environ.setdefault("OMP_NUM_THREADS", "1")

import argparse
import hashlib
import importlib.util
import json
import sys
import time
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
BACKEND = HERE.parent
sys.path.insert(0, str(HERE))
import residual_model as rm  # noqa: E402


def _load_by_path(name, path):  # bypass app/core/__init__ (heavy imports) — these modules import nothing from app
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


FE = _load_by_path("clear_rate_features", BACKEND / "app/core/clear_rate/features.py")
MD = _load_by_path("clear_rate_model", BACKEND / "app/core/clear_rate/model.py")
CN = _load_by_path("clear_rate_conditions", BACKEND / "app/core/clear_rate/conditions.py")

CAL = rm.CAL
BOT_FILE = "bot_v24/bot_v2.4f_no_rules_only.json"
BASELINE_FILE = "bot_v24/target/ftany2.json"
LEGACY_BATCH = BACKEND / "data/production/batch_1792056041502_cn5e4ny66.json"
MODELS = BACKEND / "data/models/clear_rate"
DEFAULT_VERSION = "cr-ftany-v24r-20261016"
FEATS = FE.FEATS
K, REPS = 5, 4
GATE = {"mae_max": 0.035, "rho_min": 0.72}  # doc 31 §2-2 proposal (D9)
PROTOCOL, SEED_BAND = "theta4x128_v1", "seed11M"  # seeds 11,000,000 + level_index*1000 + game
SHARD_COMMIT = "b741f6a3"  # bot_af_L32_500.SHARD_110 — build 1.1.0 maps = maps the AF runs were played on (doc 31 §2-2)
T0 = time.time()


def log(*a):
    print(f"[{time.time() - T0:6.0f}s]", *a, flush=True)


# ── quantile GBM (pinball loss; leaves = α-quantile of the residuals that reach them) ──────────────
class QGBM(rm.GBM):
    def __init__(self, feats, alpha, **kw):
        super().__init__(feats, **kw)
        self.alpha = alpha

    def _relabel(self, t, X, r):
        if t[0] == "leaf":
            return ("leaf", float(np.quantile(r, self.alpha))) if len(r) else t
        m = X[:, t[1]] <= t[2]
        return ("node", t[1], t[2], self._relabel(t[3], X[m], r[m]), self._relabel(t[4], X[~m], r[~m]))

    def fit(self, X, y, cols):
        self.idx = [cols.index(c) for c in self.feats]
        Xf = X[:, self.idx]
        rng = np.random.RandomState(self.seed)
        self.base = float(np.quantile(y, self.alpha))
        self.gain = np.zeros(len(self.idx))
        F = np.full(len(y), self.base)
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


def point_model():
    return rm.Blend(rm.Ridge(FEATS), rm.GBM(FEATS))


def quant_pair(X, y):
    lo, hi = QGBM(FEATS, 0.1).fit(X, y, FEATS), QGBM(FEATS, 0.9).fit(X, y, FEATS)
    return lo, hi


def qpredict(lo, hi, X):
    a, b = lo.predict(X, FEATS), hi.predict(X, FEATS)
    return np.minimum(a, b), np.maximum(a, b)


CQR_SEEDS = 3  # inner splits pooled — one 5-fold split alone gave widths 0.00~0.22 logit across outer folds


def cqr_width(X, y, idx, seed, q=0.8):
    """Inner 5-fold conformity score E = max(lo − y, y − hi) → its finite-sample q-quantile (residual_model_lib),
    scores pooled over CQR_SEEDS inner splits."""
    E = []
    for s in range(CQR_SEEDS):
        inner = np.random.RandomState(seed * 100 + s).permutation(len(idx)) % 5
        for j in range(5):
            a, b = idx[inner != j], idx[inner == j]
            lo, hi = qpredict(*quant_pair(X[a], y[a]), X[b])
            E.append(np.maximum(lo - y[b], y[b] - hi))
    E = np.concatenate(E)
    return float(np.quantile(E, min(1.0, q * (1 + 1 / len(E)))))


# ── data ────────────────────────────────────────────────────────────────────────────────────────────
def load_all():
    prep = {int(k): v for k, v in rm.load(CAL / "bot_v21/prep.json").items()}
    af = {int(k): v for k, v in rm.load(CAL / "bot_v21/af.json").items()}
    bot_rows = rm.load(CAL / BOT_FILE)["rows"]
    LM_doc = rm.load(CAL / "level_metrics.json")
    LM = {r["level"]: r for r in LM_doc["levels"]}
    leg = rm.load(LEGACY_BATCH)
    legm = {lv["meta"]["level_number"]: lv["meta"].get("predicted_clear_rate") for lv in leg["levels"]}
    return prep, af, bot_rows, LM_doc, LM, legm


def position_table(prep):
    """Exposure counts before each live level (L32..L-1) — residual_model.build's schedule, kept for serving."""
    mf = {L: FE.map_features(prep[L]["map"]) for L in prep}
    seen, expo = Counter(), {}
    for L in sorted(prep):
        expo[L] = {g: seen[g] for g in FE.GIMMICKS}
        for g in FE.GIMMICKS:
            if mf[L].get(g, 0) > 0:
                seen[g] += 1
    expo[max(prep) + 1] = {g: seen[g] for g in FE.GIMMICKS}
    return expo


def features_for(L, prep, af, expo, bot):
    p = prep[L]
    return FE.level_features(
        p["map"], placement_level=L, use_tile_count=p["row"]["useTileCount"], unlock_tile=p["row"]["unlockTile"],
        is_boss=bool(af[L].get("is_boss")), random_layout=p["mode"] == "random",
        map2nd=p["map_match_editor"] == "mismatch", exposure=expo[L],
        gimmick_first=bool(af[L].get("is_gimmick_first")), bot_rows=bot.get(L, {}).values())


def build_dataset():
    prep, af, bot_rows, LM_doc, LM, legm = load_all()
    bot = rm.bot_table(CAL / BOT_FILE)
    expo = position_table(prep)
    ref = rm.build(CAL / BOT_FILE)  # reference implementation
    rm.add_logits(ref)
    assert FEATS == rm.FEATS_ALL, "feature order differs from residual_model.FEATS_ALL"
    mism = 0
    for r in ref:
        f = features_for(r["L"], prep, af, expo, bot)
        for c in FEATS:
            a, b = f[c], float(r[c])
            if not ((a != a and b != b) or abs(a - b) <= 1e-12):
                mism += 1
                log("feature mismatch", r["L"], c, a, b)
    assert mism == 0, f"{mism} feature mismatches vs residual_model.build"
    rows = []
    for r in ref:
        m = LM.get(r["L"])
        if r["exclude"] or r["clean_n"] < rm.MIN_N or not r["has_bot"]:
            continue
        if not m or m.get("map_match") != "same" or (m.get("first_try_ended") or 0) < 100:
            continue
        if m.get("ft_clear_rate_any_help") is None or not legm.get(r["L"]):
            continue
        rows.append({"L": r["L"], "seg": r["seg"], "maphash": r["maphash"], "ft_any": m["ft_clear_rate_any_help"],
                     "lb": m["unaided_clear_lower_bound"], "help": m["ft_help_rate"],
                     "gims": [g for g in FE.GIMMICKS if r["has_" + g]], "x": [float(r[c]) for c in FEATS]})
    X = np.array([r["x"] for r in rows], float)
    assert not np.isnan(X).any()
    log(f"features: {len(ref)} levels match residual_model.build; training set n={len(rows)}")
    return rows, X, prep, af, bot_rows, LM_doc, expo, len(ref)


def kfolds(rows, rep):  # residual_model_lib.kfolds (map-hash groups)
    grp = np.array([r["maphash"] for r in rows])
    gperm = {g: i % K for i, g in enumerate(np.random.RandomState(100 + rep).permutation(sorted(set(grp))))}
    return np.array([gperm[g] for g in grp])


def ytarget(rows, key):
    return rm.logit(np.clip(np.array([r[key] for r in rows], float), 0.005, 0.995))


# ── evaluation ──────────────────────────────────────────────────────────────────────────────────────
def metr(y, p):
    e = p - y
    return {"mae": float(np.abs(e).mean()), "bias": float(e.mean()), "rho": rm.spearman(p, y),
            "hit05": float((np.abs(e) <= 0.05).mean()), "hit10": float((np.abs(e) <= 0.10).mean())}


def agg(ms):
    out = {k: round(float(np.mean([m[k] for m in ms])), 4) for k in ms[0]}
    out["sd"] = {k: round(float(np.std([m[k] for m in ms])), 4) for k in ms[0]}
    return out


def evaluate(rows, X):
    n = len(rows)
    heads = {"ft_any": "ft_any", "unaided_lb": "lb", "help_rate": "help"}
    Y = {h: ytarget(rows, k) for h, k in heads.items()}
    T = {h: np.array([r[k] for r in rows]) for h, k in heads.items()}
    oof = {h: np.zeros((REPS, n)) for h in heads}
    for rep in range(REPS):
        folds = kfolds(rows, rep)
        for k in range(K):
            tr, te = folds != k, folds == k
            for h in heads:
                oof[h][rep, te] = rm.expit(point_model().fit(X[tr], Y[h][tr], FEATS).predict(X[te], FEATS))
        log(f"K-fold rep {rep + 1}/{REPS}: ft_any MAE {metr(T['ft_any'], oof['ft_any'][rep])['mae']:.4f}")
    res = {h: agg([metr(T[h], oof[h][rep]) for rep in range(REPS)]) for h in heads}
    segs = sorted({r["seg"] for r in rows})
    res["ft_any_by_segment"] = {}
    for s in segs:
        mk = np.array([r["seg"] == s for r in rows])
        res["ft_any_by_segment"][s] = dict(agg([metr(T["ft_any"][mk], oof["ft_any"][rep][mk]) for rep in range(REPS)]),
                                           n=int(mk.sum()))
    # reliable-range table (doc 26 §11-9) on the repeat-mean OOF
    pm, y = oof["ft_any"].mean(0), T["ft_any"]
    res["ft_any_by_actual"] = {}
    for name, lo, hi in (("ge0.96", 0.96, 9), ("0.92-0.96", 0.92, 0.96), ("0.85-0.92", 0.85, 0.92), ("lt0.85", -9, 0.85)):
        mk = (y >= lo) & (y < hi)
        e = pm[mk] - y[mk]
        res["ft_any_by_actual"][name] = {"n": int(mk.sum()), "mae": round(float(np.abs(e).mean()), 4),
                                         "bias": round(float(e.mean()), 4), "hit05": round(float((np.abs(e) <= .05).mean()), 3)}
    # CQR 80% coverage (rep 0, as doc 21)
    folds = kfolds(rows, 0)
    lo_, hi_, w_ = np.zeros(n), np.zeros(n), []
    for k in range(K):
        te = folds == k
        tr_idx = np.where(~te)[0]
        lo, hi = qpredict(*quant_pair(X[~te], Y["ft_any"][~te]), X[te])
        w = cqr_width(X, Y["ft_any"], tr_idx, seed=k)
        w_.append(w)
        lo_[te], hi_[te] = lo - w, hi + w
        log(f"CQR fold {k}: width {w:+.3f}")
    probs = [MD.range_to_prob(a, b) for a, b in zip(lo_, hi_)]
    plo, phi, pt = np.array([v[0] for v in probs]), np.array([v[1] for v in probs]), oof["ft_any"][0]
    y = T["ft_any"]
    res["ft_any_range80"] = {"coverage": round(float(((y >= plo) & (y <= phi)).mean()), 3),
                             "mean_width": round(float((phi - plo).mean()), 3),
                             "median_width": round(float(np.median(phi - plo)), 3),
                             "point_inside": round(float(((pt >= plo) & (pt <= phi)).mean()), 3),
                             "upper_at_clip_share": round(float((phi >= 1.0).mean()), 3),
                             "cqr_width_logit_per_fold": [round(w, 3) for w in w_]}
    for s in segs:
        mk = np.array([r["seg"] == s for r in rows])
        res["ft_any_range80"][f"coverage_{s}"] = round(float(((y[mk] >= plo[mk]) & (y[mk] <= phi[mk])).mean()), 3)
    return res, Y


def baseline():
    b = rm.load(CAL / BASELINE_FILE)["results"]
    pick = lambda k: {m: b[k]["e1"][m] for m in ("mae", "bias", "rho", "hit05", "hit10")} | {"sd": b[k]["e1"]["sd"]}
    return {"v23_E1_lightgbm": pick("ft_any|v23"), "v24_rules_only_E1_lightgbm": pick("ft_any|rules_only"),
            "source": f"af_calibration/{BASELINE_FILE} (doc 26 §11-2)"}


def gates(ev, base):
    e, b = ev["ft_any"], base["v23_E1_lightgbm"]
    # "equivalent within repeat sd": |ΔMAE| ≤ 2·max(sd) and Δρ ≥ −2·max(sd_ρ)
    tol_mae = 2 * max(e["sd"]["mae"], b["sd"]["mae"], 0.0005)
    tol_rho = 2 * max(e["sd"]["rho"], b["sd"]["rho"], 0.005)
    g = {"mae_le_gate": e["mae"] <= GATE["mae_max"], "rho_ge_gate": e["rho"] >= GATE["rho_min"],
         "mae_equiv_baseline": abs(e["mae"] - b["mae"]) <= tol_mae, "rho_equiv_baseline": e["rho"] >= b["rho"] - tol_rho,
         "tol_mae": round(tol_mae, 4), "tol_rho": round(tol_rho, 4),
         "delta_mae": round(e["mae"] - b["mae"], 4), "delta_rho": round(e["rho"] - b["rho"], 4)}
    g["pass"] = all(v for k, v in g.items() if isinstance(v, bool))
    return g


# ── export ──────────────────────────────────────────────────────────────────────────────────────────
def j_tree(t):
    return ["leaf", float(t[1])] if t[0] == "leaf" else ["node", int(t[1]), float(t[2]), j_tree(t[3]), j_tree(t[4])]


def j_ridge(R):
    return {"feats": list(R.feats), "mu": [float(v) for v in R.mu], "sd": [float(v) for v in R.sd],
            "w0": float(R.w[0]), "w": [float(v) for v in R.w[1:]], "lam": float(R.lam_used)}


def j_gbm(G):
    return {"feats": list(G.feats), "base": float(G.base), "lr": float(G.lr), "trees": [j_tree(t) for t in G.trees]}


def fit_export(rows, X, Y, expo, af, prep, bot_rows):
    heads, np_pred = {}, {}
    for h in ("ft_any", "unaided_lb", "help_rate"):
        m = point_model().fit(X, Y[h], FEATS)
        R, G = m.models
        heads[h] = {"point": {"ridge": j_ridge(R), "gbm": j_gbm(G)}}
        np_pred[h] = m.predict(X, FEATS)
    lo, hi = quant_pair(X, Y["ft_any"])
    w = cqr_width(X, Y["ft_any"], np.arange(len(rows)), seed=0)
    heads["ft_any"].update({"q_lo": j_gbm(lo), "q_hi": j_gbm(hi), "cqr_w": w})
    np_pred["lo"], np_pred["hi"] = qpredict(lo, hi, X)
    log(f"final fit done (CQR width {w:+.3f})")

    yv = np.array([r["ft_any"] for r in rows])
    segs = sorted({r["seg"] for r in rows})
    support = {
        "n_train": len(rows), "level_range": [32, 500],
        "train_levels": [r["L"] for r in rows],
        "feature_p01": [float(v) for v in np.percentile(X, 1, axis=0)],
        "feature_p99": [float(v) for v in np.percentile(X, 99, axis=0)],
        "gimmick_train_levels": {g: int(sum(g in r["gims"] for r in rows)) for g in FE.GIMMICKS},
        "segment_levels": {s: int(sum(r["seg"] == s for r in rows)) for s in segs},
        "target_p05_p95_by_segment": {s: [float(v) for v in np.percentile(yv[[r["seg"] == s for r in rows]], [5, 95])]
                                      for s in segs},
        "min_gimmick_levels": 10, "ood_min_features": 2,
    }
    position = {"exposure": {str(L): v for L, v in sorted(expo.items())},
                "gimmick_first_levels": sorted(L for L in af if af[L].get("is_gimmick_first")),
                "boss_rule": "autoCollectCount in 1..3 (upload default: 3 when level % 10 == 0)"}
    check = [{"L": rows[i]["L"], "x": rows[i]["x"], "ft_logit": float(np_pred["ft_any"][i]),
              "lb_logit": float(np_pred["unaided_lb"][i]), "help_logit": float(np_pred["help_rate"][i]),
              "q_lo": float(np_pred["lo"][i]), "q_hi": float(np_pred["hi"][i])} for i in range(0, len(rows), 76)]
    model = {"features": FEATS, "heads": heads, "support": support, "position": position, "check": check}

    # bot cache: training-schedule (live build) levels with all 4 θ rows, keyed by the measured game-condition hash
    by_L = {}
    for r in bot_rows:
        by_L.setdefault(r["L"], {})[round(float(r["theta"]), 2)] = r
    cache = {}
    for L, th in sorted(by_L.items()):
        if L not in prep or not all(t in th for t in FE.THETAS):
            continue
        h = CN.cond_hash(prep[L]["map"], prep[L]["row"])
        cache[h] = {"L": L, "bot_version": "v2.4", "protocol": PROTOCOL, "seed_band": SEED_BAND, "cond_hash": h,
                    "conditions": CN.normalize_conditions(prep[L]["row"]),
                    "rows": [{"theta": t, "games": th[t]["games"], "wins": th[t]["wins"],
                              "fail_reasons": th[t]["fail_reasons"],
                              **({"fail_tiles_left_board": th[t]["fail_tiles_left_board"]} if t == 1.0 else {})}
                             for t in FE.THETAS]}
    return model, cache, np_pred


def parity(model, rows, np_pred):
    """Pure-Python predictor (app/core/clear_rate/model.py) vs numpy on every training row."""
    H = model["heads"]
    d = 0.0
    for i, r in enumerate(rows):
        f = dict(zip(FEATS, r["x"]))
        for h in ("ft_any", "unaided_lb", "help_rate"):
            pt = H[h]["point"]
            v = 0.5 * (MD.ridge_predict(pt["ridge"], [f[c] for c in pt["ridge"]["feats"]]) +
                       MD.gbm_predict(pt["gbm"], [f[c] for c in pt["gbm"]["feats"]]))
            d = max(d, abs(v - np_pred[h][i]))
        a = MD.gbm_predict(H["ft_any"]["q_lo"], [f[c] for c in FEATS])
        b = MD.gbm_predict(H["ft_any"]["q_hi"], [f[c] for c in FEATS])
        d = max(d, abs(min(a, b) - np_pred["lo"][i]), abs(max(a, b) - np_pred["hi"][i]))
    return d


def dumps(o):
    return json.dumps(o, ensure_ascii=False, separators=(",", ":"), sort_keys=True)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--version", default=DEFAULT_VERSION)
    ap.add_argument("--check", action="store_true", help="retrain and compare with the saved model.json / bot_cache.json")
    ap.add_argument("--no-activate", action="store_true")
    a = ap.parse_args()

    rows, X, prep, af, bot_rows, LM_doc, expo, n_feat_checked = build_dataset()
    if a.check:
        Y = {h: ytarget(rows, k) for h, k in (("ft_any", "ft_any"), ("unaided_lb", "lb"), ("help_rate", "help"))}
        model, cache, np_pred = fit_export(rows, X, Y, expo, af, prep, bot_rows)
        out = MODELS / a.version
        same_m = dumps(model) == (out / "model.json").read_text(encoding="utf-8")
        same_c = dumps(cache) == (out / "bot_cache.json").read_text(encoding="utf-8")
        print(json.dumps({"model_json_identical": same_m, "bot_cache_identical": same_c}))
        sys.exit(0 if same_m and same_c else 1)

    ev, Y = evaluate(rows, X)
    base = baseline()
    g = gates(ev, base)
    log("ft_any", ev["ft_any"], "gates", g)
    if not g["pass"]:
        log("gates failed — model not saved")
        sys.exit(2)
    model, cache, np_pred = fit_export(rows, X, Y, expo, af, prep, bot_rows)
    pdiff = parity(model, rows, np_pred)
    assert pdiff < 1e-9, f"pure-python predictor differs from numpy by {pdiff}"
    tags = sorted({t for r in rm.load(CAL / BOT_FILE)["rows"] for t in (r.get("v24") or [])})
    model_s, cache_s = dumps(model), dumps(cache)
    manifest = {
        "model_version": a.version,
        "trained_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "target_metric": "ft_any_v1",
        "target_definition": "first-try clear rate incl. help = first-try clears / (clears + final fails); "
                             "ended runs only, no_end excluded (af_level_metrics ft_clear_rate_any_help)",
        "aux_targets": {"unaided_lb": "unaided_clear_lower_bound", "help_rate": "ft_help_rate"},
        "bot_version": "v2.4",
        "bot_config": "rule-parity defaults (V24_DEFAULT @ 26dd967: unknown_hide, curtain_hide, unknown_nobonus, "
                      "ac_inner, stack_hide, dock_rel); behaviour items off",
        "bot_rows_file": f"af_calibration/{BOT_FILE}", "bot_rows_v24_tags_seen": tags,
        "bot_rows_note": "doc 26 §11-1: 'rules only' file = full combination with behaviour items dropped, re-measured "
                         "on levels where those items can act; the other levels' rows are copied from the full "
                         "combination (items never fire there, same seeds -> identical rows), hence their tags",
        "bot_protocol": PROTOCOL, "bot_seed_band": SEED_BAND, "bot_thetas": list(FE.THETAS), "bot_games_per_theta": 128,
        "bot_seed_rule": "11,000,000 + level_index*1000 + game",
        "train_data": {"maps": f"af_calibration/bot_v21/prep.json (build 1.1.0 shard {SHARD_COMMIT})",
                       "shard_commit": SHARD_COMMIT, "af_level_metrics_generated_at": LM_doc.get("generated_at"),
                       "af_scope": LM_doc.get("scope"), "level_filter": "bot rows ∩ map_match==same ∩ first_try_ended≥100 "
                       "∩ not excluded ∩ clean_ft_n≥100 ∩ legacy predicted_clear_rate present",
                       "legacy_batch": LEGACY_BATCH.name, "n_levels": len(rows),
                       "feature_parity_levels_checked": n_feat_checked},
        "model": "c+ = mean(ridge, GBM) logits (residual_model.Ridge / GBM defaults); range80 = CQR(quantile GBM 0.1/0.9, "
                 f"inner 5-fold scores pooled over {CQR_SEEDS} splits); bound at target clip (0.01/0.99) shown as 0/1",
        "kfold": {"scheme": "map-hash group 5-fold × 4 repeats (RandomState(100+rep))", **ev},
        "baseline": base, "gates": g, "gate_thresholds": GATE,
        "parity_max_abs_logit_diff": pdiff,
        "model_json_sha256": hashlib.sha256(model_s.encode()).hexdigest(),
        "bot_cache_sha256": hashlib.sha256(cache_s.encode()).hexdigest(),
        "condition_fields": list(CN.GAME_FIELDS),
        "input_audit": "inputs = map structure/gimmicks, placement position (log L, segment, gimmick exposure and "
                       "first-appearance from the live schedule/unlock table, boss = autoCollectCount 1..3) and bot "
                       "measurement only; no AF value of the level itself (help rate, clear rate) is an input",
        "trust_notes": "ft_any < 0.85 unreliable (doc 26 §11-9: +0.118 easy bias); ≥ 0.95 ceiling — low discrimination",
    }
    out = MODELS / a.version
    out.mkdir(parents=True, exist_ok=True)
    (out / "model.json").write_text(model_s, encoding="utf-8")
    (out / "bot_cache.json").write_text(cache_s, encoding="utf-8")
    (out / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=1), encoding="utf-8")
    if not a.no_activate:
        (MODELS / "active.json").write_text(json.dumps({"version": a.version}) + "\n", encoding="utf-8")
    log("saved", out, f"model.json {len(model_s) // 1024} KB, bot_cache.json {len(cache_s) // 1024} KB")


if __name__ == "__main__":
    main()
