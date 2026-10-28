"""[v2: C = persistent per-bomb awareness, + ALL cell] Cost-only small batch for doc 58 (not an evaluation): L152 (grass), L313 (bomb), L322 (grass+bomb) x thetas .65/.85/1.2 x 4 games,
cells per map as in the PREREG runner, seed 49M (not used by the PREREG). Writes only inside OUT."""
import sys, json, os
from pathlib import Path
B_ = Path(__file__).resolve().parents[1]; sys.path[:0] = [str(B_), str(B_ / 'scripts')]
import bot_grass_bomb_prereg_20261027 as P
import run_guard_20261027 as G
OUT = B_ / 'data/pv_sandbox/af_calibration/grass_bomb_cost_v2_20261027'
OUT.mkdir(parents=True, exist_ok=True)
for L in (152, 313, 322):
    for cell in P.cells_for(L):
        for t in P.THETAS:
            assert G.wait_ok()
            r = P.measure('cost', cell, L, t, 4, 49000000)
            with (OUT / 'rows.jsonl').open('a') as f: f.write(json.dumps(r) + '\n')
            print('COST', L, cell, t, f"{r['sec'] / 4:.2f}s/game", flush=True)
