"""Doc 69: L82 (fixed, craft 1 + link 2, AF 93.7%) — doc 59 COMBO craft-stratum failure came from theta 1.2 B 30/32
vs COMBO 27/32 (P2 part). Paired B' vs B'+P2 at theta 1.2, 48 games, seed 70M; strong parity replay; per pick:
search ran / refused, match, free slots, craft pick; per game outcome, tiles left, first divergence.
Guard + STOP flag. Writes OUT/trace_rows.jsonl."""
import sys, json, os
from pathlib import Path
B_ = Path(__file__).resolve().parents[1]; sys.path[:0] = [str(B_), str(B_ / 'scripts')]
import bot_craft_diag_20261027 as CD
import trace_parity_20261026 as TP
import run_guard_20261027 as G
c = CD.c
OUT = B_ / 'data/pv_sandbox/af_calibration/l82_trace_20261027'
L = 82; GAMES = 48


def main():
    OUT.mkdir(parents=True, exist_ok=True); out = OUT / 'trace_rows.jsonl'
    done = {(r['cell'], r['g']) for r in map(json.loads, out.read_text().splitlines())} if out.exists() else set()
    layout = c.ev.base.level_layouts(c.P[L], 1)[0]
    for cell in ("B'", 'P2'):
        p = CD.prof(L, 1.2, CD.CELLS[cell])
        for g in range(GAMES):
            if (cell, g) in done: continue
            if (OUT / 'STOP').exists() or not G.wait_ok(): print('STOP', flush=True); return
            b = TP.recorder(CD.Diag)(); b.set_rule_parity(p)
            st = b._create_initial_state(json.loads(json.dumps(layout)), int(layout['max_moves'])); b._precompute_blocking_map(st)
            b._rng.seed(70000000 + g); end = b._play_game(b._fast_copy_state(st), p)
            pb = TP.recorder(c.BotSimulator)(); pb.set_rule_parity(p)
            ps = pb._create_initial_state(json.loads(json.dumps(layout)), int(layout['max_moves'])); pb._precompute_blocking_map(ps)
            pb._rng.seed(70000000 + g); pe = pb._play_game(pb._fast_copy_state(ps), p)
            ok, detail = TP.compare(b, end, pb, pe, c.ev.base.fail_reason)
            if not ok: print('PARITY_FAIL', cell, g, detail, flush=True); sys.exit(2)
            row = dict(cell=cell, g=g, cleared=end.cleared, cat=c.ev.base.fail_reason(b, end),
                       tiles_left=sum(1 for l2 in end.tiles.values() for x in l2.values() if not x.picked),
                       keys=b.choice_keys, plog=b.plog, parity='strong')
            with out.open('a') as f: f.write(json.dumps(row) + '\n'); f.flush(); os.fsync(f.fileno())
        print('CELL', cell, flush=True)
    print('DONE', flush=True)


if __name__ == '__main__':
    main()
