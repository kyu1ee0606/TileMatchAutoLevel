"""Doc 63 step 3: chain-map behaviour trace (diagnostic, not a candidate measurement).

Maps: 378 (fixed; AF fails ~35% by chain), 388 (random; AF chain 35%), 372 (random; AF clear 81%, chain fails present),
219 (random; chain 6 + link 6). Cells: B (new default, prior.BASE incl. K1C) and B + stack_early.
Thetas 5 x 8 games, seed 57M; random maps 8 layouts x 1 game (bot_layouts_util rule, scaled to 8 games).
Per pick (pre-pick, no RNG): number of 'chain-trap' moves (applying the move on a copy makes a locked chain impossible
-> the game would end Chain), whether the chosen move is a trap, chain awareness flag of the turn, locked chains.
Strong parity: every traced game is replayed with the plain BotSimulator (same chosen sequence / outcome / dock).
Guard + STOP flag. Writes OUT/trace_rows.jsonl.
"""
import sys, json, os, dataclasses
from pathlib import Path
from collections import Counter
B_ = Path(__file__).resolve().parents[1]; sys.path[:0] = [str(B_), str(B_ / 'scripts')]
import bot_hard_key_prereg_20261027 as HK
import bot_layouts_util_20261027 as LU
import trace_parity_20261026 as TP
import run_guard_20261027 as G
from app.core.bot_simulator import TileEffectType, Move
c = HK.c; R = HK.R
OUT = B_ / 'data/pv_sandbox/af_calibration/chain_diag_20261027'
MAPS = [378, 388, 372, 219]; GAMES = 8; SEED = 57000000
CELLS = {'B': [], 'SE': ['stack_early']}


class ChainDiag(c.BotSimulator):
    def __init__(self, *a, **k):
        super().__init__(*a, **k); self.plog = []

    def _trap(self, state, m):
        s = self._v2_copy_state(state)
        tile = s.tiles.get(m.layer_idx, {}).get(m.position)
        if tile is None: return False
        self._apply_move(s, Move(layer_idx=m.layer_idx, position=m.position, tile_type=m.tile_type, tile_state=tile,
                                 attribute=m.attribute, match_count=m.match_count, will_match=m.will_match, score=m.score,
                                 linked_tiles=m.linked_tiles))
        return self._check_chain_impossible(s)

    def _select_move_with_profile(self, moves, state, profile):
        sel = super()._select_move_with_profile(moves, state, profile)
        if sel is not None:
            locked = sum(1 for lay in state.tiles.values() for t in lay.values()
                         if not t.picked and t.effect_type == TileEffectType.CHAIN and not t.effect_data.get('unlocked', False))
            traps = [m for m in moves if locked and self._trap(state, m)] if locked else []
            self.plog.append(dict(locked=locked, n_moves=len(moves), n_traps=len(traps), picked_trap=any(m is sel for m in traps),
                                  aware_chain=bool((getattr(self, '_v21_aware', None) or {}).get('chain')),
                                  occ=len(state.dock_tiles), cap=state.max_dock_slots, match=sel.will_match))
        return sel


def prof(L, t, extra):
    p = c.make_skill_profile(t, 'v2.4'); cfg = dict(p.gimmick_awareness); cfg.update(c.ev.v21.FIXED)
    cfg.update(alpha=dict(c.V21_AWARENESS_DEFAULTS['alpha']), gamma=dict(c.V21_AWARENESS_DEFAULTS['gamma']), exposure=c.EX[L], parity=None,
               auto_collect=int(float(c.P[L]['row'].get('autoCollectCount') or 0)), v24_expo=c.ev._gc_expo(c.P)[L],
               v24=list(R.prior.BASE) + extra, grass_attention_cap=.65)
    return dataclasses.replace(p, gimmick_awareness=cfg)


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    out = OUT / 'trace_rows.jsonl'
    done = {(r['L'], r['cell'], r['theta'], r['g']) for r in map(json.loads, out.read_text().splitlines())} if out.exists() else set()
    for L in MAPS:
        plan = LU.layouts_for(c, L, GAMES, n_random=8)
        for cell, extra in CELLS.items():
            for t in R.THETAS:
                p = prof(L, t, extra); gi = 0
                for li, (lay, ng, lseed) in enumerate(plan):
                    for g in range(ng):
                        key = (L, cell, t, gi); gi += 1
                        if key in done: continue
                        if (OUT / 'STOP').exists() or not G.wait_ok(): print('STOP', flush=True); return
                        b = TP.recorder(ChainDiag)(); b.set_rule_parity(p)
                        st = b._create_initial_state(json.loads(json.dumps(lay)), int(lay['max_moves'])); b._precompute_blocking_map(st)
                        b._rng.seed(SEED + li * 1000 + g); end = b._play_game(b._fast_copy_state(st), p)
                        pb = TP.recorder(c.BotSimulator)(); pb.set_rule_parity(p)
                        ps = pb._create_initial_state(json.loads(json.dumps(lay)), int(lay['max_moves'])); pb._precompute_blocking_map(ps)
                        pb._rng.seed(SEED + li * 1000 + g); pe = pb._play_game(pb._fast_copy_state(ps), p)
                        ok, detail = TP.compare(b, end, pb, pe, c.ev.base.fail_reason)
                        if not ok: print('PARITY_FAIL', key, detail, flush=True); sys.exit(2)
                        lg = b.plog
                        row = dict(L=L, cell=cell, theta=t, g=key[3], layout_seed=lseed, cat=c.ev.base.fail_reason(b, end), cleared=end.cleared,
                                   picks=len(lg), turns_with_traps=sum(1 for x in lg if x['n_traps']), trap_moves=sum(x['n_traps'] for x in lg),
                                   trap_picks=sum(1 for x in lg if x['picked_trap']),
                                   trap_turns_aware=sum(1 for x in lg if x['n_traps'] and x['aware_chain']),
                                   trap_turns_unaware=sum(1 for x in lg if x['n_traps'] and not x['aware_chain']),
                                   avoid_unaware=sum(1 for x in lg if x['n_traps'] and not x['aware_chain'] and not x['picked_trap']),
                                   first_trap_turn=next((i for i, x in enumerate(lg) if x['n_traps']), None),
                                   locked_end=lg[-1]['locked'] if lg else None, parity='strong')
                        with out.open('a') as f: f.write(json.dumps(row) + '\n'); f.flush(); os.fsync(f.fileno())
                print('CELL', L, cell, t, flush=True)
    print('DONE', flush=True)


if __name__ == '__main__':
    main()
