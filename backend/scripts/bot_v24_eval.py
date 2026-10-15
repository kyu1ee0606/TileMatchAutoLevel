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
        cfg["v24_expo"] = _gc_expo(P)[args["L"]]
        cfg["v24"] = args.get("v24")
        if args.get("psavvy") is not None:
            cfg["ac_p_savvy"] = args["psavvy"]
        if args.get("cmem") is not None:
            cfg["curtain_mem"] = args["cmem"]
        if args.get("beta") is not None:
            cfg["beta"] = args["beta"]
        for k in ("extra",):                      # free-form v2.4 behaviour params (dict) for later items
            if args.get(k):
                cfg.update(args[k])
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
            "parity": None, "v24": args.get("v24"), "psavvy": args.get("psavvy"), "cmem": args.get("cmem"),
            "beta": args.get("beta"), "extra": args.get("extra"), "sec": time.time() - t0}


_GC = {}


def _gc_expo(P):
    """Levels before L (all levels incl. cat-help) whose map has grass / chain — v2.4 gc_naive learning."""
    if not _GC:
        cnt = Counter()
        for L in sorted(P):
            _GC[L] = {"grass": cnt["grass"], "chain": cnt["chain"]}
            for g, f in (("grass", "eff_grass"), ("chain", "eff_chain")):
                if P[L]["features"].get(f, 0) > 0:
                    cnt[g] += 1
    return _GC


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
        if name == "summary":
            continue
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


CMEM_ITEMS = ["unknown_hide", "curtain_hide", "unknown_nobonus", "curtain_memory_v24"]
CMEM_A = (-2.0, 0.0, 2.0, 4.0, 8.0)
CMEM_C = (0.0, 0.5, 1.5)


def cmd_cmemgrid(a):
    """curtain_memory_v24 calibration: θ=1.0, 64 games, curtain levels, a × c (b fixed 4); base = no memory."""
    ex = _expo()
    lv = v23.levels_with(["eff_curtain"])
    tasks = [{"L": L, "theta": 1.0, "games": 64, "exposure": ex[L], "v24": CMEM_ITEMS[:3], "cmem": None} for L in lv]
    tasks += [{"L": L, "theta": 1.0, "games": 64, "exposure": ex[L], "v24": CMEM_ITEMS,
               "cmem": {"a": ca, "b": 4.0, "c": cc}} for ca in CMEM_A for cc in CMEM_C for L in lv]
    key = lambda r: (r["L"], None if r.get("cmem") is None else (r["cmem"]["a"], r["cmem"]["c"]))
    d = _pool_run(tasks, "cmem_grid.json", key)
    print(f"cmemgrid rows={len(d['rows'])}")


BETA_GRID = (0.0, 1.0, 2.0, 4.0, 6.0)


def cmd_betagrid(a):
    """bomb awareness θ-slope β: bomb levels, θ ∈ {0.65, 0.85}, 64 games, β grid (all other v2.4 items on)."""
    ex = _expo()
    lv = v23.levels_with(["eff_bomb"])
    tasks = [{"L": L, "theta": t, "games": 64, "exposure": ex[L], "v24": None, "beta": b}
             for b in BETA_GRID for t in (0.65, 0.85) for L in lv]
    d = _pool_run(tasks, "beta_grid.json", lambda r: (r["L"], r["theta"], r["beta"]))
    print(f"betagrid rows={len(d['rows'])}")


def cmd_betafit(a):
    """2-fold CV (200): loss = mean over θ{0.65,0.85} of relative MAE (segment refs = v2.4 rows at that θ)."""
    from bot_af_L1_31 import spearman
    P, A = v21.prep()
    refs = {}
    rows24 = load(OUT / "bot_v2.4.json")["rows"]
    for t in (0.65, 0.85):
        refs[t] = seg_refs({r["L"]: r for r in rows24 if r["theta"] == t}, A, P)
    by = {}
    for r in load(OUT / "beta_grid.json")["rows"]:
        by.setdefault(r["beta"], {}).setdefault(r["theta"], {})[r["L"]] = r
    lv = sorted(L for L in by[4.0][0.85] if A[L]["unaided_clear_lower_bound"] is not None)

    def met(b, ls, t):
        rs = by[b][t]
        sa, sb = refs[t]
        rate = {L: rs[L]["wins"] / rs[L]["games"] for L in ls}
        return {"mae_rel": sum(abs(sa[base.seg_of(L)] + rate[L] - sb[base.seg_of(L)] - _mid(A, L)) for L in ls) / len(ls),
                "bias_rel": sum(sa[base.seg_of(L)] + rate[L] - sb[base.seg_of(L)] - _mid(A, L) for L in ls) / len(ls),
                "resid": sum(rate[L] - _mid(A, L) for L in ls) / len(ls),
                "rho": spearman([rate[L] for L in ls], [_mid(A, L) for L in ls])}
    loss = lambda b, ls: sum(met(b, ls, t)["mae_rel"] for t in (0.65, 0.85)) / 2
    grid = {str(b): {str(t): {k: round(v, 4) for k, v in met(b, lv, t).items()} for t in (0.65, 0.85)} for b in by}
    rng, res, picks = random.Random(27), [], Counter()
    for _ in range(200):
        sh = lv[:]
        rng.shuffle(sh)
        tr, te = sh[: len(sh) // 2], sh[len(sh) // 2:]
        best = min(by, key=lambda b: loss(b, tr))
        picks[best] += 1
        res.append((loss(best, te), loss(4.0, te)))
    out = {"levels": len(lv), "grid": grid, "cv_loss_best": round(sum(r[0] for r in res) / 200, 4),
           "cv_loss_beta4": round(sum(r[1] for r in res) / 200, 4), "picks": {str(k): v for k, v in picks.most_common()},
           "chosen": min(by, key=lambda b: loss(b, lv))}
    save("beta_fit.json", out)
    print(json.dumps(out, ensure_ascii=False, indent=1))


def cmd_cmem085(a):
    """θ0.85 check (64 games): no memory vs forgetful (a −2) vs near-perfect memory (a 8), c 0."""
    ex = _expo()
    lv = v23.levels_with(["eff_curtain"])
    tasks = [{"L": L, "theta": 0.85, "games": 64, "exposure": ex[L], "v24": CMEM_ITEMS[:3], "cmem": None} for L in lv]
    tasks += [{"L": L, "theta": 0.85, "games": 64, "exposure": ex[L], "v24": CMEM_ITEMS,
               "cmem": {"a": ca, "b": 4.0, "c": 0.0}} for ca in (-2.0, 8.0) for L in lv]
    key = lambda r: (r["L"], None if r.get("cmem") is None else (r["cmem"]["a"], r["cmem"]["c"]))
    d = _pool_run(tasks, "cmem_grid085.json", key)
    print(f"cmem085 rows={len(d['rows'])}")


def cmd_cmemfit(a):
    """2-fold CV (200) over curtain levels: loss = relative MAE (segment refs from v2.4 full rows, θ1.0)."""
    from bot_af_L1_31 import spearman
    P, A = v21.prep()
    b24 = {r["L"]: r for r in load(OUT / "v24_rows.json")["rows"] if r["theta"] == 1.0}
    seg_af, seg_bot = seg_refs(b24, A, P)
    by = {}
    for r in load(OUT / "cmem_grid.json")["rows"]:
        k = "none" if r.get("cmem") is None else f"{r['cmem']['a']},{r['cmem']['c']}"
        by.setdefault(k, {})[r["L"]] = r
    lv = sorted(L for L in by["none"] if A[L]["unaided_clear_lower_bound"] is not None)

    def met(rs, ls):
        rate = {L: rs[L]["wins"] / rs[L]["games"] for L in ls}
        pred = {L: seg_af[base.seg_of(L)] + rate[L] - seg_bot[base.seg_of(L)] for L in ls}
        return {"mae_rel": sum(abs(pred[L] - _mid(A, L)) for L in ls) / len(ls),
                "resid": sum(rate[L] - _mid(A, L) for L in ls) / len(ls),
                "rate": sum(rate.values()) / len(ls),
                "rho": spearman([rate[L] for L in ls], [_mid(A, L) for L in ls])}
    grid = {k: met(v, lv) for k, v in by.items()}
    rng, res, picks = random.Random(26), [], Counter()
    cands = [k for k in by if k != "none"]
    for _ in range(200):
        sh = lv[:]
        rng.shuffle(sh)
        tr, te = sh[: len(sh) // 2], sh[len(sh) // 2:]
        best = min(cands, key=lambda k: met(by[k], tr)["mae_rel"])
        picks[best] += 1
        res.append((met(by[best], te), met(by["none"], te)))
    cv = {k: round(sum(r[0][k] for r in res) / 200, 4) for k in ("mae_rel", "resid", "rho")}
    cv0 = {k: round(sum(r[1][k] for r in res) / 200, 4) for k in ("mae_rel", "resid", "rho")}
    best_all = min(cands, key=lambda k: grid[k]["mae_rel"])
    out = {"levels": len(lv), "grid": {k: {x: round(y, 4) for x, y in m.items()} for k, m in grid.items()},
           "cv_memory": cv, "cv_none": cv0, "picks": dict(picks.most_common(5)), "chosen": best_all}
    save("cmem_fit.json", out)
    print(json.dumps({k: v for k, v in out.items() if k != "grid"}, ensure_ascii=False, indent=1))
    for k, m in sorted(grid.items()):
        print("  ", k, {x: round(y, 3) for x, y in m.items()})


GIM_FEAT = {"grass": "eff_grass", "bomb": "eff_bomb", "chain": "eff_chain", "teleporter": "eff_teleporter",
            "frog": "eff_frog", "ice": "eff_ice", "stack": "stack", "craft": "craft", "curtain": "eff_curtain",
            "unknown": "eff_unknown", "link": "eff_link"}
GIM_FAIL = {"grass": "Grass", "bomb": "Bomb", "chain": "Chain", "ice": "Ice"}   # others: Normal (dock overflow)


def _gim_stats(rows_t, Ls, seg_af, seg_bot, A, reason):
    from bot_af_L1_31 import spearman
    rate = {L: rows_t[L]["wins"] / rows_t[L]["games"] for L in Ls}
    res = [rate[L] - _mid(A, L) for L in Ls]
    rel = [abs(seg_af[base.seg_of(L)] + rate[L] - seg_bot[base.seg_of(L)] - _mid(A, L)) for L in Ls]
    bc, ac = Counter(), Counter()
    for L in Ls:
        bc.update(rows_t[L]["fail_reasons"])
        ac.update(_af_fail(A, L))
    return {"rho": spearman([rate[L] for L in Ls], [_mid(A, L) for L in Ls]) if len(Ls) > 2 else float("nan"),
            "resid": sum(res) / len(Ls), "mae_rel": sum(rel) / len(Ls),
            "share_bot": bc[reason] / max(1, sum(bc.values())), "share_af": ac[reason] / max(1, sum(ac.values()))}


def cmd_gimtab(a):
    """Per-gimmick v2.3 → v2.4 table; paired level bootstrap (+ binomial redraw of changed levels' bot wins)
    for Δρ, Δ|resid|, ΔMAE_rel → 95% CI excludes 0 → 개선/악화, else 동일."""
    P, A = v21.prep()
    b23, b24 = {}, {}
    for r in load(V23_OUT / "bot_v2.3.json")["rows"]:
        b23.setdefault(r["theta"], {})[r["L"]] = r
    for r in load(OUT / a.v24file)["rows"]:
        b24.setdefault(r["theta"], {})[r["L"]] = r
    cat23 = load(OUT / "v23_cat.json")["rows"]
    cat24 = load(OUT / a.cat24)["rows"] if (OUT / a.cat24).exists() else []
    lv = v21.levels_of()
    groups = {g: [L for L in lv if P[L]["features"].get(f, 0) > 0] for g, f in GIM_FEAT.items()}
    rng = random.Random(2024)
    out = {}
    for t in [float(x) for x in a.thetas.split(",")]:
        s23, s24 = seg_refs(b23[t], A, P), seg_refs(b24[t], A, P)
        c23 = {r["L"]: r for r in cat23 if r["theta"] == t}
        c24 = {r["L"]: r for r in cat24 if r["theta"] == t}
        rows_out = {}
        todo = list(groups.items()) + ([("냥이의 도움", sorted(c24))] if c24 else [])
        for g, Ls in todo:
            R23, R24 = (c23, c24) if g == "냥이의 도움" else (b23[t], b24[t])
            Ls = [L for L in Ls if L in R23 and L in R24 and A[L]["unaided_clear_lower_bound"] is not None]
            reason = GIM_FAIL.get(g, "Normal")
            m23 = _gim_stats(R23, Ls, *s23, A, reason)
            m24 = _gim_stats(R24, Ls, *s24, A, reason)
            d = {"rho": [], "absres": [], "mae": []}
            changed = [L for L in Ls if R23[L]["wins"] != R24[L]["wins"]]
            for _ in range(a.boot):
                bs = [rng.choice(Ls) for _ in Ls]
                # 봇 표본 잡음: 결과가 바뀐 레벨은 두 버전의 승수를 각각 이항 재추출(같은 결과면 차이 0 그대로)
                P23, P24 = dict(R23), dict(R24)
                for L in changed:
                    for R, PP in ((R23, P23), (R24, P24)):
                        ng, nw = R[L]["games"], R[L]["wins"]
                        PP[L] = dict(R[L], wins=sum(1 for _ in range(ng) if rng.random() < nw / ng))
                x23, x24 = _gim_stats(P23, bs, *s23, A, reason), _gim_stats(P24, bs, *s24, A, reason)
                d["rho"].append(x24["rho"] - x23["rho"])
                d["absres"].append(abs(x24["resid"]) - abs(x23["resid"]))
                d["mae"].append(x24["mae_rel"] - x23["mae_rel"])
            ci = {}
            for k, v in d.items():
                v = sorted(x for x in v if x == x)
                ci[k] = (v[int(0.025 * len(v))], v[int(0.975 * len(v)) - 1]) if v else (0, 0)

            def verdict(k, better_if_positive):
                lo, hi = ci[k]
                if lo > 0:
                    return "개선" if better_if_positive else "악화"
                if hi < 0:
                    return "악화" if better_if_positive else "개선"
                return "동일"
            rows_out[g] = {"n": len(Ls), "v23": m23, "v24": m24, "ci": ci,
                           "verdict": {"rho": verdict("rho", True), "absres": verdict("absres", False),
                                       "mae": verdict("mae", False)}}
        out[str(t)] = rows_out
    save(a.out, out)
    for t, rows_out in out.items():
        print(f"## θ{t}")
        print("| 기믹 | n | ρ v2.3→v2.4 | 잔차 v2.3→v2.4 | 상대MAE v2.3→v2.4 | 실패비중 봇 v2.3→v2.4 (AF) | 판정 ρ/잔차/MAE |")
        print("|---|---|---|---|---|---|---|")
        for g, m in rows_out.items():
            a3, a4, v = m["v23"], m["v24"], m["verdict"]
            print(f"| {g} | {m['n']} | {a3['rho']:.2f}→{a4['rho']:.2f} | {a3['resid']:+.3f}→{a4['resid']:+.3f} | "
                  f"{a3['mae_rel']:.3f}→{a4['mae_rel']:.3f} | {a3['share_bot']:.2f}→{a4['share_bot']:.2f} "
                  f"({a3['share_af']:.2f}, {GIM_FAIL.get(g, 'Normal')}) | {v['rho']}/{v['absres']}/{v['mae']} |")


def cmd_final(a):
    """Final v2.4 (V24_DEFAULT + fitted params) on all comparison levels, θ list, 128 games → v24f_rows.json."""
    ex = _expo()
    stored = load(V23_OUT / "bot_v2.3.json")["rows"]
    lv = sorted({r["L"] for r in stored})
    items = None
    if a.drop:
        items = [x for x in _default_items() if x not in a.drop.split(",")]
    tasks = [{"L": L, "theta": float(t), "games": 128, "exposure": ex[L], "v24": items} for t in a.thetas.split(",") for L in lv]
    tag = f"_no_{a.drop.replace(',', '_')}" if a.drop else ""
    d = _pool_run(tasks, f"v24f{tag}_rows.json", lambda r: (r["L"], r["theta"]))
    save(f"bot_v2.4f{tag}.json", {"rows": d["rows"]})
    print(f"final v2.4 rows={len(d['rows'])}")


def cmd_curtfull(a):
    """Re-measure curtain levels (θ grid, 128 games) with the final v2.4 (incl. curtain_memory_v24)."""
    ex = _expo()
    lv = v23.levels_with(["eff_curtain"])
    tasks = [{"L": L, "theta": float(t), "games": 128, "exposure": ex[L], "v24": None} for t in GRID.split(",") for L in lv]
    d = _pool_run(tasks, "v24_curtain_rows.json", lambda r: (r["L"], r["theta"]))
    print(f"curtain v2.4 rows={len(d['rows'])}")


def _boot_cmp(R0, R1, Ls, s0, s1, A, reason, boot, rng):
    """Paired level bootstrap + binomial redraw of changed levels → verdicts for Δρ, Δ|resid|, ΔMAE_rel."""
    m0, m1 = _gim_stats(R0, Ls, *s0, A, reason), _gim_stats(R1, Ls, *s1, A, reason)
    changed = [L for L in Ls if R0[L]["wins"] != R1[L]["wins"]]
    d = {"rho": [], "absres": [], "mae": []}
    for _ in range(boot):
        bs = [rng.choice(Ls) for _ in Ls]
        P0, P1 = dict(R0), dict(R1)
        for L in changed:
            for R, PP in ((R0, P0), (R1, P1)):
                ng, nw = R[L]["games"], R[L]["wins"]
                PP[L] = dict(R[L], wins=sum(1 for _ in range(ng) if rng.random() < nw / ng))
        x0, x1 = _gim_stats(P0, bs, *s0, A, reason), _gim_stats(P1, bs, *s1, A, reason)
        d["rho"].append(x1["rho"] - x0["rho"])
        d["absres"].append(abs(x1["resid"]) - abs(x0["resid"]))
        d["mae"].append(x1["mae_rel"] - x0["mae_rel"])
    out = {}
    for k, v in d.items():
        v = sorted(x for x in v if x == x)
        lo, hi = (v[int(0.025 * len(v))], v[int(0.975 * len(v)) - 1]) if v else (0, 0)
        pos_good = k == "rho"
        out[k] = ("개선" if pos_good else "악화") if lo > 0 else (("악화" if pos_good else "개선") if hi < 0 else "동일")
    return m0, m1, out, len(changed)


def _default_items():
    from app.core.bot_simulator import V24_DEFAULT
    return list(V24_DEFAULT)


def cmd_bgrid(a):
    """Behaviour item grid: v2.4 default (+ fixed --extra-items) + ITEM with param P ∈ values; value 'off' = item off.
    Levels = feature list (row_unlock / cat / eff_* / stack). 64 games, θ list."""
    ex = _expo()
    if a.levels == "sample3":                      # 일반 행동 항목: 비교 410레벨 중 매 3번째(137레벨)
        lv = v21.levels_of()[::3]
    else:
        lv = v23.levels_with([f for f in a.levels.split(",") if f])
    base_items = _default_items() + [x for x in a.extra_items.split(",") if x]
    fixed = json.loads(a.fixed) if a.fixed else {}
    tasks = []
    for val in a.values.split(","):
        items = list(base_items) + ([] if val == "off" else [a.item])
        par = dict(fixed)
        if val != "off":
            par[a.param] = float(val)
        for t in a.thetas.split(","):
            for L in lv:
                tasks.append({"L": L, "theta": float(t), "games": a.games, "exposure": ex[L], "v24": items,
                              "extra": {"v24_par": par}, "val": val})
    d = _pool_run(tasks, f"bg_{a.name}.json", lambda r: (r["L"], r["theta"], r.get("val") or "off"))
    print(f"bgrid {a.name}: rows={len(d['rows'])} levels={len(lv)}")


def cmd_bfit(a):
    """2-fold CV (200) over levels: loss = mean_θ relative MAE (+ share_w·|fail share − AF| for --reason)."""
    from bot_af_L1_31 import spearman
    P, A = v21.prep()
    rows24 = load(OUT / "bot_v2.4.json")["rows"]
    by = {}
    rows = load(OUT / f"bg_{a.name}.json")["rows"]
    base_n = min(len(r.get("v24") or []) for r in rows)

    def val_of(r):                                   # rows don't store 'val' → item present ⇒ its single v24_par value
        if len(r.get("v24") or []) == base_n:
            return "off"
        par = ((r.get("extra") or {}).get("v24_par") or {})
        return ",".join(f"{v:g}" for k, v in sorted(par.items()) if k not in (a.fixed_keys or "").split(",")) or "on"
    for r in rows:
        by.setdefault(val_of(r), {}).setdefault(r["theta"], {})[r["L"]] = r
    thetas = sorted(next(iter(by.values())))
    refs = {t: seg_refs({r["L"]: r for r in rows24 if r["theta"] == t}, A, P) for t in thetas}
    lv = sorted(L for L in by["off"][thetas[0]] if A[L]["unaided_clear_lower_bound"] is not None)

    def self_refs(v, t):
        """Segment refs from this value's own rows: plain levels (no chain/bomb/grass) among the measured levels;
        a segment with no plain level falls back to all measured levels (= within-group centering)."""
        rs = by[v][t]
        sa, sb = {}, {}
        for lo, hi in base.SEGMENTS:
            sname = f"{lo}-{hi}"
            seg = [L for L in lv if lo <= L <= hi]
            G = [L for L in seg if not any(P[L]["features"].get(f, 0) for f in ("eff_chain", "eff_bomb", "eff_grass"))] or seg
            if G:
                sa[sname] = sum(_mid(A, L) for L in G) / len(G)
                sb[sname] = sum(rs[L]["wins"] / rs[L]["games"] for L in G) / len(G)
        return sa, sb

    def met(v, ls, t):
        rs = by[v][t]
        sa, sb = self_refs(v, t) if a.refs == "self" else refs[t]
        rate = {L: rs[L]["wins"] / rs[L]["games"] for L in ls}
        bc, ac = Counter(), Counter()
        for L in ls:
            bc.update(rs[L]["fail_reasons"])
            ac.update(_af_fail(A, L))
        return {"mae_rel": sum(abs(sa[base.seg_of(L)] + rate[L] - sb[base.seg_of(L)] - _mid(A, L)) for L in ls) / len(ls),
                "resid": sum(rate[L] - _mid(A, L) for L in ls) / len(ls),
                "rate": sum(rate.values()) / len(ls),
                "rho": spearman([rate[L] for L in ls], [_mid(A, L) for L in ls]),
                "share_bot": bc[a.reason] / max(1, sum(bc.values())), "share_af": ac[a.reason] / max(1, sum(ac.values()))}

    def loss(v, ls):
        ms = [met(v, ls, t) for t in thetas]
        return sum(m["mae_rel"] + a.share_w * abs(m["share_bot"] - m["share_af"]) for m in ms) / len(ms)
    grid = {v: {str(t): {k: round(x, 4) for k, x in met(v, lv, t).items()} for t in thetas} for v in by}
    rng, res, picks = random.Random(31), [], Counter()
    for _ in range(200):
        sh = lv[:]
        rng.shuffle(sh)
        tr, te = sh[: len(sh) // 2], sh[len(sh) // 2:]
        best = min(by, key=lambda v: loss(v, tr))
        picks[best] += 1
        res.append((loss(best, te), loss("off", te)))
    out = {"levels": len(lv), "thetas": thetas, "grid": grid, "cv_loss_fit": round(sum(r[0] for r in res) / 200, 4),
           "cv_loss_off": round(sum(r[1] for r in res) / 200, 4),
           "cv_win_rate": round(sum(1 for r in res if r[0] < r[1]) / 200, 3),
           "picks": dict(picks.most_common()), "chosen": min(by, key=lambda v: loss(v, lv))}
    save(f"bfit_{a.name}_{a.refs}.json", out)
    print(json.dumps({k: v for k, v in out.items() if k != "grid"}, ensure_ascii=False))
    for v, m in grid.items():
        print("  ", v, " | ".join(f"θ{t}: rate {x['rate']:.3f} ρ {x['rho']:.3f} res {x['resid']:+.3f} mae {x['mae_rel']:.3f} "
                                  f"share {x['share_bot']:.2f}/{x['share_af']:.2f}" for t, x in m.items()))


def cmd_cmp(a):
    """Compare an item's rows with a baseline rows file on its levels (θ each), with bootstrap verdicts."""
    P, A = v21.prep()
    full = {}
    for r in load(OUT / "bot_v2.4.json")["rows"]:
        full.setdefault(r["theta"], {})[r["L"]] = r
    base_rows = {}
    for f in a.base.split(","):
        for r in load(OUT / f)["rows"]:
            base_rows.setdefault(r["theta"], {})[r["L"]] = r
    item = {}
    for r in load(OUT / f"item_{a.name}.json")["rows"]:
        item.setdefault(r["theta"], {})[r["L"]] = r
    rng = random.Random(77)
    for t in sorted(item):
        Ls = sorted(L for L in item[t] if L in base_rows.get(t, {}) and A[L]["unaided_clear_lower_bound"] is not None)
        if not Ls:
            continue
        f0 = dict(full.get(t, {})); f0.update(base_rows[t])
        f1 = dict(f0); f1.update(item[t])
        s0, s1 = seg_refs(f0, A, P), seg_refs(f1, A, P)
        m0, m1, v, nch = _boot_cmp(base_rows[t], item[t], Ls, s0, s1, A, a.reason, a.boot, rng)
        print(f"{a.name} θ{t} n={len(Ls)} changed={nch} rate {sum(base_rows[t][L]['wins']/base_rows[t][L]['games'] for L in Ls)/len(Ls):.3f}"
              f"→{sum(item[t][L]['wins']/item[t][L]['games'] for L in Ls)/len(Ls):.3f} ρ {m0['rho']:.3f}→{m1['rho']:.3f} "
              f"resid {m0['resid']:+.3f}→{m1['resid']:+.3f} maeRel {m0['mae_rel']:.3f}→{m1['mae_rel']:.3f} "
              f"share {m0['share_bot']:.2f}→{m1['share_bot']:.2f} (AF {m0['share_af']:.2f}) | {v['rho']}/{v['absres']}/{v['mae']}")


def cmd_assemble(a):
    rows = load(OUT / "v24_rows.json")["rows"]
    cur = OUT / "v24_curtain_rows.json"          # curtain levels re-measured after curtain_memory_v24 was added
    if cur.exists():
        ov = {(r["L"], r["theta"]): r for r in load(cur)["rows"]}
        rows = [ov.get((r["L"], r["theta"]), r) for r in rows]
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
    sub.add_parser("cmemgrid").set_defaults(f=cmd_cmemgrid)
    sub.add_parser("cmemfit").set_defaults(f=cmd_cmemfit)
    sub.add_parser("cmem085").set_defaults(f=cmd_cmem085)
    sub.add_parser("curtfull").set_defaults(f=cmd_curtfull)
    p = sub.add_parser("final"); p.add_argument("--thetas", default="0.55,0.65,0.85,1.0"); p.add_argument("--drop", default="")
    p.set_defaults(f=cmd_final)
    sub.add_parser("betagrid").set_defaults(f=cmd_betagrid)
    sub.add_parser("betafit").set_defaults(f=cmd_betafit)
    p = sub.add_parser("bgrid"); p.add_argument("--name", required=True); p.add_argument("--item", required=True)
    p.add_argument("--param", required=True); p.add_argument("--values", required=True); p.add_argument("--levels", required=True)
    p.add_argument("--thetas", default="0.85,1.0"); p.add_argument("--games", type=int, default=64)
    p.add_argument("--extra-items", dest="extra_items", default=""); p.add_argument("--fixed", default="")
    p.set_defaults(f=cmd_bgrid)
    p = sub.add_parser("bfit"); p.add_argument("--name", required=True); p.add_argument("--reason", default="Normal")
    p.add_argument("--share-w", dest="share_w", type=float, default=0.0); p.add_argument("--fixed-keys", dest="fixed_keys", default="")
    p.add_argument("--refs", default="base", help="base = segment refs from bot_v2.4 rows; self = this value's own rows")
    p.set_defaults(f=cmd_bfit)
    p = sub.add_parser("cmp"); p.add_argument("--name", required=True); p.add_argument("--base", default="bot_v2.4.json")
    p.add_argument("--reason", default="Normal"); p.add_argument("--boot", type=int, default=500); p.set_defaults(f=cmd_cmp)
    p = sub.add_parser("gimtab"); p.add_argument("--thetas", default="1.0,0.85"); p.add_argument("--boot", type=int, default=1000)
    p.add_argument("--cat24", default="item_cat_v24.json"); p.add_argument("--v24file", default="bot_v2.4.json")
    p.add_argument("--out", default="gimmick_table.json"); p.set_defaults(f=cmd_gimtab)
    a = ap.parse_args()
    a.f(a)


if __name__ == "__main__":
    main()
