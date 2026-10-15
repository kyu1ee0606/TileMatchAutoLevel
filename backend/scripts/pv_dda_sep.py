"""Cause separation for the ③ drop (10 §9-8): selection bias (regression to the mean) vs bot version.

For the 288 levels of ③ (R2 32~1000), R2 chosen tiers + original map:
  (a) v1 bot, R2 θ pair, NEW seeds (no overlap with any earlier stage), 950 games per θ (= R2 stage 2).
  (b) v2 bot, R2 θ pair, 950 games — reused from ③ m.json when ③ measured exactly that θ with 950 games,
      otherwise measured here (new seeds).
Decomposition: R2 stored Δ -> (a) = selection bias, (a) -> (b) = bot version, (b) -> ③ (v2 own θ pair) = θ pair shift.

Run from an isolated worktree whose bot_simulator.py blob is faadc98 (pre v2.3 merge). Reads main pv_sandbox
(SB override), writes only dda_sets_v2/sep/. Usage: PV_WORKERS=4 python scripts/pv_dda_sep.py run|report
"""
from __future__ import annotations

import json
import os
import statistics
import subprocess
import sys
import time
from collections import Counter
from concurrent.futures import ProcessPoolExecutor

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import pv_dda as P  # noqa: E402

MAIN_BACKEND = os.environ.get("PV_MAIN_BACKEND", "/Users/casualdev/TileMatchAutoLevel/backend")
P.SB = os.path.join(MAIN_BACKEND, "data", "pv_sandbox", P.COPY)
P.DDA = os.path.join(P.SB, "dda_sets")
V2 = os.path.join(P.SB, "dda_sets_v2")
OUT = os.path.join(V2, "sep")
BOT_FILE = os.path.join(P.BACKEND, "app", "core", "bot_simulator.py")
BOT_BLOB = "faadc984972e64b7f6044d5aab87ae4b775d0aee"
WORKERS = int(os.environ.get("PV_WORKERS", "4"))
GAMES = P.S2_GAMES  # 950
SEED_A, SEED_B = 7_600_000, 7_800_000  # unused ranges (R2 7.0M, ③ 7.2M, others 5.x/6.x/9.x/41M)


def load(p):
    return P.load(p) if os.path.exists(p) else None


def blob():
    return subprocess.run(["git", "hash-object", BOT_FILE], capture_output=True, text=True).stdout.strip()


def guard():
    b = blob()
    if b != BOT_BLOB:
        raise SystemExit(f"BOT FILE BLOB {b} != {BOT_BLOB} — STOP")


def games_task(a):
    from app.core.mc_difficulty import make_skill_profile
    from app.core.pv.evaluate import _TrackingBot
    t0 = time.time()
    bot = _TrackingBot()
    lj = a["lj"]
    base = bot._create_initial_state(lj, int(lj["max_moves"]))
    bot._precompute_blocking_map(base)
    prof = make_skill_profile(a["theta"], a["ver"])
    wins = 0
    for i in range(a["start"], a["start"] + a["count"]):
        bot._rng.seed(a["seed"] + i)
        bot.reset_track()
        wins += 1 if bot._play_game(bot._fast_copy_state(base), prof).cleared else 0
    return {"key": a["key"], "theta": a["theta"], "wins": wins, "n": a["count"], "sec": time.time() - t0}


def run(ex, maps, jobs, ver, seed):
    """jobs [(key, theta, thetaIndex)] -> {key: {θstr: {n, rate}}}, cpu. Same seed per θ index across maps (CRN)."""
    futs = [ex.submit(games_task, {"key": k, "lj": maps[k], "theta": th, "ver": ver, "seed": seed + ti * 10_000,
                                   "start": s, "count": min(100, GAMES - s)})
            for k, th, ti in jobs for s in range(0, GAMES, 100)]
    acc, cpu = {}, 0.0
    for f in futs:
        r = f.result()
        cpu += r["sec"]
        x = acc.setdefault(r["key"], {}).setdefault(f"{r['theta']:g}", [0, 0])
        x[0] += r["wins"]
        x[1] += r["n"]
    return {k: {t: {"n": n, "rate": w / n} for t, (w, n) in v.items()} for k, v in acc.items()}, cpu


def levels():
    out = []
    for name in sorted(os.listdir(os.path.join(V2, "work"))):
        if name.isdigit() and int(name) <= 1000:
            p3 = load(os.path.join(V2, "work", name, "p3.json"))
            if p3 and "tiers" in p3:
                out.append((int(name), p3))
    return out


def level(ex, n, p3):
    f = os.path.join(OUT, "work", f"{n:04d}.json")
    if os.path.exists(f):
        return "done"
    guard()
    w = P.W(n)
    fin, prep = w.get("final.json"), w.get("prep.json")
    th = [float(t) for t in w.get("scan.json")["choice"]["thetas"]]
    keys = ["orig"] + [v["key"] for v in fin["tiers"].values()]
    maps = {k: (P.lj_orig(prep) if k == "orig" else P.lj_seed(prep, k)) for k in keys}
    t0 = time.time()
    a, ca = run(ex, maps, [(k, t, i) for k in keys for i, t in enumerate(th)], "v1", SEED_A)
    m = load(os.path.join(V2, "work", f"{n:04d}", "m.json")) or {}
    b, reused, need = {}, 0, []
    for k in keys:
        for i, t in enumerate(th):
            x = m.get(k, {}).get(f"θ:{t:g}")
            if x and x["n"] == GAMES:
                b.setdefault(k, {})[f"{t:g}"] = {"n": x["n"], "rate": x["rate"], "src": "p3"}
                reused += 1
            else:
                need.append((k, t, i))
    cb = 0.0
    if need:
        r, cb = run(ex, maps, need, "v2", SEED_B)
        for k, v in r.items():
            for t, x in v.items():
                b.setdefault(k, {})[t] = {**x, "src": "sep"}
    res = {"level": n, "thetas": th, "a_v1": a, "b_v2": b, "bReused": reused, "bMeasured": len(need),
           "wall": round(time.time() - t0, 1), "cpuSec": round(ca + cb, 1),
           "evalVer": {"botBlob": blob(), "worktreeHead": subprocess.run(["git", "rev-parse", "--short", "HEAD"],
                                                                        capture_output=True, text=True).stdout.strip()},
           "seeds": {"a": SEED_A, "b": SEED_B}}
    P.save(f, res)
    return f"reused {reused} measured {len(need)}"


def main_run():
    os.makedirs(os.path.join(OUT, "work"), exist_ok=True)
    guard()
    lv = levels()
    with ProcessPoolExecutor(WORKERS) as ex:
        for i, (n, p3) in enumerate(lv):
            t = time.time()
            r = level(ex, n, p3)
            print(f"{n} {r} {time.time() - t:.1f}s [{i + 1}/{len(lv)}]", flush=True)
    print("end", time.strftime("%Y-%m-%d %H:%M:%S"), flush=True)


def report():
    rows = {}
    for n, p3 in levels():
        r = load(os.path.join(OUT, "work", f"{n:04d}.json"))
        if not r:
            continue
        fin = P.W(n).get("final.json")
        th = [f"{t:g}" for t in r["thetas"]]

        def wd(src, key):
            return sum(src[key][t]["rate"] for t in th) / len(th) - sum(src["orig"][t]["rate"] for t in th) / len(th)
        st = {}
        for t, v in fin["tiers"].items():
            st[t] = {"R2": v["delta"], "a": wd(r["a_v1"], v["key"]), "b": wd(r["b_v2"], v["key"]),
                     "c": p3["tiers"][t]["v2Delta"]}
        rows[n] = st
    stages = ("R2", "a", "b", "c")
    summ = {"levels": len(rows), "stageNote": "R2 stored (v1, selected) | a v1 fresh seeds R2 θ pair | "
                                              "b v2 R2 θ pair | c ③ v2 own θ pair"}
    for s in stages:
        def sign_ok(t, d):
            return (d > 0) if t.startswith("e") else (d < 0)
        summ[s] = {
            "medAbs": {t: round(statistics.median(abs(v[t][s]) for v in rows.values()), 4) for t in ("e2", "h2")},
            "outerPass013": sum(1 for v in rows.values() if all(sign_ok(t, v[t][s]) and abs(v[t][s]) >= P.OUTER_MIN for t in ("e2", "h2"))),
            "outerSignFlipLevels": sum(1 for v in rows.values() if any(not sign_ok(t, v[t][s]) for t in ("e2", "h2"))),
            "innerSignFlipTiers": sum(1 for v in rows.values() for t in ("e1", "h1") if t in v and not sign_ok(t, v[t][s])),
        }
    flips44 = sorted(n for n, v in rows.items() if any(not ((v[t]["c"] > 0) if t == "e2" else (v[t]["c"] < 0)) for t in ("e2", "h2")))

    def first_flip(v):
        for s in ("a", "b", "c"):
            if any(not ((v[t][s] > 0) if t == "e2" else (v[t][s] < 0)) for t in ("e2", "h2")):
                return s
        return "none"
    summ["flip44"] = {"n": len(flips44), "firstFlipStage": dict(Counter(first_flip(rows[n]) for n in flips44)),
                      "levels": {n: first_flip(rows[n]) for n in flips44}}
    summ["meanShift"] = {f"{x}->{y}": {t: round(statistics.mean(abs(v[t][y]) - abs(v[t][x]) for v in rows.values()), 4)
                                         for t in ("e2", "h2")} for x, y in (("R2", "a"), ("a", "b"), ("b", "c"))}
    P.save(os.path.join(OUT, "sep_summary.json"), summ)
    P.save(os.path.join(OUT, "sep_levels.json"), {str(k): v for k, v in rows.items()})
    print(json.dumps(summ, ensure_ascii=False))


if __name__ == "__main__":
    {"run": main_run, "report": report}[sys.argv[1]]()
