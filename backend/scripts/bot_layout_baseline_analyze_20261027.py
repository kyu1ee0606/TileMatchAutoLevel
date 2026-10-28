"""Doc 63 step 2 analysis: mixture-weighted clear / fail mix for single vs multi layout per map, error vs AF."""
import sys, json
from pathlib import Path
B_ = Path(__file__).resolve().parents[1]; sys.path[:0] = [str(B_), str(B_ / 'scripts')]
import bot_combo_prereg_20261027 as C9
OUT = B_ / 'data/pv_sandbox/af_calibration/layout_baseline_20261027'
rows = [json.loads(x) for x in (OUT / 'rows.jsonl').read_text().splitlines()]
Ls = sorted({r['L'] for r in rows}, key=lambda L: [292, 388, 291, 372, 239, 256, 379, 243].index(L))
res = {}
for opt in ('single', 'multi'):
    e = C9.evaluate(rows, 'LB', opt, Ls); res[opt] = {x['L']: x for x in e['rows']}; res[opt + '_agg'] = {k: e[k] for k in ('joint_mse', 'clear_mae', 'cat_mae')}
pct = lambda v: '/'.join(f'{100 * x:.1f}' for x in v[:4])
for L in Ls:
    s, m = res['single'][L], res['multi'][L]
    print(L, 'AF', pct(s['actual']), '| single', pct(s['predicted']), f"err {100 * s['clear_error']:+.1f}", '| multi', pct(m['predicted']), f"err {100 * m['clear_error']:+.1f}",
          f"| shift {100 * (m['predicted'][0] - s['predicted'][0]):+.1f}")
print('agg single', res['single_agg'], 'multi', res['multi_agg'])
print('mean |shift| %.1f%%p' % (100 * sum(abs(res['multi'][L]['predicted'][0] - res['single'][L]['predicted'][0]) for L in Ls) / len(Ls)))
(OUT / 'summary.json').write_text(json.dumps({k: v for k, v in res.items()}, default=str, indent=1))
