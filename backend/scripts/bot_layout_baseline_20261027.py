"""Doc 63 step 2: single-layout illusion. New default bot (core 39d2de55, BASE = prior.BASE incl. K1C), maps:
292, 388 (measured with layout seed 1 only in docs 56-61) + the 6 lowest-AF other eligible random-layout maps
(291, 372, 239, 256, 379, 243). Per map x theta: 'single' = layout seed 1 x 32 games (old practice),
'multi' = 16 layouts x 2 games (bot_layouts_util). seed 56M. Guard + STOP flag. Writes OUT/rows.jsonl."""
import sys, json, os, time, dataclasses, hashlib
from pathlib import Path
from collections import Counter
B_ = Path(__file__).resolve().parents[1]; sys.path[:0] = [str(B_), str(B_ / 'scripts')]
import bot_hard_key_prereg_20261027 as HK
import bot_layouts_util_20261027 as LU
import run_guard_20261027 as G
c = HK.c; R = HK.R
OUT = B_ / 'data/pv_sandbox/af_calibration/layout_baseline_20261027'
MAPS = [292, 388, 291, 372, 239, 256, 379, 243]; SEED = 56000000; GAMES = 32


def prof(L, t):
    p = c.make_skill_profile(t, 'v2.4'); cfg = dict(p.gimmick_awareness); cfg.update(c.ev.v21.FIXED)
    cfg.update(alpha=dict(c.V21_AWARENESS_DEFAULTS['alpha']), gamma=dict(c.V21_AWARENESS_DEFAULTS['gamma']), exposure=c.EX[L], parity=None,
               auto_collect=int(float(c.P[L]['row'].get('autoCollectCount') or 0)), v24_expo=c.ev._gc_expo(c.P)[L],
               v24=list(R.prior.BASE), grass_attention_cap=.65)
    return dataclasses.replace(p, gimmick_awareness=cfg)


def run(L, t, plan):
    p = prof(L, t); wins = 0; fr = Counter(); n = 0
    for li, (lay, ng, _) in enumerate(plan):
        b = c.BotSimulator(); b.set_rule_parity(p)
        st = b._create_initial_state(json.loads(json.dumps(lay)), int(lay['max_moves'])); b._precompute_blocking_map(st)
        for g in range(ng):
            b._rng.seed(SEED + li * 1000 + g); e = b._play_game(b._fast_copy_state(st), p); n += 1
            if e.cleared: wins += 1
            else: fr[c.ev.base.fail_reason(b, e)] += 1
    return wins, dict(fr), n


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    out = OUT / 'rows.jsonl'
    done = {(r['L'], r['theta'], r['option']) for r in map(json.loads, out.read_text().splitlines())} if out.exists() else set()
    for L in MAPS:
        single = [(c.ev.base.level_layouts(c.P[L], 1)[0], GAMES, 1)]
        multi = LU.layouts_for(c, L, GAMES)
        for t in R.THETAS:
            for name, plan in (('single', single), ('multi', multi)):
                if (L, t, name) in done: continue
                if (OUT / 'STOP').exists() or not G.wait_ok(): print('STOP', flush=True); return
                s0 = time.time(); w, fr, n = run(L, t, plan)
                row = dict(phase='LB', option=name, L=L, theta=t, games=n, wins=w, fail_reasons=fr, layouts=len(plan), sec=time.time() - s0)
                with out.open('a') as f: f.write(json.dumps(row) + '\n'); f.flush(); os.fsync(f.fileno())
                print('ROW', L, t, name, f'{w}/{n}', fr, flush=True)
    print('DONE', flush=True)


if __name__ == '__main__':
    main()
