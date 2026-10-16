import json, os, sys
sys.path.insert(0, '/Users/casualdev/TileMatchAutoLevel/backend/scripts'); sys.path.insert(0, '/Users/casualdev/TileMatchAutoLevel/backend')
import pv_verify_dda as Q

WORK = os.path.join(os.path.dirname(Q.VDIR), 'dda_sets', 'work')
RANGES = [("32-250", 32, 250), ("251-500", 251, 500), ("501-1000", 501, 1000), ("1001-1500", 1001, 1500)]
TS = {"e2": 1, "e1": 1, "h1": -1, "h2": -1}


def lv_list():
    return sorted(int(f[:4]) for f in os.listdir(Q.VDIR) if f[:4].isdigit() and f.endswith('.json') and len(f) == 9)


def classify(S):
    r, g = S['rep'], S['gen']
    mech = all(S['solv'].values()) and S['golden'] and S['invariantsOk']
    f = []
    if not mech: f.append('mech')
    if not all(r['outerOk'].values()): f.append('outerDelta<.10:' + ','.join(t for t, v in r['outerOk'].items() if not v))
    if not all(r['signOk'].values()) or not r['orderOk']: f.append('selThetaOrder')
    for t in ('e2', 'h2'):
        if t in g['dirTrust'] and not g['dirTrust'][t]['pass']: f.append('outerDir:' + t)
    for t in ('e1', 'h1'):
        if t in g['dirTrust'] and not g['dirTrust'][t]['pass']: f.append('innerDir:' + t)
    return f


def swap_ok(S, pair):
    """swap the two labels of an unstable inner pair, re-check all pass criteria (selection θ outer Δ / order, dirTrust)."""
    hi, lo = pair.split('>')
    r, g = S['rep'], S['gen']
    rates = dict(r['rates']); delta = dict(r['delta'])
    rates[hi], rates[lo] = rates[lo], rates[hi]; delta[hi], delta[lo] = delta[lo], delta[hi]
    outer = all(delta[t] * TS[t] >= Q.OUTER_MIN for t in ('e2', 'h2'))
    sign = all(delta[t] * TS[t] > 0 for t in delta)
    order_keys = [k for k in Q.ORDER if k in rates]
    order = all(rates[a] > rates[b] for a, b in zip(order_keys, order_keys[1:]))
    dt = {t: dict(v) for t, v in g['dirTrust'].items()}
    dt[hi], dt[lo] = dt[lo], dt[hi]
    dpass = {}
    for t, v in dt.items():  # kept was counted with the other label's sign; same side -> same sign, so pass carries over
        dpass[t] = v['pass']
    mech = all(S['solv'].values()) and S['golden'] and S['invariantsOk']
    return outer and sign and order and all(dpass.values()) and mech


def floor_flags(n):
    fp = os.path.join(WORK, f"{n:04d}", "final.json")
    if not os.path.exists(fp):
        return None
    d = json.load(open(fp))
    return ((d.get('tiers') or {}).get('h2') or {}).get('floorFlags')


def agg(levels, Ss):
    out = {"n": len(levels)}
    P = lambda fn: sum(1 for n in levels if fn(Ss[n]))
    out['pass'] = P(lambda S: S['pass']); out['outerPass'] = P(lambda S: S['outerPass'])
    out['5t'] = P(lambda S: S['tierCount'] == 4); out['5tPass'] = P(lambda S: S['tierCount'] == 4 and S['pass'])
    out['3t'] = P(lambda S: S['tierCount'] == 2); out['3tPass'] = P(lambda S: S['tierCount'] == 2 and S['pass'])
    out['mech'] = P(lambda S: all(S['solv'].values()) and S['golden'] and S['invariantsOk'])
    out['outerDeltaOk'] = P(lambda S: all(S['rep']['outerOk'].values()))
    out['orderOk'] = P(lambda S: S['rep']['orderOk'] and all(S['rep']['signOk'].values()))
    out['dirTrust'] = {t: [P(lambda S: t in S['gen']['dirTrust'] and S['gen']['dirTrust'][t]['pass']),
                           P(lambda S: t in S['gen']['dirTrust'])] for t in ('e2', 'e1', 'h1', 'h2')}
    out['dirPoints'] = {t: [sum(Ss[n]['gen']['dirTrust'][t]['kept'] for n in levels if t in Ss[n]['gen']['dirTrust']),
                            sum(Ss[n]['gen']['dirTrust'][t]['n'] for n in levels if t in Ss[n]['gen']['dirTrust'])]
                        for t in ('e2', 'e1', 'h1', 'h2')}
    ft = {}
    for n in levels:
        for x in classify(Ss[n]):
            k = x.split(':')[0] + (':' + x.split(':')[1] if ':' in x else '')
            ft[k] = ft.get(k, 0) + 1
    out['failTypes'] = dict(sorted(ft.items()))
    unst = {n: [p for p, v in Ss[n]['gen']['inner'].items() if v['unstable']] for n in levels}
    unst = {n: v for n, v in unst.items() if v}
    out['innerUnstable'] = sorted(unst)
    out['swapStrictOk'] = sorted(n for n, ps in unst.items() if all(swap_ok(Ss[n], p) for p in ps))
    out['demote3Ok'] = sorted(n for n in levels if Ss[n]['tierCount'] == 4 and not Ss[n]['pass'] and Ss[n]['outerPass'])
    out['passButUnstable'] = sorted(n for n in unst if Ss[n]['pass'])
    out['sensitive'] = P(lambda S: any(v['sensitive'] for v in S['gen']['dirTrust'].values()))
    ff = {k: 0 for k in ('abs20', 'abs10', 'abs05', 'rel50', 'none')}; miss = 0
    for n in levels:
        f = floor_flags(n)
        if not f: miss += 1; continue
        for k in ff: ff[k] += bool(f.get(k))
    out['h2FloorFlags'] = ff; out['h2FloorFlagsMissing'] = miss
    out['predOrder'] = P(lambda S: (S.get('pred') or {}).get('orderOk'))
    out['predH2Min'] = P(lambda S: (S.get('pred') or {}).get('h2MinOk'))
    out['predCount'] = P(lambda S: 'pred' in S)
    # pass rate split by floor tightness
    out['passByFloor'] = {}
    for k in ('abs05', 'rel50'):
        tight = [n for n in levels if (floor_flags(n) or {}).get(k)]
        loose = [n for n in levels if n not in tight]
        out['passByFloor'][k] = {"with": [sum(Ss[n]['pass'] for n in tight), len(tight)],
                                 "without": [sum(Ss[n]['pass'] for n in loose), len(loose)]}
    return out


Ss = {n: Q.summarize(json.load(open(os.path.join(Q.VDIR, f"{n:04d}.json")))) for n in lv_list()}
res = {}
for name, lo, hi in RANGES:
    L = [n for n in Ss if lo <= n <= hi]
    res[name] = agg(L, Ss)
res["501-1500"] = agg([n for n in Ss if 501 <= n <= 1500], Ss)
res["32-1500"] = agg(sorted(Ss), Ss)
res["perLevelFail"] = {n: classify(Ss[n]) for n in sorted(Ss) if not Ss[n]['pass']}
print(json.dumps(res, ensure_ascii=False, indent=1))
