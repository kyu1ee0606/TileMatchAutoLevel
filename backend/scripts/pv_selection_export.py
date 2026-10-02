"""Export P1 re-measure selections to a machine-readable file for independent verification.

Writes <sandbox>/selection_v2.json. Deployment string = A-plan (2026-10-02 user decision):
the existing `randSeed` field carries "base|e2|e1|h1|h2" ('|' separator, first value = base).
Levels without bidirectional 5 seeds keep the original explicit map (no string).

Usage: python scripts/pv_selection_export.py
"""
from __future__ import annotations

import json
import os
import sys

BACKEND = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BACKEND)

from app.core.pv.select import Z_V2, indep_diff  # noqa: E402

SB = os.path.join(BACKEND, "data", "pv_sandbox", "pv_20261002_live3")
A_ORDER = ("b", "e2", "e1", "h1", "h2")


def load(p):
    with open(p, encoding="utf-8") as f:
        return json.load(f)


def a_string(seeds: dict) -> str:
    vals = [int(seeds[t]) for t in A_ORDER]
    validate_a_values(vals, base=int(seeds["b"]))
    return "|".join(str(v) for v in vals)


def validate_a_values(vals, base):
    """Editor-side export check: 5 distinct positive int32 values, first = base."""
    if len(vals) != 5:
        raise ValueError("A-plan string needs exactly 5 values")
    if any((not isinstance(v, int)) or v <= 0 or v > 2**31 - 1 for v in vals):
        raise ValueError(f"non-positive / out-of-range seed in {vals}")
    if len(set(vals)) != 5:
        raise ValueError(f"duplicate seeds in {vals}")
    if vals[0] != base:
        raise ValueError("first value must be base")


def merged(d, prefix):
    out = {}
    for p in (32, 64, 128):
        f = os.path.join(d, f"{prefix}_p{p}.json")
        if os.path.exists(f):
            out.update(load(f)["results"] if prefix != "solve" else load(f)["solved"])
    return out


def main() -> int:
    levels = load(os.path.join(SB, "sample2.json"))["levels"]
    rows = []
    for n in levels:
        d = os.path.join(SB, "eval2", f"{n:04d}")
        fin_p = os.path.join(d, "final.json")
        if not os.path.exists(fin_p):
            rows.append({"level": n, "status": "not_finished"})
            continue
        fin = load(fin_p)
        prep = load(os.path.join(d, "prep.json"))
        row = {"level": n, "structHash": prep["meta"]["structHash"], "utc": prep["meta"]["utc0"],
               "t0izeVersion": prep["meta"]["t0izeVersion"], "status": fin["status"]}
        if fin["status"] == "unevaluable":
            row.update(reason=fin["reason"], deploy="keep_explicit_map",
                       scanRates=load(os.path.join(d, "scan.json"))["rates"])
            rows.append(row)
            continue
        s2 = merged(d, "s2")
        orig = load(os.path.join(d, "orig2.json"))["results"]["orig"]
        base = fin["basePick"]["base"]
        bo = indep_diff(s2[base], orig)
        row.update(
            thetas=fin["thetas"], gamesPerTheta=s2[base]["theta"][next(iter(s2[base]["theta"]))]["n"],
            poolUsed=fin["poolUsed"], wOrig=orig["W"],
            origPercentile=fin["basePick"]["origPercentile"], origExtreme=fin["basePick"]["origExtreme"],
            base={"seed": int(base), "W": s2[base]["W"], "deltaVsOrig": bo["diff"], "ci": [bo["lo"], bo["hi"]]},
            ciZ=Z_V2, ciMethod="independent two-sample normal approx, mean over θ",
        )
        if fin["status"] == "ok":
            seeds = dict(fin["sel"]["seeds"])
            tiers = {}
            for t in ("e2", "e1", "h1", "h2"):
                s = seeds[t]
                dd = indep_diff(s2[s], s2[base])
                tiers[t] = {"seed": int(s), "W": s2[s]["W"], "deltaVsBase": dd["diff"], "ci": [dd["lo"], dd["hi"]],
                            "perTheta": {th: v["rate"] for th, v in s2[s]["theta"].items()}}
            row.update(tiers=tiers, randSeedA=a_string(seeds), deploy="randSeed_A_string")
        else:
            row.update(deploy="keep_explicit_map",
                       unmet={side: {"reason": v["reason"], "nValid": v["nValid"]}
                              for side, v in fin["sel"]["sides"].items() if v["pick"] is None})
        rows.append(row)
    out = {
        "format": "pv_selection_v2", "copyId": "pv_20261002_live3",
        "selectionRule": "06 §8: adaptive θ (2 pts, orig≈0.5, trough [0.34,0.50) excluded), stage-1 64 games/θ, "
                         "stage-2 950 games/θ, independent CI z=2.4977, Δmin 0.04, e2/e1 gap ≥0.02, "
                         "solvability evidence (bot win or solver PROVEN_SOLVABLE), pool 32→64→128",
        "seedBases": {"scan": 5_000_000, "stage1": 6_000_000, "stage2": 7_000_000,
                      "note": "verification must use different bot seeds, θ and profiles"},
        "aPlanOrder": list(A_ORDER),
        "levels": rows,
    }
    dst = os.path.join(SB, "selection_v2.json")
    with open(dst + ".tmp", "w", encoding="utf-8") as f:  # atomic: readers never see a partial file
        json.dump(out, f, ensure_ascii=False, indent=1)
    os.replace(dst + ".tmp", dst)
    from collections import Counter
    print(Counter(r["status"] for r in rows))
    return 0


if __name__ == "__main__":
    sys.exit(main())
