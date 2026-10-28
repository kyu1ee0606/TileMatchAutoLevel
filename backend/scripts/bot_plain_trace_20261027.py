"""Doc 61 step 2: small diagnostic trace on 'plain' maps (no key/bomb/grass/craft). Not a candidate measurement.

Maps (chosen from step 1, existing B rows): 378 (under-success, chain 5 + stack), 388 (over-success, link 4 + chain 2 +
stack 2), 57 (non-monotone theta curve, link + stack), 275 (population v2.4f rows: AF far above the theta<=1.0 band,
curtain + stack). Current B settings (BASE, cap .65) as in docs 56-60, thetas .55/.65/.85/1.0/1.2 x 8 games, seed 50M.
Each game is played twice: traced DiagBot (SummaryBot + extra pre-pick snapshot) and the plain BotSimulator; strong
parity (same chosen tile sequence, outcome, reason, final dock) is required for every trace row.
Per game: level_summary keys (bot_play_summary), pick classes (match / pair-forming / new single), missed matches
(a non-match pick while a matching move existed), chain state, end dock composition and available moves at the end.
Guard run_guard_20261027; STOP flag OUT/STOP. Writes only inside OUT (trace_rows.jsonl, resumable).
"""
import sys, json, os, dataclasses
from pathlib import Path
from collections import Counter
B_ = Path(__file__).resolve().parents[1]; sys.path[:0] = [str(B_), str(B_ / 'scripts')]
import bot_hard_key_prereg_20261027 as HK
import trace_parity_20261026 as TP
import run_guard_20261027 as G
from app.core import bot_play_summary as S
from app.core.bot_simulator import TileEffectType
c = HK.c; R = HK.R
OUT = B_ / 'data/pv_sandbox/af_calibration/plain_diag_20261027'
MAPS = [378, 388, 57, 275]; GAMES = 8; SEED = 50000000


class DiagBot(S.SummaryBot):
    def _select_move_with_profile(self, moves, state, profile):
        sel = super()._select_move_with_profile(moves, state, profile)
        if sel is not None and self.pick_log:
            dock = Counter(t.tile_type for t in state.dock_tiles)
            n = dock.get(sel.tile_type, 0)
            self.pick_log[-1].update(
                n_moves=len(moves), n_match_moves=sum(1 for m in moves if m.will_match),
                n_pair_moves=sum(1 for m in moves if not m.will_match and dock.get(m.tile_type, 0) == 1),
                cls='match' if sel.will_match else ('pair' if n == 1 else 'new'),
                chains_locked=sum(1 for lay in state.tiles.values() for t in lay.values()
                                  if not t.picked and t.effect_type == TileEffectType.CHAIN and not t.effect_data.get('unlocked', False)),
                chain_pick=bool(sel.tile_state is not None and sel.tile_state.effect_type == TileEffectType.CHAIN))
        return sel


def profile(L, t):
    p = c.make_skill_profile(t, 'v2.4'); cfg = dict(p.gimmick_awareness); cfg.update(c.ev.v21.FIXED)
    cfg.update(alpha=dict(c.V21_AWARENESS_DEFAULTS['alpha']), gamma=dict(c.V21_AWARENESS_DEFAULTS['gamma']), exposure=c.EX[L], parity=None,
               auto_collect=int(float(c.P[L]['row'].get('autoCollectCount') or 0)), v24_expo=c.ev._gc_expo(c.P)[L],
               v24=list(R.prior.BASE), grass_attention_cap=.65)
    return dataclasses.replace(p, gimmick_awareness=cfg)


def _p(name):
    p = OUT / name; assert p.resolve().parent == OUT.resolve(); return p


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    done = set()
    if _p('trace_rows.jsonl').exists():
        for line in _p('trace_rows.jsonl').read_text().splitlines():
            try: r = json.loads(line); done.add((r['L'], r['theta'], r['g']))
            except ValueError: break
    for L in MAPS:
        layout = c.ev.base.level_layouts(c.P[L], 1)[0]
        for t in R.THETAS:
            p = profile(L, t)
            for g in range(GAMES):
                if (L, t, g) in done: continue
                if _p('STOP').exists(): print('STOP flag', flush=True); return
                if not G.wait_ok(): return
                b = TP.recorder(DiagBot)(); b.set_rule_parity(p)
                st = b._create_initial_state(layout, int(layout['max_moves'])); b._precompute_blocking_map(st)
                b.pick_log = []; b._rng.seed(SEED + g); end = b._play_game(b._fast_copy_state(st), p)
                cat = c.ev.base.fail_reason(b, end)
                pb = TP.recorder(c.BotSimulator)(); pb.set_rule_parity(p)
                ps = pb._create_initial_state(layout, int(layout['max_moves'])); pb._precompute_blocking_map(ps)
                pb._rng.seed(SEED + g); pe = pb._play_game(pb._fast_copy_state(ps), p)
                ok, detail = TP.compare(b, end, pb, pe, c.ev.base.fail_reason)
                if not ok: print('PARITY_FAIL', L, t, g, detail, flush=True); sys.exit(2)
                summ = S.summarize(b.pick_log, st, end, cat, L, f'bot_L{L}_t{t}_s{SEED + g}')
                log = b.pick_log; nm = [x for x in log if x.get('cls') != 'match']
                acc = b._get_available_moves(end) if not end.cleared else []
                row = dict(L=L, theta=t, g=g, cat=cat, cleared=end.cleared, moves=end.moves_used, summary=summ, parity='strong',
                           n_match=sum(1 for x in log if x.get('cls') == 'match'), n_pair=sum(1 for x in log if x.get('cls') == 'pair'),
                           n_new=sum(1 for x in log if x.get('cls') == 'new'),
                           missed_match=sum(1 for x in nm if x.get('n_match_moves', 0) > 0),
                           missed_pair=sum(1 for x in log if x.get('cls') == 'new' and x.get('n_pair_moves', 0) > 0),
                           chain_picks=sum(1 for x in log if x.get('chain_pick')),
                           chains_locked_end=sum(1 for lay in end.tiles.values() for tt in lay.values()
                                                 if not tt.picked and tt.effect_type == TileEffectType.CHAIN and not tt.effect_data.get('unlocked', False)),
                           end_dock=sorted(Counter(x.tile_type for x in end.dock_tiles).values(), reverse=True),
                           end_moves=len(acc), end_match_moves=sum(1 for m in acc if m.will_match),
                           tiles_left=sum(1 for lay in end.tiles.values() for tt in lay.values() if not tt.picked),
                           last5=[dict(occ=x['occ'], cap=x['cap'], n=x['n'], cls=x.get('cls'), nm=x.get('n_moves'), nmatch=x.get('n_match_moves'),
                                       chains=x.get('chains_locked')) for x in log[-5:]])
                with _p('trace_rows.jsonl').open('a') as f:
                    f.write(json.dumps(row) + '\n'); f.flush(); os.fsync(f.fileno())
                print('GAME', L, t, g, cat, end.moves_used, flush=True)


if __name__ == '__main__':
    main()
