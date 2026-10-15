"""Bot v2.4 (hidden-type info parity + cat-help policy) evaluation — 26_bot_v24.md.

Base = v2.3 (all parity items + chain_aware). Results: data/pv_sandbox/af_calibration/bot_v24/.
  item   --name NAME --v24 ITEMS --levels FEATURE[,..] [--thetas ..] [--games N] [--psavvy P]
         v2.4 with ONLY the listed v2.4 items on the levels containing any listed feature ('cat' = cat-help levels).
         Compared with v2.3 rows of the same (level, θ) and seeds (bot_v23/bot_v2.3.json; cat levels: cat_v23 item).
  ver23  --name NAME --levels ..       v2.3 rows (baseline for levels/θ not in bot_v2.3.json, e.g. cat levels)
  full   [--grid ..] [--games N]       v2.4 with all items, all comparison levels (θ grid) → v24_rows.json
  verify                               re-run v2.3 on stored (L, θ) rows and check exact equality
  isum                                 per-item summary vs v2.3 (relative MAE, within-group ρ, fail shares)
  catfit                               p_savvy fit on the cat levels (naive / savvy rows, linear mixture)
  assemble                             bot_v2.4.json (+ copies of v1/v2/v2.1/v2.3 inputs)
Workers <= 3.
"""
from __future__ import annotations

import argparse
import json
import os
import random
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
import bot_v23_eval as v23  # noqa: E402

V23_OUT = v23.OUT
OUT = BACKEND / "data/pv_sandbox/af_calibration/bot_v24"
WORKERS = min(3, int(os.environ.get("PV_WORKERS", "3")))
GRID = "0.47,0.55,0.65,0.75,0.85,1.0"


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
    """Same as bot_v23_eval.run_task (same seeds) plus bot_version / v2.4 items / p_savvy."""
    import dataclasses
    from app.core.bot_simulator import BotSimulator, V21_AWARENESS_DEFAULTS
    from app.core.mc_difficulty import make_skill_profile
    t0 = time.time()
    P, _ = v21.prep()
    entry = P[args["L"]]
    games = args["games"]
    ver = args.get("ver", "v2.4")
    n_lay = min(base.LAYOUTS, games) if entry["mode"] == "random" else 1
    lays = base.level_layouts(entry, n_lay)
    per = games // len(lays)
    prof = make_skill_profile(args["theta"], ver)
    cfg = dict(prof.gimmick_awareness)
    cfg.update(v21.FIXED)
    cfg["alpha"], cfg["gamma"] = dict(V21_AWARENESS_DEFAULTS["alpha"]), dict(V21_AWARENESS_DEFAULTS["gamma"])
    cfg["exposure"] = args["exposure"]
    cfg["parity"] = None
    cfg["auto_collect"] = int(float(entry["row"].get("autoCollectCount") or 0))
    if ver == "v2.4":
        cfg["v24"] = args.get("v24")
        if args.get("psavvy") is not None:
            cfg["ac_p_savvy"] = args["psavvy"]
    prof = dataclasses.replace(prof, gimmick_awareness=cfg)
    bot = BotSimulator()
    wins, left, left_board, reasons, n = 0, [], [], Counter(), 0
    for li, lj in enumerate(lays):
        total = int(lj["max_moves"]) - 50
        bot.set_rule_parity(prof)
        st0 = bot._create_initial_state(lj, int(lj["max_moves"]))
        bot._precompute_blocking_map(st0)
        for g in range(per):
            bot._rng.seed(11_000_000 + li * 1000 + g)
            final = bot._play_game(bot._fast_copy_state(st0), prof)
            n += 1
            if final.cleared:
                wins += 1
            else:
                rem = total - final.total_tiles_cleared
                left.append(rem)
                left_board.append(rem - len(final.dock_tiles))
                reasons[base.fail_reason(bot, final)] += 1
    return {"L": args["L"], "theta": args["theta"], "ver": ver, "games": n, "wins": wins, "layouts": len(lays),
            "fail_tiles_left": left, "fail_tiles_left_board": left_board, "fail_reasons": dict(reasons),
            "parity": None, "v24": args.get("v24"), "psavvy": args.get("psavvy"), "sec": time.time() - t0}


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


def _expo():
    return {int(k): v for k, v in load(v21.OUT / "exposure.json").items()}


def _items(s):
    return None if s is None else [x for x in s.split(",") if x]


def cmd_item(a):
    ex = _expo()
    lv = v23.levels_with([f for f in a.levels.split(",") if f])
    tasks = [{"L": L, "theta": float(t), "games": a.games, "exposure": ex[L], "v24": _items(a.v24),
              "psavvy": a.psavvy} for t in a.thetas.split(",") for L in lv]
    d = _pool_run(tasks, f"item_{a.name}.json", lambda r: (r["L"], r["theta"]))
    print(f"item {a.name}: rows={len(d['rows'])} levels={len(lv)}")


def cmd_ver23(a):
    ex = _expo()
    lv = v23.levels_with([f for f in a.levels.split(",") if f])
    tasks = [{"L": L, "theta": float(t), "games": a.games, "exposure": ex[L], "ver": "v2.3"}
             for t in a.thetas.split(",") for L in lv]
    d = _pool_run(tasks, f"v23_{a.name}.json", lambda r: (r["L"], r["theta"]))
    print(f"v2.3 {a.name}: rows={len(d['rows'])}")


def cmd_full(a):
    ex = _expo()
    P, _ = v21.prep()
    stored = load(V23_OUT / "bot_v2.3.json")["rows"]
    lv = sorted({r["L"] for r in stored})
    tasks = [{"L": L, "theta": float(t), "games": a.games, "exposure": ex[L], "v24": None}
             for t in a.grid.split(",") for L in lv]
    d = _pool_run(tasks, "v24_rows.json", lambda r: (r["L"], r["theta"]))
    print(f"full v2.4 rows={len(d['rows'])}")


def cmd_verify(a):
    """Exact reproduction of stored v2.3 rows (bot_v23/bot_v2.3.json) with this code."""
    ex = _expo()
    stored = {(r["L"], r["theta"]): r for r in load(V23_OUT / "bot_v2.3.json")["rows"]}
    rng = random.Random(24)
    keys = rng.sample(sorted(stored), a.n)
    tasks = [{"L": L, "theta": t, "games": stored[(L, t)]["games"], "exposure": ex[L], "ver": "v2.3"} for L, t in keys]
    ok = 0
    with ProcessPoolExecutor(WORKERS) as ex_:
        for t, r in zip(tasks, ex_.map(run_task, tasks, chunksize=1)):
            s = stored[(t["L"], t["theta"])]
            same = (r["wins"] == s["wins"] and r["fail_reasons"] == s["fail_reasons"]
                    and r["fail_tiles_left"] == s["fail_tiles_left"])
            ok += same
            print(t["L"], t["theta"], "OK" if same else f"DIFF {r['wins']} vs {s['wins']}")
    print(f"verify v2.3: {ok}/{len(tasks)} identical")


def _mid(A, L):
    return (A[L]["unaided_clear_lower_bound"] + A[L]["unaided_clear_upper_bound"]) / 2


def _af_fail(A, L):
    c = Counter()
    for k, v in (A[L]["fail_reason"] or {}).items():
        c[k.replace("_CantRevive", "")] += v
    return c


def group_metrics(rows_by_L, Ls, seg_af, seg_bot, A, share_keys=("Chain", "Bomb", "Grass", "Ice", "Normal")):
    """Relative MAE as in 19 §6 (segment AF mean + bot − segment bot mean of plain levels), bias, ρ, fail shares."""
    from bot_af_L1_31 import spearman
    pred = {L: seg_af[base.seg_of(L)] + rows_by_L[L]["wins"] / rows_by_L[L]["games"] - seg_bot[base.seg_of(L)]
            for L in Ls}
    bc, ac = Counter(), Counter()
    for L in Ls:
        bc.update(rows_by_L[L]["fail_reasons"])
        ac.update(_af_fail(A, L))
    nb, na = max(1, sum(bc.values())), max(1, sum(ac.values()))
    return {"n": len(Ls),
            "mae_rel": round(sum(abs(pred[L] - _mid(A, L)) for L in Ls) / len(Ls), 4),
            "bias_rel": round(sum(pred[L] - _mid(A, L) for L in Ls) / len(Ls), 4),
            "rate": round(sum(rows_by_L[L]["wins"] / rows_by_L[L]["games"] for L in Ls) / len(Ls), 4),
            "rho": round(spearman([rows_by_L[L]["wins"] / rows_by_L[L]["games"] for L in Ls],
                                  [_mid(A, L) for L in Ls]), 3) if len(Ls) > 2 else None,
            "share_bot": {k: round(bc[k] / nb, 3) for k in share_keys},
            "share_af": {k: round(ac[k] / na, 3) for k in share_keys}}


def seg_refs(rows_t, A, P):
    """Segment means over plain levels (no chain/bomb/grass), as in bot_v23_eval.cmd_chainfit."""
    lv_all = v21.levels_of()
    plain = [L for L in lv_all if not any(P[L]["features"].get(f, 0) for f in ("eff_chain", "eff_bomb", "eff_grass"))
             and L in rows_t]
    seg_af, seg_bot = {}, {}
    for lo, hi in base.SEGMENTS:
        G = [L for L in plain if lo <= L <= hi]
        s = f"{lo}-{hi}"
        seg_af[s] = sum(_mid(A, L) for L in G) / len(G)
        seg_bot[s] = sum(rows_t[L]["wins"] / rows_t[L]["games"] for L in G) / len(G)
    return seg_af, seg_bot


def cmd_isum(a):
    P, A = v21.prep()
    b23 = {}
    for r in load(V23_OUT / "bot_v2.3.json")["rows"]:
        b23.setdefault(r["theta"], {})[r["L"]] = r
    for f in sorted(OUT.glob("v23_*.json")):
        for r in load(f)["rows"]:
            b23.setdefault(r["theta"], {}).setdefault(r["L"], r)
    out = {}
    for f in sorted(OUT.glob("item_*.json")):
        name = f.stem[5:]
        by_t = {}
        for r in load(f)["rows"]:
            if A[r["L"]]["unaided_clear_lower_bound"] is not None:
                by_t.setdefault(r["theta"], {})[r["L"]] = r
        res = {}
        for t, rs in sorted(by_t.items()):
            Ls = sorted(L for L in rs if L in b23.get(t, {}))
            seg_af, seg_bot = seg_refs(b23[t], A, P)
            after = dict(b23[t])
            after.update(rs)
            seg_bot_after = seg_refs(after, A, P)[1]
            changed = sum(1 for L in Ls if rs[L]["wins"] != b23[t][L]["wins"] or rs[L]["fail_reasons"] != b23[t][L]["fail_reasons"])
            res[str(t)] = {"changed_levels": changed,
                           "before": group_metrics(b23[t], Ls, seg_af, seg_bot, A),
                           "after": group_metrics(rs, Ls, seg_af, seg_bot_after, A),
                           "sec_per_game_after": round(sum(rs[L]["sec"] for L in Ls) / sum(rs[L]["games"] for L in Ls), 4)}
        out[name] = res
    save("item_summary.json", out)
    for name, res in out.items():
        for t, m in res.items():
            b, af = m["before"], m["after"]
            print(f"{name:16s} θ{t} n={b['n']} changed={m['changed_levels']} rate {b['rate']}→{af['rate']} "
                  f"maeRel {b['mae_rel']}→{af['mae_rel']} bias {b['bias_rel']}→{af['bias_rel']} ρ {b['rho']}→{af['rho']}")


def cmd_catfit(a):
    """p_savvy: naive = v2.4 without ac_policy (item cat_naive), savvy = ac_policy with p=1 (item cat_savvy).
    Mixture rate = p·savvy + (1−p)·naive per level. Loss = MAE vs AF mid; absolute at each θ and segment-relative."""
    from bot_af_L1_31 import spearman
    P, A = v21.prep()
    nv = {(r["L"], r["theta"]): r for r in load(OUT / "item_cat_naive.json")["rows"]}
    sv = {(r["L"], r["theta"]): r for r in load(OUT / "item_cat_savvy.json")["rows"]}
    b23 = {}
    for r in load(V23_OUT / "bot_v2.3.json")["rows"]:
        b23.setdefault(r["theta"], {})[r["L"]] = r
    thetas = sorted({t for _, t in nv})
    Ls = sorted({L for L, _ in nv})
    segs = [f"{lo}-{hi}" for lo, hi in base.SEGMENTS]
    grid = [i / 20 for i in range(21)]
    out = {"levels": len(Ls), "af_mid_mean": round(sum(_mid(A, L) for L in Ls) / len(Ls), 4), "by_theta": {}}
    for t in thetas:
        seg_af, seg_bot = seg_refs(b23[t], A, P) if t in b23 else (None, None)
        rn = {L: nv[(L, t)]["wins"] / nv[(L, t)]["games"] for L in Ls}
        rs = {L: sv[(L, t)]["wins"] / sv[(L, t)]["games"] for L in Ls}

        def ev(p, G, rel):
            pr = {L: p * rs[L] + (1 - p) * rn[L] for L in G}
            if rel:
                pr = {L: seg_af[base.seg_of(L)] + pr[L] - seg_bot[base.seg_of(L)] for L in G}
            return (sum(abs(pr[L] - _mid(A, L)) for L in G) / len(G), sum(pr[L] - _mid(A, L) for L in G) / len(G),
                    spearman([pr[L] for L in G], [_mid(A, L) for L in G]))
        res = {"naive_rate": round(sum(rn.values()) / len(Ls), 4), "savvy_rate": round(sum(rs.values()) / len(Ls), 4)}
        for rel in (False, True):
            if rel and seg_af is None:
                continue
            tag = "rel" if rel else "abs"
            best = min(grid, key=lambda p: ev(p, Ls, rel)[0])
            m0, m1, mb = ev(0.0, Ls, rel), ev(1.0, Ls, rel), ev(best, Ls, rel)
            res[tag] = {"p_best": best, "mae_naive": round(m0[0], 4), "mae_savvy": round(m1[0], 4),
                        "mae_best": round(mb[0], 4), "bias_best": round(mb[1], 4), "rho_naive": round(m0[2], 3),
                        "rho_best": round(mb[2], 3)}
            seg_p = {}
            for s in segs:
                G = [L for L in Ls if base.seg_of(L) == s]
                bp = min(grid, key=lambda p: ev(p, G, rel)[0])
                seg_p[s] = {"n": len(G), "p_best": bp, "mae_best": round(ev(bp, G, rel)[0], 4),
                            "mae_naive": round(ev(0.0, G, rel)[0], 4), "mae_savvy": round(ev(1.0, G, rel)[0], 4)}
            res[tag]["by_segment"] = seg_p
            # 2-fold CV of a single global p
            rng, cv = random.Random(26), []
            for _ in range(200):
                sh = Ls[:]
                rng.shuffle(sh)
                tr, te = sh[: len(sh) // 2], sh[len(sh) // 2:]
                bp = min(grid, key=lambda p: ev(p, tr, rel)[0])
                cv.append((ev(bp, te, rel)[0], ev(0.0, te, rel)[0], bp))
            res[tag]["cv_mae_best"] = round(sum(c[0] for c in cv) / len(cv), 4)
            res[tag]["cv_mae_naive"] = round(sum(c[1] for c in cv) / len(cv), 4)
            res[tag]["cv_p_mean"] = round(sum(c[2] for c in cv) / len(cv), 3)
        out["by_theta"][str(t)] = res
    save("cat_fit.json", out)
    print(json.dumps(out, ensure_ascii=False, indent=1))


def cmd_assemble(a):
    rows = load(OUT / "v24_rows.json")["rows"]
    save("bot_v2.4.json", {"rows": rows})
    for f in ("bot_v2.3.json", "bot_v2.1.json", "prep.json", "af.json", "bot_v1.json", "bot_v2.json"):
        if (V23_OUT / f).exists():
            shutil.copyfile(V23_OUT / f, OUT / f)
    print(f"assembled v2.4 rows={len(rows)}")


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("item"); p.add_argument("--name", required=True); p.add_argument("--levels", default="")
    p.add_argument("--v24", default=None, help="comma list of v2.4 items (default all); '' = none")
    p.add_argument("--thetas", default="0.65,1.0"); p.add_argument("--games", type=int, default=128)
    p.add_argument("--psavvy", type=float, default=None)
    p.set_defaults(f=cmd_item)
    p = sub.add_parser("ver23"); p.add_argument("--name", required=True); p.add_argument("--levels", default="")
    p.add_argument("--thetas", default="0.65,1.0"); p.add_argument("--games", type=int, default=128)
    p.set_defaults(f=cmd_ver23)
    p = sub.add_parser("full"); p.add_argument("--grid", default=GRID); p.add_argument("--games", type=int, default=128)
    p.set_defaults(f=cmd_full)
    p = sub.add_parser("verify"); p.add_argument("--n", type=int, default=6); p.set_defaults(f=cmd_verify)
    sub.add_parser("isum").set_defaults(f=cmd_isum)
    sub.add_parser("catfit").set_defaults(f=cmd_catfit)
    sub.add_parser("assemble").set_defaults(f=cmd_assemble)
    a = ap.parse_args()
    a.f(a)


if __name__ == "__main__":
    main()
