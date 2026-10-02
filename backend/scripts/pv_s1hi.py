"""P1 supplementary (floor-effect check): stage-1 seeds re-evaluated at high skill points.

Main protocol θ = {0.29, 0.47, 0.65} gives W≈0 for many late levels (06 report). This stage
runs the same 32 stage-1 seeds and the original map at θ = {0.85, 1.0}, 64 games each, CRN,
early termination off -> <sandbox>/eval/<level>/s1hi.json. Not used by the main selection.

Usage: python scripts/pv_s1hi.py --level 857
"""
from __future__ import annotations

import argparse
import os
import sys
import time
from concurrent.futures import ProcessPoolExecutor

BACKEND = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BACKEND)

from app.core.pv.evaluate import evaluate_maps  # noqa: E402
from pv_run_pilot import load, orig_lj, sandbox, save, seed_lj  # noqa: E402

THETAS_HI = (0.85, 1.0)
GAMES, SEED_BASE = 64, 4_000_000


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--copy-id", default="pv_20261002_live3")
    ap.add_argument("--level", type=int, required=True)
    args = ap.parse_args()
    sb = sandbox(args.copy_id)
    d = os.path.join(sb, "eval", f"{args.level:04d}")
    p = os.path.join(d, "s1hi.json")
    if os.path.exists(p):
        print(f"skip {args.level} s1hi")
        return 0
    t0 = load(os.path.join(sb, "t0", f"{args.level:04d}.json"))
    maps = {str(s): seed_lj(t0, s) for s in t0["candidateSeeds"]}
    maps["orig"] = orig_lj(sb, args.level, t0)
    started = time.time()
    with ProcessPoolExecutor(max_workers=8) as ex:
        out = evaluate_maps(ex, maps, GAMES, SEED_BASE, thetas=THETAS_HI, chunk=32)
    cpu = out.pop("_cpuSec", 0.0)
    save(p, {"level": args.level, "thetas": list(THETAS_HI), "games": GAMES, "seedBase": SEED_BASE,
             "cpuSec": cpu, "wallSec": round(time.time() - started, 2), "results": out})
    ws = sorted(v["W"] for k, v in out.items() if k != "orig")
    print(f"done {args.level} s1hi wall={time.time() - started:.0f}s orig={out['orig']['W']:.3f} "
          f"seedW min={ws[0]:.3f} med={ws[len(ws) // 2]:.3f} max={ws[-1]:.3f}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
