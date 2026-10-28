"""L138 key / dock-lock diagnosis (observation only, no core change, no bot-quality measurement).

Part F (forced, 0 games): on the real L138 initial state, apply moves that only take the key stack top
(after clearing any tile above it) and log dock / lock counts -> does the 3rd key match unlock a slot?
Part T (trace, small): baseline profile (same as play_summary_check_20261027) at theta .85 / 1.2 x 8 games.
Per pick: type, from key stack?, dock types, keys in dock, locked slots, keys remaining in stack.
Writes only inside OUT.
"""
import sys, json, dataclasses
from pathlib import Path
from collections import Counter
B_ = Path(__file__).resolve().parents[1]; sys.path[:0] = [str(B_), str(B_ / 'scripts')]
import bot_public_deadline_20261026 as prior
c = prior.c
OUT = B_ / 'data/pv_sandbox/af_calibration/key_unlock_diag_20261027'
L = 138; THETAS = [.85, 1.2]; GAMES = 8; SEED = 34000000
STACK_POS = (2, '6_4')


def profile(t):
    p = c.make_skill_profile(t, 'v2.4'); cfg = dict(p.gimmick_awareness); cfg.update(c.ev.v21.FIXED)
    cfg.update(alpha=dict(c.V21_AWARENESS_DEFAULTS['alpha']), gamma=dict(c.V21_AWARENESS_DEFAULTS['gamma']), exposure=c.EX[L], parity=None,
               auto_collect=int(float(c.P[L]['row'].get('autoCollectCount') or 0)), v24_expo=c.ev._gc_expo(c.P)[L],
               v24=list(prior.BASE), grass_attention_cap=.65)
    return dataclasses.replace(p, gimmick_awareness=cfg)


def locked(st): return sum(1 for s in st.dock if s.is_locked)


def keys_left(st):
    on = [t for lay in st.tiles.values() for t in lay.values() if t.tile_type == 'key' and not t.picked]
    st_ = [t for t in st.stacked_tiles.values() if t.tile_type == 'key' and not t.picked and all(t is not o for o in on)]
    return len(on) + len(st_)


def make_trace_bot(base):
    class TB(base):
        def _play_game(self, state, profile):
            self._main_state = state          # log only real moves, not search/rollout copies
            return super()._play_game(state, profile)

        def _apply_move(self, state, move):
            ts = move.tile_state
            pre_dock = [t.tile_type for t in state.dock_tiles]; pre_lock = locked(state)
            from_stack = bool(ts and ts.is_stack_tile and (ts.layer_idx, ts.position_key) == STACK_POS)
            r = super()._apply_move(state, move)
            if getattr(self, 'log', None) is not None and state is getattr(self, '_main_state', None):
                self.log.append(dict(i=state.moves_used, type=ts.tile_type if ts else None, stack=from_stack,
                                     pre_dock=pre_dock, dock=[t.tile_type for t in state.dock_tiles],
                                     cap=state.max_dock_slots, lock_pre=pre_lock, lock=locked(state),
                                     keys_dock=sum(1 for t in state.dock_tiles if t.tile_type == 'key'),
                                     keys_left=keys_left(state), cleared=r))
            return r
    return TB


def part_f(layout):
    b = c.BotSimulator(); st = b._create_initial_state(layout, int(layout['max_moves'])); b._precompute_blocking_map(st)
    out = dict(init_lock=locked(st), init_cap=st.max_dock_slots, init_keys=keys_left(st), steps=[])
    for _ in range(40):
        if keys_left(st) == 0 or b._is_game_over(st): break
        moves = b._get_available_moves(st)
        top = st.tiles.get(STACK_POS[0], {}).get(STACK_POS[1])
        pick = next((m for m in moves if m.tile_state is top), None)
        if pick is None:   # stack top blocked or not accessible: take a move that clears the dock best (prefer match)
            pick = max(moves, key=lambda m: (m.will_match, -sum(1 for t in st.dock_tiles if t.tile_type != m.tile_type)))
        pre = locked(st); b._apply_move(st, pick); st.moves_used += 1
        out['steps'].append(dict(type=pick.tile_type, stack=pick.tile_state is top, dock=[t.tile_type for t in st.dock_tiles],
                                 lock_pre=pre, lock=locked(st), cap=st.max_dock_slots, keys_left=keys_left(st),
                                 over=b._is_game_over(st)))
    return out


def main():
    OUT.mkdir(parents=True, exist_ok=False)
    layout = c.ev.base.level_layouts(c.P[L], 1)[0]
    f = part_f(layout)
    (OUT / 'forced.json').write_text(json.dumps(f, indent=1))
    print('FORCED init lock', f['init_lock'], 'cap', f['init_cap'], 'keys', f['init_keys'])
    for s in f['steps']: print('  F', s)
    rows = []
    for t in THETAS:
        p = profile(t)
        for g in range(GAMES):
            b = make_trace_bot(c.BotSimulator)(); b.set_rule_parity(p)
            st = b._create_initial_state(layout, int(layout['max_moves'])); b._precompute_blocking_map(st)
            b.log = []; b._rng.seed(SEED + g); end = b._play_game(b._fast_copy_state(st), p)
            cat = c.ev.base.fail_reason(b, end)
            row = dict(theta=t, g=g, cat=cat, moves=end.moves_used, n_log=len(b.log), lock_end=locked(end),
                       keys_left_end=keys_left(end), keys_dock_end=sum(1 for x in end.dock_tiles if x.tile_type == 'key'),
                       dock_end=[x.tile_type for x in end.dock_tiles], cap_end=end.max_dock_slots,
                       stack_picks=[(x['i'], x['type']) for x in b.log if x['stack']],
                       first_key_pick=next((x['i'] for x in b.log if x['type'] == 'key'), None), log=b.log)
            rows.append(row)
            with (OUT / 'rows.jsonl').open('a') as fh: fh.write(json.dumps(row) + '\n')
            print('GAME', t, g, cat, 'moves', end.moves_used, 'lock_end', row['lock_end'], 'keys_left', row['keys_left_end'],
                  'keys_dock', row['keys_dock_end'], 'dock', row['dock_end'], 'stack_picks', row['stack_picks'], flush=True)
    print('SUMMARY', Counter((r['theta'], r['cat'], r['keys_left_end']) for r in rows))


if __name__ == '__main__':
    main()
