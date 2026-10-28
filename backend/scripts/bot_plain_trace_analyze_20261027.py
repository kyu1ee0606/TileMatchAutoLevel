"""Doc 61: summarise plain_diag_20261027/trace_rows.jsonl per map x theta (no games). Writes trace_summary.json."""
import json, statistics as stx
from pathlib import Path
from collections import Counter, defaultdict
OUT = Path(__file__).resolve().parents[1] / 'data/pv_sandbox/af_calibration/plain_diag_20261027'
rows = [json.loads(x) for x in (OUT / 'trace_rows.jsonl').read_text().splitlines()]
g = defaultdict(list)
for r in rows: g[(r['L'], r['theta'])].append(r)
out = {}
med = lambda v: stx.median(v) if v else None
for (L, t), rs in sorted(g.items()):
    picks = sum(r['n_match'] + r['n_pair'] + r['n_new'] for r in rs)
    nm = sum(r['n_pair'] + r['n_new'] for r in rs)
    fails = [r for r in rs if not r['cleared']]
    s = dict(games=len(rs), clear=sum(r['cleared'] for r in rs), cats=dict(Counter(r['cat'] for r in rs)),
             match_share=sum(r['n_match'] for r in rs) / picks, new_share_of_nonmatch=sum(r['n_new'] for r in rs) / max(1, nm),
             missed_match_per_game=sum(r['missed_match'] for r in rs) / len(rs), missed_pair_per_game=sum(r['missed_pair'] for r in rs) / len(rs),
             min_free_med=med([r['summary']['min_free'] for r in rs]), danger_picks_med=med([r['summary']['danger_picks'] for r in rs]),
             danger_tail_med=med([r['summary']['danger_tail'] for r in rs]), picks_med=med([r['summary']['picks'] for r in rs]),
             chain_picks_med=med([r['chain_picks'] for r in rs]),
             fail_chains_locked_med=med([r['chains_locked_end'] for r in fails]), fail_tiles_left_med=med([r['tiles_left'] for r in fails]),
             fail_end_moves_med=med([r['end_moves'] for r in fails]), fail_end_dock=Counter(tuple(r['end_dock']) for r in fails).most_common(3),
             fail_last_nmatch=[[x['nmatch'] for x in r['last5']] for r in fails][:3],
             fail_last_chains=[[x['chains'] for x in r['last5']] for r in fails][:3])
    out[f'{L}|{t}'] = s
    print(L, t, f"clear {s['clear']}/8", s['cats'], f"match {s['match_share']:.2f} new/nonmatch {s['new_share_of_nonmatch']:.2f}",
          f"missedM {s['missed_match_per_game']:.1f} missedP {s['missed_pair_per_game']:.1f}", f"minfree {s['min_free_med']} dangerTail {s['danger_tail_med']}",
          f"chainPicks {s['chain_picks_med']} failChainsLocked {s['fail_chains_locked_med']} failTilesLeft {s['fail_tiles_left_med']} failEndMoves {s['fail_end_moves_med']}", s['fail_end_dock'][:2])
(OUT / 'trace_summary.tmp').write_text(json.dumps(out, indent=1, default=list)); (OUT / 'trace_summary.tmp').replace(OUT / 'trace_summary.json')
