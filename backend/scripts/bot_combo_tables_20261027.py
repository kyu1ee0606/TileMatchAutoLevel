"""Tables for combo_prereg_20261027 (doc 59): per map AF / B / COMBO clear/Grass/Bomb/Normal % (mixture weighted),
grouped by stratum and AF band, plus group clear MAE / category MAE / TV. Reads rows only; writes tables.md."""
import sys, json, os
from pathlib import Path
B_ = Path(__file__).resolve().parents[1]; sys.path[:0] = [str(B_), str(B_ / 'scripts')]
import bot_combo_prereg_20261027 as P
OUT = P.OUT


def pct(v): return '/'.join(f'{100 * x:.1f}' for x in v[:4])


def main():
    rows = P.load_rows(); man = json.loads((OUT / 'manifest.json').read_text())
    sel = man['selection']; Ls = P.nmaps(sel)
    eb = {e['L']: e for e in P.evaluate(rows, 'N', 'B', Ls)['rows']}
    ec = {e['L']: e for e in P.evaluate(rows, 'N', 'COMBO', Ls)['rows']}
    md = ['| 층 | AF 구간 | 맵 | tier | AF | B | COMBO |', '|---|---|---|---|---|---|---|']
    for s in P.STRATA:
        for b in P.BANDS:
            for L in sel[f'{s}|{b}']:
                md.append(f"| {s} | {b} | {L} | {man['tiers'][str(L)]} | {pct(eb[L]['actual'])} | {pct(eb[L]['predicted'])} | {pct(ec[L]['predicted'])} |")
    md += ['', '| 묶음 | n | 클리어 MAE B→COMBO | 범주 MAE B→COMBO | TV B→COMBO | 공동 MSE B→COMBO |', '|---|---|---|---|---|---|']
    groups = [('전체', Ls)] + [(f'층 {s}', [L for L in Ls if P.stratum(L) == s]) for s in P.STRATA] + \
             [(f'AF {b}', [L for L in Ls if P.band(L) == b]) for b in P.BANDS] + [('tier 1', [L for L in Ls if man['tiers'][str(L)] == 1])]
    for name, gl in groups:
        if not gl: continue
        a, b = P.evaluate(rows, 'N', 'COMBO', gl), P.evaluate(rows, 'N', 'B', gl)
        md.append(f"| {name} | {len(gl)} | {100 * b['clear_mae']:.1f}→{100 * a['clear_mae']:.1f} | {100 * b['cat_mae']:.1f}→{100 * a['cat_mae']:.1f} | "
                  f"{b['tv']:.3f}→{a['tv']:.3f} | {b['joint_mse']:.4f}→{a['joint_mse']:.4f} |")
    (OUT / 'tables.tmp').write_text('\n'.join(md)); os.replace(OUT / 'tables.tmp', OUT / 'tables.md')
    print('\n'.join(md))


if __name__ == '__main__':
    main()
