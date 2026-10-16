"""Clear-rate candidate models A1 / A1+A2 vs the active model (doc 33 §12, doc 35 §8-3 A1·A1b·A2).

Adds low-clear levels from doc 35a to the training set of `train_clear_rate_model.py` and compares, on the same
map-group folds, against the active model. The active model directory and active.json are never written.

  A1 : L429·494·498·499 — bot v2.4 rows exist; excluded from 379 only by clean_ft_n < 100
  A2 : L505·507·521·531·537·551·558·566·568·577·578 — L501+, newly measured here (v2.4 rules only, theta4x128_v1)

Sub-commands (run from the worktree root with the analysis venv; data are read from the main checkout's ignored
sandbox, CR_DATA_ROOT, because the worktree has no pv_sandbox / production batch):
  prep     build-1.1.0 shard (b741f6a3) maps + rows for L501..578 (same builder as bot_af_L32_500.cmd_prep,
           checked to reproduce the stored L32..500 prep entries) → cand_a1a2/prep_ext.json, af_ext.json
  measure  A2 bot rows: bot_v24_eval.run_task (same seeds 11,000,000 + layout*1000 + game), V24_DEFAULT items,
           θ 0.55/0.65/0.85/1.0 × 128, ≤ 2 processes, checkpointed → cand_a1a2/bot_v24_rules_A2.json
           (first re-runs 3 stored (L, θ) rows of the training file and requires identical results)
  eval     pre-registered comparison (doc 33 §12-1) → cand_a1a2/compare.json, compare.md
  export   candidate model directories (model.json, bot_cache.json, manifest.json); active.json untouched
"""
import os

os.environ.setdefault("OMP_NUM_THREADS", "1")

import argparse
import hashlib
import json
import resource
import subprocess
import sys
import time
from collections import Counter
from concurrent.futures import ProcessPoolExecutor
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
BACKEND = HERE.parent
DATA = Path(os.environ.get("CR_DATA_ROOT", str(BACKEND.parent.parent / "TileMatchAutoLevel/backend/data")))
CAL = DATA / "pv_sandbox/af_calibration"
OUT = CAL / "cand_a1a2"
os.environ.setdefault("BOT_CMP_OUT", str(CAL / "bot_compare_L32_500"))
sys.path.insert(0, str(BACKEND))
sys.path.insert(0, str(HERE))

A1 = (429, 494, 498, 499)
A2 = (505, 507, 521, 531, 537, 551, 558, 566, 568, 577, 578)
VERSION_Z = (505, 531)  # doc 35a §3: |z| > 1.96 between android 1.0.162 and 1.1.0 (decision P-e: report both)
EXT_HI = 578
THETAS = (0.55, 0.65, 0.85, 1.0)
GAMES = 128
WORKERS = min(2, int(os.environ.get("PV_WORKERS", "2")))
T0 = time.time()


def log(*a):
    print(f"[{time.time() - T0:6.0f}s]", *a, flush=True)


def load(p):
    with open(p, encoding="utf-8") as f:
        return json.load(f)


def save(path, obj):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, separators=(",", ":"))
    os.replace(tmp, path)


def swap_used():
    try:
        s = subprocess.run(["sysctl", "-n", "vm.swapusage"], capture_output=True, text=True).stdout
        return s.split("used = ")[1].split()[0]
    except Exception:
        return "?"


# ── prep ────────────────────────────────────────────────────────────────────────────────────────
def build_entries(lo, hi, LM):
    """bot_af_L32_500.cmd_prep for levels lo..hi (any range): played map + row from the 1.1.0 shard."""
    import bot_af_L32_500 as base

    def shard(commit):
        maps = {}
        for i in range((hi - 1) // 100 + 1):
            maps.update(base._git_key(commit, f"levelmap_level_{i}"))
        tab = base._git_key(commit, "levels")
        keys = tab["__keys"]
        rows = {}
        for v in tab["__vals"]:
            o = {keys[i]: v[i] for i in range(min(len(keys), len(v)))}
            rows[str(o.get("id"))] = o
        return maps, rows

    m110, r110 = shard(base.SHARD_110)
    m162, r162 = shard(base.SHARD_162)
    out = {}
    for L in range(lo, hi + 1):
        key = f"level_{L}"
        m, row = m110[key], r110[key]
        row_s = {k: row.get(k) for k in base.ROW_KEYS}
        same162 = (key in m162 and base._canon_hash(m162[key]) == base._canon_hash(m)
                   and {k: r162.get(key, {}).get(k) for k in base.ROW_KEYS} == row_s)
        x = LM[L]
        excl = None
        if int(float(row.get("autoCollectCount") or 0)) > 0:
            excl = "cat_help"
        elif (x["ft_booster_rate"] or 0) >= 0.5 and (x["ft_revive_rate"] or 0) < 0.05:
            excl = "booster_tutorial"
        elif float(row.get("timea") or 0) > 0:
            excl = "time_limit"
        out[L] = {"row": row_s, "map": m, "same162": same162, "map_match_editor": x["map_match"],
                  "mode": base.layout_mode(m), "features": base.features(m), "exclude": excl}
    return out


def cmd_prep(a):
    LM = {r["level"]: r for r in load(CAL / "level_metrics.json")["levels"]}
    stored = {int(k): v for k, v in load(CAL / "bot_v21/prep.json").items()}
    stored2 = {int(k): v for k, v in load(CAL / "bot_compare_L32_500/prep.json").items()}
    assert json.dumps(stored, sort_keys=True) == json.dumps(stored2, sort_keys=True), "bot_v21 vs bot_compare prep differ"
    ent = build_entries(32, EXT_HI, LM)
    diff = [L for L in stored if json.dumps(ent[L], sort_keys=True) != json.dumps(stored[L], sort_keys=True)]
    assert not diff, f"shard rebuild differs from stored prep on {len(diff)} levels: {diff[:10]}"
    log(f"shard rebuild reproduces stored prep.json on all {len(stored)} levels L32..500")
    ext = {L: v for L, v in ent.items() if L > 500}
    from bot_af_L32_500 import AF_KEYS
    af = {}
    for L in ext:
        x = LM[L]
        af[L] = {k: x.get(k) for k in AF_KEYS}
        af[L]["versions_used"] = "all"
    save(OUT / "prep_ext.json", {"levels": {str(L): v for L, v in ext.items()},
                                 "shard_commit": "b741f6a3", "shard_commit_162": "a2229a5d",
                                 "builder": "bot_af_L32_500.cmd_prep (same code path), L501..578",
                                 "check": f"rebuild == stored prep.json for L32..500 ({len(stored)} levels)"})
    save(OUT / "af_ext.json", {str(L): v for L, v in af.items()})
    for L in A2:
        e = ext[L]
        log(L, "mode", e["mode"], "excl", e["exclude"], "same162", e["same162"], "map_match", e["map_match_editor"],
            "row", e["row"])


def prep_all():
    """Stored prep/af (L32..500) + extension (L501..578) — for L ≤ 500 identical to the stored files."""
    P = {int(k): v for k, v in load(CAL / "bot_v21/prep.json").items()}
    A = {int(k): v for k, v in load(CAL / "bot_v21/af.json").items()}
    P.update({int(k): v for k, v in load(OUT / "prep_ext.json")["levels"].items()})
    A.update({int(k): v for k, v in load(OUT / "af_ext.json").items()})
    return P, A


# ── measure ─────────────────────────────────────────────────────────────────────────────────────
def _init_worker():
    import bot_v21_fit as v21
    P, A = prep_all()
    v21._CACHE["prep"], v21._CACHE["af"] = P, A


def _task(t):
    import bot_v24_eval as v24
    r = v24.run_task(t)
    r["maxrss_mb"] = round(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 2 ** 20, 1)  # macOS: bytes
    return r


def cmd_measure(a):
    import bot_v21_fit as v21
    from app.core.bot_simulator import V24_DEFAULT
    _init_worker()
    ex = v21.exposure_table()
    stored_ex = {int(k): v for k, v in load(CAL / "bot_v21/exposure.json").items()}
    assert all(ex[L] == stored_ex[L] for L in stored_ex), "exposure table differs from stored exposure.json"
    items = list(V24_DEFAULT)
    path = OUT / "bot_v24_rules_A2.json"
    log("swap used before:", swap_used(), "workers", WORKERS)

    # 1) protocol identity: re-run stored training rows (rules-only file) with the current default items
    train = {(r["L"], r["theta"]): r for r in load(CAL / "bot_v24/bot_v2.4f_no_rules_only.json")["rows"]}
    probes = [(237, 0.65), (301, 1.0), (455, 0.85)]
    with ProcessPoolExecutor(WORKERS, initializer=_init_worker) as ex_:
        res = list(ex_.map(_task, [{"L": L, "theta": t, "games": GAMES, "exposure": ex[L], "v24": items}
                                   for L, t in probes]))
    for (L, t), r in zip(probes, res):
        s = train[(L, t)]
        same = all(r[k] == s[k] for k in ("games", "wins", "fail_reasons", "fail_tiles_left", "fail_tiles_left_board"))
        log(f"identity L{L} θ{t}: wins {r['wins']} vs stored {s['wins']} → {'identical' if same else 'DIFFERENT'}")
        assert same, f"re-run of stored row L{L} θ{t} differs — protocol not reproduced"

    # 2) A2 levels
    done = load(path)["rows"] if path.exists() else []
    have = {(r["L"], r["theta"]) for r in done}
    todo = [{"L": L, "theta": t, "games": GAMES, "exposure": ex[L], "v24": items}
            for t in THETAS for L in A2 if (L, t) not in have]
    log(f"A2 todo {len(todo)} rows × {GAMES} games (have {len(done)})")
    t0, tl = time.time(), time.time()
    with ProcessPoolExecutor(WORKERS, initializer=_init_worker) as ex_:
        for i, r in enumerate(ex_.map(_task, todo, chunksize=1), 1):
            done.append(r)
            log(f"row {i}/{len(todo)} L{r['L']} θ{r['theta']} wins {r['wins']}/{r['games']} {r['sec']:.1f}s "
                f"rss {r['maxrss_mb']}MB")
            if time.time() - tl > 30:
                save(path, {"rows": done})
                tl = time.time()
    meta = {"bot_version": "v2.4", "v24_items": items, "protocol": "theta4x128_v1", "seed_band": "seed11M",
            "seed_rule": "11,000,000 + layout_index*1000 + game (bot_v24_eval.run_task, same as training rows)",
            "thetas": list(THETAS), "games_per_theta": GAMES, "workers": WORKERS,
            "shard_commit": "b741f6a3", "levels": list(A2),
            "wall_sec": round(time.time() - t0, 1), "cpu_sec": round(sum(r["sec"] for r in done), 1),
            "games": sum(r["games"] for r in done), "peak_worker_rss_mb": max(r["maxrss_mb"] for r in done),
            "swap_used_after": swap_used(), "measured_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "identity_probes": [f"L{L} θ{t}" for L, t in probes]}
    save(path, {"rows": done, "meta": meta})
    log("measure done", meta)


# ── training data (analysis venv: numpy) ────────────────────────────────────────────────────────
R1_LEVELS = (429, 433, 441, 466, 479, 493, 494, 498, 499)  # every L32..500 level failing only clean_ft_n ≥ 100
VARIANTS = {"B0": (), "C1": A1, "C2": A1 + A2, "C3": tuple(L for L in A1 + A2 if L not in VERSION_Z), "R1": R1_LEVELS}
CAND_DIRS = {"C1": "cr-ftany-v24r-cand-20261016-a1", "C2": "cr-ftany-v24r-cand-20261016-a1a2",
             "C3": "cr-ftany-v24r-cand-20261016-a1a2x"}
ACT_BINS = (("lt0.70", -9, 0.70), ("0.70-0.85", 0.70, 0.85), ("0.85-0.92", 0.85, 0.92), ("0.92-0.96", 0.92, 0.96),
            ("ge0.96", 0.96, 9), ("lt0.85", -9, 0.85))
SEGS = (("32-100", 32, 100), ("101-300", 101, 300), ("301-500", 301, 500), ("501+", 501, 10 ** 6))
BOOT = 2000
_TR = None


def tr():
    """train_clear_rate_model with its data paths pointed at CR_DATA_ROOT (the module itself is unchanged)."""
    global _TR
    if _TR is None:
        import importlib.util
        spec = importlib.util.spec_from_file_location("train_clear_rate_model", HERE / "train_clear_rate_model.py")
        m = importlib.util.module_from_spec(spec)
        sys.modules["train_clear_rate_model"] = m
        spec.loader.exec_module(m)
        m.rm.CAL = m.CAL = CAL
        m.LEGACY_BATCH = DATA / "production" / m.LEGACY_BATCH.name
        _TR = m
    return _TR


def seg_name(L):
    return next(s for s, lo, hi in SEGS if lo <= L <= hi)


def dataset():
    """379 base rows (train_clear_rate_model.build_dataset, unchanged) + candidate rows for every added level."""
    import numpy as np
    TR = tr()
    rows, X, prep, af, bot_rows, LM_doc, expo, n_feat = TR.build_dataset()
    P, A = prep_all()
    a2 = load(OUT / "bot_v24_rules_A2.json")
    ext_rows = bot_rows + a2["rows"]
    bot = {}
    for r in ext_rows:
        bot.setdefault(r["L"], {})[round(float(r["theta"]), 2)] = r
    expo_ext = TR.position_table(P)
    assert all(expo_ext[L] == expo[L] for L in prep), "extended exposure differs on L32..500"
    LM = {r["level"]: r for r in LM_doc["levels"]}
    have = {r["L"] for r in rows}
    add = {}
    for L in sorted(set(R1_LEVELS) | set(A1) | set(A2)):
        assert L not in have
        m, p = LM[L], P[L]
        assert p["exclude"] is None and m["map_match"] == "same" and m["first_try_ended"] >= 100, L
        assert all(t in bot.get(L, {}) for t in THETAS), f"bot rows missing for L{L}"
        f = TR.features_for(L, P, A, expo_ext, bot)
        mf = TR.FE.map_features(p["map"])
        add[L] = {"L": L, "seg": seg_name(L), "maphash": hashlib.sha1(json.dumps(p["map"], sort_keys=True).encode()).hexdigest()[:12],
                  "ft_any": m["ft_clear_rate_any_help"], "lb": m["unaided_clear_lower_bound"], "help": m["ft_help_rate"],
                  "gims": TR.FE.present_gimmicks(mf), "x": [float(f[c]) for c in TR.FEATS],
                  "clean_ft_n": m["clean_ft_n"], "first_try_ended": m["first_try_ended"]}
        assert not any(v != v for v in add[L]["x"]), f"NaN feature L{L}"
    base_groups = {r["maphash"] for r in rows}
    assert not base_groups & {r["maphash"] for r in add.values()}, "added level shares a map group with the 379"
    for r in rows:
        r["seg"] = seg_name(r["L"])
    return {"rows": rows, "X": X, "add": add, "prep": prep, "af": af, "P": P, "A": A, "bot_rows": bot_rows,
            "ext_rows": ext_rows, "LM_doc": LM_doc, "expo": expo, "n_feat": n_feat, "a2_meta": a2["meta"]}


# ── evaluation ──────────────────────────────────────────────────────────────────────────────────
def folds_for(TR, base_rows, add_rows, rep, setting):
    import numpy as np
    f0 = TR.kfolds(base_rows, rep)
    if not add_rows:
        return f0
    if setting == "S1":
        return np.concatenate([f0, np.full(len(add_rows), -1)])  # -1 = in every training fold
    groups = sorted({r["maphash"] for r in add_rows})
    g = {h: i % TR.K for i, h in enumerate(np.random.RandomState(200 + rep).permutation(groups))}
    return np.concatenate([f0, np.array([g[r["maphash"]] for r in add_rows])])


def run_oof(D, variant, setting, cqr=True):
    import numpy as np
    TR = tr()
    base, add = D["rows"], [D["add"][L] for L in VARIANTS[variant]]
    rows = base + add
    X = np.vstack([D["X"]] + ([np.array([r["x"] for r in add])] if add else []))
    Y = TR.ytarget(rows, "ft_any")
    n = len(rows)
    oof = np.full((TR.REPS, n), np.nan)
    for rep in range(TR.REPS):
        folds = folds_for(TR, base, add, rep, setting)
        for k in range(TR.K):
            trn, te = folds != k, folds == k
            oof[rep, te] = TR.rm.expit(TR.point_model().fit(X[trn], Y[trn], TR.FEATS).predict(X[te], TR.FEATS))
    plo = phi = None
    if cqr:  # rep 0, as train_clear_rate_model.evaluate
        folds = folds_for(TR, base, add, 0, setting)
        lo_, hi_ = np.full(n, np.nan), np.full(n, np.nan)
        for k in range(TR.K):
            te = folds == k
            lo, hi = TR.qpredict(*TR.quant_pair(X[~te], Y[~te]), X[te])
            w = TR.cqr_width(X, Y, np.where(~te)[0], seed=k)
            lo_[te], hi_[te] = lo - w, hi + w
        pr = [TR.MD.range_to_prob(a, b) if a == a else (np.nan, np.nan) for a, b in zip(lo_, hi_)]
        plo, phi = np.array([v[0] for v in pr]), np.array([v[1] for v in pr])
    return {"rows": rows, "X": X, "Y": Y, "oof": oof, "plo": plo, "phi": phi}


def _stats(y, pm, plo=None, phi=None):
    import numpy as np
    TR = tr()
    e = pm - y
    out = {"n": int(len(y)), "mae": float(np.abs(e).mean()) if len(y) else float("nan"),
           "bias": float(e.mean()) if len(y) else float("nan")}
    if len(y) >= 3:
        out["rho"] = TR.rm.spearman(pm, y)
        out["hit05"] = float((np.abs(e) <= 0.05).mean())
        out["slope"] = float(np.polyfit(y, e, 1)[0])
    if plo is not None and len(y):
        out["cov80"] = float(((y >= plo) & (y <= phi)).mean())
    return out


def masks(rows, idx):
    import numpy as np
    y = np.array([rows[i]["ft_any"] for i in idx])
    L = np.array([rows[i]["L"] for i in idx])
    m = {"all": np.ones(len(idx), bool)}
    for nm, lo, hi in ACT_BINS:
        m["act_" + nm] = (y >= lo) & (y < hi)
    for nm, lo, hi in SEGS:
        m["seg_" + nm] = (L >= lo) & (L <= hi)
    return m


def summarize(R, idx):
    """Metrics on the subset idx: repeat-mean OOF (+ per-rep sd) per mask."""
    import numpy as np
    rows = R["rows"]
    y = np.array([rows[i]["ft_any"] for i in idx])
    pm = R["oof"][:, idx].mean(0)
    out = {}
    for nm, mk in masks(rows, idx).items():
        if not mk.any():
            continue
        s = _stats(y[mk], pm[mk], *( (R["plo"][idx][mk], R["phi"][idx][mk]) if R["plo"] is not None else ()))
        reps = [_stats(y[mk], R["oof"][rep, idx][mk]) for rep in range(R["oof"].shape[0])]
        s["sd"] = {k: float(np.std([r[k] for r in reps])) for k in ("mae", "bias", "rho", "slope") if k in reps[0]}
        s["mae_rep_mean"] = float(np.mean([r["mae"] for r in reps]))  # train_clear_rate_model.agg convention
        out[nm] = {k: (round(v, 4) if isinstance(v, float) else v) for k, v in s.items() if k != "sd"}
        out[nm]["sd"] = {k: round(v, 4) for k, v in s["sd"].items()}
    return out


def boot_delta(Rb, Rc, n_eval, seed=12345):
    """Paired level bootstrap over the first n_eval rows (the 379): Δ = candidate − B0 on the same resample."""
    import numpy as np
    rng = np.random.RandomState(seed)
    rows = Rb["rows"][:n_eval]
    y = np.array([r["ft_any"] for r in rows])
    pb, pc = Rb["oof"][:, :n_eval].mean(0), Rc["oof"][:, :n_eval].mean(0)
    cb = (y >= Rb["plo"][:n_eval]) & (y <= Rb["phi"][:n_eval])
    cc = (y >= Rc["plo"][:n_eval]) & (y <= Rc["phi"][:n_eval])
    mk = masks(rows, list(range(n_eval)))
    keys = [k for k in mk if mk[k].any()]
    D = {f"{k}|{m}": [] for k in keys for m in ("mae", "bias")}
    D.update({"all|rho": [], "all|slope": [], "all|cov80": []})
    for _ in range(BOOT):
        b = rng.randint(0, n_eval, n_eval)
        yb, eb, ec = y[b], pb[b] - y[b], pc[b] - y[b]
        for k in keys:
            s = mk[k][b]
            if s.sum() == 0:
                continue
            D[f"{k}|mae"].append(np.abs(ec[s]).mean() - np.abs(eb[s]).mean())
            D[f"{k}|bias"].append(ec[s].mean() - eb[s].mean())
        D["all|rho"].append(tr().rm.spearman(pc[b], yb) - tr().rm.spearman(pb[b], yb))
        D["all|slope"].append(np.polyfit(yb, ec, 1)[0] - np.polyfit(yb, eb, 1)[0])
        D["all|cov80"].append(cc[b].mean() - cb[b].mean())
    return {k: [round(float(np.percentile(v, 2.5)), 4), round(float(np.percentile(v, 97.5)), 4)] for k, v in D.items() if v}


def judge(sb, sc, ci):
    """Pre-registered criteria doc 33 §12-0 (S1, 379)."""
    d = lambda k, m: sc[k][m] - sb[k][m]
    tol = lambda k, m, lo: 2 * max(sb[k]["sd"].get(m, 0), sc[k]["sd"].get(m, 0), lo)
    K1 = d("act_lt0.85", "bias") <= -0.010 and ci["act_lt0.85|bias"][1] < 0
    K2 = (d("all", "mae") <= tol("all", "mae", 0.0005) and d("all", "rho") >= -tol("all", "rho", 0.005)
          and sc["all"]["mae"] <= 0.035 and sc["all"]["rho"] >= 0.72)
    worse = {}
    for k in ("act_0.85-0.92", "act_0.92-0.96", "act_ge0.96", "seg_32-100", "seg_101-300", "seg_301-500"):
        worse[k] = bool(d(k, "mae") > tol(k, "mae", 0.0005) and ci[f"{k}|mae"][0] > 0)
    K3 = not any(worse.values())
    K4 = sc["all"]["cov80"] >= 0.75 and d("all", "cov80") >= -0.03
    verdict = "채택 권고" if (K1 and K2 and K3 and K4) else ("기각" if not (K2 and K3 and K4) else "보류")
    return {"K1": bool(K1), "K2": bool(K2), "K3": bool(K3), "K4": bool(K4), "worse": worse, "verdict": verdict,
            "d_lt085_bias": round(d("act_lt0.85", "bias"), 4), "d_mae": round(d("all", "mae"), 4),
            "d_rho": round(d("all", "rho"), 4), "tol_mae": round(tol("all", "mae", 0.0005), 4),
            "tol_rho": round(tol("all", "rho", 0.005), 4)}


def cmd_eval(a):
    import numpy as np
    TR = tr()
    D = dataset()
    n0 = len(D["rows"])
    log(f"base rows {n0}, added candidates {sorted(D['add'])}")
    res = {"n_base": n0, "variants": {v: list(L) for v, L in VARIANTS.items()}, "S1": {}, "S2": {}, "boot": {},
           "judge": {}, "added_levels": {L: {k: r[k] for k in ("seg", "ft_any", "clean_ft_n", "first_try_ended", "gims")}
                                         for L, r in D["add"].items()}}
    R = {}
    for v in VARIANTS:
        R[("S1", v)] = run_oof(D, v, "S1")
        res["S1"][v] = {"eval379": summarize(R[("S1", v)], list(range(n0)))}
        log(f"S1 {v}: 379 MAE {res['S1'][v]['eval379']['all']['mae']} bias<0.85 {res['S1'][v]['eval379']['act_lt0.85']['bias']}")
        if v != "B0":
            R[("S2", v)] = run_oof(D, v, "S2")
            n = len(R[("S2", v)]["rows"])
            res["S2"][v] = {"eval379": summarize(R[("S2", v)], list(range(n0))),
                            "eval_all": summarize(R[("S2", v)], list(range(n))),
                            "eval_added": summarize(R[("S2", v)], list(range(n0, n))),
                            "added_oof": {r["L"]: {"actual": r["ft_any"], "pred": round(float(R[("S2", v)]["oof"][:, n0 + i].mean()), 4)}
                                          for i, r in enumerate(R[("S2", v)]["rows"][n0:])}}
            log(f"S2 {v}: all MAE {res['S2'][v]['eval_all']['all']['mae']}")
    # B0 must reproduce the saved model's K-fold numbers
    man = load(TR.MODELS / TR.DEFAULT_VERSION / "manifest.json")["kfold"]
    b = res["S1"]["B0"]["eval379"]["all"]
    res["B0_reproduces_manifest"] = {"mae_rep_mean": [b["mae_rep_mean"], man["ft_any"]["mae"]],
                                     "cov80": [b["cov80"], man["ft_any_range80"]["coverage"]]}
    assert abs(b["mae_rep_mean"] - man["ft_any"]["mae"]) < 1e-4 and abs(b["cov80"] - man["ft_any_range80"]["coverage"]) < 1e-3, \
        res["B0_reproduces_manifest"]
    for v in VARIANTS:
        if v == "B0":
            continue
        ci = boot_delta(R[("S1", "B0")], R[("S1", v)], n0)
        res["boot"][v] = ci
        res["judge"][v] = judge(res["S1"]["B0"]["eval379"], res["S1"][v]["eval379"], ci)
        log(v, res["judge"][v])
    save(OUT / "compare.json", res)
    (OUT / "compare.md").write_text(render_md(res), encoding="utf-8")
    log("saved", OUT / "compare.json")


def render_md(res):
    lines = []
    keys = ["all"] + [f"act_{b[0]}" for b in ACT_BINS] + [f"seg_{s[0]}" for s in SEGS[:3]]
    lines.append("| 구간 | n | " + " | ".join(f"{v} MAE / 편향" for v in VARIANTS) + " |")
    lines.append("|---|---|" + "---|" * len(VARIANTS))
    for k in keys:
        b = res["S1"]["B0"]["eval379"].get(k)
        if not b:
            continue
        cells = []
        for v in VARIANTS:
            s = res["S1"][v]["eval379"][k]
            cells.append(f"{s['mae']:.4f} / {s['bias']:+.4f}")
        lines.append(f"| {k} | {b['n']} | " + " | ".join(cells) + " |")
    lines.append("")
    for v, j in res["judge"].items():
        lines.append(f"- {v}: {j['verdict']} — K1 {j['K1']} K2 {j['K2']} K3 {j['K3']} K4 {j['K4']}, Δ편향<0.85 {j['d_lt085_bias']:+.4f} "
                     f"CI {res['boot'][v]['act_lt0.85|bias']}, ΔMAE {j['d_mae']:+.4f} (허용 {j['tol_mae']}), Δρ {j['d_rho']:+.4f}")
    return "\n".join(lines) + "\n"


# ── export ──────────────────────────────────────────────────────────────────────────────────────
ADD_REASON = {**{L: "A1: bot v2.4 rows exist; excluded from 379 only by clean_ft_n < 100 (doc 35a §3)" for L in A1},
              **{L: "A2: L501+ low-clear level, newly measured (doc 35a §3, doc 35 §8-3 A2)" for L in A2}}


def build_candidate(D, v):
    import numpy as np
    TR = tr()
    R = run_oof(D, v, "S2")  # OOF over the candidate's own training set → reliability tables (as evaluate())
    rows, X = R["rows"], R["X"]
    y = np.array([r["ft_any"] for r in rows])
    rel = TR.reliability_tables(rows, R["oof"].mean(0), y, R["plo"], R["phi"])
    Y = {h: TR.ytarget(rows, k) for h, k in (("ft_any", "ft_any"), ("unaided_lb", "lb"), ("help_rate", "help"))}
    bot_rows = D["ext_rows"] if any(L in A2 for L in VARIANTS[v]) else D["bot_rows"]
    model, cache, np_pred = TR.fit_export(rows, X, Y, D["expo"], D["af"], D["P"], bot_rows, rel)
    return model, cache, np_pred, rows, R


def cmd_export(a):
    TR = tr()
    D = dataset()
    cmp_ = load(OUT / "compare.json")
    base_dir = TR.MODELS / TR.DEFAULT_VERSION
    active_before = (TR.MODELS / "active.json").read_bytes()
    base_bytes = {f: (base_dir / f).read_bytes() for f in ("model.json", "bot_cache.json", "manifest.json")}
    ok = True
    for v in (a.only.split(",") if a.only else CAND_DIRS):
        model, cache, np_pred, rows, R = build_candidate(D, v)
        model_s, cache_s = TR.dumps(model), TR.dumps(cache)
        out = TR.MODELS / CAND_DIRS[v]
        if a.check:
            same = (model_s == (out / "model.json").read_text(encoding="utf-8"),
                    cache_s == (out / "bot_cache.json").read_text(encoding="utf-8"))
            log(v, "model_json_identical", same[0], "bot_cache_identical", same[1])
            ok &= all(same)
            continue
        pdiff = TR.parity(model, rows, np_pred)
        assert pdiff < 1e-9, pdiff
        base_man = load(base_dir / "manifest.json")
        added = list(VARIANTS[v])
        man = {k: base_man[k] for k in ("target_metric", "target_definition", "aux_targets", "bot_version", "bot_config",
                                        "bot_protocol", "bot_seed_band", "bot_thetas", "bot_games_per_theta",
                                        "bot_seed_rule", "model", "condition_fields", "input_audit", "trust_notes")}
        man.update({
            "model_version": CAND_DIRS[v], "candidate": v, "status": "candidate — NOT active (active.json unchanged); "
            "activation needs separate approval (doc 35 §8-3 A8)",
            "trained_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "base_model": TR.DEFAULT_VERSION,
            "train_levels": [r["L"] for r in rows], "n_levels": len(rows),
            "added_levels": {str(L): {"reason": ADD_REASON[L], "ft_any": D["add"][L]["ft_any"],
                                      "clean_ft_n": D["add"][L]["clean_ft_n"],
                                      "first_try_ended": D["add"][L]["first_try_ended"]} for L in added},
            "excluded_from_candidates": {"L505,L531": "version z significant (doc 35a §3)" if v == "C3" else None,
                                         "L100,L290": "cat-help policy levels (G1) — not added"},
            "version_policy": "AF target pooled over app versions (same as the 379); L505/L531 have significant "
                              "android 1.0.162 vs 1.1.0 unaided first-try z (doc 35a §3) — "
                              + ("excluded" if v == "C3" else "included" if v == "C2" else "not in this candidate"),
            "train_data": {**base_man["train_data"], "n_levels": len(rows),
                           "level_filter": base_man["train_data"]["level_filter"] + " ∪ added_levels (clean_ft_n < 100 "
                           "allowed only for these; first_try_ended ≥ 100 and map_match==same still required)",
                           "a2_bot_rows": "af_calibration/cand_a1a2/bot_v24_rules_A2.json" if any(L in A2 for L in added) else None,
                           "a2_measurement": D["a2_meta"] if any(L in A2 for L in added) else None,
                           "ext_maps": "af_calibration/cand_a1a2/prep_ext.json (build 1.1.0 shard b741f6a3, L501..578)"},
            "support_note": "support.level_range stays [32, 500]: 11 L501+ training levels do not extend the "
                            "served range (doc 35 §2-4, E2c)",
            "kfold_candidate_own_set": {"scheme": "map-hash group 5-fold × 4 (379 folds = RandomState(100+rep); "
                                        "added groups RandomState(200+rep) % 5) — setting S2",
                                        "summary": cmp_["S2"][v]["eval_all"]["all"]},
            "comparison_vs_base": {"setting": "S1 (added levels train-only, eval 379 fixed)",
                                   "eval379": {k: cmp_["S1"][v]["eval379"][k] for k in ("all", "act_lt0.85", "act_ge0.96")},
                                   "judge": cmp_["judge"][v], "doc": "claudedocs/difficulty_personalization/33 §12"},
            "independent_validation": False,
            "parity_max_abs_logit_diff": pdiff,
            "model_json_sha256": hashlib.sha256(model_s.encode()).hexdigest(),
            "bot_cache_sha256": hashlib.sha256(cache_s.encode()).hexdigest(),
        })
        out.mkdir(parents=True, exist_ok=True)
        (out / "model.json").write_text(model_s, encoding="utf-8")
        (out / "bot_cache.json").write_text(cache_s, encoding="utf-8")
        (out / "manifest.json").write_text(json.dumps(man, ensure_ascii=False, indent=1), encoding="utf-8")
        log("saved", out.name, f"n={len(rows)} model {len(model_s) // 1024} KB cache {len(cache_s) // 1024} KB "
            f"({len(cache)} levels) parity {pdiff:.1e}")
    assert (TR.MODELS / "active.json").read_bytes() == active_before, "active.json changed"
    assert all((base_dir / f).read_bytes() == b for f, b in base_bytes.items()), "base model files changed"
    log("active.json and base model files unchanged")
    if a.check:
        print(json.dumps({"candidates_identical": bool(ok)}))
        sys.exit(0 if ok else 1)


def cmd_check_base(a):
    """train_clear_rate_model --check for the active model, with the data paths of this script."""
    TR = tr()
    rows, X, prep, af, bot_rows, LM_doc, expo, _ = TR.build_dataset()
    ev, Y = TR.evaluate(rows, X)
    model, cache, _ = TR.fit_export(rows, X, Y, expo, af, prep, bot_rows, ev["reliability"])
    out = TR.MODELS / TR.DEFAULT_VERSION
    r = {"model_json_identical": TR.dumps(model) == (out / "model.json").read_text(encoding="utf-8"),
         "bot_cache_identical": TR.dumps(cache) == (out / "bot_cache.json").read_text(encoding="utf-8")}
    print(json.dumps(r))
    sys.exit(0 if all(r.values()) else 1)


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("prep").set_defaults(f=cmd_prep)
    sub.add_parser("measure").set_defaults(f=cmd_measure)
    sub.add_parser("eval").set_defaults(f=cmd_eval)
    p = sub.add_parser("export")
    p.add_argument("--check", action="store_true", help="rebuild and compare with the saved candidate files")
    p.add_argument("--only", default="", help="comma list of candidates (C1,C2,C3)")
    p.set_defaults(f=cmd_export)
    sub.add_parser("check-base").set_defaults(f=cmd_check_base)
    a = ap.parse_args()
    a.f(a)


if __name__ == "__main__":
    main()
