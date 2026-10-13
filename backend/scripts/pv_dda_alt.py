"""Alternative-rule re-selection for the DDA preparation — stored measurements only (no new bot runs, no predictor).
PREPARATION ONLY — NOT APPROVED. Current R1 outputs in dda_sets/ are left untouched.

R2: outer tiers need selection |Δ| >= OUTER (0.13 / 0.15) instead of 0.10. Inner failure -> 3 tiers (no swap). h2 floor rel50.
A candidate that would need a measurement we do not have (robust points or predictor) is NOT selected; counted as "needsMeasure".

Writes dda_sets/alt_R2_<tag>/: seedvar_rows.json, coverage.json, levels.json (per-level tiers), sample_estimate.json
(expected pass on the independent-verification sample: verify_dda_seedvar/, 96 levels).

Usage: python scripts/pv_dda_alt.py --outer 0.13 --tag 013
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from collections import Counter

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import pv_dda as P  # noqa: E402

SEGMENTS = [(32, 500), (501, 1000), (1001, 1500)]
VERIFY = os.path.join(P.SB, "verify_dda_seedvar")
NOTE = ("ALTERNATIVE RULE (comparison only) — PREPARATION ONLY, NOT APPROVED, NOT UPLOADED. "
        "Re-selected from stored measurements; current R1 outputs are in dda_sets/seedvar_rows.json.")


def reselect(n, outer_min):
    w = P.W(n)
    fin = w.get("final.json")
    if fin is None or fin["status"] not in ("5tier", "3tier", "no_variant"):
        return {"status": fin["status"] if fin else "missing"}
    if fin["status"] == "no_variant":
        return {"status": "no_variant", "reason": "R1 no_variant (stricter rule cannot add a tier)"}
    prep, scan = w.get("prep.json"), w.get("scan.json")
    th = scan["choice"]["thetas"]
    xt = P.extra_theta(scan["rates"], th)
    points = [f"θ:{xt:g}", "profile:average", "profile:expert", f"θ:{P.low_theta(th, xt):g}"]
    judged = [f"θ:{float(t):g}" for t in th] + points[:3]
    ts = {float(t) for t in th}
    s1 = {k: v for k, v in w.get("s1.json", {}).items() if {float(t) for t in v["theta"]} == ts}
    s2 = {k: v for k, v in w.get("s2.json", {}).items() if {float(t) for t in v["theta"]} == ts}
    sol, rob, pred = w.get("solve.json", {}), w.get("robust.json", {}), w.get("pred.json", {})
    rv4 = w.get("robust_v4.json", {"results": {}})
    if rv4.get("points") == points[:3]:
        for k, v in rv4["results"].items():
            rob.setdefault(k, v)
    sides = P.decide(prep, s1, s2, sol, rob, judged, pred, judged + [points[3]], outer_min=outer_min, swap=False)
    needs = {}
    for sd in ("easy", "hard"):
        if sides[sd]["outer"] is None:
            sign = 1 if sd == "easy" else -1
            unmeasured = [k for k, e in s2.items() if k != "orig" and P.side_of(prep, sd, k)
                          and sign * (e["W"] - s2["orig"]["W"]) >= outer_min and k not in rob]
            needs[sd] = {"robustUnmeasured": len(unmeasured), "predictorPending": len(sides[sd]["predQueue"])}
    if not (sides["easy"]["outer"] and sides["hard"]["outer"]):
        miss = [sd for sd in ("easy", "hard") if sides[sd]["outer"] is None]
        return {"status": "no_variant", "reason": "outer tier |Δ| >= %.2f not found: %s" % (outer_min, ",".join(miss)),
                "needsMeasure": needs, "r1Status": fin["status"]}
    tiers = {"e2": sides["easy"]["outer"], "h2": sides["hard"]["outer"]}
    order = ("e2", "h2")
    if sides["easy"]["inner"] and sides["hard"]["inner"]:
        tiers.update(e1=sides["easy"]["inner"], h1=sides["hard"]["inner"])
        order = ("e2", "e1", "h1", "h2")
    gold = w.get("golden.json", {})
    issues = [f"{t}: golden missing" for t in order if gold.get(tiers[t]["key"]) is not True]
    grade = "strict" if all(tiers[t]["evidence"] == "strict" for t in order) else "extended"
    token = "|".join(P.tok(prep, tiers[t]["key"]) for t in order)
    return {"status": ("invariant_fail" if issues else ("5tier" if len(order) == 4 else "3tier")), "token": token,
            "grade": grade, "issues": issues, "r1Status": fin["status"], "r1Token": fin.get("token"),
            "tiers": {t: {"key": tiers[t]["key"], "delta": round(tiers[t]["delta"], 4), "absd": round(tiers[t]["absd"], 4)}
                      for t in order},
            "sameOuterAsR1": all(tiers[t]["key"] == fin["tiers"][t]["key"] for t in ("e2", "h2"))}


def sample_estimate(levels):
    """Expected pass on the independent-verification sample (only levels whose R2 tiers equal the verified R1 tiers)."""
    roll = P.load(os.path.join(VERIFY, "_rollup_32_1500.json"))
    fails = {int(k): v for k, v in roll["perLevelFail"].items()}
    verified = sorted(int(f[:4]) for f in os.listdir(VERIFY) if f[:4].isdigit())
    kept, dropped, changed = [], [], []
    outer_ok = all_ok = 0
    for n in verified:
        r = levels.get(n, {})
        if r.get("status") not in ("5tier", "3tier"):
            dropped.append(n)
            continue
        if not r.get("sameOuterAsR1"):
            changed.append(n)
            continue
        kept.append(n)
        f = fails.get(n, [])
        o = not any(x.startswith("outer") for x in f)
        inner_ok = not any(x.startswith("innerDir") for x in f) or r["status"] == "3tier"
        outer_ok += o
        all_ok += o and inner_ok
    k = len(kept)
    return {"verified": len(verified), "keptSameTiers": k, "dropped": len(dropped), "outerChanged": len(changed),
            "droppedLevels": dropped, "changedLevels": changed,
            "outerPass": [outer_ok, k], "allTierPassAsSelected": [all_ok, k],
            "note": "pass flags from verify_dda_seedvar (R1 tiers). Inner tiers of R1 5-tier levels that R2 keeps as "
                    "5-tier keep their verifier result; levels R2 makes 3-tier drop inner tiers. Inner-failure "
                    "demotion on verifier results would make all-tier pass = outer pass."}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--outer", type=float, required=True)
    ap.add_argument("--tag", required=True)
    a = ap.parse_args()
    out_dir = os.path.join(P.DDA, f"alt_R2_{a.tag}")
    levels, rows = {}, {}
    work = os.path.join(P.DDA, "work")
    for name in sorted(os.listdir(work)):
        if not name.isdigit():
            continue
        n = int(name)
        r = reselect(n, a.outer)
        levels[n] = r
        if r["status"] in ("5tier", "3tier"):
            row = P.load(os.path.join(work, name, "seedvar_row.json"))
            rows[f"seedvar_{n}"] = {**row, "randSeed": r["token"]}
    cov = {"note": NOTE, "rule": {"outerAbsDeltaMin": a.outer, "innerFailure": "3-tier (no swap)",
                                  "h2Floor": "rel50", "innerDeltaMin": P.INNER_MIN, "gap": P.GAP_MIN},
           "status": dict(Counter(r["status"] for r in levels.values())),
           "grade": dict(Counter(r.get("grade") for r in levels.values() if r.get("grade"))),
           "fromR1": dict(Counter(f"{r.get('r1Status')}->{r['status']}" for r in levels.values() if r.get("r1Status"))),
           "needsMeasureLevels": sum(1 for r in levels.values() if any(
               v["robustUnmeasured"] or v["predictorPending"] for v in (r.get("needsMeasure") or {}).values())),
           "bySegment": {}}
    for lo, hi in SEGMENTS:
        seg = [r for n, r in levels.items() if lo <= n <= hi]
        cov["bySegment"][f"{lo}-{hi}"] = {"status": dict(Counter(r["status"] for r in seg)),
                                          "withVariant": sum(1 for r in seg if r["status"] in ("5tier", "3tier"))}
    est = sample_estimate(levels)
    P.save(os.path.join(out_dir, "seedvar_rows.json"), {"_note": NOTE, "rows": rows})
    P.save(os.path.join(out_dir, "coverage.json"), cov)
    P.save(os.path.join(out_dir, "levels.json"), {str(k): v for k, v in levels.items()})
    P.save(os.path.join(out_dir, "sample_estimate.json"), est)
    print(json.dumps({"rows": len(rows), **{k: cov[k] for k in ("status", "grade", "fromR1", "needsMeasureLevels", "bySegment")},
                      "sample": {k: est[k] for k in ("keptSameTiers", "dropped", "outerChanged", "outerPass", "allTierPassAsSelected")}},
                     ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
