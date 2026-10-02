"""P1 v4 re-selection (user decision 2026-10-02, 09 report).

Rules:
1. base: extreme-original levels (orig percentile >0.90 / <0.10) use the v3 "relaxed" base (utc0∓1),
   others the v2 strict base (utc0). Easy side utc ∈ {utc0-1, utc0}, hard side utc ∈ {utc0, utc0+1}.
2. Outer tiers (e2/h2): valid at the selection θ pair (Δ≥0.04, CI>0, solvability evidence), ranked by
   closeness to target Δ (easy +0.20 / hard -0.25); top 3 per side get robust measurements
   (extra θ point + AVERAGE + EXPERT profiles, 600 games). h2 floor: max(rate at θ_hi, EXPERT) ≥ 0.10.
3. Robust test on informative points (not both ≤0.02 / ≥0.98): direction kept on ≥ 2/3 of them and
   not skill-sensitive (a reversed point AND spread ≥ 0.15).
4. Inner tiers (e1/h1): current rule (smallest valid Δ, below the outer by ≥0.02) then the same robust
   test. Both inner pass -> 5 tiers, else 3 tiers (b|e2|h2). Same-side order flip -> swap and re-judge.
5. Outer side failing -> pool expansion (utc0 up to 128, ±1 up to 64) -> else original explicit map.
Shared core untouched. Each call runs ONE step:  python scripts/pv_v4.py --level 55 --next
Files: <sandbox>/eval4/<level>/...
"""
from __future__ import annotations

import argparse
import math
import os
import sys
import time
from concurrent.futures import ProcessPoolExecutor

BACKEND = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BACKEND)
sys.path.insert(0, os.path.join(BACKEND, "scripts"))

from app.core.pv.evaluate import evaluate_maps, evaluate_points, solve_check  # noqa: E402
from app.core.pv.select import SCAN_THETAS, any_win, indep_diff  # noqa: E402
from pv_remeasure import lj_for, load, save, sb  # noqa: E402
from pv_utcflex import golden_u, prep_u  # noqa: E402

WORKERS = int(os.environ.get("PV_WORKERS", "6"))
DELTA_MIN, GAP_MIN = 0.04, 0.02
TARGET = {"easy": 0.20, "hard": -0.25}
H_FLOOR = 0.10
E_CEIL = 0.95           # reported only (data-driven proposal)
ROBUST_GAMES = 600
SEED_ROBUST = 9_100_000
SEED_S1, SEED_S2 = 6_000_000, 7_000_000
S1_GAMES, S2_GAMES = 64, 950
TROUGH = (0.34, 0.50)
INFO_LO, INFO_HI = 0.02, 0.98
POOL_U0 = (32, 64, 128)
POOL_FLEX = (32, 64)
SOLVER_NODES = 5000


def ddir(level, v):
    return os.path.join(sb(), f"eval{v}", f"{level:04d}")


class Lv:
    def __init__(self, level):
        self.level = level
        self.d2, self.d3, self.d4 = ddir(level, 2), ddir(level, 3), ddir(level, 4)
        os.makedirs(self.d4, exist_ok=True)
        self.prep0 = load(os.path.join(self.d2, "prep.json"))
        self.u0 = self.prep0["meta"]["utc0"]
        self.fin2 = load(os.path.join(self.d2, "final.json"))

    def f(self, name):
        return os.path.join(self.d4, name)

    def prep_for(self, u):
        if u == self.u0:
            return self.prep0
        p = prep_u(self.level, u)
        golden_u(self.level, p)  # every ±1 board checked against dotnet golden before evaluation
        return p

    # ── data merge (keys "u:seed") ──
    def s1(self):
        out = {}
        for p in POOL_U0:
            fp = os.path.join(self.d2, f"s1_p{p}.json")
            if os.path.exists(fp):
                out.update({f"{self.u0}:{s}": e for s, e in load(fp)["results"].items()})
        if os.path.isdir(self.d3):
            for fn in os.listdir(self.d3):
                if fn.startswith("s1_u"):
                    u = fn.split("_")[1][1:]
                    out.update({f"{u}:{s}": e for s, e in load(os.path.join(self.d3, fn))["results"].items()})
        for fn in os.listdir(self.d4):
            if fn.startswith("exp_s1_"):
                out.update(load(self.f(fn))["results"])
        return out

    def s2(self):
        ev, sol = {}, {}
        for p in POOL_U0:
            fp = os.path.join(self.d2, f"s2_p{p}.json")
            if os.path.exists(fp):
                ev.update({f"{self.u0}:{s}": e for s, e in load(fp)["results"].items()})
            fp = os.path.join(self.d2, f"solve_p{p}.json")
            if os.path.exists(fp):
                sol.update({f"{self.u0}:{s}": v for s, v in load(fp)["solved"].items()})
        for d, name, tgt, k in ((self.d3, "s2_flex.json", ev, "results"), (self.d3, "solve_flex.json", sol, "solved"),
                                (self.d4, "exp_s2.json", ev, "results"), (self.d4, "exp_solve.json", sol, "solved")):
            fp = os.path.join(d, name)
            if os.path.exists(fp):
                tgt.update(load(fp)[k])
        return ev, sol

    def robust(self):
        fp = self.f("robust.json")
        return load(fp) if os.path.exists(fp) else {"points": None, "results": {}}


def extra_theta(scan_rates, sel):
    cands = []
    for t in SCAN_THETAS:
        if TROUGH[0] <= t < TROUGH[1] or t >= 1.0:
            continue
        if all(abs(t - s) >= 0.2 - 1e-9 for s in sel):
            cands.append(t)
    if not cands:
        cands = [t for t in SCAN_THETAS if not (TROUGH[0] <= t < TROUGH[1]) and t < 1.0 and t not in sel]
    rates = {float(k): v for k, v in scan_rates.items()}
    return min(cands, key=lambda t: (abs(rates.get(t, 0) - 0.5), t))


def base_key(lv: Lv):
    pct = lv.fin2["basePick"]["origPercentile"]
    extreme = pct > 0.90 or pct < 0.10
    if extreme:
        rb = os.path.join(lv.d3, "relaxed_base.json")
        if os.path.exists(rb):
            ev, _ = lv.s2()
            orig = load(os.path.join(lv.d2, "orig2.json"))["results"]["orig"]
            near = [k for k in load(rb)["candidates"] if k in ev]
            if near:
                return min(near, key=lambda k: abs(ev[k]["W"] - orig["W"])), "relaxed", pct
    return f"{lv.u0}:{lv.fin2['basePick']['base']}", "strict", pct


def allowed(lv, side, k):
    u = int(k.split(":")[0])
    return u in ((lv.u0 - 1, lv.u0) if side == "easy" else (lv.u0, lv.u0 + 1))


def valid_side(lv, base, ev, ver, side):
    sign = 1 if side == "easy" else -1
    out = []
    for k, e in ev.items():
        if k == base or not allowed(lv, side, k) or sign * (e["W"] - ev[base]["W"]) <= 0 or not ver.get(k):
            continue
        d = indep_diff(e, ev[base]) if sign > 0 else indep_diff(ev[base], e)
        if d["diff"] >= DELTA_MIN and d["lo"] > 0:
            out.append({"key": k, "delta": e["W"] - ev[base]["W"]})
    return out


def point_rates(k, ev, rob):
    """{pointName: rate} combining selection θ (stage 2) and robust points."""
    r = {f"θ:{float(t):g}": v["rate"] for t, v in ev[k]["theta"].items()}
    for pt, v in rob["results"].get(k, {}).get("point", {}).items():
        r[pt] = v["rate"]
    return r


def robust_judge(k, base, ev, rob, side):
    sign = 1 if side == "easy" else -1
    rc, rb = point_rates(k, ev, rob), point_rates(base, ev, rob)
    pts = [p for p in rc if p in rb]
    info = [p for p in pts if not (max(rc[p], rb[p]) <= INFO_LO or min(rc[p], rb[p]) >= INFO_HI)]
    deltas = {p: sign * (rc[p] - rb[p]) for p in info}
    ok_dir = sum(1 for d in deltas.values() if d > 0)
    need = math.ceil(2 * len(info) / 3) if info else 1
    spread = (max(deltas.values()) - min(deltas.values())) if deltas else 0.0
    sensitive = any(d < 0 for d in deltas.values()) and spread >= 0.15
    measured = len(pts) >= 5
    return {"pass": measured and bool(info) and ok_dir >= need and not sensitive, "measured": measured,
            "points": len(pts), "informative": len(info), "dirOk": ok_dir, "need": need,
            "sensitive": sensitive, "spread": round(spread, 4),
            "meanDelta": (sum(deltas.values()) / len(deltas)) if deltas else 0.0,
            "rates": {p: round(rc[p], 4) for p in pts}, "baseRates": {p: round(rb[p], 4) for p in pts}}


def hi_rate(k, ev, rob):
    r = point_rates(k, ev, rob)
    th = [p for p in r if p.startswith("θ:")]
    top_theta = max(th, key=lambda p: float(p[2:])) if th else None
    vals = [r[top_theta]] if top_theta else []
    if "profile:expert" in r:
        vals.append(r["profile:expert"])
    return max(vals) if vals else 0.0


def lo_rate(k, ev, rob):
    r = point_rates(k, ev, rob)
    th = [p for p in r if p.startswith("θ:")]
    vals = [r[min(th, key=lambda p: float(p[2:]))]] if th else []
    if "profile:average" in r:
        vals.append(r["profile:average"])
    return min(vals) if vals else 1.0


def plan_candidates(lv, base, ev, ver, exclude_measured=()):
    plan = {}
    for side in ("easy", "hard"):
        vs = valid_side(lv, base, ev, ver, side)
        tg = TARGET[side]
        outer = sorted(vs, key=lambda c: (abs(c["delta"] - tg), c["key"]))
        # h2 floor is applied in decide() once EXPERT has been measured
        top = [c["key"] for c in outer[:3]]
        best_abs = abs(outer[0]["delta"]) if outer else 0
        inner = sorted([c for c in vs if c["key"] not in top and abs(c["delta"]) <= best_abs - GAP_MIN],
                       key=lambda c: (abs(c["delta"]), c["key"]))
        plan[side] = {"outer": top, "inner": [c["key"] for c in inner[:2]], "nValid": len(vs)}
    return plan


def decide(lv, base, ev, ver, rob):
    res = {"base": base, "sides": {}}
    for side in ("easy", "hard"):
        vs = {c["key"]: c["delta"] for c in valid_side(lv, base, ev, ver, side)}
        measured = [k for k in vs if k in rob["results"]]
        judged = {k: robust_judge(k, base, ev, rob, side) for k in measured}
        tg = TARGET[side]
        outer_ok = []
        for k in sorted(measured, key=lambda k: (abs(vs[k] - tg), k)):
            j = judged[k]
            floor_ok = hi_rate(k, ev, rob) >= H_FLOOR if side == "hard" else True
            j["floorOk"] = floor_ok
            j["loRate"] = lo_rate(k, ev, rob)
            j["hiRate"] = hi_rate(k, ev, rob)
            if j["pass"] and floor_ok:
                outer_ok.append(k)
        outer = outer_ok[0] if outer_ok else None
        inner = None
        if outer:
            inner_c = sorted([k for k in measured if k != outer and judged[k]["pass"]
                              and abs(vs[k]) <= abs(vs[outer]) - GAP_MIN], key=lambda k: (abs(vs[k]), k))
            inner = inner_c[0] if inner_c else None
            swapped = False
            # order flip on robust points: inner more extreme than outer -> swap and re-judge
            if inner and judged[inner]["meanDelta"] > judged[outer]["meanDelta"]:
                new_outer, new_inner = inner, outer
                fl = hi_rate(new_outer, ev, rob) >= H_FLOOR if side == "hard" else True
                if fl:
                    outer, inner, swapped = new_outer, new_inner, True
                else:
                    inner = None
            res["sides"][side] = {"outer": outer, "inner": inner, "swapped": swapped}
        else:
            res["sides"][side] = {"outer": None, "inner": None}
        res["sides"][side]["judged"] = judged
        res["sides"][side]["nValid"] = len(vs)
        res["sides"][side]["nMeasured"] = len(measured)
    eo, ho = res["sides"]["easy"]["outer"], res["sides"]["hard"]["outer"]
    if eo and ho:
        ei, hi = res["sides"]["easy"]["inner"], res["sides"]["hard"]["inner"]
        if ei and hi:
            res["tiers"] = 5
            res["seeds"] = [("b", base), ("e2", eo), ("e1", ei), ("h1", hi), ("h2", ho)]
        else:
            res["tiers"] = 3
            res["seeds"] = [("b", base), ("e2", eo), ("h2", ho)]
    else:
        res["tiers"] = 0
    return res


def run_robust(lv, keys, points, ex):
    rob = lv.robust()
    need = [k for k in keys if k not in rob["results"]]
    if not need:
        return 0
    maps = {}
    for k in need:
        u, s = k.split(":")
        maps[k] = lj_for(lv.prep_for(int(u)), int(s))
    out = evaluate_points(ex, maps, points, ROBUST_GAMES, SEED_ROBUST)
    rob["points"] = points
    rob["results"].update(out)
    save(lv.f("robust.json"), rob)
    return len(need)


def expansion_next(lv, side, base):
    """Next (u, lo, hi) seed chunk for this side not yet evaluated at stage 1."""
    s1 = lv.s1()
    us = [lv.u0, lv.u0 - 1] if side == "easy" else [lv.u0, lv.u0 + 1]
    for u in us:
        if not 1 <= u <= 15:
            continue
        pools = POOL_U0 if u == lv.u0 else POOL_FLEX
        prep = lv.prep0 if u == lv.u0 else lv.prep_for(u)
        for p in pools:
            seeds = prep["pool"][:p]
            if any(f"{u}:{s}" not in s1 for s in seeds):
                lo = max([q for q in pools if q < p] or [0])
                return u, lo, p
    return None


def step(level, ex):
    lv = Lv(level)
    if lv.fin2["status"] == "unevaluable":
        if not os.path.exists(lv.f("final.json")):
            save(lv.f("final.json"), {"level": level, "status": "fixed_map", "reason": "unevaluable (orig scan max <0.10)"})
        return "LEVEL_DONE"
    if os.path.exists(lv.f("final.json")):
        return "LEVEL_DONE"
    t0 = time.time()
    base, mode, pct = base_key(lv)
    th = lv.fin2["thetas"]
    xt = extra_theta(load(os.path.join(lv.d2, "scan.json"))["rates"], th)
    points = [f"θ:{xt:g}", "profile:average", "profile:expert"]
    ev, sol = lv.s2()
    s1 = lv.s1()
    ver = {k: any_win(s1.get(k), ev.get(k)) or sol.get(k, {}).get("verdict") == "PROVEN_SOLVABLE" for k in ev}
    rob = lv.robust()
    plan = plan_candidates(lv, base, ev, ver)
    keys = [base] + [k for sd in plan.values() for k in sd["outer"] + sd["inner"]]
    n = run_robust(lv, keys, points, ex)
    if n:
        return f"robust {n} keys ({time.time() - t0:.0f}s)"
    rob = lv.robust()
    res = decide(lv, base, ev, ver, rob)
    rounds = load(lv.f("rounds.json")) if os.path.exists(lv.f("rounds.json")) else []
    if res["tiers"] == 0:
        failing = [s for s in ("easy", "hard") if res["sides"][s]["outer"] is None]
        for side in failing:
            nx = expansion_next(lv, side, base)
            if nx is None:
                continue
            u, lo, hi = nx
            prep = lv.prep_for(u)
            seeds = prep["pool"][lo:hi]
            name = lv.f(f"exp_s1_{u}_{lo}_{hi}.json")
            out = evaluate_maps(ex, {f"{u}:{s}": lj_for(prep, s) for s in seeds}, S1_GAMES, SEED_S1, thetas=th, chunk=64)
            out.pop("_cpuSec", None)
            save(name, {"results": out})
            # stage-2 for the new candidates nearest the outer target (stage-1 Δ vs base stage-1 W)
            s1n = lv.s1()
            wb = s1n[base]["W"] if base in s1n else ev[base]["W"]
            sign = 1 if side == "easy" else -1
            pool_new = [k for k in out if sign * (out[k]["W"] - wb) > 0]
            pool_new.sort(key=lambda k: abs((out[k]["W"] - wb) - TARGET[side]))
            pick = pool_new[:3]
            if pick:
                o2 = evaluate_maps(ex, {k: lj_for(prep, int(k.split(":")[1])) for k in pick}, S2_GAMES, SEED_S2, thetas=th)
                o2.pop("_cpuSec", None)
                cur = load(lv.f("exp_s2.json")) if os.path.exists(lv.f("exp_s2.json")) else {"results": {}}
                cur["results"].update(o2)
                save(lv.f("exp_s2.json"), cur)
                nowin = [k for k in pick if not any_win(out.get(k), o2.get(k))]
                futs = {k: ex.submit(solve_check, lj_for(prep, int(k.split(':')[1])), SOLVER_NODES) for k in nowin}
                cs = load(lv.f("exp_solve.json")) if os.path.exists(lv.f("exp_solve.json")) else {"solved": {}}
                cs["solved"].update({k: fu.result() for k, fu in futs.items()})
                save(lv.f("exp_solve.json"), cs)
            rounds.append({"side": side, "utc": u, "chunk": [lo, hi], "stage2": pick})
            save(lv.f("rounds.json"), rounds)
            return f"expand {side} u{u} {lo}-{hi} ({time.time() - t0:.0f}s)"
    status = {5: "5tier", 3: "3tier", 0: "fixed_map"}[res["tiers"]]
    reason = None
    if res["tiers"] == 0:
        reason = "outer not robust after pool expansion: " + ",".join(
            s for s in ("easy", "hard") if res["sides"][s]["outer"] is None)
    elif res["tiers"] == 3:
        reason = "inner not robust: " + ",".join(s for s in ("easy", "hard") if res["sides"][s]["inner"] is None) \
            if any(res["sides"][s]["inner"] is None for s in ("easy", "hard")) else None
    save(lv.f("final.json"), {"level": level, "status": status, "reason": reason, "baseMode": mode, "origPct": pct,
                              "thetas": th, "extraTheta": xt, "robustPoints": points, "plan": plan,
                              "rounds": rounds, **res})
    return f"final {status}"


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
