#!/usr/bin/env python3
"""Offline replay harness: generator stuck-checks (TILECORE_GEN) python vs C# serve -> final level JSON byte compare.

Plan: claudedocs/PLAN_CSHARP_BATCH_LIVE_20261106.md stage 2-A.

For each case the production /generate worker (`_generate_core_worker`) runs twice in the SAME process with
everything pinned: global `random` + `os.urandom` (deterministic stream per case), every `BotSimulator()` RNG seeded
from (case seed, instantiation order), PYTHONHASHSEED=0 in workers.  Run A: TILECORE_GEN=off, run B: =on (order
alternates per case).  Compared: serialized response bytes, and per `tilecore_client.simulate` call
(result key + simulator RNG end-state hash).  `--selfcheck` runs off/off instead (checks the pinning itself).

Request parameters follow the production batch (frontend ProductionDashboard handleStartGeneration): levels,
target_difficulty, pattern_index, unit_assembly marker, tile_type_profile and gimmick_unlock_levels come from a real
batch file (read only); symmetry/goal/grid/layers are drawn like the frontend with a per-case seeded RNG.

  python3 scripts/tilecore_gen_replay.py --n 20 --procs 3          # first check
  python3 scripts/tilecore_gen_replay.py --n 300 --procs 3         # resume-capable (results.jsonl)
  python3 scripts/tilecore_gen_replay.py --report                  # summary only
"""
from __future__ import annotations

import argparse
import hashlib
import json
import multiprocessing as mp
import os
import random
import statistics
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
BACKEND = HERE.parent
REPO = BACKEND.parent
DEFAULT_BATCH = Path.home() / "TileMatchAutoLevel/backend/data/production/batch_1792056041502_cn5e4ny66.json"
DEFAULT_OUT = REPO / "claudedocs/tilecore_gen_replay_20261106"
BASE_SEED = 20261106


# ───────────────────────── case construction ─────────────────────────
def _scan(lj: dict) -> dict:
    has_t0 = has_gim = False
    size = 0
    for i in range(int(lj.get("layer", 0) or 0)):
        ld = lj.get(f"layer_{i}") or {}
        size = max(size, int(ld.get("col") or 0), int(ld.get("row") or 0))
        for v in (ld.get("tiles") or {}).values():
            if not isinstance(v, list) or not v:
                continue
            if v[0] == "t0":
                has_t0 = True
            if len(v) > 1 and v[1]:
                has_gim = True
    return {"t0": has_t0, "gim": has_gim, "size8": size >= 8}


def build_cases(batch_path: Path, n: int) -> list:
    d = json.load(open(batch_path))
    batch = d["batch"]
    lvls = [l for l in d["levels"] if l["meta"]["level_number"] >= 4]      # 1~3 are fixed tutorials (no bot calls)
    strata: dict = {}
    for l in lvls:
        lj = l["level_json"]
        sc = _scan(lj)
        boss = l["meta"]["level_number"] % 10 == 0
        band = 0 if l["meta"]["level_number"] < 100 else 1 if l["meta"]["level_number"] < 400 else 2 if l["meta"]["level_number"] < 800 else 3
        key = (boss, sc["size8"], band, sc["gim"])
        strata.setdefault(key, []).append((l, sc))
    rng = random.Random(BASE_SEED)
    for v in strata.values():
        rng.shuffle(v)
    keys = sorted(strata)
    picked, i = [], 0
    while len(picked) < n and any(strata.values()):          # round-robin over strata => balanced
        k = keys[i % len(keys)]
        i += 1
        if strata[k]:
            picked.append((k, *strata[k].pop()))
    cases = []
    for idx, (k, l, sc) in enumerate(picked):
        m, lj = l["meta"], l["level_json"]
        cases.append({
            "id": f"L{m['level_number']}", "idx": idx, "level_number": m["level_number"],
            "target_difficulty": m["target_difficulty"], "pattern_index": m.get("pattern_index"),
            "unit_assembly": bool(lj.get("_unit_assembly")), "stratum": {
                "boss": k[0], "size8": k[1], "band": k[2], "gimmick": k[3]},
            "tile_type_profile": batch.get("tile_type_profile"),
            "gimmick_unlock_levels": batch.get("gimmick_unlock_levels"),
            "seed": BASE_SEED * 1000 + m["level_number"],
        })
    return cases


def build_request(c: dict) -> dict:
    """Mirror of the frontend initial-generation request (one candidate)."""
    r = random.Random(c["seed"])
    L, td = c["level_number"], c["target_difficulty"]
    early, special, boss = L <= 30, L % 10 == 9, L % 10 == 0
    roll = r.random()
    if early:
        sym = "horizontal" if roll < .25 else "vertical" if roll < .5 else "both"
    elif special:
        sym = "none" if roll < .3 else "horizontal" if roll < .65 else "vertical"
    elif boss:
        sym = "horizontal" if roll < .2 else "vertical" if roll < .4 else "both"
    else:
        sym = "none" if roll < .05 else "horizontal" if roll < .4 else "vertical" if roll < .75 else "both"
    if sym in ("both", "vertical"):
        dirs = ["s", "n"] if r.random() < .7 else ["e", "w"]
    elif sym == "horizontal":
        dirs = ["e", "w"] if r.random() < .7 else ["s", "n"]
    else:
        dirs = ["s", "n", "e", "w"]
    gdir, gtype = r.choice(dirs), r.choice(["craft", "stack"])
    grid = [7, 7]
    if boss and td > .3:
        grid = [8, 8]
    elif not early and r.random() < .3:
        grid = [8, 8]
    mn, mx = 2, min(10, 3 + int(td * 7))
    if early:
        mx = min(4, mx)
    elif boss:
        mn, mx = max(3, int(2 + td * 2)), min(10, 4 + int(td * 6))
    layer_var = [-1, 0, 1][c["idx"] % 3]
    mult = [.8, 1.0, 1.2][c["idx"] % 3]
    req = {
        "target_difficulty": td, "grid_size": [7, 7] if boss else grid,
        "min_layers": 5 if boss else max(2, mn + layer_var), "max_layers": 6 if boss else min(10, mx + layer_var),
        "obstacle_types": [],
        "goals": [{"type": gtype, "direction": gdir, "count": max(2, int(3 + td * 2))}],
        "symmetry_mode": sym, "pattern_type": "aesthetic",
        "pattern_index": None if boss or c["pattern_index"] is None or c["pattern_index"] < 0 else c["pattern_index"],
        "auto_select_gimmicks": True,
        "available_gimmicks": ["craft", "stack", "chain", "frog", "ice", "grass", "link", "bomb", "curtain",
                               "teleport", "unknown"],
        "gimmick_intensity": min(td * mult, L / 500),
        "gimmick_unlock_levels": c["gimmick_unlock_levels"], "level_number": L,
    }
    if c.get("tile_type_profile") and c["tile_type_profile"] != "baseline":
        req["tile_type_profile"] = c["tile_type_profile"]
    if c["unit_assembly"] and not boss:
        req["unit_assembly"] = True
    if boss:
        req["boss_mode"] = True
    return req


# ───────────────────────── one pinned generate() run ─────────────────────────
def _jdefault(o):
    if isinstance(o, (set, frozenset)):
        return sorted(o, key=repr)
    return str(o)


class _JsonShim:
    """tilecore_client.request() does json.dumps(level) and fails on set values (_pattern_locked_positions; the bot
    ignores that key). --set-workaround makes dumps() tolerate sets for the C# request ONLY; the python path is untouched."""
    def __getattr__(self, name):
        return getattr(json, name)

    @staticmethod
    def dumps(o, **kw):
        kw.setdefault("default", _jdefault)
        return json.dumps(o, **kw)


def run_once(c: dict, mode: str) -> dict:
    from app.api.routes import generate as gen_routes
    from app.core import bot_simulator, tilecore_client

    os.environ["TILECORE_GEN"] = mode
    tilecore_client.reset_counters()
    from app.core.generator import LevelGenerator
    LevelGenerator._recent_pattern_categories = []        # class-level history leaks between generate() calls
    seed = c["seed"]
    rnd_urandom = random.Random(seed ^ 0x5EED)
    inst = [0]
    calls: list = []

    real_urandom = os.urandom
    os.urandom = lambda n: bytes(rnd_urandom.getrandbits(8) for _ in range(n))
    # unseeded `random.Random()` / `Random(None)` (e.g. select_color_balanced_tiles(seed=None)) -> deterministic seed
    orig_seed = random.Random.seed

    def det_seed(self, a=None, version=2):
        if a is None:
            a = rnd_urandom.getrandbits(64)
        return orig_seed(self, a, version)
    random.Random.seed = det_seed
    orig_init = bot_simulator.BotSimulator.__init__

    def init(self, *a, **kw):
        orig_init(self, *a, **kw)
        self._rng.seed(seed * 1000003 + inst[0])
        inst[0] += 1
    bot_simulator.BotSimulator.__init__ = init

    orig_sim = tilecore_client.simulate
    orig_json = tilecore_client.json
    if mode == "on" and os.environ.get("GEN_REPLAY_SET_WORKAROUND") == "1":
        tilecore_client.json = _JsonShim()

    def rec(simulator, level_json, profile, **kw):
        t = time.perf_counter()
        res = orig_sim(simulator, level_json, profile, **kw)
        calls.append({"it": kw.get("iterations"), "seed": kw.get("seed"), "res": list(tilecore_client._res_key(res)),
                      "end": tilecore_client._state_hash(simulator._rng), "s": round(time.perf_counter() - t, 5)})
        return res
    tilecore_client.simulate = rec
    random.seed(seed)
    t0 = time.perf_counter()
    try:
        out = gen_routes._generate_core_worker(build_request(c))
        wall = time.perf_counter() - t0
        if out.get("ok"):
            d = out["response"].model_dump()
            d.pop("generation_time_ms", None)
            body = json.dumps(d, ensure_ascii=False, separators=(",", ":"), default=_jdefault).encode()
        else:
            body = json.dumps({"error": out}, ensure_ascii=False, sort_keys=True, default=_jdefault).encode()
    finally:
        tilecore_client.simulate = orig_sim
        tilecore_client.json = orig_json
        bot_simulator.BotSimulator.__init__ = orig_init
        os.urandom = real_urandom
        random.Random.seed = orig_seed
    return {"body": body, "wall": wall, "calls": calls, "inst": inst[0],
            "counters": tilecore_client.counters().get("gen", {})}


_WORKER_N = [0]


def work(args) -> dict:
    c, selfcheck, outdir = args
    first, second = ("off", "off") if selfcheck else (("off", "on") if c["idx"] % 2 == 0 else ("on", "off"))
    # Warm-up pair (discarded): the python bot/generator keep process-level state that makes the first run of a case
    # differ from later runs (python-vs-python, independent of C#) -> compare only warm runs, in alternating order.
    run_once(c, "off")
    run_once(c, "off" if selfcheck else "on")
    a = run_once(c, first)
    b = run_once(c, second)
    runs = {}
    if selfcheck:
        runs = {"a": a, "b": b}
        py, cs = a, b
    else:
        runs = {first: a, second: b}
        py, cs = runs["off"], runs["on"]
    same_bytes = py["body"] == cs["body"]
    same_calls = len(py["calls"]) == len(cs["calls"]) and all(
        x["res"] == y["res"] and x["end"] == y["end"] and x["it"] == y["it"] and x["seed"] == y["seed"]
        for x, y in zip(py["calls"], cs["calls"]))
    first_diff = None
    if not same_calls:
        for i, (x, y) in enumerate(zip(py["calls"], cs["calls"])):
            if x["res"] != y["res"] or x["end"] != y["end"]:
                first_diff = {"call": i, "py": x, "cs": y}
                break
        else:
            first_diff = {"call_count": [len(py["calls"]), len(cs["calls"])]}
    if not same_bytes:
        Path(outdir, "mismatch").mkdir(parents=True, exist_ok=True)
        Path(outdir, "mismatch", f"{c['id']}_py.json").write_bytes(py["body"])
        Path(outdir, "mismatch", f"{c['id']}_cs.json").write_bytes(cs["body"])
    _WORKER_N[0] += 1
    return {
        "id": c["id"], "idx": c["idx"], "level": c["level_number"], "stratum": c["stratum"],
        "selfcheck": selfcheck, "same_bytes": same_bytes, "same_calls": same_calls, "first_diff": first_diff,
        "n_calls": len(py["calls"]), "n_it3": sum(1 for x in py["calls"] if x["it"] == 3),
        "n_it5": sum(1 for x in py["calls"] if x["it"] == 5), "n_instances": py["inst"], "bytes_len": len(py["body"]),
        "sha": hashlib.sha256(py["body"]).hexdigest()[:16], "t0_out": b'"t0"' in py["body"],
        "py_s": round(py["wall"], 4), "cs_s": round(cs["wall"], 4), "order": first,
        "first_in_proc": _WORKER_N[0] == 1,
        "cs_counters": cs["counters"], "py_bot_s": round(sum(x["s"] for x in py["calls"]), 4),
        "cs_bot_s": round(sum(x["s"] for x in cs["calls"]), 4), "pid": os.getpid(),
    }


# ───────────────────────── report ─────────────────────────
def pct(v, p):
    v = sorted(v)
    return v[min(len(v) - 1, int(round(p * (len(v) - 1))))] if v else float("nan")


def report(outdir: Path, load_note: str = "") -> str:
    rows = [json.loads(l) for l in open(outdir / "results.jsonl")] if (outdir / "results.jsonl").exists() else []
    rows = [r for r in rows if not r.get("selfcheck")]
    if not rows:
        return "no results"
    n = len(rows)
    sb = sum(r["same_bytes"] for r in rows)
    sc = sum(r["same_calls"] for r in rows)
    calls = sum(r["n_calls"] for r in rows)
    agg = {k: sum(r["cs_counters"].get(k, 0) for r in rows) for k in
           ("cs_ok", "unsupported", "error", "timeout", "fallback")}
    lines0 = (f"calls by site: _quick_deadlock_check(5 games)={sum(r.get('n_it5', 0) for r in rows)}  "
              f"_fix_same_type_blocking(3 games)={sum(r.get('n_it3', 0) for r in rows)}")
    steady = [r for r in rows if not r["first_in_proc"]]
    tpy = [r["py_s"] for r in steady]
    tcs = [r["cs_s"] for r in steady]
    bpy = [r["py_bot_s"] for r in steady]
    bcs = [r["cs_bot_s"] for r in steady]
    ncalls = [r["n_calls"] for r in rows]
    lines = [
        f"levels={n}  json_byte_identical={sb}/{n}  per-call-identical levels={sc}/{n}  total_calls={calls}",
        f"C# counters (on runs): {agg}  unsupported_ratio={agg['unsupported'] / max(1, calls):.4f}  "
        f"fallback_ratio={agg['fallback'] / max(1, calls):.4f}",
        f"levels with 0 bot calls={sum(1 for x in ncalls if x == 0)}  calls/level median={statistics.median(ncalls)} "
        f"max={max(ncalls)}",
        f"generate() wall (excl. first case per process; n={len(steady)}) {load_note}",
        f"  python total : median {statistics.median(tpy):.3f}s  p95 {pct(tpy, .95):.3f}s  sum {sum(tpy):.1f}s",
        f"  C# total     : median {statistics.median(tcs):.3f}s  p95 {pct(tcs, .95):.3f}s  sum {sum(tcs):.1f}s",
        f"  python bot-only: median {statistics.median(bpy):.3f}s  p95 {pct(bpy, .95):.3f}s",
        f"  C# bot-only    : median {statistics.median(bcs):.3f}s  p95 {pct(bcs, .95):.3f}s",
        f"  speedup total median-of-ratios {statistics.median([a / b for a, b in zip(tpy, tcs) if b > 0]):.2f}x  "
        f"sum-ratio {sum(tpy) / max(1e-9, sum(tcs)):.2f}x",
    ]
    lines.insert(1, lines0)
    strata: dict = {}
    for r in rows:
        k = "boss={boss} size8={size8} band={band} gimmick={gimmick}".format(**r["stratum"])
        s = strata.setdefault(k, [0, 0])
        s[0] += 1
        s[1] += r["same_bytes"]
    lines.append(f"output has t0 tiles: {sum(1 for r in rows if r.get('t0_out'))}/{n} levels "
                 f"(identical among them: {sum(1 for r in rows if r.get('t0_out') and r['same_bytes'])})")
    lines.append("strata (n / identical):")
    lines += [f"  {k}: {v[0]} / {v[1]}" for k, v in sorted(strata.items())]
    bad = [r for r in rows if not (r["same_bytes"] and r["same_calls"])]
    if bad:
        lines.append(f"MISMATCH first: {json.dumps(bad[0], ensure_ascii=False)[:1500]}")
    text = "\n".join(lines)
    (outdir / "summary.txt").write_text(text + "\n")
    return text


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=20)
    ap.add_argument("--procs", type=int, default=3)
    ap.add_argument("--batch", default=str(DEFAULT_BATCH))
    ap.add_argument("--out", default=str(DEFAULT_OUT))
    ap.add_argument("--selfcheck", action="store_true", help="off vs off (pinning check)")
    ap.add_argument("--report", action="store_true")
    ap.add_argument("--set-workaround", action="store_true",
                    help="convert set values to lists in level_json sent to C# (tilecore_client cannot serialize sets)")
    ap.add_argument("--note", default="", help="load note for the report")
    a = ap.parse_args()
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    if a.report:
        print(report(out, a.note))
        return
    if os.environ.get("PYTHONHASHSEED") != "0":           # re-exec so parent + spawned workers share a hash seed
        os.environ["PYTHONHASHSEED"] = "0"
        os.execv(sys.executable, [sys.executable] + sys.argv)
    sys.path.insert(0, str(BACKEND))
    if a.set_workaround:
        os.environ["GEN_REPLAY_SET_WORKAROUND"] = "1"
    res_path = out / ("selfcheck.jsonl" if a.selfcheck else "results.jsonl")
    done = set()
    if res_path.exists():
        done = {json.loads(l)["id"] for l in open(res_path)}
    cases = [c for c in build_cases(Path(a.batch), a.n) if c["id"] not in done]
    print(f"cases to run: {len(cases)} (done {len(done)})", flush=True)
    ctx = mp.get_context("spawn")
    t0 = time.time()
    with ctx.Pool(a.procs, initializer=_init, initargs=(str(BACKEND),)) as pool, open(res_path, "a") as f:
        for k, r in enumerate(pool.imap_unordered(work, [(c, a.selfcheck, str(out)) for c in cases]), 1):
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
            f.flush()
            if k % 10 == 0 or not (r["same_bytes"] and r["same_calls"]):
                print(f"[{k}/{len(cases)}] {r['id']} bytes={r['same_bytes']} calls={r['same_calls']} "
                      f"py={r['py_s']}s cs={r['cs_s']}s elapsed={time.time() - t0:.0f}s", flush=True)
    if not a.selfcheck:
        print(report(out, a.note))


def _init(backend: str) -> None:
    sys.path.insert(0, backend)
    os.environ.setdefault("TILECORE_SERVE_THREADS_GEN", "1")
    import logging
    logging.disable(logging.WARNING)


if __name__ == "__main__":
    main()
