"""Live pilot plan B v3 (10 §9-9-3) — B v2 extended with non-consensus R2 levels at p0 0.35~0.85. Stored values only.

Rules: 32~100 ceiling h2 levels of B v2 are replaced except the top-3 traffic ones; imports = R2 levels with AF p0 in
[0.35, 0.85], v1 two-stage pass (R2 and (a)), eligible (exclusions kept), e2 exposed; greedy order = covers a gimmick
missing from the plan, then daily first-try traffic. Tag by the exposed tier under v2:
  near-consensus (same sign in b and c, no collapse) / disagree (reversed in b or c, or max(|b|,|c|) < 0.5 |a|).
Risk: predicted user Δ = expit(logit(p0) + β·botLogitΔ) − p0, β = 0.429 (doc 25 logit slope), botLogitΔ from bot W
of the original and the exposed variant (v2: ③ own θ pair; v1: (a) fresh seeds, R2 θ pair).
Usage: python scripts/pv_dda_pilot_v3.py
"""
from __future__ import annotations

import json
import math
import os
import statistics
import sys
from collections import Counter

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import pv_dda as P  # noqa: E402
import pv_dda_pilot_v2 as V2P  # noqa: E402

V2 = os.path.join(P.SB, "dda_sets_v2")
CONS = os.path.join(V2, "consensus")
BETA = 0.429
KEEP_TOP = 3
WEEKS = 4


def logit(p):
    p = min(max(p, 1e-3), 1 - 1e-3)
    return math.log(p / (1 - p))


def expit(x):
    return 1 / (1 + math.exp(-x))


def bot_w(n, key, src):
    """bot pair-mean success: src 'v2' -> ③ m.json at v2 θ pair, 'v1' -> sep (a) at R2 θ pair."""
    if src == "v2":
        p3 = P.load(os.path.join(V2, "work", f"{n:04d}", "p3.json"))
        m = P.load(os.path.join(V2, "work", f"{n:04d}", "m.json"))
        pts = [f"θ:{t:g}" for t in p3["thetasV2"]]
        return sum(m[key][p]["rate"] for p in pts) / len(pts)
    s = P.load(os.path.join(V2, "sep", "work", f"{n:04d}.json"))
    th = [f"{t:g}" for t in s["thetas"]]
    return sum(s["a_v1"][key][t]["rate"] for t in th) / len(th)


def main():
    lv = {int(k): v for k, v in P.load(os.path.join(CONS, "levels.json")).items()}
    prep = P.load(os.path.join(V2P.AFD, "prep.json"))
    b2 = P.load(os.path.join(CONS, "pilot_B_v2.json"))["levels"]
    for r in lv.values():
        r["gimmicks"] = V2P.gimmicks(prep[str(r["level"])]["features"]) if str(r["level"]) in prep else ["?"]
        r["daily"] = round((r["afFtN"] or 0) / V2P.DAYS, 1)
        r["eligible"] = r["segment"] != "501-1000" and not r["exclude"] and (r["afFtN"] or 0) >= 100
    ceil32 = sorted([x for x in b2 if x["segment"] == "32-100" and x["afFtRate"] >= 0.9], key=lambda x: -x["daily"])
    drop = {x["level"] for x in ceil32[KEEP_TOP:]}
    plan = [{**lv[x["level"]], **{k: x[k] for k in ("pick", "expose", "exposeToken", "botDelta", "disType", "consensusTag")}}
            for x in b2 if x["level"] not in drop]
    have = {x["level"] for x in plan}
    pool = [r for r in lv.values() if r["eligible"] and r["v1Pass"] and 0.35 <= r["afFtRate"] <= 0.85 and r["level"] not in have]
    covered = {g for x in plan for g in x["gimmicks"]}
    missing = [g for g in V2P.GIMMICKS if g not in covered]
    imports = []
    while len(imports) < len(drop) and pool:
        pool.sort(key=lambda r: (-len(set(r["gimmicks"]) & set(missing)), -r["daily"], r["level"]))
        r = pool.pop(0)
        missing = [g for g in missing if g not in r["gimmicks"]]
        imports.append({**r, "pick": "import", "expose": "e2", "exposeToken": r["tokens"]["e2"], "botDelta": r["outer"]["e2"]})
    plan += imports

    for x in plan:
        t, o = x["expose"], x["outer"][x["expose"]]
        s = 1 if t == "e2" else -1
        rev = [st for st in ("b", "c") if s * o[st] < 0]
        collapse = max(abs(o["b"]), abs(o["c"])) < 0.5 * abs(o["a"])
        x["v2Tag"] = ("consensus" if x["pick"] == "consensus" else
                      "disagree:reversed" if rev else "disagree:collapsed" if collapse else "near-consensus")
        x["v2Reversed"] = rev
        n = x["level"]
        k = P.W(n).get("final.json")["tiers"][t]["key"]
        risk = {}
        for src in ("v1", "v2"):
            wo, wv = bot_w(n, "orig", src), bot_w(n, k, src)
            bl = logit(wv) - logit(wo)
            pu = expit(logit(x["afFtRate"]) + BETA * bl)
            risk[src] = {"botWOrig": round(wo, 4), "botWVar": round(wv, 4), "botLogitDelta": round(bl, 4),
                         "predUserDelta": round(pu - x["afFtRate"], 4)}
        x["risk"] = risk
        pu2 = risk["v2"]["predUserDelta"]
        x["riskFlag"] = ("opposite" if s * pu2 < 0 else "none-effect" if abs(pu2) < 0.01 else "ok")

    def coverage(pl):
        cov = {"n": len(pl), "bySegment": dict(Counter(r["segment"] for r in pl)), "expose": dict(Counter(r["expose"] for r in pl)),
               "v2Tag": dict(Counter(r["v2Tag"] for r in pl))}
        g = Counter(z for r in pl for z in r["gimmicks"])
        cov["gimmicks"] = {k: g.get(k, 0) for k in ("none",) + V2P.GIMMICKS}
        cov["gimmicksZero"] = [k for k in V2P.GIMMICKS if not g.get(k)]
        p0 = [r["afFtRate"] for r in pl]
        cov["p0"] = {"bands": dict(Counter(("0.35-0.85", "0.85-0.9", ">=0.9", "<0.35")[V2P.band(z)] for z in p0)),
                     "min": min(p0), "median": statistics.median(p0), "max": max(p0)}
        ng = lambda r: r["daily"] * 7 * WEEKS / 2
        for st, lab in (("a", "v1"), ("c", "v2")):
            d = [r["botDelta"][st] for r in pl]
            sd = statistics.pstdev(d)
            w = sum(ng(r) / (2 * r["afFtRate"] * (1 - r["afFtRate"])) for r in pl)
            ld = [r["risk"][lab]["botLogitDelta"] for r in pl]
            sdl = statistics.pstdev(ld)
            wl = sum(ng(r) * r["afFtRate"] * (1 - r["afFtRate"]) / 2 for r in pl)
            cov[f"botDelta_{lab}"] = {"mean": round(statistics.mean(d), 4), "sd": round(sd, 4), "seSlopeProb4w": round(1 / math.sqrt(sd ** 2 * w), 4),
                                      "logitSd": round(sdl, 4), "seSlopeLogit4w": round(1 / math.sqrt(sdl ** 2 * wl), 4)}
        w08 = sum(ng(r) / (2 * r["afFtRate"] * (1 - r["afFtRate"])) for r in pl)
        cov["seSlopeProb4w_sd008"] = round(1 / math.sqrt(0.08 ** 2 * w08), 4)
        cov["nPerGroup4w"] = {s: round(sum(ng(r) for r in pl if r["segment"] == s)) for s in ("32-100", "101-300", "301-500")}
        cov["dailyBySegment"] = {s: round(sum(r["daily"] for r in pl if r["segment"] == s), 1) for s in ("32-100", "101-300", "301-500")}
        return cov

    cov = coverage(plan)
    dis = [r for r in plan if r["v2Tag"].startswith("disagree")]
    keepk = ("level", "segment", "pick", "v2Tag", "v2Reversed", "disType", "consensusTag", "expose", "exposeToken", "botDelta",
             "afFtRate", "afFtN", "daily", "gimmicks", "risk", "riskFlag", "verifyPass", "verifyFail")
    out = {"_note": "plan B v3 — B v2 + non-consensus imports at p0 0.35~0.85 (NOT APPROVED)", "coverage": cov,
           "dropped": sorted(drop), "imports": [r["level"] for r in imports],
           "disagree": {"n": len(dis), "types": dict(Counter(r["v2Tag"] for r in dis))},
           "levels": [{k: r.get(k) for k in keepk} for r in plan]}
    P.save(os.path.join(CONS, "pilot_B_v3.json"), out)
    print(json.dumps({k: out[k] for k in ("coverage", "dropped", "imports", "disagree")}, ensure_ascii=False))
    for r in plan:
        print(r["level"], r["segment"], r["pick"], r["v2Tag"], r["expose"], r["exposeToken"], f"p0={r['afFtRate']:.3f}", r["daily"],
              "Δ a/b/c=" + "/".join(f"{r['botDelta'][s]:+.2f}" for s in ("a", "b", "c")),
              "uΔ v1/v2=" + "/".join(f"{r['risk'][s]['predUserDelta']:+.3f}" for s in ("v1", "v2")), r["riskFlag"], ",".join(r["gimmicks"]))


if __name__ == "__main__":
    main()
