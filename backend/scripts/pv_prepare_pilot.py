"""P1 prep: t0-ize sample levels, derive K candidate seeds, write sandbox t0 rows + golden inputs.

Usage: python scripts/pv_prepare_pilot.py [--copy-id pv_20261002_live3] [--k 32] [--golden]
"""
from __future__ import annotations

import argparse
import json
import os
import sys

BACKEND = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BACKEND)

from app.core.pv.evaluate import candidate_seeds  # noqa: E402
from app.core.pv.t0ize import t0ize_level  # noqa: E402

GOLDEN_INPUTS = os.path.join(BACKEND, "tests", "golden", "pv_t0", "inputs")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--copy-id", default="pv_20261002_live3")
    ap.add_argument("--k", type=int, default=32)
    ap.add_argument("--golden", action="store_true", help="also write golden inputs r_pv_l*.json")
    args = ap.parse_args()
    sb = os.path.join(BACKEND, "data", "pv_sandbox", args.copy_id)
    sample = json.load(open(os.path.join(sb, "sample.json"), encoding="utf-8"))["sample"]
    src = json.load(open(os.path.join(sb, "source.json"), encoding="utf-8"))
    by_n = {lv["meta"]["level_number"]: lv for lv in src["levels"]}
    os.makedirs(os.path.join(sb, "t0"), exist_ok=True)

    for s in sample:
        n = s["level"]
        lv = by_n[n]
        first = t0ize_level(lv["level_json"], 1)
        seeds = candidate_seeds(first["meta"]["structHash"], args.k)
        res = t0ize_level(lv["level_json"], seeds[0])
        out = {
            "level": n,
            "row": res["row"],
            "meta": res["meta"],
            "candidateSeeds": seeds,
            "orig": {
                "randSeed": lv["level_json"].get("randSeed"),
                "useTileCount": lv["level_json"].get("useTileCount"),
                "predicted_clear_rate": lv["meta"].get("predicted_clear_rate"),
                "target_difficulty": lv["meta"].get("target_difficulty"),
            },
        }
        with open(os.path.join(sb, "t0", f"{n:04d}.json"), "w", encoding="utf-8") as f:
            json.dump(out, f, ensure_ascii=False)
        if args.golden:
            case = {
                "caseId": f"r_pv_l{n:04d}",
                "kind": "real",
                "note": f"P1 pilot: LIVE3 Lv{n} t0-ized ({res['meta']['t0izeVersion']}, canonical GB order); "
                        f"runs = {args.k} candidate seeds (evaluated boards)",
                "levelId": f"level_{n}",
                "dumpRng": False,
                "row": res["row"],
                "runs": [{"randSeed": str(x)} for x in seeds],
            }
            with open(os.path.join(GOLDEN_INPUTS, f"r_pv_l{n:04d}.json"), "w", encoding="utf-8") as f:
                json.dump(case, f, ensure_ascii=False, separators=(",", ":"))
        print(n, res["meta"]["utc0"], res["meta"]["tileCount"], seeds[:3])
    return 0


if __name__ == "__main__":
    sys.exit(main())
