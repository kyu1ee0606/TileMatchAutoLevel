#!/usr/bin/env python3
"""Plan PLAN_CSHARP_BATCH_LIVE_20261106 §2-C: python vs `tilecore serve` (v1 skill profile) on a live batch.

Per level: 8 theta points x 64 rollouts, seed = 4242 + idx*1000, early_termination=True, max_moves=None (exactly what
rl_sim._parallel_point_sweep sends), compared game by game: cleared, moves, combo, tiles_cleared and the real game
count n (+ the rounded point dict that sweep_point_task returns). Also the generator's `optimal` profile (PR 0.99) in
gen_state mode: 5 games from a fixed python RNG state, compared per game + end RNG state.

Resumable: one JSON line per finished level in <out>/results.jsonl; rerun with the same --out skips finished levels.
Progress: <out>/progress.json (updated every few levels); final: <out>/summary.json.

usage (from backend/):
  python scripts/tilecore_sweep_parity.py --sample 50                       # evenly spaced 50 levels
  python scripts/tilecore_sweep_parity.py --workers 4 --threads 2           # all levels
Python workers (--workers, default 4) run in a process pool, C# is one resident `serve --threads N` (default 2).
"""
import argparse
import concurrent.futures as cf
import json
import os
import random
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

from app.core import tilecore_client as tc                       # noqa: E402
from app.core import mc_difficulty as mc                         # noqa: E402
from app.core.bot_simulator import BotSimulator                  # noqa: E402
from app.models.bot_profile import BotType, get_profile          # noqa: E402

DEFAULT_BATCH = os.path.expanduser(
    "~/TileMatchAutoLevel/backend/data/production/batch_1786011385119_qi96gz8x5.json")
DEFAULT_OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "claudedocs",
                           "tilecore_sweep_parity_20261106")
ROLLOUTS, BASE_SEED = 64, mc.DEFAULT_BASE_SEED


def _grid():
    return mc.normalize_skill_grid(None)


def py_level(args):
    """Worker process: python side for one level -> records (no C# here)."""
    i, lj = args
    t0 = time.perf_counter()
    pts = []
    for k, theta in enumerate(_grid()):
        task = {"key": i, "level_json": lj, "theta": theta, "rollouts": ROLLOUTS, "seed": BASE_SEED + k * 1000,
                "max_moves": None}
        pts.append((task, tc.sweep_point_task_recorded(task)))
    t_sweep = time.perf_counter() - t0
    t1 = time.perf_counter()
    prof = get_profile(BotType.OPTIMAL)
    sim = tc._RecordingSim()
    sim._rng.seed(1000003 * i + 17)
    pre = tc.rng_state_to_json(sim._rng)
    res = sim.simulate_with_profile(lj, prof, iterations=5, max_moves=None, seed=None)
    gen = {"pre": pre, "games": sim.rec_games, "end": tc.rng_state_to_json(sim._rng), "n": res.iterations}
    return {"i": i, "pts": pts, "gen": gen, "py_sweep_s": t_sweep, "py_gen_s": time.perf_counter() - t1}


def _g(games):
    return [[bool(g["cleared"]), int(g["moves"]), int(g["combo"]), int(g["tiles_cleared"])] for g in games]


def compare_level(rec, lj):
    """Main process: C# side + comparison. Returns the result row."""
    tasks = [t for t, _ in rec["pts"]]
    t0 = time.perf_counter()
    cs = tc._cs_many(tasks, "sweep")
    cs_sweep_s = time.perf_counter() - t0
    row = {"i": rec["i"], "lvl": tc._lvl_hash(lj), "py_sweep_s": round(rec["py_sweep_s"], 3),
           "cs_sweep_s": round(cs_sweep_s, 3), "py_gen_s": round(rec["py_gen_s"], 3), "points": [], "first_mismatch": None}
    for (task, prec), r in zip(rec["pts"], cs):
        p = {"theta": task["theta"], "n": len(prec["games"] or [])}
        if isinstance(r, Exception):
            p["cat"] = "unsupported" if isinstance(r, tc.ServeUnsupported) else "timeout" if isinstance(
                r, (TimeoutError, tc.ServeDeadline)) else "error"
            p["msg"] = str(r)[:160]
        else:
            same_games = _g(r[1]) == prec["games"]
            same_point = r[0] == prec["point"]
            p["cat"] = "same" if (same_games and same_point) else "mismatch"
            if p["cat"] == "mismatch" and row["first_mismatch"] is None:
                j = next((k for k, (a, b) in enumerate(zip(_g(r[1]), prec["games"])) if a != b), None)
                row["first_mismatch"] = {"theta": task["theta"], "seed": task["seed"], "game": j, "n_py": len(prec["games"]),
                                         "n_cs": len(r[1]), "py": prec["games"][j] if j is not None else None,
                                         "cs": _g(r[1])[j] if j is not None else None,
                                         "point_py": prec["point"], "point_cs": r[0]}
        row["points"].append(p)
    # generator optimal profile, gen_state mode
    g = rec["gen"]
    prof = get_profile(BotType.OPTIMAL)
    t1 = time.perf_counter()
    try:
        games, st_out = tc._cs_call("sweep", lj, prof, 5, tc.resolve_max_moves(lj, None), None, False, g["pre"])
        same = _g(games) == g["games"] and st_out == g["end"] and len(games) == g["n"]
        row["gen"] = {"cat": "same" if same else "mismatch", "n": g["n"]}
        if not same and row["first_mismatch"] is None:
            row["first_mismatch"] = {"gen_state": True, "py": g["games"], "cs": _g(games),
                                     "state_equal": st_out == g["end"]}
    except tc.ServeUnsupported as exc:
        row["gen"] = {"cat": "unsupported", "msg": str(exc)[:160]}
    except Exception as exc:
        row["gen"] = {"cat": "error", "msg": f"{type(exc).__name__}: {exc}"[:160]}
    row["cs_gen_s"] = round(time.perf_counter() - t1, 3)
    return row


def summarize(rows):
    s = {"levels": len(rows), "points": 0, "points_same": 0, "points_mismatch": 0, "points_unsupported": 0,
         "points_error": 0, "games_py": 0, "gen_state_calls": len(rows), "gen_same": 0, "gen_mismatch": 0,
         "gen_unsupported": 0, "gen_error": 0, "py_sweep_s": 0.0, "cs_sweep_s": 0.0, "py_gen_s": 0.0, "cs_gen_s": 0.0}
    first = None
    for r in rows:
        s["py_sweep_s"] += r["py_sweep_s"]
        s["cs_sweep_s"] += r["cs_sweep_s"]
        s["py_gen_s"] += r["py_gen_s"]
        s["cs_gen_s"] += r["cs_gen_s"]
        for p in r["points"]:
            s["points"] += 1
            s["games_py"] += p["n"]
            s["points_" + {"same": "same", "mismatch": "mismatch", "unsupported": "unsupported"}.get(p["cat"], "error")] += 1
        s["gen_" + {"same": "same", "mismatch": "mismatch", "unsupported": "unsupported"}.get(r["gen"]["cat"], "error")] += 1
        if first is None and r.get("first_mismatch"):
            first = {"i": r["i"], **r["first_mismatch"]}
    for k in ("py_sweep_s", "cs_sweep_s", "py_gen_s", "cs_gen_s"):
        s[k] = round(s[k], 2)
    s["first_mismatch"] = first
    s["all_identical"] = s["points_same"] == s["points"] and s["gen_same"] == s["gen_state_calls"]
    return s


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--batch", default=DEFAULT_BATCH)
    ap.add_argument("--out", default=DEFAULT_OUT)
    ap.add_argument("--sample", type=int, default=0, help="evenly spaced N levels (0 = all)")
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--threads", type=int, default=2, help="serve --threads")
    ap.add_argument("--dll", default="~/tilecore/release/v7/bin/tilecore.dll")
    ap.add_argument("--timeout", type=float, default=120.0)
    a = ap.parse_args()
    os.makedirs(a.out, exist_ok=True)
    os.environ["TILECORE_SERVE_DLL"] = os.path.expanduser(a.dll)
    os.environ["TILECORE_SERVE_THREADS_SWEEP"] = str(a.threads)
    os.environ["TILECORE_TIMEOUT_S"] = str(a.timeout)

    levels = [x["level_json"] for x in json.load(open(a.batch))["levels"]]
    idxs = list(range(len(levels)))
    if a.sample:
        step = len(idxs) / a.sample
        idxs = sorted({int(k * step) for k in range(a.sample)})
    res_path = os.path.join(a.out, "results.jsonl")
    done = {}
    if os.path.exists(res_path):
        for line in open(res_path):
            try:
                r = json.loads(line)
                done[r["i"]] = r
            except ValueError:
                pass
    todo = [i for i in idxs if i not in done]
    print(f"levels target={len(idxs)} done={len(done) - len([d for d in done if d not in idxs])} todo={len(todo)}", flush=True)
    t_start = time.time()
    n_new = 0

    def write_progress():
        rows = [done[i] for i in idxs if i in done]
        prog = {"updated": time.strftime("%Y-%m-%d %H:%M:%S"), "target": len(idxs), "finished": len(rows),
                "elapsed_s": round(time.time() - t_start), "new_this_run": n_new, "summary": summarize(rows) if rows else None}
        json.dump(prog, open(os.path.join(a.out, "progress.json"), "w"), indent=1, ensure_ascii=False)

    if todo:
        with cf.ProcessPoolExecutor(max_workers=a.workers) as ex, open(res_path, "a") as fout:
            it = iter(todo)
            inflight = {}

            def submit():
                i = next(it, None)
                if i is not None:
                    inflight[ex.submit(py_level, (i, levels[i]))] = i
            for _ in range(a.workers * 2):
                submit()
            while inflight:
                fin, _ = cf.wait(list(inflight), return_when=cf.FIRST_COMPLETED)
                for f in fin:
                    i = inflight.pop(f)
                    submit()
                    row = compare_level(f.result(), levels[i])
                    done[i] = row
                    fout.write(json.dumps(row, ensure_ascii=False) + "\n")
                    fout.flush()
                    n_new += 1
                    if n_new % 5 == 0:
                        write_progress()
                        print(f"progress: {len([1 for k in idxs if k in done])}/{len(idxs)} "
                              f"elapsed={time.time() - t_start:.0f}s", flush=True)
    rows = [done[i] for i in idxs if i in done]
    summ = summarize(rows)
    summ["batch"] = os.path.basename(a.batch)
    summ["rollouts"] = ROLLOUTS
    summ["theta_grid"] = _grid()
    w = tc.get_worker("sweep")
    summ["serve_hello"] = w.hello()
    json.dump(summ, open(os.path.join(a.out, "summary.json"), "w"), indent=1, ensure_ascii=False)
    write_progress()
    print(json.dumps({k: v for k, v in summ.items() if k not in ("serve_hello", "theta_grid")}, ensure_ascii=False))
    tc.shutdown_all()
    return 0 if summ["all_identical"] or summ["points_mismatch"] + summ["gen_mismatch"] == 0 else 2


if __name__ == "__main__":
    sys.exit(main())
