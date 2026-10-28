"""Doc 66: why does stack_early (SE) collapse L208 (and hurt L149)?  Paired-seed trace, diagnostic only.
(Not used for doc 65's judgement.)

Cells (same seeds/layouts): B' = current default (core 39d2de55, prior.BASE incl. K1C), SE = B' + stack_early (w=8).
Maps (random-layout, craft + stack): 208 (theta 1.2, 16 layouts x 2 games), 149 (theta 1.2, 16 layouts x 1 game).
Layout rule bot_layouts_util_20261027 (layout seeds 1..16); per-game seed 64M + layout_index * 1000 + game.
Per pick (pre-pick snapshot, no RNG): chosen key, stack pick / non-match stack pick (the SE-scored action), craft pick,
match, dock occupancy & free slots, distinct dock types, number of moves, accessible craft-emitted tiles, craft boxes
with tiles left, stack tiles left.  Per game: layout seed, outcome, tiles left, end dock, end moves.
Strong parity: each traced game replayed with the plain BotSimulator.  Guard + STOP flag. Writes OUT/trace_rows.jsonl.
"""
import sys, json, os, dataclasses
from pathlib import Path
from collections import Counter
B_ = Path(__file__).resolve().parents[1]; sys.path[:0] = [str(B_), str(B_ / 'scripts')]
import bot_hard_key_prereg_20261027 as HK
import bot_layouts_util_20261027 as LU
import trace_parity_20261026 as TP
import run_guard_20261027 as G
c = HK.c; R = HK.R
OUT = B_ / 'data/pv_sandbox/af_calibration/se_craft_20261027'
PLAN = {208: 2, 149: 1}; THETA = 1.2; SEED = 64000000
CELLS = {"B'": [], 'SE': ['stack_early']}


class Diag(c.BotSimulator):
    def __init__(self, *a, **k):
        super().__init__(*a, **k); self.plog = []

    def _select_move_with_profile(self, moves, state, profile):
        sel = super()._select_move_with_profile(moves, state, profile)
        if sel is not None:
            ts = sel.tile_state
            on_board = [t for lay in state.tiles.values() for t in lay.values() if not t.picked]
            boxes = sum(1 for keys in state.craft_boxes.values()
                        if any((t := state.stacked_tiles.get(k)) is not None and not t.picked and not t.is_crafted for k in keys))
            stack_left = sum(1 for t in state.stacked_tiles.values() if not t.picked and t.is_stack_tile and not t.is_craft_tile) + \
                sum(1 for t in on_board if t.is_stack_tile and not t.is_craft_tile)
            self.plog.append(dict(
                key=ts.full_key if ts else None,
                stack=bool(ts and ts.is_stack_tile and not ts.is_craft_tile),
                craft=bool(ts and ts.is_craft_tile), match=sel.will_match,
                occ=len(state.dock_tiles), free=state.max_dock_slots - len(state.dock_tiles),
                types=len({t.tile_type for t in state.dock_tiles}), n_moves=len(moves),
                n_match_moves=sum(1 for m in moves if m.will_match),
                craft_emitted=sum(1 for t in on_board if t.is_craft_tile and t.is_crafted),
                craft_boxes=boxes, stack_left=stack_left))
        return sel


def prof(L, extra):
    p = c.make_skill_profile(THETA, 'v2.4'); cfg = dict(p.gimmick_awareness); cfg.update(c.ev.v21.FIXED)
    cfg.update(alpha=dict(c.V21_AWARENESS_DEFAULTS['alpha']), gamma=dict(c.V21_AWARENESS_DEFAULTS['gamma']), exposure=c.EX[L], parity=None,
               auto_collect=int(float(c.P[L]['row'].get('autoCollectCount') or 0)), v24_expo=c.ev._gc_expo(c.P)[L],
               v24=list(R.prior.BASE) + extra, grass_attention_cap=.65)
    return dataclasses.replace(p, gimmick_awareness=cfg)


def main():
    OUT.mkdir(parents=True, exist_ok=True); out = OUT / 'trace_rows.jsonl'
    done = {(r['L'], r['cell'], r['layout'], r['g']) for r in map(json.loads, out.read_text().splitlines())} if out.exists() else set()
    for L, per in PLAN.items():
        plan = LU.layouts_for(c, L, 16 * per)
        for cell, extra in CELLS.items():
            p = prof(L, extra)
            for li, (lay, ng, lseed) in enumerate(plan):
                for g in range(ng):
                    if (L, cell, lseed, g) in done: continue
                    if (OUT / 'STOP').exists() or not G.wait_ok(): print('STOP', flush=True); return
                    b = TP.recorder(Diag)(); b.set_rule_parity(p)
                    st = b._create_initial_state(json.loads(json.dumps(lay)), int(lay['max_moves'])); b._precompute_blocking_map(st)
                    b._rng.seed(SEED + li * 1000 + g); end = b._play_game(b._fast_copy_state(st), p)
                    pb = TP.recorder(c.BotSimulator)(); pb.set_rule_parity(p)
                    ps = pb._create_initial_state(json.loads(json.dumps(lay)), int(lay['max_moves'])); pb._precompute_blocking_map(ps)
                    pb._rng.seed(SEED + li * 1000 + g); pe = pb._play_game(pb._fast_copy_state(ps), p)
                    ok, detail = TP.compare(b, end, pb, pe, c.ev.base.fail_reason)
                    if not ok: print('PARITY_FAIL', L, cell, lseed, g, detail, flush=True); sys.exit(2)
                    acc = b._get_available_moves(end) if not end.cleared else []
                    row = dict(L=L, cell=cell, layout=lseed, g=g, cat=c.ev.base.fail_reason(b, end), cleared=end.cleared,
                               picks=len(b.plog), tiles_left=sum(1 for lay2 in end.tiles.values() for t in lay2.values() if not t.picked),
                               end_dock=sorted(Counter(t.tile_type for t in end.dock_tiles).values(), reverse=True),
                               end_moves=len(acc), end_match_moves=sum(1 for m in acc if m.will_match), plog=b.plog, parity='strong')
                    with out.open('a') as f: f.write(json.dumps(row) + '\n'); f.flush(); os.fsync(f.fileno())
            print('CELL', L, cell, flush=True)
    print('DONE', flush=True)


if __name__ == '__main__':
    main()
