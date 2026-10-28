"""Doc 63 step 4: L275 (curtain 2 + stack 1; AF 98.7%, bot far below) small cause split. Diagnostic only.
New default bot (prior.BASE incl. K1C) and variants, theta 1.0 / 1.2 x 16 games, seed 59M:
  B; +stack_early; -curtain_hide (closed-curtain types visible to the bot); +curtain_memory_v24 (remember seen types);
  -stack_hide (stack inner types visible).  Guard + STOP flag. Writes OUT/rows.jsonl."""
import sys, json, dataclasses
from pathlib import Path
from collections import Counter
B_ = Path(__file__).resolve().parents[1]; sys.path[:0] = [str(B_), str(B_ / 'scripts')]
import bot_hard_key_prereg_20261027 as HK
import run_guard_20261027 as G
c = HK.c; R = HK.R
OUT = B_ / 'data/pv_sandbox/af_calibration/curtain_diag_20261027'
L = 275
BASE = list(R.prior.BASE)
CFG = {'B': BASE, '+stack_early': BASE + ['stack_early'], '-curtain_hide': [x for x in BASE if x != 'curtain_hide'],
       '+curtain_memory_v24': BASE + ['curtain_memory_v24'], '-stack_hide': [x for x in BASE if x != 'stack_hide']}


def main():
    OUT.mkdir(parents=True, exist_ok=True); out = OUT / 'rows.jsonl'
    done = {(r['cfg'], r['theta']) for r in map(json.loads, out.read_text().splitlines())} if out.exists() else set()
    layout = c.ev.base.level_layouts(c.P[L], 1)[0]
    for t in (1.0, 1.2):
        for name, v24 in CFG.items():
            if (name, t) in done: continue
            if (OUT / 'STOP').exists() or not G.wait_ok(): print('STOP'); return
            p = c.make_skill_profile(t, 'v2.4'); cfg = dict(p.gimmick_awareness); cfg.update(c.ev.v21.FIXED)
            cfg.update(alpha=dict(c.V21_AWARENESS_DEFAULTS['alpha']), gamma=dict(c.V21_AWARENESS_DEFAULTS['gamma']), exposure=c.EX[L], parity=None,
                       auto_collect=int(float(c.P[L]['row'].get('autoCollectCount') or 0)), v24_expo=c.ev._gc_expo(c.P)[L], v24=v24, grass_attention_cap=.65)
            p = dataclasses.replace(p, gimmick_awareness=cfg)
            b = c.BotSimulator(); b.set_rule_parity(p)
            st = b._create_initial_state(json.loads(json.dumps(layout)), int(layout['max_moves'])); b._precompute_blocking_map(st)
            w = 0; fr = Counter(); left = []
            for g in range(16):
                b._rng.seed(59000000 + g); e = b._play_game(b._fast_copy_state(st), p)
                if e.cleared: w += 1
                else:
                    fr[c.ev.base.fail_reason(b, e)] += 1; left.append(sum(1 for lay in e.tiles.values() for x in lay.values() if not x.picked))
            row = dict(L=L, cfg=name, theta=t, games=16, wins=w, fail=dict(fr), tiles_left=sorted(left))
            with out.open('a') as f: f.write(json.dumps(row) + '\n')
            print(row, flush=True)


if __name__ == '__main__':
    main()
