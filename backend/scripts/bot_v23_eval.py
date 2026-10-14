"""Bot v2.3 (game-rule parity) evaluation — 19_bot_rule_parity.md.

Base = v2.1 (fitted awareness + exposure). Results: data/pv_sandbox/af_calibration/bot_v23/.
  item  --name ITEM --levels FEATURE[,FEATURE] [--thetas ..] [--games N]
        v2.3 with ONLY that parity item on, on the levels containing any listed feature; compared with the
        v2.1 rows of the same (level, θ) (bot_v21/bot_v2.1.json, same seeds).
  full  [--grid ..] [--games N]       v2.3 with all items, all 410 comparison levels (θ grid) → bot_v2.3.json
  isum                                 per-item summary (group bias / MAE (relative, as in 16) / ρ before → after)
  assemble                             copies inputs so bot_af_L32_500 report/calib run on OUT with v1,v2,v2.1,v2.3
Workers <= 3.
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
import time
from collections import Counter
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

BACKEND = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND))
sys.path.insert(0, str(BACKEND / "scripts"))

import bot_af_L32_500 as base  # noqa: E402
import bot_v21_fit as v21  # noqa: E402

SRC = base.OUT
V21_OUT = v21.OUT
OUT = BACKEND / "data/pv_sandbox/af_calibration/bot_v23"
WORKERS = min(3, int(os.environ.get("PV_WORKERS", "3")))
GRID = "0.15,0.29,0.4,0.47,0.55,0.65,0.75,0.85,1.0"


def load(p):
    with open(p, encoding="utf-8") as f:
        return json.load(f)


def save(name, obj):
    OUT.mkdir(parents=True, exist_ok=True)
    tmp = OUT / (name + ".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, separators=(",", ":"))
    os.replace(tmp, OUT / name)


def run_task(args):
    import dataclasses
    from app.core.bot_simulator import BotSimulator, V21_AWARENESS_DEFAULTS
    from app.core.mc_difficulty import make_skill_profile
    t0 = time.time()
    P, _ = v21.prep()
    entry = P[args["L"]]
    games = args["games"]
    n_lay = min(base.LAYOUTS, games) if entry["mode"] == "random" else 1
    lays = base.level_layouts(entry, n_lay)
    per = games // len(lays)
    prof = make_skill_profile(args["theta"], "v2.3")
    cfg = dict(prof.gimmick_awareness)
    cfg.update(v21.FIXED)
    cfg["alpha"], cfg["gamma"] = V21_AWARENESS_DEFAULTS["alpha"], V21_AWARENESS_DEFAULTS["gamma"]
    cfg["exposure"] = args["exposure"]
    cfg["parity"] = args["parity"]                 # None = all items
    cfg["auto_collect"] = int(float(entry["row"].get("autoCollectCount") or 0))
    prof = dataclasses.replace(prof, gimmick_awareness=cfg)
    bot = BotSimulator()
    wins, left, left_board, reasons, n = 0, [], [], Counter(), 0
    for li, lj in enumerate(lays):
        total = int(lj["max_moves"]) - 50
        bot.set_rule_parity(prof)                   # init-time parity items (e.g. craft emission) need it first
        st0 = bot._create_initial_state(lj, int(lj["max_moves"]))
        bot._precompute_blocking_map(st0)
        for g in range(per):
            bot._rng.seed(11_000_000 + li * 1000 + g)          # same seeds as bot_af_L32_500 / bot_v21_fit
            final = bot._play_game(bot._fast_copy_state(st0), prof)
            n += 1
            if final.cleared:
                wins += 1
            else:
                rem = total - final.total_tiles_cleared
                left.append(rem)
                left_board.append(rem - len(final.dock_tiles))
                reasons[base.fail_reason(bot, final)] += 1
    return {"L": args["L"], "theta": args["theta"], "ver": "v2.3", "games": n, "wins": wins, "layouts": len(lays),
            "fail_tiles_left": left, "fail_tiles_left_board": left_board, "fail_reasons": dict(reasons),
            "parity": args["parity"], "sec": time.time() - t0}


def _pool_run(tasks, name, key):
    path = OUT / name
    done = load(path) if path.exists() else {"rows": []}
    have = {key(r) for r in done["rows"]}
    todo = [t for t in tasks if key(t) not in have]
    t0 = time.time()
    with ProcessPoolExecutor(WORKERS) as ex:
        for r in ex.map(run_task, todo, chunksize=1):
            done["rows"].append(r)
            if time.time() - t0 > 30:
                save(name, done)
                t0 = time.time()
    save(name, done)
    return done


def levels_with(features):
    P, A = v21.prep()
    if features == ["cat"]:                           # 냥이의 도움 레벨(비교 집합에서 빠졌던 47개 중 AF 판 ≥100)
        return [L for L in sorted(P) if P[L]["exclude"] == "cat_help" and (A[L]["clean_ft_n"] or 0) >= 100]
    lv = v21.levels_of()
    if not features:
        return lv
    def has(L, f):
        if f == "row_unlock":                         # unlockTile > 0 in the level row (key/lock parity)
            return int(P[L]["row"].get("unlockTile") or 0) > 0
        return P[L]["features"].get(f, 0) > 0
    return [L for L in lv if any(has(L, f) for f in features)]


def cmd_item(a):
    ex = {int(k): v for k, v in load(V21_OUT / "exposure.json").items()}
    lv = levels_with([f for f in a.levels.split(",") if f])
    parity = [a.name] if a.parity is None else [x for x in a.parity.split(",") if x]
    tasks = [{"L": L, "theta": float(t), "games": a.games, "exposure": ex[L], "parity": parity}
             for t in a.thetas.split(",") for L in lv]
    d = _pool_run(tasks, f"item_{a.name}.json", lambda r: (r["L"], r["theta"]))
    print(f"item {a.name}: rows={len(d['rows'])} levels={len(lv)}")


def cmd_full(a):
    ex = {int(k): v for k, v in load(V21_OUT / "exposure.json").items()}
    P, _ = v21.prep()
    lv = [L for L in sorted(P) if not P[L]["exclude"]]
    tasks = [{"L": L, "theta": float(t), "games": a.games, "exposure": ex[L], "parity": None}
             for t in a.grid.split(",") for L in lv]
    d = _pool_run(tasks, "v23_rows.json", lambda r: (r["L"], r["theta"]))
    print(f"full v2.3 rows={len(d['rows'])}")


def cmd_isum(a):
    from bot_af_L1_31 import spearman
    P, A = v21.prep()
    lv_all = [L for L in P if (A[L]["clean_ft_n"] or 0) >= 100 and A[L]["unaided_clear_lower_bound"] is not None]
    mid = {L: (A[L]["unaided_clear_lower_bound"] + A[L]["unaided_clear_upper_bound"]) / 2 for L in lv_all}
    b21 = {(r["L"], r["theta"]): r for r in load(V21_OUT / "bot_v2.1.json")["rows"]}
    base_cat = OUT / "item_cat_base.json"          # v2.1-equivalent (no parity item) rows for the cat levels
    if base_cat.exists():
        for r in load(base_cat)["rows"]:
            b21.setdefault((r["L"], r["theta"]), r)
    out = {}
    for f in sorted(OUT.glob("item_*.json")):
        name = f.stem[5:]
        if name == "cat_base" or name == "summary":
            continue
        rows = load(f)["rows"]
        by_t = {}
        for r in rows:
            if r["L"] in mid:
                by_t.setdefault(r["theta"], []).append(r)
        res = {}
        for t, rs in sorted(by_t.items()):
            Ls = [r["L"] for r in rs]
            after = {r["L"]: r["wins"] / r["games"] for r in rs}
            before = {L: b21[(L, t)]["wins"] / b21[(L, t)]["games"] for L in Ls}
            changed = sum(1 for L in Ls if abs(after[L] - before[L]) > 1e-9)
            res[str(t)] = {"levels": len(Ls), "changed_levels": changed,
                           "mean_rate_before": round(sum(before.values()) / len(Ls), 4),
                           "mean_rate_after": round(sum(after.values()) / len(Ls), 4),
                           "resid_before": round(sum(before[L] - mid[L] for L in Ls) / len(Ls), 4),
                           "resid_after": round(sum(after[L] - mid[L] for L in Ls) / len(Ls), 4),
                           "rho_before": round(spearman([before[L] for L in Ls], [mid[L] for L in Ls]), 3) if len(Ls) > 2 else None,
                           "rho_after": round(spearman([after[L] for L in Ls], [mid[L] for L in Ls]), 3) if len(Ls) > 2 else None,
                           "sec_per_game": round(sum(r["sec"] for r in rs) / sum(r["games"] for r in rs), 4)}
        out[name] = res
    save("item_summary.json", out)
    print(json.dumps(out, ensure_ascii=False, indent=1))


def cmd_assemble(a):
    rows = load(OUT / "v23_rows.json")["rows"]
    save("bot_v2.3.json", {"rows": rows})
    shutil.copyfile(V21_OUT / "bot_v2.1.json", OUT / "bot_v2.1.json")
    for f in ("prep.json", "af.json", "bot_v1.json", "bot_v2.json"):
        shutil.copyfile(SRC / f, OUT / f)
    print(f"assembled v2.3 rows={len(rows)}")


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("item"); p.add_argument("--name", required=True); p.add_argument("--levels", default="")
    p.add_argument("--thetas", default="0.65,1.0"); p.add_argument("--games", type=int, default=128)
    p.add_argument("--parity", default=None, help="comma list of items (default: --name); '' = none (v2.1 baseline)")
    p.set_defaults(f=cmd_item)
    p = sub.add_parser("full"); p.add_argument("--grid", default=GRID); p.add_argument("--games", type=int, default=128)
    p.set_defaults(f=cmd_full)
    sub.add_parser("isum").set_defaults(f=cmd_isum)
    sub.add_parser("assemble").set_defaults(f=cmd_assemble)
    a = ap.parse_args()
    a.f(a)


if __name__ == "__main__":
    main()
