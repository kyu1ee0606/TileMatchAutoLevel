"""Doc 63 step 3 analysis of chain_diag_20261027/trace_rows.jsonl."""
import json
from pathlib import Path
from collections import Counter, defaultdict
OUT = Path(__file__).resolve().parents[1] / 'data/pv_sandbox/af_calibration/chain_diag_20261027'
rows = [json.loads(x) for x in (OUT / 'trace_rows.jsonl').read_text().splitlines()]
g = defaultdict(list)
for r in rows: g[(r['L'], r['cell'], r['theta'])].append(r)
summ = {}
for k, rs in sorted(g.items()):
    tt = sum(r['turns_with_traps'] for r in rs); tp = sum(r['trap_picks'] for r in rs)
    tu = sum(r['trap_turns_unaware'] for r in rs); au = sum(r['avoid_unaware'] for r in rs)
    s = dict(n=len(rs), clear=sum(r['cleared'] for r in rs), cats=dict(Counter(r['cat'] for r in rs)), trap_turns=tt, trap_picks=tp,
             trap_pick_rate=tp / tt if tt else None, unaware_trap_turns=tu, unaware_avoid_rate=au / tu if tu else None,
             aware_share_on_trap_turns=sum(r['trap_turns_aware'] for r in rs) / tt if tt else None,
             first_trap_turn_med=sorted(x for x in (r['first_trap_turn'] for r in rs) if x is not None)[len([1 for r in rs if r['first_trap_turn'] is not None]) // 2] if any(r['first_trap_turn'] is not None for r in rs) else None)
    summ['|'.join(map(str, k))] = s
    print(k, f"clear {s['clear']}/{s['n']}", s['cats'], f"trapTurns {tt} trapPicks {tp} rate {s['trap_pick_rate'] and round(s['trap_pick_rate'], 3)}",
          f"awareShare {s['aware_share_on_trap_turns'] and round(s['aware_share_on_trap_turns'], 2)} unawareAvoid {s['unaware_avoid_rate'] and round(s['unaware_avoid_rate'], 3)} firstTrap {s['first_trap_turn_med']}")
(OUT / 'trace_summary.json').write_text(json.dumps(summ, indent=1))
