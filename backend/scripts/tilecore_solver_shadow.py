"""Offline TILECORE shadow sample for solver.solve_level (Python A*) vs FastJudge (C#).

Runs each selected level through ``solve_level`` with TILECORE=shadow (service result = Python, unchanged)
and summarises the shadow log. One process, sequential (CPU = 1 core + FastJudge --procs 1).

  cd backend
  .venv/bin/python scripts/tilecore_solver_shadow.py run --src data/production/<batch>.json [--src data/fixed_levels.json] \
      --n 30 --log /tmp/tilecore_shadow/sample.jsonl [--node-budget 60000 --time-budget 5]
  .venv/bin/python scripts/tilecore_solver_shadow.py summary --log /tmp/tilecore_shadow/sample.jsonl

Selection = stratified by gimmick set (round-robin over groups, file order inside a group) -> deterministic.
"""
import argparse
import collections
import json
import os
import statistics
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


def _levels(path):
    d = json.load(open(path, encoding="utf-8"))
    if isinstance(d, dict) and isinstance(d.get("levels"), list):
        items = d["levels"]
    elif isinstance(d, dict):
        items = list(d.values())
    else:
        items = d
    for i, it in enumerate(items):
        lj = it.get("level_json") if isinstance(it, dict) and "level_json" in it else it
        if isinstance(lj, dict) and any(k.startswith("layer_") for k in lj):
            yield f"{os.path.basename(path)}#{i}", lj


def cmd_run(a):
    os.environ["TILECORE"] = "shadow"
    os.environ["TILECORE_SHADOW_LOG"] = a.log
    from app.core import tilecore_shadow
    from app.core.solver import solve_level
    groups = collections.OrderedDict()
    for src in a.src:
        for lid, lj in _levels(src):
            groups.setdefault(tuple(tilecore_shadow.gimmick_set(lj)), []).append((lid, lj))
    picked, k = [], 0
    while len(picked) < a.n and any(len(v) > k for v in groups.values()):
        for v in groups.values():
            if len(v) > k and len(picked) < a.n:
                picked.append(v[k])
        k += 1
    print(f"groups {len(groups)} picked {len(picked)}", file=sys.stderr)
    for i, (lid, lj) in enumerate(picked):
        r = solve_level(lj, node_budget=a.node_budget, time_budget_s=a.time_budget)
        print(f"[{i + 1}/{len(picked)}] {lid} py={r['verdict']} nodes={r['nodes_expanded']}", file=sys.stderr)
    cmd_summary(a)


def cmd_summary(a):
    rows = [json.loads(l) for l in open(a.log, encoding="utf-8") if l.strip()]
    cat = collections.Counter(r.get("category") for r in rows)
    print(f"lines {len(rows)} categories {dict(cat)}")
    skip = ("cs_error", "cs_unsupported", "cs_unsupported_seed0", "shadow_internal_error")
    both = [r for r in rows if r.get("category") not in skip and (r.get("py") or {}).get("nodes")]  # both engines searched
    for r in rows:
        if r.get("category") not in ("same",):
            t0 = r.get("t0") or {}
            print(f"  {r.get('category'):24s} py={r['py']['verdict']:17s} cs={r['cs'].get('verdict')}/{r['cs'].get('reason', '')[:40]:40s} "
                  f"gim={','.join(r.get('gimmicks') or [])} t0mis={t0.get('mismatch')}/{t0.get('compared')}")
    if both:
        py = [r["py"]["sec"] for r in both]
        cs_wall = [r["cs"]["wall_s"] for r in both]
        cs_in = [float(r["cs"].get("sec") or 0) for r in both]
        print(f"time (n={len(both)}, decided-by-search lines) py median {statistics.median(py):.3f}s sum {sum(py):.2f}s | "
              f"cs process wall median {statistics.median(cs_wall):.3f}s sum {sum(cs_wall):.2f}s | cs in-engine sum {sum(cs_in):.2f}s")


def main():
    p = argparse.ArgumentParser()
    sp = p.add_subparsers(dest="cmd", required=True)
    r = sp.add_parser("run")
    r.add_argument("--src", action="append", required=True)
    r.add_argument("--n", type=int, default=30)
    r.add_argument("--log", required=True)
    r.add_argument("--node-budget", type=int, default=60000)
    r.add_argument("--time-budget", type=float, default=5.0)
    s = sp.add_parser("summary")
    s.add_argument("--log", required=True)
    a = p.parse_args()
    cmd_run(a) if a.cmd == "run" else cmd_summary(a)


if __name__ == "__main__":
    main()
