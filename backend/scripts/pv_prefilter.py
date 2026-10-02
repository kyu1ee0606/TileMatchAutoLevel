"""P1 extension: placement-feature pre-filter study.

Stages (files <sandbox>/eval/<level>/<stage>.json, skip if present):
  feat   features for a pool of 256 candidate seeds (first 32 == stage-1 seeds) + "bot-lite"
         (2 games at θ=0.65 with fixed bot seeds, progress fraction)
  corr   (global, no --level) per-level Spearman(feature, stage-1 W) on the 32 stage-1 seeds and on the
         stage-2 shortlist; leave-one-level-out choice of the filter score -> <sandbox>/prefilter_corr.json
  fs2    filter pipeline for one level: stratify the 256 pool by the held-out score, pick 11 seeds,
         stage-2 bot evaluation (same bot streams as orig/s2), solver for picks without wins
  fsel   5-seed selection on the filter picks (same final rules as the current pipeline)

Usage:
  python scripts/pv_prefilter.py --level 55 --stage feat
  python scripts/pv_prefilter.py --stage corr
  python scripts/pv_prefilter.py --level 55 --stage fs2
"""
from __future__ import annotations

import argparse
import json
import math
import os
import statistics as st
import sys
import time
from concurrent.futures import ProcessPoolExecutor

BACKEND = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BACKEND)

from app.core.pv.cs_shuffle import resolve_map, shuffle_empty_tiles  # noqa: E402
from app.core.pv.evaluate import candidate_seeds, evaluate_maps, run_games_task, solve_check  # noqa: E402
from app.core.pv.features import compute_features  # noqa: E402
from app.core.pv.select import any_win, final_select, quantile  # noqa: E402
from app.core.pv.t0ize import bot_level_json  # noqa: E402

POOL = 256
PICKS = 11
PICK_Q = [0.02, 0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 0.98]
BOTLITE_THETA, BOTLITE_GAMES, BOTLITE_SEED = 0.65, 2, 7_000_000
SEED_S2, S2_GAMES, SOLVER_NODES, WORKERS = 2_000_000, 400, 5000, 8


def sb_dir(copy_id):
    return os.path.join(BACKEND, "data", "pv_sandbox", copy_id)


def load(p):
    with open(p, encoding="utf-8") as f:
        return json.load(f)


def save(p, obj):
    tmp = p + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, separators=(",", ":"))
    os.replace(tmp, p)


def resolved_and_lj(t0, seed):
    row = {**t0["row"], "randSeed": str(seed)}
    res = shuffle_empty_tiles(row["map"], rand_seed=seed, use_tile_count=row["useTileCount"], strict=True)
    rm = resolve_map(row["map"], res)
    return rm, bot_level_json(row, rm)


def _feat_task(args):
    t0, seeds = args
    out = {}
    for s in seeds:
        rm, lj = resolved_and_lj(t0, s)
        f = compute_features(rm)
        # bot-lite: progress fraction over 2 fixed games at θ 0.65
        r = run_games_task({"key": str(s), "theta": BOTLITE_THETA, "level_json": lj,
                            "seed_base": BOTLITE_SEED, "start": 0, "count": BOTLITE_GAMES})
        f["botLiteWins"] = sum(r["wins"])
        f["botLiteDockMax"] = sum(r["dockMax"]) / len(r["dockMax"])
        f["botLiteCrisis"] = sum(r["crisisFrac"]) / len(r["crisisFrac"])
        out[str(s)] = f
    return out


def rank(xs):
    order = sorted(range(len(xs)), key=lambda i: xs[i])
    r = [0.0] * len(xs)
    i = 0
    while i < len(xs):
        j = i
        while j + 1 < len(xs) and xs[order[j + 1]] == xs[order[i]]:
            j += 1
        for k in range(i, j + 1):
            r[order[k]] = (i + j) / 2 + 1
        i = j + 1
    return r


def spearman(a, b):
    if len(a) < 3:
        return None
    ra, rb = rank(a), rank(b)
    ma, mb = sum(ra) / len(ra), sum(rb) / len(rb)
    sa = math.sqrt(sum((x - ma) ** 2 for x in ra))
    sb = math.sqrt(sum((y - mb) ** 2 for y in rb))
    if sa == 0 or sb == 0:
        return None
    return sum((x - ma) * (y - mb) for x, y in zip(ra, rb)) / (sa * sb)


def zscores(vals):
    m = sum(vals) / len(vals)
    sd = math.sqrt(sum((v - m) ** 2 for v in vals) / len(vals)) or 1.0
    return [(v - m) / sd for v in vals]


def stage_feat(sb, level, ex):
    d = os.path.join(sb, "eval", f"{level:04d}")
    p = os.path.join(d, "feat.json")
    if os.path.exists(p):
        return f"skip {level} feat"
    t0 = load(os.path.join(sb, "t0", f"{level:04d}.json"))
    pool = candidate_seeds(t0["meta"]["structHash"], POOL)
    assert pool[:32] == t0["candidateSeeds"], "pool prefix must equal stage-1 seeds"
    started = time.time()
    chunks = [pool[i:i + 16] for i in range(0, POOL, 16)]
    feats = {}
    for part in ex.map(_feat_task, [(t0, c) for c in chunks]):
        feats.update(part)
    # placement-only timing (single process, no bot-lite) for the cost table
    t1 = time.time()
    for s in pool[:32]:
        rm, _ = resolved_and_lj(t0, s)
        compute_features(rm)
    ms_per_seed = (time.time() - t1) / 32 * 1000
    save(p, {"level": level, "pool": pool, "features": feats, "wallSec": round(time.time() - started, 2),
             "placementMsPerSeed": round(ms_per_seed, 2)})
    return f"done {level} feat wall={time.time() - started:.1f}s place={ms_per_seed:.1f}ms/seed"


def stage_corr(sb, levels):
    per_level = {}
    for n in levels:
        d = os.path.join(sb, "eval", f"{n:04d}")
        if not all(os.path.exists(os.path.join(d, f)) for f in ("feat.json", "s1.json", "s2.json")):
            continue
        feat = load(os.path.join(d, "feat.json"))["features"]
        s1 = load(os.path.join(d, "s1.json"))["results"]
        s2 = load(os.path.join(d, "s2.json"))["results"]
        names = sorted(next(iter(feat.values())).keys())
        seeds1 = list(s1.keys())
        w1 = [s1[s]["W"] for s in seeds1]
        seeds2 = list(s2.keys())
        w2 = [s2[s]["W"] for s in seeds2]
        per_level[n] = {
            "s1": {f: spearman([feat[s][f] for s in seeds1], w1) for f in names},
            "s2": {f: spearman([feat[s][f] for s in seeds2], w2) for f in names},
            "featMedian": {f: st.median(feat[s][f] for s in feat) for f in names},
            "w1Flat": max(w1) - min(w1) < 1e-9,
        }
    names = sorted({f for v in per_level.values() for f in v["s1"]})

    def summary(f, lv_set):
        vals = [per_level[n]["s1"][f] for n in lv_set if per_level[n]["s1"][f] is not None]
        return (st.median(vals) if vals else None), vals

    feat_summary = {}
    for f in names:
        med, vals = summary(f, per_level)
        feat_summary[f] = {
            "medianRho_s1": med,
            "nLevels": len(vals),
            "nAbsRhoGe04": sum(1 for v in vals if abs(v) >= 0.4),
            "nSameSignAsMedian": sum(1 for v in vals if med is not None and v * med > 0),
            "medianRho_s2": st.median([per_level[n]["s2"][f] for n in per_level if per_level[n]["s2"][f] is not None] or [0]),
        }
    # leave-one-level-out score choice: best single feature by |median rho| on the other levels,
    # plus composite = mean of oriented z-scores of the top-3 features.
    loo = {}
    for n in per_level:
        others = [m for m in per_level if m != n and not per_level[m]["w1Flat"]]
        meds = {}
        for f in names:
            vals = [per_level[m]["s1"][f] for m in others if per_level[m]["s1"][f] is not None]
            if vals:
                meds[f] = st.median(vals)
        top = sorted(meds, key=lambda f: -abs(meds[f]))[:3]
        loo[n] = {"best": top[0], "bestSign": 1 if meds[top[0]] > 0 else -1,
                  "top3": [(f, 1 if meds[f] > 0 else -1) for f in top]}
    # how well do held-out scores rank the 32 stage-1 seeds of the held-out level?
    for n, sel in loo.items():
        d = os.path.join(sb, "eval", f"{n:04d}")
        feat = load(os.path.join(d, "feat.json"))["features"]
        s1 = load(os.path.join(d, "s1.json"))["results"]
        seeds1 = list(s1.keys())
        w1 = [s1[s]["W"] for s in seeds1]
        sel["heldOutRho_best"] = spearman([sel["bestSign"] * feat[s][sel["best"]] for s in seeds1], w1)
        comp = composite(feat, seeds1, sel["top3"])
        sel["heldOutRho_composite"] = spearman(comp, w1)
    out = {"perLevel": per_level, "features": feat_summary, "loo": loo}
    save(os.path.join(sb, "prefilter_corr.json"), out)
    return out


def composite(feat, seeds, top3):
    cols = []
    for f, sign in top3:
        cols.append(zscores([sign * feat[s][f] for s in seeds]))
    return [sum(c[i] for c in cols) / len(cols) for i in range(len(seeds))]


def stage_fs2(sb, level, ex):
    d = os.path.join(sb, "eval", f"{level:04d}")
    p = os.path.join(d, "fs2.json")
    if os.path.exists(p):
        return f"skip {level} fs2"
    corr = load(os.path.join(sb, "prefilter_corr.json"))
    sel = corr["loo"][str(level)]
    use = "composite" if (sel.get("heldOutRho_composite") or -9) >= (sel.get("heldOutRho_best") or -9) else "best"
    t0 = load(os.path.join(sb, "t0", f"{level:04d}.json"))
    feat = load(os.path.join(d, "feat.json"))
    pool = [str(s) for s in feat["pool"]]
    f = feat["features"]
    score = composite(f, pool, sel["top3"]) if use == "composite" else [sel["bestSign"] * f[s][sel["best"]] for s in pool]
    order = sorted(range(len(pool)), key=lambda i: (score[i], int(pool[i])))
    picks = []
    for q in PICK_Q:
        idx = order[min(len(order) - 1, int(round(q * (len(order) - 1))))]
        j = order.index(idx)
        while pool[order[j]] in picks and j + 1 < len(order):
            j += 1
        picks.append(pool[order[j]])
    started = time.time()
    maps = {s: resolved_and_lj(t0, int(s))[1] for s in picks}
    out = evaluate_maps(ex, maps, S2_GAMES, SEED_S2)
    cpu = out.pop("_cpuSec", 0.0)
    need = [s for s in picks if not any_win(out[s])]
    futs = {s: ex.submit(solve_check, maps[s], SOLVER_NODES) for s in need}
    solved = {s: fu.result() for s, fu in futs.items()}
    save(p, {"level": level, "scoreUsed": use, "scoreDef": sel, "picks": picks,
             "pickScores": {pool[i]: score[i] for i in range(len(pool)) if pool[i] in picks},
             "results": out, "solved": solved, "cpuSec": cpu, "wallSec": round(time.time() - started, 2)})
    return f"done {level} fs2 wall={time.time() - started:.1f}s cpu={cpu:.0f}s"


def stage_fsel(sb, level):
    d = os.path.join(sb, "eval", f"{level:04d}")
    p = os.path.join(d, "fsel.json")
    fs2 = load(os.path.join(d, "fs2.json"))
    orig = load(os.path.join(d, "orig.json"))["results"]["orig"]
    ev = fs2["results"]
    w = {s: e["W"] for s, e in ev.items()}
    # base: within the 25–75% band of the picks' W, closest to W_orig (no stage-1 data in this pipeline)
    lo, hi = quantile(list(w.values()), 0.25), quantile(list(w.values()), 0.75)
    band = [s for s in w if lo <= w[s] <= hi and any_win(ev[s])] or [s for s in w if lo <= w[s] <= hi]
    base = min(band, key=lambda s: (abs(w[s] - orig["W"]), int(s)))
    verified = {s: any_win(ev[s]) or fs2["solved"].get(s, {}).get("verdict") == "PROVEN_SOLVABLE" for s in ev}
    easy = [s for s in w if w[s] > w[base]]
    hard = [s for s in w if w[s] < w[base]]
    fs = final_select(base, easy, hard, ev, verified)
    picked = {t: {"seed": int(s), "W2": w[s]} for t, s in fs["seeds"]}
    out = {"level": level, "status": fs["status"], "collapsed": fs["collapsed"], "picked": picked,
           "wOrig": orig["W"], "baseShift": w[base] - orig["W"],
           "pickWRange": [min(w.values()), max(w.values())],
           "finalRange": picked["e2"]["W2"] - picked["h2"]["W2"]}
    save(p, out)
    return f"done {level} fsel {fs['status']} range={out['finalRange']:.3f}"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--copy-id", default="pv_20261002_live3")
    ap.add_argument("--level", type=int)
    ap.add_argument("--stage", required=True, choices=["feat", "corr", "fs2", "fsel"])
    args = ap.parse_args()
    sb = sb_dir(args.copy_id)
    if args.stage == "corr":
        levels = [s["level"] for s in load(os.path.join(sb, "sample.json"))["sample"]]
        out = stage_corr(sb, levels)
        print(json.dumps(out["features"], ensure_ascii=False, indent=1))
        print(json.dumps({n: {k: v for k, v in x.items() if k != "top3"} for n, x in out["loo"].items()}, ensure_ascii=False))
        return 0
    if args.stage == "fsel":
        print(stage_fsel(sb, args.level))
        return 0
    with ProcessPoolExecutor(max_workers=WORKERS) as ex:
        fn = stage_feat if args.stage == "feat" else stage_fs2
        print(fn(sb, args.level, ex), flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
