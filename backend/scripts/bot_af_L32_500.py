"""Bot skill axis vs real users (AF), L32~500 — 15_bot_vs_af_L32_500.md (14_ method extended).

Sub-commands (results under data/pv_sandbox/af_calibration/bot_compare_L32_500/):
  prep            Maps + level rows from the build shards (game repo, git show only): 1.1.0/iOS 2.1.0 = b741f6a3,
                  1.0.162 = a2229a5d. Per level: played map (b741f6a3), whether 1.0.162 played the same map/row,
                  layout mode (fixed vs runtime-random: t0 or count-only containers), gimmick features, exclusions.
  af              AF first-try unaided metrics. Levels whose 1.0.162 shard map/row differs from 1.1.0 → recomputed
                  with android 1.1.0 + iOS 2.1.0 runs only; otherwise level_metrics.json (all versions) as is.
  run --ver v1|v2 [--grid ..] [--games N]
                  θ grid × games. Fixed layout: N games. Random layout: LAYOUTS sampled client layouts
                  (ShuffleEmptyTiles port, seeds 1..LAYOUTS) × N/LAYOUTS games.
  report          rank correlation (overall / segment / within gimmick block), range hit (tolerant/strict), MAE,
                  fits (single θ, 2-point mix, per-segment θ), 2-fold CV, gimmick residuals, tiles_left, fail reasons,
                  per-segment user θ estimate → report.json

Shared core untouched; workers <= 5.
"""
from __future__ import annotations

import argparse
import hashlib
import itertools
import json
import os
import random
import subprocess
import sys
import time
from collections import Counter
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

BACKEND = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND))
sys.path.insert(0, str(BACKEND / "scripts"))

from bot_af_L1_31 import q, spearman  # noqa: E402

OUT = BACKEND / "data/pv_sandbox/af_calibration/bot_compare_L32_500"
AF_JSON = BACKEND / "data/pv_sandbox/af_calibration/level_metrics.json"
GAME_REPO = "/Users/casualdev/sp_meowsgarden"
SHARD_110, SHARD_162 = "b741f6a3", "a2229a5d"
WORKERS = min(5, int(os.environ.get("PV_WORKERS", "5")))
LO, HI = 32, 500
LAYOUTS = 32
GAMES = 128
GRID = {"v1": (0.15, 0.29, 0.40, 0.47, 0.55, 0.65, 0.75, 0.85, 1.0),
        "v2": (0.15, 0.29, 0.40, 0.47, 0.55, 0.65, 0.75, 0.85, 1.0)}
SEGMENTS = ((32, 100), (101, 300), (301, 500))
SAME_SHARD_VERSIONS = {("android", "1.1.0"), ("ios", "2.1.0")}
ROW_KEYS = ("randSeed", "useTileCount", "unlockTile", "shuffleTile", "typeImbalance", "autoCollectCount", "timea", "layer")


def load(p):
    with open(p, encoding="utf-8") as f:
        return json.load(f)


def save(name, obj):
    OUT.mkdir(parents=True, exist_ok=True)
    tmp = OUT / (name + ".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, separators=(",", ":"))
    os.replace(tmp, OUT / name)


def seg_of(L):
    for lo, hi in SEGMENTS:
        if lo <= L <= hi:
            return f"{lo}-{hi}"
    return None


# ── prep ────────────────────────────────────────────────────────────────────────────────────────
def _git_key(commit, key):
    from pv_scan_shards import decrypt_shard_file
    p = f"Assets/StreamingAssets/GBoost/a{hashlib.md5(key.encode()).hexdigest()}.txt"
    r = subprocess.run(["git", "-C", GAME_REPO, "show", f"{commit}:{p}"], capture_output=True)
    if r.returncode != 0:
        raise RuntimeError(f"git show failed: {commit} {key}")
    return decrypt_shard_file(r.stdout)


def _shard(commit):
    maps = {}
    for i in range((HI - 1) // 100 + 1):
        maps.update(_git_key(commit, f"levelmap_level_{i}"))
    tab = _git_key(commit, "levels")
    keys = tab["__keys"]
    rows = {}
    for v in tab["__vals"]:
        o = {keys[i]: v[i] for i in range(min(len(keys), len(v)))}
        rows[str(o.get("id"))] = o
    return maps, rows


def _canon_hash(m):
    from app.core.pv.canonical import canonical_map
    return hashlib.sha256(json.dumps(canonical_map(m), separators=(",", ":")).encode()).hexdigest()


def features(m):
    """Gimmick / structure features of a map (board tiles; container counts include inner tiles)."""
    f = Counter()
    for k, v in m.items():
        if not (k.startswith("layer_") and isinstance(v, dict)):
            continue
        tiles = v.get("tiles") or {}
        if not isinstance(tiles, dict):
            continue
        for t in tiles.values():
            tid = str(t[0])
            f["tiles"] += 1
            if tid.startswith("stack"):
                f["stack"] += 1
            elif tid.startswith("craft"):
                f["craft"] += 1
            elif tid in ("t16", "key"):
                f["key"] += 1
            elif tid == "t0":
                f["t0"] += 1
            eff = str(t[1]) if len(t) > 1 and t[1] else ""
            if eff:
                base = eff.split("_")[0]
                f["eff_" + base] += 1
    return dict(f)


def layout_mode(m):
    from app.core.pv.cs_shuffle import build_level_model, get_empty_tile_list
    import copy
    return "random" if get_empty_tile_list(build_level_model(copy.deepcopy(m))) else "fixed"


def cmd_prep(a):
    m110, r110 = _shard(SHARD_110)
    m162, r162 = _shard(SHARD_162)
    af = {x["level"]: x for x in load(AF_JSON)["levels"]}
    out = {}
    for L in range(LO, HI + 1):
        key = f"level_{L}"
        m, row = m110[key], r110[key]
        row_s = {k: row.get(k) for k in ROW_KEYS}
        same162 = (key in m162 and _canon_hash(m162[key]) == _canon_hash(m)
                   and {k: r162.get(key, {}).get(k) for k in ROW_KEYS} == row_s)
        x = af[L]
        excl = None
        if int(float(row.get("autoCollectCount") or 0)) > 0:
            excl = "cat_help"
        elif (x["ft_booster_rate"] or 0) >= 0.5 and (x["ft_revive_rate"] or 0) < 0.05:
            excl = "booster_tutorial"
        elif float(row.get("timea") or 0) > 0:
            excl = "time_limit"
        out[L] = {"row": row_s, "map": m, "same162": same162, "map_match_editor": x["map_match"],
                  "mode": layout_mode(m), "features": features(m), "exclude": excl}
    save("prep.json", out)
    c = Counter((v["exclude"], v["mode"], v["same162"]) for v in out.values())
    print(c)
    print("excluded:", {L: v["exclude"] for L, v in out.items() if v["exclude"]})


# ── AF ──────────────────────────────────────────────────────────────────────────────────────────
AF_KEYS = ("clean_ft_n", "clean_ft_rate", "clean_ft_ci95", "unaided_clear_lower_bound", "unaided_clear_upper_bound",
           "first_try_ended", "ft_booster_rate", "ft_revive_rate", "ft_help_rate", "fail_tiles_left", "fail_reason",
           "is_boss", "is_gimmick_first")


def cmd_af(a):
    prep = {int(k): v for k, v in load(OUT / "prep.json").items()}
    full = {x["level"]: x for x in load(AF_JSON)["levels"]}
    need = [L for L, v in prep.items() if not v["same162"]]
    sub = {}
    if need:
        import af_level_metrics as am
        per_dev, _ = am.load_events(am.AF_DATA)
        runs, *_ = am.build_runs(per_dev)
        del per_dev
        am.mark_first_try(runs)
        need_s = set(need)
        by = {}
        for r in runs:
            if not r["infinite"] and r["L"] in need_s and (r["plat"], r["ver"]) in SAME_SHARD_VERSIONS:
                by.setdefault(r["L"], []).append(r)
        for L in need:
            sub[L] = am.level_block(by.get(L, []))
    out = {}
    for L in prep:
        b = sub.get(L, full[L])
        o = {k: b.get(k) for k in AF_KEYS}
        o["is_boss"], o["is_gimmick_first"] = full[L]["is_boss"], full[L]["is_gimmick_first"]
        o["versions_used"] = "all" if L not in sub else "1.1.0+ios2.1.0"
        out[L] = o
    save("af.json", out)
    print(f"af: {len(out)} levels, recomputed (1.1.0+iOS only) {len(sub)}: {sorted(sub)}")


# ── bot runs ────────────────────────────────────────────────────────────────────────────────────
_PREP = None


def _prep():
    global _PREP
    if _PREP is None:
        _PREP = {int(k): v for k, v in load(OUT / "prep.json").items()}
    return _PREP


def level_layouts(entry, n_layouts):
    from app.core.pv.cs_shuffle import resolve_map, shuffle_empty_tiles
    from app.core.pv.t0ize import bot_level_json
    row = entry["row"]
    if entry["mode"] == "fixed":
        return [bot_level_json({"randSeed": row.get("randSeed") or 1, "useTileCount": row.get("useTileCount"),
                                "unlockTile": row.get("unlockTile") or 0}, entry["map"])]
    out = []
    for s in range(1, n_layouts + 1):
        res = shuffle_empty_tiles(entry["map"], rand_seed=s, use_tile_count=row["useTileCount"],
                                  unlock_tile=row.get("unlockTile") or 0, shuffle_tile=row.get("shuffleTile") or 0,
                                  type_imbalance=row.get("typeImbalance") or 0, strict=True)
        out.append(bot_level_json({"randSeed": s, "useTileCount": row["useTileCount"],
                                   "unlockTile": row.get("unlockTile") or 0}, resolve_map(entry["map"], res)))
    return out


def fail_reason(bot, s):
    if not s.failed:
        return "clear" if s.cleared else "unfinished"
    if bot._is_dock_full(s):
        return "Normal"
    if any(v <= 0 for v in s.bomb_tiles.values()):
        return "Bomb"
    if bot._check_grass_impossible(s):
        return "Grass"
    if bot._check_ice_impossible(s):
        return "Ice"
    if bot._check_chain_impossible(s):
        return "Chain"
    if s.moves_used >= s.max_moves:
        return "MaxMoves"
    return "NoMoves"


def run_task(args):
    from app.core.bot_simulator import BotSimulator
    from app.core.mc_difficulty import make_skill_profile
    t0 = time.time()
    entry = _prep()[args["L"]]
    games = args["games"]
    n_lay = min(LAYOUTS, games) if entry["mode"] == "random" else 1
    lays = level_layouts(entry, n_lay)
    per = games // len(lays)
    prof = make_skill_profile(args["theta"], args["ver"])
    bot = BotSimulator()
    wins, left, reasons, n = 0, [], Counter(), 0
    for li, lj in enumerate(lays):
        total = int(lj["max_moves"]) - 50
        base = bot._create_initial_state(lj, int(lj["max_moves"]))
        bot._precompute_blocking_map(base)
        for g in range(per):
            bot._rng.seed(11_000_000 + li * 1000 + g)
            final = bot._play_game(bot._fast_copy_state(base), prof)
            n += 1
            if final.cleared:
                wins += 1
            else:
                left.append(total - final.total_tiles_cleared)
                reasons[fail_reason(bot, final)] += 1
    return {"L": args["L"], "theta": args["theta"], "ver": args["ver"], "games": n, "wins": wins,
            "layouts": len(lays), "fail_tiles_left": left, "fail_reasons": dict(reasons), "sec": time.time() - t0}


def cmd_run(a):
    name = f"bot_{a.ver}.json"
    path = OUT / name
    done = load(path) if path.exists() else {"rows": []}
    have = {(r["L"], r["theta"]) for r in done["rows"]}
    prep = _prep()
    levels = [L for L, v in sorted(prep.items()) if not v["exclude"]]
    grid = [float(x) for x in a.grid.split(",")] if a.grid else GRID[a.ver]
    todo = [{"L": L, "theta": th, "ver": a.ver, "games": a.games} for th in grid for L in levels if (L, th) not in have]
    # heavy levels first spread: interleave by level so workers stay balanced
    t0 = time.time()
    with ProcessPoolExecutor(WORKERS) as ex:
        for r in ex.map(run_task, todo, chunksize=1):
            done["rows"].append(r)
            if time.time() - t0 > 30:
                save(name, done)
                t0 = time.time()
    save(name, done)
    print(f"run {a.ver}: rows={len(done['rows'])} todo_was={len(todo)}")


# ── report ──────────────────────────────────────────────────────────────────────────────────────
GIMMICKS = ("stack", "craft", "key", "eff_ice", "eff_chain", "eff_grass", "eff_bomb", "eff_curtain",
            "eff_teleporter", "eff_frog", "eff_link", "eff_unknown")


def block_of(feat):
    """Gimmick block used for within-block rank correlation: the effect gimmick(s) present."""
    effs = sorted(k[4:] for k in feat if k.startswith("eff_"))
    return "+".join(effs) if effs else "none"


def cmd_report(a):
    from af_level_metrics import wilson
    prep = {int(k): v for k, v in load(OUT / "prep.json").items()}
    af = {int(k): v for k, v in load(OUT / "af.json").items()}
    min_n = a.min_n
    levels = [L for L in sorted(prep) if not prep[L]["exclude"] and (af[L]["clean_ft_n"] or 0) >= min_n
              and af[L]["unaided_clear_lower_bound"] is not None]
    lb = {L: af[L]["unaided_clear_lower_bound"] for L in levels}
    ub = {L: af[L]["unaided_clear_upper_bound"] for L in levels}
    mid = {L: (lb[L] + ub[L]) / 2 for L in levels}
    pt = {L: af[L]["clean_ft_rate"] for L in levels}
    nft = {L: af[L]["first_try_ended"] for L in levels}
    lb_lo = {L: wilson(round(lb[L] * nft[L]), nft[L])[0] for L in levels}
    ub_hi = {L: wilson(round(ub[L] * nft[L]), nft[L])[1] for L in levels}
    seg = {L: seg_of(L) for L in levels}
    blk = {L: block_of(prep[L]["features"]) for L in levels}
    rep = {"min_n": min_n, "levels": len(levels),
           "excluded": {str(L): v["exclude"] for L, v in prep.items() if v["exclude"]},
           "excluded_low_n": [L for L in sorted(prep) if not prep[L]["exclude"] and L not in levels],
           "segments": {s: sum(1 for L in levels if seg[L] == s) for s in (f"{a}-{b}" for a, b in SEGMENTS)},
           "blocks": dict(Counter(blk.values()).most_common()),
           "af_internal": {"rho_pt_mid": spearman([pt[L] for L in levels], [mid[L] for L in levels])},
           "af_mean_mid": {s: round(sum(mid[L] for L in levels if seg[L] == s) / max(1, sum(1 for L in levels if seg[L] == s)), 4)
                           for s in (f"{a}-{b}" for a, b in SEGMENTS)},
           "versions": {}}
    rep["af_mean_mid"]["all"] = round(sum(mid.values()) / len(mid), 4)
    seg_names = [f"{a}-{b}" for a, b in SEGMENTS]

    for ver in ("v1", "v2"):
        p = OUT / f"bot_{ver}.json"
        if not p.exists():
            continue
        rows = load(p)["rows"]
        rate = {(r["L"], r["theta"]): r["wins"] / r["games"] for r in rows}
        games = {(r["L"], r["theta"]): r["games"] for r in rows}
        thetas = sorted({t for (L, t) in rate if L in mid})
        thetas = [t for t in thetas if all((L, t) in rate for L in levels)]
        if not thetas:
            continue
        # fits only over θ measured with the full game count: a θ with fewer games (θ1.2: 32) has a wider bot
        # Wilson interval and would win the tolerant hit by noise alone. Per-θ tables below still list every θ.
        fit_thetas = [t for t in thetas if min(games[(L, t)] for L in levels) >= GAMES]
        mixes = [(t,) for t in fit_thetas] + list(itertools.combinations(fit_thetas, 2))

        def pred(mix, L):
            return sum(rate[(L, t)] for t in mix) / len(mix)

        def tol(mix, L, v):
            n = sum(games[(L, t)] for t in mix)
            lo, hi = wilson(round(v * n), n)
            return hi >= lb_lo[L] - 1e-9 and lo <= ub_hi[L] + 1e-9

        def stats(mix_of, lv):
            """mix_of: L -> mix (allows per-segment θ)."""
            pr = [pred(mix_of(L), L) for L in lv]
            return {"rho_mid": spearman(pr, [mid[L] for L in lv]), "rho_pt": spearman(pr, [pt[L] for L in lv]),
                    "hit": sum(1 for L, v in zip(lv, pr) if lb[L] - 1e-9 <= v <= ub[L] + 1e-9) / len(lv),
                    "hit_tol": sum(1 for L, v in zip(lv, pr) if tol(mix_of(L), L, v)) / len(lv),
                    "mae": sum(abs(v - mid[L]) for L, v in zip(lv, pr)) / len(lv)}

        def r3(d):
            return {k: round(v, 3) for k, v in d.items()}

        def fit_key(s):
            return (s["hit_tol"], s["hit"], -s["mae"])

        # rank correlation per θ: overall, per segment, within blocks (blocks with >= 10 levels), pooled within-block
        single = {}
        for t in thetas:
            d = {"all": r3(stats(lambda L, t=t: (t,), levels))}
            for s in seg_names:
                lv = [L for L in levels if seg[L] == s]
                d[s] = r3(stats(lambda L, t=t: (t,), lv))
            wb = {}
            for b, cnt in Counter(blk[L] for L in levels).items():
                lv = [L for L in levels if blk[L] == b]
                if cnt >= 10:
                    wb[b] = {"n": cnt, "rho": round(spearman([rate[(L, t)] for L in lv], [mid[L] for L in lv]), 3)}
            tot = sum(v["n"] for v in wb.values())
            d["within_block"] = wb
            d["within_block_weighted_rho"] = round(sum(v["n"] * v["rho"] for v in wb.values() if v["rho"] == v["rho"]) / tot, 3) if tot else None
            # within segment × block
            single[str(t)] = d
        # fits
        best_single = max(fit_thetas, key=lambda t: fit_key(stats(lambda L: (t,), levels)))
        best_mix = max(mixes, key=lambda m: fit_key(stats(lambda L: m, levels)))
        seg_theta = {s: max(fit_thetas, key=lambda t: fit_key(stats(lambda L: (t,), [L for L in levels if seg[L] == s])))
                     for s in seg_names}
        fits = {"single": {"theta": best_single, **r3(stats(lambda L: (best_single,), levels))},
                "mix2": {"mix": list(best_mix), **r3(stats(lambda L: best_mix, levels))},
                "per_segment": {"theta": seg_theta, **r3(stats(lambda L: (seg_theta[seg[L]],), levels)),
                                "by_segment": {s: r3(stats(lambda L: (seg_theta[s],), [L for L in levels if seg[L] == s]))
                                               for s in seg_names}}}
        # user θ estimate per segment: θ where segment mean bot rate == segment mean AF mid (linear interpolation)
        theta_est = {}
        for s in seg_names + ["all"]:
            lv = levels if s == "all" else [L for L in levels if seg[L] == s]
            target = sum(mid[L] for L in lv) / len(lv)
            curve = [(t, sum(rate[(L, t)] for L in lv) / len(lv)) for t in thetas]
            est = None
            for (t1, y1), (t2, y2) in zip(curve, curve[1:]):
                if (y1 - target) * (y2 - target) <= 0 and y1 != y2:
                    est = round(t1 + (target - y1) * (t2 - t1) / (y2 - y1), 3)
                    break
            theta_est[s] = {"target_mid": round(target, 4), "theta": est,
                            "curve": {str(t): round(y, 4) for t, y in curve}}
        # 2-fold CV (200 random half splits): single θ, 2-mix, per-segment θ
        rng = random.Random(1500)
        cv = {"single": [], "mix2": [], "per_segment": [], "rho_single_test": []}
        cache = {}
        for _ in range(200):
            lv = levels[:]
            rng.shuffle(lv)
            A, B = lv[: len(lv) // 2], lv[len(lv) // 2:]
            sa = {m: stats(lambda L, m=m: m, A) for m in mixes}
            ts = max(fit_thetas, key=lambda t: fit_key(sa[(t,)]))
            cv["single"].append(stats(lambda L: (ts,), B))
            mm = max(mixes, key=lambda m: fit_key(sa[m]))
            cv["mix2"].append(stats(lambda L: mm, B))
            st = {s: max(fit_thetas, key=lambda t: fit_key(stats(lambda L: (t,), [L for L in A if seg[L] == s] or A)))
                  for s in seg_names}
            cv["per_segment"].append(stats(lambda L: (st[seg[L]],), B))
            tr = max(fit_thetas, key=lambda t: sa[(t,)]["rho_mid"])
            cv["rho_single_test"].append(stats(lambda L: (tr,), B)["rho_mid"])
        cv_sum = {}
        for k in ("single", "mix2", "per_segment"):
            v = cv[k]
            cv_sum[k] = {m: round(sum(x[m] for x in v) / len(v), 3) for m in ("hit_tol", "hit", "mae", "rho_mid")}
            cv_sum[k]["hit_tol_p10"] = round(q([x["hit_tol"] for x in v], .1), 3)
            cv_sum[k]["hit_tol_p90"] = round(q([x["hit_tol"] for x in v], .9), 3)
        cv_sum["rho_test_best_rho_theta"] = round(sum(cv["rho_single_test"]) / 200, 3)
        # residuals at per-segment θ by gimmick
        fitted = {L: pred((seg_theta[seg[L]],), L) for L in levels}
        resid = {L: fitted[L] - mid[L] for L in levels}
        gim = {}
        for g in GIMMICKS:
            has = [L for L in levels if prep[L]["features"].get(g, 0) > 0]
            if len(has) < 3:
                continue
            no = [L for L in levels if prep[L]["features"].get(g, 0) == 0]
            first = min(L for L in sorted(prep) if prep[L]["features"].get(g, 0) > 0)
            gim[g] = {"n": len(has), "first_level": first,
                      "mean_resid": round(sum(resid[L] for L in has) / len(has), 4),
                      "mean_resid_without": round(sum(resid[L] for L in no) / max(1, len(no)), 4),
                      "hit_tol": round(sum(1 for L in has if tol((seg_theta[seg[L]],), L, fitted[L])) / len(has), 3),
                      "share_bot_harder": round(sum(1 for L in has if resid[L] < 0) / len(has), 3)}
        for nm, cond in (("boss", lambda L: af[L]["is_boss"]), ("gimmick_first", lambda L: af[L]["is_gimmick_first"]),
                         ("random_layout", lambda L: prep[L]["mode"] == "random"),
                         ("map_mismatch_editor", lambda L: prep[L]["map_match_editor"] == "mismatch")):
            has = [L for L in levels if cond(L)]
            if has:
                gim[nm] = {"n": len(has), "levels": has if len(has) <= 30 else None,
                           "mean_resid": round(sum(resid[L] for L in has) / len(has), 4),
                           "hit_tol": round(sum(1 for L in has if tol((seg_theta[seg[L]],), L, fitted[L])) / len(has), 3)}
        top_resid = sorted(levels, key=lambda L: -abs(resid[L]))[:25]
        # tiles left & fail reasons per segment at per-segment θ
        tl, fr = {}, {}
        for s in seg_names:
            lv = [L for L in levels if seg[L] == s]
            t = seg_theta[s]
            diffs = []
            for L in lv:
                r = next(x for x in rows if x["L"] == L and x["theta"] == t)
                afd = af[L]["fail_tiles_left"] or {}
                if len(r["fail_tiles_left"]) >= 10 and (afd.get("n") or 0) >= 10:
                    diffs.append(q(r["fail_tiles_left"], .5) - afd["p50"])
            tl[s] = {"levels": len(diffs), "median_diff_p50": q(diffs, .5), "share_bot_more": round(sum(1 for d in diffs if d > 0) / max(1, len(diffs)), 3)}
            bc, ac = Counter(), Counter()
            for L in lv:
                r = next(x for x in rows if x["L"] == L and x["theta"] == t)
                bc.update(r["fail_reasons"])
                for k, v in (af[L]["fail_reason"] or {}).items():
                    ac[k.replace("_CantRevive", "") or "unknown"] += v
            bt, at = sum(bc.values()) or 1, sum(ac.values()) or 1
            fr[s] = {"bot": {k: round(v / bt, 3) for k, v in bc.most_common()}, "af": {k: round(v / at, 3) for k, v in ac.most_common()},
                     "bot_n": sum(bc.values()), "af_n": sum(ac.values())}
        sec = sum(r["sec"] for r in rows) / sum(r["games"] for r in rows)
        rep["versions"][ver] = {
            "thetas": thetas, "fit_thetas": fit_thetas, "sec_per_game": round(sec, 4), "single": single, "fits": fits, "theta_est": theta_est,
            "cv": cv_sum, "gimmick_resid": gim,
            "top_resid": [{"L": L, "seg": seg[L], "block": blk[L], "bot": round(fitted[L], 3), "lb": lb[L], "ub": ub[L],
                           "resid": round(resid[L], 3), "feat": prep[L]["features"], "boss": af[L]["is_boss"]} for L in top_resid],
            "tiles_left": tl, "fail_reasons": fr,
            "per_level": {str(L): {"fit": round(fitted[L], 3), "mid": round(mid[L], 4), "resid": round(resid[L], 3)} for L in levels},
        }
    save("report.json", rep)
    print(json.dumps({k: v for k, v in rep.items() if k != "versions"}, ensure_ascii=False)[:1500])
    for ver, v in rep["versions"].items():
        print(ver, json.dumps({"fits": v["fits"], "cv": v["cv"], "theta_est": {s: x["theta"] for s, x in v["theta_est"].items()}}, ensure_ascii=False))


def cmd_calib(a):
    """Monotone calibration: logit(AF mid) = a + b·logit(bot rate at θ), fit on half / test on half (200 splits).
    Compared with the no-bot baseline (segment mean of AF mid). tolAF = prediction inside [Wilson lo of LB, Wilson hi
    of UB] (AF noise only — a calibrated prediction has no bot binomial width)."""
    import math
    from af_level_metrics import wilson
    prep = {int(k): v for k, v in load(OUT / "prep.json").items()}
    af = {int(k): v for k, v in load(OUT / "af.json").items()}
    lv = [L for L in sorted(prep) if not prep[L]["exclude"] and (af[L]["clean_ft_n"] or 0) >= a.min_n]
    lb = {L: af[L]["unaided_clear_lower_bound"] for L in lv}
    ub = {L: af[L]["unaided_clear_upper_bound"] for L in lv}
    mid = {L: (lb[L] + ub[L]) / 2 for L in lv}
    n = {L: af[L]["first_try_ended"] for L in lv}
    lo = {L: wilson(round(lb[L] * n[L]), n[L])[0] for L in lv}
    hi = {L: wilson(round(ub[L] * n[L]), n[L])[1] for L in lv}

    def lg(p):
        p = min(max(p, 0.01), 0.99)
        return math.log(p / (1 - p))

    def fit(A, x):
        xs, ys = [lg(x[L]) for L in A], [lg(mid[L]) for L in A]
        mx, my = sum(xs) / len(xs), sum(ys) / len(ys)
        b = sum((u - mx) * (v - my) for u, v in zip(xs, ys)) / max(1e-9, sum((u - mx) ** 2 for u in xs))
        c = my - b * mx
        return lambda L: 1 / (1 + math.exp(-(c + b * lg(x[L]))))

    def score(pred, B):
        return (sum(lb[L] <= pred(L) <= ub[L] for L in B) / len(B), sum(lo[L] <= pred(L) <= hi[L] for L in B) / len(B),
                sum(abs(pred(L) - mid[L]) for L in B) / len(B))

    def cv(make):
        rng, res = random.Random(3), []
        for _ in range(200):
            s = lv[:]
            rng.shuffle(s)
            A, B = s[: len(s) // 2], s[len(s) // 2:]
            res.append(score(make(A), B))
        return {k: round(sum(r[i] for r in res) / len(res), 3) for i, k in enumerate(("strict", "tolAF", "mae"))}

    out = {"levels": len(lv)}

    def seg_mean(A):
        m = {s: [mid[L] for L in A if seg_of(L) == s] for s in (f"{x}-{y}" for x, y in SEGMENTS)}
        m = {s: sum(v) / len(v) for s, v in m.items() if v}
        return lambda L: m[seg_of(L)]
    out["baseline_segment_mean"] = cv(seg_mean)
    for ver in ("v1", "v2"):
        p = OUT / f"bot_{ver}.json"
        if not p.exists():
            continue
        rate = {(r["L"], r["theta"]): r["wins"] / r["games"] for r in load(p)["rows"]}
        out[ver] = {}
        for t in sorted({t for _, t in rate}):
            if not all((L, t) in rate for L in lv):
                continue
            x = {L: rate[(L, t)] for L in lv}
            out[ver][str(t)] = cv(lambda A, x=x: fit(A, x))
    save("calib.json", out)
    print(json.dumps(out, ensure_ascii=False))


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("prep").set_defaults(f=cmd_prep)
    sub.add_parser("af").set_defaults(f=cmd_af)
    p = sub.add_parser("run")
    p.add_argument("--ver", required=True)
    p.add_argument("--grid", default="")
    p.add_argument("--games", type=int, default=GAMES)
    p.set_defaults(f=cmd_run)
    p = sub.add_parser("report")
    p.add_argument("--min-n", type=int, default=100)
    p.set_defaults(f=cmd_report)
    p = sub.add_parser("calib")
    p.add_argument("--min-n", type=int, default=100)
    p.set_defaults(f=cmd_calib)
    a = ap.parse_args()
    a.f(a)


if __name__ == "__main__":
    main()
