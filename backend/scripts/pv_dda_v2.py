"""DDA re-measurement with bot v2 (doc 12) — PREPARATION ONLY, NOT APPROVED. Current R2 outputs (dda_sets/) untouched.

Phases (10 §9-5 / §9-6):
  gate  : θ monotonicity regression on the 19 reference levels (selection_v2 'ok'), v1 vs v2, original maps.
  p1    : ① R2 chosen tiers + original — high-skill end points (v2 θ1.0 · θ1.1, OPTIMAL, fast:expert) and the
          robust judge re-applied (R2 judged points + high points). Outer failure -> level excluded, inner -> 3 tiers.
          θ1.0 is dropped for a level when the original's v2 θ1.0 < θ0.85 (z > 2).
  p3    : ③ 32~1000 R2 chosen tiers re-checked with v2: v2 scan -> θ pair, stage-2 950 games, v2 extra/low θ robust
          (+ named profiles AVERAGE/EXPERT reused — named bots are always v1), + ① high points. Comparison only.
  report: summaries -> dda_sets_v2/

Work dir: dda_sets_v2/work/NNNN/ ; outputs dda_sets_v2/. evalVer recorded in every result.
Bot file guard: bot_simulator.py git blob is checked before every level; a change stops the run.

Usage: python scripts/pv_dda_v2.py gate|p1|p3|report [--from N --to N]
"""
from __future__ import annotations

import argparse
import json
import math
import os
import statistics
import subprocess
import sys
import time
from concurrent.futures import ProcessPoolExecutor

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import pv_dda as P  # noqa: E402

V2 = os.path.join(P.SB, "dda_sets_v2")
BOT_FILE = os.path.join(P.BACKEND, "app", "core", "bot_simulator.py")
WORKERS = int(os.environ.get("PV_WORKERS", "4"))

HI_POINTS = ["θ:1.0", "θ:1.1", "profile:optimal", "profile:fast:expert"]
MID_POINTS = ["θ:0.55", "θ:0.65"]          # criterion B core (v2 θ0.55~0.65 best matches user ranking, doc 15)
HI_GAMES = {"θ:1.0": 400, "θ:1.1": 80, "profile:optimal": 400, "profile:fast:expert": 400, "θ:0.85": 400}
SEED_HI = 9_500_000
SEED_V2_SCAN, SEED_V2_S2, SEED_V2_ROB = 5_200_000, 7_200_000, 9_300_000
GATE_THETAS = (0.15, 0.29, 0.35, 0.40, 0.47, 0.55, 0.65, 0.75, 0.85, 1.0)


def blob():
    return subprocess.run(["git", "hash-object", BOT_FILE], capture_output=True, text=True, cwd=P.REPO).stdout.strip()


def head():
    return subprocess.run(["git", "rev-parse", "--short", "HEAD"], capture_output=True, text=True, cwd=P.REPO).stdout.strip()


EVAL_VER = None


def eval_ver():
    global EVAL_VER
    if EVAL_VER is None:
        EVAL_VER = {"bot": "v2", "botCommit": "06df2f2", "head": head(), "botBlob": blob(),
                    "named": "AVERAGE/EXPERT/OPTIMAL/fast:expert are named profiles (always v1 code path)"}
        P.save(os.path.join(V2, "evalVer.json"), EVAL_VER)
    return EVAL_VER


def guard():
    b = blob()
    if b != eval_ver()["botBlob"]:
        raise SystemExit(f"BOT FILE CHANGED {eval_ver()['botBlob']} -> {b} — STOP")


class W2(P.W):
    def __init__(self, n):
        self.n = n
        self.d = os.path.join(V2, "work", f"{n:04d}")
        os.makedirs(self.d, exist_ok=True)


# ── game task (own profile resolution: θ (v2) / named / fast:named) ─────────────────────────────────────
def _profile(spec):
    from app.core.mc_difficulty import make_skill_profile
    from app.models.bot_profile import BotType, get_profile
    if spec.startswith("θ:"):
        return make_skill_profile(float(spec[2:]), "v2")
    if spec.startswith("θv1:"):
        return make_skill_profile(float(spec[4:]), "v1")
    name = spec.split(":", 1)[1]
    if name.startswith("fast:"):
        return get_profile(BotType(name[5:]), fast_mode=True)
    return get_profile(BotType(name))


def games_task(a):
    from app.core.pv.evaluate import _TrackingBot
    t0 = time.time()
    bot = _TrackingBot()
    lj = a["lj"]
    base = bot._create_initial_state(lj, int(lj["max_moves"]))
    bot._precompute_blocking_map(base)
    prof = _profile(a["pt"])
    wins = []
    for i in range(a["start"], a["start"] + a["count"]):
        bot._rng.seed(a["seed"] + i)
        bot.reset_track()
        wins.append(1 if bot._play_game(bot._fast_copy_state(base), prof).cleared else 0)
    return {"key": a["key"], "pt": a["pt"], "start": a["start"], "wins": wins, "sec": time.time() - t0}


def run_points(ex, maps, pts_games, seed_base):
    """maps {key: lj}; pts_games [(point, games, seedIndex)] -> {key: {point: {n, wins, rate}}}, cpuSec."""
    futs = []
    for k, lj in maps.items():
        for pt, g, idx in pts_games:
            ch = 10 if (pt.startswith("θ:") and float(pt[2:]) > 1.0) else 100
            for s in range(0, g, ch):
                futs.append(ex.submit(games_task, {"key": k, "pt": pt, "lj": lj, "seed": seed_base + idx * 10_000,
                                                   "start": s, "count": min(ch, g - s)}))
    acc, cpu = {}, 0.0
    for f in futs:
        r = f.result()
        cpu += r["sec"]
        acc.setdefault(r["key"], {}).setdefault(r["pt"], []).append(r)
    out = {}
    for k, per in acc.items():
        out[k] = {}
        for pt, parts in per.items():
            parts.sort(key=lambda x: x["start"])
            w = [x for p in parts for x in p["wins"]]
            out[k][pt] = {"n": len(w), "wins": sum(w), "rate": sum(w) / len(w)}
    return out, cpu


def z2(a, b):
    """z for rate a > rate b (independent)."""
    p1, n1, p2, n2 = a["rate"], a["n"], b["rate"], b["n"]
    se = math.sqrt(max(p1 * (1 - p1) / n1 + p2 * (1 - p2) / n2, 1e-12))
    return (p1 - p2) / se


def judge(rc, ro, sign, pts):
    """robust_judge on explicit rate dicts (same rule as pv_dda.robust_judge)."""
    use = [p for p in pts if p in rc and p in ro]
    info = [p for p in use if not (max(rc[p], ro[p]) <= 0.02 or min(rc[p], ro[p]) >= 0.98)]
    d = {p: sign * (rc[p] - ro[p]) for p in info}
    ok = sum(1 for v in d.values() if v > 0)
    need = math.ceil(2 * len(info) / 3) if info else 1
    spread = (max(d.values()) - min(d.values())) if d else 0.0
    sens = any(v < 0 for v in d.values()) and spread >= 0.15
    return {"pass": bool(info) and ok >= need and not sens, "informative": len(info), "dirOk": ok, "need": need,
            "sensitive": sens, "spread": round(spread, 4), "deltas": {p: round(v, 4) for p, v in d.items()}}


def r2_levels(lo=32, hi=1500):
    out = []
    for name in sorted(os.listdir(os.path.join(P.DDA, "work"))):
        if name.isdigit() and lo <= int(name) <= hi:
            f = P.W(int(name)).get("final.json")
            if f and f["status"] in ("5tier", "3tier"):
                out.append((int(name), f))
    return out


def old_ctx(n):
    """R2 selection context (v1 measurements) for level n."""
    w = P.W(n)
    prep, scan = w.get("prep.json"), w.get("scan.json")
    th = scan["choice"]["thetas"]
    xt = P.extra_theta(scan["rates"], th)
    points = [f"θ:{xt:g}", "profile:average", "profile:expert", f"θ:{P.low_theta(th, xt):g}"]
    judged = [f"θ:{float(t):g}" for t in th] + points[:3]
    ts = {float(t) for t in th}
    s2 = {k: v for k, v in w.get("s2.json", {}).items() if {float(t) for t in v["theta"]} == ts}
    rob = w.get("robust.json", {})
    rv4 = w.get("robust_v4.json", {"results": {}})
    if rv4.get("points") == points[:3]:
        for k, v in rv4["results"].items():
            rob.setdefault(k, v)
    return prep, th, points, judged, s2, rob


# ── gate ──────────────────────────────────────────────────────────────────────────────────────────────
def gate():
    sel = P.load(os.path.join(P.SB, "selection_v2.json"))
    levels = [x["level"] for x in sel["levels"] if x.get("status") == "ok"]
    maps = {str(n): P.lj_orig(P.W(n).get("prep.json") or {}) for n in levels if P.W(n).get("prep.json")}
    res = {}
    with ProcessPoolExecutor(WORKERS) as ex:
        for ver, pref in (("v1", "θv1:"), ("v2", "θ:")):
            r, cpu = run_points(ex, maps, [(f"{pref}{t:g}", 64, i) for i, t in enumerate(GATE_THETAS)], 41_000_000)
            res[ver] = {"rates": {k: {t: r[k][f"{pref}{t:g}"]["rate"] for t in GATE_THETAS} for k in r}, "cpuSec": round(cpu)}
    summ = {}
    for ver in ("v1", "v2"):
        R = res[ver]["rates"]
        mean = [sum(R[k][t] for k in R) / len(R) for t in GATE_THETAS]
        drops = 0
        for k in R:
            bad = False
            for i, a in enumerate(GATE_THETAS):
                for b in GATE_THETAS[i + 1:]:
                    hi_, lo_ = R[k][b], R[k][a]
                    if z2({"rate": lo_, "n": 64}, {"rate": hi_, "n": 64}) > 2:
                        bad = True
            drops += bad
        summ[ver] = {"mean": [round(x, 3) for x in mean], "meanStrictlyIncreasing": all(b > a for a, b in zip(mean, mean[1:])),
                     "levelsWithSigDrop": drops, "theta1BelowTheta085": sum(1 for k in R if R[k][1.0] < R[k][0.85])}
    out = {"evalVer": eval_ver(), "levels": levels, "thetas": GATE_THETAS, "summary": summ, "raw": res,
           "pass": summ["v2"]["meanStrictlyIncreasing"]}
    P.save(os.path.join(V2, "gate.json"), out)
    print(json.dumps({"pass": out["pass"], "summary": summ}, ensure_ascii=False))


# ── ① high-skill end points ───────────────────────────────────────────────────────────────────────────
def p1_level(ex, n, fin):
    w2 = W2(n)
    if w2.get("p1.json"):
        return "done"
    guard()
    prep, th, points, judged, s2, rob = old_ctx(n)
    keys = ["orig"] + [fin["tiers"][t]["key"] for t in fin["tiers"]]
    maps = {k: (P.lj_orig(prep) if k == "orig" else P.lj_seed(prep, k)) for k in keys}
    hi = w2.get("hi.json", {})
    need = {k: [p for p in HI_POINTS if p not in hi.get(k, {})] for k in keys}
    if "θ:0.85" not in hi.get("orig", {}):
        need["orig"].append("θ:0.85")
    idx = {p: i for i, p in enumerate(HI_POINTS + ["θ:0.85"])}
    t0 = time.time()
    cpu = 0.0
    for pt in HI_POINTS + ["θ:0.85"]:
        ks = [k for k in keys if pt in need[k]]
        if not ks:
            continue
        r, c = run_points(ex, {k: maps[k] for k in ks}, [(pt, HI_GAMES[pt], idx[pt])], SEED_HI)
        cpu += c
        for k, v in r.items():
            hi.setdefault(k, {}).update(v)
    w2.put("hi.json", hi)
    o = hi["orig"]
    drop10 = o["θ:1.0"]["rate"] < o["θ:0.85"]["rate"] and z2(o["θ:0.85"], o["θ:1.0"]) > 2
    hp = [p for p in HI_POINTS if not (drop10 and p == "θ:1.0")]
    ro_old = P.point_rates("orig", s2, rob)
    ro = {**ro_old, **{p: o[p]["rate"] for p in hp}}
    tiers = {}
    for t, v in fin["tiers"].items():
        sign = 1 if t.startswith("e") else -1
        k = v["key"]
        rc_old = P.point_rates(k, s2, rob)
        rc = {**rc_old, **{p: hi[k][p]["rate"] for p in hp}}
        base_pts = judged + ([points[3]] if t in ("e1", "h1") else [])
        tiers[t] = {"key": k, "judgeOld": judge(rc_old, ro_old, sign, base_pts),
                    "judgeHiOnly": judge(rc, ro, sign, hp), "judge": judge(rc, ro, sign, base_pts + hp),
                    "hiRates": {p: round(hi[k][p]["rate"], 4) for p in HI_POINTS}}
    outer_ok = tiers["e2"]["judge"]["pass"] and tiers["h2"]["judge"]["pass"]
    inner_ok = all(tiers[t]["judge"]["pass"] for t in ("e1", "h1") if t in tiers) and len(tiers) == 4
    status = ("excluded" if not outer_ok else ("5tier" if inner_ok else "3tier"))
    res = {"level": n, "r2Status": fin["status"], "status": status, "token": fin["token"] if status == "5tier" else (
        "|".join(P.tok(prep, tiers[t]["key"]) for t in ("e2", "h2")) if status == "3tier" else None),
        "theta1Dropped": drop10, "origHi": {p: round(o[p]["rate"], 4) for p in o}, "tiers": tiers,
        "wall": round(time.time() - t0, 1), "cpuSec": round(cpu, 1), "evalVer": eval_ver(),
        "rule": "robust judge over R2 judged points (v1) + high points (v2 θ1.0/θ1.1, OPTIMAL, fast:expert); "
                "outer fail -> excluded, inner fail -> 3 tiers; θ1.0 dropped if orig v2 θ1.0 < θ0.85 (z>2)"}
    w2.put("p1.json", res)
    return status


# ── ③ v2 re-check of chosen tiers (32~1000) ──────────────────────────────────────────────────────────
def p3_level(ex, n, fin):
    w2 = W2(n)
    if w2.get("p3.json"):
        return "done"
    guard()
    prep, th1, points1, judged1, s2_1, rob1 = old_ctx(n)
    t0, cpu = time.time(), 0.0
    sc = w2.get("scan.json")
    if sc is None:
        r, c = run_points(ex, {"orig": P.lj_orig(prep)}, [(f"θ:{t:g}", P.SCAN_GAMES, i) for i, t in enumerate(P.SCAN_THETAS)],
                          SEED_V2_SCAN)
        cpu += c
        rates = {f"{t:g}": r["orig"][f"θ:{t:g}"]["rate"] for t in P.SCAN_THETAS}
        sc = {"rates": rates, "choice": P.choose_pair(rates)}
        w2.put("scan.json", sc)
    if not sc["choice"]["evaluable"]:
        res = {"level": n, "status": "unevaluable_v2", "reason": sc["choice"]["reason"], "evalVer": eval_ver()}
        w2.put("p3.json", res)
        return res["status"]
    th = sc["choice"]["thetas"]
    xt = P.extra_theta(sc["rates"], th)
    lt = P.low_theta(th, xt)
    keys = ["orig"] + [fin["tiers"][t]["key"] for t in fin["tiers"]]
    maps = {k: (P.lj_orig(prep) if k == "orig" else P.lj_seed(prep, k)) for k in keys}
    m = w2.get("m.json", {})
    plan = [(f"θ:{t:g}", P.S2_GAMES, i) for i, t in enumerate(th)] + [(f"θ:{xt:g}", P.ROBUST_GAMES, 2), (f"θ:{lt:g}", P.ROBUST_GAMES, 3)]
    plan += [(pt, P.ROBUST_GAMES, 4 + j) for j, pt in enumerate(MID_POINTS) if pt not in [x for x, _, _ in plan]]  # criterion B
    for pt, g, i in plan:
        ks = [k for k in keys if pt not in m.get(k, {})]
        if ks:
            r, c = run_points(ex, {k: maps[k] for k in ks}, [(pt, g, i)], SEED_V2_S2 if i < 2 else SEED_V2_ROB)
            cpu += c
            for k, v in r.items():
                m.setdefault(k, {}).update(v)
    w2.put("m.json", m)
    pair = [f"θ:{t:g}" for t in th]
    hi = w2.get("hi.json", {})
    p1 = w2.get("p1.json") or {}
    hp = [p for p in HI_POINTS if not (p1.get("theta1Dropped") and p == "θ:1.0")]

    def rates(k):
        r = {p: v["rate"] for p, v in m[k].items()}
        r.update({p: rob1.get(k, {}).get("point", {}).get(p, {}).get("rate") for p in ("profile:average", "profile:expert")})
        r.update({p: hi.get(k, {}).get(p, {}).get("rate") for p in hp})
        return {p: v for p, v in r.items() if v is not None}

    def w_of(k):
        return sum(m[k][p]["rate"] for p in pair) / 2

    def ci(k, sign):
        a = {"theta": {p: {"rate": m[k][p]["rate"], "n": m[k][p]["n"]} for p in pair}}
        b = {"theta": {p: {"rate": m["orig"][p]["rate"], "n": m["orig"][p]["n"]} for p in pair}}
        return P.indep_diff(a, b) if sign > 0 else P.indep_diff(b, a)

    ro = rates("orig")
    jpts = pair + [f"θ:{xt:g}", "profile:average", "profile:expert"]
    tiers = {}
    for t, v in fin["tiers"].items():
        sign = 1 if t.startswith("e") else -1
        k = v["key"]
        rc = rates(k)
        d = w_of(k) - w_of("orig")
        c = ci(k, sign)
        inner = t in ("e1", "h1")
        pts = jpts + ([f"θ:{lt:g}"] if inner else []) + [p for p in hp if p in rc and p in ro]
        j = judge(rc, ro, sign, pts)
        ptsB = list(dict.fromkeys(pair + MID_POINTS + [f"θ:{xt:g}", "profile:average", "profile:expert"] + ([f"θ:{lt:g}"] if inner else [])))
        jB = judge(rc, ro, sign, ptsB)
        jHi = judge(rc, ro, sign, [p for p in hp if p in rc and p in ro])
        mag = abs(d) >= (P.INNER_MIN if inner else P.OUTER_MIN)
        tiers[t] = {"key": k, "r2Delta": v["delta"], "v2Delta": round(d, 4), "signKept": sign * d > 0, "magOk": mag,
                    "ciLo": round(c["lo"], 4), "ciOk": c["lo"] > 0, "judge": j, "judgeB": jB, "judgeHiOnly": jHi,
                    "hiWarn": not jHi["pass"],
                    "ok": sign * d > 0 and mag and c["lo"] > 0 and j["pass"],
                    "okB": sign * d > 0 and mag and c["lo"] > 0 and jB["pass"]}
    if "e1" in tiers:
        for side, (o_, i_) in (("easy", ("e2", "e1")), ("hard", ("h2", "h1"))):
            sign = 1 if side == "easy" else -1
            ro_, ri_ = rates(tiers[o_]["key"]), rates(tiers[i_]["key"])
            use = [p for p in jpts + [f"θ:{lt:g}"] if p in ro_ and p in ri_ and p in ro]
            good = sum(1 for p in use if sign * (ro_[p] - ri_[p]) > 0)
            tiers[i_]["orderOk"] = bool(use) and good * 2 > len(use)
            tiers[i_]["ok"] = tiers[i_]["ok"] and tiers[i_]["orderOk"]
            tiers[i_]["okB"] = tiers[i_]["okB"] and tiers[i_]["orderOk"]

    def status_of(f):
        if not (tiers["e2"][f] and tiers["h2"][f]):
            return "excluded"
        return "5tier" if len(tiers) == 4 and tiers["e1"][f] and tiers["h1"][f] else "3tier"
    status, statusB = status_of("ok"), status_of("okB")
    res = {"level": n, "r2Status": fin["status"], "proposedStatus": status, "statusA": status, "statusB": statusB,
           "hiWarn": [t for t, v in tiers.items() if v["hiWarn"]], "thetasV2": th, "thetasR2": th1,
           "wOrigV2": round(w_of("orig"), 4), "wOrigR2": fin.get("wOrig"), "extraTheta": xt, "lowTheta": lt,
           "tiers": tiers, "outerDirKept": tiers["e2"]["signKept"] and tiers["h2"]["signKept"],
           "wall": round(time.time() - t0, 1), "cpuSec": round(cpu, 1), "evalVer": eval_ver(),
           "rule": "v2 θ pair 950 games + v2 extra/low θ 600 + named AVERAGE/EXPERT (reused) + ① high points; "
                   "outer: sign kept, |Δ|>=0.13, CI lo>0, robust; inner: |Δ|>=0.04, robust incl. low θ, order majority"}
    w2.put("p3.json", res)
    return status


# ── ② full v2 pipeline for L1001+ unevaluable + timeout_hold ──────────────────────────────────────────
P2_HIGH = (1.1, 1.2)
P2_SCAN_HIGH_GAMES = 16
P2_HIGH_DIV = 8                         # games at θ > 1.0 = base games / 8 (stage-1 8, stage-2 119, robust 75)
P2_HIGH_POOL = [("u0", 0, 32), ("u0", 32, 64), ("flex", 0, 32)]   # pool rounds when the pair has a θ > 1.0
P2_TIME_CAP = 40 * 60
SEED_P2 = {"scan": 5_300_000, "s1": 6_300_000, "s2": 7_300_000, "rob": 9_400_000}


def g_at(theta, base):
    return max(8, base // P2_HIGH_DIV) if theta > 1.0 else base


def as_eval(r_k, pts):
    """run_points result for one key -> pv eval format {"theta": {θstr: {rate, n, wins[]}}, "W"}."""
    th = {}
    for pt in pts:
        v = r_k[pt]
        th[pt[2:]] = {"rate": v["rate"], "n": v["n"], "wins": [1] * v["wins"] + [0] * (v["n"] - v["wins"])}
    return {"theta": th, "W": sum(v["rate"] for v in th.values()) / len(th)}


def eval_maps_v2(ex, maps, thetas, base_games, seed):
    pts = [(f"θ:{t:g}", g_at(t, base_games), i) for i, t in enumerate(thetas)]
    r, cpu = run_points(ex, maps, pts, seed)
    return {k: as_eval(r[k], [p for p, _, _ in pts]) for k in r}, cpu


def choose_pair_v2(rates):
    r = {float(t): v for t, v in rates.items()}
    best = max(r.values()) if r else 0.0
    if best < P.UNEVALUABLE_MAX:
        return {"evaluable": False, "reason": f"orig max rate over v2 scan θ (incl. 1.1/1.2) = {best:.3f} < {P.UNEVALUABLE_MAX}"}
    ranked = sorted(r, key=lambda t: (abs(r[t] - 0.5), t))
    pair = [ranked[0]]
    for t in ranked[1:]:
        if t > 1.0 and pair[0] > 1.0:
            continue                    # at most one θ > 1.0 (cost)
        pair.append(t)
        break
    return {"evaluable": True, "thetas": sorted(pair), "high": any(t > 1.0 for t in pair)}


def p2_targets():
    out = []
    for name in sorted(os.listdir(os.path.join(P.DDA, "work"))):
        if name.isdigit() and int(name) >= 1001:
            f = P.W(int(name)).get("final.json")
            if f and f["status"] in ("unevaluable", "timeout_hold"):
                out.append((int(name), f))
    return out


def p2_step(ex, n, r1):
    """One step for level n (resumable). Returns a short message; 'LEVEL_DONE' when final."""
    w = W2(n)
    if w.get("final.json") is not None:
        return "LEVEL_DONE"
    guard()
    t_start = time.time()
    state = w.get("state.json", {"wall": 0.0, "cpu": 0.0})

    def done(final):
        final.update(level=n, wallSec=round(state["wall"] + time.time() - t_start, 1), cpuSec=round(state["cpu"], 1),
                     evalVer=eval_ver(), r1Status=r1["status"], ruleVersion=P.RULE_VERSION + "+v2")
        w.put("final.json", final)
        return "final " + final["status"]

    def tick(msg, cpu=0.0):
        state["wall"] += time.time() - t_start
        state["cpu"] += cpu
        w.put("state.json", state)
        return msg

    if state["wall"] > P2_TIME_CAP:
        return done({"status": "timeout_hold", "reason": f"v2 level time cap {P2_TIME_CAP}s exceeded"})
    prep = w.get("prep.json")
    if prep is None:
        prep = P.W(n).get("prep.json")
        if prep is None:
            return done({"status": "not_prepared", "reason": "no R1 prep"})
        w.put("prep.json", prep)
        return tick("prep")
    scan = w.get("scan.json")
    if scan is None:
        lj = P.lj_orig(prep)
        r, c1 = run_points(ex, {"orig": lj}, [(f"θ:{t:g}", P.SCAN_GAMES, i) for i, t in enumerate(P.SCAN_THETAS)], SEED_P2["scan"])
        r2, c2 = run_points(ex, {"orig": lj}, [(f"θ:{t:g}", P2_SCAN_HIGH_GAMES, 20 + i) for i, t in enumerate(P2_HIGH)], SEED_P2["scan"])
        rates = {f"{t:g}": r["orig"][f"θ:{t:g}"]["rate"] for t in P.SCAN_THETAS}
        rates.update({f"{t:g}": r2["orig"][f"θ:{t:g}"]["rate"] for t in P2_HIGH})
        w.put("scan.json", {"rates": rates, "games": {"≤1.0": P.SCAN_GAMES, ">1.0": P2_SCAN_HIGH_GAMES},
                            "choice": choose_pair_v2(rates)})
        return tick("scan", c1 + c2)
    ch = scan["choice"]
    if not ch["evaluable"]:
        return done({"status": "unevaluable", "reason": ch["reason"], "scan": scan["rates"]})
    th = ch["thetas"]
    xt = P.extra_theta({k: v for k, v in scan["rates"].items() if float(k) <= 1.0}, th)
    lt = P.low_theta(th, xt)
    points = [f"θ:{xt:g}", "profile:average", "profile:expert", f"θ:{lt:g}"]
    judged = [f"θ:{float(t):g}" for t in th] + points[:3]
    judged_inner = judged + [points[3]]
    pool_plan = P2_HIGH_POOL if ch["high"] else P.POOL_PLAN
    s2 = w.get("s2.json", {})
    if "orig" not in s2:
        out, c = eval_maps_v2(ex, {"orig": P.lj_orig(prep)}, th, P.S2_GAMES, SEED_P2["s2"])
        w.merge("s2.json", out)
        return tick("orig2", c)
    s1, sol, rob = w.get("s1.json", {}), w.get("solve.json", {}), w.get("robust.json", {})
    rounds = w.get("rounds.json", [])
    w_orig = s2["orig"]["W"]
    sides = P.decide(prep, s1, s2, sol, rob, judged, None, judged_inner)

    def missing(k):
        return [p for p in points if p not in rob.get(k, {}).get("point", {})]
    need_rob = (["orig"] if missing("orig") else []) + [k for sd in ("easy", "hard") for k in sides[sd]["robustQueue"] if missing(k)]
    need_rob = list(dict.fromkeys(need_rob))
    if need_rob:
        cpu = 0.0
        for i, pt in enumerate(points):
            ks = [k for k in need_rob if pt in missing(k)]
            if not ks:
                continue
            g = g_at(float(pt[2:]), P.ROBUST_GAMES) if pt.startswith("θ:") else P.ROBUST_GAMES
            spec = pt if pt.startswith("θ:") else "profile:" + pt.split(":", 1)[1]
            r, c = run_points(ex, {k: (P.lj_orig(prep) if k == "orig" else P.lj_seed(prep, k)) for k in ks}, [(spec, g, i)],
                              SEED_P2["rob"])
            cpu += c
            for k, v in r.items():
                rob.setdefault(k, {"point": {}})["point"][pt] = v[spec]
        w.put("robust.json", rob)
        return tick(f"robust {len(need_rob)}", cpu)
    pred = w.get("pred.json", {})
    pq = [k for k in sides["hard"]["predQueue"] if k not in pred]
    if pq and "orig" not in pred:
        pq = ["orig"] + pq
    if pq:
        futs = {k: ex.submit(P.sweep_level_task, {"level_json": P.lj_orig(prep) if k == "orig" else P.lj_seed(prep, k),
                                                  "seed": P.SEED_PRED, "level_number": n}) for k in pq}
        w.merge("pred.json", {k: {"predicted_clear_rate": f.result().get("predicted_clear_rate"),
                                  "error": f.result().get("error")} for k, f in futs.items()})
        return tick(f"pred {len(pq)}")
    sides = P.decide(prep, s1, s2, sol, rob, judged, pred, judged_inner)
    failing = [sd for sd in ("easy", "hard") if sides[sd]["outer"] is None]
    if failing:
        r_idx = len(rounds)
        jobs = []
        while r_idx < len(pool_plan):
            kind, lo, hi = pool_plan[r_idx]
            jobs = []
            for sd in failing:
                u = prep["utc0"] if kind == "u0" else (prep["utc0"] - 1 if sd == "easy" else prep["utc0"] + 1)
                if 1 <= u <= 15:
                    seeds = P.pool_seeds(prep, u)[lo:hi]
                    if seeds:
                        jobs.append((sd, u, seeds))
            if jobs:
                break
            rounds.append({"round": r_idx, "skipped": True})
            r_idx += 1
        if r_idx >= len(pool_plan):
            return P.finalize(w, prep, s1, s2, sol, rob, judged, points, th, sides, rounds, pred, done)
        cpu = 0.0
        new_s1 = {}
        for sd, u, seeds in {(u, tuple(s)): (sd, u, s) for sd, u, s in jobs}.values():
            P.golden_check(w, prep, u, seeds)
            miss = [x for x in seeds if f"{u}:{x}" not in s1]
            if miss:
                out, c = eval_maps_v2(ex, {f"{u}:{x}": P.lj_seed(prep, f"{u}:{x}") for x in miss}, th, P.S1_GAMES, SEED_P2["s1"])
                cpu += c
                new_s1.update(out)
        if new_s1:
            s1 = w.merge("s1.json", new_s1)
        picks = []
        n_pick = 2 if ch["high"] else 4
        for sd, u, seeds in jobs:
            sign = 1 if sd == "easy" else -1
            pool = [f"{u}:{x}" for x in seeds if f"{u}:{x}" in s1 and f"{u}:{x}" not in s2]
            pool = [k for k in pool if sign * (s1[k]["W"] - w_orig) > 0]
            outer = sorted(pool, key=lambda k: (abs((s1[k]["W"] - w_orig) - P.TARGET[sd]), k))[:n_pick // 2]
            inner = sorted([k for k in pool if k not in outer], key=lambda k: (abs((s1[k]["W"] - w_orig) - sign * 0.06), k))[:n_pick // 2]
            picks += outer + inner
        picks = list(dict.fromkeys(picks))
        if picks:
            out, c = eval_maps_v2(ex, {k: P.lj_seed(prep, k) for k in picks}, th, P.S2_GAMES, SEED_P2["s2"])
            cpu += c
            s2 = w.merge("s2.json", out)
            futs = {k: ex.submit(P.solve_check, P.lj_seed(prep, k), P.SOLVER_NODES) for k in picks}
            w.merge("solve.json", {k: f.result() for k, f in futs.items()})
        rounds.append({"round": r_idx, "plan": pool_plan[r_idx], "sides": failing, "stage2": picks})
        w.put("rounds.json", rounds)
        return tick(f"round {r_idx} {pool_plan[r_idx]} picks={len(picks)}", cpu)
    chosen = [sides[sd][k]["key"] for sd in ("easy", "hard") for k in ("outer", "inner") if sides[sd][k]]
    gold = w.get("golden.json", {})
    ung = [k for k in chosen if k not in gold]
    if ung:
        by_u = {}
        for k in ung:
            u, sd_ = k.split(":")
            by_u.setdefault(int(u), []).append(int(sd_))
        for u, seeds in by_u.items():
            P.golden_check(w, prep, u, seeds)
        return tick(f"golden {len(ung)}")
    uns = [k for k in chosen if k not in sol]
    if uns:
        futs = {k: ex.submit(P.solve_check, P.lj_seed(prep, k), P.SOLVER_NODES) for k in uns}
        w.merge("solve.json", {k: f.result() for k, f in futs.items()})
        return tick(f"solve {len(uns)}")
    return P.finalize(w, prep, s1, s2, sol, rob, judged, points, th, sides, rounds, pred, done)


def run_p2(lo, hi):
    eval_ver()
    tg = [(n, f) for n, f in p2_targets() if lo <= n <= hi]
    with ProcessPoolExecutor(WORKERS) as ex:
        for i, (n, f) in enumerate(tg):
            for _ in range(200):
                t = time.time()
                msg = p2_step(ex, n, f)
                print(f"{n} {msg} {time.time() - t:.1f}s [{i + 1}/{len(tg)}]", flush=True)
                if msg == "LEVEL_DONE":
                    break
    print("end", time.strftime("%Y-%m-%d %H:%M:%S"), flush=True)


# ── ① A/B comparison (no measurement) ────────────────────────────────────────────────────────────────
def ab1():
    """A: high end points in the robust judge (p1 status). B: R2 judge (v1 points; v2 θ0.55~0.65 only from ③),
    high end points = warning flags only."""
    from collections import Counter
    roll = P.load(os.path.join(P.SB, "verify_dda_seedvar", "_rollup_32_1500.json"))
    fails = {int(k): v for k, v in roll["perLevelFail"].items()}
    verified = {int(f[:4]) for f in os.listdir(os.path.join(P.SB, "verify_dda_seedvar")) if f[:4].isdigit()}
    rows = {"A": {}, "B": {}}
    lv = {}
    for n, fin in r2_levels():
        p1 = W2(n).get("p1.json")
        if not p1:
            continue
        flips = {}
        for t, v in p1["tiers"].items():
            d = v["judgeHiOnly"]["deltas"]
            neg = [p for p, x in d.items() if x < 0]
            if neg or not v["judge"]["pass"]:
                flips[t] = {"reversedHi": neg, "sensitive": v["judge"]["sensitive"], "dirOk": v["judge"]["dirOk"],
                            "informative": v["judge"]["informative"], "pass": v["judge"]["pass"]}
        stB = fin["status"]
        lv[n] = {"A": p1["status"], "B": stB, "warnB": [t for t, v in p1["tiers"].items() if not v["judgeHiOnly"]["pass"]],
                 "flips": flips, "theta1Dropped": p1["theta1Dropped"],
                 "verified": n in verified, "verifyPass": (n in verified and n not in fails), "verifyFail": fails.get(n)}
        row = P.W(n).get("seedvar_row.json")
        if p1["status"] in ("5tier", "3tier"):
            rows["A"][f"seedvar_{n}"] = {**row, "randSeed": p1["token"]}
        rows["B"][f"seedvar_{n}"] = row
    segs = [(32, 500), (501, 1000), (1001, 1500)]
    summ = {}
    for c in ("A", "B"):
        summ[c] = {"status": dict(Counter(v[c] for v in lv.values())),
                   "bySegment": {f"{a}-{b}": dict(Counter(v[c] for n, v in lv.items() if a <= n <= b)) for a, b in segs},
                   "rows": len(rows[c])}
        ver = [v for v in lv.values() if v["verified"] and v[c] in ("5tier", "3tier")]
        summ[c]["verifiedKept"] = len(ver)
        summ[c]["verifiedKeptPass"] = sum(1 for v in ver if v["verifyPass"])
        summ[c]["verifiedKeptOuterPass"] = sum(1 for v in ver if not any(x.startswith("outer") for x in (v["verifyFail"] or [])))
    onlyA = {n: v for n, v in lv.items() if v["A"] == "excluded" and v["B"] != "excluded"}
    summ["onlyAExcluded"] = len(onlyA)
    summ["onlyAExcludedVerified"] = {n: ("pass" if v["verifyPass"] else v["verifyFail"]) for n, v in onlyA.items() if v["verified"]}
    summ["reversedEndpointCounts"] = dict(Counter(p for v in onlyA.values() for f in v["flips"].values() for p in f["reversedHi"]))
    summ["onlyAReason"] = dict(Counter("sensitive" if any(f["sensitive"] for f in v["flips"].values() if not f["pass"])
                                       else "direction" for v in onlyA.values()))
    summ["warnBLevels"] = sum(1 for v in lv.values() if v["warnB"])
    for c in ("A", "B"):
        d = os.path.join(V2, c)
        P.save(os.path.join(d, "seedvar_rows.json"), {"_note": f"criterion {c} (phase ①) — comparison only, NOT APPROVED", "rows": rows[c]})
        P.save(os.path.join(d, "coverage.json"), {"criterion": c, "evalVer": eval_ver(), **summ[c]})
    P.save(os.path.join(V2, "ab1_levels.json"), {str(k): v for k, v in lv.items()})
    P.save(os.path.join(V2, "ab1_summary.json"), summ)
    print(json.dumps(summ, ensure_ascii=False)[:3000])


def ab3():
    """③ summary: R2 status vs v2 re-check (statusA / statusB), outer failure reasons, verification overlap.
    Comparison only — exports proposed rows to dda_sets_v2/p3_A, p3_B (NOT APPROVED, R2 untouched)."""
    from collections import Counter
    roll = P.load(os.path.join(P.SB, "verify_dda_seedvar", "_rollup_32_1500.json"))
    fails = {int(k): v for k, v in roll["perLevelFail"].items()}
    verified = {int(f[:4]) for f in os.listdir(os.path.join(P.SB, "verify_dda_seedvar")) if f[:4].isdigit()}
    rows = {"A": {}, "B": {}}
    lv = {}
    for n, fin in r2_levels(32, 1000):
        p3 = W2(n).get("p3.json")
        if not p3:
            continue
        if "tiers" not in p3:
            lv[n] = {"r2": fin["status"], "A": p3["status"], "B": p3["status"], "segment": "32-500" if n <= 500 else "501-1000"}
            continue
        T = p3["tiers"]
        reasons = {}
        for t in ("e2", "h2"):
            v = T[t]
            r = [x for x, ok in (("sign", v["signKept"]), ("mag", v["magOk"]), ("ci", v["ciOk"]), ("judge", v["judge"]["pass"])) if not ok]
            if r:
                reasons[t] = r
        # sensitivity: outer threshold 0.10 (R1) instead of 0.13, everything else equal (criterion A)
        ok10 = all(T[t]["signKept"] and abs(T[t]["v2Delta"]) >= 0.10 and T[t]["ciOk"] and T[t]["judge"]["pass"] for t in ("e2", "h2"))
        p1 = W2(n).get("p1.json") or {}
        lv[n] = {"r2": fin["status"], "A": p3["statusA"], "B": p3["statusB"], "p1A": p1.get("status"),
                 "segment": "32-500" if n <= 500 else "501-1000", "outerReasons": reasons,
                 "magOnly": bool(reasons) and all(r == ["mag"] for r in reasons.values()), "outerOk010": ok10,
                 "hiWarn": p3["hiWarn"], "thetasR2": p3["thetasR2"], "thetasV2": p3["thetasV2"],
                 "delta": {t: [T[t]["r2Delta"], T[t]["v2Delta"]] for t in T},
                 "verified": n in verified, "verifyPass": (n in verified and n not in fails), "verifyFail": fails.get(n)}
        prep = P.W(n).get("prep.json")
        row = P.W(n).get("seedvar_row.json")
        for c in ("A", "B"):
            st = lv[n][c]
            if st == "5tier":
                rows[c][f"seedvar_{n}"] = {**row, "randSeed": fin["token"]}
            elif st == "3tier":
                rows[c][f"seedvar_{n}"] = {**row, "randSeed": "|".join(P.tok(prep, T[t]["key"]) for t in ("e2", "h2"))}
    segs = ("32-500", "501-1000")
    summ = {"levels": len(lv), "r2": dict(Counter(v["r2"] for v in lv.values()))}
    for c in ("A", "B"):
        ver = [v for v in lv.values() if v.get("verified") and v[c] in ("5tier", "3tier")]
        summ[c] = {"status": dict(Counter(v[c] for v in lv.values())),
                   "bySegment": {s: dict(Counter(v[c] for v in lv.values() if v["segment"] == s)) for s in segs},
                   "transition": dict(Counter(f"{v['r2']}->{v[c]}" for v in lv.values())), "rows": len(rows[c]),
                   "verifiedKept": len(ver), "verifiedKeptPass": sum(1 for v in ver if v["verifyPass"]),
                   "verifiedKeptOuterPass": sum(1 for v in ver if not any(x.startswith("outer") for x in (v["verifyFail"] or [])))}
    exA = [v for v in lv.values() if v["A"] == "excluded" and "outerReasons" in v]
    summ["outerReasonCountsA"] = dict(Counter(r for v in exA for rs in v["outerReasons"].values() for r in rs))
    summ["outerSignFlipLevels"] = sorted(n for n, v in lv.items() if any("sign" in rs for rs in v.get("outerReasons", {}).values()))
    summ["excludedMagOnlyA"] = sum(1 for v in exA if v["magOnly"])
    summ["keptIfOuter010A"] = sum(1 for v in lv.values() if v.get("outerOk010"))
    ab = [v for v in lv.values() if v.get("p1A")]
    summ["vsPhase1A"] = dict(Counter(f"{v['p1A']}|{v['A']}" for v in ab))
    summ["deltaMedian"] = {t: {"r2": statistics.median([abs(v["delta"][t][0]) for v in lv.values() if "delta" in v]),
                               "v2": statistics.median([abs(v["delta"][t][1]) for v in lv.values() if "delta" in v])} for t in ("e2", "h2")}
    vv = [v for v in lv.values() if v.get("verified")]
    summ["verifiedAll"] = {"n": len(vv), "pass": sum(1 for v in vv if v["verifyPass"]),
                           "AKeptPass": sum(1 for v in vv if v["A"] != "excluded" and v["verifyPass"]),
                           "AExcludedPass": sum(1 for v in vv if v["A"] == "excluded" and v["verifyPass"]),
                           "AExcludedFail": sum(1 for v in vv if v["A"] == "excluded" and not v["verifyPass"])}
    for c in ("A", "B"):
        d = os.path.join(V2, f"p3_{c}")
        P.save(os.path.join(d, "seedvar_rows.json"), {"_note": f"criterion {c} (phase ③ v2 re-check, 32~1000) — comparison only, NOT APPROVED", "rows": rows[c]})
        P.save(os.path.join(d, "coverage.json"), {"criterion": c, "evalVer": eval_ver(), **summ[c]})
    P.save(os.path.join(V2, "ab3_levels.json"), {str(k): v for k, v in lv.items()})
    P.save(os.path.join(V2, "ab3_summary.json"), summ)
    print(json.dumps(summ, ensure_ascii=False)[:4000])


# ── ② A/B flags for finished v2 levels (measures MID + HI points for chosen tiers + orig) ────────────
def p2ab_level(ex, n):
    w = W2(n)
    fin = w.get("final.json")
    if not fin or fin["status"] not in ("5tier", "3tier") or w.get("ab.json"):
        return "skip"
    guard()
    prep = w.get("prep.json")
    keys = ["orig"] + [v["key"] for v in fin["tiers"].values()]
    maps = {k: (P.lj_orig(prep) if k == "orig" else P.lj_seed(prep, k)) for k in keys}
    s2, rob = w.get("s2.json", {}), w.get("robust.json", {})
    extra = w.get("abm.json", {})
    games = {**HI_GAMES, "θ:0.55": P.ROBUST_GAMES, "θ:0.65": P.ROBUST_GAMES}
    pts_all = HI_POINTS + ["θ:0.85"] + MID_POINTS
    cpu = 0.0
    for i, pt in enumerate(pts_all):
        ks = [k for k in keys if pt not in extra.get(k, {}) and pt not in P.point_rates(k, s2, rob)
              and not (pt == "θ:0.85" and k != "orig")]
        if ks:
            r, c = run_points(ex, {k: maps[k] for k in ks}, [(pt, games[pt], 40 + i)], SEED_HI)
            cpu += c
            for k, v in r.items():
                extra.setdefault(k, {}).update(v)
    w.put("abm.json", extra)

    def rates(k):
        r = P.point_rates(k, s2, rob)
        r.update({p: v["rate"] for p, v in extra.get(k, {}).items()})
        return r
    ro = rates("orig")
    drop10 = ("θ:1.0" in ro and "θ:0.85" in ro and ro["θ:1.0"] < ro["θ:0.85"]
              and z2({"rate": ro["θ:0.85"], "n": 400}, {"rate": ro["θ:1.0"], "n": 400}) > 2)
    hp = [p for p in HI_POINTS if not (drop10 and p == "θ:1.0")]
    judged, rp = fin["judgedPoints"], fin["robustPoints"]
    pair = [p for p in judged if p.startswith("θ:")][:2]
    tiers = {}
    for t, v in fin["tiers"].items():
        sign = 1 if t.startswith("e") else -1
        inner = t in ("e1", "h1")
        rc = rates(v["key"])
        a_pts = judged + ([rp[3]] if inner else []) + hp
        b_pts = list(dict.fromkeys(pair + MID_POINTS + [rp[0], "profile:average", "profile:expert"] + ([rp[3]] if inner else [])))
        tiers[t] = {"key": v["key"], "judgeA": judge(rc, ro, sign, a_pts), "judgeB": judge(rc, ro, sign, b_pts),
                    "judgeHiOnly": judge(rc, ro, sign, hp)}

    def st(f):
        if not (tiers["e2"][f]["pass"] and tiers["h2"][f]["pass"]):
            return "excluded"
        return "5tier" if "e1" in tiers and tiers["e1"][f]["pass"] and tiers["h1"][f]["pass"] else "3tier"
    res = {"level": n, "status": fin["status"], "statusA": st("judgeA"), "statusB": st("judgeB"),
           "hiWarn": [t for t, v in tiers.items() if not v["judgeHiOnly"]["pass"]], "theta1Dropped": drop10,
           "tiers": tiers, "cpuSec": round(cpu, 1), "evalVer": eval_ver()}
    w.put("ab.json", res)
    return f"A={res['statusA']} B={res['statusB']}"


def run_p2ab(lo, hi):
    eval_ver()
    lv = sorted(int(x) for x in os.listdir(os.path.join(V2, "work")) if x.isdigit() and lo <= int(x) <= hi)
    with ProcessPoolExecutor(WORKERS) as ex:
        for i, n in enumerate(lv):
            t = time.time()
            r = p2ab_level(ex, n)
            if r != "skip":
                print(f"{n} {r} {time.time() - t:.1f}s [{i + 1}/{len(lv)}]", flush=True)
    print("end", time.strftime("%Y-%m-%d %H:%M:%S"), flush=True)


def run_phase(fn, lo, hi):
    lv = r2_levels(lo, hi)
    eval_ver()
    with ProcessPoolExecutor(WORKERS) as ex:
        for i, (n, fin) in enumerate(lv):
            t = time.time()
            r = fn(ex, n, fin)
            print(f"{n} {r} {time.time() - t:.1f}s [{i + 1}/{len(lv)}]", flush=True)
    print("end", time.strftime("%Y-%m-%d %H:%M:%S"), flush=True)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("phase", choices=["gate", "p1", "p3", "p2", "ab1", "ab3", "p2ab"])
    ap.add_argument("--from", dest="lo", type=int, default=32)
    ap.add_argument("--to", dest="hi", type=int, default=1500)
    a = ap.parse_args()
    os.makedirs(V2, exist_ok=True)
    if a.phase == "gate":
        gate()
    elif a.phase == "p1":
        run_phase(p1_level, a.lo, a.hi)
    elif a.phase == "p2ab":
        run_p2ab(max(a.lo, 1001), a.hi)
    elif a.phase == "ab1":
        ab1()
    elif a.phase == "ab3":
        ab3()
    elif a.phase == "p3":
        run_phase(p3_level, a.lo, min(a.hi, 1000))
    else:
        run_p2(max(a.lo, 1001), a.hi)
    return 0


if __name__ == "__main__":
    sys.exit(main())
