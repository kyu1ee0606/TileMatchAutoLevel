"""Doc 64: why does stack_early (SE) over-succeed on L269 (and hurt L417)?  Paired-seed trace, diagnostic only.

Cells (same seeds): B' = new default (core 39d2de55, prior.BASE incl. K1C) and SE = B' + stack_early (w=8, 26 §10).
Maps: 269 (grass 2 + curtain 2 + stack 5; thetas .65/.85/1.2 x 12 games), 417 (curtain 2 + frog 2 + stack; x 8 games).
Both maps are fixed-layout (doc 63 multi-layout rule not needed). Seed 60M.
Per pick (pre-pick snapshot, no RNG): chosen key, stack pick, match, dock occupancy, grass layers left / covered grass /
alive neighbours per grass, stack tiles left. Per game: divergence-ready chosen-key list, first stack pick, stack
exhausted pick, first grass reduction, grass cleared, fail reason, final dock.
Strong parity: each traced game replayed with the plain BotSimulator (same chosen sequence / outcome / dock).
Guard + STOP flag. Writes OUT/trace_rows.jsonl.
"""
import sys, json, os, dataclasses
from pathlib import Path
from collections import Counter
B_ = Path(__file__).resolve().parents[1]; sys.path[:0] = [str(B_), str(B_ / 'scripts')]
import bot_hard_key_prereg_20261027 as HK
import trace_parity_20261026 as TP
import run_guard_20261027 as G
from app.core.bot_simulator import TileEffectType
c = HK.c; R = HK.R
OUT = B_ / 'data/pv_sandbox/af_calibration/se_cause_20261027'
PLAN = {269: 12, 417: 8}; THETAS = [.65, .85, 1.2]; SEED = 60000000
CELLS = {"B'": [], 'SE': ['stack_early']}


class Diag(c.BotSimulator):
    def __init__(self, *a, **k):
        super().__init__(*a, **k); self.plog = []

    def _snap(self, state):
        grass = []
        for lay in state.tiles.values():
            for t in lay.values():
                if t.picked or t.effect_type != TileEffectType.GRASS or t.effect_data.get('remaining', 0) <= 0: continue
                layer = state.tiles.get(t.layer_idx, {})
                alive = sum(1 for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1))
                            if (n := layer.get(f'{t.x_idx + dx}_{t.y_idx + dy}')) is not None and not n.picked)
                grass.append(dict(rem=t.effect_data.get('remaining', 0), covered=self._is_blocked_by_upper(state, t), alive=alive))
        stack_left = sum(1 for t in state.stacked_tiles.values() if not t.picked and t.is_stack_tile and not t.is_craft_tile) + \
            sum(1 for lay in state.tiles.values() for t in lay.values() if not t.picked and t.is_stack_tile and not t.is_craft_tile)
        return grass, stack_left

    def _select_move_with_profile(self, moves, state, profile):
        sel = super()._select_move_with_profile(moves, state, profile)
        if sel is not None:
            grass, stack_left = self._snap(state)
            ts = sel.tile_state
            self.plog.append(dict(key=ts.full_key if ts else None, stack=bool(ts and ts.is_stack_tile and not ts.is_craft_tile),
                                  match=sel.will_match, occ=len(state.dock_tiles), cap=state.max_dock_slots,
                                  grass_rem=sum(g['rem'] for g in grass), grass_cov=sum(1 for g in grass if g['covered']),
                                  grass_alive=[g['alive'] for g in grass], stack_left=stack_left,
                                  n_dock_types=len({t.tile_type for t in state.dock_tiles})))
        return sel


def prof(L, t, extra):
    p = c.make_skill_profile(t, 'v2.4'); cfg = dict(p.gimmick_awareness); cfg.update(c.ev.v21.FIXED)
    cfg.update(alpha=dict(c.V21_AWARENESS_DEFAULTS['alpha']), gamma=dict(c.V21_AWARENESS_DEFAULTS['gamma']), exposure=c.EX[L], parity=None,
               auto_collect=int(float(c.P[L]['row'].get('autoCollectCount') or 0)), v24_expo=c.ev._gc_expo(c.P)[L],
               v24=list(R.prior.BASE) + extra, grass_attention_cap=.65)
    return dataclasses.replace(p, gimmick_awareness=cfg)


def main():
    OUT.mkdir(parents=True, exist_ok=True); out = OUT / 'trace_rows.jsonl'
    done = {(r['L'], r['cell'], r['theta'], r['g']) for r in map(json.loads, out.read_text().splitlines())} if out.exists() else set()
    for L, n in PLAN.items():
        assert c.P[L]['mode'] == 'fixed'
        layout = c.ev.base.level_layouts(c.P[L], 1)[0]
        for t in THETAS:
            for cell, extra in CELLS.items():
                p = prof(L, t, extra)
                for g in range(n):
                    if (L, cell, t, g) in done: continue
                    if (OUT / 'STOP').exists() or not G.wait_ok(): print('STOP', flush=True); return
                    b = TP.recorder(Diag)(); b.set_rule_parity(p)
                    st = b._create_initial_state(json.loads(json.dumps(layout)), int(layout['max_moves'])); b._precompute_blocking_map(st)
                    b._rng.seed(SEED + g); end = b._play_game(b._fast_copy_state(st), p)
                    pb = TP.recorder(c.BotSimulator)(); pb.set_rule_parity(p)
                    ps = pb._create_initial_state(json.loads(json.dumps(layout)), int(layout['max_moves'])); pb._precompute_blocking_map(ps)
                    pb._rng.seed(SEED + g); pe = pb._play_game(pb._fast_copy_state(ps), p)
                    ok, detail = TP.compare(b, end, pb, pe, c.ev.base.fail_reason)
                    if not ok: print('PARITY_FAIL', L, cell, t, g, detail, flush=True); sys.exit(2)
                    lg = b.plog
                    gr = [x['grass_rem'] for x in lg]
                    row = dict(L=L, cell=cell, theta=t, g=g, cat=c.ev.base.fail_reason(b, end), cleared=end.cleared, picks=len(lg),
                               keys=[x['key'] for x in lg],
                               first_stack=next((i for i, x in enumerate(lg) if x['stack']), None),
                               stack_done=next((i for i, x in enumerate(lg) if x['stack_left'] == 0), None),
                               stack_picks_nonmatch=sum(1 for x in lg if x['stack'] and not x['match']),
                               first_grass_cut=next((i for i in range(1, len(gr)) if gr[i] < gr[i - 1]), None),
                               grass_cleared=next((i for i, v in enumerate(gr) if v == 0), None),
                               grass_cov_first10=[x['grass_cov'] for x in lg[:10]],
                               min_free=min((x['cap'] - x['occ'] for x in lg), default=None),
                               end_dock=sorted(Counter(x.tile_type for x in end.dock_tiles).values(), reverse=True),
                               plog=lg, parity='strong')
                    with out.open('a') as f: f.write(json.dumps(row) + '\n'); f.flush(); os.fsync(f.fileno())
                print('CELL', L, t, cell, flush=True)
    print('DONE', flush=True)


if __name__ == '__main__':
    main()
