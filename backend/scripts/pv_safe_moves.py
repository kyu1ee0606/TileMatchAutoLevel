"""Metric B (safe-move ratio) validation against bot W — doc 11.

  python scripts/pv_safe_moves.py plan                 # stratified level sample (L32-500) + candidate boards
  python scripts/pv_safe_moves.py run [--workers 3]    # compute B per board (resumable, one json per board)
  python scripts/pv_safe_moves.py pilot --levels 1001,1002 [--seeds 2]   # L1001+ unevaluable trial
  python scripts/pv_safe_moves.py analyze              # Spearman / direction agreement / cost -> summary.json

Ground truth = stage-2 bot W (950 games x 2 adaptive θ) already stored in dda_sets/work/NNNN/s2.json.
Reads dda_sets only; writes <sandbox>/safe_moves/ only. Shared core untouched (import only).
"""
from __future__ import annotations

import argparse
import json
import math
import os
import random
import sys
import time
from concurrent.futures import ProcessPoolExecutor, as_completed

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import pv_dda as P  # noqa: E402  (helpers: lj_seed / lj_orig / load / save; import only)

from app.core.pv.safe_moves import analyze_board, analyze_board_info  # noqa: E402

OUT = os.path.join(P.SB, "safe_moves")
ROOT_NODES, WALL_CAP = 20000, 300.0
K_PATHS = int(os.environ.get("PV_SM_K", "3"))             # paths per board (K-boost experiment: 15)
MAX_TILES = int(os.environ.get("PV_SM_MAX_TILES", "999"))  # run only levels below this size (K-boost subset)
NODE_BUDGET = int(os.environ.get("PV_SM_NODES", "3000"))   # per-child solve budget (1000 tried: more UNCERTAIN -> slower)
BOARDS = os.path.join(OUT, ("boards" if NODE_BUDGET == 3000 else f"boards_n{NODE_BUDGET}")
                      + ("" if K_PATHS == 3 else f"_k{K_PATHS}"))
TAG = f"n{NODE_BUDGET}" + ("" if K_PATHS == 3 else f"_k{K_PATHS}")
MAX_CANDS = 12               # orig + chosen tiers + random fill (8~16 per level)
SAMPLE_SEED = 20261013
TILE_BINS = ((0, 50), (50, 70), (70, 90))   # levels ≥ 90 tiles skipped in validation (cost; measured in pilot)
PER_STRATUM = 6
UNTRUSTED_N = 8
METRICS = {"meanSafe": 1, "low10Safe": 1, "bottle1": -1, "bottle2": -1, "log10RandClear": 1}  # sign: +1 = higher is easier
DIR_MIN = 0.05               # |ΔW| needed to count a candidate in direction agreement (≈3σ at 950x2 games)


def wdir(n):
    return os.path.join(P.DDA, "work", f"{n:04d}")


def board_path(n, key):
    return os.path.join(BOARDS, f"{n:04d}_{key.replace(':', '-')}.json")


# ── plan ──────────────────────────────────────────────────────────────────────────────────────
def plan():
    pool = []
    for n in range(32, 501):
        d = wdir(n)
        if not all(os.path.exists(os.path.join(d, f)) for f in ("prep.json", "final.json", "s2.json")):
            continue
        fin, prep, s2 = (P.load(os.path.join(d, f)) for f in ("final.json", "prep.json", "s2.json"))
        if fin["status"] not in ("5tier", "3tier", "no_variant") or "orig" not in s2 or len(s2) < 8:
            continue
        if prep["tileCount"] >= TILE_BINS[-1][1]:
            continue
        pool.append({"level": n, "tiles": prep["tileCount"], "craft": bool(prep.get("craft")),
                     "untrusted": bool(prep.get("solverUnreliable")), "status": fin["status"]})
    rng = random.Random(SAMPLE_SEED)
    chosen = []
    for lo, hi in TILE_BINS:
        for craft in (False, True):
            st = [p for p in pool if not p["untrusted"] and p["craft"] == craft and lo <= p["tiles"] < hi]
            rng.shuffle(st)
            chosen += [{**p, "stratum": f"t{lo}-{hi}{'_craft' if craft else ''}"} for p in st[:PER_STRATUM]]
    unt = [p for p in pool if p["untrusted"]]
    rng.shuffle(unt)
    chosen += [{**p, "stratum": "untrusted"} for p in unt[:UNTRUSTED_N]]
    for c in chosen:
        s2 = P.load(os.path.join(wdir(c["level"]), "s2.json"))
        fin = P.load(os.path.join(wdir(c["level"]), "final.json"))
        tiers = {t: v["key"] for t, v in (fin.get("tiers") or {}).items()}
        keys = ["orig"] + [k for k in tiers.values() if k in s2]
        rest = sorted(k for k in s2 if k not in keys)
        rng.shuffle(rest)
        keys += rest[:MAX_CANDS - len(keys)]
        c["candidates"] = [{"key": k, "tier": next((t for t, v in tiers.items() if v == k), None),
                            "W": s2[k]["W"]} for k in keys]
    P.save(os.path.join(OUT, "plan.json"), {"levels": chosen, "pool": len(pool),
                                            "params": {"k": K_PATHS, "nodeBudget": NODE_BUDGET, "rootNodes": ROOT_NODES,
                                                       "wallCap": WALL_CAP, "maxCands": MAX_CANDS, "seed": SAMPLE_SEED}})
    from collections import Counter
    print("pool", len(pool), "chosen", len(chosen), Counter(c["stratum"] for c in chosen),
          "boards", sum(len(c["candidates"]) for c in chosen))


# ── run ───────────────────────────────────────────────────────────────────────────────────────
def one_board(n, key, k_paths, wall_cap):
    prep = P.load(os.path.join(wdir(n), "prep.json"))
    lj = P.lj_orig(prep) if key == "orig" else P.lj_seed(prep, key)
    try:
        r = analyze_board(lj, k_paths=k_paths, seed=SAMPLE_SEED, node_budget=NODE_BUDGET,
                          root_node_budget=ROOT_NODES, wall_cap_s=wall_cap)
    except Exception as exc:  # noqa: BLE001
        r = {"ok": False, "error": repr(exc)}
    r.update({"level": n, "key": key})
    P.save(board_path(n, key), r)
    return n, key, r.get("ok"), r.get("sec"), r.get("tiles")


def run_tasks(tasks, workers, k_paths, wall_cap):
    os.makedirs(BOARDS, exist_ok=True)
    todo = [(n, k) for n, k in tasks if not os.path.exists(board_path(n, k))]
    print(f"todo {len(todo)} / {len(tasks)}", flush=True)
    t0 = time.time()
    with ProcessPoolExecutor(max_workers=workers) as ex:
        futs = [ex.submit(one_board, n, k, k_paths, wall_cap) for n, k in todo]
        for i, f in enumerate(as_completed(futs), 1):
            n, k, ok, sec, tiles = f.result()
            print(f"[{i}/{len(todo)} {time.time() - t0:.0f}s] L{n} {k} ok={ok} tiles={tiles} sec={sec}", flush=True)


def run(workers):
    pl = P.load(os.path.join(OUT, "plan.json"))
    # small boards first so partial results cover many levels
    lv = sorted((c for c in pl["levels"] if c["tiles"] < MAX_TILES and c["stratum"] != "untrusted"
                 or MAX_TILES == 999), key=lambda c: c["tiles"])
    run_tasks([(c["level"], x["key"]) for c in lv for x in c["candidates"]], workers, K_PATHS, WALL_CAP)


def pilot(levels, seeds, workers, wall_cap):
    tasks = []
    for n in levels:
        prep = P.load(os.path.join(wdir(n), "prep.json"))
        tasks.append((n, "orig"))
        tasks += [(n, f"{prep['utc0']}:{s}") for s in P.pool_seeds(prep, prep["utc0"])[:seeds]]
    run_tasks(tasks, workers, K_PATHS, wall_cap)


# ── analyze ───────────────────────────────────────────────────────────────────────────────────
def ranks(xs):
    order = sorted(range(len(xs)), key=lambda i: xs[i])
    r = [0.0] * len(xs)
    i = 0
    while i < len(xs):
        j = i
        while j + 1 < len(xs) and xs[order[j + 1]] == xs[order[i]]:
            j += 1
        for t in range(i, j + 1):
            r[order[t]] = (i + j) / 2
        i = j + 1
    return r


def spearman(x, y):
    if len(x) < 3:
        return None
    rx, ry = ranks(x), ranks(y)
    mx, my = sum(rx) / len(rx), sum(ry) / len(ry)
    sxy = sum((a - mx) * (b - my) for a, b in zip(rx, ry))
    sxx = sum((a - mx) ** 2 for a in rx)
    syy = sum((b - my) ** 2 for b in ry)
    return sxy / math.sqrt(sxx * syy) if sxx > 0 and syy > 0 else None


def median(xs):
    xs = sorted(xs)
    if not xs:
        return None
    m = len(xs) // 2
    return xs[m] if len(xs) % 2 else (xs[m - 1] + xs[m]) / 2


def analyze():
    pl = P.load(os.path.join(OUT, "plan.json"))
    per_level = []
    for c in pl["levels"]:
        rows = []
        for x in c["candidates"]:
            bp = board_path(c["level"], x["key"])
            if os.path.exists(bp):
                b = P.load(bp)
                rows.append({**x, **{m: b.get(m) for m in list(METRICS) + ["uncertainFrac", "sec", "tiles", "ok",
                                                                         "root", "stuckPaths", "impl"]},
                             "pathVals": {m: [pp[m] for pp in b.get("paths", [])] for m in METRICS}})
        s2 = P.load(os.path.join(wdir(c["level"]), "s2.json"))
        okrows = [r for r in rows if r["ok"]]
        orig = next((r for r in okrows if r["key"] == "orig"), None)
        lvl = {"level": c["level"], "stratum": c["stratum"], "tiles": c["tiles"], "nBoards": len(rows),
               "nOk": len(okrows), "rho": {}, "dir": {}}
        if len(okrows) >= 6 and orig:
            for m, sg in METRICS.items():
                v = [(r[m], r["W"]) for r in okrows if r[m] is not None]
                rho = spearman([sg * a for a, _ in v], [b for _, b in v])
                lvl["rho"][m] = rho
                agree = tie = tot = 0
                for r in okrows:
                    if r["key"] == "orig" or r[m] is None or abs(r["W"] - orig["W"]) < DIR_MIN:
                        continue
                    tot += 1
                    d = sg * (r[m] - orig[m])
                    if d == 0:
                        tie += 1
                    elif (d > 0) == (r["W"] > orig["W"]):
                        agree += 1
                lvl["dir"][m] = {"agree": agree, "tie": tie, "n": tot}
                # reliability of B itself: path 0 vs mean of the other paths, across candidates
                pv = [r["pathVals"][m] for r in okrows if len(r["pathVals"][m]) >= 2 and None not in r["pathVals"][m]]
                lvl.setdefault("relB", {})[m] = spearman([x[0] for x in pv], [sum(x[1:]) / len(x[1:]) for x in pv])
            # reliability of the bot ground truth: W from even vs odd games (same 2 θ)
            def w_half(k, par):
                th = s2[k]["theta"].values()
                return sum(sum(v["wins"][par::2]) / len(v["wins"][par::2]) for v in th) / len(th)
            ks = [r["key"] for r in okrows]
            lvl["relBot"] = spearman([w_half(k, 0) for k in ks], [w_half(k, 1) for k in ks])
            lvl["wSpread"] = max(r["W"] for r in okrows) - min(r["W"] for r in okrows)
        for r in rows:
            r.pop("pathVals", None)
        lvl["boards"] = rows
        per_level.append(lvl)

    def summarize(levels):
        out = {"nLevels": len(levels), "relBotMedian": median([l["relBot"] for l in levels if l.get("relBot") is not None]),
               "wSpreadMedian": median([l["wSpread"] for l in levels if "wSpread" in l])}
        for m in METRICS:
            rh = [l["rho"][m] for l in levels if l["rho"].get(m) is not None]
            dd = [l["dir"][m] for l in levels if m in l["dir"]]
            n, a = sum(d["n"] for d in dd), sum(d["agree"] for d in dd)
            rb = [l["relB"][m] for l in levels if l.get("relB", {}).get(m) is not None]
            out[m + "_relB"] = median(rb)
            out[m] = {"rhoMedian": median(rh), "rhoMean": (sum(rh) / len(rh)) if rh else None, "nRho": len(rh),
                      "rhoPos": sum(1 for x in rh if x > 0), "dirAgree": (a / n) if n else None, "dirN": n,
                      "dirTies": sum(d["tie"] for d in dd)}
        return out

    usable = [l for l in per_level if l["rho"]]
    groups = {"trusted": [l for l in usable if l["stratum"] != "untrusted"],
              "trusted_noCraft": [l for l in usable if l["stratum"] != "untrusted" and "craft" not in l["stratum"]],
              "trusted_craft": [l for l in usable if "craft" in l["stratum"]],
              "untrusted": [l for l in usable if l["stratum"] == "untrusted"]}
    # direction agreement by |ΔW| size, and e2 vs h2 order (trusted levels)
    bins = ((0.05, 0.10), (0.10, 0.20), (0.20, 9.0))
    dir_bins = {m: {f"{lo}-{hi}": [0, 0] for lo, hi in bins} for m in METRICS}
    e2h2 = {m: [0, 0] for m in METRICS}
    for l in groups["trusted"]:
        okb = [b for b in l["boards"] if b["ok"]]
        o = next((b for b in okb if b["key"] == "orig"), None)
        e2 = next((b for b in okb if b["tier"] == "e2"), None)
        h2 = next((b for b in okb if b["tier"] == "h2"), None)
        for m, sg in METRICS.items():
            for b in okb:
                dw = b["W"] - o["W"]
                for lo, hi in bins:
                    if b["key"] != "orig" and lo <= abs(dw) < hi:
                        cell = dir_bins[m][f"{lo}-{hi}"]
                        cell[1] += 1
                        cell[0] += (sg * (b[m] - o[m]) > 0) == (dw > 0)
            if e2 and h2:
                e2h2[m][1] += 1
                e2h2[m][0] += sg * (e2[m] - h2[m]) > 0
    # pairwise seed-vs-seed order (original excluded), by |ΔW|; and original's offset in B rank
    pair = {m: {f"{lo}-{hi}": [0, 0] for lo, hi in bins} for m in METRICS}
    orig_rank = {m: [] for m in METRICS}   # (rank of orig by B) - (rank of orig by W), normalized to [-1, 1]
    for l in groups["trusted"]:
        okb = [b for b in l["boards"] if b["ok"]]
        seeds = [b for b in okb if b["key"] != "orig"]
        for m, sg in METRICS.items():
            for i in range(len(seeds)):
                for j in range(i + 1, len(seeds)):
                    a, b = seeds[i], seeds[j]
                    dw = a["W"] - b["W"]
                    for lo, hi in bins:
                        if lo <= abs(dw) < hi:
                            pair[m][f"{lo}-{hi}"][1] += 1
                            pair[m][f"{lo}-{hi}"][0] += (sg * (a[m] - b[m]) > 0) == (dw > 0)
            rb, rw = ranks([sg * b[m] for b in okb]), ranks([b["W"] for b in okb])
            io = next(i for i, b in enumerate(okb) if b["key"] == "orig")
            orig_rank[m].append((rb[io] - rw[io]) / (len(okb) - 1))
    boards = [b for l in per_level for b in l["boards"] if b["ok"]]
    cost = {}
    for b in boards:
        if b.get("impl") != "fastcopy":
            continue  # cost table: current implementation only
        k = f"{(b['tiles'] // 10) * 10}"
        cost.setdefault(k, []).append(b["sec"])
    summary = {"groups": {g: summarize(v) for g, v in groups.items()},
               "trustedDirByAbsDeltaW": {m: {k: {"agree": a, "n": n, "rate": a / n if n else None} for k, (a, n) in v.items()}
                                         for m, v in dir_bins.items()},
               "trustedPairwiseSeeds": {m: {k: {"agree": a, "n": n, "rate": a / n if n else None} for k, (a, n) in v.items()}
                                        for m, v in pair.items()},
               "trustedOrigRankOffset": {m: {"median": median(v), "mean": sum(v) / len(v) if v else None,
                                             "nBelow": sum(1 for x in v if x < 0), "nAbove": sum(1 for x in v if x > 0)}
                                         for m, v in orig_rank.items()},
               "trustedE2aboveH2": {m: {"agree": a, "n": n} for m, (a, n) in e2h2.items()},
               "rootNotSolvable": {"trusted": sum(1 for l in per_level if l["stratum"] != "untrusted" for b in l["boards"] if b.get("root") not in (None, "S")),
                                   "untrusted": sum(1 for l in per_level if l["stratum"] == "untrusted" for b in l["boards"] if b.get("root") not in (None, "S")),
                                   "boardsTrusted": sum(len(l["boards"]) for l in per_level if l["stratum"] != "untrusted"),
                                   "boardsUntrusted": sum(len(l["boards"]) for l in per_level if l["stratum"] == "untrusted")},
               "boards": len(boards), "boardsFailed": sum(1 for l in per_level for b in l["boards"] if not b["ok"]),
               "uncertainFracMedian": median([b["uncertainFrac"] for b in boards if b["uncertainFrac"] is not None]),
               "uncertainFracMax": max([b["uncertainFrac"] or 0 for b in boards], default=None),
               "costByTiles": {k: {"n": len(v), "median": median(v), "max": max(v)} for k, v in sorted(cost.items(), key=lambda kv: int(kv[0]))},
               "perLevel": [{k: v for k, v in l.items() if k != "boards"} for l in per_level]}
    P.save(os.path.join(OUT, f"summary_{TAG}.json"), summary)
    print(json.dumps({k: v for k, v in summary.items() if k != "perLevel"}, ensure_ascii=False, indent=1))


# ── information-limited B′ (doc 11 §8) ────────────────────────────────────────────────────────────
INFO_DIR = os.path.join(OUT, "boards_info")
INFO_CFG = {"k_paths": 2, "points_per_path": 8, "m_worlds": 6, "thr": 0.8, "wall_cap_s": 900.0, "world_node_budget": 300}
INFO_METRICS = ["B", "B_nonTrivial", "B_sampled", "Bp_occluded", "Bp_covered"]   # all: higher = easier


def info_path(n, key):
    return os.path.join(INFO_DIR, f"{n:04d}_{key.replace(':', '-')}.json")


def one_board_info(n, key):
    prep = P.load(os.path.join(wdir(n), "prep.json"))
    lj = P.lj_orig(prep) if key == "orig" else P.lj_seed(prep, key)
    try:
        r = analyze_board_info(lj, seed=SAMPLE_SEED, node_budget=NODE_BUDGET, root_node_budget=ROOT_NODES, **INFO_CFG)
    except Exception as exc:  # noqa: BLE001
        r = {"ok": False, "error": repr(exc)}
    r.update({"level": n, "key": key})
    P.save(info_path(n, key), r)
    return n, key, r.get("ok"), r.get("sec"), r.get("tiles")


def run_info(tasks, workers):
    os.makedirs(INFO_DIR, exist_ok=True)
    todo = [(n, k) for n, k in tasks if not os.path.exists(info_path(n, k))]
    print(f"todo {len(todo)} / {len(tasks)}", flush=True)
    t0 = time.time()
    with ProcessPoolExecutor(max_workers=workers) as ex:
        futs = [ex.submit(one_board_info, n, k) for n, k in todo]
        for i, f in enumerate(as_completed(futs), 1):
            n, k, ok, sec, tiles = f.result()
            print(f"[{i}/{len(todo)} {time.time() - t0:.0f}s] L{n} {k} ok={ok} tiles={tiles} sec={sec}", flush=True)


def analyze_info():
    pl = P.load(os.path.join(OUT, "plan.json"))
    levels = []
    for c in pl["levels"]:
        if c["stratum"] == "untrusted":
            continue
        rows = []
        for x in c["candidates"]:
            bp = info_path(c["level"], x["key"])
            if os.path.exists(bp):
                b = P.load(bp)
                if b.get("ok"):
                    rows.append({**x, **{m: b.get(m) for m in INFO_METRICS + ["B_sat1", "B_ntSat1", "Bp_occluded_sat1",
                                                                          "Bp_covered_sat1", "Bp_occluded_unc",
                                                                          "Bp_covered_unc", "Bp_occluded_hidden",
                                                                          "Bp_covered_hidden", "immFrac", "sec", "tiles"]},
                                 "pv": {m: [pp.get(m) for pp in b["paths"]] for m in INFO_METRICS}})
        orig = next((r for r in rows if r["key"] == "orig"), None)
        if len(rows) < 6 or not orig:
            continue
        lv = {"level": c["level"], "stratum": c["stratum"], "n": len(rows), "rho": {}, "dir": {}, "rel": {}}
        for m in INFO_METRICS:
            v = [r for r in rows if r[m] is not None]
            lv["rho"][m] = spearman([r[m] for r in v], [r["W"] for r in v])
            a = n = 0
            for r in v:
                if r["key"] != "orig" and orig[m] is not None and abs(r["W"] - orig["W"]) >= DIR_MIN:
                    n += 1
                    a += (r[m] - orig[m] > 0) == (r["W"] > orig["W"])
            lv["dir"][m] = (a, n)
            pv = [r["pv"][m] for r in v if len(r["pv"][m]) >= 2 and None not in r["pv"][m][:2]]
            lv["rel"][m] = spearman([x[0] for x in pv], [x[1] for x in pv])
        lv["rows"] = rows
        levels.append(lv)

    def summ(ls):
        o = {"nLevels": len(ls)}
        for m in INFO_METRICS:
            rh = [l["rho"][m] for l in ls if l["rho"][m] is not None]
            a = sum(l["dir"][m][0] for l in ls)
            n = sum(l["dir"][m][1] for l in ls)
            o[m] = {"rhoMedian": median(rh), "rhoPos": sum(1 for x in rh if x > 0), "nRho": len(rh),
                    "dirAgree": a / n if n else None, "dirN": n,
                    "relPathSplit": median([l["rel"][m] for l in ls if l["rel"][m] is not None])}
        return o

    rows = [r for l in levels for r in l["rows"]]
    dist = {k: {"median": median([r[k] for r in rows if r[k] is not None]),
                "p10": sorted(r[k] for r in rows if r[k] is not None)[len(rows) // 10] if rows else None,
                "p90": sorted(r[k] for r in rows if r[k] is not None)[len(rows) * 9 // 10] if rows else None}
            for k in INFO_METRICS + ["B_sat1", "B_ntSat1", "Bp_occluded_sat1", "Bp_covered_sat1", "Bp_occluded_unc",
                                     "Bp_covered_unc", "Bp_occluded_hidden", "Bp_covered_hidden", "immFrac"]}
    cost = {}
    for r in rows:
        cost.setdefault(str((r["tiles"] // 10) * 10), []).append(r["sec"])
    res = {"config": INFO_CFG, "all": summ(levels), "noCraft": summ([l for l in levels if "craft" not in l["stratum"]]),
           "craft": summ([l for l in levels if "craft" in l["stratum"]]), "dist": dist, "boards": len(rows),
           "cost": {k: {"n": len(v), "median": median(v), "max": max(v)} for k, v in sorted(cost.items(), key=lambda kv: int(kv[0]))},
           "perLevel": [{k: v for k, v in l.items() if k != "rows"} for l in levels]}
    P.save(os.path.join(OUT, "summary_info.json"), res)
    print(json.dumps({k: v for k, v in res.items() if k != "perLevel"}, ensure_ascii=False, indent=1))


def kcurve(ks=(1, 3, 5, 10, 15)):
    """Paired K effect on the K-boost boards: metric = mean over the first k paths (log-mean-exp for (e))."""
    pl = P.load(os.path.join(OUT, "plan.json"))
    res = {}
    for k in ks:
        per = {m: {"rho": [], "agree": 0, "n": 0} for m in METRICS}
        nlev = 0
        for c in pl["levels"]:
            rows = []
            for x in c["candidates"]:
                bp = board_path(c["level"], x["key"])
                if os.path.exists(bp) and P.load(bp).get("ok"):
                    b = P.load(bp)
                    vals = {}
                    for m in METRICS:
                        v = [pp[m] for pp in b["paths"][:k] if pp[m] is not None]
                        if m == "log10RandClear":
                            vals[m] = math.log10(sum(10 ** a for a in v) / len(v)) if v else None
                        else:
                            vals[m] = sum(v) / len(v) if v else None
                    rows.append({**x, **vals})
            orig = next((r for r in rows if r["key"] == "orig"), None)
            if len(rows) < 6 or not orig or len(rows) < len(c["candidates"]):
                continue
            nlev += 1
            for m, sg in METRICS.items():
                rho = spearman([sg * r[m] for r in rows], [r["W"] for r in rows])
                if rho is not None:
                    per[m]["rho"].append(rho)
                for r in rows:
                    if r["key"] != "orig" and abs(r["W"] - orig["W"]) >= DIR_MIN:
                        per[m]["n"] += 1
                        per[m]["agree"] += (sg * (r[m] - orig[m]) > 0) == (r["W"] > orig["W"])
        res[k] = {"nLevels": nlev, **{m: {"rhoMedian": median(v["rho"]), "dirAgree": v["agree"] / v["n"] if v["n"] else None,
                                         "dirN": v["n"]} for m, v in per.items()}}
    P.save(os.path.join(OUT, f"kcurve_{TAG}.json"), res)
    for k, v in res.items():
        print(k, v["nLevels"], {m: (round(x["rhoMedian"], 2) if x["rhoMedian"] is not None else None,
                                   round(x["dirAgree"], 2) if x["dirAgree"] is not None else None)
                               for m, x in v.items() if m != "nLevels"})


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["plan", "run", "pilot", "analyze", "kcurve", "run_info", "pilot_info", "analyze_info"])
    ap.add_argument("--workers", type=int, default=3)
    ap.add_argument("--levels", default="")
    ap.add_argument("--seeds", type=int, default=0)
    ap.add_argument("--wall", type=float, default=WALL_CAP)
    a = ap.parse_args()
    if a.cmd == "plan":
        plan()
    elif a.cmd == "run":
        run(min(a.workers, 3))
    elif a.cmd == "pilot":
        pilot([int(x) for x in a.levels.split(",") if x], a.seeds, min(a.workers, 3), a.wall)
    elif a.cmd == "run_info":
        pl = P.load(os.path.join(OUT, "plan.json"))
        lv = sorted((c for c in pl["levels"] if c["stratum"] != "untrusted"), key=lambda c: c["tiles"])
        run_info([(c["level"], x["key"]) for c in lv for x in c["candidates"]], min(a.workers, 3))
    elif a.cmd == "pilot_info":
        tasks = []
        for n in [int(x) for x in a.levels.split(",") if x]:
            prep = P.load(os.path.join(wdir(n), "prep.json"))
            tasks += [(n, "orig")] + [(n, f"{prep['utc0']}:{s}") for s in P.pool_seeds(prep, prep["utc0"])[:a.seeds]]
        run_info(tasks, min(a.workers, 3))
    elif a.cmd == "analyze_info":
        analyze_info()
    elif a.cmd == "kcurve":
        kcurve()
    else:
        analyze()


if __name__ == "__main__":
    main()
