"""Doc 61 step 2c: behaviour items that were in V24_DEFAULT when v24f_rows (2026-10-15 19:55, commit 68c4522) were made.
Current core, current B cfg; v24 = BASE + item(s). Maps from argv (default 378), theta 1.0 / 1.2 x 16 games, seed 51M.
Diagnostic only (no adoption). Guard + STOP flag. Writes OUT/ablate2_rows.jsonl."""
import sys, json, os, dataclasses
from pathlib import Path
from collections import Counter
B_ = Path(__file__).resolve().parents[1]; sys.path[:0] = [str(B_), str(B_ / 'scripts')]
import bot_hard_key_prereg_20261027 as HK
import run_guard_20261027 as G
c = HK.c; R = HK.R
OUT = B_ / 'data/pv_sandbox/af_calibration/plain_diag_20261027'
CFG = {'BASE': [], '+stack_early': ['stack_early'], '+covered_info': ['covered_info'],
       '+v24f_items': ['stack_early', 'covered_info', 'bomb_impulse', 'key_first']}


def prof(L, t, extra):
    p = c.make_skill_profile(t, 'v2.4'); cfg = dict(p.gimmick_awareness); cfg.update(c.ev.v21.FIXED)
    cfg.update(alpha=dict(c.V21_AWARENESS_DEFAULTS['alpha']), gamma=dict(c.V21_AWARENESS_DEFAULTS['gamma']), exposure=c.EX[L], parity=None,
               auto_collect=int(float(c.P[L]['row'].get('autoCollectCount') or 0)), v24_expo=c.ev._gc_expo(c.P)[L],
               v24=list(R.prior.BASE) + extra, grass_attention_cap=.65)
    return dataclasses.replace(p, gimmick_awareness=cfg)


def main():
    maps = [int(x) for x in sys.argv[1:]] or [378]
    only = os.environ.get('CFGS')
    cfgs = {k: v for k, v in CFG.items() if not only or k in only.split(',')}
    out = OUT / 'ablate2_rows.jsonl'
    done = {(r['L'], r['cfg'], r['theta']) for r in map(json.loads, out.read_text().splitlines())} if out.exists() else set()
    for L in maps:
        layout = c.ev.base.level_layouts(c.P[L], 1)[0]
        for t in (1.0, 1.2):
            for name, extra in cfgs.items():
                if (L, name, t) in done: continue
                if (OUT / 'STOP').exists() or not G.wait_ok(): return
                p = prof(L, t, extra); b = c.BotSimulator(); b.set_rule_parity(p)
                st = b._create_initial_state(layout, int(layout['max_moves'])); b._precompute_blocking_map(st)
                wins = 0; fr = Counter()
                for g in range(16):
                    b._rng.seed(51000000 + g); e = b._play_game(b._fast_copy_state(st), p)
                    if e.cleared: wins += 1
                    else: fr[c.ev.base.fail_reason(b, e)] += 1
                row = dict(L=L, cfg=name, theta=t, games=16, wins=wins, fail=dict(fr))
                with out.open('a') as f: f.write(json.dumps(row) + '\n')
                print(row, flush=True)


if __name__ == '__main__':
    main()
