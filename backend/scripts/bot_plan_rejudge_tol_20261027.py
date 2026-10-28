"""Post-hoc numeric-tolerance rejudge of plan_prereg_20261027 (doc 56 §6, user-approved 2026-10-27). No new games.

Original machine judgement (judgement.json) is kept untouched. This re-evaluates the SAME rows with the SAME
judge, except every "not worse" (<=) comparison gets an absolute tolerance TOL = 1e-12 (float noise only;
e.g. L84 TV 5.0e-16 vs 3.9e-16). Strict "improves" (<) conditions are unchanged (no tolerance).
Writes only inside OUT.
"""
import sys, json, hashlib, os
from pathlib import Path
B_ = Path(__file__).resolve().parents[1]; sys.path[:0] = [str(B_), str(B_ / 'scripts')]
import bot_plan_prereg_20261027 as PR
SRC = B_ / 'data/pv_sandbox/af_calibration/plan_prereg_20261027'
OUT = B_ / 'data/pv_sandbox/af_calibration/plan_prereg_rejudge_tol_20261027'
TOL = 1e-12


def main():
    rows = [json.loads(x) for x in (SRC / 'rows.jsonl').read_text().splitlines()]
    man = json.loads((SRC / 'manifest.json').read_text())
    new = {s: [int(L) for L in Ls] for s, Ls in man['new'].items()}
    nmaps = [L for s in new.values() for L in s]
    out = dict(tolerance=TOL, source_rows_sha256=hashlib.sha256((SRC / 'rows.jsonl').read_bytes()).hexdigest(),
               source_judgement_sha256=hashlib.sha256((SRC / 'judgement.json').read_bytes()).hexdigest(),
               note='post-hoc numeric tolerance on <= conditions only; original judgement.json unchanged', cands={})
    orig = json.loads((SRC / 'judgement.json').read_text())
    for cand in ('P1', 'P2', 'P12'):
        if not orig[cand].get('gate'):
            out['cands'][cand] = dict(gate=False); continue
        ra, rb = PR.ev(rows, 'R', cand, PR.DEV), PR.ev(rows, 'R', 'B', PR.DEV)
        na, nb = PR.ev(rows, 'N', cand, nmaps), PR.ev(rows, 'N', 'B', nmaps)
        strata = {s: (PR.ev(rows, 'N', cand, Ls)['joint_mse'], PR.ev(rows, 'N', 'B', Ls)['joint_mse']) for s, Ls in new.items()}
        cond = dict(R_joint=ra['joint_mse'] < rb['joint_mse'], R_clear=ra['clear_mae'] <= rb['clear_mae'] + TOL,
                    N_joint=na['joint_mse'] < nb['joint_mse'], N_clear=na['clear_mae'] <= nb['clear_mae'] + TOL,
                    N_tv=PR.tv_mean(na) <= PR.tv_mean(nb) + TOL,
                    N_strata=all(a <= 1.10 * b + TOL for a, b in strata.values()))
        out['cands'][cand] = dict(gate=True, conditions=cond, support=all(cond.values()),
                                  original_conditions=orig[cand]['conditions'], original_support=orig[cand]['support'],
                                  N_tv=(PR.tv_mean(na), PR.tv_mean(nb)), strata=strata)
    OUT.mkdir(parents=True, exist_ok=True)
    tmp = OUT / 'rejudge.tmp'; tmp.write_text(json.dumps(out, indent=2)); os.replace(tmp, OUT / 'rejudge.json')
    for k, v in out['cands'].items():
        print(k, 'support', v.get('support'), 'orig', v.get('original_support'), v.get('conditions'))


if __name__ == '__main__':
    main()
