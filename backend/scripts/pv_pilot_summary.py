"""Summarize P1 pilot eval files into JSON (+ markdown tables on stdout).

Usage: python scripts/pv_pilot_summary.py [--copy-id pv_20261002_live3]
Writes <sandbox>/pilot_summary.json.
"""
from __future__ import annotations

import argparse
import json
import math
import os
import statistics as st
import sys

BACKEND = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def load(p):
    with open(p, encoding="utf-8") as f:
        return json.load(f)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--copy-id", default="pv_20261002_live3")
    args = ap.parse_args()
    sb = os.path.join(BACKEND, "data", "pv_sandbox", args.copy_id)
    sample = load(os.path.join(sb, "sample.json"))["sample"]
    rows, wall_total, cpu_total = [], 0.0, 0.0
    for s in sample:
        n = s["level"]
        d = os.path.join(sb, "eval", f"{n:04d}")
        if not os.path.exists(os.path.join(d, "sel.json")):
            rows.append({"level": n, "missing": True})
            continue
        t0 = load(os.path.join(sb, "t0", f"{n:04d}.json"))
        sel = load(os.path.join(d, "sel.json"))
        rep = load(os.path.join(d, "rep.json"))
        solve = load(os.path.join(d, "solve.json"))
        wall = sum(load(os.path.join(d, f"{x}.json")).get("wallSec", 0) for x in ("s1", "orig", "s2", "rep", "solve", "sel"))
        cpu = sum(load(os.path.join(d, f"{x}.json")).get("cpuSec", 0) for x in ("s1", "orig", "s2", "rep"))
        wall_total += wall
        cpu_total += cpu
        reps = [r["W"] for r in rep["replicates"]]
        p = sel["picked"]
        rows.append({
            "level": n, "stratum": s["stratum"], "gimmicks": s["gimmicks"],
            "tiles": t0["meta"]["tileCount"], "utc": t0["meta"]["utc0"], "origSetSpread": t0["meta"]["origSetSpread"],
            "wOrig": sel["wOrig"], "s1": sel["s1Spread"], "s1Unverified": sel["s1Unverified"],
            "s1DeltaVsOrig": sel["s1DeltaVsOrig"],
            "status": sel["status"], "collapsed": sel["collapsed"], "baseShift": sel["baseShift"],
            "W2": {t: p[t]["W2"] for t in ("e2", "e1", "b", "h1", "h2")},
            "seeds": {t: p[t]["seed"] for t in ("e2", "e1", "b", "h1", "h2")},
            "regression": {t: p[t]["regression"] for t in ("e2", "e1", "h1", "h2")},
            "repW": reps, "repSD": st.stdev(reps) if len(reps) > 1 else None,
            "crnRho": sel["crnRhoMean"],
            "dockMax_b": p["b"]["dockMaxMean"], "crisis_b": p["b"]["crisisGameRate"],
            "crisis_h2": p["h2"]["crisisGameRate"], "crisis_e2": p["e2"]["crisisGameRate"],
            "solver": solve["solved"], "wallSec": wall, "cpuSec": cpu,
        })
    ok = [r for r in rows if not r.get("missing")]
    summ = {
        "levels": len(ok),
        "status": {k: sum(1 for r in ok if r["status"] == k) for k in ("ok", "collapsed", "flat")},
        "wallSecTotal": wall_total, "cpuSecTotal": cpu_total,
        "wallSecPerLevelMean": wall_total / max(1, len(ok)),
        "repSDMedian": st.median([r["repSD"] for r in ok if r["repSD"] is not None]) if ok else None,
        "rows": rows,
    }
    with open(os.path.join(sb, "pilot_summary.json"), "w", encoding="utf-8") as f:
        json.dump(summ, f, ensure_ascii=False, indent=1)

    f3 = lambda x: "-" if x is None or (isinstance(x, float) and math.isnan(x)) else f"{x:.3f}"  # noqa: E731
    print("| Lv | 구간 | 기믹 | 타일 | utc | W_orig | 1단계 W min / q25 / q75 / max | 미확인 | 상태 | e2 | e1 | b | h1 | h2 | baseShift | 반복SD | CRN ρ | wall s |")
    print("|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|")
    for r in ok:
        s1 = r["s1"]
        w = r["W2"]
        print(f"| {r['level']} | {r['stratum']} | {r['gimmicks']} | {r['tiles']} | {r['utc']} | {f3(r['wOrig'])} | "
              f"{f3(s1['min'])} / {f3(s1['q25'])} / {f3(s1['q75'])} / {f3(s1['max'])} | {r['s1Unverified']} | "
              f"{r['status']}{'(' + ','.join(r['collapsed']) + ')' if r['collapsed'] else ''} | "
              f"{f3(w['e2'])} | {f3(w['e1'])} | {f3(w['b'])} | {f3(w['h1'])} | {f3(w['h2'])} | "
              f"{f3(r['baseShift'])} | {f3(r['repSD'])} | {f3(r['crnRho'])} | {r['wallSec']:.0f} |")
    print(json.dumps({k: v for k, v in summ.items() if k != "rows"}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
