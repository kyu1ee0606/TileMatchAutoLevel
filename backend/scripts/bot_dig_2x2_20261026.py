"""PREREG (fixed before any run): container_dig_capacity 2x2 with bomb_threat_memory. Core 186b73ab... fixed.

Cells: B=baseline, M=bomb_threat_memory, G=container_dig_capacity, MG=both. Mixture/awareness not refit.
No-bomb maps: M==B and MG==G by construction (memory code only runs with bombs; its RNG never touches the main RNG);
those cells are not run, copied with flag 'structural_copy' (checked once in regress on L138).
Stages (separate seeds; maps fixed by features/n before viewing their AF rates for this experiment):
  regress: OFF L293 .85 18M x16 = 7; OFF L294 1.2 21M x32 = 23; M L294 1.2 21M x32 = 28; L138 .85 25M x16 M == B.
  D (dev; diagnosed container maps L138/L292/L306): seed25M, 16/theta, all cells run.
     Gate: G joint MSE < B over D maps, else stop (R/N skipped).
  R (same maps, new RNG; not independent maps): seed26M, 32/theta.
  N (new maps): bombN maps minus dev (313/297/298/332/296/303; B,M rows reused from bomb_memory_rerun seed22M x32 =
     same-seed paired reuse, not independent re-measurement; G,MG run) + key-stack maps by rule
     (unlockTile>0, stack, no craft, editor map same, not excluded, not used in 10-26 bot work, n>=100, top4 by n:
     242/287/339/327; all cells run at seed27M x32).
Support criteria for G vs B (and, reported separately, MG vs M):
  R: joint MSE improves AND clear MAE not worse.
  N: joint MSE improves AND clear MAE not worse AND Normal-fail share abs error improves on >= 2/3 of N container maps
     AND mean Bomb-fail share abs error over N bomb maps not worse.
  Never default; report only. Stop: swap<500MB, disk<10GiB, run games > 6400, 3600 s.
"""
import sys, json, time, hashlib, subprocess, re, shutil, os, math
from pathlib import Path
B_ = Path(__file__).resolve().parents[1]; sys.path[:0] = [str(B_), str(B_ / 'scripts')]
import bot_bomb_memory_key_20261026 as R
c = R.c
OUT = B_ / 'data/pv_sandbox/af_calibration/dig_2x2_20261026'
RERUN = B_ / 'data/pv_sandbox/af_calibration/bomb_memory_rerun_20261026'
CORE = '186b73ab6a1db93a62b534dd4a36eaf52f6d9eb7aa6fe42e469616d4d2ed97b7'
DEV = [138, 292, 306]
N_BOMB = [313, 297, 298, 332, 296, 303]
N_KEY = [242, 287, 339, 327]
CELLS = {'B': 'baseline', 'M': 'bomb_threat_memory', 'G': 'container_dig_capacity', 'MG': 'memory+dig'}
MAX_GAMES = 6400; MAX_SEC = 3600


def rules(cell):
    base = list(R.prior.BASE)
    return base + {'B': [], 'M': ['bomb_threat_memory'], 'G': ['container_dig_capacity'],
                   'MG': ['bomb_threat_memory', 'container_dig_capacity']}[cell]


def has_bomb(L): return bool(c.P[L]['features'].get('eff_bomb'))
def has_container(L): return bool(c.P[L]['features'].get('stack') or c.P[L]['features'].get('craft'))


def measure(phase, cell, L, t, n, seed):
    import dataclasses
    from collections import Counter
    start = time.time(); p = c.make_skill_profile(t, 'v2.4'); cfg = dict(p.gimmick_awareness); cfg.update(c.ev.v21.FIXED)
    cfg.update(alpha=dict(c.V21_AWARENESS_DEFAULTS['alpha']), gamma=dict(c.V21_AWARENESS_DEFAULTS['gamma']), exposure=c.EX[L], parity=None,
               auto_collect=int(float(c.P[L]['row'].get('autoCollectCount') or 0)), v24_expo=c.ev._gc_expo(c.P)[L], v24=rules(cell), grass_attention_cap=.65)
    p = dataclasses.replace(p, gimmick_awareness=cfg); b = c.BotSimulator(); b.set_rule_parity(p)
    layout = c.ev.base.level_layouts(c.P[L], 1)[0]; st = b._create_initial_state(layout, int(layout['max_moves'])); b._precompute_blocking_map(st)
    wins = 0; reasons = Counter()
    for g in range(n):
        b._rng.seed(seed + g); end = b._play_game(b._fast_copy_state(st), p)
        if end.cleared: wins += 1
        else: reasons[c.ev.base.fail_reason(b, end)] += 1
    return dict(phase=phase, option=cell, L=L, theta=t, games=n, wins=wins, fail_reasons=dict(reasons), seedbase=seed, sec=time.time() - start)


def append(row):
    with (OUT / 'rows.jsonl').open('a') as f:
        f.write(json.dumps(row) + '\n'); f.flush(); os.fsync(f.fileno())
    msg = f"ROW {row['phase']} {row['option']} {row['L']} {row['theta']} {row['wins']} {row['games']} {round(row.get('sec', 0), 2)}"
    print(msg, flush=True)
    with (OUT / 'progress.log').open('a') as f: f.write(msg + '\n')


def load_rows():
    p = OUT / 'rows.jsonl'
    if not p.exists(): return []
    out = []
    for line in p.read_text().splitlines():
        try: out.append(json.loads(line))
        except ValueError: break   # truncated tail line from an interrupted write: ignored, re-run
    return out


def ev(rows, phase, cell, Ls):
    return R.prior.evaluate([dict(r, phase=phase) for r in rows if r['phase'] == phase], phase, cell, Ls)


def judge(rows):
    out = {}
    def compare(phase, Ls, a, b):
        A, Bv = ev(rows, phase, a, Ls), ev(rows, phase, b, Ls)
        ra = {x['L']: x for x in A['rows']}; rb = {x['L']: x for x in Bv['rows']}
        cont = [L for L in Ls if has_container(L)]; bombs = [L for L in Ls if has_bomb(L)]
        norm_imp = sum(abs(ra[L]['predicted'][3] - ra[L]['actual'][3]) < abs(rb[L]['predicted'][3] - rb[L]['actual'][3]) for L in cont)
        bomb_a = sum(abs(ra[L]['predicted'][2] - ra[L]['actual'][2]) for L in bombs) / max(1, len(bombs))
        bomb_b = sum(abs(rb[L]['predicted'][2] - rb[L]['actual'][2]) for L in bombs) / max(1, len(bombs))
        return dict(joint_mse=(A['joint_mse'], Bv['joint_mse']), clear_mae=(A['clear_mae'], Bv['clear_mae']),
                    joint_improves=A['joint_mse'] < Bv['joint_mse'], clear_not_worse=A['clear_mae'] <= Bv['clear_mae'],
                    normal_improved_maps=norm_imp, container_maps=len(cont), normal_2of3=norm_imp >= math.ceil(2 * len(cont) / 3),
                    bomb_err_mean=(bomb_a, bomb_b), bomb_not_worse=bomb_a <= bomb_b)
    Nmaps = N_BOMB + N_KEY
    for a, b in (('G', 'B'), ('MG', 'M')):
        d = compare('D', DEV, a, b)
        res = dict(D=d, gate=d['joint_improves'])
        have = {(r['phase'], r['option'], r['L'], r['theta']) for r in rows}
        complete = lambda ph, Ls: all((ph, x, L, t) in have for x in (a, b) for L in Ls for t in R.THETAS)
        if complete('R', DEV) and complete('N', Nmaps):   # judge only complete stages (resume-safe)
            r_, n_ = compare('R', DEV, a, b), compare('N', Nmaps, a, b)
            res.update(R=r_, N=n_, support=res['gate'] and r_['joint_improves'] and r_['clear_not_worse'] and n_['joint_improves']
                       and n_['clear_not_worse'] and n_['normal_2of3'] and n_['bomb_not_worse'])
        out[f'{a}_vs_{b}'] = res
    return out


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    sha = hashlib.sha256((B_ / 'app/core/bot_simulator.py').read_bytes()).hexdigest(); assert sha == CORE == os.environ['EXPECTED_BOT_SHA256']
    rerun_raw = (RERUN / 'rows.jsonl').read_bytes()
    man = dict(source_hash=sha, cells=CELLS, thetas=R.THETAS, weights=R.WEIGHTS, cap=.65, base=R.prior.BASE,
               dev=DEV, n_bomb=N_BOMB, n_key=N_KEY, seeds=dict(D=25000000, R=26000000, N_bomb_reuse=22000000, N_key=27000000),
               games=dict(D=16, R=32, N=32), reuse=dict(source='bomb_memory_rerun_20261026', rows_sha256=hashlib.sha256(rerun_raw).hexdigest(),
                                                       note='B,M rows for N_BOMB: same-seed paired reuse, not independent re-measurement'),
               dig_constants='weight = stack_early_w (8.0, existing) x s(theta); no new fitted constants',
               excluded_from_N='L292/L306 (used as dev/diagnosis maps)', stop=dict(max_games=MAX_GAMES, max_sec=MAX_SEC, swap_mb=500, disk_gib=10),
               maps={L: dict(hash=hashlib.sha256(json.dumps(c.P[L]['map'], sort_keys=True).encode()).hexdigest(),
                             features=c.P[L]['features'], n=c.A[L]['clean_ft_n']) for L in DEV + N_BOMB + N_KEY},
               doc=__doc__)
    mp = OUT / 'manifest.json'
    if mp.exists(): assert json.loads(mp.read_text()) == json.loads(json.dumps(man))
    else:
        tmp = mp.with_suffix('.tmp'); tmp.write_text(json.dumps(man, indent=2)); os.replace(tmp, mp)
    rows = load_rows()
    if (OUT / 'rows.jsonl').exists():   # rewrite clean (drop truncated tail) atomically
        tmp = OUT / 'rows.tmp'; tmp.write_text(''.join(json.dumps(r) + '\n' for r in rows)); os.replace(tmp, OUT / 'rows.jsonl')
    have = {(r['phase'], r['option'], r['L'], r['theta']) for r in rows}
    src = [json.loads(x) for x in rerun_raw.decode().splitlines()]
    for r in src:   # copy each missing reused key individually (resume-safe even if interrupted mid-copy)
        if r['phase'] == 'bombN' and r['L'] in N_BOMB:
            cell = {'baseline': 'B', 'bomb_threat_memory': 'M'}[r['option']]
            if ('N', cell, r['L'], r['theta']) in have: continue
            row = dict(r, phase='N', option=cell, reused_from='bomb_memory_rerun_20261026'); append(row); rows.append(row)
            have.add(('N', cell, r['L'], r['theta']))
    done = {(r['phase'], r['option'], r['L'], r['theta']) for r in rows}; assert len(done) == len(rows)
    start = time.time(); spent = lambda: sum(r['games'] for r in rows if not r.get('reused_from') and not r.get('structural_copy'))

    def run(phase, cell, L, t, n, seed):
        if (phase, cell, L, t) in done: return True
        if not has_bomb(L) and cell in ('M', 'MG') and phase != 'regress':
            src = next(r for r in rows if r['phase'] == phase and r['option'] == {'M': 'B', 'MG': 'G'}[cell] and r['L'] == L and r['theta'] == t)
            row = dict(src, option=cell, structural_copy=True, sec=0.0)
        else:
            free = float(re.search(r'free = ([\d.]+)M', subprocess.check_output(['sysctl', 'vm.swapusage'], text=True))[1])
            if free < 500 or shutil.disk_usage(B_).free < 10 * 1024 ** 3 or spent() + n > MAX_GAMES or time.time() - start > MAX_SEC:
                print('STOP', free, spent(), flush=True); return False
            row = measure(phase, cell, L, t, n, seed)
        append(row); rows.append(row); done.add((phase, cell, L, t)); return True

    for cell, L, t, n, seed, want in (('B', 293, .85, 16, 18000000, 7), ('B', 294, 1.2, 32, 21000000, 23), ('M', 294, 1.2, 32, 21000000, 28)):
        if not run('regress', cell, L, t, n, seed): return
        got = next(r['wins'] for r in rows if (r['phase'], r['option'], r['L'], r['theta']) == ('regress', cell, L, t))
        if got != want: print('REGRESS_MISMATCH', cell, L, t, got, want, flush=True); return
    for cell in ('B', 'M'):
        if not run('regress', cell, 138, .85, 16, 25000000): return
    a, b = [next(r for r in rows if (r['phase'], r['option'], r['L'], r['theta']) == ('regress', x, 138, .85)) for x in ('B', 'M')]
    if (a['wins'], a['fail_reasons']) != (b['wins'], b['fail_reasons']): print('STRUCTURAL_MISMATCH', flush=True); return
    order = ('B', 'G', 'M', 'MG')
    for L in DEV:
        for cell in order:
            for t in R.THETAS:
                if not run('D', cell, L, t, 16, 25000000): return
    j = judge(rows); gate = j['G_vs_B']['gate']; print('GATE', gate, flush=True)
    if gate:
        for L in DEV:
            for cell in order:
                for t in R.THETAS:
                    if not run('R', cell, L, t, 32, 26000000): return
        for L in N_BOMB:
            for cell in ('G', 'MG'):
                for t in R.THETAS:
                    if not run('N', cell, L, t, 32, 22000000): return
        for L in N_KEY:
            for cell in order:
                for t in R.THETAS:
                    if not run('N', cell, L, t, 32, 27000000): return
    j = judge(rows)
    j.update(rows=len(rows), new_games=spent(), rows_sha256=hashlib.sha256((OUT / 'rows.jsonl').read_bytes()).hexdigest())
    tmp = OUT / 'judgement.tmp'; tmp.write_text(json.dumps(j, indent=2)); os.replace(tmp, OUT / 'judgement.json')
    print('DONE', len(rows), spent(), flush=True)


if __name__ == '__main__':
    main()
