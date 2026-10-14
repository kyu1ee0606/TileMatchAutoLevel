"""Bot skill axis vs real users (AF), L1~31 — 14_bot_v2_vs_af_L1_31.md.

Sub-commands (results under data/pv_sandbox/af_calibration/bot_compare_L1_31/):
  af              AF first-try unaided metrics per level, restricted to the versions whose build shard equals the
                  1.1.0 shard (mixed levels: android 1.1.0 + ios 2.1.0 only; same levels: also 1.0.162).
                  Reuses af_level_metrics (read-only). ~3 min.
  maps            Level rows + maps from the 1.1.0/iOS 2.1.0 build shard (game repo commit b741f6a3, git show only).
  run --ver v1|v2 θ grid × layouts × games. randSeed 0 levels: LAYOUTS random layouts (client ShuffleEmptyTiles port,
                  seeds 1..LAYOUTS) — the client draws a time seed per play. Fixed-seed levels: the one layout.
  report          Spearman / range hit / CV / tiles_left analysis → report.json.

Shared core untouched; workers <= 4.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import random
import subprocess
import sys
import time
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

BACKEND = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND))
sys.path.insert(0, str(BACKEND / "scripts"))

OUT = BACKEND / "data/pv_sandbox/af_calibration/bot_compare_L1_31"
GAME_REPO = "/Users/casualdev/sp_meowsgarden"
SHARD_COMMIT = "b741f6a3"           # 1.1.0 / iOS 2.1.0 build shard (13 §6)
WORKERS = min(4, int(os.environ.get("PV_WORKERS", "4")))
LAYOUTS = 32
GAMES_PER_LAYOUT = 8                # 256 games per (level, θ)
GRID = {"v1": (0.0, 0.15, 0.29, 0.40, 0.47, 0.55, 0.65, 0.75, 0.85, 1.0),
        "v2": (0.0, 0.15, 0.29, 0.40, 0.47, 0.55, 0.65, 0.75, 0.85, 1.0, 1.2)}
LEVELS = range(1, 32)
SAME_SHARD_VERSIONS = {("android", "1.1.0"), ("ios", "2.1.0")}


def load(p):
    with open(p, encoding="utf-8") as f:
        return json.load(f)


def save(name, obj):
    OUT.mkdir(parents=True, exist_ok=True)
    tmp = OUT / (name + ".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, separators=(",", ":"))
    os.replace(tmp, OUT / name)


# ── AF ──────────────────────────────────────────────────────────────────────────────────────────
def cmd_af(a):
    import af_level_metrics as am
    per_dev, meta = am.load_events(am.AF_DATA)
    runs, *_ = am.build_runs(per_dev)
    del per_dev
    am.mark_first_try(runs)
    runs = [r for r in runs if not r["infinite"] and 1 <= r["L"] <= 31]
    full = {x["level"]: x for x in load(am.OUT_DIR / "level_metrics.json")["levels"] if x["level"] <= 31}
    out = {}
    for L in LEVELS:
        match = full[L]["map_match"]
        allowed = None if match == "same" else SAME_SHARD_VERSIONS
        rs = [r for r in runs if r["L"] == L and (allowed is None or (r["plat"], r["ver"]) in allowed)]
        b = am.level_block(rs)
        b["map_match"] = match
        b["versions_used"] = "all" if allowed is None else "1.1.0+ios2.1.0"
        # sensitivity: 1.1.0+iOS only for every level (one user pool)
        b2 = am.level_block([r for r in runs if r["L"] == L and (r["plat"], r["ver"]) in SAME_SHARD_VERSIONS])
        b["only_110"] = {k: b2[k] for k in ("clean_ft_n", "clean_ft_rate", "unaided_clear_lower_bound",
                                             "unaided_clear_upper_bound", "ft_booster_rate", "ft_help_rate")}
        out[L] = b
    save("af_L1_31.json", out)
    for L, b in out.items():
        print(L, b["map_match"], b["clean_ft_n"], b["clean_ft_rate"], b["unaided_clear_lower_bound"],
              b["unaided_clear_upper_bound"], b["ft_booster_rate"], b["fail_tiles_left"].get("p50"))


# ── maps ────────────────────────────────────────────────────────────────────────────────────────
def _git_key(key):
    from pv_scan_shards import decrypt_shard_file
    p = f"Assets/StreamingAssets/GBoost/a{hashlib.md5(key.encode()).hexdigest()}.txt"
    r = subprocess.run(["git", "-C", GAME_REPO, "show", f"{SHARD_COMMIT}:{p}"], capture_output=True)
    if r.returncode != 0:
        raise RuntimeError(f"git show failed: {key}")
    return decrypt_shard_file(r.stdout)


def cmd_maps(a):
    maps = _git_key("levelmap_level_0")      # levels 1..100 live in shard 0
    tab = _git_key("levels")
    keys = tab["__keys"]
    rows = {}
    for v in tab["__vals"]:
        o = {keys[i]: v[i] for i in range(min(len(keys), len(v)))}
        rows[str(o.get("id"))] = o
    out = {}
    for L in LEVELS:
        r = rows[f"level_{L}"]
        out[L] = {"row": {k: r.get(k) for k in ("randSeed", "useTileCount", "unlockTile", "shuffleTile",
                                                "typeImbalance", "autoCollectCount", "layer")},
                  "map": maps[f"level_{L}"]}
    save("maps.json", out)
    for L, v in out.items():
        print(L, v["row"])


def level_layouts(L, entry):
    """Bot level_jsons for a level: fixed seed → 1 layout; randSeed 0 → LAYOUTS sampled seeds."""
    from app.core.pv.cs_shuffle import resolve_map, shuffle_empty_tiles
    from app.core.pv.t0ize import bot_level_json
    row = entry["row"]
    fixed = int(row.get("randSeed") or 0)
    seeds = [fixed] if fixed else list(range(1, LAYOUTS + 1))
    out = []
    for s in seeds:
        res = shuffle_empty_tiles(entry["map"], rand_seed=s, use_tile_count=row["useTileCount"],
                                  unlock_tile=row.get("unlockTile") or 0, shuffle_tile=row.get("shuffleTile") or 0,
                                  type_imbalance=row.get("typeImbalance") or 0, strict=True)
        r2 = {"randSeed": s, "useTileCount": row["useTileCount"], "unlockTile": row.get("unlockTile") or 0}
        out.append(bot_level_json(r2, resolve_map(entry["map"], res)))
    return out


# ── bot runs ────────────────────────────────────────────────────────────────────────────────────
def run_task(args):
    from app.core.bot_simulator import BotSimulator
    from app.core.mc_difficulty import make_skill_profile
    t0 = time.time()
    entry = load(OUT / "maps.json")[str(args["L"])]
    lays = level_layouts(args["L"], entry)
    games = (LAYOUTS * GAMES_PER_LAYOUT) // len(lays)
    prof = make_skill_profile(args["theta"], args["ver"])
    bot = BotSimulator()
    wins, left = 0, []
    n = 0
    for li, lj in enumerate(lays):
        total = int(lj["max_moves"]) - 50
        base = bot._create_initial_state(lj, int(lj["max_moves"]))
        bot._precompute_blocking_map(base)
        for g in range(games):
            bot._rng.seed(9_000_000 + li * 1000 + g)
            final = bot._play_game(bot._fast_copy_state(base), prof)
            n += 1
            if final.cleared:
                wins += 1
            else:
                left.append(total - final.total_tiles_cleared)
    return {"L": args["L"], "theta": args["theta"], "ver": args["ver"], "games": n, "wins": wins,
            "layouts": len(lays), "fail_tiles_left": left, "sec": time.time() - t0}


def cmd_run(a):
    name = f"bot_{a.ver}.json"
    path = OUT / name
    done = load(path) if path.exists() else {"rows": []}
    have = {(r["L"], r["theta"]) for r in done["rows"]}
    levels = [int(x) for x in a.levels.split(",")] if a.levels else list(LEVELS)
    grid = [float(x) for x in a.grid.split(",")] if a.grid else GRID[a.ver]
    todo = [{"L": L, "theta": th, "ver": a.ver} for th in grid for L in levels if (L, th) not in have]
    t0 = time.time()
    with ProcessPoolExecutor(WORKERS) as ex:
        for r in ex.map(run_task, todo):
            done["rows"].append(r)
            if time.time() - t0 > 30:
                save(name, done)
                t0 = time.time()
    save(name, done)
    print(f"run {a.ver}: rows={len(done['rows'])}")


# ── report ──────────────────────────────────────────────────────────────────────────────────────
def spearman(x, y):
    def rank(v):
        o = sorted(range(len(v)), key=lambda i: v[i])
        r = [0.0] * len(v)
        i = 0
        while i < len(o):
            j = i
            while j + 1 < len(o) and v[o[j + 1]] == v[o[i]]:
                j += 1
            for k in range(i, j + 1):
                r[o[k]] = (i + j) / 2
            i = j + 1
        return r
    rx, ry = rank(x), rank(y)
    mx, my = sum(rx) / len(rx), sum(ry) / len(ry)
    c = sum((a - mx) * (b - my) for a, b in zip(rx, ry))
    s = (sum((a - mx) ** 2 for a in rx) * sum((b - my) ** 2 for b in ry)) ** 0.5
    return c / s if s else float("nan")


def q(v, p):
    v = sorted(v)
    return v[min(len(v) - 1, int(p * len(v)))] if v else None


def cmd_report(a):
    af = {int(k): v for k, v in load(OUT / "af_L1_31.json").items()}
    maps = {int(k): v for k, v in load(OUT / "maps.json").items()}
    excl = {}
    for L in LEVELS:
        if int(maps[L]["row"].get("autoCollectCount") or 0) > 0:
            excl[L] = "cat_help(autoCollectCount>0)"
        elif (af[L]["ft_booster_rate"] or 0) >= 0.5:
            excl[L] = f"booster_tutorial(ft_booster_rate={af[L]['ft_booster_rate']})"
    levels = [L for L in LEVELS if L not in excl]
    lb = {L: af[L]["unaided_clear_lower_bound"] for L in levels}
    ub = {L: af[L]["unaided_clear_upper_bound"] for L in levels}
    mid = {L: (lb[L] + ub[L]) / 2 for L in levels}
    pt = {L: af[L]["clean_ft_rate"] for L in levels}
    # tolerant range: [Wilson lower of LB, Wilson upper of UB] on the first-try ended runs (AF sampling noise)
    from af_level_metrics import wilson
    nft = {L: af[L]["first_try_ended"] for L in levels}
    lb_lo = {L: wilson(round(lb[L] * nft[L]), nft[L])[0] for L in levels}
    ub_hi = {L: wilson(round(ub[L] * nft[L]), nft[L])[1] for L in levels}
    rep = {"excluded": excl, "levels": levels, "versions": {}}
    for ver in ("v1", "v2"):
        p = OUT / f"bot_{ver}.json"
        if not p.exists():
            continue
        rows = load(p)["rows"]
        rate = {(r["L"], r["theta"]): r["wins"] / r["games"] for r in rows}
        tl = {(r["L"], r["theta"]): r["fail_tiles_left"] for r in rows}
        sec = sum(r["sec"] for r in rows) / sum(r["games"] for r in rows)
        thetas = sorted({t for _, t in rate})
        if any((L, t) not in rate for L in levels for t in thetas):
            continue
        # mixtures: single θ, all 2-point and 3-point equal-weight mixes over the grid
        import itertools
        mixes = [(t,) for t in thetas] + list(itertools.combinations(thetas, 2)) + list(itertools.combinations(thetas, 3))

        def pred(mix, L):
            return sum(rate[(L, t)] for t in mix) / len(mix)

        games = {(r["L"], r["theta"]): r["games"] for r in rows}

        def tol_hit(mix, L, v):
            # bot Wilson 95% interval overlaps the AF tolerant range
            n = sum(games[(L, t)] for t in mix)
            lo, hi = wilson(round(v * n), n)
            return hi >= lb_lo[L] - 1e-9 and lo <= ub_hi[L] + 1e-9

        def stats(mix, lv):
            pr = [pred(mix, L) for L in lv]
            return {"rho_mid": spearman(pr, [mid[L] for L in lv]), "rho_pt": spearman(pr, [pt[L] for L in lv]),
                    "rho_lb": spearman(pr, [lb[L] for L in lv]),
                    "hit": sum(1 for L, v in zip(lv, pr) if lb[L] - 1e-9 <= v <= ub[L] + 1e-9) / len(lv),
                    "hit_tol": sum(1 for L, v in zip(lv, pr) if tol_hit(mix, L, v)) / len(lv),
                    "mae_mid": sum(abs(v - mid[L]) for L, v in zip(lv, pr)) / len(lv)}

        allst = {"+".join(map(str, m)): stats(m, levels) for m in mixes}
        single = {k: v for k, v in allst.items() if "+" not in k}
        best_hit = max(allst.items(), key=lambda kv: (kv[1]["hit_tol"], kv[1]["hit"], -kv[1]["mae_mid"]))
        best_rho = max(allst.items(), key=lambda kv: kv[1]["rho_mid"])
        # 2-fold CV over many random half splits: fit (max hit, tie → min MAE) on half A, evaluate on half B
        rng = random.Random(1414)
        cv_hit, cv_hit_strict, cv_rho, cv_rho_fit = [], [], [], []
        for _ in range(200):
            lv = levels[:]
            rng.shuffle(lv)
            A, B = lv[: len(lv) // 2], lv[len(lv) // 2:]
            sA = {m: stats(m, A) for m in mixes}
            fitted = max(mixes, key=lambda m: (sA[m]["hit_tol"], sA[m]["hit"], -sA[m]["mae_mid"]))
            sB = stats(fitted, B)
            cv_hit.append(sB["hit_tol"])
            cv_hit_strict.append(sB["hit"])
            fitted_r = max(mixes, key=lambda m: sA[m]["rho_mid"])
            cv_rho.append(stats(fitted_r, B)["rho_mid"])
            cv_rho_fit.append(sA[fitted_r]["rho_mid"])
        bm = tuple(float(x) for x in best_hit[0].split("+"))
        per_level = {L: {"bot": round(pred(bm, L), 3), "lb": lb[L], "ub": ub[L], "clean_ft": pt[L],
                         "resid_mid": round(pred(bm, L) - mid[L], 3), "tol_hit": tol_hit(bm, L, pred(bm, L)), "curve": {t: round(rate[(L, t)], 3) for t in thetas}}
                     for L in levels}
        # tiles left on fail at the best-hit mixture (pooled over its θs) vs AF
        tl_cmp = {}
        for L in levels:
            v = [x for t in bm for x in tl[(L, t)]]
            afd = af[L]["fail_tiles_left"]
            tl_cmp[L] = {"bot_n": len(v), "bot_p25": q(v, .25), "bot_p50": q(v, .5), "bot_p75": q(v, .75),
                         "af_n": afd.get("n", 0), "af_p25": afd.get("p25"), "af_p50": afd.get("p50"), "af_p75": afd.get("p75")}
        rep["versions"][ver] = {
            "sec_per_game": round(sec, 4), "thetas": thetas, "single": single,
            "best_hit": {"mix": best_hit[0], **best_hit[1]}, "best_rho": {"mix": best_rho[0], **best_rho[1]},
            "cv": {"splits": 200, "hit_tol_mean": round(sum(cv_hit) / 200, 3), "hit_strict_mean": round(sum(cv_hit_strict) / 200, 3), "hit_p10": q(cv_hit, .1), "hit_p90": q(cv_hit, .9),
                   "rho_test_mean": round(sum(cv_rho) / 200, 3), "rho_test_p10": round(q(cv_rho, .1), 3),
                   "rho_train_mean": round(sum(cv_rho_fit) / 200, 3)},
            "per_level": per_level, "tiles_left": tl_cmp,
        }
    # AF self-consistency reference: Spearman between AF measures
    rep["af_internal"] = {"rho_pt_lb": spearman([pt[L] for L in levels], [lb[L] for L in levels]),
                          "rho_pt_mid": spearman([pt[L] for L in levels], [mid[L] for L in levels])}
    save("report.json", rep)
    print(json.dumps({k: v for k, v in rep.items() if k != "versions"}, ensure_ascii=False))
    for ver, v in rep["versions"].items():
        print(ver, json.dumps({k: v[k] for k in ("sec_per_game", "best_hit", "best_rho", "cv")}, ensure_ascii=False))
        print(ver, "single", json.dumps({k: {kk: round(vv, 3) for kk, vv in s.items()} for k, s in v["single"].items()}))


def cmd_extras(a):
    """Robustness: ρ on the non-trivial subset (L≥13), bootstrap CI of ρ(v2)−ρ(v1), residuals, tiles_left."""
    rep = load(OUT / "report.json")
    af = {int(k): v for k, v in load(OUT / "af_L1_31.json").items()}
    levels = rep["levels"]
    mid = {L: (af[L]["unaided_clear_lower_bound"] + af[L]["unaided_clear_upper_bound"]) / 2 for L in levels}
    rate = {}
    for ver in ("v1", "v2"):
        for r in load(OUT / f"bot_{ver}.json")["rows"]:
            rate[(ver, r["L"], r["theta"])] = r["wins"] / r["games"]
    thetas = [0.0, 0.15, 0.29, 0.4, 0.47, 0.55, 0.65, 0.75, 0.85, 1.0]
    sub = [L for L in levels if L >= 13]
    out = {"subset_L13plus": {}, "bootstrap": {}}
    for ver in ("v1", "v2"):
        out["subset_L13plus"][ver] = {t: round(spearman([rate[(ver, L, t)] for L in sub], [mid[L] for L in sub]), 3)
                                      for t in thetas}
    rng = random.Random(7)
    for t in thetas:
        for name, lv in (("all", levels), ("L13plus", sub)):
            d = []
            for _ in range(2000):
                s = [rng.choice(lv) for _ in lv]
                y = [mid[L] for L in s]
                if len(set(y)) < 2:
                    continue
                r1 = spearman([rate[("v1", L, t)] for L in s], y)
                r2 = spearman([rate[("v2", L, t)] for L in s], y)
                if r1 == r1 and r2 == r2:
                    d.append(r2 - r1)
            d.sort()
            out["bootstrap"][f"{name}|{t}"] = {"mean": round(sum(d) / len(d), 3), "ci95": [round(q(d, .025), 3), round(q(d, .975), 3)]}
    # θ where the bot mean matches the AF mean (calibrated point) per version
    afm = sum(mid[L] for L in levels) / len(levels)
    out["af_mean_mid"] = round(afm, 3)
    out["bot_mean"] = {ver: {t: round(sum(rate[(ver, L, t)] for L in levels) / len(levels), 3) for t in thetas}
                       for ver in ("v1", "v2")}
    save("extras.json", out)
    print(json.dumps(out, ensure_ascii=False))


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("af").set_defaults(f=cmd_af)
    sub.add_parser("maps").set_defaults(f=cmd_maps)
    p = sub.add_parser("run")
    p.add_argument("--ver", required=True)
    p.add_argument("--levels", default="")
    p.add_argument("--grid", default="")
    p.set_defaults(f=cmd_run)
    sub.add_parser("report").set_defaults(f=cmd_report)
    sub.add_parser("extras").set_defaults(f=cmd_extras)
    a = ap.parse_args()
    a.f(a)


if __name__ == "__main__":
    main()
