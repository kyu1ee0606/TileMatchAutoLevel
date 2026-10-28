"""Doc 71 analysis (2026-10-28): calibration-model retrain readiness.  NEW GAMES 0 -- reads existing measured rows only.

Per map the 'newest default-like cell' predicted vector at theta {.65,.85,1.2} with weights .1164/.1255/.7580 (rows of af_calibration folders, docs 56-70).
Version tags (priority, newest first):
  B3  drp_prereg B'''  (core a89a29ab, current default + .65 cap)            -- doc 70
  B2  drp_dev B''      (core 4b31534c: + P2, before alignment)               -- doc 70 dev
  P2  p2_prereg P2     (core 39d2de55 + public_craft_belief, BASE then)       -- doc 68
  K1  stack_early / se_power B' (core 39d2de55 = K1C default) and k1c_prereg K1C -- docs 60/62/65
Maps with more than one version keep the newest; version mix is reported and every metric is also split by version.
Calibration candidate: ONE logit shift per gimmick layer, logit(AF)=logit(pred)+b_layer, b = mean residual of the OTHER maps in the layer
(leave-one-map-out; layers with <3 other maps fall back to the global shift of the other maps).  No other feature, no refit of the bot.
"""
import sys, json, math, glob, collections
from pathlib import Path
B_ = Path(__file__).resolve().parents[1]; sys.path[:0] = [str(B_), str(B_ / 'scripts')]
import bot_p2_prereg_20261027 as M
c = M.c; R = M.R
AFC = B_ / 'data/pv_sandbox/af_calibration'
TH = (.65, .85, 1.2); W = dict(zip(R.THETAS, R.WEIGHTS)); WS = [W[t] for t in TH]; WS = [w / sum(WS) for w in WS]
SRC = [('B3', 'drp_prereg_20261027', "B'''"), ('B2', 'drp_dev_20261027', "B''"), ('P2', 'p2_prereg_20261027', 'P2'),
       ('K1', 'stack_early_prereg_20261027', "B'"), ('K1', 'se_power_prereg_20261027', "B'"), ('K1', 'k1c_prereg_20261027', 'K1C')]
PHASES = ('N', 'D')


def load():
    best = {}   # L -> (rank, tag, {theta: row})
    for rank, (tag, folder, cell) in enumerate(SRC):
        f = AFC / folder / 'rows.jsonl'
        if not f.exists(): continue
        d = collections.defaultdict(dict)
        for l in f.read_text().splitlines():
            try: r = json.loads(l)
            except ValueError: continue
            if r['option'] == cell and r.get('phase', 'N') in PHASES: d[r['L']][r['theta']] = r
        for L, th in d.items():
            if all(t in th for t in TH) and (L not in best or rank < best[L][0]): best[L] = (rank, tag, th)
    return best


def pred(th):
    vs = [c.vector(th[t]) for t in TH]; return [sum(w * v[j] for w, v in zip(WS, vs)) for j in range(len(c.CATS))]


def layer(L):
    f = c.P[L]['features']
    if f.get('craft'): return 'craft'
    if R.unlock(L) > 0: return 'key'
    if f.get('stack'): return 'stack'
    if f.get('eff_bomb'): return 'bomb'
    if f.get('eff_grass'): return 'grass'
    if any(f.get(k) for k in ('eff_chain', 'eff_link', 'eff_curtain', 'eff_unknown')): return 'other_gimmick'
    return 'plain'


lg = lambda p: math.log(min(.98, max(.02, p)) / (1 - min(.98, max(.02, p))))
sg = lambda x: 1 / (1 + math.exp(-x))
band = lambda a: '<.80' if a < .80 else ('.80-.95' if a < .95 else '>=.95')


def rank(xs):
    o = sorted(range(len(xs)), key=lambda i: xs[i]); r = [0.0] * len(xs); i = 0
    while i < len(o):
        j = i
        while j + 1 < len(o) and xs[o[j + 1]] == xs[o[i]]: j += 1
        for k in range(i, j + 1): r[o[k]] = (i + j) / 2 + 1
        i = j + 1
    return r


def spearman(a, b):
    if len(a) < 4: return None
    ra, rb = rank(a), rank(b); ma, mb = sum(ra) / len(ra), sum(rb) / len(rb)
    num = sum((x - ma) * (y - mb) for x, y in zip(ra, rb)); den = math.sqrt(sum((x - ma) ** 2 for x in ra) * sum((y - mb) ** 2 for y in rb))
    return None if den == 0 else num / den


def main():
    best = load(); Ls = sorted(best)
    rows = []
    for L in Ls:
        p = pred(best[L][2]); a = c.target(L)[0]
        rows.append(dict(L=L, tag=best[L][1], layer=layer(L), pred=p[0], af=a, band=band(a), mode=c.P[L]['mode']))
    n = len(rows)
    # LOO one-shift-per-layer
    for r in rows:
        oth = [x for x in rows if x['L'] != r['L']]
        same = [lg(x['af']) - lg(x['pred']) for x in oth if x['layer'] == r['layer']]
        glob_ = [lg(x['af']) - lg(x['pred']) for x in oth]
        b = sum(same) / len(same) if len(same) >= 3 else sum(glob_) / len(glob_)
        r['cal'] = sg(lg(r['pred']) + b); r['b'] = b
    mae = lambda xs, k: sum(abs(x[k] - x['af']) for x in xs) / len(xs) if xs else None
    bias = lambda xs, k: sum(x[k] - x['af'] for x in xs) / len(xs) if xs else None

    def block(xs):
        return dict(n=len(xs), raw_mae=mae(xs, 'pred'), loo_mae=mae(xs, 'cal'), raw_bias=bias(xs, 'pred'), loo_bias=bias(xs, 'cal'),
                    sp_raw=spearman([x['pred'] for x in xs], [x['af'] for x in xs]), sp_cal=spearman([x['cal'] for x in xs], [x['af'] for x in xs]))
    out = dict(n_maps=n, tags=dict(collections.Counter(r['tag'] for r in rows)), overall=block(rows),
               by_tag={t: block([r for r in rows if r['tag'] == t]) for t in sorted({r['tag'] for r in rows})},
               by_layer={l: block([r for r in rows if r['layer'] == l]) for l in sorted({r['layer'] for r in rows})},
               by_band={b: block([r for r in rows if r['band'] == b]) for b in ('<.80', '.80-.95', '>=.95')},
               by_mode={m: block([r for r in rows if r['mode'] == m]) for m in sorted({r['mode'] for r in rows})},
               shifts={l: sum(lg(x['af']) - lg(x['pred']) for x in rows if x['layer'] == l) / sum(1 for x in rows if x['layer'] == l) for l in sorted({r['layer'] for r in rows})},
               af_min=min(r['af'] for r in rows), af_ge95=sum(r['af'] >= .95 for r in rows))
    # noise reference: binomial 192 games, half width 95% at p; mean over maps of AF-> use predicted p
    out['binom_hw_192_mean'] = sum(1.96 * math.sqrt(r['af'] * (1 - r['af']) / 192) for r in rows) / n
    # (5) training-time bot (bot_v24/bot_v2.4f.json: theta .55/.65/.85/1.0, no 1.2) raw error on the SAME maps.  PROXY: weights .1164/.1255 for .65/.85
    # and .7580 on theta 1.0 (the nearest available theta to 1.2) -- not the same mixture, shown for scale only.
    old = {}
    for r in json.load((AFC / 'bot_v24/bot_v2.4f.json').open())['rows']: old[(r['L'], r['theta'])] = r
    ow = {.65: .1164, .85: .1255, 1.0: .7580}; tot = sum(ow.values()); oerr = []; nerr = []; cmp_rows = []
    for r in rows:
        if all((r['L'], t) in old for t in ow):
            o = sum(ow[t] / tot * old[(r['L'], t)]['wins'] / old[(r['L'], t)]['games'] for t in ow)
            cmp_rows.append((r['L'], r['tag'], o, r['pred'], r['af']))
    out['old_bot_proxy'] = dict(n=len(cmp_rows), old_mae=sum(abs(o - a) for _, _, o, _, a in cmp_rows) / len(cmp_rows), new_mae=sum(abs(p - a) for _, _, _, p, a in cmp_rows) / len(cmp_rows),
                                old_bias=sum(o - a for _, _, o, _, a in cmp_rows) / len(cmp_rows), new_bias=sum(p - a for _, _, _, p, a in cmp_rows) / len(cmp_rows),
                                old_sp=spearman([o for _, _, o, _, _ in cmp_rows], [a for *_, a in cmp_rows]), new_sp=spearman([p for _, _, _, p, _ in cmp_rows], [a for *_, a in cmp_rows]))
    # cost per map-cell (192 games) from rows
    secs = []
    for folder, cell in (('drp_prereg_20261027', "B'''"), ('p2_prereg_20261027', 'P2'), ('p2_prereg_20261027', "B'")):
        f = AFC / folder / 'rows.jsonl'
        if f.exists():
            d = collections.defaultdict(float)
            for l in f.read_text().splitlines():
                r = json.loads(l)
                if r['option'] == cell and r['theta'] in TH: d[r['L']] += r['sec']
            secs += [v for v in d.values()]
    out['sec_per_map_cell'] = dict(n=len(secs), mean=sum(secs) / len(secs) if secs else None, median=sorted(secs)[len(secs) // 2] if secs else None)
    out['rows'] = rows
    (AFC / 'drp_prereg_20261027' / 'readiness_71.json').write_text(json.dumps(out, indent=1))
    f3 = lambda v: 'NA' if v is None else f'{v:.3f}'
    print('maps', n, out['tags'], 'af_ge95', out['af_ge95'], 'binom_hw', round(out['binom_hw_192_mean'], 4))
    for k in ('overall', 'by_tag', 'by_layer', 'by_band', 'by_mode'):
        d = out[k] if k != 'overall' else {'all': out[k]}
        for nm, v in d.items(): print(k, nm, v['n'], 'rawMAE', f3(v['raw_mae']), 'looMAE', f3(v['loo_mae']), 'rawBias', f3(v['raw_bias']), 'looBias', f3(v['loo_bias']), 'sp', f3(v['sp_raw']), '->', f3(v['sp_cal']))
    print('old_bot_proxy', out['old_bot_proxy'], 'sec', out['sec_per_map_cell'])
    print('shifts', {k: round(v, 2) for k, v in out['shifts'].items()})


if __name__ == '__main__':
    main()
