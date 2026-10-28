"""Doc 59 adoption impact (read-only): which official levels L32-1530 contain a COMBO trigger (unlockTile>0 -> K1;
craft container -> P2; bomb effect -> C), crossed with the DDA screen_refine final status. Game shards read via git show
(HEAD, read-only). Writes combo_prereg_20261027/impact.json."""
import sys, json, csv, collections
from pathlib import Path
B_ = Path(__file__).resolve().parents[1]; sys.path[:0] = [str(B_), str(B_ / 'scripts')]
import bot_af_L32_500 as SH
OUT = B_ / 'data/pv_sandbox/af_calibration/combo_prereg_20261027'
tab = SH._git_key('HEAD', 'levels'); keys = tab['__keys']; rows = {}
for v in tab['__vals']:
    o = {keys[i]: v[i] for i in range(min(len(keys), len(v)))}; rows[str(o.get('id'))] = o
maps = {}
for i in range(16): maps.update(SH._git_key('HEAD', f'levelmap_level_{i}'))
final = {int(r['level']): r for r in csv.DictReader(open(B_ / 'data/dda_seeds/screen_refine_20261026/final_levels.csv'))}
def feats(m):
    f = set()
    for lk, lv in m.items():
        if not (lk.startswith('layer_') and isinstance(lv, dict) and isinstance(lv.get('tiles'), dict)): continue
        for td in lv['tiles'].values():
            t = str(td[0]); e = str(td[1]) if len(td) > 1 and td[1] else ''
            if t.startswith('craft'): f.add('craft')
            if e.startswith('bomb'): f.add('bomb')
    return f
out = {}; cnt = collections.Counter(); bystatus = collections.Counter()
for L in range(32, 1531):
    k = f'level_{L}'; m = maps.get(k); r = rows.get(k)
    if m is None or r is None: continue
    f = feats(m)
    if int(float(r.get('unlockTile') or 0)) > 0: f.add('key')
    trig = sorted(f & {'key', 'craft', 'bomb'})
    st = final.get(L, {}).get('final', '')
    out[L] = dict(triggers=trig, dda_final=st)
    if trig:
        cnt['any'] += 1
        for t in trig: cnt[t] += 1
        bystatus[st] += 1
OUT.mkdir(parents=True, exist_ok=True)
(OUT / 'impact.tmp').write_text(json.dumps(dict(levels=out, counts=cnt, by_dda_final=bystatus), ensure_ascii=False, indent=1))
(OUT / 'impact.tmp').replace(OUT / 'impact.json')
print('levels', len(out), dict(cnt)); print(dict(bystatus))
print('L32-500 any', sum(1 for L, v in out.items() if L <= 500 and v['triggers']), 'L501-1530 any', sum(1 for L, v in out.items() if L > 500 and v['triggers']))
