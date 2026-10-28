"""Doc 66 analysis of se_craft_20261027/trace_rows.jsonl (paired B' vs SE)."""
import json, statistics as stx
from pathlib import Path
from collections import Counter, defaultdict
OUT = Path(__file__).resolve().parents[1] / 'data/pv_sandbox/af_calibration/se_craft_20261027'
rows = [json.loads(x) for x in (OUT / 'trace_rows.jsonl').read_text().splitlines()]
by = {(r['L'], r['cell'], r['layout'], r['g']): r for r in rows}
med = lambda v: stx.median(v) if v else None
summ = {}
for L in (208, 149):
    lays = sorted({r['layout'] for r in rows if r['L'] == L})
    tab = []
    for ls in lays:
        gs = sorted({r['g'] for r in rows if r['L'] == L and r['layout'] == ls})
        b = [by[(L, "B'", ls, g)] for g in gs]; s = [by[(L, 'SE', ls, g)] for g in gs]
        div = [next((i for i, (x, y) in enumerate(zip(bb['plog'], ss['plog'])) if x['key'] != y['key']), None) for bb, ss in zip(b, s)]
        tab.append(dict(layout=ls, B=sum(r['cleared'] for r in b), SE=sum(r['cleared'] for r in s), n=len(gs), div=div,
                        B_left=[r['tiles_left'] for r in b if not r['cleared']], SE_left=[r['tiles_left'] for r in s if not r['cleared']]))
    def agg(cell):
        rs = [r for r in rows if r['L'] == L and r['cell'] == cell]
        pl = [x for r in rs for x in r['plog']]
        fails = [r for r in rs if not r['cleared']]
        snm = [x for x in pl if x['stack'] and not x['match']]
        return dict(games=len(rs), clear=sum(r['cleared'] for r in rs),
                    stack_nonmatch_per_game=len(snm) / len(rs), stack_nonmatch_free_med=med([x['free'] for x in snm]),
                    stack_nonmatch_with_match_avail=sum(1 for x in snm if x['n_match_moves'] > 0),
                    first_stack_pick_med=med([next((i for i, x in enumerate(r['plog']) if x['stack']), None) for r in rs if any(x['stack'] for x in r['plog'])]),
                    craft_picks_per_game=sum(1 for x in pl if x['craft']) / len(rs),
                    fail_tiles_left=Counter(r['tiles_left'] for r in fails).most_common(4),
                    fail_end_moves_med=med([r['end_moves'] for r in fails]), fail_end_dock=Counter(tuple(r['end_dock']) for r in fails).most_common(3),
                    min_free_med=med([min(x['free'] for x in r['plog']) for r in rs]),
                    craft_emitted_at_fail_med=med([r['plog'][-1]['craft_emitted'] for r in fails]),
                    craft_boxes_at_fail_med=med([r['plog'][-1]['craft_boxes'] for r in fails]),
                    stack_left_at_fail_med=med([r['plog'][-1]['stack_left'] for r in fails]))
    summ[L] = dict(layouts=tab, B=agg("B'"), SE=agg('SE'))
    print('==', L)
    for t in tab: print('  layout', t['layout'], f"B' {t['B']}/{t['n']} SE {t['SE']}/{t['n']}", 'div', t['div'], 'Bleft', t['B_left'], 'SEleft', t['SE_left'])
    for cell in ('B', 'SE'): print(' ', cell, summ[L][cell])
(OUT / 'summary.json').write_text(json.dumps(summ, indent=1, default=str))
