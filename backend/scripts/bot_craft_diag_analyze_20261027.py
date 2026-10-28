"""Doc 67 analysis: trace (theta 1.2, dock>=4 non-match picks: partner locations / alternatives / search refusal) and
trace2 (human-hypothesis metrics per theta). Writes OUT/analysis.json."""
import json, statistics as stx
from pathlib import Path
from collections import Counter, defaultdict
OUT = Path(__file__).resolve().parents[1] / 'data/pv_sandbox/af_calibration/craft_diag_20261027'
T = [json.loads(x) for x in (OUT / 'trace_rows.jsonl').read_text().splitlines()]
T2 = [json.loads(x) for x in (OUT / 'trace2_rows.jsonl').read_text().splitlines()]
med = lambda v: stx.median(v) if v else None
res = {}
# Q1/Q2 from trace (theta 1.2)
for L in (208, 149):
    rs = [r for r in T if r['L'] == L]; pl = [x for r in rs for x in r['plog']]
    risk = [x for x in pl if 'cls' in x]
    loc = Counter()
    for x in risk:
        w = x['where']; tot = sum(w.values()) or 1
        top = 'accessible' if w.get('accessible') else ('covered' if w.get('covered') else ('craft_box' if w.get('craft_box') else ('stack_inner' if w.get('stack_inner') else 'none')))
        loc[top] += 1
    res[f'T{L}'] = dict(games=len(rs), clear=sum(r['cleared'] for r in rs), picks=len(pl),
                        search_ran=sum(1 for x in pl if x['searched'] and not x['refused']), search_refused=sum(1 for x in pl if x['refused']),
                        risk_picks=len(risk), risk_cls=dict(Counter(x['cls'] for x in risk)),
                        risk_partner_best=dict(loc),
                        risk_new_with_alt_pair=sum(1 for x in risk if x['cls'] == 'new' and x['alt_pair'] > 0),
                        risk_no_access_with_alt_access=sum(1 for x in risk if not x['where'].get('accessible') and x['alt_access'] > 0))
    print('T', L, res[f'T{L}'])
# human hypothesis metrics from trace2
for L in (208, 149):
    for t in (.65, .85, 1.2):
        rs = [r for r in T2 if r['L'] == L and r['theta'] == t]
        first_craft = [next((i for i, x in enumerate(r['plog']) if x['craft']), None) for r in rs]
        by_free = defaultdict(lambda: Counter())
        for r in rs:
            for x in r['plog']:
                f = x['free']; k = 'match' if x['match'] else ('stack' if x['stack'] else ('craft' if x['craft'] else 'other'))
                by_free[f][k] += 1
        curve = {f: dict(n=sum(cn.values()), nonmatch=round((cn['stack'] + cn['craft'] + cn['other']) / sum(cn.values()), 2),
                         stack=round(cn['stack'] / sum(cn.values()), 2)) for f, cn in sorted(by_free.items(), reverse=True)}
        runs = []
        for r in rs:
            if r['cleared']: continue
            n = 0
            for x in reversed(r['plog']):
                if x['match']: break
                n += 1
            runs.append(n)
        res[f'H{L}|{t}'] = dict(games=len(rs), clear=sum(r['cleared'] for r in rs),
                                first_craft_med=med([v for v in first_craft if v is not None]), no_craft_games=sum(v is None for v in first_craft),
                                craft_picks_per_game=sum(x['craft'] for r in rs for x in r['plog']) / len(rs),
                                nonmatch_by_free=curve, fail_tail_nonmatch_run=sorted(runs), fail_tail_med=med(runs),
                                search_refused_share=round(sum(x['refused'] for r in rs for x in r['plog']) / max(1, sum(x['searched'] for r in rs for x in r['plog'])), 3))
        h = res[f'H{L}|{t}']
        print('H', L, t, f"clear {h['clear']}/{h['games']} firstCraft {h['first_craft_med']} craft/game {h['craft_picks_per_game']:.1f} tail {h['fail_tail_med']} {h['fail_tail_nonmatch_run']}",
              {f: (v['nonmatch'], v['stack']) for f, v in h['nonmatch_by_free'].items()})
(OUT / 'analysis.json').write_text(json.dumps(res, indent=1))
