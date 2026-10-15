"""Live pilot candidates v2 (10 §9-9 revision) — stored values only, no measurement.

One exposed variant per level (e2 or h2). Original AF first-try unaided clear rate p0:
  p0 >= 0.9 -> h2 only (ceiling: e2 cannot raise the user rate); p0 < 0.9 -> e2 allowed.
Priority p0 in [0.35, 0.85] (no ceiling / floor), then [0.85, 0.9), then >= 0.9 by ascending p0, gimmick coverage greedy.
Pools: consensus 0.13 -> consensus 0.10v2 (consensus/levels.json). Plan B adds 6 disagreement levels by type
(e2 direction reversed, h2 direction reversed, e2 |Δ| collapsed in v2), ceiling (p0 >= 0.9) excluded.
Power: doc 24 formula SE(slope) = 1 / sqrt(sd(botΔ)^2 · Σ n_i / (2 p0_i (1 - p0_i))), n_i = daily × 28 / 2.
Usage: python scripts/pv_dda_pilot_v2.py
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

CONS = os.path.join(P.SB, "dda_sets_v2", "consensus")
AFD = os.path.join(P.BACKEND, "data", "pv_sandbox", "af_calibration", "bot_compare_L32_500")
DAYS, WEEKS = 35.7, 4
GIMMICKS = ("link", "stack", "craft", "bomb", "grass", "chain", "curtain", "unknown", "teleporter", "frog", "ice")
QUOTA_A = {"32-100": 6, "101-300": 9, "301-500": 6}
QUOTA_B_CONS = {"32-100": 6, "101-300": 7, "301-500": 2}
DIS_TYPES = (("e2rev", 2), ("h2rev", 2), ("e2collapse", 2))


def gimmicks(feat):
    g = {k: feat.get(k if k in ("stack", "craft") else f"eff_{k}", 0) for k in GIMMICKS}
    return [k for k, v in g.items() if v > 0] or ["none"]


def band(p):
    return 0 if 0.35 <= p <= 0.85 else 1 if 0.85 < p < 0.9 else 2 if p >= 0.9 else 3  # 3 = floor (<0.35)


def dis_type(r):
    o = r["outer"]

    def rev(t):
        s = 1 if t == "e2" else -1
        return [x for x in ("b", "c") if s * o[t][x] < 0]
    if rev("e2"):
        return "e2rev"
    if rev("h2"):
        return "h2rev"
    if max(abs(o["e2"]["b"]), abs(o["e2"]["c"])) < 0.5 * abs(o["e2"]["a"]):
        return "e2collapse"
    if max(abs(o["h2"]["b"]), abs(o["h2"]["c"])) < 0.5 * abs(o["h2"]["a"]):
        return "h2collapse"
    return None


def main():
    lv = {int(k): v for k, v in P.load(os.path.join(CONS, "levels.json")).items()}
    prep = P.load(os.path.join(AFD, "prep.json"))
    for n, r in lv.items():
        r["gimmicks"] = gimmicks(prep[str(n)]["features"]) if str(n) in prep else ["?"]
        r["daily"] = round((r["afFtN"] or 0) / DAYS, 1)
        r["eligible"] = r["segment"] != "501-1000" and not r["exclude"] and (r["afFtN"] or 0) >= 100
    elig = [r for r in lv.values() if r["eligible"]]

    def expose(r, want_e2):
        t = "e2" if (want_e2 and r["afFtRate"] < 0.9) else "h2"
        return {**r, "expose": t, "exposeToken": r["tokens"][t], "botDelta": r["outer"][t]}

    def greedy(pool, k, covered):
        out, pool = [], list(pool)
        while pool and len(out) < k:
            pool.sort(key=lambda r: (band(r["afFtRate"]), -len(set(r["gimmicks"]) - covered), r["afFtRate"], r["level"]))
            r = pool.pop(0)
            covered |= set(r["gimmicks"])
            out.append(r)
        return out

    def build(quota, tag):
        sel, covered, notes = [], set(), []
        for s, q in quota.items():
            c13 = [r for r in elig if r["segment"] == s and r["consensus013"]]
            c10 = [r for r in elig if r["segment"] == s and r["consensus010v2"] and not r["consensus013"]]
            mid13 = [r for r in c13 if band(r["afFtRate"]) <= 1]
            mid10 = [r for r in c10 if band(r["afFtRate"]) <= 1]
            notes.append(f"{tag} {s}: p0<0.9 consensus 0.13 {len(mid13)} / +0.10v2 {len(mid10)}; p0 0.35~0.85 "
                         f"{sum(1 for r in c13 + c10 if band(r['afFtRate']) == 0)}")
            pick = greedy(mid13 + mid10, q, covered)          # non-ceiling first (0.13 and 0.10v2 together)
            pick += greedy(c13, q - len(pick), covered) if len(pick) < q else []
            pick += greedy([r for r in c10 if r not in pick], q - len(pick), covered) if len(pick) < q else []
            sel += [{**r, "pick": "consensus"} for r in pick]
        return sel, notes

    def assign(sel):  # e2 for every non-ceiling level (they are the only e2-capable ones), h2 otherwise
        return [expose(r, True) if r["pick"] == "consensus" else r for r in sel]

    plan_a, notes_a = build(QUOTA_A, "A")
    plan_a = assign(plan_a)
    cons_b, notes_b = build(QUOTA_B_CONS, "B")
    cons_b = assign(cons_b)
    dis_pool = [r for r in elig if r["disagree"] and r["afFtRate"] < 0.9 and r["afFtRate"] >= 0.35]
    for r in dis_pool:
        r["disType"] = dis_type(r)
    dis_pick = []
    for typ, k in DIS_TYPES:
        cand = sorted([r for r in dis_pool if r["disType"] == typ and r not in dis_pick],
                      key=lambda r: (band(r["afFtRate"]), -r["daily"], r["level"]))[:k]
        if len(cand) < k and typ == "h2rev":
            notes_b.append(f"B h2rev: only {len(cand)} non-ceiling level(s); filled with h2collapse")
            cand += sorted([r for r in dis_pool if r["disType"] == "h2collapse" and r not in dis_pick],
                           key=lambda r: (band(r["afFtRate"]), -r["daily"], r["level"]))[:k - len(cand)]
        for r in cand:
            t = "h2" if r["disType"].startswith("h2") else "e2"
            dis_pick.append({**r, "pick": "disagree", "expose": t, "exposeToken": r["tokens"][t], "botDelta": r["outer"][t]})
    plan_b = cons_b + dis_pick
    notes_b.append("B disagreement pool (p0 0.35~0.9, eligible): " + json.dumps(dict(Counter(r["disType"] for r in dis_pool))))

    def coverage(plan):
        seg = Counter(r["segment"] for r in plan)
        g = Counter(x for r in plan for x in r["gimmicks"])
        p0 = [r["afFtRate"] for r in plan]
        bands = Counter(("0.35-0.85", "0.85-0.9", ">=0.9", "<0.35")[band(x)] for x in p0)
        cov = {"n": len(plan), "bySegment": dict(seg), "expose": dict(Counter(r["expose"] for r in plan)),
               "gimmicks": {k: g.get(k, 0) for k in ("none",) + GIMMICKS}, "gimmicksZero": [k for k in GIMMICKS if not g.get(k)],
               "p0": {"bands": dict(bands), "min": min(p0), "median": statistics.median(p0), "max": max(p0)}}
        for st, lab in (("a", "v1"), ("c", "v2")):
            d = [r["botDelta"][st] for r in plan]
            sd = statistics.pstdev(d)
            w = sum((r["daily"] * 7 * WEEKS / 2) / (2 * r["afFtRate"] * (1 - r["afFtRate"])) for r in plan)
            cov[f"botDelta_{lab}"] = {"mean": round(statistics.mean(d), 4), "sd": round(sd, 4),
                                      "seSlope4w": round(1 / math.sqrt(sd ** 2 * w), 4) if sd else None}
        w08 = sum((r["daily"] * 7 * WEEKS / 2) / (2 * r["afFtRate"] * (1 - r["afFtRate"])) for r in plan)
        cov["seSlope4w_sd008"] = round(1 / math.sqrt(0.08 ** 2 * w08), 4)
        cov["nPerGroup4w"] = {s: round(sum(r["daily"] * 7 * WEEKS / 2 for r in plan if r["segment"] == s))
                              for s in ("32-100", "101-300", "301-500")}
        cov["dailyBySegment"] = {s: round(sum(r["daily"] for r in plan if r["segment"] == s), 1) for s in ("32-100", "101-300", "301-500")}
        return cov

    keep = ("level", "segment", "pick", "consensusTag", "disType", "expose", "exposeToken", "botDelta", "afFtRate", "afFtN",
            "daily", "gimmicks", "verifyPass", "verifyFail", "pilotTierPlan")
    for name, plan, notes in (("A", plan_a, notes_a), ("B", plan_b, notes_b)):
        cov = coverage(plan)
        P.save(os.path.join(CONS, f"pilot_{name}_v2.json"),
               {"_note": f"plan {name} v2 — one exposed variant per level (NOT APPROVED)", "coverage": cov, "notes": notes,
                "levels": [{k: r.get(k) for k in keep} for r in plan]})
        print(name, json.dumps(cov, ensure_ascii=False))
        print(" notes", notes)
        for r in plan:
            print(" ", r["level"], r["segment"], r["pick"][0], r.get("consensusTag") or r.get("disType"), r["expose"],
                  r["exposeToken"], f"p0={r['afFtRate']:.3f}", f"d/day={r['daily']}",
                  "Δv1/v2b/v2c=" + "/".join(f"{r['botDelta'][s]:+.2f}" for s in ("a", "b", "c")), ",".join(r["gimmicks"]),
                  "V" if r["verifyPass"] else "")


if __name__ == "__main__":
    main()
