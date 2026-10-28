"""Report tables for hard_key_prereg_20261027 (doc 57): per-map AF vs cells (mixture-weighted clear / Grass / Bomb / Normal %),
plus key unlock share (theta-weighted). Reads rows only; writes tables.md / tables.json inside OUT."""
import sys, json, os
from pathlib import Path
B_ = Path(__file__).resolve().parents[1]; sys.path[:0] = [str(B_), str(B_ / 'scripts')]
import bot_hard_key_prereg_20261027 as HK
c = HK.c; R = HK.R
OUT = HK.OUT


def pct(v): return '/'.join(f'{100 * x:.1f}' for x in v)


def main():
    rows = HK.load_rows(); man = json.loads((OUT / 'manifest.json').read_text())
    H = {s: v for s, v in man['H'].items()}; hm = [L for v in H.values() for L in v]
    groups = [('H', hm, ['B', 'P2', 'P12']), ('KD', man['kdev'], ['B', 'K1', 'K2']),
              ('KR', man['kdev'], ['B', 'K1', 'K2']), ('KN', man['knew'], ['B', 'K1', 'K2'])]
    out = {}; md = []
    for ph, Ls, cells in groups:
        have = {r['option'] for r in rows if r['phase'] == ph}
        cells = [x for x in cells if x in have]
        if not cells: continue
        ev = {x: {e['L']: e for e in HK.ev(rows, ph, x, Ls)['rows']} for x in cells}
        unl = {}
        for x in cells:
            for L in Ls:
                rs = {r['theta']: r for r in rows if r['phase'] == ph and r['option'] == x and r['L'] == L}
                unl[x, L] = sum(w * rs[t]['unlocked_games'] / rs[t]['games'] for w, t in zip(R.WEIGHTS, R.THETAS)) if rs.get(1.2, {}).get('lock0') else None
        md.append(f'\n### {ph} — clear/Grass/Bomb/Normal % (AF | ' + ' | '.join(cells) + ')\n')
        md.append('| 맵 | AF | ' + ' | '.join(cells) + (' | 해제판(가중) ' + '/'.join(cells) if ph != 'H' else '') + ' |')
        md.append('|---|---|' + '---|' * len(cells) + ('---|' if ph != 'H' else ''))
        for L in Ls:
            a = ev[cells[0]][L]['actual']
            line = f'| {L} | {pct(a[:4])} | ' + ' | '.join(pct(ev[x][L]['predicted'][:4]) for x in cells)
            if ph != 'H': line += ' | ' + '/'.join('-' if unl[x, L] is None else f'{100 * unl[x, L]:.0f}' for x in cells)
            md.append(line + ' |')
            out.setdefault(ph, {})[L] = dict(af=a, **{x: ev[x][L]['predicted'] for x in cells}, unlocked={x: unl[x, L] for x in cells})
    (OUT / 'tables.tmp').write_text('\n'.join(md)); os.replace(OUT / 'tables.tmp', OUT / 'tables.md')
    (OUT / 'tables.jtmp').write_text(json.dumps(out)); os.replace(OUT / 'tables.jtmp', OUT / 'tables.json')
    print('\n'.join(md))


if __name__ == '__main__':
    main()
