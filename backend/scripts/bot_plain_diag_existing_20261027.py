"""Doc 61 step 1 (no games): plain maps (no key / bomb / grass / craft) from existing B rows measured with the current
B definition (BASE, cap .65; cores 4196e75a / cbc2e652 behave the same on maps without keys):
plan_prereg_20261027 (D/R/N), hard_key_prereg_20261027 (H), combo_prereg_20261027 (N/Rp).
Per map: theta curve (clear, fail mix), AF, mixture prediction, residual; per-map theta that matches AF; a diagnostic
simplex mixture fit over the plain maps (DIAGNOSTIC ONLY - not adopted, not used for any judgement).
Also the population v2.4f rows (theta <= 1.0, older v24 list) for all plain maps as context. Writes OUT/existing.json."""
import sys, json, itertools
from pathlib import Path
B_ = Path(__file__).resolve().parents[1]; sys.path[:0] = [str(B_), str(B_ / 'scripts')]
import bot_hard_key_prereg_20261027 as HK
c = HK.c; R = HK.R
AFC = B_ / 'data/pv_sandbox/af_calibration'
OUT = AFC / 'plain_diag_20261027'
SRC = [('plan_prereg_20261027', 'B'), ('hard_key_prereg_20261027', 'B'), ('combo_prereg_20261027', 'B')]


def is_plain(L):
    f = c.P[L]['features']
    return R.unlock(L) == 0 and not f.get('eff_bomb') and not f.get('eff_grass') and not f.get('craft')


def main():
    by = {}
    for folder, opt in SRC:
        for line in (AFC / folder / 'rows.jsonl').read_text().splitlines():
            r = json.loads(line)
            if r['option'] != opt or not is_plain(r['L']): continue
            by.setdefault(r['L'], {}).setdefault(r['theta'], []).append(r)
    maps = {}
    for L, th in sorted(by.items()):
        if set(th) != set(R.THETAS): continue
        curve = {}
        for t, rs in th.items():
            g = sum(r['games'] for r in rs); w = sum(r['wins'] for r in rs)
            fr = {}
            for r in rs:
                for k, v in r['fail_reasons'].items(): fr[k] = fr.get(k, 0) + v
            curve[t] = dict(games=g, clear=w / g, fail={k: v / g for k, v in fr.items()})
        mix = sum(wt * curve[t]['clear'] for wt, t in zip(R.WEIGHTS, R.THETAS))
        af = c.target(L)[0]
        best = min(R.THETAS, key=lambda t: abs(curve[t]['clear'] - af))
        rng = (min(v['clear'] for v in curve.values()), max(v['clear'] for v in curve.values()))
        maps[L] = dict(features=c.P[L]['features'], af=af, af_fail=c.target(L)[1:], n=c.A[L]['clean_ft_n'], mix=mix, resid=mix - af,
                       curve=curve, nearest_theta=best, af_inside_curve=rng[0] <= af <= rng[1], curve_range=rng)
    # diagnostic simplex fit (grid .05) on plain maps: minimise mean squared clear error
    Ls = list(maps); grid = [i / 20 for i in range(21)]; best = None
    for w in itertools.product(grid, repeat=len(R.THETAS)):
        if abs(sum(w) - 1) > 1e-9: continue
        e = sum((sum(wi * maps[L]['curve'][t]['clear'] for wi, t in zip(w, R.THETAS)) - maps[L]['af']) ** 2 for L in Ls) / len(Ls)
        if best is None or e < best[0]: best = (e, w)
    cur = sum(maps[L]['resid'] ** 2 for L in Ls) / len(Ls)
    # population context (older v24 list, theta <= 1.0): plain maps, where AF sits vs the theta .55..1.0 band
    pop = json.loads((AFC / 'bot_v24/v24f_rows.json').read_text())['rows']; pc = {}
    for r in pop:
        if r['L'] in c.P and r['L'] in c.A and is_plain(r['L']) and HK.eligible(r['L']): pc.setdefault(r['L'], {})[r['theta']] = r['wins'] / r['games']
    ctx = {L: dict(af=c.target(L)[0], lo=min(v.values()), hi=max(v.values()), t10=v.get(1.0)) for L, v in pc.items() if len(v) == 4}
    above = sum(1 for v in ctx.values() if v['af'] > v['hi']); below = sum(1 for v in ctx.values() if v['af'] < v['lo'])
    out = dict(maps=maps, diag_fit=dict(weights=dict(zip(R.THETAS, best[1])), mse=best[0], current_mse=cur, n=len(Ls), note='DIAGNOSTIC ONLY'),
               population_context=dict(n=len(ctx), af_above_theta10_band=above, af_below_theta055_band=below,
                                       mean_af_minus_t10=sum(v['af'] - v['t10'] for v in ctx.values()) / len(ctx), maps=ctx))
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / 'existing.tmp').write_text(json.dumps(out, indent=1)); (OUT / 'existing.tmp').replace(OUT / 'existing.json')
    for L, m in maps.items():
        cv = ' '.join(f"{t}:{100 * m['curve'][t]['clear']:.0f}" for t in R.THETAS)
        print(L, {k: v for k, v in m['features'].items() if k != 'tiles'}, f"AF {100 * m['af']:.1f} mix {100 * m['mix']:.1f} resid {100 * m['resid']:+.1f}", cv, 'nearest', m['nearest_theta'], 'inside', m['af_inside_curve'])
    print('diag fit', out['diag_fit']); print('pop', {k: v for k, v in out['population_context'].items() if k != 'maps'})


if __name__ == '__main__':
    main()
