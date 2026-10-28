"""PREREG (fixed before any run): dig_bomb_yield (G') vs fixed container_dig_capacity (Gf) vs baseline (B).

Core 8592974884ec8286... fixed (rollout dig-state fix + dig_bomb_yield, both opt-in). No refit, no new constants.
Cells: B = baseline rules; Gf = + container_dig_capacity (fixed rollout transition); Gp = Gf + dig_bomb_yield.
Stages (all cells run; no reuse; separate seeds):
  regress: B L293 .85 18M x16 = 7; B L294 1.2 21M x32 = 23; Gf L313 .65 22M x32 = 1; Gf L327 1.2 27M x32 = 15.
  D (dev; diagnosis maps 313/332/298/292): seed30M, 16/theta. Gate: Gp joint MSE < Gf over D, else stop.
  R (same maps, new RNG; not independent maps): seed31M, 32/theta.
  N (unused new maps): eff_bomb & (stack or craft) & editor map same & not excluded & never used in 10-26 bot work
     & n>=100, top 8 by n -> 302/304/291/295/314/336/329/334 (chosen before viewing their AF rates), seed32M, 32/theta.
Support (Gp vs Gf, primary; same test also reported for Gp vs B and Gf vs B):
  R: joint MSE improves AND clear MAE not worse.
  N: joint MSE improves AND clear MAE not worse AND Bomb-fail share abs error improves on >= 2/3 of N maps
     AND mean Normal-fail share abs error not worse.
  Never default; report only. Stop: swap<500MB, disk<10GiB, run games > 7000, 3600 s.
Writes only inside OUT (asserted).
"""
import sys, json, time, hashlib, subprocess, re, shutil, os, math
from pathlib import Path
B_ = Path(__file__).resolve().parents[1]; sys.path[:0] = [str(B_), str(B_ / 'scripts')]
import bot_bomb_memory_key_20261026 as R
c = R.c
OUT = B_ / 'data/pv_sandbox/af_calibration/dig_yield_20261026'
CORE = '8592974884ec8286046e2feaef2f8f1fc623a365916fd235333217adaea4609d'
DEV = [313, 332, 298, 292]
NEW = [302, 304, 291, 295, 314, 336, 329, 334]
CELLS = {'B': [], 'Gf': ['container_dig_capacity'], 'Gp': ['container_dig_capacity', 'dig_bomb_yield']}
MAX_GAMES = 7000; MAX_SEC = 3600


def measure(phase, cell, L, t, n, seed):
    import dataclasses
    from collections import Counter
    start = time.time(); p = c.make_skill_profile(t, 'v2.4'); cfg = dict(p.gimmick_awareness); cfg.update(c.ev.v21.FIXED)
    cfg.update(alpha=dict(c.V21_AWARENESS_DEFAULTS['alpha']), gamma=dict(c.V21_AWARENESS_DEFAULTS['gamma']), exposure=c.EX[L], parity=None,
               auto_collect=int(float(c.P[L]['row'].get('autoCollectCount') or 0)), v24_expo=c.ev._gc_expo(c.P)[L],
               v24=list(R.prior.BASE) + CELLS[cell], grass_attention_cap=.65)
    p = dataclasses.replace(p, gimmick_awareness=cfg); b = c.BotSimulator(); b.set_rule_parity(p)
    layout = c.ev.base.level_layouts(c.P[L], 1)[0]; st = b._create_initial_state(layout, int(layout['max_moves'])); b._precompute_blocking_map(st)
    wins = 0; reasons = Counter()
    for g in range(n):
        b._rng.seed(seed + g); end = b._play_game(b._fast_copy_state(st), p)
        if end.cleared: wins += 1
        else: reasons[c.ev.base.fail_reason(b, end)] += 1
    return dict(phase=phase, option=cell, L=L, theta=t, games=n, wins=wins, fail_reasons=dict(reasons), seedbase=seed, sec=time.time() - start)


def _path(name):
    p = OUT / name
    assert p.resolve().parent == OUT.resolve(), p
    return p


def append(row):
    with _path('rows.jsonl').open('a') as f:
        f.write(json.dumps(row) + '\n'); f.flush(); os.fsync(f.fileno())
    msg = f"ROW {row['phase']} {row['option']} {row['L']} {row['theta']} {row['wins']} {row['games']} {round(row['sec'], 2)}"
    print(msg, flush=True)
    with _path('progress.log').open('a') as f: f.write(msg + '\n')


def load_rows():
    p = _path('rows.jsonl')
    if not p.exists(): return []
    out = []
    for line in p.read_text().splitlines():
        try: out.append(json.loads(line))
        except ValueError: break
    return out


def ev(rows, phase, cell, Ls):
    return R.prior.evaluate([r for r in rows if r['phase'] == phase], phase, cell, Ls)


def compare(rows, phase, Ls, a, b):
    A, Bv = ev(rows, phase, a, Ls), ev(rows, phase, b, Ls)
    ra = {x['L']: x for x in A['rows']}; rb = {x['L']: x for x in Bv['rows']}
    bomb_imp = sum(abs(ra[L]['predicted'][2] - ra[L]['actual'][2]) < abs(rb[L]['predicted'][2] - rb[L]['actual'][2]) for L in Ls)
    na = sum(abs(ra[L]['predicted'][3] - ra[L]['actual'][3]) for L in Ls) / len(Ls)
    nb = sum(abs(rb[L]['predicted'][3] - rb[L]['actual'][3]) for L in Ls) / len(Ls)
    return dict(joint_mse=(A['joint_mse'], Bv['joint_mse']), clear_mae=(A['clear_mae'], Bv['clear_mae']),
                joint_improves=A['joint_mse'] < Bv['joint_mse'], clear_not_worse=A['clear_mae'] <= Bv['clear_mae'],
                bomb_improved_maps=bomb_imp, maps=len(Ls), bomb_2of3=bomb_imp >= math.ceil(2 * len(Ls) / 3),
                normal_err_mean=(na, nb), normal_not_worse=na <= nb)


def judge(rows):
    have = {(r['phase'], r['option'], r['L'], r['theta']) for r in rows}
    complete = lambda ph, Ls: all((ph, x, L, t) in have for x in CELLS for L in Ls for t in R.THETAS)
    out = {}
    for a, b in (('Gp', 'Gf'), ('Gp', 'B'), ('Gf', 'B')):
        res = {}
        if complete('D', DEV):
            res['D'] = compare(rows, 'D', DEV, a, b); res['gate'] = res['D']['joint_improves']
        if complete('R', DEV) and complete('N', NEW):
            r_, n_ = compare(rows, 'R', DEV, a, b), compare(rows, 'N', NEW, a, b)
            res.update(R=r_, N=n_, support=res['gate'] and r_['joint_improves'] and r_['clear_not_worse'] and n_['joint_improves']
                       and n_['clear_not_worse'] and n_['bomb_2of3'] and n_['normal_not_worse'])
        out[f'{a}_vs_{b}'] = res
    return out


def main():
    assert OUT.parent.name == 'af_calibration' and OUT.name == 'dig_yield_20261026'
    OUT.mkdir(parents=True, exist_ok=True)
    sha = hashlib.sha256((B_ / 'app/core/bot_simulator.py').read_bytes()).hexdigest(); assert sha == CORE == os.environ['EXPECTED_BOT_SHA256']
    man = dict(source_hash=sha, cells=CELLS, thetas=R.THETAS, weights=R.WEIGHTS, cap=.65, base=R.prior.BASE, dev=DEV, new=NEW,
               seeds=dict(D=30000000, R=31000000, N=32000000), games=dict(D=16, R=32, N=32),
               stop=dict(max_games=MAX_GAMES, max_sec=MAX_SEC, swap_mb=500, disk_gib=10),
               maps={L: dict(hash=hashlib.sha256(json.dumps(c.P[L]['map'], sort_keys=True).encode()).hexdigest(),
                             features=c.P[L]['features'], n=c.A[L]['clean_ft_n']) for L in DEV + NEW}, doc=__doc__)
    mp = _path('manifest.json')
    if mp.exists(): assert json.loads(mp.read_text()) == json.loads(json.dumps(man))
    else:
        tmp = _path('manifest.tmp'); tmp.write_text(json.dumps(man, indent=2)); os.replace(tmp, mp)
    rows = load_rows()
    if _path('rows.jsonl').exists():
        tmp = _path('rows.tmp'); tmp.write_text(''.join(json.dumps(r) + '\n' for r in rows)); os.replace(tmp, _path('rows.jsonl'))
    done = {(r['phase'], r['option'], r['L'], r['theta']) for r in rows}; assert len(done) == len(rows)
    start = time.time(); spent = lambda: sum(r['games'] for r in rows)

    def run(phase, cell, L, t, n, seed):
        if (phase, cell, L, t) in done: return True
        free = float(re.search(r'free = ([\d.]+)M', subprocess.check_output(['sysctl', 'vm.swapusage'], text=True))[1])
        if free < 500 or shutil.disk_usage(B_).free < 10 * 1024 ** 3 or spent() + n > MAX_GAMES or time.time() - start > MAX_SEC:
            print('STOP', free, spent(), flush=True); return False
        row = measure(phase, cell, L, t, n, seed); append(row); rows.append(row); done.add((phase, cell, L, t)); return True

    for cell, L, t, n, seed, want in (('B', 293, .85, 16, 18000000, 7), ('B', 294, 1.2, 32, 21000000, 23),
                                      ('Gf', 313, .65, 32, 22000000, 1), ('Gf', 327, 1.2, 32, 27000000, 15)):
        if not run('regress', cell, L, t, n, seed): return
        got = next(r['wins'] for r in rows if (r['phase'], r['option'], r['L'], r['theta']) == ('regress', cell, L, t))
        if got != want: print('REGRESS_MISMATCH', cell, L, t, got, want, flush=True); return
    for L in DEV:
        for cell in CELLS:
            for t in R.THETAS:
                if not run('D', cell, L, t, 16, 30000000): return
    j = judge(rows); gate = j['Gp_vs_Gf']['gate']; print('GATE', gate, flush=True)
    if gate:
        for phase, Ls, seed in (('R', DEV, 31000000), ('N', NEW, 32000000)):
            for L in Ls:
                for cell in CELLS:
                    for t in R.THETAS:
                        if not run(phase, cell, L, t, 32, seed): return
    j = judge(rows); j.update(rows=len(rows), games=spent(), rows_sha256=hashlib.sha256(_path('rows.jsonl').read_bytes()).hexdigest())
    tmp = _path('judgement.tmp'); tmp.write_text(json.dumps(j, indent=2)); os.replace(tmp, _path('judgement.json'))
    print('DONE', len(rows), spent(), flush=True)


if __name__ == '__main__':
    main()
