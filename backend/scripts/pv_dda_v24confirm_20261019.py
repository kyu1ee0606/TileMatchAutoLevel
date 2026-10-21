"""DDA pilot set — bot v2.4 (rule-parity default) confirmation of existing R2 candidates (2026-10-19, doc 44).

No selection here: candidate tiers are fixed from R2 (v1) / readiness doc 43. This script only CONFIRMS or HOLDS.
Stages per level (each checkpointed to work/NNNN/<stage>.json; resume skips finished stages):
  scan : v2.4, original map, 8θ × 64 games (seed band 21.0M)            -> θ pair W≈0.5 (pv_dda.choose_pair)
  c1   : v2.4, orig + tiers, θ pair × 950 (21.2M) + robust 600/pt (21.4M): extra θ, low θ, θ0.55, θ0.65
  c2   : v2.4, orig + tiers, θ pair × 950, INDEPENDENT seed band 21.6M (final confirmation)
  result: pre-registered judgement (PREREG.json, written before any result).
Named profiles (v1 code path) are NOT used — rule-parity baseline only.
Bot file guard: bot_simulator.py git blob checked before each level; change -> stop.
Control files in OUT: STOP (stop after current stage), workers (int, read at each level), NO_NEW_AFTER (epoch).

Usage: venv/bin/python scripts/pv_dda_v24confirm_20261019.py init|run|report
Results are BOT-BASED. Not user clear rates (live unverified).
"""
from __future__ import annotations

import hashlib
import json
import math
import os
import signal
import subprocess
import sys
import time
from concurrent.futures import ProcessPoolExecutor

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import pv_dda as P  # noqa: E402

OUT = os.path.join(P.SB, "dda_v24confirm_20261019")
READY = os.path.join(P.SB, "dda_readiness_20261019", "levels.json")
BOT_FILE = os.path.join(P.BACKEND, "app", "core", "bot_simulator.py")
BOT_BLOB = "06a5dc9b36a33c40178239c236c63a917071c796"   # HEAD b757f70: v2.4 default = rule-parity items only
BOT_VER = "v2.4"
SEED = {"scan": 21_000_000, "pair": 21_200_000, "rob": 21_400_000, "ind": 21_600_000}
PAIR_GAMES, ROB_GAMES = P.S2_GAMES, P.ROBUST_GAMES        # 950, 600
MID_POINTS = ["θ:0.55", "θ:0.65"]
OUTER_MIN, INNER_MIN = 0.10, 0.04                          # consensus010v2 v2-stage scale (A basis), inner as R2
P5 = {429, 433, 441, 466, 479, 493, 494, 499}              # doc 42 §6 — never measured/reused here
DEADLINE_HARD = "2026-10-20 10:00"                         # KST, supervisor kills before this

PREREG = {
    "written": None, "bot": BOT_VER, "botBlob": BOT_BLOB, "seeds": SEED,
    "games": {"scan": "8θ×64 orig", "pair": "2θ×950 per map", "robust": "600 per point (extra θ, low θ, 0.55, 0.65)",
              "independent": "2θ×950 per map, new seed band"},
    "tiersMeasured": "class A: setTiersUsable (doc 43). class B: all R2 tiers",
    "judge": {
        "outer(e2,h2) c1": f"sign kept & |Δ|>={OUTER_MIN} & CI lo>0 (z=2.4977, indep) & robust judge pass over pair+extraθ+0.55+0.65",
        "inner(e1,h1) c1": f"sign kept & |Δ|>={INNER_MIN} & CI lo>0 & robust judge pass (+lowθ) & order majority vs outer",
        "outer c2 (independent)": f"sign kept & |Δ|>={OUTER_MIN} & CI lo>0",
        "inner c2": f"sign kept & |Δ|>={INNER_MIN} & CI lo>0 & outer more extreme than inner (pair mean)",
        "set": "PASS5 = all 4 tiers pass c1&c2; PASS3 = e2&h2 pass c1&c2 (inner fail -> 3 tiers); else HOLD",
        "unevaluable": "orig scan max < 0.10 -> HOLD(unevaluable)",
    },
    "notLowered": "no threshold changes after results; no cherry-picking; all measured levels reported",
    "label": "bot-based (v2.4 rule-parity); live user clear rate unverified",
}


def load(p, d=None):
    return json.load(open(p)) if os.path.exists(p) else d


def save(p, o):
    tmp = p + ".tmp"
    with open(tmp, "w") as f:
        json.dump(o, f, ensure_ascii=False, indent=1)
    os.replace(tmp, p)


def blob():
    return subprocess.run(["git", "hash-object", BOT_FILE], capture_output=True, text=True, cwd=P.REPO).stdout.strip()


def lj_hash(lj):
    return hashlib.sha256(json.dumps(lj, sort_keys=True, ensure_ascii=False).encode()).hexdigest()[:16]


def games_task(a):
    from app.core.mc_difficulty import make_skill_profile
    from app.core.pv.evaluate import _TrackingBot
    t0 = time.time()
    bot = _TrackingBot()
    lj = a["lj"]
    base = bot._create_initial_state(lj, int(lj["max_moves"]))
    bot._precompute_blocking_map(base)
    prof = make_skill_profile(float(a["pt"][2:]), BOT_VER)
    wins = 0
    for i in range(a["start"], a["start"] + a["count"]):
        bot._rng.seed(a["seed"] + i)
        bot.reset_track()
        wins += 1 if bot._play_game(bot._fast_copy_state(base), prof).cleared else 0
    return {"key": a["key"], "pt": a["pt"], "wins": wins, "n": a["count"], "sec": time.time() - t0}


def run_points(ex, maps, pts, seed_base):
    """pts [(point, games, idx)] -> {key: {pt: {n, wins, rate}}}, cpu, games. CRN: same seeds per point across maps."""
    futs = [ex.submit(games_task, {"key": k, "pt": pt, "lj": lj, "seed": seed_base + idx * 10_000,
                                   "start": s, "count": min(100, g - s)})
            for k, lj in maps.items() for pt, g, idx in pts for s in range(0, g, 100)]
    acc, cpu, ng = {}, 0.0, 0
    for f in futs:
        r = f.result()
        cpu += r["sec"]
        ng += r["n"]
        x = acc.setdefault(r["key"], {}).setdefault(r["pt"], [0, 0])
        x[0] += r["wins"]
        x[1] += r["n"]
    return {k: {p: {"n": n, "wins": w, "rate": w / n} for p, (w, n) in v.items()} for k, v in acc.items()}, cpu, ng


def queue():
    rows = json.load(open(READY))
    q = []
    for r in rows:
        if r["class"] not in ("A", "B") or r["level"] in P5:
            continue
        if r["class"] == "A":
            tiers = ["e2", "h2"] if r["setTiersUsable"] == "3tier" else ["e1", "e2", "h1", "h2"]
            assert r["setTiersUsable"] in ("3tier", "5tier") and all(t in r["tiers"] for t in tiers)
            pri = 0 if (r["level"] <= 500 and r.get("afN100")) else 1
        else:
            tiers = sorted(r["tiers"])
            pri = 2 if r["level"] <= 1000 else 3
        q.append({"level": r["level"], "class": r["class"], "segment": r["segment"], "priority": pri,
                  "tiers": {t: r["tiers"][t]["candKey"] for t in tiers},
                  "tokens": {t: r["tiers"][t]["token"] for t in tiers},
                  "variantIdHash16": {t: r["tiers"][t]["variantIdHash16"] for t in tiers},
                  "canonicalMapSha256": r["canonicalMapSha256"], "pilotB_v3_1": r.get("pilotB_v3_1"),
                  "afN100": r.get("afN100")})
    q.sort(key=lambda x: (x["priority"], x["level"]))
    return q


def init():
    os.makedirs(os.path.join(OUT, "work"), exist_ok=True)
    if os.path.exists(os.path.join(OUT, "PREREG.json")):
        raise SystemExit("PREREG exists — not overwriting")
    pre = dict(PREREG, written=time.strftime("%Y-%m-%d %H:%M:%S %Z"))
    save(os.path.join(OUT, "PREREG.json"), pre)
    q = queue()
    save(os.path.join(OUT, "queue.json"), q)
    print(len(q), {p: sum(1 for x in q if x["priority"] == p) for p in range(4)})


def ctl(name, default=None):
    p = os.path.join(OUT, name)
    if not os.path.exists(p):
        return default
    return open(p).read().strip()


def stop_now():
    if ctl("STOP") is not None:
        return "STOP file"
    na = ctl("NO_NEW_AFTER")
    if na and time.time() >= float(na):
        return "NO_NEW_AFTER reached"
    return None


def theta_pts(ts):
    return [f"θ:{t:g}" for t in ts]


def measure_level(ex, item):
    n = item["level"]
    d = os.path.join(OUT, "work", f"{n:04d}")
    os.makedirs(d, exist_ok=True)
    if os.path.exists(os.path.join(d, "result.json")):
        return "done", 0
    if blob() != BOT_BLOB:
        raise SystemExit(f"BOT FILE CHANGED -> {blob()} STOP")
    prep = P.W(n).get("prep.json")
    keys = ["orig"] + list(item["tiers"].values())
    maps = {k: (P.lj_orig(prep) if k == "orig" else P.lj_seed(prep, k)) for k in keys}
    hashes = {k: lj_hash(v) for k, v in maps.items()}
    games = 0
    sc = load(os.path.join(d, "scan.json"))
    if sc is None:
        t0 = time.time()
        r, cpu, ng = run_points(ex, {"orig": maps["orig"]}, [(f"θ:{t:g}", P.SCAN_GAMES, i) for i, t in enumerate(P.SCAN_THETAS)], SEED["scan"])
        rates = {f"{t:g}": r["orig"][f"θ:{t:g}"]["rate"] for t in P.SCAN_THETAS}
        sc = {"rates": rates, "choice": P.choose_pair(rates), "cpu": cpu, "games": ng, "wall": time.time() - t0}
        save(os.path.join(d, "scan.json"), sc)
        games += ng
    if not sc["choice"]["evaluable"]:
        save(os.path.join(d, "result.json"), {"level": n, "status": "HOLD", "reason": "unevaluable: " + sc["choice"]["reason"],
                                              "mapHash16": hashes})
        return "HOLD unevaluable", games
    th = sc["choice"]["thetas"]
    xt = P.extra_theta(sc["rates"], th)
    lt = P.low_theta(th, xt)
    if stop_now():
        return "stopped", games
    c1 = load(os.path.join(d, "c1.json"))
    if c1 is None:
        t0 = time.time()
        plan = [(p, PAIR_GAMES, i) for i, p in enumerate(theta_pts(th))]
        r, cpu, ng = run_points(ex, maps, plan, SEED["pair"])
        rob_pts = list(dict.fromkeys([f"θ:{xt:g}", f"θ:{lt:g}"] + MID_POINTS))
        rob_pts = [p for p in rob_pts if p not in theta_pts(th)]
        r2, cpu2, ng2 = run_points(ex, maps, [(p, ROB_GAMES, 2 + j) for j, p in enumerate(rob_pts)], SEED["rob"])
        for k, v in r2.items():
            r[k].update(v)
        c1 = {"m": r, "robPoints": rob_pts, "cpu": cpu + cpu2, "games": ng + ng2, "wall": time.time() - t0}
        save(os.path.join(d, "c1.json"), c1)
        games += ng + ng2
    if stop_now():
        return "stopped", games
    c2 = load(os.path.join(d, "c2.json"))
    if c2 is None:
        t0 = time.time()
        r, cpu, ng = run_points(ex, maps, [(p, PAIR_GAMES, i) for i, p in enumerate(theta_pts(th))], SEED["ind"])
        c2 = {"m": r, "cpu": cpu, "games": ng, "wall": time.time() - t0}
        save(os.path.join(d, "c2.json"), c2)
        games += ng
    res = judge(item, th, xt, lt, c1, c2)
    res.update({"mapHash16": hashes, "scanRates": sc["rates"], "evalVer": {"bot": BOT_VER, "botBlob": BOT_BLOB, "seeds": SEED},
                "cpuSec": round(sc.get("cpu", 0) + c1["cpu"] + c2["cpu"], 1),
                "gamesTotal": sc.get("games", 0) + c1["games"] + c2["games"]})
    save(os.path.join(d, "result.json"), res)
    return res["status"], games


def wpair(m, k, pair):
    return sum(m[k][p]["rate"] for p in pair) / len(pair)


def ci(m, k, pair, sign):
    a = {"theta": {p: m[k][p] for p in pair}}
    b = {"theta": {p: m["orig"][p] for p in pair}}
    return P.indep_diff(a, b) if sign > 0 else P.indep_diff(b, a)


def robust(m, k, sign, pts):
    rc = {p: v["rate"] for p, v in m[k].items()}
    ro = {p: v["rate"] for p, v in m["orig"].items()}
    use = [p for p in pts if p in rc and p in ro]
    info = [p for p in use if not (max(rc[p], ro[p]) <= 0.02 or min(rc[p], ro[p]) >= 0.98)]
    dd = {p: sign * (rc[p] - ro[p]) for p in info}
    ok = sum(1 for v in dd.values() if v > 0)
    need = math.ceil(2 * len(info) / 3) if info else 1
    spread = (max(dd.values()) - min(dd.values())) if dd else 0.0
    sens = any(v < 0 for v in dd.values()) and spread >= 0.15
    return {"pass": bool(info) and ok >= need and not sens, "informative": len(info), "dirOk": ok, "need": need,
            "sensitive": sens, "deltas": {p: round(v, 4) for p, v in dd.items()}}


def judge(item, th, xt, lt, c1, c2):
    pair = theta_pts(th)
    m1, m2 = c1["m"], c2["m"]
    tiers = {}
    for t, k in item["tiers"].items():
        sign = 1 if t.startswith("e") else -1
        inner = t in ("e1", "h1")
        mn = INNER_MIN if inner else OUTER_MIN
        d1, d2 = wpair(m1, k, pair) - wpair(m1, "orig", pair), wpair(m2, k, pair) - wpair(m2, "orig", pair)
        ci1, ci2 = ci(m1, k, pair, sign), ci(m2, k, pair, sign)
        pts = pair + [f"θ:{xt:g}"] + MID_POINTS + ([f"θ:{lt:g}"] if inner else [])
        rj = robust(m1, k, sign, list(dict.fromkeys(pts)))
        ok1 = sign * d1 > 0 and abs(d1) >= mn and ci1["lo"] > 0 and rj["pass"]
        ok2 = sign * d2 > 0 and abs(d2) >= mn and ci2["lo"] > 0
        tiers[t] = {"key": k, "token": item["tokens"][t], "c1Delta": round(d1, 4), "c1CiLo": round(ci1["lo"], 4),
                    "c1CiHi": round(ci1["hi"], 4), "robust": rj, "c1ok": ok1, "c2Delta": round(d2, 4),
                    "c2CiLo": round(ci2["lo"], 4), "c2CiHi": round(ci2["hi"], 4), "c2ok": ok2,
                    "wPair_c1": round(wpair(m1, k, pair), 4), "wPair_c2": round(wpair(m2, k, pair), 4)}
    for o_, i_ in (("e2", "e1"), ("h2", "h1")):
        if i_ in tiers:
            sign = 1 if o_ == "e2" else -1
            ko, ki = tiers[o_]["key"], tiers[i_]["key"]
            use = [p for p in pair + [f"θ:{xt:g}", f"θ:{lt:g}"] + MID_POINTS if p in m1[ko] and p in m1[ki]]
            use = list(dict.fromkeys(use))
            good = sum(1 for p in use if sign * (m1[ko][p]["rate"] - m1[ki][p]["rate"]) > 0)
            ord1 = bool(use) and good * 2 > len(use)
            ord2 = sign * (wpair(m2, ko, pair) - wpair(m2, ki, pair)) > 0
            tiers[i_].update({"order1": ord1, "order2": ord2})
            tiers[i_]["c1ok"] = tiers[i_]["c1ok"] and ord1
            tiers[i_]["c2ok"] = tiers[i_]["c2ok"] and ord2
    ok = {t: v["c1ok"] and v["c2ok"] for t, v in tiers.items()}
    if not (ok.get("e2") and ok.get("h2")):
        status = "HOLD"
        fails = [t for t in ("e2", "h2") if not ok.get(t)]
        reason = "outer fail: " + ",".join(f"{t}({'c1' if not tiers[t]['c1ok'] else 'c2'})" for t in fails)
    elif all(t in ok and ok[t] for t in ("e1", "h1")):
        status, reason = "PASS5", ""
    else:
        status = "PASS3"
        reason = "" if "e1" not in tiers else "inner fail -> 3 tiers"
    return {"level": item["level"], "class": item["class"], "status": status, "reason": reason, "thetas": th,
            "extraTheta": xt, "lowTheta": lt, "wOrig_c1": round(wpair(m1, "orig", pair), 4),
            "wOrig_c2": round(wpair(m2, "orig", pair), 4), "tiers": tiers, "label": PREREG["label"]}


_STOP = False


def _term(*_):
    global _STOP
    _STOP = True
    raise KeyboardInterrupt


def main_run():
    signal.signal(signal.SIGTERM, _term)
    q = load(os.path.join(OUT, "queue.json"))
    prog = os.path.join(OUT, "progress.jsonl")
    ex, nw = None, 0
    try:
        for i, item in enumerate(q):
            why = stop_now()
            if why:
                print("stop:", why, flush=True)
                break
            if os.path.exists(os.path.join(OUT, "work", f"{item['level']:04d}", "result.json")):
                continue
            want = max(1, min(6, int(ctl("workers", "1") or 1)))
            if want != nw:
                if ex:
                    ex.shutdown(wait=True)
                ex, nw = ProcessPoolExecutor(want), want
            t0 = time.time()
            st, g = measure_level(ex, item)
            wall = time.time() - t0
            rec = {"t": time.strftime("%Y-%m-%d %H:%M:%S"), "level": item["level"], "class": item["class"],
                   "priority": item["priority"], "status": st, "games": g, "wall": round(wall, 1), "workers": nw,
                   "gps": round(g / wall, 1) if wall > 0 else None, "idx": i + 1, "of": len(q)}
            with open(prog, "a") as f:
                f.write(json.dumps(rec, ensure_ascii=False) + "\n")
            print(json.dumps(rec, ensure_ascii=False), flush=True)
            if st == "stopped":
                break
        else:
            print("queue end", flush=True)
    except KeyboardInterrupt:
        print("terminated (SIGTERM) — finished stages are checkpointed", flush=True)
    finally:
        if ex:
            ex.shutdown(wait=False, cancel_futures=True)


def report():
    q = load(os.path.join(OUT, "queue.json"))
    rows, cnt = [], {}
    for item in q:
        r = load(os.path.join(OUT, "work", f"{item['level']:04d}", "result.json"))
        st = r["status"] if r else "NOT_MEASURED"
        key = f"{item['class']}:{st}"
        cnt[key] = cnt.get(key, 0) + 1
        rows.append({"level": item["level"], "class": item["class"], "priority": item["priority"], "status": st,
                     "reason": (r or {}).get("reason"), "pilotB_v3_1": item["pilotB_v3_1"], "afN100": item["afN100"]})
    save(os.path.join(OUT, "summary.json"), {"generated": time.strftime("%Y-%m-%d %H:%M:%S"), "counts": cnt, "rows": rows,
                                             "label": PREREG["label"]})
    print(json.dumps(cnt, ensure_ascii=False))


if __name__ == "__main__":
    {"init": init, "run": main_run, "report": report}[sys.argv[1]]()
