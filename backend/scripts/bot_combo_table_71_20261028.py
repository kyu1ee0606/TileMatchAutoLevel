"""Doc 71 §6 (2026-10-28): bot vs AF clear rate by gimmick COMBINATION.  New games 0.
Cells: newest default-like cell per map (bot_retrain_readiness_20261028.load: B3 > B2 > P2 > K1C-era).
Combination = sorted set of present gimmicks from map features: craft, stack, key (unlockTile>0), bomb(eff_bomb), grass(eff_grass),
chain(eff_chain), link(eff_link), curtain(eff_curtain), unk(eff_unknown); none -> plain.  Combos with <2 maps -> 'other'.
Failure cause: bot fail_reasons share (Normal/Grass/Bomb among all fails) vs AF category rates (normalised among fails)."""
import sys, json, collections
from pathlib import Path
B_ = Path(__file__).resolve().parents[1]; sys.path[:0] = [str(B_), str(B_ / 'scripts')]
import bot_retrain_readiness_20261028 as RR
c = RR.c; R = RR.R
def combo(L):
    f = c.P[L]['features']; s = []
    if f.get('craft'): s.append('craft')
    if f.get('stack'): s.append('stack')
    if R.unlock(L) > 0: s.append('key')
    for k, n in (('eff_bomb', 'bomb'), ('eff_grass', 'grass'), ('eff_chain', 'chain'), ('eff_link', 'link'), ('eff_curtain', 'curtain'), ('eff_unknown', 'unk')):
        if f.get(k): s.append(n)
    return '+'.join(s) or 'plain'
def main():
    best = RR.load(); rows = []
    for L, (_, tag, th) in sorted(best.items()):
        p = RR.pred(th); a = c.target(L)
        fr = collections.Counter()
        for t in RR.TH:
            for k, v in th[t]['fail_reasons'].items(): fr[k] += v * RR.WS[RR.TH.index(t)] / th[t]['games']
        rows.append(dict(L=L, tag=tag, combo=combo(L), rand=c.P[L]['mode'] == 'random', af=a[0], bot=p[0], afc=a[1:4], botc=p[1:4], band=RR.band(a[0])))
    cnt = collections.Counter(r['combo'] for r in rows)
    for r in rows: r['grp'] = r['combo'] if cnt[r['combo']] >= 2 else 'other'
    cats = c.CATS[1:4]
    def agg(xs, name):
        n = len(xs); err = [x['bot'] - x['af'] for x in xs]; w = max(xs, key=lambda x: abs(x['bot'] - x['af']))
        top = lambda v: cats[max(range(3), key=lambda j: v[j])] if max(v) > 1e-9 else '-'
        mb = [sum(x['botc'][j] for x in xs) / n for j in range(3)]; ma = [sum(x['afc'][j] for x in xs) / n for j in range(3)]
        return f"| {name} | {n} | {sum(x['af'] for x in xs)/n:.3f} | {sum(x['bot'] for x in xs)/n:.3f} | {sum(err)/n:+.3f} | {sum(map(abs, err))/n:.3f} | L{w['L']} ({w['bot']-w['af']:+.2f}) | {top(mb)} {max(mb):.3f} / {top(ma)} {max(ma):.3f} | {','.join(sorted({x['tag'] for x in xs}))} |"
    hdr = "| {} | 맵 | AF | 봇 | 부호오차 | MAE | 최대오차 맵 | 주 실패(봇/AF, 무조건부율) | 셀 |\n|---|---|---|---|---|---|---|---|---|"
    out = [hdr.format('조합')]
    for g in sorted({r['grp'] for r in rows}, key=lambda g: (g == 'other', -sum(r['grp'] == g for r in rows))): out.append(agg([r for r in rows if r['grp'] == g], g))
    out += ['', hdr.format('AF 구간')]
    for b in ('<.80', '.80-.95', '>=.95'):
        xs = [r for r in rows if r['band'] == b]
        if xs: out.append(agg(xs, b))
    out += ['', hdr.format('배치')]
    for nm, fl in (('고정', False), ('랜덤', True)): out.append(agg([r for r in rows if r['rand'] == fl], nm))
    print('cats', cats); print('\n'.join(out)); (B_ / 'data/pv_sandbox/af_calibration/drp_prereg_20261027/combo_table_71.md').write_text('\n'.join(out))
    print({r['combo'] for r in rows if r['grp'] == 'other'})
main()
