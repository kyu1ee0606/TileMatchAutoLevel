"""Per-map tables for grass_bomb_prereg_20261027 (doc 58): mixture-weighted clear/Grass/Bomb/Normal % per cell. Reads rows only."""
import sys, json, os
from pathlib import Path
B_ = Path(__file__).resolve().parents[1]; sys.path[:0] = [str(B_), str(B_ / 'scripts')]
import bot_grass_bomb_prereg_20261027 as P
OUT = P.OUT


def pct(v): return '/'.join(f'{100 * x:.1f}' for x in v[:4])


def main():
    rows = P.load_rows(); man = json.loads((OUT / 'manifest.json').read_text())
    groups = [('D', 'grass', man['dev']['grass'], ['B', 'G', 'ALL']), ('D', 'bomb', man['dev']['bomb'], ['B', 'C', 'ALL']),
              ('R', 'grass', man['dev']['grass'], ['B', 'G', 'ALL']), ('R', 'bomb', man['dev']['bomb'], ['B', 'C', 'ALL']),
              ('V', 'grass', man['val']['grass'], ['B', 'G', 'ALL']), ('V', 'bomb', man['val']['bomb'], ['B', 'C', 'ALL']),
              ('M', 'both', man['both'], ['B', 'G', 'C', 'GC', 'ALL'])]
    md = []; out = {}
    for ph, s, Ls, cells in groups:
        ev = {x: {e['L']: e for e in P.evaluate(rows, ph, x, Ls, inert=False)['rows']} for x in cells}
        md.append(f'\n### {ph} {s} — clear/Grass/Bomb/Normal % (AF | ' + ' | '.join(cells) + ')\n')
        md.append('| 맵 | AF | ' + ' | '.join(cells) + ' |'); md.append('|---|---|' + '---|' * len(cells))
        for L in Ls:
            a = ev[cells[0]][L]['actual']
            md.append(f'| {L} | {pct(a)} | ' + ' | '.join(pct(ev[x][L]['predicted']) for x in cells) + ' |')
            out.setdefault(ph, {}).setdefault(s, {})[L] = dict(af=a, **{x: ev[x][L]['predicted'] for x in cells})
    (OUT / 'tables.tmp').write_text('\n'.join(md)); os.replace(OUT / 'tables.tmp', OUT / 'tables.md')
    (OUT / 'tables.jtmp').write_text(json.dumps(out)); os.replace(OUT / 'tables.jtmp', OUT / 'tables.json')
    print('\n'.join(md))


if __name__ == '__main__':
    main()
