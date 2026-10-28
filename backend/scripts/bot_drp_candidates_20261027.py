"""dock_reserve_play (doc 67 §5-2, doc 70) — opt-in candidate as a runner subclass (core untouched).

Public information only: dock contents, accessible board tiles (visible types, cached _get_accessible_type_counts),
craft emission tiles on the board.  Mistake / impulsive draws and awareness draws are untouched (experts still err).
Terms added to the v2.4 behaviour bonus (so they also act inside the theta>1 search candidate set and rollouts):
  1. reserve: a non-matching pick whose triplet cannot be completed from what is accessible now
     (dock[T] + 1 + accessible_others[T] < 3) gets  -w1 * k * max(0, 4 - f),  f = unlocked free slots before the pick.
  2. craft_first: with f >= 5, a non-matching pick of a craft emission tile gets  +w2 * k.
  k = s(theta) = clip((theta-0.5)/0.5, 0, 1) when scaled, else 1.
Params come from profile.gimmick_awareness['drp'] = dict(w1=, w2=, scaled=bool).

Dev stage (this file, main): constants are chosen on DEV maps only (all already AF-compared; no unused map is run).
  cells: B'' (new default, core 4b31534c, prior.BASE incl. K1C + P2), D1 (w1 10, w2 0, scaled), D2 (w1 10, w2 10,
  scaled), D3 (w1 10, w2 10, unscaled).  games per map x cell: theta .65 16 + .85 16 + 1.2 32 (weights .1164/.1255/.7580),
  random-layout maps 16 layouts (bot_layouts_util_20261027).  seed 73M.
  DEV maps (fixed before running): under-success Normal-failure maps 331, 318, 165 (doc 68), 149, 256, 275 (docs 63/67);
  over-success guards 172 (doc 68), 388 (doc 63).
  Rule: the candidate with the lowest dev joint MSE is taken to PREREG only if its dev joint MSE < B'' and dev clear
  MAE <= B''; otherwise no PREREG (report).
Guard run_guard_20261027; STOP flag OUT/STOP; single process.
"""
import sys, json, time, hashlib, os, dataclasses
from pathlib import Path
from collections import Counter
B_ = Path(__file__).resolve().parents[1]; sys.path[:0] = [str(B_), str(B_ / 'scripts')]
import bot_p2_prereg_20261027 as M
import bot_layouts_util_20261027 as LU
import run_guard_20261027 as G
c = M.c; R = M.R
AFC = B_ / 'data/pv_sandbox/af_calibration'
OUT = AFC / 'drp_dev_20261027'
CORE = '4b31534c74ca47c703127bb598ae71e2204ea74f3088be3a368839cdfc1f53e0'
BASE = list(R.prior.BASE)
W = dict(zip(R.THETAS, R.WEIGHTS))
DEV_GAMES = {.65: 16, .85: 16, 1.2: 32}
DEV_MAPS = [331, 318, 165, 149, 256, 275, 172, 388]
DEV_CELLS = {"B''": None, 'D1': dict(w1=10.0, w2=0.0, scaled=True), 'D2': dict(w1=10.0, w2=10.0, scaled=True),
             'D3': dict(w1=10.0, w2=10.0, scaled=False)}


class DRPBot(c.BotSimulator):
    _drp = None

    def set_rule_parity(self, profile):
        super().set_rule_parity(profile)
        cfg = getattr(profile, 'gimmick_awareness', None) or {}
        self._drp = cfg.get('drp') if self._v24 else None

    def _v24_behaviour_bonus(self, move, state, dock_count, dc_risk):
        bonus = super()._v24_behaviour_bonus(move, state, dock_count, dc_risk)
        d = self._drp
        if not d or move.will_match:
            return bonus
        k = self._v24_skill() if d.get('scaled', True) else 1.0
        unlocked = sum(1 for sl in state.dock if not sl.is_locked)
        free = unlocked - dock_count
        if d['w1'] and free < 4:
            in_dock = sum(1 for t in state.dock_tiles if t.tile_type == move.tile_type)
            others = max(0, self._get_accessible_type_counts(state).get(move.tile_type, 0) - 1)
            if in_dock + 1 + others < 3:
                bonus -= d['w1'] * k * (4 - free)
        ts = move.tile_state
        if d['w2'] and free >= 5 and ts is not None and ts.is_craft_tile:
            bonus += d['w2'] * k
        return bonus


def profile(L, t, drp):
    p = c.make_skill_profile(t, 'v2.4'); cfg = dict(p.gimmick_awareness); cfg.update(c.ev.v21.FIXED)
    cfg.update(alpha=dict(c.V21_AWARENESS_DEFAULTS['alpha']), gamma=dict(c.V21_AWARENESS_DEFAULTS['gamma']), exposure=c.EX[L], parity=None,
               auto_collect=int(float(c.P[L]['row'].get('autoCollectCount') or 0)), v24_expo=c.ev._gc_expo(c.P)[L],
               v24=list(BASE), grass_attention_cap=.65)
    if drp: cfg['drp'] = dict(drp)
    return dataclasses.replace(p, gimmick_awareness=cfg)


def measure(phase, cell, drp, L, t, n_games, seed):
    start = time.time(); p = profile(L, t, drp)
    plan = LU.layouts_for(c, L, n_games)
    wins = 0; reasons = Counter(); n = 0
    for li, (lay, ng, _) in enumerate(plan):
        b = DRPBot(); b.set_rule_parity(p)
        st = b._create_initial_state(json.loads(json.dumps(lay)), int(lay['max_moves'])); b._precompute_blocking_map(st)
        for g in range(ng):
            b._rng.seed(seed + li * 1000 + g); end = b._play_game(b._fast_copy_state(st), p); n += 1
            if end.cleared: wins += 1
            else: reasons[c.ev.base.fail_reason(b, end)] += 1
    return dict(phase=phase, option=cell, L=L, theta=t, games=n, layouts=len(plan), wins=wins, fail_reasons=dict(reasons),
                seedbase=seed, sec=time.time() - start)


def evaluate(rows, phase, cell, Ls, thetas):
    d = {(r['L'], r['theta']): r for r in rows if r['phase'] == phase and r['option'] == cell}
    out = []
    for L in Ls:
        vs = [c.vector(d[L, t]) for t in thetas]; ws = [W[t] for t in thetas]
        p = [sum(w * v[j] for w, v in zip(ws, vs)) for j in range(len(c.CATS))]; a = c.target(L)
        out.append(dict(L=L, predicted=p, actual=a, clear_error=p[0] - a[0], joint_mse=sum((x - y) ** 2 for x, y in zip(p, a)) / len(c.CATS),
                        cat_mae=sum(abs(p[j] - a[j]) for j in (1, 2, 3)) / 3))
    return dict(rows=out, joint_mse=sum(x['joint_mse'] for x in out) / len(out), clear_mae=sum(abs(x['clear_error']) for x in out) / len(out),
                cat_mae=sum(x['cat_mae'] for x in out) / len(out))


def main():
    sha = hashlib.sha256((B_ / 'app/core/bot_simulator.py').read_bytes()).hexdigest(); assert sha == CORE
    assert 'public_craft_belief' in BASE
    OUT.mkdir(parents=True, exist_ok=True); out = OUT / 'rows.jsonl'
    rows = [json.loads(l) for l in out.read_text().splitlines()] if out.exists() else []
    done = {(r['option'], r['L'], r['theta']) for r in rows}
    log = lambda m: (print(m, flush=True), (OUT / 'progress.log').open('a').write(m + '\n'))
    for L in DEV_MAPS:
        for cell, drp in DEV_CELLS.items():
            for t, n in DEV_GAMES.items():
                if (cell, L, t) in done: continue
                if (OUT / 'STOP').exists(): log('STOP flag'); return
                if not G.wait_ok(log): return
                r = measure('D', cell, drp, L, t, n, 73000000)
                with out.open('a') as f: f.write(json.dumps(r) + '\n'); f.flush(); os.fsync(f.fileno())
                rows.append(r)
                log(f"ROW {cell} {L} {t} {r['wins']}/{r['games']} {r['fail_reasons']} {r['sec']:.1f}s total{sum(x['games'] for x in rows)}")
    th = list(DEV_GAMES)
    res = {cell: evaluate(rows, 'D', cell, DEV_MAPS, th) for cell in DEV_CELLS}
    summ = {cell: dict(joint_mse=v['joint_mse'], clear_mae=v['clear_mae'], cat_mae=v['cat_mae'],
                       per_map={x['L']: round(x['clear_error'], 4) for x in v['rows']}) for cell, v in res.items()}
    base = res["B''"]
    ok = [cell for cell in DEV_CELLS if cell != "B''" and res[cell]['joint_mse'] < base['joint_mse'] and res[cell]['clear_mae'] <= base['clear_mae'] + 1e-12]
    pick = min(ok, key=lambda x: res[x]['joint_mse']) if ok else None
    j = dict(summary=summ, eligible=ok, pick=pick, games=sum(x['games'] for x in rows),
             rows_sha256=hashlib.sha256(out.read_bytes()).hexdigest(), core=sha, base=BASE, cells=DEV_CELLS, dev_maps=DEV_MAPS)
    (OUT / 'dev_result.json').write_text(json.dumps(j, indent=2)); log(f'DONE pick={pick}')


if __name__ == '__main__':
    main()
