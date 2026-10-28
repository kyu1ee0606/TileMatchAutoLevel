"""Post-hoc PREREG judgement for bomb_memory_key_20261026 (no new games; reads rows.jsonl only).

Applies the criteria stored in manifest.json exactly and writes judgement.json beside summary.json.
"""
import sys, json, hashlib
from pathlib import Path
B = Path(__file__).resolve().parents[1]; sys.path[:0] = [str(B), str(B / 'scripts')]
import bot_bomb_memory_key_20261026 as R
OUT = R.OUT


def main(out_dir=None):
    OUTD = Path(out_dir) if out_dir else OUT
    man = json.loads((OUTD / 'manifest.json').read_text())
    raw = (OUTD / 'rows.jsonl').read_bytes()
    rows = [json.loads(x) for x in raw.decode().splitlines()]
    ev = lambda ph, o, Ls, rr=rows: R.evaluate(rr, ph, o, Ls)
    diag, newb, newk = man['bomb_diag'], man['bomb_new'], man['key_new']
    out = dict(rows_sha256=hashlib.sha256(raw).hexdigest(), rows=len(rows), games=sum(r['games'] for r in rows),
               criteria=man['criteria'])
    D = {o: ev('bombD', o, diag) for o in ('baseline', 'bomb_threat_memory')}
    out['gate'] = D['bomb_threat_memory']['joint_mse'] < D['baseline']['joint_mse']
    if not out['gate']:   # PREREG: gate failure skips bombR/bombN -> record development judgement only
        out['bomb'] = dict(support=False, metrics=dict(bombD={o: (D[o]['joint_mse'], D[o]['clear_mae']) for o in D}), note='gate failed')
        (OUTD / 'judgement.json').write_text(json.dumps(out, indent=2))
        print(json.dumps(dict(gate=False, bomb_support=False, rows_sha256=out['rows_sha256'][:16])))
        return
    Rr = {o: ev('bombR', o, diag) for o in ('baseline', 'bomb_threat_memory')}
    N = {o: ev('bombN', o, newb) for o in ('baseline', 'bomb_threat_memory')}
    nb = {x['L']: x for x in N['baseline']['rows']}; nm = {x['L']: x for x in N['bomb_threat_memory']['rows']}
    bomb_err = {L: (abs(nb[L]['predicted'][2] - nb[L]['actual'][2]), abs(nm[L]['predicted'][2] - nm[L]['actual'][2])) for L in newb}
    c = dict(
        bombR_joint_mse_improves=Rr['bomb_threat_memory']['joint_mse'] < Rr['baseline']['joint_mse'],
        bombN_joint_mse_improves=N['bomb_threat_memory']['joint_mse'] < N['baseline']['joint_mse'],
        bombN_clear_mae_not_worse=N['bomb_threat_memory']['clear_mae'] <= N['baseline']['clear_mae'],
        bombN_bomb_error_improved_maps=sum(m < b for b, m in bomb_err.values()))
    c['bombN_bomb_error_5of8'] = c['bombN_bomb_error_improved_maps'] >= 5
    out['bomb'] = dict(conditions=c, support=out['gate'] and all(v for k, v in c.items() if k != 'bombN_bomb_error_improved_maps'),
                       metrics=dict(bombD={o: (D[o]['joint_mse'], D[o]['clear_mae']) for o in D},
                                    bombR={o: (Rr[o]['joint_mse'], Rr[o]['clear_mae']) for o in Rr},
                                    bombN={o: (N[o]['joint_mse'], N[o]['clear_mae']) for o in N}),
                       bomb_error_per_map=bomb_err)
    kr = [r for r in rows if r['phase'] == 'key']
    if not kr:
        (OUTD / 'judgement.json').write_text(json.dumps(out, indent=2))
        print(json.dumps(dict(gate=out['gate'], bomb=out['bomb']['conditions'], bomb_support=out['bomb']['support'], rows_sha256=out['rows_sha256'][:16])))
        return
    done = {(r['option'], r['L'], r['theta']) for r in kr}
    copied = [dict(r, option='key_off') for r in kr if r['option'] == 'baseline' and r['theta'] != 1.2 and ('key_off', r['L'], r['theta']) not in done]
    K = {o: ev('key', o, newk, kr + copied) for o in ('baseline', 'key_off')}
    on = {x['L']: x for x in K['baseline']['rows']}; off = {x['L']: x for x in K['key_off']['rows']}
    improved = sum(abs(on[L]['clear_error']) < abs(off[L]['clear_error']) for L in newk)
    kc = dict(joint_mse_improves=K['baseline']['joint_mse'] < K['key_off']['joint_mse'], clear_error_improved_maps=improved,
              clear_error_4of6=improved >= 4)
    out['key'] = dict(conditions=kc, support=kc['joint_mse_improves'] and kc['clear_error_4of6'],
                      metrics={o: (K[o]['joint_mse'], K[o]['clear_mae']) for o in K})
    (OUTD / 'judgement.json').write_text(json.dumps(out, indent=2))
    print(json.dumps(dict(gate=out['gate'], bomb=out['bomb']['conditions'], bomb_support=out['bomb']['support'],
                          key=kc, key_support=out['key']['support'], rows_sha256=out['rows_sha256'][:16])))


if __name__ == '__main__':
    main(sys.argv[1] if len(sys.argv) > 1 else None)
