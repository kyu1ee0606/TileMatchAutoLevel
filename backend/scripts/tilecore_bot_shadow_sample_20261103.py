"""Small parity run for the TILECORE bot shadow (autoplay path shape) — plan PLAN_CSHARP_ACCELERATION_20261102 §0-A.

Picks production levels (read only), runs the same calls /analyze/autoplay makes per profile
(simulate_with_profile, max_moves=_calculate_max_moves, seed, early_termination=True) through
tilecore_bot.run_python_recorded, then tilecore_bot.process_request (C# replay, one subprocess per level).

usage (from backend/):
  venv/bin/python scripts/tilecore_bot_shadow_sample_20261103.py --levels 40 --profiles average,expert,optimal \
      --iterations 20 --log /tmp/tc_bot_sample.jsonl [--start 0 --count 20]   # --start/--count = chunking
  venv/bin/python scripts/tilecore_bot_shadow_sample_20261103.py --summary /tmp/tc_bot_sample.jsonl
"""
import argparse
import glob
import json
import os
import random
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.core import tilecore_bot  # noqa: E402
from app.models.bot_profile import get_profile  # noqa: E402

PROD = os.path.expanduser("~/TileMatchAutoLevel/backend/data/production")


def pick_levels(n, pick_seed):
    files = sorted(f for f in glob.glob(os.path.join(PROD, "batch_*.json")))
    rnd = random.Random(pick_seed)
    rnd.shuffle(files)
    out = []
    for f in files:
        try:
            d = json.load(open(f, encoding="utf-8"))
        except Exception:  # noqa: BLE001
            continue
        lv = [x for x in (d.get("levels") or []) if isinstance(x, dict) and isinstance(x.get("level_json"), dict)]
        if not lv:
            continue
        x = rnd.choice(lv)
        out.append((os.path.basename(f), x["level_json"]))
        if len(out) >= n:
            break
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--levels", type=int, default=40)
    ap.add_argument("--profiles", default="average,expert,optimal")
    ap.add_argument("--iterations", type=int, default=20)
    ap.add_argument("--seed", type=int, default=4242)
    ap.add_argument("--pick-seed", type=int, default=20261103)
    ap.add_argument("--start", type=int, default=0)
    ap.add_argument("--count", type=int, default=10**9)
    ap.add_argument("--log", default="/tmp/tc_bot_sample.jsonl")
    ap.add_argument("--summary")
    a = ap.parse_args()
    if a.summary:
        print(json.dumps(tilecore_bot.summarize(a.summary), ensure_ascii=False, indent=1))
        return
    os.environ["TILECORE_BOT_SHADOW_LOG"] = a.log
    from app.api.routes.analyze import _calculate_max_moves
    levels = pick_levels(a.levels, a.pick_seed)[a.start:a.start + a.count]
    t_all = time.perf_counter()
    for k, (src, lj) in enumerate(levels):
        mm = _calculate_max_moves(lj)
        recs = []
        for pn in a.profiles.split(","):
            _, rec = tilecore_bot.run_python_recorded(lj, get_profile(pn), a.iterations, mm, a.seed,
                                                      early_termination=True)
            recs.append(rec)
        lines = tilecore_bot.process_request(lj, mm, recs, kind="sample_autoplay")
        cats = ",".join(l["category"] for l in lines)
        print(f"[{a.start + k}] {src} randSeed={lj.get('randSeed')} unlock={lj.get('unlockTile')} -> {cats}", flush=True)
    print(f"done {len(levels)} levels in {time.perf_counter() - t_all:.1f}s", flush=True)


if __name__ == "__main__":
    main()
