"""Bot v2.1 gimmick-awareness calibration — 16_bot_v21_gimmick_awareness.md.

Data: reuses bot_compare_L32_500 (prep / af / v1 / v2 rows). Results: data/pv_sandbox/af_calibration/bot_v21/.
  exposure          per level: number of earlier levels (1..L-1) whose played map contains bomb / grass.
  grid              θ=1.0, 64 games, grass/bomb levels only, alpha × gamma grid (same pair for both gimmicks;
                    each gimmick is scored only on its own levels, levels with both gimmicks are left out of the fit).
  fit               2-fold CV over random half splits: choose (alpha, gamma) per gimmick on half A, score on half B.
  run --alpha-bomb .. --gamma-bomb .. --alpha-grass .. --gamma-grass .. [--grid] [--games]
                    full v2.1 measurement on grass/bomb levels (other levels are bit-identical to v2: no awareness
                    draw happens without those gimmicks), written as bot_v2.1.json together with the v2 rows of the
                    other levels.
Workers <= 3 (shares CPU with the DDA measurement).
"""
from __future__ import annotations

import argparse
import itertools
import json
import os
import random
import sys
import time
from collections import Counter
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

BACKEND = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND))
sys.path.insert(0, str(BACKEND / "scripts"))

import bot_af_L32_500 as base  # noqa: E402

SRC = base.OUT                                         # bot_compare_L32_500
OUT = BACKEND / "data/pv_sandbox/af_calibration/bot_v21"
WORKERS = min(3, int(os.environ.get("PV_WORKERS", "3")))
GIMMICKS = {"bomb": "eff_bomb", "grass": "eff_grass"}
ALPHAS = (-3.0, -2.0, -1.0, 0.0, 1.0, 2.0)
GAMMAS = (0.0, 2.0, 4.0)
FIT_THETA, FIT_GAMES = 1.0, 64
FIXED = {"beta": 4.0, "l0": 0.5, "tau": 15.0}         # assumptions (not identifiable from θ=1.0 data)


def load(p):
    with open(p, encoding="utf-8") as f:
        return json.load(f)


def save(name, obj):
    OUT.mkdir(parents=True, exist_ok=True)
    tmp = OUT / (name + ".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, separators=(",", ":"))
    os.replace(tmp, OUT / name)


_CACHE = {}


def prep():
    if "prep" not in _CACHE:
        _CACHE["prep"] = {int(k): v for k, v in load(SRC / "prep.json").items()}
        _CACHE["af"] = {int(k): v for k, v in load(SRC / "af.json").items()}
    return _CACHE["prep"], _CACHE["af"]


def exposure_table():
    """n_g(L) = levels before L (in 32..L-1; no bomb/grass exists in 1..31) whose map has gimmick g."""
    P, _ = prep()
    out, cnt = {}, Counter()
    for L in sorted(P):
        out[L] = {g: cnt[g] for g in GIMMICKS}
        for g, f in GIMMICKS.items():
            if P[L]["features"].get(f, 0) > 0:
                cnt[g] += 1
    return out


def levels_of(g=None):
    P, A = prep()
    lv = [L for L in sorted(P) if not P[L]["exclude"] and (A[L]["clean_ft_n"] or 0) >= 100]
    if g is None:
        return lv
    return [L for L in lv if P[L]["features"].get(GIMMICKS[g], 0) > 0]


def run_task(args):
    """Like bot_af_L32_500.run_task but v2.1 with injected awareness params + level exposure; also logs dock size."""
    import dataclasses
    from app.core.bot_simulator import BotSimulator
    from app.core.mc_difficulty import make_skill_profile
    t0 = time.time()
    P, _ = prep()
    entry = P[args["L"]]
    games = args["games"]
    n_lay = min(base.LAYOUTS, games) if entry["mode"] == "random" else 1
    lays = base.level_layouts(entry, n_lay)
    per = games // len(lays)
    prof = make_skill_profile(args["theta"], "v2.1")
    cfg = dict(prof.gimmick_awareness)
    cfg.update(FIXED)
    cfg["alpha"], cfg["gamma"] = args["alpha"], args["gamma"]
    cfg["exposure"] = args["exposure"]
    prof = dataclasses.replace(prof, gimmick_awareness=cfg)
    bot = BotSimulator()
    wins, left, left_board, reasons, n = 0, [], [], Counter(), 0
    for li, lj in enumerate(lays):
        total = int(lj["max_moves"]) - 50
        st0 = bot._create_initial_state(lj, int(lj["max_moves"]))
        bot._precompute_blocking_map(st0)
        for g in range(per):
            bot._rng.seed(11_000_000 + li * 1000 + g)          # same seeds as bot_af_L32_500
            final = bot._play_game(bot._fast_copy_state(st0), prof)
            n += 1
            if final.cleared:
                wins += 1
            else:
                rem = total - final.total_tiles_cleared
                left.append(rem)
                left_board.append(rem - len(final.dock_tiles))
                reasons[base.fail_reason(bot, final)] += 1
    return {"L": args["L"], "theta": args["theta"], "ver": "v2.1", "games": n, "wins": wins, "layouts": len(lays),
            "fail_tiles_left": left, "fail_tiles_left_board": left_board, "fail_reasons": dict(reasons),
            "params": {"alpha": args["alpha"], "gamma": args["gamma"]}, "sec": time.time() - t0}


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


def cmd_exposure(a):
    ex = exposure_table()
    save("exposure.json", ex)
    first = {g: min(L for L, v in prep()[0].items() if v["features"].get(f, 0) > 0) for g, f in GIMMICKS.items()}
    print("first appearance", first, "levels with gimmick:", {g: len(levels_of(g)) for g in GIMMICKS})


def cmd_grid(a):
    ex = {int(k): v for k, v in load(OUT / "exposure.json").items()}
    only = a.only.split(",") if a.only else list(GIMMICKS)
    lv = sorted(set().union(*(levels_of(g) for g in only)))
    alphas = [float(x) for x in a.alphas.split(",")] if a.alphas else ALPHAS
    gammas = [float(x) for x in a.gammas.split(",")] if a.gammas else GAMMAS
    tasks = []
    for al, ga in itertools.product(alphas, gammas):
        for L in lv:
            tasks.append({"L": L, "theta": FIT_THETA, "games": FIT_GAMES, "exposure": ex[L],
                          "alpha": {"bomb": al, "grass": al}, "gamma": {"bomb": ga, "grass": ga}})
    if a.part:
        tasks = tasks[: a.part]
    d = _pool_run(tasks, "grid.json", lambda r: (r["L"], r["params"]["alpha"]["bomb"], r["params"]["gamma"]["bomb"])
                  if "params" in r else (r["L"], r["alpha"]["bomb"], r["gamma"]["bomb"]))
    print(f"grid rows={len(d['rows'])} (this call {len(alphas) * len(gammas) * len(lv)} tasks)")


# ── fit ─────────────────────────────────────────────────────────────────────────────────────────
def _targets():
    """Per level AF mid, segment plain-level AF mean and v2 plain-level bot mean at FIT_THETA (relative target)."""
    if "targets" in _CACHE:
        return _CACHE["targets"]
    P, A = prep()
    lv = levels_of()
    mid = {L: (A[L]["unaided_clear_lower_bound"] + A[L]["unaided_clear_upper_bound"]) / 2 for L in lv}
    v2 = {(r["L"], r["theta"]): r for r in load(SRC / "bot_v2.json")["rows"]}
    plain = [L for L in lv if not any(P[L]["features"].get(f, 0) for f in GIMMICKS.values())]
    seg_af, seg_bot = {}, {}
    for lo, hi in base.SEGMENTS:
        s = f"{lo}-{hi}"
        G = [L for L in plain if lo <= L <= hi]
        seg_af[s] = sum(mid[L] for L in G) / len(G)
        seg_bot[s] = sum(v2[(L, FIT_THETA)]["wins"] / v2[(L, FIT_THETA)]["games"] for L in G) / len(G)
    _CACHE["targets"] = (mid, seg_af, seg_bot, v2)
    return _CACHE["targets"]


def _af_share(L, g):
    _, A = prep()
    c = Counter()
    for k, v in (A[L]["fail_reason"] or {}).items():
        c[k.replace("_CantRevive", "")] += v
    return c


def group_metrics(rows_by_L, g, lv):
    """Relative prediction MAE, gimmick fail share (bot vs AF), Spearman vs AF mid, for gimmick g on levels lv."""
    from bot_af_L1_31 import spearman
    mid, seg_af, seg_bot, _ = _targets()
    gname = g.capitalize()
    pred, bc, ac = {}, Counter(), Counter()
    for L in lv:
        r = rows_by_L[L]
        s = base.seg_of(L)
        pred[L] = seg_af[s] + (r["wins"] / r["games"] - seg_bot[s])
        bc.update(r["fail_reasons"])
        ac.update(_af_share(L, g))
    bt, at = sum(bc.values()), sum(ac.values())
    return {"n": len(lv), "mae_rel": sum(abs(pred[L] - mid[L]) for L in lv) / len(lv),
            "bias_rel": sum(pred[L] - mid[L] for L in lv) / len(lv),
            "share_bot": bc[gname] / bt if bt else 0.0, "share_af": ac[gname] / at if at else 0.0,
            "rho": spearman([rows_by_L[L]["wins"] / rows_by_L[L]["games"] for L in lv], [mid[L] for L in lv]) if len(lv) > 2 else None}


def _loss(m):
    return m["mae_rel"] + 0.5 * abs(m["share_bot"] - m["share_af"])


def cmd_fit(a):
    rows = load(OUT / "grid.json")["rows"]
    by = {}
    for r in rows:
        by.setdefault((r["params"]["alpha"]["bomb"], r["params"]["gamma"]["bomb"]), {})[r["L"]] = r
    P, _ = prep()
    _, _, _, v2 = _targets()
    out = {"grid": {}, "v2_baseline": {}, "cv": {}, "chosen": {}}
    for g in GIMMICKS:
        other = [x for x in GIMMICKS if x != g][0]
        lv = [L for L in levels_of(g) if not P[L]["features"].get(GIMMICKS[other], 0)]
        base_rows = {L: v2[(L, FIT_THETA)] for L in lv}
        by_g = {k: v for k, v in by.items() if all(L in v for L in lv)}
        out["v2_baseline"][g] = group_metrics(base_rows, g, lv)
        out["grid"][g] = {f"{al},{ga}": group_metrics(by_g[(al, ga)], g, lv) for (al, ga) in by_g}
        # CV
        rng = random.Random(16)
        res, picks = [], Counter()
        for _ in range(200):
            s = lv[:]
            rng.shuffle(s)
            A_, B_ = s[: len(s) // 2], s[len(s) // 2:]
            best = min(by_g, key=lambda k: _loss(group_metrics(by[k], g, A_)))
            picks[best] += 1
            mB = group_metrics(by[best], g, B_)
            mB0 = group_metrics(base_rows, g, B_)
            res.append((mB["mae_rel"], mB0["mae_rel"], mB["share_bot"], mB["share_af"], mB["rho"], mB0["rho"]))
        out["cv"][g] = {"mae_rel_v21": round(sum(r[0] for r in res) / 200, 4), "mae_rel_v2": round(sum(r[1] for r in res) / 200, 4),
                        "share_bot_v21": round(sum(r[2] for r in res) / 200, 3), "share_af": round(sum(r[3] for r in res) / 200, 3),
                        "rho_v21": round(sum(r[4] for r in res) / 200, 3), "rho_v2": round(sum(r[5] for r in res) / 200, 3),
                        "picks": {f"{k[0]},{k[1]}": v for k, v in picks.most_common(5)}}
        best_all = min(by_g, key=lambda k: _loss(out["grid"][g][f"{k[0]},{k[1]}"]))
        out["chosen"][g] = {"alpha": best_all[0], "gamma": best_all[1], **out["grid"][g][f"{best_all[0]},{best_all[1]}"]}
    save("fit.json", out)
    print(json.dumps({k: out[k] for k in ("v2_baseline", "cv", "chosen")}, ensure_ascii=False, indent=1))


# ── full run ───────────────────────────────────────────────────────────────────────────────────
def cmd_run(a):
    ex = {int(k): v for k, v in load(OUT / "exposure.json").items()}
    alpha = {"bomb": a.alpha_bomb, "grass": a.alpha_grass}
    gamma = {"bomb": a.gamma_bomb, "grass": a.gamma_grass}
    P, _ = prep()
    lv = [L for L in sorted(P) if not P[L]["exclude"]
          and any(P[L]["features"].get(f, 0) for f in GIMMICKS.values())]
    grid = [float(x) for x in a.grid.split(",")]
    tasks = [{"L": L, "theta": th, "games": a.games, "exposure": ex[L], "alpha": alpha, "gamma": gamma}
             for th in grid for L in lv]
    d = _pool_run(tasks, "v21_gimmick_rows.json", lambda r: (r["L"], r["theta"]))
    print(f"run v2.1 rows={len(d['rows'])}")


def cmd_assemble(a):
    """bot_v2.1.json = v2.1 rows for grass/bomb levels + v2 rows (identical behaviour) for the rest; copies inputs
    so bot_af_L32_500 report/calib can run on OUT with versions v1, v2, v2.1."""
    import shutil
    P, _ = prep()
    gim = {L for L in P if any(P[L]["features"].get(f, 0) for f in GIMMICKS.values())}
    v21 = [r for r in load(OUT / "v21_gimmick_rows.json")["rows"]]
    have = {(r["L"], r["theta"]) for r in v21}
    rows = v21 + [r for r in load(SRC / "bot_v2.json")["rows"] if r["L"] not in gim]
    missing = [(r["L"], r["theta"]) for r in load(SRC / "bot_v2.json")["rows"] if r["L"] in gim and (r["L"], r["theta"]) not in have
               and not P[r["L"]]["exclude"]]
    save("bot_v2.1.json", {"rows": rows})
    for f in ("prep.json", "af.json", "bot_v1.json", "bot_v2.json"):
        shutil.copyfile(SRC / f, OUT / f)
    print(f"assembled rows={len(rows)} gimmick-level rows missing={len(missing)}")


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("exposure").set_defaults(f=cmd_exposure)
    p = sub.add_parser("grid"); p.add_argument("--part", type=int, default=0)
    p.add_argument("--only", default=""); p.add_argument("--alphas", default=""); p.add_argument("--gammas", default="")
    p.set_defaults(f=cmd_grid)
    sub.add_parser("fit").set_defaults(f=cmd_fit)
    p = sub.add_parser("run")
    for k in ("alpha-bomb", "gamma-bomb", "alpha-grass", "gamma-grass"):
        p.add_argument(f"--{k}", type=float, required=True)
    p.add_argument("--grid", default="0.15,0.29,0.4,0.47,0.55,0.65,0.75,0.85,1.0")
    p.add_argument("--games", type=int, default=128)
    p.set_defaults(f=cmd_run)
    sub.add_parser("assemble").set_defaults(f=cmd_assemble)
    a = ap.parse_args()
    a.f(a)


if __name__ == "__main__":
    main()
