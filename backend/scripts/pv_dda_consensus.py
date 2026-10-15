"""Consensus / disagreement sets and live-pilot candidates from stored values only (10 §9-9). No measurement.

Inputs (read only): dda_sets/work/NNNN/final.json (R2), dda_sets_v2/sep/sep_levels.json (R2 / a v1 fresh / b v2 same θ
pair / c ③ v2 own θ pair Δ per tier), dda_sets_v2/work/NNNN/p3.json (③ CI), verify_dda_seedvar (07),
af_calibration/bot_compare_L32_500/prep.json (cat_help / booster_tutorial / time_limit exclusions, L32~500).
Output: dda_sets_v2/consensus/*.json. Usage: python scripts/pv_dda_consensus.py
"""
from __future__ import annotations

import json
import os
import sys
from collections import Counter

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import pv_dda as P  # noqa: E402

V2 = os.path.join(P.SB, "dda_sets_v2")
OUT = os.path.join(V2, "consensus")
AF_PREP = os.path.join(P.BACKEND, "data", "pv_sandbox", "af_calibration", "bot_compare_L32_500", "prep.json")
AF = os.path.join(os.path.dirname(AF_PREP), "af.json")
STAGES = ("R2", "a", "b", "c")
SEGS = ((32, 100), (101, 300), (301, 500), (501, 1000))
PILOT_QUOTA = {"32-100": 8, "101-300": 10, "301-500": 3}          # doc 24 4-week plan
PILOT_B_DIS = {"32-100": 2, "101-300": 3, "301-500": 1}           # (B): 6 disagreement levels, rest consensus
OUTER_V1, OUTER_V2_ALT, INNER = 0.13, 0.10, 0.04


def seg(n):
    return next(f"{a}-{b}" for a, b in SEGS if a <= n <= b)


def ok(t, d, thr):
    return (d > 0 if t.startswith("e") else d < 0) and abs(d) >= thr


def main():
    lv = {int(k): v for k, v in P.load(os.path.join(V2, "sep", "sep_levels.json")).items()}
    roll = P.load(os.path.join(P.SB, "verify_dda_seedvar", "_rollup_32_1500.json"))
    vfail = {int(k): v for k, v in roll["perLevelFail"].items()}
    verified = {int(f[:4]) for f in os.listdir(os.path.join(P.SB, "verify_dda_seedvar")) if f[:4].isdigit()}
    excl = {int(k): v["exclude"] for k, v in P.load(AF_PREP).items() if v["exclude"]}
    af = {int(k): v for k, v in P.load(AF).items()}
    rows = {}
    for n, st in sorted(lv.items()):
        fin = P.W(n).get("final.json")
        p3 = P.load(os.path.join(V2, "work", f"{n:04d}", "p3.json"))
        outer = {t: {s: round(st[t][s], 4) for s in STAGES} for t in ("e2", "h2")}
        inner = {t: {s: round(st[t][s], 4) for s in STAGES} for t in ("e1", "h1") if t in st}
        strict = all(ok(t, outer[t][s], OUTER_V1) for t in outer for s in STAGES)
        alt = all(ok(t, outer[t][s], OUTER_V1) for t in outer for s in ("R2", "a")) and \
            all(ok(t, outer[t][s], OUTER_V2_ALT) for t in outer for s in ("b", "c"))
        v1pass = all(ok(t, outer[t][s], OUTER_V1) for t in outer for s in ("R2", "a"))
        flip = {t: [s for s in ("b", "c") if not ok(t, outer[t][s], 0.0)] for t in outer}
        shrink = {t: round(min(abs(outer[t]["b"]), abs(outer[t]["c"])) / abs(outer[t]["a"]), 3) if outer[t]["a"] else None
                  for t in outer}
        inner_ok = bool(inner) and all(ok(t, inner[t][s], INNER) for t in inner for s in STAGES)
        tok = {t: v["token"] for t, v in fin["tiers"].items()}
        a = af.get(n, {})
        rows[n] = {"level": n, "segment": seg(n), "r2Status": fin["status"], "outer": outer, "inner": inner,
                   "consensus013": strict, "consensus010v2": alt, "v1Pass": v1pass, "flip": flip,
                   "firstFlip": next((s for s in ("b", "c") if any(s in f for f in flip.values())), None),
                   "v2Shrink": shrink, "innerConsensus": inner_ok,
                   "pilotTierPlan": "5tier" if inner_ok else "3tier",
                   "token5": fin["token"] if fin["status"] == "5tier" else None,
                   "token3": f"{tok['e2']}|{tok['h2']}", "tokens": tok,
                   "pilotToken": fin["token"] if (inner_ok and fin["status"] == "5tier") else f"{tok['e2']}|{tok['h2']}",
                   "ciLoV2": {t: p3["tiers"][t]["ciLo"] for t in ("e2", "h2")},
                   "verified": n in verified, "verifyPass": n in verified and n not in vfail,
                   "verifyFail": vfail.get(n) if n in verified else None,
                   "exclude": excl.get(n), "afFtN": a.get("clean_ft_n"), "afFtRate": a.get("clean_ft_rate")}
    # disagreement: v1 pass, v2 sign flip or outer |Δ| (min of b,c) < half of v1 fresh |Δ|
    for r in rows.values():
        side = [t for t in ("e2", "h2") if r["flip"][t] or (r["v2Shrink"][t] is not None and r["v2Shrink"][t] < 0.5)]
        r["disagree"] = r["v1Pass"] and bool(side) and not r["consensus010v2"]
        r["disagreeSide"] = side if r["disagree"] else []
        cflip = any("c" in f for f in r["flip"].values())
        r["flip44"] = cflip  # one of the 44 ③ sign-flip levels
        r["disagreeKind"] = ((("botFlip" if cflip else "botFlipBOnly") if r["firstFlip"] == "b" else
                              "pairFlip" if r["firstFlip"] == "c" else "shrink") if r["disagree"] else None)
        r["consensusTag"] = "0.13" if r["consensus013"] else "0.10v2" if r["consensus010v2"] else None

    def strength(r):  # weakest sign-correct outer |Δ| over all stages (robustness score)
        return min(abs(r["outer"][t][s]) for t in ("e2", "h2") for s in STAGES)

    def pilot_ok(r):
        return r["segment"] in PILOT_QUOTA and not r["exclude"] and (r["afFtN"] or 0) >= 100

    def pick(pool, k, key):
        return sorted(pool, key=key)[:k]

    cons = [r for r in rows.values() if r["consensus013"]]
    cons10 = [r for r in rows.values() if r["consensus010v2"]]
    dis = [r for r in rows.values() if r["disagree"]]
    plan_a, plan_b, notes = [], [], []
    for sname, q in PILOT_QUOTA.items():
        c13 = [r for r in cons if r["segment"] == sname and pilot_ok(r)]
        c10 = [r for r in cons10 if r["segment"] == sname and pilot_ok(r) and not r["consensus013"]]
        rank = (lambda r: (-r["verifyPass"], -strength(r), r["level"]))
        pa = pick(c13, q, rank)
        if len(pa) < q:
            notes.append(f"A {sname}: strict 0.13 consensus {len(pa)} < {q}, filled from 0.10(v2) consensus")
            pa += pick(c10, q - len(pa), rank)
        plan_a += [{**r, "pilotPlan": "A", "pick": "consensus"} for r in pa]
        nd = PILOT_B_DIS[sname]
        d = [r for r in dis if r["segment"] == sname and pilot_ok(r)]
        drank = (lambda r: (r["disagreeKind"] != "botFlip", -min(abs(r["outer"][t]["a"]) for t in ("e2", "h2")), r["level"]))
        pd = pick(d, nd, drank)
        pc = pa[: q - len(pd)]
        plan_b += [{**r, "pilotPlan": "B", "pick": "consensus"} for r in pc] + [{**r, "pilotPlan": "B", "pick": "disagree"} for r in pd]
        if len(pd) < nd:
            notes.append(f"B {sname}: disagreement pool {len(pd)} < {nd}")
    summ = {"levels": len(rows), "rule": {"consensusOuter": "e2 & h2 sign kept and |Δ|>=0.13 in R2, a(v1 fresh), b(v2 R2 pair), c(③ v2 pair)",
                                          "consensus010v2": "same but b,c use |Δ|>=0.10 (v2 e2 scale 0.126/0.170 ≈ 0.74 × 0.13 ≈ 0.10)",
                                          "inner": "e1/h1 sign kept and |Δ|>=0.04 in all four stages -> 5 tiers, else 3 tiers",
                                          "disagree": "v1 pass (R2 & a) but v2 sign flip (b or c) or min(|b|,|c|) < 0.5×|a| on e2/h2, not in consensus010v2",
                                          "pilotFilter": "L32~500, exclude cat_help/booster_tutorial/time_limit, AF clean first-try n>=100",
                                          "rankA": "07 verify pass first, then weakest |Δ| over stages (desc)",
                                          "rankBdis": "bot-version flips (first flip at b) first, then v1 |Δ| (desc)"}}
    for name, pool in (("consensus013", cons), ("consensus010v2", cons10), ("disagree", dis)):
        summ[name] = {"n": len(pool), "bySegment": {f"{a}-{b}": sum(1 for r in pool if r["segment"] == f"{a}-{b}") for a, b in SEGS},
                      "innerConsensus": sum(1 for r in pool if r["innerConsensus"]),
                      "verified": sum(1 for r in pool if r["verified"]), "verifyPass": sum(1 for r in pool if r["verifyPass"]),
                      "pilotEligible": sum(1 for r in pool if pilot_ok(r))}
    summ["disagree"]["kind"] = dict(Counter(r["disagreeKind"] for r in dis))
    summ["disagree"]["flip44Covered"] = sum(1 for r in dis if r["flip44"])
    summ["disagree"]["botFlip27InV1Pass"] = sum(1 for r in rows.values() if r["flip44"] and r["firstFlip"] == "b" and r["v1Pass"])
    summ["disagree"]["side"] = dict(Counter("+".join(r["disagreeSide"]) for r in dis))
    summ["notes"] = notes
    slim = lambda r: {k: r[k] for k in ("level", "segment", "pick", "consensusTag", "pilotTierPlan", "pilotToken", "token5", "token3", "tokens", "outer",
                                         "inner", "verifyPass", "verifyFail", "disagreeKind", "disagreeSide", "afFtN", "afFtRate") if k in r}
    os.makedirs(OUT, exist_ok=True)
    P.save(os.path.join(OUT, "levels.json"), {str(k): v for k, v in rows.items()})
    P.save(os.path.join(OUT, "consensus_013.json"), [r["level"] for r in cons])
    P.save(os.path.join(OUT, "consensus_010v2.json"), [r["level"] for r in cons10])
    P.save(os.path.join(OUT, "disagree.json"), [{k: r[k] for k in ("level", "segment", "disagreeKind", "disagreeSide", "outer",
                                                                   "verifyPass", "verifyFail")} for r in dis])
    P.save(os.path.join(OUT, "pilot_A.json"), {"_note": "plan A — 21 consensus levels (NOT APPROVED)", "levels": [slim(r) for r in plan_a]})
    P.save(os.path.join(OUT, "pilot_B.json"), {"_note": "plan B — 15 consensus + 6 disagreement (NOT APPROVED)", "levels": [slim(r) for r in plan_b]})
    P.save(os.path.join(OUT, "summary.json"), summ)
    print(json.dumps(summ, ensure_ascii=False))
    for nm, pl in (("A", plan_a), ("B", plan_b)):
        print(nm, [(r["level"], r["pick"][0], r["consensusTag"], r["disagreeKind"], r["pilotTierPlan"][0]) for r in pl])


if __name__ == "__main__":
    main()
