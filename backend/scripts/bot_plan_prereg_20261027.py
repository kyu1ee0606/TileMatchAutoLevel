"""PREREG (doc 56 §4, approved 2026-10-27): skill_planning (P1) / public_craft_belief (P2) / both (P12) vs B.

Core 4196e75a... fixed. Fixed mixture/cap/BASE rules, no refit (theta .55 / 1.0 weights are 0: their effect is
reported, not judged). bomb_threat_memory cells excluded (approved).
Stages: D dev (292,306 craft; 138 key+stack; 313,293 bomb; 152 grass) seed35M x16, all cells.
        Per-candidate gate: D joint MSE < B. Failed candidates are not run in R/N.
        R same maps seed36M x32 (not independent maps).
        N unused new maps: all maps used in 10-26/27 bot work excluded (USED), editor map same, not excluded, n>=100;
          stratum (priority): craft -> key/stack (lock or stack) -> bomb -> grass -> plain; top 5 by n per stratum
          (plain 3); selected by rule before viewing their AF rates; seed37M x32.
Support (candidate vs B): R joint MSE improves AND clear MAE not worse;
  N joint MSE improves AND clear MAE not worse AND mean failure TV not worse AND every stratum joint MSE <= 1.10 x B.
Target (reported separately): N clear MAE <= 10%p. Stop: swap<500MB, disk<10GiB, 22,000 games, 4 h.
Writes only inside OUT.
"""
import sys, json, time, hashlib, subprocess, re, shutil, os, math, dataclasses
from pathlib import Path
from collections import Counter
B_ = Path(__file__).resolve().parents[1]; sys.path[:0] = [str(B_), str(B_ / 'scripts')]
import bot_bomb_memory_key_20261026 as R
c = R.c
OUT = B_ / 'data/pv_sandbox/af_calibration/plan_prereg_20261027'
CORE = '4196e75a7356527fc5c073bbd97a00b115f1145feec2e80f7e5d988f8236cab4'
DEV = [292, 306, 138, 313, 293, 152]
CELLS = {'B': [], 'P1': ['skill_planning'], 'P2': ['public_craft_belief'], 'P12': ['skill_planning', 'public_craft_belief']}
USED = [51, 68, 81, 102, 111, 133, 138, 151, 152, 153, 154, 161, 164, 182, 184, 189, 198, 209, 224, 236, 241, 242, 251,
        276, 284, 287, 291, 292, 293, 294, 295, 296, 297, 298, 302, 303, 304, 306, 313, 314, 315, 324, 327, 329, 332, 334,
        336, 339, 343, 354, 355, 382, 396, 442, 448, 449]
PER = {'craft': 5, 'key/stack': 5, 'bomb': 5, 'grass': 5, 'plain': 3}
MAX_GAMES = 22000; MAX_SEC = 4 * 3600


def stratum(L):
    f = c.P[L]['features']
    if f.get('craft'): return 'craft'
    if R.unlock(L) > 0 or f.get('stack'): return 'key/stack'
    if f.get('eff_bomb'): return 'bomb'
    if f.get('eff_grass'): return 'grass'
    return 'plain'


def select_new():
    Ls = sorted(set(c.P) & set(c.A))
    ok = [L for L in Ls if L not in USED and not c.P[L].get('exclude') and c.P[L].get('map_match_editor') == 'same'
          and c.A[L]['clean_ft_n'] >= 100]
    out = {}
    for s, k in PER.items():
        out[s] = sorted([L for L in ok if stratum(L) == s], key=lambda L: (-c.A[L]['clean_ft_n'], L))[:k]
    return out


def measure(phase, cell, L, t, n, seed):
    from collections import Counter as Ctr
    start = time.time(); p = c.make_skill_profile(t, 'v2.4'); cfg = dict(p.gimmick_awareness); cfg.update(c.ev.v21.FIXED)
    cfg.update(alpha=dict(c.V21_AWARENESS_DEFAULTS['alpha']), gamma=dict(c.V21_AWARENESS_DEFAULTS['gamma']), exposure=c.EX[L], parity=None,
               auto_collect=int(float(c.P[L]['row'].get('autoCollectCount') or 0)), v24_expo=c.ev._gc_expo(c.P)[L],
               v24=list(R.prior.BASE) + CELLS[cell], grass_attention_cap=.65)
    p = dataclasses.replace(p, gimmick_awareness=cfg); b = c.BotSimulator(); b.set_rule_parity(p)
    layout = c.ev.base.level_layouts(c.P[L], 1)[0]; st = b._create_initial_state(layout, int(layout['max_moves'])); b._precompute_blocking_map(st)
    wins = 0; reasons = Ctr()
    for g in range(n):
        b._rng.seed(seed + g); end = b._play_game(b._fast_copy_state(st), p)
        if end.cleared: wins += 1
        else: reasons[c.ev.base.fail_reason(b, end)] += 1
    return dict(phase=phase, option=cell, L=L, theta=t, games=n, wins=wins, fail_reasons=dict(reasons), seedbase=seed, sec=time.time() - start)


def _p(name):
    p = OUT / name; assert p.resolve().parent == OUT.resolve(), p; return p


def append(row):
    with _p('rows.jsonl').open('a') as f:
        f.write(json.dumps(row) + '\n'); f.flush(); os.fsync(f.fileno())
    msg = f"ROW {row['phase']} {row['option']} {row['L']} {row['theta']} {row['wins']} {row['games']} {round(row['sec'], 2)}"
    print(msg, flush=True)
    with _p('progress.log').open('a') as f: f.write(msg + '\n')


def load_rows():
    if not _p('rows.jsonl').exists(): return []
    out = []
    for line in _p('rows.jsonl').read_text().splitlines():
        try: out.append(json.loads(line))
        except ValueError: break
    return out


def ev(rows, phase, cell, Ls):
    return R.prior.evaluate([r for r in rows if r['phase'] == phase], phase, cell, Ls)


def tv_mean(e):
    v = [x['failure_tv'] for x in e['rows'] if x['failure_tv'] is not None]
    return sum(v) / len(v) if v else 0.0


def judge(rows, new):
    have = {(r['phase'], r['option'], r['L'], r['theta']) for r in rows}
    complete = lambda ph, cell, Ls: all((ph, cell, L, t) in have for L in Ls for t in R.THETAS)
    nmaps = [L for s in new.values() for L in s]
    out = {}
    for cand in ('P1', 'P2', 'P12'):
        res = {}
        if complete('D', cand, DEV) and complete('D', 'B', DEV):
            a, b = ev(rows, 'D', cand, DEV), ev(rows, 'D', 'B', DEV)
            res['D'] = dict(joint_mse=(a['joint_mse'], b['joint_mse']), clear_mae=(a['clear_mae'], b['clear_mae']))
            res['gate'] = a['joint_mse'] < b['joint_mse']
        if res.get('gate') and complete('R', cand, DEV) and complete('N', cand, nmaps) and complete('N', 'B', nmaps):
            ra, rb = ev(rows, 'R', cand, DEV), ev(rows, 'R', 'B', DEV)
            na, nb = ev(rows, 'N', cand, nmaps), ev(rows, 'N', 'B', nmaps)
            strata = {}
            for s, Ls in new.items():
                sa, sb = ev(rows, 'N', cand, Ls), ev(rows, 'N', 'B', Ls)
                strata[s] = dict(joint_mse=(sa['joint_mse'], sb['joint_mse']), clear_mae=(sa['clear_mae'], sb['clear_mae']),
                                 ok=sa['joint_mse'] <= 1.10 * sb['joint_mse'])
            cond = dict(R_joint=ra['joint_mse'] < rb['joint_mse'], R_clear=ra['clear_mae'] <= rb['clear_mae'],
                        N_joint=na['joint_mse'] < nb['joint_mse'], N_clear=na['clear_mae'] <= nb['clear_mae'],
                        N_tv=tv_mean(na) <= tv_mean(nb), N_strata=all(v['ok'] for v in strata.values()))
            res.update(R=dict(joint_mse=(ra['joint_mse'], rb['joint_mse']), clear_mae=(ra['clear_mae'], rb['clear_mae'])),
                       N=dict(joint_mse=(na['joint_mse'], nb['joint_mse']), clear_mae=(na['clear_mae'], nb['clear_mae']),
                              tv=(tv_mean(na), tv_mean(nb))),
                       strata=strata, conditions=cond, support=all(cond.values()),
                       target_N_clear_mae_le_10pp=na['clear_mae'] <= 0.10)
        out[cand] = res
    if complete('N', 'B', nmaps):
        out['B_target_N_clear_mae'] = ev(rows, 'N', 'B', nmaps)['clear_mae']
    return out


def main():
    assert OUT.parent.name == 'af_calibration' and OUT.name == 'plan_prereg_20261027'
    OUT.mkdir(parents=True, exist_ok=True)
    sha = hashlib.sha256((B_ / 'app/core/bot_simulator.py').read_bytes()).hexdigest(); assert sha == CORE == os.environ['EXPECTED_BOT_SHA256']
    doc = B_.parent / 'claudedocs/difficulty_personalization/56_bot_planning_craft_belief_20261027.md'
    new = select_new()
    man = dict(source_hash=sha, prereg_doc_sha256=os.environ['PREREG_DOC_SHA256'], cells=CELLS, thetas=R.THETAS, weights=R.WEIGHTS,
               cap=.65, base=R.prior.BASE, dev=DEV, new=new, used_excluded=USED, per_stratum=PER,
               seeds=dict(D=35000000, R=36000000, N=37000000), games=dict(D=16, R=32, N=32),
               stop=dict(max_games=MAX_GAMES, max_sec=MAX_SEC, swap_mb=500, disk_gib=10),
               maps={L: dict(stratum=stratum(L), hash=hashlib.sha256(json.dumps(c.P[L]['map'], sort_keys=True).encode()).hexdigest(),
                             features=c.P[L]['features'], n=c.A[L]['clean_ft_n']) for L in DEV + [L for s in new.values() for L in s]},
               doc=__doc__)
    assert hashlib.sha256(doc.read_bytes()).hexdigest() == os.environ['PREREG_DOC_SHA256']
    if _p('manifest.json').exists(): assert json.loads(_p('manifest.json').read_text()) == json.loads(json.dumps(man))
    else:
        tmp = _p('manifest.tmp'); tmp.write_text(json.dumps(man, indent=2)); os.replace(tmp, _p('manifest.json'))
    print('NEW', json.dumps(new), flush=True)
    rows = load_rows()
    if _p('rows.jsonl').exists():
        tmp = _p('rows.tmp'); tmp.write_text(''.join(json.dumps(r) + '\n' for r in rows)); os.replace(tmp, _p('rows.jsonl'))
    done = {(r['phase'], r['option'], r['L'], r['theta']) for r in rows}; assert len(done) == len(rows)
    start = time.time(); spent = lambda: sum(r['games'] for r in rows)

    def run(phase, cell, L, t, n, seed):
        if (phase, cell, L, t) in done: return True
        free = float(re.search(r'free = ([\d.]+)M', subprocess.check_output(['sysctl', 'vm.swapusage'], text=True))[1])
        if free < 500 or shutil.disk_usage(B_).free < 10 * 1024 ** 3 or spent() + n > MAX_GAMES or time.time() - start > MAX_SEC:
            print('STOP', free, spent(), flush=True); return False
        row = measure(phase, cell, L, t, n, seed); append(row); rows.append(row); done.add((phase, cell, L, t)); return True

    for L in DEV:
        for cell in CELLS:
            for t in R.THETAS:
                if not run('D', cell, L, t, 16, 35000000): return
    j = judge(rows, new); passing = [k for k in ('P1', 'P2', 'P12') if j[k].get('gate')]
    print('GATES', {k: j[k].get('gate') for k in ('P1', 'P2', 'P12')}, flush=True)
    if passing:
        nmaps = [L for s in new.values() for L in s]
        for phase, Ls, n, seed in (('R', DEV, 32, 36000000), ('N', nmaps, 32, 37000000)):
            for L in Ls:
                for cell in ['B'] + passing:
                    for t in R.THETAS:
                        if not run(phase, cell, L, t, n, seed): return
    j = judge(rows, new); j.update(rows=len(rows), games=spent(), rows_sha256=hashlib.sha256(_p('rows.jsonl').read_bytes()).hexdigest())
    tmp = _p('judgement.tmp'); tmp.write_text(json.dumps(j, indent=2)); os.replace(tmp, _p('judgement.json'))
    print('DONE', len(rows), spent(), flush=True)


if __name__ == '__main__':
    main()
