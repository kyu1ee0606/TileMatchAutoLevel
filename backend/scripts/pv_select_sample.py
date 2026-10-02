"""P1 pilot sample selection (04 §7-3 candidate rules + stratified 20 levels).

Reads the sandbox copy only. Writes <sandbox>/sample.json.
Usage: python scripts/pv_select_sample.py [--copy-id pv_20261002_live3]
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from collections import Counter

BACKEND = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BACKEND)

from app.core.pv.t0ize import PvT0izeError, t0ize_level  # noqa: E402

RISKY_EFFECT_PREFIX = ("bomb", "curtain", "frog", "teleporter", "unknown")  # solver-unreliable (03 §1)
TUTORIAL_LEVELS = {11, 21, 31, 51, 81, 111, 151, 191, 241, 291, 391, 441}  # GEN TUTORIAL_UNLOCK_LEVELS
SHARD_STRUCT_MISMATCH = {34}  # 05 §3-3 (P0-G4)
STRATA = [(32, 250, 3), (251, 500, 3), (501, 750, 3), (751, 1000, 4), (1001, 1250, 3), (1251, 1500, 4)]


def exclusion_reasons(n: int, lj: dict) -> list:
    r = []
    if n < 32 or n > 1500:
        r.append("range")
    if n % 10 == 0:
        r.append("boss")
    if n in TUTORIAL_LEVELS:
        r.append("tutorial")
    if n in SHARD_STRUCT_MISMATCH:
        r.append("shard_struct_mismatch")
    try:
        if int(lj.get("timea", lj.get("timeAttack", 0)) or 0) > 0:
            r.append("timea")
    except (TypeError, ValueError):
        r.append("timea_unparsable")
    effects, craft, keys, count_only = set(), False, False, False
    for k, layer in lj.items():
        if not k.startswith("layer_") or not isinstance(layer, dict):
            continue
        tiles = layer.get("tiles")
        if not isinstance(tiles, dict):
            continue
        for t in tiles.values():
            tid = t[0] if t and isinstance(t[0], str) else ""
            eff = t[1] if len(t) > 1 and isinstance(t[1], str) else ""
            if eff:
                effects.add(eff.lower())
            if tid.startswith("craft_"):
                craft = True
            if tid in ("key", "t16") or eff.lower() == "key":
                keys = True
            if tid.startswith(("stack_", "craft_")) and len(t) > 2 and isinstance(t[2], list):
                inner = t[2][1] if len(t[2]) > 1 and isinstance(t[2][1], str) else ""
                ids = inner.split("_") if inner else []
                if len(ids) != int(t[2][0]):
                    count_only = True
                elif "key" in ids:
                    keys = True
    if any(e.startswith(RISKY_EFFECT_PREFIX) for e in effects):
        r.append("risky_gimmick")
    if craft:
        r.append("craft")
    if keys:
        r.append("key")
    if count_only:
        r.append("count_only")
    return r


def gimmick_class(lj: dict) -> str:
    effs, stack = set(), False
    for k, layer in lj.items():
        if k.startswith("layer_") and isinstance(layer, dict) and isinstance(layer.get("tiles"), dict):
            for t in layer["tiles"].values():
                if len(t) > 1 and isinstance(t[1], str) and t[1]:
                    effs.add(t[1].split("_")[0].lower())
                if t and isinstance(t[0], str) and t[0].startswith("stack_"):
                    stack = True
    parts = sorted(effs) + (["stack"] if stack else [])
    return "+".join(parts) if parts else "plain"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--copy-id", default="pv_20261002_live3")
    args = ap.parse_args()
    sb = os.path.join(BACKEND, "data", "pv_sandbox", args.copy_id)
    data = json.load(open(os.path.join(sb, "source.json"), encoding="utf-8"))

    reasons_count = Counter()
    cands = []
    for lv in data["levels"]:
        n = lv["meta"].get("level_number")
        lj = lv["level_json"]
        if not isinstance(n, int) or n < 32 or n > 1500:
            continue
        rs = exclusion_reasons(n, lj)
        for x in rs:
            reasons_count[x] += 1
        if rs:
            continue
        try:
            t0ize_level(lj, 1)
        except PvT0izeError as e:
            reasons_count["t0ize_error"] += 1
            print(f"Lv{n}: t0ize error {e}")
            continue
        cands.append((n, gimmick_class(lj)))

    sample = []
    for lo, hi, k in STRATA:
        pool = [c for c in cands if lo <= c[0] <= hi]
        if not pool:
            continue
        picks = sorted({int((j + 0.5) * len(pool) / k) for j in range(k)})
        for p in picks:
            n, g = pool[min(p, len(pool) - 1)]
            sample.append({"level": n, "stratum": f"{lo}-{hi}", "gimmicks": g, "stratumPool": len(pool)})

    out = {
        "copyId": args.copy_id,
        "rules": "04 §7-3 + 05 §3-3: exclude boss, tutorial, timea>0, Lv34, risky gimmick "
                 "(bomb/curtain/frog/teleporter/unknown), craft, key, count-only containers",
        "exclusionCounts": dict(reasons_count),
        "candidateCount": len(cands),
        "candidatesByStratum": {f"{lo}-{hi}": sum(1 for c in cands if lo <= c[0] <= hi) for lo, hi, _ in STRATA},
        "sample": sample,
    }
    with open(os.path.join(sb, "sample.json"), "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)
    print(json.dumps(out, ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
