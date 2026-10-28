"""Tables for se_power_prereg_20261027 (doc 65): per map AF / B' / SE clear/Grass/Bomb/Normal % and grouped MAE."""
import sys, json, os
from pathlib import Path
B_ = Path(__file__).resolve().parents[1]; sys.path[:0] = [str(B_), str(B_ / 'scripts')]
import bot_se_power_prereg_20261027 as P
OUT = P.OUT


def pct(v): return '/'.join(f'{100 * x:.1f}' for x in v[:4])


def main():
    rows = [json.loads(x) for x in (OUT / 'rows.jsonl').read_text().splitlines()]
    man = json.loads((OUT / 'manifest.json').read_text()); Ls = man['target'] + man['control']
    eb = {e['L']: e for e in P.evaluate(rows, 'N', "B'", Ls)['rows']}; es = {e['L']: e for e in P.evaluate(rows, 'N', 'SE', Ls)['rows']}
    md = ["| 맵 | 층 | 배치 | AF | B′ | SE | 클리어 오차 B′→SE |", '|---|---|---|---|---|---|---|']
    for L in Ls:
        md.append(f"| {L} | {P.stratum(L)} | {P.c.P[L]['mode']} | {pct(eb[L]['actual'])} | {pct(eb[L]['predicted'])} | {pct(es[L]['predicted'])} | "
                  f"{100 * eb[L]['clear_error']:+.1f}→{100 * es[L]['clear_error']:+.1f} |")
    md += ['', '| 묶음 | n | 클리어 MAE B′→SE | 범주 MAE B′→SE | TV B′→SE | 공동 MSE B′→SE |', '|---|---|---|---|---|---|']
    groups = [('전체', Ls), ('대상(스택) 15', man['target'])] + [(f'층 {s}', [L for L in Ls if P.stratum(L) == s]) for s in P.S62.STRATA] + \
             [(f'AF {b}', [L for L in Ls if P.band(L) == b]) for b in P.S62.BANDS]
    for name, gl in groups:
        if not gl: continue
        a, b = P.evaluate(rows, 'N', 'SE', gl), P.evaluate(rows, 'N', "B'", gl)
        md.append(f"| {name} | {len(gl)} | {100 * b['clear_mae']:.1f}→{100 * a['clear_mae']:.1f} | {100 * b['cat_mae']:.1f}→{100 * a['cat_mae']:.1f} | "
                  f"{b['tv']:.3f}→{a['tv']:.3f} | {b['joint_mse']:.4f}→{a['joint_mse']:.4f} |")
    (OUT / 'tables.tmp').write_text('\n'.join(md)); os.replace(OUT / 'tables.tmp', OUT / 'tables.md')
    print('\n'.join(md))


if __name__ == '__main__':
    main()
