"""P1 v3: useTileCount ±1 flex search for bidirectional 5 seeds (user decision 2026-10-02).

Rules (08 report):
- Each tier is filled from utc0 seeds first; only a side that cannot be filled may use
  utc0-1 (easy side) / utc0+1 (hard side). Pair choice minimises the number of ±1 seeds.
- base stays utc0 ("strict"). For extreme-original levels (orig percentile >0.90 / <0.10) a
  "relaxed" variant also allows base from utc0-1 / utc0+1; both are reported.
- Same evaluation as v2: v2 θ pair, stage-1 64 games/θ, stage-2 950 games/θ (same bot seed bases),
  independent CI, Δmin 0.04, same-side gap 0.02, solvability evidence, no duplicate filling.
- ±1 pools: 32 -> 64 (capped at 64 for cost; utc0 pool already went to 128 in v2).
- Every ±1 board is checked against the dotnet golden (all 64 seeds) before evaluation.
Shared core untouched; θ trough avoidance from v2 kept.

Each call runs ONE missing step for one level:  python scripts/pv_utcflex.py --level 574 --next
Files: <sandbox>/eval3/<level>/...  (reads eval2 for utc0 data)
"""
from __future__ import annotations

import argparse
import copy
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

from app.core.pv.cs_shuffle import CTile, shuffle_empty_tiles  # noqa: E402
from app.core.pv.evaluate import candidate_seeds, evaluate_maps, solve_check  # noqa: E402
from app.core.pv.select import (  # noqa: E402
    DELTA_MIN_V2, GAP_MIN_V2, any_win, indep_diff, staircase_shortlist,
)
from pv_remeasure import lj_for, load, merged_s1, merged_s2, orig_lj, save, sb  # noqa: E402

FLEX_POOLS = (32, 64)
S1_GAMES, S2_GAMES = 64, 950
SEED_S1, SEED_S2 = 6_000_000, 7_000_000  # same bot streams as v2 (comparable to utc0 data)
SOLVER_NODES = 5000
WORKERS = int(os.environ.get("PV_WORKERS", "6"))
EXTREME_HI, EXTREME_LO = 0.90, 0.10


def d2(level):
    return os.path.join(sb(), "eval2", f"{level:04d}")


def d3(level):
    p = os.path.join(sb(), "eval3", f"{level:04d}")
    os.makedirs(p, exist_ok=True)
    return p


def key(u, s):
    return f"{u}:{s}"


def prep_u(level, u):
    """t0 row with useTileCount=u and its own seed pool (64)."""
    p = os.path.join(d3(level), f"prep_u{u}.json")
    if os.path.exists(p):
        return load(p)
    base = load(os.path.join(d2(level), "prep.json"))
    row = copy.deepcopy(base["row"])
    row["useTileCount"] = str(u)
    pool = candidate_seeds(f"{base['meta']['structHash']}|u{u}", FLEX_POOLS[-1])
    row["randSeed"] = str(pool[0])
    for s in pool:  # 05 §3-3 / v3 rule 3: strict port check for every ±1 board
        shuffle_empty_tiles(row["map"], rand_seed=s, use_tile_count=u, strict=True)
    out = {"level": level, "utc": u, "utc0": base["meta"]["utc0"], "row": row, "pool": pool,
           "meta": base["meta"], "orig": base["orig"]}
    save(p, out)
    return out


def golden_u(level, prep):
    u = prep["utc"]
    p = os.path.join(d3(level), f"golden_u{u}.json")
    if os.path.exists(p):
        return False
    gdir = os.path.join(sb(), "golden3")
    os.makedirs(os.path.join(gdir, "inputs"), exist_ok=True)
    os.makedirs(os.path.join(gdir, "expected"), exist_ok=True)
    name = f"r_pv3_l{level:04d}_u{u}.json"
    inp = os.path.join(gdir, "inputs", name)
    save(inp, {"caseId": name[:-5], "kind": "real", "levelId": f"level_{level}", "dumpRng": False,
               "note": f"P1 v3 utc flex pool (utc={u}, utc0={prep['utc0']})", "row": prep["row"],
               "runs": [{"randSeed": str(s)} for s in prep["pool"]]})
    out = subprocess.run(["dotnet", "run", "--project", os.path.join(REPO, "tools", "pv_golden"), "--", "case", inp],
                         cwd=REPO, capture_output=True, text=True, timeout=200)
    if out.returncode != 0:
        raise SystemExit(f"dotnet case failed: {out.stderr[-500:]}")
    exp = json.loads(out.stdout)
    save(os.path.join(gdir, "expected", name), exp)
    mism = []
    for s, r in zip(prep["pool"], exp["results"]):
        got = shuffle_empty_tiles(prep["row"]["map"], rand_seed=s, use_tile_count=u)
        pos = [[x.layer_name, x.pos, -1 if x.inner_index is None else x.inner_index] for x in got.slots]
        if pos != r["positions"] or [CTile("", "", t, "").tile_id_num for t in got.assigned] != r["types"]:
            mism.append(s)
    save(p, {"runs": len(prep["pool"]), "mismatch": mism, "distVer": exp.get("distVer")})
    if mism:
        raise SystemExit(f"GOLDEN MISMATCH level {level} utc {u}: {mism[:5]}")
    return True


def side_pick(base_key, cands, ev, verified, sign, delta_min=DELTA_MIN_V2, gap_min=GAP_MIN_V2):
    """Choose (near, far) on one side preferring utc0 seeds (fewest ±1 tokens), then widest spread."""
    wb = ev[base_key]["W"]
    utc_base = base_key.split(":")[0]
    valid, log = [], []
    for k in cands:
        if k == base_key or k not in ev or sign * (ev[k]["W"] - wb) <= 0:
            continue
        d = indep_diff(ev[k], ev[base_key]) if sign > 0 else indep_diff(ev[base_key], ev[k])
        rec = {"key": k, "delta": round(ev[k]["W"] - wb, 4), "lo": round(d["lo"], 4)}
        if not verified.get(k):
            rec["reject"] = "unverified"
        elif d["diff"] < delta_min:
            rec["reject"] = f"delta<{delta_min}"
        elif d["lo"] <= 0:
            rec["reject"] = "ci_includes_0"
        else:
            valid.append((d["diff"], k))
        log.append(rec)
    best = None
    for i in range(len(valid)):
        for j in range(i + 1, len(valid)):
            (dn, kn), (df, kf) = sorted([valid[i], valid[j]])
            if df - dn < gap_min:
                continue
            n_flex = sum(1 for x in (kn, kf) if x.split(":")[0] != utc_base)
            score = (-n_flex, df - dn)
            if best is None or score > best[0]:
                best = (score, kn, kf)
    reason = None if best else ("no_valid" if not valid else ("one_valid" if len(valid) == 1 else f"gap<{gap_min}"))
    return {"pick": (best[1], best[2]) if best else None, "nFlex": (-best[0][0]) if best else None,
            "nValid": len(valid), "reason": reason, "log": log}


def scenario_select(base_key, ev, verified, side_cands):
    easy = side_pick(base_key, side_cands["easy"], ev, verified, +1)
    hard = side_pick(base_key, side_cands["hard"], ev, verified, -1)
    ok = easy["pick"] is not None and hard["pick"] is not None
    r = {"base": base_key, "ok": ok, "sides": {"easy": easy, "hard": hard}}
    if ok:
        e1, e2 = easy["pick"]
        h1, h2 = hard["pick"]
        r["seeds"] = [("e2", e2), ("e1", e1), ("b", base_key), ("h1", h1), ("h2", h2)]
    return r


class Level:
    """Holds utc0 (v2) and ±1 data for one level; keys are "utc:seed"."""

    def __init__(self, level):
        self.level = level
        self.d2 = d2(level)
        self.d3 = d3(level)
        self.prep0 = load(os.path.join(self.d2, "prep.json"))
        self.u0 = self.prep0["meta"]["utc0"]
        self.fin2 = load(os.path.join(self.d2, "final.json"))
        self.th = self.fin2.get("thetas")

    def f(self, name):
        return os.path.join(self.d3, name)

    def s1_all(self):
        out = {key(self.u0, s): e for s, e in merged_s1(self.d2, 128).items()}
        for u in (self.u0 - 1, self.u0 + 1):
            for p in FLEX_POOLS:
                fp = self.f(f"s1_u{u}_p{p}.json")
                if os.path.exists(fp):
                    out.update({key(u, s): e for s, e in load(fp)["results"].items()})
        return out

    def s2_all(self):
        s2, solved = merged_s2(self.d2, 128)
        ev = {key(self.u0, s): e for s, e in s2.items()}
        sol = {key(self.u0, s): v for s, v in solved.items()}
        fp = self.f("s2_flex.json")
        if os.path.exists(fp):
            ev.update(load(fp)["results"])
        fp = self.f("solve_flex.json")
        if os.path.exists(fp):
            sol.update(load(fp)["solved"])
        return ev, sol

    def verified(self, s1, ev, sol):
        return {k: any_win(s1.get(k), ev.get(k)) or sol.get(k, {}).get("verdict") == "PROVEN_SOLVABLE"
                for k in set(s1) | set(ev)}

    def orig(self):
        return load(os.path.join(self.d2, "orig2.json"))["results"]["orig"]


def eval_s2(lv, keys, ex):
    """Stage-2 evaluate keys not yet evaluated; accumulate into s2_flex.json and run the solver."""
    ev, sol = lv.s2_all()
    need = [k for k in keys if k not in ev]
    if not need:
        return 0
    preps = {}
    maps = {}
    for k in need:
        u, s = k.split(":")
        u = int(u)
        prep = lv.prep0 if u == lv.u0 else preps.setdefault(u, prep_u(lv.level, u))
        maps[k] = lj_for(prep, int(s)) if u == lv.u0 else lj_for(prep, int(s))
    out = evaluate_maps(ex, maps, S2_GAMES, SEED_S2, thetas=lv.th)
    out.pop("_cpuSec", None)
    fp = lv.f("s2_flex.json")
    cur = load(fp) if os.path.exists(fp) else {"results": {}}
    cur["results"].update(out)
    save(fp, cur)
    s1 = lv.s1_all()
    no_win = [k for k in need if not any_win(s1.get(k), out.get(k))]
    futs = {k: ex.submit(solve_check, maps[k], SOLVER_NODES) for k in no_win}
    fp = lv.f("solve_flex.json")
    cur = load(fp) if os.path.exists(fp) else {"solved": {}}
    cur["solved"].update({k: fu.result() for k, fu in futs.items()})
    save(fp, cur)
    return len(need)


def run_s1(lv, u, p, ex):
    fp = lv.f(f"s1_u{u}_p{p}.json")
    if os.path.exists(fp):
        return False
    prep = prep_u(lv.level, u)
    golden_u(lv.level, prep)
    lo = 0 if p == FLEX_POOLS[0] else FLEX_POOLS[0]
    seeds = prep["pool"][lo:p]
    out = evaluate_maps(ex, {str(s): lj_for(prep, s) for s in seeds}, S1_GAMES, SEED_S1, thetas=lv.th, chunk=64)
    out.pop("_cpuSec", None)
    save(fp, {"utc": u, "results": out})
    return True


def flex_shortlist(lv, base_key, u, side, s1, exclude):
    """Staircase shortlist on one side from the utc=u pool (stage-1 W relative to base stage-1 W)."""
    w1 = {k: e["W"] for k, e in s1.items() if k.startswith(f"{u}:") or k == base_key}
    ver = {k: any_win(s1.get(k)) for k in w1}
    sl = staircase_shortlist(w1, base_key, ver, exclude=exclude)
    return sl[side]


def step(level, ex):
    lv = Level(level)
    st0 = lv.fin2["status"]
    t0 = time.time()
    # ── unevaluable: short check only ─────────────────────────────────────
    if st0 == "unevaluable":
        fp = lv.f("unevaluable_check.json")
        if os.path.exists(fp):
            return "LEVEL_DONE"
        out = {}
        for u in (lv.u0 - 1, lv.u0):
            if not 1 <= u <= 15:
                continue
            prep = prep_u(level, u) if u != lv.u0 else lv.prep0
            if u != lv.u0:
                golden_u(level, prep)
            seeds = prep["pool"][:16]
            r = evaluate_maps(ex, {str(s): lj_for(prep, s) for s in seeds}, 32, 8_000_000, thetas=(0.85, 1.0), chunk=32)
            r.pop("_cpuSec", None)
            out[str(u)] = {"maxW": max(v["W"] for v in r.values()), "meanW": sum(v["W"] for v in r.values()) / len(r)}
        save(fp, {"note": "orig map itself is unevaluable (scan max <0.10); seeds checked at θ 0.85/1.0, 16 seeds x 32 games",
                  "byUtc": out, "wallSec": round(time.time() - t0, 1)})
        return "unevaluable_check"

    s1 = lv.s1_all()
    ev, sol = lv.s2_all()
    orig = lv.orig()
    pct = lv.fin2["basePick"]["origPercentile"]
    base0 = key(lv.u0, lv.fin2["basePick"]["base"])
    extreme = "hi" if pct > EXTREME_HI else ("lo" if pct < EXTREME_LO else None)

    # ── strict: base utc0 ────────────────────────────────────────────────
    if not os.path.exists(lv.f("strict.json")):
        ver = lv.verified(s1, ev, sol)
        cands0 = [k for k in ev if k.startswith(f"{lv.u0}:")]
        res = scenario_select(base0, ev, ver, {"easy": cands0, "hard": cands0})
        if res["ok"]:
            save(lv.f("strict.json"), {**res, "flexUsed": []})
            return "strict(utc0 only)"
        # failing sides -> flex pools
        for side, u in (("easy", lv.u0 - 1), ("hard", lv.u0 + 1)):
            if res["sides"][side]["pick"] is not None or not 1 <= u <= 15:
                continue
            for p in FLEX_POOLS:
                if run_s1(lv, u, p, ex):
                    return f"s1_u{u}_p{p}"
                s1 = lv.s1_all()
                tag = lv.f(f"sl_{side}_u{u}_p{p}.json")
                if not os.path.exists(tag):
                    excl = [k for k in ev if k != base0]
                    sl = flex_shortlist(lv, base0, u, side, s1, excl)
                    n = eval_s2(lv, sl, ex)
                    save(tag, {"shortlist": sl, "evaluated": n})
                    return f"s2 {side} u{u} p{p}"
                ev, sol = lv.s2_all()
                ver = lv.verified(s1, ev, sol)
                pool_side = [k for k in ev if k.startswith(f"{lv.u0}:") or k.startswith(f"{u}:")]
                r_side = side_pick(base0, pool_side, ev, ver, +1 if side == "easy" else -1)
                if r_side["pick"] is not None:
                    break
        ev, sol = lv.s2_all()
        s1 = lv.s1_all()
        ver = lv.verified(s1, ev, sol)
        cand_e = [k for k in ev if k.split(":")[0] in (str(lv.u0), str(lv.u0 - 1))]
        cand_h = [k for k in ev if k.split(":")[0] in (str(lv.u0), str(lv.u0 + 1))]
        res = scenario_select(base0, ev, ver, {"easy": cand_e, "hard": cand_h})
        used = [k for _, k in res.get("seeds", []) if not k.startswith(f"{lv.u0}:")]
        save(lv.f("strict.json"), {**res, "flexUsed": used})
        return "strict"

    # ── relaxed: base from utc0-1 (orig much easier) / utc0+1 (orig much harder) ──
    if extreme and not os.path.exists(lv.f("relaxed.json")):
        ub = lv.u0 - 1 if extreme == "hi" else lv.u0 + 1
        if not 1 <= ub <= 15:
            save(lv.f("relaxed.json"), {"ok": False, "reason": f"utc {ub} out of range"})
            return "relaxed(n/a)"
        for p in FLEX_POOLS:
            if run_s1(lv, ub, p, ex):
                return f"s1_u{ub}_p{p}"
        s1 = lv.s1_all()
        tag = lv.f("relaxed_base.json")
        if not os.path.exists(tag):
            pool = {k: e for k, e in s1.items() if k.startswith(f"{ub}:") and any_win(e)}
            near = sorted(pool, key=lambda k: abs(pool[k]["W"] - orig["W"]))[:2]
            eval_s2(lv, near, ex)
            save(tag, {"candidates": near})
            return "relaxed base s2"
        ev, sol = lv.s2_all()
        near = load(tag)["candidates"]
        if not near:
            save(lv.f("relaxed.json"), {"ok": False, "reason": "no verified base candidate in flex pool"})
            return "relaxed(no base)"
        base_r = min(near, key=lambda k: abs(ev[k]["W"] - orig["W"]))
        tag2 = lv.f("relaxed_sides.json")
        if not os.path.exists(tag2):
            # easy side from utc0-1 pool (or utc0 when ub=utc0+1); hard side from utc0 pool (+1 allowed)
            easy_u = lv.u0 - 1 if extreme == "hi" else lv.u0
            hard_u = lv.u0 if extreme == "hi" else lv.u0 + 1
            w1 = {k: e["W"] for k, e in s1.items()}
            w1[base_r] = s1[base_r]["W"]
            excl = [k for k in ev if k != base_r]
            sl_e = staircase_shortlist({k: w for k, w in w1.items() if k.startswith(f"{easy_u}:") or k == base_r},
                                       base_r, {k: any_win(s1.get(k)) for k in w1}, exclude=excl)["easy"]
            sl_h = staircase_shortlist({k: w for k, w in w1.items() if k.startswith(f"{hard_u}:") or k == base_r},
                                       base_r, {k: any_win(s1.get(k)) for k in w1}, exclude=excl)["hard"]
            eval_s2(lv, sl_e + sl_h, ex)
            save(tag2, {"easy": sl_e, "hard": sl_h})
            return "relaxed sides s2"
        ev, sol = lv.s2_all()
        ver = lv.verified(s1, ev, sol)
        allowed_e = {str(lv.u0 - 1), str(lv.u0)}
        allowed_h = {str(lv.u0), str(lv.u0 + 1)}
        res = scenario_select(base_r, ev, ver, {"easy": [k for k in ev if k.split(":")[0] in allowed_e],
                                                "hard": [k for k in ev if k.split(":")[0] in allowed_h]})
        bo = indep_diff(ev[base_r], orig)
        save(lv.f("relaxed.json"), {**res, "baseVsOrig": [bo["diff"], bo["lo"], bo["hi"]],
                                    "flexUsed": [k for _, k in res.get("seeds", []) if not k.startswith(f"{lv.u0}:")]})
        return "relaxed"
    return "LEVEL_DONE"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--level", type=int, required=True)
    ap.add_argument("--next", action="store_true")
    args = ap.parse_args()
    t = time.time()
    with ProcessPoolExecutor(max_workers=WORKERS) as ex:
        r = step(args.level, ex)
    print(f"{args.level} {r} {time.time() - t:.1f}s", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
