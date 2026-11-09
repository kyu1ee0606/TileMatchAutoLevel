#!/usr/bin/env python3
"""Aggregate tilecore_client shadow logs ({gen,sweep}_shadow_diff.jsonl) and decide PASS/FAIL (plan §3단계).

usage: python scripts/tilecore_shadow_report.py [--dir ~/tilecore/shadow] [--since 2026-11-09T10:00] [--json out.json]
                                                [--min-calls 1000] [--min-gimmick 30] [--paths gen,sweep]

Categories per record: same | mismatch | cs_unsupported | timeout | cs_error | serialize_error
(+ sampled_on records from `on` mode sampling: same | mismatch).
  comparable = same + mismatch;  not_comparable = cs_unsupported + timeout + cs_error + serialize_error

TWO POPULATIONS, never summed (no combined 'same' is printed or stored):
  normal       = compared on the ORIGINAL level
  seeded_copy  = randSeed<=0 + t0 levels compared on a per-call SEEDED COPY (record has "seeded_copy": true)
Every table (path total and per-gimmick) is split into these two; each has its own n / same / mismatch /
not_comparable / not_comparable%.
VERDICT (per path)
  normal      PASS = mismatch == 0 AND not_comparable% < 5 (plan line 196) AND n >= --min-calls
              (gimmick tags below --min-gimmick are flagged "thin", not failed)
  seeded_copy PASS = mismatch == 0 AND not_comparable% < 5 (separate condition; n == 0 -> "N/A", not a failure)
  path PASS = normal PASS AND seeded_copy (PASS or N/A)
PATHS: by default BOTH gen and sweep are required; a path without any record is NO_DATA = not passed. Use --paths gen
to judge only some paths.
Exit code: 0 = all required paths PASS; 2 = some path FAILED; 3 = no data for a required path (and none failed).
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


def split_seeded(rows):
    """(normal rows, seeded-copy rows)."""
    nz = [r for r in rows if not r.get("seeded_copy")]
    sd = [r for r in rows if r.get("seeded_copy")]
    return nz, sd


def agg(rows):
    c = collections.Counter(r.get("category", "?") for r in rows)
    n = len(rows)
    nc = sum(c[k] for k in NOT_COMPARABLE)
    return {"n": n, "same": c["same"], "mismatch": c["mismatch"], **{k: c[k] for k in NOT_COMPARABLE},
            "not_comparable": nc, "not_comparable_pct": round(100.0 * nc / n, 2) if n else 0.0,
            "py_s": round(sum(r.get("py_s", 0) for r in rows), 2), "cs_s": round(sum(r.get("cs_s", 0) for r in rows), 2)}


def judge_normal(a, min_calls):
    reasons = []
    if a["mismatch"]:
        reasons.append(f"mismatch={a['mismatch']}")
    if a["not_comparable_pct"] >= 5.0:
        reasons.append(f"not_comparable {a['not_comparable_pct']}% >= 5%")
    if a["n"] < min_calls:
        reasons.append(f"volume {a['n']} < {min_calls}")
    return reasons


def judge_seeded(a):
    if a["n"] == 0:
        return None            # N/A
    reasons = []
    if a["mismatch"]:
        reasons.append(f"mismatch={a['mismatch']}")
    if a["not_comparable_pct"] >= 5.0:
        reasons.append(f"not_comparable {a['not_comparable_pct']}% >= 5%")
    return reasons


def build_path(rows, min_calls, min_gimmick):
    nz, sd = split_seeded(rows)
    res = {"normal": agg(nz), "seeded_copy": agg(sd)}
    gim = {}
    for key, part in (("normal", nz), ("seeded_copy", sd)):
        by = collections.defaultdict(list)
        for r in part:
            for g in (r.get("gim") or ["(none)"]):
                by[g].append(r)
        gim[key] = {g: agg(v) for g, v in sorted(by.items())}
    res["gimmicks"] = gim
    res["thin_gimmicks_normal"] = sorted(g for g, v in gim["normal"].items() if v["n"] < min_gimmick)
    res["thin_gimmicks_seeded_copy"] = sorted(g for g, v in gim["seeded_copy"].items() if v["n"] < min_gimmick)
    rn = judge_normal(res["normal"], min_calls)
    rs = judge_seeded(res["seeded_copy"])
    res["verdict_normal"] = "PASS" if not rn else "FAIL: " + "; ".join(rn)
    res["verdict_seeded_copy"] = "N/A" if rs is None else ("PASS" if not rs else "FAIL: " + "; ".join(rs))
    res["verdict"] = "PASS" if (not rn and not rs) else "FAIL"
    res["first_mismatch"] = next((r for r in rows if r.get("category") == "mismatch"), None)
    return res


def fmt(a):
    return (f"n={a['n']} same={a['same']} mismatch={a['mismatch']} cs_unsupported={a['cs_unsupported']} "
            f"timeout={a['timeout']} cs_error={a['cs_error']} serialize_error={a['serialize_error']} "
            f"not_comparable={a['not_comparable']} ({a['not_comparable_pct']}%) py_s={a['py_s']} cs_s={a['cs_s']}")


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--dir", default="~/tilecore/shadow")
    ap.add_argument("--since", default="")
    ap.add_argument("--json", default="")
    ap.add_argument("--min-calls", type=int, default=1000)
    ap.add_argument("--min-gimmick", type=int, default=30)
    ap.add_argument("--paths", default="gen,sweep", help="required paths (default both)")
    a = ap.parse_args(argv)
    d = os.path.expanduser(a.dir)
    since = datetime.datetime.fromisoformat(a.since).timestamp() if a.since else 0
    paths = [p.strip() for p in a.paths.split(",") if p.strip()]
    out, failed, no_data = {}, False, False
    for path in paths:
        rows = load(os.path.join(d, f"{path}_shadow_diff.jsonl"), since)
        if not rows:
            out[path] = {"verdict": "NO_DATA"}
            no_data = True
            continue
        res = build_path(rows, a.min_calls, a.min_gimmick)
        failed |= res["verdict"] != "PASS"
        out[path] = res
    for path, res in out.items():
        if res["verdict"] == "NO_DATA":
            print(f"== {path}: NO_DATA (not passed)")
            continue
        print(f"== {path}: {res['verdict']}")
        print(f"   <normal: 원본 레벨 그대로 비교> {res['verdict_normal']}\n      {fmt(res['normal'])}")
        print(f"   <seeded_copy: 시드 고정 사본으로 비교> {res['verdict_seeded_copy']}\n      {fmt(res['seeded_copy'])}")
        for key in ("normal", "seeded_copy"):
            thin = set(res[f"thin_gimmicks_{key}"])
            for g, v in res["gimmicks"][key].items():
                print(f"   [{key}][{g}] n={v['n']} same={v['same']} mismatch={v['mismatch']} "
                      f"not_comparable={v['not_comparable']} ({v['not_comparable_pct']}%){'  (thin)' if g in thin else ''}")
    if a.json:
        json.dump(out, open(a.json, "w"), indent=1, ensure_ascii=False)
    if failed:
        return 2
    return 3 if no_data else 0


if __name__ == "__main__":
    sys.exit(main())
