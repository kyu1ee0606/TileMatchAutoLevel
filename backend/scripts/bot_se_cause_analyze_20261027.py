"""Doc 64 analysis: paired B' vs SE (same seed) on se_cause_20261027/trace_rows.jsonl. Writes OUT/summary.json."""
import json, statistics as stx
from pathlib import Path
from collections import Counter, defaultdict
OUT = Path(__file__).resolve().parents[1] / 'data/pv_sandbox/af_calibration/se_cause_20261027'
rows = [json.loads(x) for x in (OUT / 'trace_rows.jsonl').read_text().splitlines()]
by = {(r['L'], r['cell'], r['theta'], r['g']): r for r in rows}
med = lambda v: stx.median(v) if v else None
summ = {}
for L in sorted({r['L'] for r in rows}):
    for t in sorted({r['theta'] for r in rows if r['L'] == L}):
        gs = sorted({r['g'] for r in rows if r['L'] == L and r['theta'] == t})
        pairs = [(by[(L, "B'", t, g)], by[(L, 'SE', t, g)]) for g in gs]
        div = []; trans = Counter()
        for b, s in pairs:
            d = next((i for i, (x, y) in enumerate(zip(b['keys'], s['keys'])) if x != y), None)
            div.append(d); trans[(b['cat'], s['cat'])] += 1
        cell = {}
        for name, k in (("B'", 0), ('SE', 1)):
            rs = [p[k] for p in pairs]
            cell[name] = dict(clear=sum(r['cleared'] for r in rs), cats=dict(Counter(r['cat'] for r in rs)),
                              first_stack=med([r['first_stack'] for r in rs if r['first_stack'] is not None]),
                              stack_done=med([r['stack_done'] for r in rs if r['stack_done'] is not None]),
                              stack_done_n=sum(1 for r in rs if r['stack_done'] is not None),
                              first_grass_cut=med([r['first_grass_cut'] for r in rs if r['first_grass_cut'] is not None]),
                              grass_cleared=med([r['grass_cleared'] for r in rs if r['grass_cleared'] is not None]),
                              grass_cleared_n=sum(1 for r in rs if r['grass_cleared'] is not None),
                              min_free=med([r['min_free'] for r in rs]), picks=med([r['picks'] for r in rs]))
        summ[f'{L}|{t}'] = dict(cells=cell, divergence_pick_med=med([d for d in div if d is not None]), identical_games=sum(d is None for d in div),
                                transitions={f'{a}->{b}': n for (a, b), n in trans.items()})
        print(L, t, 'div', summ[f'{L}|{t}']['divergence_pick_med'], 'same', summ[f'{L}|{t}']['identical_games'], dict(trans))
        for name in ("B'", 'SE'): print('   ', name, cell[name])
(OUT / 'summary.json').write_text(json.dumps(summ, indent=1, default=str))
