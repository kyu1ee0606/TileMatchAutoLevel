"""Post-hoc simulation of 07 §5 robust-selection rules on v3 data (no new games).

Only the two selection θ points exist for every stage-2 candidate, so the "extra θ / extra bot profile"
part of robust selection cannot be simulated here -> counts are an UPPER BOUND for the full rule.
For the seeds actually selected in v2/v3, the verification session's extra-θ/profile data
(07, <sandbox>/verify/*.json) is used separately in the 08 report.

Usage: python scripts/pv_robust_sim.py
"""
from __future__ import annotations

import json
import os
import sys
from collections import Counter

BACKEND = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BACKEND)
sys.path.insert(0, os.path.join(BACKEND, "scripts"))

from app.core.pv.select import any_win, indep_diff  # noqa: E402

SB = os.path.join(BACKEND, "data", "pv_sandbox", "pv_20261002_live3")


def load(p):
    with open(p, encoding="utf-8") as f:
        return json.load(f)


RULES = {
    "R0 current (Δ≥0.04, gap 0.02)": dict(inner=0.04, sens=None, dir_all=False),
    "R1 inner≥0.08": dict(inner=0.08, sens=None, dir_all=False),
    "R2 skill-sensitive excl. (flip & spread≥0.15)": dict(inner=0.04, sens=0.15, dir_all=False),
    "R3 direction at every θ": dict(inner=0.04, sens=None, dir_all=True),
    "R1+R2": dict(inner=0.08, sens=0.15, dir_all=False),
    "R1+R3": dict(inner=0.08, sens=None, dir_all=True),
}


def side(base, cands, ev, ver, sign, utc_base, inner, sens, dir_all, dmin=0.04, gap=0.02):
    wb = ev[base]["W"]
    valid = []
    for k in cands:
        if k == base or sign * (ev[k]["W"] - wb) <= 0 or not ver.get(k):
            continue
        d = indep_diff(ev[k], ev[base]) if sign > 0 else indep_diff(ev[base], ev[k])
        if d["diff"] < dmin or d["lo"] <= 0:
            continue
        per = [sign * v for v in d["perTheta"].values()] if sign > 0 else list(d["perTheta"].values())
        # per-θ signed deltas in the intended direction (positive = correct direction)
        if dir_all and any(p <= 0 for p in per):
            continue
        if sens is not None and any(p < 0 for p in per) and (max(per) - min(per)) >= sens:
            continue
        valid.append((d["diff"], k))
    best = None
    for i in range(len(valid)):
        for j in range(i + 1, len(valid)):
            (dn, kn), (df, kf) = sorted([valid[i], valid[j]])
            if dn < inner or df - dn < gap:
                continue
            nflex = sum(1 for x in (kn, kf) if x.split(":")[0] != utc_base)
            sc = (-nflex, df - dn)
            if best is None or sc > best[0]:
                best = (sc, kn, kf)
    return best


def level_data(n):
    d2 = os.path.join(SB, "eval2", f"{n:04d}")
    d3 = os.path.join(SB, "eval3", f"{n:04d}")
    prep = load(os.path.join(d2, "prep.json"))
    u0 = prep["meta"]["utc0"]
    ev, s1, sol = {}, {}, {}
    for p in (32, 64, 128):
        for name, tgt in (("s2", ev), ("s1", s1)):
            f = os.path.join(d2, f"{name}_p{p}.json")
            if os.path.exists(f):
                tgt.update({f"{u0}:{s}": e for s, e in load(f)["results"].items()})
        f = os.path.join(d2, f"solve_p{p}.json")
        if os.path.exists(f):
            sol.update({f"{u0}:{s}": v for s, v in load(f)["solved"].items()})
    for f, tgt, key in ((os.path.join(d3, "s2_flex.json"), ev, "results"),
                        (os.path.join(d3, "solve_flex.json"), sol, "solved")):
        if os.path.exists(f):
            tgt.update(load(f)[key])
    if os.path.isdir(d3):
        for fn in os.listdir(d3):
            if fn.startswith("s1_u"):
                u = fn.split("_")[1][1:]
                s1.update({f"{u}:{s}": e for s, e in load(os.path.join(d3, fn))["results"].items()})
    ver = {k: any_win(s1.get(k), ev.get(k)) or sol.get(k, {}).get("verdict") == "PROVEN_SOLVABLE" for k in ev}
    return u0, ev, ver


def main():
    v3 = load(os.path.join(SB, "selection_v3.json"))
    out = {}
    for name, r in RULES.items():
        cnt = Counter()
        for row in v3["levels"]:
            if row["status"] == "unevaluable":
                continue
            n = row["level"]
            u0, ev, ver = level_data(n)
            e_al = {str(u0), str(u0 - 1)}
            h_al = {str(u0), str(u0 + 1)}
            scen = {"strict": f"{u0}:{row['strict']['tiers']['b']['seed']}" if row["strict"].get("ok") else None}
            if row["strict"].get("ok") is False:
                f2 = load(os.path.join(SB, "eval2", f"{n:04d}", "final.json"))
                scen["strict"] = f"{u0}:{f2['basePick']['base']}"
            rl = row.get("relaxed")
            pct = row.get("origPercentile", 0.5)
            extreme = pct > 0.9 or pct < 0.1
            if rl and rl.get("ok"):
                t = rl["tiers"]["b"]
                scen["relaxed"] = f"{t['utc']}:{t['seed']}"
            for sc, base in scen.items():
                if base is None:
                    continue
                ub = base.split(":")[0]
                e = side(base, [k for k in ev if k.split(":")[0] in e_al], ev, ver, +1, ub, **r)
                h = side(base, [k for k in ev if k.split(":")[0] in h_al], ev, ver, -1, ub, **r)
                ok = e is not None and h is not None
                cnt[f"{sc}_ok"] += ok
                if sc == "strict" and not extreme:
                    cnt["policy_ok"] += ok  # non-extreme levels use strict
                if sc == "relaxed" and extreme:
                    cnt["policy_ok"] += ok  # extreme levels use relaxed
        out[name] = dict(cnt)
    print(json.dumps(out, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
