"""Bot v2 (skill-monotone) measurement driver — 12_bot_v2.md.

Sub-commands (each prints a summary; results under <sandbox>/bot_v2/):
  regress  --out NAME     v1 regression snapshot (20 levels, fixed seeds): per-game outcomes for the pv θ path,
                          an editor MC sweep (predicted_clear_rate path) and named-profile simulate_with_profile.
  mono     --ver v1|v2    monotonicity: 30 levels 32~1000 × θ grid × N games (original map, CRN seeds).
  upper    --ver v1|v2    upper bound: 30 stratified L1001+ 'unevaluable' levels × high θ × N games.
  impact                  editor predicted_clear_rate v1 vs v2 (50 levels, run_skill_sweep defaults).

Original maps only (lj_orig from pv_dda, same as the DDA scan). Workers <= 4.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import random
import sys
import time
from concurrent.futures import ProcessPoolExecutor

BACKEND = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BACKEND)
sys.path.insert(0, os.path.join(BACKEND, "scripts"))

import pv_dda  # noqa: E402
from app.core.pv.evaluate import run_games_task  # noqa: E402

OUT = os.path.join(pv_dda.SB, "bot_v2")
WORKERS = min(4, int(os.environ.get("PV_WORKERS", "4")))
GRID = (0.15, 0.29, 0.35, 0.40, 0.47, 0.55, 0.65, 0.75, 0.85, 1.0)
HI_GRID = (0.65, 0.85, 1.0)


def meta(n):
    p = os.path.join(pv_dda.DDA, "meta", f"{n}.json")
    return pv_dda.load(p) if os.path.exists(p) else None


def lj(n):
    prep = pv_dda.load(os.path.join(pv_dda.DDA, "work", f"{n:04d}", "prep.json"))
    return pv_dda.lj_orig(prep)


def has_prep(n):
    return os.path.exists(os.path.join(pv_dda.DDA, "work", f"{n:04d}", "prep.json"))


def pick(pool, k, seed):
    rng = random.Random(seed)
    pool = sorted(pool)
    if len(pool) <= k:
        return pool
    # stratified: split sorted pool into k bins, one random level per bin
    out = []
    for i in range(k):
        lo, hi = len(pool) * i // k, len(pool) * (i + 1) // k
        out.append(pool[rng.randrange(lo, hi)])
    return out


def levels_by_status(statuses, lo, hi):
    out = []
    for n in range(lo, hi + 1):
        m = meta(n)
        if m and m["status"] in statuses and has_prep(n):
            out.append(n)
    return out


def save(name, obj):
    os.makedirs(OUT, exist_ok=True)
    pv_dda.save(os.path.join(OUT, name), obj)


# ── regression snapshot ─────────────────────────────────────────────────────────────────────────
def regress_task(n):
    from app.core.bot_simulator import BotSimulator
    from app.core.mc_difficulty import run_skill_sweep
    from app.models.bot_profile import BotType, get_profile
    level = lj(n)
    out = {"level": n, "pv": {}, "named": {}}
    for th in (0.15, 0.29, 0.47, 0.65, 0.85, 1.0):
        r = run_games_task({"key": str(n), "theta": th, "level_json": level, "seed_base": 777_000, "start": 0, "count": 6})
        r.pop("sec")
        out["pv"][str(th)] = r
    sw = run_skill_sweep(level, rollouts_per_point=6, seed=4242)
    out["sweep"] = sw
    sim = BotSimulator()
    for bt in (BotType.CASUAL, BotType.EXPERT):
        res = sim.simulate_with_profile(level, get_profile(bt), iterations=4, seed=99)
        out["named"][bt.value] = res.to_dict()
    return out


def regress_levels():
    pool = levels_by_status({"5tier", "3tier", "no_variant", "unevaluable"}, 32, 1500)
    return pick(pool, 20, 20261014)


def cmd_regress(a):
    levels = regress_levels()
    t0 = time.time()
    with ProcessPoolExecutor(WORKERS) as ex:
        res = list(ex.map(regress_task, levels))
    blob = json.dumps(res, sort_keys=True, ensure_ascii=False)
    sha = hashlib.sha256(blob.encode()).hexdigest()
    save(f"regress_{a.out}.json", {"levels": levels, "sha256": sha, "results": res})
    print(f"regress {a.out}: {len(levels)} levels sha256={sha} wall={time.time() - t0:.0f}s")


# ── θ-grid measurement (mono / upper) ───────────────────────────────────────────────────────────
def grid_task(args):
    level = lj(args["n"])
    r = run_games_task({"key": str(args["n"]), "theta": args["theta"], "level_json": level,
                        "seed_base": args["seed_base"], "start": 0, "count": args["games"],
                        "bot_version": args["ver"]})
    return {"n": args["n"], "theta": args["theta"], "wins": sum(r["wins"]), "games": len(r["wins"]), "sec": r["sec"]}


def run_grid(name, levels, grid, games, ver, part):
    path = os.path.join(OUT, f"{name}_{ver}.json")
    done = pv_dda.load(path) if os.path.exists(path) else {"levels": levels, "grid": list(grid), "games": games, "rows": []}
    have = {(r["n"], r["theta"]) for r in done["rows"]}
    todo = [{"n": n, "theta": th, "games": games, "ver": ver, "seed_base": 3_000_000 + int(th * 1000) * 1000}
            for n in levels for th in grid if (n, th) not in have]
    if part:
        todo = todo[:part]
    t0 = time.time()
    with ProcessPoolExecutor(WORKERS) as ex:
        for r in ex.map(grid_task, todo):
            done["rows"].append(r)
            if time.time() - t0 > 60:
                save(f"{name}_{ver}.json", done)
                t0 = time.time()
    save(f"{name}_{ver}.json", done)
    left = len(levels) * len(grid) - len(done["rows"])
    print(f"{name} {ver}: rows={len(done['rows'])} left={left}")


def mono_levels():
    pool = levels_by_status({"5tier", "3tier", "no_variant"}, 32, 1000)
    return pick(pool, 30, 32_1000)


def upper_levels():
    pool = levels_by_status({"unevaluable"}, 1001, 1500)
    return pick(pool, 30, 1001_1500)


def cmd_mono(a):
    grid = tuple(float(x) for x in a.grid.split(",")) if a.grid else GRID
    run_grid("mono", mono_levels(), grid, a.games, a.ver, a.part)


def cmd_upper(a):
    grid = tuple(float(x) for x in a.grid.split(",")) if a.grid else HI_GRID
    run_grid("upper", upper_levels(), grid, a.games, a.ver, a.part)


# ── editor impact ───────────────────────────────────────────────────────────────────────────────
def impact_task(args):
    from app.core.mc_difficulty import run_skill_sweep
    t0 = time.time()
    sw = run_skill_sweep(lj(args["n"]), bot_version=args["ver"])
    return {"n": args["n"], "ver": args["ver"], "pred": sw["predicted_clear_rate"], "dscore": sw["difficulty_score"],
            "theta_star": sw["theta_star"], "curve": [c["clear_rate"] for c in sw["skill_curve"]], "sec": time.time() - t0}


def cmd_impact(a):
    pool = levels_by_status({"5tier", "3tier", "no_variant", "unevaluable", "timeout_hold"}, 32, 1500)
    levels = pick(pool, 50, 50_2026)
    path = os.path.join(OUT, "impact.json")
    done = pv_dda.load(path) if os.path.exists(path) else {"levels": levels, "rows": []}
    have = {(r["n"], r["ver"]) for r in done["rows"]}
    todo = [{"n": n, "ver": v} for n in levels for v in ("v1", "v2") if (n, v) not in have]
    if a.part:
        todo = todo[:a.part]
    with ProcessPoolExecutor(WORKERS) as ex:
        for r in ex.map(impact_task, todo):
            done["rows"].append(r)
    save("impact.json", done)
    print(f"impact rows={len(done['rows'])} left={len(levels) * 2 - len(done['rows'])}")


# ── report ──────────────────────────────────────────────────────────────────────────────────────
def curves(name, ver):
    d = pv_dda.load(os.path.join(OUT, f"{name}_{ver}.json"))
    c, sec, games = {}, 0.0, 0
    for r in d["rows"]:
        c.setdefault(r["n"], {})[r["theta"]] = (r["wins"], r["games"])
        sec += r["sec"]
        games += r["games"]
    return d, c, sec / max(1, games)


def drop_stats(curve, z=2.0):
    """Largest drop below any lower-θ point; 'significant' if two-proportion z > z."""
    ths = sorted(curve)
    worst, sig = 0.0, 0
    for i, ti in enumerate(ths):
        wi, ni = curve[ti]
        pi = wi / ni
        for tj in ths[:i]:
            wj, nj = curve[tj]
            pj = wj / nj
            d = pj - pi
            if d > worst:
                worst = d
            pp = (wi + wj) / (ni + nj)
            se = (pp * (1 - pp) * (1 / ni + 1 / nj)) ** 0.5
            if se > 0 and d / se > z:
                sig += 1
    return worst, sig


def cmd_report(a):
    out = {}
    for name in ("mono", "upper"):
        for ver in ("v1", "v2"):
            p = os.path.join(OUT, f"{name}_{ver}.json")
            if not os.path.exists(p):
                continue
            d, c, spg = curves(name, ver)
            ths = sorted({t for cv in c.values() for t in cv})
            mean = {t: sum(cv[t][0] / cv[t][1] for cv in c.values() if t in cv) / len(c) for t in ths}
            ds = {n: drop_stats(cv) for n, cv in c.items()}
            best = {n: max(w / g for w, g in cv.values()) for n, cv in c.items()}
            hi = {n: cv[max(cv)][0] / cv[max(cv)][1] for n, cv in c.items()}
            out[f"{name}_{ver}"] = {
                "levels": len(c), "secPerGame": round(spg, 4),
                "meanCurve": {str(t): round(v, 3) for t, v in mean.items()},
                "worstDropMedian": round(sorted(v[0] for v in ds.values())[len(ds) // 2], 3),
                "levelsWorstDrop>0.15": sum(1 for v in ds.values() if v[0] > 0.15),
                "levelsSigDrop(z>2)": sum(1 for v in ds.values() if v[1] > 0),
                "levelsMaxThetaWithin0.05OfBest": sum(1 for n in c if hi[n] >= best[n] - 0.05),
                "maxThetaRateZero": sum(1 for v in hi.values() if v == 0),
                "bestRateZero": sum(1 for v in best.values() if v == 0),
                "bestRate>=0.10": sum(1 for v in best.values() if v >= 0.10),
                "bestRateMedian": round(sorted(best.values())[len(best) // 2], 3),
                "perLevel": {str(n): {"curve": {str(t): round(w / g, 3) for t, (w, g) in sorted(cv.items())},
                                      "worstDrop": round(ds[n][0], 3), "sigDrops": ds[n][1]} for n, cv in sorted(c.items())},
            }
    imp = os.path.join(OUT, "impact.json")
    if os.path.exists(imp):
        d = pv_dda.load(imp)
        by = {}
        for r in d["rows"]:
            by.setdefault(r["n"], {})[r["ver"]] = r
        pairs = [(n, v["v1"], v["v2"]) for n, v in by.items() if "v1" in v and "v2" in v]
        deltas = sorted(b["pred"] - x["pred"] for _, x, b in pairs)
        if deltas:
            q = lambda f: round(deltas[min(len(deltas) - 1, int(f * len(deltas)))], 4)
            from statistics import mean
            # Spearman between v1 and v2 predicted
            def rank(xs):
                o = sorted(range(len(xs)), key=lambda i: xs[i]); r = [0.0] * len(xs)
                i = 0
                while i < len(o):
                    j = i
                    while j + 1 < len(o) and xs[o[j + 1]] == xs[o[i]]:
                        j += 1
                    for k in range(i, j + 1):
                        r[o[k]] = (i + j) / 2
                    i = j + 1
                return r
            r1, r2 = rank([x["pred"] for _, x, _ in pairs]), rank([b["pred"] for _, _, b in pairs])
            m1, m2 = mean(r1), mean(r2)
            cov = sum((a_ - m1) * (b_ - m2) for a_, b_ in zip(r1, r2))
            sd = (sum((a_ - m1) ** 2 for a_ in r1) * sum((b_ - m2) ** 2 for b_ in r2)) ** 0.5
            out["impact"] = {
                "levels": len(pairs), "deltaPred": {"min": deltas[0], "p25": q(0.25), "median": q(0.5),
                                                    "p75": q(0.75), "max": deltas[-1], "mean": round(mean(deltas), 4)},
                "absDelta>0.10": sum(1 for x in deltas if abs(x) > 0.10),
                "spearmanV1V2": round(cov / sd, 3) if sd else None,
                "secV1": round(sum(x["sec"] for _, x, _ in pairs), 1), "secV2": round(sum(b["sec"] for _, _, b in pairs), 1),
                "perLevel": {str(n): {"v1": x["pred"], "v2": b["pred"]} for n, x, b in sorted(pairs)},
            }
    save("summary.json", out)
    for k, v in out.items():
        print(k, json.dumps({kk: vv for kk, vv in v.items() if kk != "perLevel"}, ensure_ascii=False))


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("regress"); p.add_argument("--out", required=True); p.set_defaults(f=cmd_regress)
    for nm, f in (("mono", cmd_mono), ("upper", cmd_upper)):
        p = sub.add_parser(nm); p.add_argument("--ver", default="v1"); p.add_argument("--games", type=int, default=64)
        p.add_argument("--part", type=int, default=0); p.add_argument("--grid", default=""); p.set_defaults(f=f)
    p = sub.add_parser("impact"); p.add_argument("--part", type=int, default=0); p.set_defaults(f=cmd_impact)
    p = sub.add_parser("report"); p.set_defaults(f=cmd_report)
    a = ap.parse_args()
    a.f(a)


if __name__ == "__main__":
    main()
