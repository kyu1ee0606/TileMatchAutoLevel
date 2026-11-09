#!/usr/bin/env python3
"""Aggregate tilecore_client shadow logs ({gen,sweep}_shadow_diff.jsonl) and decide PASS/FAIL (plan §3단계).

usage: python scripts/tilecore_shadow_report.py [--dir ~/tilecore/shadow] [--since 2026-11-09T10:00] [--json out.json]
                                                [--min-calls 1000] [--min-gimmick 30]

Categories per record: same | mismatch | cs_unsupported | timeout | cs_error | serialize_error
(+ sampled_on records from `on` mode sampling: same | mismatch).
  comparable = same + mismatch;  not_comparable = cs_unsupported + timeout + cs_error + serialize_error
PASS (per path) = mismatch == 0  AND  not_comparable / total < 5%  (plan line 196)  AND  volume enough
  (total >= --min-calls; every gimmick tag seen at least --min-gimmick times is reported, tags below it are flagged
  "thin" and listed, not failed).
Also prints the not_comparable breakdown so 'rs0'(randSeed<=0, python time-seeded t0) can be seen separately.
Exit code 0 = all paths PASS, 2 = something failed, 3 = no data.
"""
import argparse
import collections
import datetime
import json
import os
import sys

NOT_COMPARABLE = ("cs_unsupported", "timeout", "cs_error", "serialize_error")


def load(path, since):
    rows = []
    if not os.path.exists(path):
        return rows
    for line in open(path, encoding="utf-8"):
        try:
            r = json.loads(line)
        except ValueError:
            continue
        if since and r.get("ts", 0) < since:
            continue
        rows.append(r)
    return rows


def agg(rows):
    c = collections.Counter(r.get("category", "?") for r in rows)
    total = len(rows)
    nc = sum(c[k] for k in NOT_COMPARABLE)
    return {"total": total, "same": c["same"], "mismatch": c["mismatch"],
            **{k: c[k] for k in NOT_COMPARABLE}, "not_comparable": nc,
            "not_comparable_pct": round(100.0 * nc / total, 2) if total else 0.0,
            "py_s": round(sum(r.get("py_s", 0) for r in rows), 2), "cs_s": round(sum(r.get("cs_s", 0) for r in rows), 2)}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dir", default="~/tilecore/shadow")
    ap.add_argument("--since", default="")
    ap.add_argument("--json", default="")
    ap.add_argument("--min-calls", type=int, default=1000)
    ap.add_argument("--min-gimmick", type=int, default=30)
    a = ap.parse_args()
    d = os.path.expanduser(a.dir)
    since = datetime.datetime.fromisoformat(a.since).timestamp() if a.since else 0
    out, ok_all, any_data = {}, True, False
    for path in ("gen", "sweep"):
        rows = load(os.path.join(d, f"{path}_shadow_diff.jsonl"), since)
        if not rows:
            out[path] = {"total": 0, "verdict": "NO_DATA"}
            continue
        any_data = True
        res = agg(rows)
        by_g = collections.defaultdict(list)
        for r in rows:
            for g in (r.get("gim") or ["(none)"]):
                by_g[g].append(r)
        res["gimmicks"] = {g: agg(v) for g, v in sorted(by_g.items())}
        res["thin_gimmicks"] = sorted(g for g, v in by_g.items() if len(v) < a.min_gimmick)
        nc_rs0 = sum(1 for r in rows if r.get("category") in NOT_COMPARABLE and "rs0" in (r.get("gim") or []))
        res["not_comparable_with_rs0"] = nc_rs0
        res["not_comparable_without_rs0"] = res["not_comparable"] - nc_rs0
        reasons = []
        if res["mismatch"]:
            reasons.append(f"mismatch={res['mismatch']}")
        if res["not_comparable_pct"] >= 5.0:
            reasons.append(f"not_comparable {res['not_comparable_pct']}% >= 5%")
        if res["total"] < a.min_calls:
            reasons.append(f"volume {res['total']} < {a.min_calls}")
        res["verdict"] = "PASS" if not reasons else "FAIL: " + "; ".join(reasons)
        ok_all &= not reasons
        first = next((r for r in rows if r.get("category") == "mismatch"), None)
        res["first_mismatch"] = first
        out[path] = res
    for path, res in out.items():
        print(f"== {path}: {res.get('verdict')}  total={res.get('total')}")
        if res.get("total"):
            print("   " + " ".join(f"{k}={res[k]}" for k in ("same", "mismatch") + NOT_COMPARABLE),
                  f"| not_comparable={res['not_comparable_pct']}% (rs0 {res['not_comparable_with_rs0']}, other "
                  f"{res['not_comparable_without_rs0']}) | py_s={res['py_s']} cs_s={res['cs_s']}")
            for g, v in res["gimmicks"].items():
                print(f"   [{g}] n={v['total']} same={v['same']} mismatch={v['mismatch']} not_cmp={v['not_comparable']}"
                      f"{'  (thin)' if g in res['thin_gimmicks'] else ''}")
    if a.json:
        json.dump(out, open(a.json, "w"), indent=1, ensure_ascii=False)
    if not any_data:
        return 3
    return 0 if ok_all else 2


if __name__ == "__main__":
    sys.exit(main())
