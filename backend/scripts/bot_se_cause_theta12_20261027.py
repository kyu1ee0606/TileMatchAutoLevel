"""Doc 64: extra paired games at theta 1.2 only (the mixture weight .758 tier that carried doc 62's L269/L417 shifts).
B' vs SE, maps 269 / 417, 32 games each, seed 61M (new). Behaviour-identical Diag bot (strong parity shown in the
trace run) logs stack-exhausted pick and grass-cleared pick. Guard + STOP. Writes OUT/theta12_rows.jsonl."""
import sys, json, os
from pathlib import Path
from collections import Counter
B_ = Path(__file__).resolve().parents[1]; sys.path[:0] = [str(B_), str(B_ / 'scripts')]
import bot_se_cause_trace_20261027 as T
import run_guard_20261027 as G
c = T.c
OUT = T.OUT


def main():
    out = OUT / 'theta12_rows.jsonl'
    done = {(r['L'], r['cell']) for r in map(json.loads, out.read_text().splitlines())} if out.exists() else set()
    for L in (269, 417):
        layout = c.ev.base.level_layouts(c.P[L], 1)[0]
        for cell, extra in T.CELLS.items():
            if (L, cell) in done: continue
            if (OUT / 'STOP').exists() or not G.wait_ok(): print('STOP'); return
            p = T.prof(L, 1.2, extra); w = 0; fr = Counter(); sd = []; gc = []
            for g in range(32):
                b = T.Diag(); b.set_rule_parity(p)
                st = b._create_initial_state(json.loads(json.dumps(layout)), int(layout['max_moves'])); b._precompute_blocking_map(st)
                b._rng.seed(61000000 + g); e = b._play_game(b._fast_copy_state(st), p)
                if e.cleared: w += 1
                else: fr[c.ev.base.fail_reason(b, e)] += 1
                sd.append(next((i for i, x in enumerate(b.plog) if x['stack_left'] == 0), None))
                gr = [x['grass_rem'] for x in b.plog]; gc.append(next((i for i in range(1, len(gr)) if gr[i] < gr[i - 1]), None))
            row = dict(L=L, cell=cell, theta=1.2, games=32, wins=w, fail=dict(fr), stack_done=sd, first_grass_cut=gc)
            with out.open('a') as f: f.write(json.dumps(row) + '\n')
            print({k: v for k, v in row.items() if k not in ('stack_done', 'first_grass_cut')}, flush=True)


if __name__ == '__main__':
    main()
