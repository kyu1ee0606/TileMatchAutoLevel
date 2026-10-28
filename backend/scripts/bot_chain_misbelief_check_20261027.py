"""Doc 63 step 3 small sensitivity check (diagnostic subclass, core untouched): can a 'covered-chain misbelief'
produce human-like chain failures at all?  UPPER-BOUND setting (misbelief always on), not a candidate fit.

Misbelief (observation-style hypothesis): the player believes a horizontal-neighbour pick unlocks a locked chain even
while the chain is covered (game rule: covered chains are NOT unlocked, TileEffect.cs:1004).
  scoring  : when the chain is noticed this turn, _chain_unlock_bonus treats covered chains as exposed
             (the existing 60-point exposed branch; no new constant) and the chain isolation penalty sees no risk;
  rollouts : determinized copies unlock covered chains on neighbour picks (the imagined rule), so search does not
             foresee the isolation.
Maps 388, 372 (random, 8 layouts x 1 game), 378; thetas .85 / 1.2; cells B (new default) and MB; seed 58M.
Guard + STOP flag. Writes OUT/misbelief_rows.jsonl.
"""
import sys, json, os, dataclasses
from pathlib import Path
from collections import Counter
B_ = Path(__file__).resolve().parents[1]; sys.path[:0] = [str(B_), str(B_ / 'scripts')]
import bot_hard_key_prereg_20261027 as HK
import bot_layouts_util_20261027 as LU
import run_guard_20261027 as G
from app.core.bot_simulator import TileEffectType
c = HK.c; R = HK.R
OUT = B_ / 'data/pv_sandbox/af_calibration/chain_diag_20261027'


class MisbeliefBot(c.BotSimulator):
    def _chain_unlock_bonus(self, base_score, move, state, profile, dock_count):
        orig = self._is_blocked_by_upper
        self._is_blocked_by_upper = lambda st, t, _o=orig: False if t.effect_type == TileEffectType.CHAIN else _o(st, t)
        try:
            return super()._chain_unlock_bonus(base_score, move, state, profile, dock_count)
        finally:
            del self._is_blocked_by_upper

    def _chain_isolation_penalty(self, base_score, state, profile, tile_state):
        return base_score                       # no perceived isolation risk

    def _v24_determinize(self, state):
        r = super()._v24_determinize(state)
        if r is not False: state._chain_misbelief = True
        return r

    def _update_adjacent_effects(self, state, picked_tile, unblocked_ice_before_pick=None):
        super()._update_adjacent_effects(state, picked_tile, unblocked_ice_before_pick)
        if getattr(state, '_chain_misbelief', False):
            layer = state.tiles.get(picked_tile.layer_idx, {})
            for ax in (picked_tile.x_idx - 1, picked_tile.x_idx + 1):
                t = layer.get(f'{ax}_{picked_tile.y_idx}')
                if t is not None and not t.picked and t.effect_type == TileEffectType.CHAIN:
                    t.effect_data['unlocked'] = True


def prof(L, t):
    p = c.make_skill_profile(t, 'v2.4'); cfg = dict(p.gimmick_awareness); cfg.update(c.ev.v21.FIXED)
    cfg.update(alpha=dict(c.V21_AWARENESS_DEFAULTS['alpha']), gamma=dict(c.V21_AWARENESS_DEFAULTS['gamma']), exposure=c.EX[L], parity=None,
               auto_collect=int(float(c.P[L]['row'].get('autoCollectCount') or 0)), v24_expo=c.ev._gc_expo(c.P)[L],
               v24=list(R.prior.BASE), grass_attention_cap=.65)
    return dataclasses.replace(p, gimmick_awareness=cfg)


def main():
    out = OUT / 'misbelief_rows.jsonl'
    done = {(r['L'], r['cell'], r['theta']) for r in map(json.loads, out.read_text().splitlines())} if out.exists() else set()
    for L in (388, 372, 378):
        plan = LU.layouts_for(c, L, 8, n_random=8)
        for t in (.85, 1.2):
            for cell, cls in (('B', c.BotSimulator), ('MB', MisbeliefBot)):
                if (L, cell, t) in done: continue
                if (OUT / 'STOP').exists() or not G.wait_ok(): print('STOP'); return
                p = prof(L, t); w = 0; fr = Counter()
                for li, (lay, ng, _) in enumerate(plan):
                    b = cls(); b.set_rule_parity(p)
                    st = b._create_initial_state(json.loads(json.dumps(lay)), int(lay['max_moves'])); b._precompute_blocking_map(st)
                    for g in range(ng):
                        b._rng.seed(58000000 + li * 1000 + g); e = b._play_game(b._fast_copy_state(st), p)
                        if e.cleared: w += 1
                        else: fr[c.ev.base.fail_reason(b, e)] += 1
                row = dict(L=L, cell=cell, theta=t, games=8, wins=w, fail=dict(fr))
                with out.open('a') as f: f.write(json.dumps(row) + '\n')
                print(row, flush=True)


if __name__ == '__main__':
    main()
