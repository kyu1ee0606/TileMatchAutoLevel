"""P1 pilot runner — one (level, stage) per call so every command stays short and resumable.

Stages (files: <sandbox>/eval/<level>/<stage>.json, existing files are skipped):
  s1    K candidate seeds × θ3 × 64 games (CRN, early termination off)
  orig  original explicit map × θ3 × 400 games (stage-2 bot streams)
  s2    shortlist (base + easy/hard ≤4 each) × θ3 × 400 games (same streams as orig, independent of s1)
  rep   base seed × 4 independent replicates × θ3 × 400 games (measurement noise, P1 only)
  solve solver (node budget) for shortlisted seeds without any bot win
  sel   final 5-seed selection

Usage:
  python scripts/pv_run_pilot.py --level 55 --stage s1
  python scripts/pv_run_pilot.py --level 55 --stage all      # all missing stages for one level
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from concurrent.futures import ProcessPoolExecutor

BACKEND = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BACKEND)

from app.core.pv.canonical import canonical_map  # noqa: E402
from app.core.pv.cs_shuffle import resolve_map, shuffle_empty_tiles  # noqa: E402
from app.core.pv.evaluate import EVAL_VERSION, THETAS, evaluate_maps, solve_check  # noqa: E402
from app.core.pv.select import any_win, crn_corr, final_select, shortlist  # noqa: E402
from app.core.pv.t0ize import bot_level_json  # noqa: E402

S1_GAMES, S2_GAMES, REPS = 64, 400, 4
SEED_S1, SEED_S2, SEED_REP = 1_000_000, 2_000_000, 3_000_000
SOLVER_NODES = 5000
WORKERS = 8
STAGES = ["s1", "orig", "s2", "rep", "solve", "sel"]


def sandbox(copy_id: str) -> str:
    return os.path.join(BACKEND, "data", "pv_sandbox", copy_id)


def load(path: str):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def save(path: str, obj) -> None:
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, separators=(",", ":"))
    os.replace(tmp, path)


def seed_lj(t0: dict, seed: int) -> dict:
    row = {**t0["row"], "randSeed": str(seed)}
    res = shuffle_empty_tiles(row["map"], rand_seed=seed, use_tile_count=row["useTileCount"], strict=True)
    return bot_level_json(row, resolve_map(row["map"], res))


def orig_lj(sb: str, level: int, t0: dict) -> dict:
    src = load(os.path.join(sb, "source.json"))
    lv = next(x for x in src["levels"] if x["meta"].get("level_number") == level)
    canon = canonical_map(lv["level_json"])
    o = t0["orig"]
    return bot_level_json({"randSeed": o.get("randSeed") or 1, "useTileCount": o.get("useTileCount") or 6,
                           "unlockTile": 0}, canon)


def strip_cpu(out: dict) -> float:
    return out.pop("_cpuSec", 0.0)


def run_stage(copy_id: str, level: int, stage: str, ex) -> str:
    sb = sandbox(copy_id)
    d = os.path.join(sb, "eval", f"{level:04d}")
    os.makedirs(d, exist_ok=True)
    path = os.path.join(d, f"{stage}.json")
    if os.path.exists(path):
        return f"skip {level} {stage}"
    t0 = load(os.path.join(sb, "t0", f"{level:04d}.json"))
    started = time.time()
    meta = {"level": level, "stage": stage, "evalVer": EVAL_VERSION, "thetas": list(THETAS)}

    if stage == "s1":
        maps = {str(s): seed_lj(t0, s) for s in t0["candidateSeeds"]}
        out = evaluate_maps(ex, maps, S1_GAMES, SEED_S1)
        meta.update(games=S1_GAMES, seedBase=SEED_S1, cpuSec=strip_cpu(out), results=out)
    elif stage == "orig":
        out = evaluate_maps(ex, {"orig": orig_lj(sb, level, t0)}, S2_GAMES, SEED_S2)
        meta.update(games=S2_GAMES, seedBase=SEED_S2, cpuSec=strip_cpu(out), results=out)
    elif stage == "s2":
        s1 = load(os.path.join(d, "s1.json"))["results"]
        w_orig = load(os.path.join(d, "orig.json"))["results"]["orig"]["W"]
        sl = shortlist(s1, w_orig)
        keys = [sl["base"]] + sl["easy"] + sl["hard"]
        out = evaluate_maps(ex, {s: seed_lj(t0, int(s)) for s in keys}, S2_GAMES, SEED_S2)
        meta.update(games=S2_GAMES, seedBase=SEED_S2, cpuSec=strip_cpu(out), shortlist=sl, results=out)
    elif stage == "rep":
        sl = load(os.path.join(d, "s2.json"))["shortlist"]
        lj = seed_lj(t0, int(sl["base"]))
        reps = []
        cpu = 0.0
        for r in range(REPS):
            out = evaluate_maps(ex, {"base": lj}, S2_GAMES, SEED_REP + r * 100_000)
            cpu += strip_cpu(out)
            reps.append({"seedBase": SEED_REP + r * 100_000, "W": out["base"]["W"],
                         "perTheta": {t: v["rate"] for t, v in out["base"]["theta"].items()}})
        meta.update(games=S2_GAMES, base=sl["base"], cpuSec=cpu, replicates=reps)
    elif stage == "solve":
        s1 = load(os.path.join(d, "s1.json"))["results"]
        s2f = load(os.path.join(d, "s2.json"))
        s2, sl = s2f["results"], s2f["shortlist"]
        need = [s for s in [sl["base"]] + sl["easy"] + sl["hard"] if not any_win(s1.get(s), s2.get(s))]
        futs = {s: ex.submit(solve_check, seed_lj(t0, int(s)), SOLVER_NODES) for s in need}
        meta.update(nodeBudget=SOLVER_NODES, solved={s: f.result() for s, f in futs.items()})
    elif stage == "sel":
        s1 = load(os.path.join(d, "s1.json"))["results"]
        s2f = load(os.path.join(d, "s2.json"))
        s2, sl = s2f["results"], s2f["shortlist"]
        solved = load(os.path.join(d, "solve.json"))["solved"]
        orig = load(os.path.join(d, "orig.json"))["results"]["orig"]
        verified = {s: any_win(s1.get(s), s2.get(s)) or solved.get(s, {}).get("verdict") == "PROVEN_SOLVABLE"
                    for s in s2}
        fs = final_select(sl["base"], sl["easy"], sl["hard"], s2, verified)
        base = sl["base"]
        w1, w2 = sl["w1"], {s: e["W"] for s, e in s2.items()}
        picked = {}
        for tier, s in fs["seeds"]:
            e = s2[s]
            picked[tier] = {
                "seed": int(s), "W1": w1[s], "W2": e["W"],
                "perTheta": {t: v["rate"] for t, v in e["theta"].items()},
                "dockMaxMean": {t: round(v["dockMaxMean"], 3) for t, v in e["theta"].items()},
                "crisisGameRate": {t: round(v["crisisGameRate"], 3) for t, v in e["theta"].items()},
                "verified": verified.get(s),
                "regression": (None if s == base or w1[s] == w1[base]
                               else (w2[s] - w2[base]) / (w1[s] - w1[base])),
            }
        rhos = [crn_corr(s2[base], s2[s]) for s in s2 if s != base]
        rhos = [r for r in rhos if r is not None]
        meta.update(
            status=fs["status"], collapsed=fs["collapsed"], picked=picked, log=fs["log"],
            wOrig=orig["W"], baseShift=w2[base] - orig["W"],
            s1Spread={"min": min(w1.values()), "q25": sl["band"][0], "q75": sl["band"][1], "max": max(w1.values())},
            s1DeltaVsOrig=sorted(round(v - orig["W"], 4) for v in w1.values()),
            s1Unverified=sum(1 for s, e in s1.items() if not any_win(e)),
            crnRhoMean=(sum(rhos) / len(rhos)) if rhos else None,
            pv={"v": 1, "mode": "seed", "structHash": t0["meta"]["structHash"], "utc": t0["meta"]["utc0"],
                "status": fs["status"], "collapsed": fs["collapsed"],
                "seeds": [{"tier": tier, "seed": int(s)} for tier, s in fs["seeds"]]},
        )
    else:
        raise SystemExit(f"unknown stage {stage}")

    meta["wallSec"] = round(time.time() - started, 2)
    save(path, meta)
    return f"done {level} {stage} wall={meta['wallSec']}s cpu={round(meta.get('cpuSec', 0), 1)}s"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--copy-id", default="pv_20261002_live3")
    ap.add_argument("--level", type=int, required=True)
    ap.add_argument("--stage", default="all", choices=STAGES + ["all"])
    args = ap.parse_args()
    stages = STAGES if args.stage == "all" else [args.stage]
    with ProcessPoolExecutor(max_workers=WORKERS) as ex:
        for st in stages:
            print(run_stage(args.copy_id, args.level, st, ex), flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
