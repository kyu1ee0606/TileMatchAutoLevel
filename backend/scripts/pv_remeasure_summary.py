"""Summarize the P1 re-measure (eval2) for 06 §8. Prints markdown + JSON stats.

Usage: python scripts/pv_remeasure_summary.py
"""
from __future__ import annotations

import json
import os
import statistics as st
import sys
from collections import Counter

BACKEND = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BACKEND)

from app.core.pv.select import any_win, bidirectional_select, indep_diff  # noqa: E402

SB = os.path.join(BACKEND, "data", "pv_sandbox", "pv_20261002_live3")
STEPS = ["golden", "scan", "orig2", "s1_p32", "s2_p32", "solve_p32", "sel_p32", "s1_p64", "s2_p64", "solve_p64",
         "sel_p64", "s1_p128", "s2_p128", "solve_p128", "sel_p128"]


def load(p):
    with open(p, encoding="utf-8") as f:
        return json.load(f)


def merged(d, prefix, upto=128):
    out = {}
    for p in (32, 64, 128):
        if p > upto:
            break
        f = os.path.join(d, f"{prefix}_p{p}.json")
        if os.path.exists(f):
            out.update(load(f)["results"] if prefix != "solve" else load(f)["solved"])
    return out


def main():
    s2meta = load(os.path.join(SB, "sample2.json"))
    levels = s2meta["levels"]
    rows, pool_ok, reasons, sens = [], Counter(), Counter(), Counter()
    for n in levels:
        d = os.path.join(SB, "eval2", f"{n:04d}")
        if not os.path.exists(os.path.join(d, "final.json")):
            rows.append({"level": n, "status": "not_finished"})
            continue
        fin = load(os.path.join(d, "final.json"))
        wall = sum(load(os.path.join(d, f"{s}.json")).get("wallSec", 0) for s in STEPS
                   if os.path.exists(os.path.join(d, f"{s}.json")))
        r = {"level": n, "new": n in s2meta["new"], "status": fin["status"], "wall": wall}
        if fin["status"] == "unevaluable":
            r["scan"] = load(os.path.join(d, "scan.json"))["rates"]
            rows.append(r)
            reasons["unevaluable"] += 1
            continue
        s2 = merged(d, "s2")
        s1 = merged(d, "s1")
        solved = merged(d, "solve")
        orig = load(os.path.join(d, "orig2.json"))["results"]["orig"]
        base = fin["basePick"]["base"]
        bo = indep_diff(s2[base], orig)
        r.update(thetas=fin["thetas"], pool=fin["poolUsed"], wOrig=orig["W"], pct=fin["basePick"]["origPercentile"],
                 baseW=s2[base]["W"], baseVsOrig=(bo["diff"], bo["lo"], bo["hi"]))
        # pool at which bidirectional was first satisfied
        for p in (32, 64, 128):
            f = os.path.join(d, f"sel_p{p}.json")
            if os.path.exists(f) and load(f)["ok"]:
                pool_ok[p] += 1
                break
        if fin["status"] == "ok":
            seeds = dict(fin["sel"]["seeds"])
            r["tiers"] = {}
            for t in ("e2", "e1", "h1", "h2"):
                dd = indep_diff(s2[seeds[t]], s2[base])
                r["tiers"][t] = (dd["diff"], dd["lo"], dd["hi"])
        else:
            for side, v in fin["sel"]["sides"].items():
                if v["pick"] is None:
                    reasons[f"{side}:{v['reason']}"] += 1
            r["unmet"] = {s: v["reason"] for s, v in fin["sel"]["sides"].items() if v["pick"] is None}
        # sensitivity on all evaluated stage-2 candidates (final pool)
        ver = {s: any_win(s1.get(s), s2.get(s)) or solved.get(s, {}).get("verdict") == "PROVEN_SOLVABLE" for s in s2}
        for dm in (0.03, 0.04, 0.05):
            for gm in (0.0, 0.02, 0.04):
                rr = bidirectional_select(base, [s for s in s2 if s != base], s2, ver, delta_min=dm, gap_min=gm)
                sens[(dm, gm)] += int(rr["ok"])
        rows.append(r)

    f3 = lambda x: f"{x:+.3f}"  # noqa: E731
    print("| Lv | 신규 | 상태 | θ | 풀 | W_orig | 원맵 백분위 | base−orig (CI) | e2 | e1 | h1 | h2 | 미충족 | wall s |")
    print("|---|---|---|---|---|---|---|---|---|---|---|---|---|---|")
    for r in rows:
        if r["status"] == "not_finished":
            print(f"| {r['level']} | | 미완 |"); continue
        if r["status"] == "unevaluable":
            mx = max(r["scan"].values())
            print(f"| {r['level']} | {'Y' if r['new'] else ''} | 평가 불가 | — | — | — | — | — | | | | | 스캔 최대 {mx:.3f} | {r['wall']:.0f} |")
            continue
        bv = r["baseVsOrig"]
        cells = []
        for t in ("e2", "e1", "h1", "h2"):
            if "tiers" in r:
                dv, lo, hi = r["tiers"][t]
                cells.append(f"{f3(dv)} [{lo:+.2f},{hi:+.2f}]" if t.startswith("e") else f"{f3(dv)} [{-hi:+.2f},{-lo:+.2f}]")
            else:
                cells.append("—")
        print(f"| {r['level']} | {'Y' if r['new'] else ''} | {r['status']} | {r['thetas']} | {r['pool']} | {r['wOrig']:.3f} | "
              f"{r['pct']:.2f} | {f3(bv[0])} [{bv[1]:+.2f},{bv[2]:+.2f}] | " + " | ".join(cells) +
              f" | {','.join(f'{k}:{v}' for k, v in (r.get('unmet') or {}).items())} | {r['wall']:.0f} |")
    done = [r for r in rows if r["status"] != "not_finished"]
    stats = {
        "finished": len(done),
        "status": dict(Counter(r["status"] for r in done)),
        "okAtPool": dict(pool_ok),
        "unmetReasons": dict(reasons),
        "sensitivity_okCount(deltaMin,gapMin)": {f"{k[0]}/{k[1]}": v for k, v in sorted(sens.items())},
        "wallSecTotal": sum(r["wall"] for r in done),
        "wallSecByStatus": {s: [round(r["wall"]) for r in done if r["status"] == s] for s in ("ok", "bidirectional_unmet", "unevaluable")},
        "evaluable": sum(1 for r in done if r["status"] != "unevaluable"),
        "origPct": [round(r["pct"], 2) for r in done if "pct" in r],
    }
    print(json.dumps(stats, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
