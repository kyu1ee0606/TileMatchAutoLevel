"""Doc 69: does the theta>1 search give up on key maps?  bot_simulator.py:5589-5590 refuses determinization when a
dock slot is locked and public_key_stack_plan (key_plan) is off, or when an unspawned craft tile remains (no P2).
Configs: B' (measurement default prior.BASE: includes hidden_common_samples + public_key_stack_plan) and DEF
(v24 = V24_DEFAULT only: no hidden_common_samples -> legacy rollouts, no refusal path). Key maps 138, 277, 357, 424
(unlockTile 1; 424/362-type maps also have bombs), theta 1.2 x 12 games, seed 71M. Counts rollout calls and refusals
with the refusal reason (re-evaluated publicly from the same state). Guard. Writes OUT/rows.jsonl."""
import sys, json, dataclasses
from pathlib import Path
from collections import Counter
B_ = Path(__file__).resolve().parents[1]; sys.path[:0] = [str(B_), str(B_ / 'scripts')]
import bot_hard_key_prereg_20261027 as HK
import run_guard_20261027 as G
from app.core.bot_simulator import V24_DEFAULT
c = HK.c; R = HK.R
OUT = B_ / 'data/pv_sandbox/af_calibration/key_refusal_20261027'
CFG = {"B'": list(R.prior.BASE), 'DEF': list(V24_DEFAULT)}


class Probe(c.BotSimulator):
    def __init__(self, *a, **k):
        super().__init__(*a, **k); self.calls = 0; self.ref = Counter()

    def _v24_determinize(self, state):
        r = super()._v24_determinize(state)
        if "hidden_common_samples" in self._v24:
            self.calls += 1
            if r is False:
                remaining = [t for lay in state.tiles.values() for t in lay.values() if not t.picked] + \
                            [t for t in state.stacked_tiles.values() if not t.picked]
                locked = sum(s.is_locked for s in state.dock)
                kp = "public_key_stack_plan" in self._v24 and "key_locks" in self._par
                if "public_craft_belief" not in self._v24 and any(t.is_craft_tile for t in remaining): self.ref['craft'] += 1
                elif locked and not kp: self.ref['lock_no_keyplan'] += 1
                else: self.ref['other(key count/triplet)'] += 1
        return r


def main():
    OUT.mkdir(parents=True, exist_ok=True); out = OUT / 'rows.jsonl'; out.write_text('')
    for L in (138, 277, 357, 424):
        layout = c.ev.base.level_layouts(c.P[L], 1)[0]
        for name, v24 in CFG.items():
            if (OUT / 'STOP').exists() or not G.wait_ok(): return
            p = c.make_skill_profile(1.2, 'v2.4'); cfg = dict(p.gimmick_awareness); cfg.update(c.ev.v21.FIXED)
            cfg.update(alpha=dict(c.V21_AWARENESS_DEFAULTS['alpha']), gamma=dict(c.V21_AWARENESS_DEFAULTS['gamma']), exposure=c.EX[L], parity=None,
                       auto_collect=int(float(c.P[L]['row'].get('autoCollectCount') or 0)), v24_expo=c.ev._gc_expo(c.P)[L], v24=v24, grass_attention_cap=.65)
            p = dataclasses.replace(p, gimmick_awareness=cfg)
            b = Probe(); b.set_rule_parity(p)
            st = b._create_initial_state(json.loads(json.dumps(layout)), int(layout['max_moves'])); b._precompute_blocking_map(st)
            w = 0
            for g in range(12):
                b._rng.seed(71000000 + g); e = b._play_game(b._fast_copy_state(st), p); w += e.cleared
            row = dict(L=L, cfg=name, games=12, wins=w, determinize_calls=b.calls, refused=dict(b.ref), features=c.P[L]['features'])
            with out.open('a') as f: f.write(json.dumps(row) + '\n')
            print(row, flush=True)


if __name__ == '__main__':
    main()
