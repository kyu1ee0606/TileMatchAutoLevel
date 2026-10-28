"""Doc 66: where are the partners of the dock tiles when the game fails? Deterministic replays of traced games
(same layout / seed as bot_se_craft_trace_20261027): L208 SE failures and B' outcomes on the same layouts (g=0),
L149 B' failures. Counts, for each dock tile type at the end: accessible now / on board but covered / inside a stack
(below the top) / inside a craft box (not emitted). Writes OUT/partner_rows.jsonl."""
import sys, json
from pathlib import Path
from collections import Counter
B_ = Path(__file__).resolve().parents[1]; sys.path[:0] = [str(B_), str(B_ / 'scripts')]
import bot_se_craft_trace_20261027 as T
import bot_layouts_util_20261027 as LU
import run_guard_20261027 as G
c = T.c
OUT = T.OUT


def locate(b, s, types):
    acc = {m.tile_state.full_key for m in b._get_available_moves(s) if m.tile_state is not None}
    on_board = {id(t) for lay in s.tiles.values() for t in lay.values()}
    res = {}
    for tt in types:
        cnt = Counter()
        for lay in s.tiles.values():
            for t in lay.values():
                if t.picked or t.tile_type != tt: continue
                cnt['accessible' if t.full_key in acc else ('craft_emitted_blocked' if t.is_craft_tile else 'board_covered')] += 1
        for k, t in s.stacked_tiles.items():
            if t.picked or t.tile_type != tt or id(t) in on_board: continue
            cnt['craft_box' if t.is_craft_tile and not t.is_crafted else 'stack_inner'] += 1
        res[tt] = dict(cnt)
    return res


def main():
    out = OUT / 'partner_rows.jsonl'; out.write_text('')
    rows = [json.loads(x) for x in (OUT / 'trace_rows.jsonl').read_text().splitlines()]
    pick = [r for r in rows if r['L'] == 208 and r['g'] == 0 and r['layout'] in (4, 5, 6, 7, 10, 11, 14, 16)] + \
           [r for r in rows if r['L'] == 149 and r['cell'] == "B'" and not r['cleared']]
    for r in pick:
        if not G.wait_ok(): return
        L = r['L']; plan = LU.layouts_for(c, L, 16 * T.PLAN[L]); li = r['layout'] - 1; lay = plan[li][0]
        p = T.prof(L, T.CELLS[r['cell']]); b = T.Diag(); b.set_rule_parity(p)
        st = b._create_initial_state(json.loads(json.dumps(lay)), int(lay['max_moves'])); b._precompute_blocking_map(st)
        b._rng.seed(T.SEED + li * 1000 + r['g']); e = b._play_game(b._fast_copy_state(st), p)
        assert e.cleared == r['cleared'] and len(b.plog) == r['picks']          # deterministic replay check
        types = sorted({t.tile_type for t in e.dock_tiles})
        row = dict(L=L, cell=r['cell'], layout=r['layout'], cleared=e.cleared, tiles_left=r['tiles_left'],
                   dock=dict(Counter(t.tile_type for t in e.dock_tiles)), partners=locate(b, e, types) if not e.cleared else None,
                   first20=[('S' if x['stack'] else ('C' if x['craft'] else '.')) + ('m' if x['match'] else '') + str(x['free']) for x in b.plog[:20]])
        with out.open('a') as f: f.write(json.dumps(row) + '\n')
        print(L, r['cell'], 'lay', r['layout'], 'clear' if e.cleared else f"fail left{r['tiles_left']}", row['partners'], ' '.join(row['first20']), flush=True)


if __name__ == '__main__':
    main()
