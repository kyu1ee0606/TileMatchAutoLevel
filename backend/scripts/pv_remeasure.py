"""P1 re-measure (06 §8): adaptive θ + bidirectional 5 seeds (base + 2 easy + 2 hard).

User rules (2026-10-02): both directions required, asymmetric spacing allowed, no duplicate/flat filling;
when a side cannot be filled, grow the candidate pool 32 -> 64 -> 128, else mark "bidirectional unmet"
and keep the original explicit map. Shared core (bot_simulator) untouched; avoid θ trough [0.34, 0.50).

Each call runs ONE missing step for one level and exits (short, resumable):
  python scripts/pv_remeasure.py --pick                 # write <sandbox>/sample2.json (20 old + 10 new 32~800)
  python scripts/pv_remeasure.py --level 55 --next      # run next step; prints "LEVEL_DONE" when finished
Files: <sandbox>/eval2/<level>/{prep,golden,scan,orig2,s1_p32,s2_p32,solve_p32,sel_p32,s1_p64,...}.json
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from concurrent.futures import ProcessPoolExecutor

BACKEND = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REPO = os.path.dirname(BACKEND)
sys.path.insert(0, BACKEND)
sys.path.insert(0, os.path.join(BACKEND, "scripts"))

from app.core.pv.canonical import canonical_map  # noqa: E402
from app.core.pv.cs_shuffle import CTile, resolve_map, shuffle_empty_tiles  # noqa: E402
from app.core.pv.evaluate import candidate_seeds, evaluate_maps, solve_check  # noqa: E402
from app.core.pv.select import (  # noqa: E402
    SCAN_THETAS, any_win, base_pick, bidirectional_select, choose_thetas, staircase_shortlist,
)
from app.core.pv.t0ize import bot_level_json, t0ize_level  # noqa: E402

COPY = "pv_20261002_live3"
POOLS = (32, 64, 128)
SCAN_GAMES, S1_GAMES, S2_GAMES = 64, 64, 950
SEED_SCAN, SEED_S1, SEED_S2 = 5_000_000, 6_000_000, 7_000_000
SOLVER_NODES, WORKERS = 5000, 8


def sb():
    return os.path.join(BACKEND, "data", "pv_sandbox", COPY)


def load(p):
    with open(p, encoding="utf-8") as f:
        return json.load(f)


def save(p, obj):
    tmp = p + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, separators=(",", ":"))
    os.replace(tmp, p)


def source_levels():
    return {lv["meta"]["level_number"]: lv for lv in load(os.path.join(sb(), "source.json"))["levels"]}


def pick_sample():
    from pv_select_sample import exclusion_reasons

    old = [s["level"] for s in load(os.path.join(sb(), "sample.json"))["sample"]]
    src = source_levels()
    cands = []
    for n in sorted(src):
        if not 32 <= n <= 800 or n in old:
            continue
        if exclusion_reasons(n, src[n]["level_json"]):
            continue
        cands.append(n)
    k = 10
    new = sorted({cands[min(len(cands) - 1, int((j + 0.5) * len(cands) / k))] for j in range(k)})
    out = {"old": old, "new": new, "newPool": len(cands), "levels": old + new}
    save(os.path.join(sb(), "sample2.json"), out)
    print(json.dumps(out))


def lj_for(prep, seed):
    row = {**prep["row"], "randSeed": str(seed)}
    res = shuffle_empty_tiles(row["map"], rand_seed=seed, use_tile_count=row["useTileCount"], strict=True)
    return bot_level_json(row, resolve_map(row["map"], res))


def orig_lj(prep, level):
    lv = source_levels()[level]
    o = prep["orig"]
    return bot_level_json({"randSeed": o.get("randSeed") or 1, "useTileCount": o.get("useTileCount") or 6,
                           "unlockTile": 0}, canonical_map(lv["level_json"]))


def scan_choice(d):
    """Recompute from stored rates so rule fixes apply to already-scanned levels."""
    return choose_thetas(load(os.path.join(d, "scan.json"))["rates"])


def thetas_of(d):
    return [float(t) for t in scan_choice(d)["thetas"]]


def merged_s1(d, upto):
    out = {}
    for p in POOLS:
        if p > upto:
            break
        f = os.path.join(d, f"s1_p{p}.json")
        if os.path.exists(f):
            out.update(load(f)["results"])
    return out


def merged_s2(d, upto):
    out, solved = {}, {}
    for p in POOLS:
        if p > upto:
            break
        f = os.path.join(d, f"s2_p{p}.json")
        if os.path.exists(f):
            out.update(load(f)["results"])
        g = os.path.join(d, f"solve_p{p}.json")
        if os.path.exists(g):
            solved.update(load(g)["solved"])
    return out, solved


def verified_map(s1, s2, solved):
    keys = set(s1) | set(s2)
    return {s: any_win(s1.get(s), s2.get(s)) or solved.get(s, {}).get("verdict") == "PROVEN_SOLVABLE" for s in keys}


def step(level, ex):
    d = os.path.join(sb(), "eval2", f"{level:04d}")
    os.makedirs(d, exist_ok=True)
    f = lambda name: os.path.join(d, name)  # noqa: E731
    t_start = time.time()

    if not os.path.exists(f("prep.json")):
        lv = source_levels()[level]
        first = t0ize_level(lv["level_json"], 1)
        pool = candidate_seeds(first["meta"]["structHash"], POOLS[-1])
        res = t0ize_level(lv["level_json"], pool[0])
        save(f("prep.json"), {"level": level, "row": res["row"], "meta": res["meta"], "pool": pool,
                              "orig": {"randSeed": lv["level_json"].get("randSeed"),
                                       "useTileCount": lv["level_json"].get("useTileCount")}})
        return "prep"

    prep = load(f("prep.json"))
    if not os.path.exists(f("golden.json")):
        gdir = os.path.join(sb(), "golden2")
        os.makedirs(os.path.join(gdir, "inputs"), exist_ok=True)
        os.makedirs(os.path.join(gdir, "expected"), exist_ok=True)
        inp = os.path.join(gdir, "inputs", f"r_pv2_l{level:04d}.json")
        save(inp, {"caseId": f"r_pv2_l{level:04d}", "kind": "real", "levelId": f"level_{level}", "dumpRng": False,
                   "note": "P1 re-measure pool (128 seeds)", "row": prep["row"],
                   "runs": [{"randSeed": str(s)} for s in prep["pool"]]})
        out = subprocess.run(["dotnet", "run", "--project", os.path.join(REPO, "tools", "pv_golden"), "--", "case", inp],
                             cwd=REPO, capture_output=True, text=True, timeout=200)
        if out.returncode != 0:
            raise SystemExit(f"dotnet case failed: {out.stderr[-500:]}")
        exp = json.loads(out.stdout)
        save(os.path.join(gdir, "expected", f"r_pv2_l{level:04d}.json"), exp)
        mism = []
        for s, r in zip(prep["pool"], exp["results"]):
            got = shuffle_empty_tiles(prep["row"]["map"], rand_seed=s, use_tile_count=prep["row"]["useTileCount"])
            pos = [[x.layer_name, x.pos, -1 if x.inner_index is None else x.inner_index] for x in got.slots]
            nums = [CTile("", "", t, "").tile_id_num for t in got.assigned]
            if pos != r["positions"] or nums != r["types"]:
                mism.append(s)
        save(f("golden.json"), {"runs": len(prep["pool"]), "mismatch": mism, "distVer": exp.get("distVer")})
        if mism:
            raise SystemExit(f"GOLDEN MISMATCH level {level}: {mism[:5]}")
        return "golden"

    if not os.path.exists(f("scan.json")):
        out = evaluate_maps(ex, {"orig": orig_lj(prep, level)}, SCAN_GAMES, SEED_SCAN, thetas=SCAN_THETAS, chunk=64)
        cpu = out.pop("_cpuSec", 0.0)
        rates = {t: v["rate"] for t, v in out["orig"]["theta"].items()}
        save(f("scan.json"), {"rates": rates, "choice": choose_thetas(rates), "cpuSec": cpu,
                              "wallSec": round(time.time() - t_start, 2)})
        return "scan"

    choice = scan_choice(d)
    if not choice["evaluable"]:
        if not os.path.exists(f("final.json")):
            save(f("final.json"), {"level": level, "status": "unevaluable", "reason": choice["reason"]})
        return "LEVEL_DONE"
    th = thetas_of(d)

    if not os.path.exists(f("orig2.json")):
        out = evaluate_maps(ex, {"orig": orig_lj(prep, level)}, S2_GAMES, SEED_S2, thetas=th)
        cpu = out.pop("_cpuSec", 0.0)
        save(f("orig2.json"), {"results": out, "cpuSec": cpu, "wallSec": round(time.time() - t_start, 2)})
        return "orig2"
    orig = load(f("orig2.json"))["results"]["orig"]

    for i, p in enumerate(POOLS):
        lo = 0 if i == 0 else POOLS[i - 1]
        if not os.path.exists(f(f"s1_p{p}.json")):
            seeds = prep["pool"][lo:p]
            out = evaluate_maps(ex, {str(s): lj_for(prep, s) for s in seeds}, S1_GAMES, SEED_S1, thetas=th, chunk=64)
            cpu = out.pop("_cpuSec", 0.0)
            save(f(f"s1_p{p}.json"), {"results": out, "cpuSec": cpu, "wallSec": round(time.time() - t_start, 2)})
            return f"s1_p{p}"
        s1 = merged_s1(d, p)
        s2_prev, solved_prev = merged_s2(d, POOLS[i - 1] if i else 0)
        if not os.path.exists(f(f"s2_p{p}.json")):
            ver1 = verified_map(s1, s2_prev, solved_prev)
            w1 = {s: e["W"] for s, e in s1.items()}
            bp = base_pick(w1, orig["W"], ver1)
            base = bp["base"]
            # keep base fixed once chosen at pool 32 (base = closest to original, re-picking would move the anchor)
            if i:
                base = load(f("s2_p32.json"))["basePick"]["base"]
            sl = staircase_shortlist(w1, base, ver1, exclude=[s for s in s2_prev if s != base])
            need = [base] + sl["easy"] + sl["hard"]
            need = [s for s in need if s not in s2_prev]
            out = evaluate_maps(ex, {s: lj_for(prep, int(s)) for s in need}, S2_GAMES, SEED_S2, thetas=th) if need else {"_cpuSec": 0.0}
            cpu = out.pop("_cpuSec", 0.0)
            save(f(f"s2_p{p}.json"), {"basePick": {**bp, "base": base}, "shortlist": sl, "evaluated": need,
                                      "results": out, "cpuSec": cpu, "wallSec": round(time.time() - t_start, 2)})
            return f"s2_p{p}"
        s2, solved = merged_s2(d, p)
        if not os.path.exists(f(f"solve_p{p}.json")):
            need = [s for s in load(f(f"s2_p{p}.json"))["evaluated"] if not any_win(s1.get(s), s2.get(s))]
            futs = {s: ex.submit(solve_check, lj_for(prep, int(s)), SOLVER_NODES) for s in need}
            save(f(f"solve_p{p}.json"), {"solved": {s: fu.result() for s, fu in futs.items()},
                                         "wallSec": round(time.time() - t_start, 2)})
            return f"solve_p{p}"
        s2, solved = merged_s2(d, p)
        if not os.path.exists(f(f"sel_p{p}.json")):
            ver = verified_map(s1, s2, solved)
            base = load(f("s2_p32.json"))["basePick"]["base"]
            r = bidirectional_select(base, [s for s in s2 if s != base], s2, ver)
            save(f(f"sel_p{p}.json"), {"pool": p, **r})
            return f"sel_p{p}"
        r = load(f(f"sel_p{p}.json"))
        if r["ok"] or p == POOLS[-1]:
            if not os.path.exists(f("final.json")):
                bp = load(f("s2_p32.json"))["basePick"]
                fin = {"level": level, "status": "ok" if r["ok"] else "bidirectional_unmet", "poolUsed": p,
                       "thetas": th, "wOrig": orig["W"], "basePick": bp, "sel": r}
                if r["ok"]:
                    fin["W2"] = {t: s2[s]["W"] for t, s in r["seeds"]}
                    fin["pv"] = {"v": 1, "mode": "seed", "structHash": prep["meta"]["structHash"],
                                 "utc": prep["meta"]["utc0"], "thetas": th,
                                 "seeds": [{"tier": t, "seed": int(s)} for t, s in r["seeds"]]}
                save(f("final.json"), fin)
            return "LEVEL_DONE"
    return "LEVEL_DONE"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--pick", action="store_true")
    ap.add_argument("--level", type=int)
    ap.add_argument("--next", action="store_true")
    args = ap.parse_args()
    if args.pick:
        pick_sample()
        return 0
    t = time.time()
    with ProcessPoolExecutor(max_workers=WORKERS) as ex:
        r = step(args.level, ex)
    print(f"{args.level} {r} {time.time() - t:.1f}s", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
