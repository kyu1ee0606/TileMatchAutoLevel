"""Gimmick residual causes (teleporter / frog / stack / ice) — 17_gimmick_residual_causes.md.

Analysis only: shared core (bot_simulator.py etc.) is NOT modified. Instrumentation and rule variants are done
by subclassing BotSimulator inside this script.

Sub-commands (results under data/pv_sandbox/af_calibration/gimmick_causes/):
  resid     calibrated residual (logit map of v2 θ0.55/0.65 → AF mid) per gimmick, raw + controlled (OLS with
            other gimmicks, segment, L>=441 dummies) → resid.json
  boost     AF first-try help: booster use by booster type, revive, LB~UB width per gimmick group vs comparable
            non-gimmick levels → boost.json
  trace     instrumented v2 games on sample levels (θ grid) → trace.json (failure timing, gimmick events before
            failure, plan breaks)
  variant   rule / judgement variants on sample levels → variant.json (vsum → variant_summary.json)
  variant2  stack variants on teleporter/frog/ice levels that also have stacks → variant2.json (v2sum)
"""
from __future__ import annotations

import argparse
import json
import math
import os
import random
import sys
import time
from collections import Counter, defaultdict
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

BACKEND = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND))
sys.path.insert(0, str(BACKEND / "scripts"))

CMP = BACKEND / "data/pv_sandbox/af_calibration/bot_compare_L32_500"
OUT = BACKEND / "data/pv_sandbox/af_calibration/gimmick_causes"
WORKERS = min(2, int(os.environ.get("PV_WORKERS", "2")))
GIM = ("eff_teleporter", "eff_frog", "stack", "eff_ice")
OTHER = ("eff_bomb", "eff_grass", "craft", "eff_curtain", "eff_link", "eff_chain", "eff_unknown", "key")


def load(p):
    with open(p, encoding="utf-8") as f:
        return json.load(f)


def save(name, obj):
    OUT.mkdir(parents=True, exist_ok=True)
    tmp = OUT / (name + ".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, separators=(",", ":"))
    os.replace(tmp, OUT / name)


def lg(p):
    p = min(max(p, 0.01), 0.99)
    return math.log(p / (1 - p))


def sig(x):
    return 1 / (1 + math.exp(-x))


def base_levels():
    prep = {int(k): v for k, v in load(CMP / "prep.json").items()}
    rep = load(CMP / "report.json")
    pl = rep["versions"]["v2"]["per_level"]
    lv = sorted(int(L) for L in pl)
    return prep, lv, {L: pl[str(L)]["mid"] for L in lv}


def has(prep, L, g):
    return prep[L]["features"].get(g, 0) > 0


def ols(X, y):
    """least squares via normal equations (small k); returns coefficients."""
    k = len(X[0])
    A = [[sum(r[i] * r[j] for r in X) for j in range(k)] for i in range(k)]
    b = [sum(r[i] * v for r, v in zip(X, y)) for i in range(k)]
    for i in range(k):
        A[i][i] += 1e-9
    # gaussian elimination
    for c in range(k):
        p = max(range(c, k), key=lambda r: abs(A[r][c]))
        A[c], A[p], b[c], b[p] = A[p], A[c], b[p], b[c]
        for r in range(k):
            if r != c and A[c][c]:
                f = A[r][c] / A[c][c]
                A[r] = [x - f * z for x, z in zip(A[r], A[c])]
                b[r] -= f * b[c]
    return [b[i] / A[i][i] for i in range(k)]


def calib_fit(x, y):
    xs, ys = [lg(v) for v in x], [lg(v) for v in y]
    mx, my = sum(xs) / len(xs), sum(ys) / len(ys)
    b = sum((u - mx) * (v - my) for u, v in zip(xs, ys)) / max(1e-9, sum((u - mx) ** 2 for u in xs))
    return my - b * mx, b


# ── resid ───────────────────────────────────────────────────────────────────────────────────────
def cmd_resid(a):
    prep, lv, mid = base_levels()
    rows = load(CMP / "bot_v2.json")["rows"]
    rate = {(r["L"], r["theta"]): r["wins"] / r["games"] for r in rows}
    out = {}
    names = ["const"] + list(GIM) + list(OTHER) + ["seg101_300", "seg301_500", "L441plus"]
    pl = load(CMP / "report.json")["versions"]["v2"]["per_level"]
    for th in (0.55, 0.65, 0.85, "direct_fit_15"):
        if th == "direct_fit_15":  # 15 §5 table: per-segment θ 0.75/0.85/0.85, bot rate used as is
            c, b = 0.0, 1.0
            pred = {L: pl[str(L)]["fit"] for L in lv}
        else:
            c, b = calib_fit([rate[(L, th)] for L in lv], [mid[L] for L in lv])
            pred = {L: sig(c + b * lg(rate[(L, th)])) for L in lv}
        res = {L: pred[L] - mid[L] for L in lv}
        d = {"calib": {"a": round(c, 3), "b": round(b, 3)}, "gimmick": {}}
        for g in GIM:
            hv = [L for L in lv if has(prep, L, g)]
            no = [L for L in lv if not has(prep, L, g)]
            late_no = [L for L in no if L >= min(hv)]
            d["gimmick"][g] = {"n": len(hv), "first": min(hv), "mean_resid": round(sum(res[L] for L in hv) / len(hv), 3),
                               "mean_resid_without": round(sum(res[L] for L in no) / len(no), 3),
                               "mean_resid_without_same_range": round(sum(res[L] for L in late_no) / max(1, len(late_no)), 3),
                               "n_without_same_range": len(late_no),
                               "share_bot_harder": round(sum(res[L] < 0 for L in hv) / len(hv), 3)}
        X = [[1.0] + [float(has(prep, L, g)) for g in GIM + OTHER]
             + [float(101 <= L <= 300), float(L >= 301), float(L >= 441)] for L in lv]
        coef = ols(X, [res[L] for L in lv])
        # bootstrap CI of OLS coefficients (levels resampled)
        rng = random.Random(17)
        boots = []
        for _ in range(400):
            idx = [rng.randrange(len(lv)) for _ in lv]
            boots.append(ols([X[i] for i in idx], [res[lv[i]] for i in idx]))
        ci = {n: [round(sorted(bb[i] for bb in boots)[10], 3), round(sorted(bb[i] for bb in boots)[389], 3)]
              for i, n in enumerate(names)}
        d["ols"] = {n: {"coef": round(v, 3), "ci95": ci[n]} for n, v in zip(names, coef)}
        d["per_level"] = {str(L): round(res[L], 3) for L in lv}
        out[str(th)] = d
    save("resid.json", out)
    for th, d in out.items():
        print(th, json.dumps(d["gimmick"], ensure_ascii=False))
        print("  OLS", {n: (v["coef"], v["ci95"]) for n, v in d["ols"].items() if n in GIM or n == "L441plus"})


# ── boost ───────────────────────────────────────────────────────────────────────────────────────
def cmd_boost(a):
    """Recompute first-try help per level with booster TYPE (af_level_metrics collapses names to 'booster')."""
    import af_level_metrics as am
    from af_level_metrics import wilson
    prep, lv, mid = base_levels()
    cmp_af = {int(k): v for k, v in load(CMP / "af.json").items()}
    lvset = set(lv)
    orig_load, orig_apply = am.load_events, am._apply

    # keep booster name: wrap json payload with the event name (module-level loader reads 'Event Name' first).
    import csv as _csv
    import gzip as _gzip

    bname_by_key = {}

    def apply(cur, n, d):
        orig_apply(cur, n, d)
        if n == "booster":
            cur.setdefault("bnames", Counter())[d.get("_b", "?")] += 1
        if n == "level_revive":
            cur.setdefault("rev_before_booster", cur["boosters"] == 0)

    am._apply = apply
    # patch KEEP_KEYS to keep our marker and inject the name by re-reading names: simplest is a local loader copy
    am.KEEP_KEYS = tuple(am.KEEP_KEYS) + ("_b",)
    real_loads = json.loads

    class _Row(list):
        pass

    def load_events(data_dir):
        # same as am.load_events but stores booster_use_<type> into payload['_b']
        orig_reader = _csv.reader

        def reader(fh, *x, **k):
            r = orig_reader(fh, *x, **k)
            h = next(r)
            iN, iV = h.index("Event Name"), h.index("Event Value")
            yield h
            for row in r:
                n = row[iN]
                if n.startswith("booster_use_"):
                    try:
                        v = real_loads(row[iV]) if row[iV] else {}
                    except ValueError:
                        v = {}
                    if not isinstance(v, dict):
                        v = {}
                    v["_b"] = n[len("booster_use_"):]
                    row[iV] = json.dumps(v)
                yield row
        am.csv.reader = reader
        try:
            return orig_load(data_dir)
        finally:
            am.csv.reader = orig_reader

    per_dev, _ = load_events(am.AF_DATA)
    runs, *_ = am.build_runs(per_dev)
    del per_dev
    am.mark_first_try(runs)
    by = defaultdict(list)
    for r in runs:
        if r["infinite"] or r["L"] not in lvset or not r.get("first_try"):
            continue
        if r["oc"] not in ("clear", "final_fail"):
            continue
        # match the version subset used in 15 (af.json): 1.1.0+iOS only for re-computed levels
        if cmp_af[r["L"]]["versions_used"] != "all" and (r["plat"], r["ver"]) not in {("android", "1.1.0"), ("ios", "2.1.0")}:
            continue
        by[r["L"]].append(r)
    per = {}
    for L in lv:
        rs = by.get(L, [])
        n = len(rs)
        if not n:
            continue
        b = Counter()
        for r in rs:
            for k, v in (r.get("bnames") or {}).items():
                b[k] += 1  # runs using that booster type
        per[L] = {"n": n, "booster": sum(1 for r in rs if r["boosters"] > 0 or r["item"] > 0) / n,
                  "item": sum(1 for r in rs if r["item"] > 0) / n,
                  "revive": sum(1 for r in rs if r["revives"] > 0) / n,
                  "help": sum(1 for r in rs if r["helped"]) / n,
                  # booster used and cleared with no fail event (= counted in UB as 'would clear')
                  "booster_noFail_clear": sum(1 for r in rs if (r["boosters"] > 0 or r["item"] > 0) and r["fails"] == 0 and r["clear"]) / n,
                  "btype": {k: v / n for k, v in b.items()},
                  "lb": cmp_af[L]["unaided_clear_lower_bound"], "ub": cmp_af[L]["unaided_clear_upper_bound"]}
    am._apply = orig_apply

    def agg(levels):
        levels = [L for L in levels if L in per]
        if not levels:
            return None
        w = sum(per[L]["n"] for L in levels)
        o = {"levels": len(levels), "runs": w}
        for k in ("booster", "item", "revive", "help", "booster_noFail_clear"):
            o[k + "_lvlmean"] = round(sum(per[L][k] for L in levels) / len(levels), 4)
        o["width_ub_lb_lvlmean"] = round(sum(per[L]["ub"] - per[L]["lb"] for L in levels) / len(levels), 4)
        o["mid_lvlmean"] = round(sum(mid[L] for L in levels) / len(levels), 4)
        bt = Counter()
        for L in levels:
            for k, v in per[L]["btype"].items():
                bt[k] += v
        o["btype_lvlmean"] = {k: round(v / len(levels), 4) for k, v in bt.most_common()}
        return o

    out = {"per_level": {str(L): {k: (round(v, 4) if isinstance(v, float) else v) for k, v in d.items() if k != "btype"}
                         | {"btype": {k: round(v, 4) for k, v in d["btype"].items()}} for L, d in per.items()}, "groups": {}}
    for g in GIM:
        hv = [L for L in lv if has(prep, L, g)]
        lo = min(hv)
        ctrl = [L for L in lv if not has(prep, L, g) and L >= lo and not any(has(prep, L, x) for x in GIM if x != "stack" or g == "stack")]
        ctrl_any = [L for L in lv if not has(prep, L, g) and L >= lo]
        out["groups"][g] = {"has": agg(hv), "control_same_range_noTFI": agg(ctrl), "control_same_range": agg(ctrl_any),
                            "control_range_from": lo}
    save("boost.json", out)
    print(json.dumps(out["groups"], ensure_ascii=False, indent=1)[:6000])


# ── bot subclass: instrumentation + rule/judgement variants (shared core untouched) ─────────────
def make_sim(variant: str, trace: bool):
    from app.core.bot_simulator import BotSimulator, TileEffectType

    TELE, FROG_GAME = TileEffectType.TELEPORT, variant == "frog_game"

    class Sim(BotSimulator):
        # ---- rule variants -------------------------------------------------------------------
        def _process_teleport(self, state):
            if variant == "tele_off":
                return
            if variant != "tele_game":
                if trace:
                    before = state.teleport_click_count
                    super()._process_teleport(state)
                    if before == 2 and state.teleport_click_count == 0 and len(state.teleport_tiles) >= 2:
                        self._ev.append("tp")
                    return
                return super()._process_teleport(state)
            # game TileGroup.cs:1996-2088 — random single cycle (Sattolo on the list, then shift along it).
            # bot_simulator.py:2865-2879 shuffles a copy but rotates the ORIGINAL order (fixed cycle).
            state.teleport_click_count += 1
            act = [t for _l, layer in state.tiles.items() for _p, t in layer.items()
                   if t.effect_type == TELE and not t.picked]
            state.teleport_tiles = [(t.layer_idx, t.position_key) for t in act]
            if len(act) < 2:
                for t in act:
                    state.tile_type_overrides[f"{t.layer_idx}_{t.position_key}"] = t.tile_type
                    t.effect_type = TileEffectType.NONE
                    t.attribute = None
                state.teleport_tiles = []
                state.teleport_click_count = 0
                return
            if state.teleport_click_count < 3:
                return
            state.teleport_click_count = 0
            lst = act[:]
            for j in range(len(lst) - 1, 0, -1):
                k = self._rng.randint(0, j - 1)
                lst[j], lst[k] = lst[k], lst[j]
            first = lst[0].tile_type
            for j in range(len(lst) - 1):
                lst[j].tile_type = lst[j + 1].tile_type
            lst[-1].tile_type = first
            if trace:
                self._ev.append("tp")

        def _get_frog_movable_tiles(self, state):
            if not FROG_GAME:
                return super()._get_frog_movable_tiles(state)
            # game TileGroup.cs:1780-1796 — any uncovered, unpicked tile without a frog (no type/effect filter)
            out = []
            for li, layer in state.tiles.items():
                for pos, t in layer.items():
                    if t.picked or t.effect_data.get("on_frog", False):
                        continue
                    if self._is_blocked_by_upper(state, t):
                        continue
                    out.append((li, pos, t))
            return out

        def _move_all_frogs(self, state):
            # game FrogManager.cs:152-159 — frogs stay put while the previous 0.5 s jump tween runs
            # (fast tapping). Approximation: skip half of the frog moves.
            if variant == "frog_skip50" and self._rng.random() < 0.5:
                return
            return super()._move_all_frogs(state)

        def _is_blocked_by_upper(self, state, tile):
            # game Tile.cs:1387-1421 — a non-craft stack tile is masked only by its upper stacked tile
            if variant == "stack_game" and tile.is_stack_tile and not tile.is_craft_tile:
                return False
            return super()._is_blocked_by_upper(state, tile)

        def _score_move_with_profile(self, move, state, profile):
            s = super()._score_move_with_profile(move, state, profile)
            if variant != "stack_nobonus":
                return s
            ts = move.tile_state
            # remove the container 'impact' bonus (bot_simulator.py:3100-3132) for non-craft stack tiles only
            if ts is None or not ts.is_stack_tile or ts.is_craft_tile or not state.goals_remaining:
                return s
            if sum(1 for sl in state.dock if sl.tile is None and not sl.is_locked) < 2:
                return s
            waiting = sum(1 for lt in state.tiles.values() for t in lt.values()
                          if not t.picked and t.tile_type == move.tile_type and not t.is_stack_tile and not t.is_craft_tile)
            inner = len(state.craft_boxes.get(f"{move.layer_idx}_{ts.position_key}", []))
            covered = 0
            bmap = getattr(self, "_blocking_map", None)
            if bmap:
                tkey = (move.layer_idx, ts.position_key)
                for (bl, bp), blockers in bmap.items():
                    if tkey in blockers:
                        bt = state.tiles.get(bl, {}).get(bp)
                        if bt and not bt.picked:
                            covered += 1
            return s - min(60.0, 6.0 * (waiting + inner + covered)) * max(0.3, profile.goal_priority)

        # ---- instrumentation -----------------------------------------------------------------
        def _pick_counts(self, state):
            saved = dict(state._blocking_cache)
            c = Counter()
            for lt in state.tiles.values():
                for t in lt.values():
                    if self._can_pick_tile(state, t):
                        c[t.tile_type] += 1
            state._blocking_cache.clear()
            state._blocking_cache.update(saved)
            return c

        def _play_game(self, state, profile):
            if not trace:
                return super()._play_game(state, profile)
            # same loop as BotSimulator._play_game (bot_simulator.py:1725-1792) + per-move records
            self._ev = []
            rec = {"dock": [], "ev": [], "stack_pick": 0, "stack_orphan": 0, "orphan": 0, "picks": 0,
                   "stack_pick_dock5": 0, "pick_dock5": 0, "ice_wait": 0}
            while not self._is_game_over(state):
                self._update_curtain_memory(state, profile)
                moves = self._get_available_moves(state)
                if not moves:
                    state.failed = True
                    break
                for m in moves:
                    m.score = self._score_move_with_profile(m, state, profile)
                sel = self._select_move_with_profile(moves, state, profile)
                if not sel:
                    continue
                exb, exc = set(), set()
                for k in state.bomb_tiles.keys():
                    p = k.split('_')
                    if len(p) >= 3:
                        lay = state.tiles.get(int(p[0]), {})
                        pos = f"{p[1]}_{p[2]}"
                        if pos in lay and not lay[pos].picked and not self._is_blocked_by_upper(state, lay[pos]):
                            exb.add(k)
                for k in state.curtain_tiles.keys():
                    p = k.split('_')
                    if len(p) >= 3:
                        lay = state.tiles.get(int(p[0]), {})
                        pos = f"{p[1]}_{p[2]}"
                        if pos in lay and not lay[pos].picked and not self._is_blocked_by_upper(state, lay[pos]):
                            exc.add((int(p[0]), pos))
                dock_before = len(state.dock_tiles)
                is_stack = sel.tile_state.is_stack_tile and not sel.tile_state.is_craft_tile
                self._apply_move(state, sel)
                state.moves_used += 1
                rec["picks"] += 1
                dcnt = Counter(t.tile_type for t in state.dock_tiles)
                pc = self._pick_counts(state)
                # orphan = picked a type that now sits alone in the dock with no pickable partner
                if not sel.will_match and dcnt.get(sel.tile_type, 0) == 1 and pc.get(sel.tile_type, 0) == 0:
                    rec["orphan"] += 1
                    if is_stack:
                        rec["stack_orphan"] += 1
                if is_stack:
                    rec["stack_pick"] += 1
                if dock_before >= 5:
                    rec["pick_dock5"] += 1
                    if is_stack:
                        rec["stack_pick_dock5"] += 1
                self._ev = []
                self._process_move_effects(state, exb, exc)
                mv = state.moves_used
                for e in self._ev:
                    rec["ev"].append((mv, e))
                if dcnt:
                    pc2 = self._pick_counts(state)
                    for tt, c in dcnt.items():
                        if c == 2 and pc.get(tt, 0) >= 1 and pc2.get(tt, 0) == 0:
                            rec["ev"].append((mv, "break2"))      # lost the visible 3rd tile of a pair
                        elif c == 2 and pc.get(tt, 0) == 0 and pc2.get(tt, 0) >= 1:
                            rec["ev"].append((mv, "gain2"))
                        elif c == 1 and pc.get(tt, 0) >= 2 and pc2.get(tt, 0) < 2:
                            rec["ev"].append((mv, "break1"))
                        elif c == 1 and pc.get(tt, 0) < 2 and pc2.get(tt, 0) >= 2:
                            rec["ev"].append((mv, "gain1"))
                    # ice wait: a dock type whose only remaining board copies are under exposed, unmelted ice
                    for tt in dcnt:
                        rest = [t for lt in state.tiles.values() for t in lt.values() if not t.picked and t.tile_type == tt]
                        if rest and all(t.effect_type == TileEffectType.ICE and t.effect_data.get("remaining", 0) > 0 for t in rest):
                            rec["ice_wait"] += 1
                            break
                rec["dock"].append(len(state.dock_tiles))
            if not state.failed:
                goals = all(c <= 0 for c in state.goals_remaining.values())
                rem = sum(1 for lt in state.tiles.values() for t in lt.values() if not t.picked)
                state.cleared = goals and rem == 0 and len(state.dock_tiles) == 0
            state._trace = rec
            return state

    return Sim


def _strip(base, variant):
    from app.core.bot_simulator import TileEffectType
    if variant == "frog_off":
        for lt in base.tiles.values():
            for t in lt.values():
                if t.effect_data.get("on_frog"):
                    t.effect_data["on_frog"] = False
        base.frog_positions.clear()
    elif variant == "ice_off":
        for lt in base.tiles.values():
            for t in lt.values():
                if t.effect_type == TileEffectType.ICE:
                    t.effect_type = TileEffectType.NONE
                    t.effect_data = {}
        base.ice_tiles.clear()


def sim_task(args):
    from bot_af_L32_500 import LAYOUTS, _prep, fail_reason, level_layouts
    from app.core.mc_difficulty import make_skill_profile
    t0 = time.time()
    entry = _prep()[args["L"]]
    games, variant, trace = args["games"], args["variant"], args.get("trace", False)
    lays = level_layouts(entry, min(LAYOUTS, games) if entry["mode"] == "random" else 1)
    per = games // len(lays)
    prof = make_skill_profile(args["theta"], "v2")
    bot = make_sim(variant, trace)()
    wins, n, reasons, recs, cov = 0, 0, Counter(), [], None
    for li, lj in enumerate(lays):
        total = int(lj["max_moves"]) - 50
        base = bot._create_initial_state(lj, int(lj["max_moves"]))
        _strip(base, variant)
        bot._precompute_blocking_map(base)
        if cov is None:  # stack tops covered by an upper layer at start (bot rule blocks them, game does not)
            tops = [t for lt in base.tiles.values() for t in lt.values() if t.is_stack_tile and not t.is_craft_tile]
            from app.core.bot_simulator import BotSimulator
            cov = [len(tops), sum(1 for t in tops if BotSimulator._is_blocked_by_upper(bot, base, t))]
        for g in range(per):
            bot._rng.seed(11_000_000 + li * 1000 + g)
            final = bot._play_game(bot._fast_copy_state(base), prof)
            n += 1
            wins += bool(final.cleared)
            if not final.cleared:
                reasons[fail_reason(bot, final)] += 1
            if trace:
                r = final._trace
                recs.append({"win": bool(final.cleared), "moves": final.moves_used, "total": total,
                             "left": total - final.total_tiles_cleared,
                             **{k: v for k, v in r.items() if k != "dock"}, "dock_tail": r["dock"][-12:],
                             "dock_max_first_half": max(r["dock"][: max(1, len(r["dock"]) // 2)] or [0])})
    out = {"L": args["L"], "theta": args["theta"], "variant": variant, "games": n, "wins": wins,
           "fail_reasons": dict(reasons), "stack_tops_covered": cov, "sec": round(time.time() - t0, 2)}
    if trace:
        out["recs"] = recs
    return out


def sample_levels():
    prep, lv, mid = base_levels()
    tfi = ("eff_teleporter", "eff_frog", "eff_ice")
    res = load(OUT / "resid.json")["direct_fit_15"]["per_level"]
    groups = {g: [L for L in lv if has(prep, L, g)] for g in tfi}
    st = [L for L in lv if has(prep, L, "stack") and not any(has(prep, L, x) for x in tfi)]
    st_sorted = sorted(st, key=lambda L: res[str(L)])
    rng = random.Random(1717)
    rest = st_sorted[15:]
    groups["stack"] = sorted(st_sorted[:15] + rng.sample(rest, 25))
    # non-stack control (same filter) for stack judgement comparisons
    ns = [L for L in lv if not has(prep, L, "stack") and not any(has(prep, L, x) for x in tfi)]
    groups["nostack_ctrl"] = sorted(rng.sample(ns, 20))
    return groups


VARIANTS = {"eff_teleporter": ("tele_game", "tele_off"), "eff_frog": ("frog_game", "frog_off"),
            "stack": ("stack_game", "stack_nobonus"), "eff_ice": ("ice_off",), "nostack_ctrl": ()}


def _run(tasks, name, key):
    path = OUT / name
    done = load(path) if path.exists() else {"rows": []}
    have = {key(r) for r in done["rows"]}
    todo = [t for t in tasks if key(t) not in have]
    print(f"{name}: todo {len(todo)} / {len(tasks)}", flush=True)
    t0 = time.time()
    with ProcessPoolExecutor(WORKERS) as ex:
        for r in ex.map(sim_task, todo, chunksize=1):
            done["rows"].append(r)
            if time.time() - t0 > 30:
                save(name, done)
                t0 = time.time()
                print(f"  rows {len(done['rows'])}", flush=True)
    save(name, done)
    print(f"{name}: rows {len(done['rows'])}", flush=True)


def cmd_trace(a):
    groups = sample_levels()
    save("sample.json", groups)
    lv = sorted({L for g in ("eff_teleporter", "eff_frog", "stack", "eff_ice", "nostack_ctrl") for L in groups[g]})
    tasks = [{"L": L, "theta": th, "variant": "base", "games": a.games, "trace": True}
             for th in (0.55, 0.65) for L in lv]
    _run(tasks, "trace.json", lambda r: (r["L"], r["theta"]))


def cmd_variant(a):
    groups = sample_levels()
    tasks = []
    for g, vs in VARIANTS.items():
        for v in vs:
            for th in (0.55, 0.65, 0.85):
                tasks += [{"L": L, "theta": th, "variant": v, "games": a.games} for L in groups[g]]
    _run(tasks, "variant.json", lambda r: (r["L"], r["theta"], r["variant"]))


def cmd_variant2(a):
    """Stack variants on teleporter/frog/ice levels that also contain stacks (co-occurrence check)."""
    prep, lv, _mid = base_levels()
    groups = sample_levels()
    xs = sorted({L for g in ("eff_teleporter", "eff_frog", "eff_ice") for L in groups[g] if has(prep, L, "stack")})
    tasks = [{"L": L, "theta": th, "variant": v, "games": a.games}
             for v in ("stack_game", "stack_nobonus") for th in (0.65, 0.85) for L in xs]
    tasks += [{"L": L, "theta": th, "variant": "frog_skip50", "games": a.games}
              for th in (0.65, 0.85) for L in groups["eff_frog"]]
    _run(tasks, "variant2.json", lambda r: (r["L"], r["theta"], r["variant"]))


def cmd_v2sum(a):
    """variant2 effect per origin group (tele/frog/ice with stack)."""
    groups = load(OUT / "sample.json")
    prep, lv, mid = base_levels()
    base = {(r["L"], r["theta"]): r["wins"] / r["games"] for r in load(CMP / "bot_v2.json")["rows"]}
    var = {(r["L"], r["theta"], r["variant"]): r["wins"] / r["games"] for r in load(OUT / "variant2.json")["rows"]}
    out = {}
    for g in ("eff_teleporter", "eff_frog", "eff_ice"):
        for v in ("stack_game", "stack_nobonus", "frog_skip50"):
            for th in (0.65, 0.85):
                L_ = [L for L in groups[g] if (L, th, v) in var and (v == "frog_skip50" or has(prep, L, "stack"))]
                if not L_:
                    continue
                rb = sum(base[(L, th)] for L in L_) / len(L_)
                rv = sum(var[(L, th, v)] for L in L_) / len(L_)
                out[f"{g}{'' if v == 'frog_skip50' else '+stack'}|{v}|{th}"] = {"levels": len(L_), "rate_base": round(rb, 3), "rate_var": round(rv, 3),
                                              "delta": round(rv - rb, 3),
                                              "direct_resid_base": round(sum(base[(L, th)] - mid[L] for L in L_) / len(L_), 3),
                                              "direct_resid_var": round(sum(var[(L, th, v)] - mid[L] for L in L_) / len(L_), 3)}
    save("variant2_summary.json", out)
    for k, d in out.items():
        print(k, json.dumps(d))


def cmd_tsum(a):
    """Summarise trace.json per sample group → trace_summary.json."""
    groups = load(OUT / "sample.json")
    rows = load(OUT / "trace.json")["rows"]
    W = 5
    out = {}
    for g, levels in groups.items():
        ls = set(levels)
        for th in (0.55, 0.65):
            recs = [(r["L"], x) for r in rows if r["L"] in ls and r["theta"] == th for x in r["recs"]]
            if not recs:
                continue
            fails = [x for _, x in recs if not x["win"]]
            wins = [x for _, x in recs if x["win"]]
            picks = sum(x["picks"] for _, x in recs)

            def evc(xs, k):
                return sum(sum(1 for _, e in x["ev"] if e == k) for x in xs)

            def per100(xs, k):
                p = sum(x["picks"] for x in xs)
                return round(100 * evc(xs, k) / max(1, p), 2)

            def near_fail(xs, k):
                """share of failed games with event k in the last W moves; expected = 1-(1-rate)^W under uniform."""
                hit = sum(1 for x in xs if any(e == k and m > x["moves"] - W for m, e in x["ev"]))
                return round(hit / max(1, len(xs)), 3)

            def exp_rate(xs, k):
                p = sum(x["picks"] for x in xs)
                r = evc(xs, k) / max(1, p)
                return round(1 - (1 - r) ** W, 3)

            fm = sorted(x["moves"] / max(1, x["total"]) for x in fails)
            d = {"games": len(recs), "win": round(len(wins) / len(recs), 3), "fails": len(fails),
                 "fail_move_frac_p25_p50_p75": [round(fm[int(len(fm) * q)], 2) for q in (.25, .5, .75)] if fm else None,
                 "fail_left_p50": sorted(x["left"] for x in fails)[len(fails) // 2] if fails else None}
            for k in ("tp", "break2", "gain2", "break1", "gain1"):
                d[k] = {"per100_win": per100(wins, k), "per100_fail": per100(fails, k),
                        "near_fail": near_fail(fails, k), "near_fail_expected": exp_rate(fails, k)}
            # win rate by whether a pair lost its visible 3rd tile (break2) in the game
            b = [x for _, x in recs if any(e == "break2" for _, e in x["ev"])]
            nb = [x for _, x in recs if not any(e == "break2" for _, e in x["ev"])]
            d["win_if_break2"] = [len(b), round(sum(x["win"] for x in b) / max(1, len(b)), 3)]
            d["win_if_no_break2"] = [len(nb), round(sum(x["win"] for x in nb) / max(1, len(nb)), 3)]
            sp = sum(x["stack_pick"] for _, x in recs)
            so = sum(x["stack_orphan"] for _, x in recs)
            orf = sum(x["orphan"] for _, x in recs)
            d["stack"] = {"pick_share": round(sp / max(1, picks), 3),
                          "pick_share_dock5": round(sum(x["stack_pick_dock5"] for _, x in recs) / max(1, sum(x["pick_dock5"] for _, x in recs)), 3),
                          "orphan_rate_stack": round(so / max(1, sp), 3),
                          "orphan_rate_other": round((orf - so) / max(1, picks - sp), 3)}
            d["ice_wait_per100"] = round(100 * sum(x["ice_wait"] for _, x in recs) / max(1, picks), 2)
            d["ice_wait_fail_share"] = round(sum(1 for x in fails if x["ice_wait"]) / max(1, len(fails)), 3)
            d["dock_tail_fail_mean"] = [round(sum(x["dock_tail"][i] for x in fails if len(x["dock_tail"]) == 12) /
                                              max(1, sum(1 for x in fails if len(x["dock_tail"]) == 12)), 2) for i in range(12)]
            cov = [r["stack_tops_covered"] for r in rows if r["L"] in ls and r["theta"] == th]
            d["stack_tops_total_covered"] = [sum(c[0] for c in cov), sum(c[1] for c in cov),
                                             sum(1 for c in cov if c[1] > 0)]
            out[f"{g}|{th}"] = d
    save("trace_summary.json", out)
    for k, d in out.items():
        print(k, json.dumps(d, ensure_ascii=False))


def cmd_vsum(a):
    """Variant effects: rate change and calibrated residual change (baseline calibration from resid.json)."""
    groups = load(OUT / "sample.json")
    prep, lv, mid = base_levels()
    base = {(r["L"], r["theta"]): r["wins"] / r["games"] for r in load(CMP / "bot_v2.json")["rows"]}
    rows = load(OUT / "variant.json")["rows"]
    var = {(r["L"], r["theta"], r["variant"]): r["wins"] / r["games"] for r in rows}
    cal = load(OUT / "resid.json")
    out = {}
    for g, vs in VARIANTS.items():
        for v in vs:
            for th in (0.55, 0.65, 0.85):
                L_ = [L for L in groups[g] if (L, th, v) in var]
                if not L_:
                    continue
                c = cal[str(th)]["calib"]
                f = lambda p: sig(c["a"] + c["b"] * lg(p))
                rb = sum(base[(L, th)] for L in L_) / len(L_)
                rv = sum(var[(L, th, v)] for L in L_) / len(L_)
                resb = sum(f(base[(L, th)]) - mid[L] for L in L_) / len(L_)
                resv = sum(f(var[(L, th, v)]) - mid[L] for L in L_) / len(L_)
                # direct-fit residual (15 §5 style: bot rate as is) at θ0.85
                db = sum(base[(L, th)] - mid[L] for L in L_) / len(L_)
                dv = sum(var[(L, th, v)] - mid[L] for L in L_) / len(L_)
                ch = [var[(L, th, v)] - base[(L, th)] for L in L_]
                out[f"{g}|{v}|{th}"] = {"levels": len(L_), "rate_base": round(rb, 3), "rate_var": round(rv, 3),
                                        "delta": round(rv - rb, 3), "delta_min_max": [round(min(ch), 3), round(max(ch), 3)],
                                        "levels_up_gt_0.1": sum(1 for x in ch if x > 0.1),
                                        "calib_resid_base": round(resb, 3), "calib_resid_var": round(resv, 3),
                                        "direct_resid_base": round(db, 3), "direct_resid_var": round(dv, 3)}
    save("variant_summary.json", out)
    for k, d in out.items():
        print(k, json.dumps(d))


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("tsum").set_defaults(f=cmd_tsum)
    sub.add_parser("vsum").set_defaults(f=cmd_vsum)
    sub.add_parser("resid").set_defaults(f=cmd_resid)
    sub.add_parser("boost").set_defaults(f=cmd_boost)
    sub.add_parser("v2sum").set_defaults(f=cmd_v2sum)
    for nm, f in (("trace", cmd_trace), ("variant", cmd_variant), ("variant2", cmd_variant2)):
        p = sub.add_parser(nm)
        p.add_argument("--games", type=int, default=128)
        p.set_defaults(f=f)
    p = sub.add_parser("check")
    p.set_defaults(f=cmd_check)
    a = ap.parse_args()
    a.f(a)


def cmd_check(a):
    """Reproducibility: subclass base (plain + traced) must equal stored bot_v2 wins."""
    stored = {(r["L"], r["theta"]): r["wins"] for r in load(CMP / "bot_v2.json")["rows"]}
    for L in (463, 418, 275, 485, 391, 138):
        for tr in (False, True):
            r = sim_task({"L": L, "theta": 0.65, "variant": "base", "games": 128, "trace": tr})
            print(L, "trace" if tr else "plain", r["wins"], stored.get((L, 0.65)), r["stack_tops_covered"], r["sec"], flush=True)


if __name__ == "__main__":
    main()
