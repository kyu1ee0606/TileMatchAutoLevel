"""Bot-only level_summary distributions per cell (B/P1/P2/P12) — auxiliary, not a judgement (doc 56 §4 step 4).
Maps 292/306 (craft), 138 (key+stack), 313 (bomb+stack) x thetas .85/1.2 x 6 games, seed 38M (192 games).
Core 4196e75a fixed; summary module bot_play_summary (confirmed 55 §9-7 definitions). Writes only inside OUT."""
import sys, json, hashlib, os, re, shutil, subprocess, dataclasses, statistics
from pathlib import Path
B_ = Path(__file__).resolve().parents[1]; sys.path[:0] = [str(B_), str(B_ / 'scripts')]
import bot_plan_prereg_20261027 as X
from app.core import bot_play_summary as S
c = X.c
OUT = B_ / 'data/pv_sandbox/af_calibration/plan_summary_dist_20261027'
MAPS = [292, 306, 138, 313]; THETAS = [.85, 1.2]; GAMES = 6; SEED = 38000000
KEYS = ['picks', 'pick_new', 'pick_match', 'min_free', 'danger_picks', 'danger_tail', 'end_pairs', 'bomb_left_min', 'key_unlock', 'cont_first']


def _p(n):
    p = OUT / n; assert p.resolve().parent == OUT.resolve(); return p


def main():
    assert OUT.name == 'plan_summary_dist_20261027'; OUT.mkdir(parents=True, exist_ok=True)
    assert hashlib.sha256((B_ / 'app/core/bot_simulator.py').read_bytes()).hexdigest() == X.CORE
    rows = []
    for L in MAPS:
        layout = c.ev.base.level_layouts(c.P[L], 1)[0]
        for cell, extra in X.CELLS.items():
            for t in THETAS:
                free = float(re.search(r'free = ([\d.]+)M', subprocess.check_output(['sysctl', 'vm.swapusage'], text=True))[1])
                if free < 500 or shutil.disk_usage(B_).free < 10 * 1024 ** 3: print('STOP', free, flush=True); return
                p = c.make_skill_profile(t, 'v2.4'); cfg = dict(p.gimmick_awareness); cfg.update(c.ev.v21.FIXED)
                cfg.update(alpha=dict(c.V21_AWARENESS_DEFAULTS['alpha']), gamma=dict(c.V21_AWARENESS_DEFAULTS['gamma']), exposure=c.EX[L], parity=None,
                           auto_collect=int(float(c.P[L]['row'].get('autoCollectCount') or 0)), v24_expo=c.ev._gc_expo(c.P)[L],
                           v24=list(X.R.prior.BASE) + extra, grass_attention_cap=.65)
                p = dataclasses.replace(p, gimmick_awareness=cfg)
                b = S.SummaryBot(); b.set_rule_parity(p); st = b._create_initial_state(layout, int(layout['max_moves'])); b._precompute_blocking_map(st)
                for g in range(GAMES):
                    s = S.play_and_summarize(b, st, p, SEED + g, L, f'bot_L{L}_{cell}_t{t}_s{SEED + g}')
                    s.update(cell=cell, theta=t, violations=S.check_ranges(s)); rows.append(s)
                print('CELL', L, cell, t, flush=True)
    with _p('rows.jsonl').open('w') as f:
        for r in rows: f.write(json.dumps(r) + '\n')
    summ = {}
    for L in MAPS:
        for cell in X.CELLS:
            rs = [r for r in rows if r['level'] == L and r['cell'] == cell]
            summ[f'{L}/{cell}'] = {k: statistics.median([r[k] for r in rs]) for k in KEYS} | dict(
                seg_end=dict((e, sum(r['seg_end'] == e for r in rs)) for e in sorted({r['seg_end'] for r in rs})),
                violations=sum(bool(r['violations']) for r in rs))
    tmp = _p('summary.tmp'); tmp.write_text(json.dumps(summ, indent=2)); os.replace(tmp, _p('summary.json'))
    print('DONE', len(rows), flush=True)


if __name__ == '__main__':
    main()
