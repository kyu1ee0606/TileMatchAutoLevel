"""PREREG doc 57 (2026-10-27): H = hard unused maps, B vs P2 / P12;  K = key maps, B vs K1 (key_first) / K2 (+key_container_dig).

Core bot_simulator.py fixed (sha CORE). Same frame as doc 56 §4: thetas/mixture [0,.1164,.1255,0,.7580], cap .65,
BASE rules, no refit. Tolerance 1e-12 on every "not worse" (<=) condition (pre-declared here).
USED_PRIOR = doc 56 USED (56 maps) + doc 56 DEV (6) + doc 56 N (16): maps whose AF-vs-bot error was viewed.
  (bot-only parity checks without AF comparison, e.g. key_parity_invariance_20261027, do not count.)
H maps (rule, chosen before any bot run on them): prep pool, not excluded, editor map same, n>=100, unlockTile 0,
  not USED_PRIOR; stratum (doc 56 priority) craft > key/stack > bomb > grass > plain; per stratum the 5 maps with the
  lowest AF clear rate (ties: larger n, then L), keeping only maps with AF clear <= .80 (hard). seed 38M x32.
K maps: unlockTile > 0. KD/KR = key maps in USED_PRIOR (dev; seed 39M x16 / 40M x32), KN = key maps not in
  USED_PRIOR with the same eligibility (seed 41M x32). Key-container stratum: stack vs craft.
Judge (candidate vs B, independent):
  H: joint MSE < B, clear MAE <= B, mean failure TV <= B, every stratum joint MSE <= 1.10 B.
  K: gate KD joint MSE < B (failed -> not run in KR/KN); KR joint < B and clear <= B;
     KN joint < B, clear <= B, TV <= B, each key-container stratum joint <= 1.10 B.
Target (reported, not judged): clear MAE <= 10%p.
Guard: run_guard_20261027 (pressure not critical, avail >= 1.5 GB, disk >= 10 GiB; wait <= 1 h then stop).
Stop: 24,000 games, 6 h. Writes only inside OUT. Resumable (row checkpoints, atomic manifest/judgement).
"""
import sys, json, time, hashlib, os, dataclasses
from pathlib import Path
from collections import Counter
B_ = Path(__file__).resolve().parents[1]; sys.path[:0] = [str(B_), str(B_ / 'scripts')]
import bot_plan_prereg_20261027 as PR
import bot_key_dig_candidate_20261027 as K
import run_guard_20261027 as G
c = PR.c; R = PR.R
OUT = B_ / 'data/pv_sandbox/af_calibration/hard_key_prereg_20261027'
CORE = 'cbc2e652c53d8d5f028d5513aa566f9285d3e5869663980b9b7d34cb34f68a8b'
TOL = 1e-12
CELLS = {'B': [], 'P2': ['public_craft_belief'], 'P12': ['skill_planning', 'public_craft_belief'],
         'K1': ['key_first'], 'K2': ['key_first', K.OPTION]}
SEEDS = dict(H=38000000, KD=39000000, KR=40000000, KN=41000000)
GAMES = dict(H=32, KD=16, KR=32, KN=32)
MAX_GAMES = 24000; MAX_SEC = 6 * 3600
PRIOR = B_ / 'data/pv_sandbox/af_calibration/plan_prereg_20261027/manifest.json'


def used_prior():
    man = json.loads(PRIOR.read_text())
    return sorted(set(PR.USED) | set(PR.DEV) | {int(L) for s in man['new'].values() for L in s})


def eligible(L):
    return not c.P[L].get('exclude') and c.P[L].get('map_match_editor') == 'same' and c.A[L]['clean_ft_n'] >= 100


def select():
    used = set(used_prior()); Ls = sorted(set(c.P) & set(c.A))
    pool = [L for L in Ls if eligible(L) and L not in used and R.unlock(L) == 0]
    H = {}
    for s in ('craft', 'key/stack', 'bomb', 'grass', 'plain'):
        cand = sorted([L for L in pool if PR.stratum(L) == s], key=lambda L: (c.target(L)[0], -c.A[L]['clean_ft_n'], L))[:5]
        H[s] = [L for L in cand if c.target(L)[0] <= .80]
    H = {s: v for s, v in H.items() if v}
    key = [L for L in Ls if R.unlock(L) > 0]
    kdev = [L for L in key if L in used]
    knew = [L for L in key if L not in used and eligible(L)]
    return H, kdev, knew


def kstratum(L):
    return 'craft' if c.P[L]['features'].get('craft') else 'stack'


def measure(phase, cell, L, t, n, seed):
    start = time.time(); p = c.make_skill_profile(t, 'v2.4'); cfg = dict(p.gimmick_awareness); cfg.update(c.ev.v21.FIXED)
    cfg.update(alpha=dict(c.V21_AWARENESS_DEFAULTS['alpha']), gamma=dict(c.V21_AWARENESS_DEFAULTS['gamma']), exposure=c.EX[L], parity=None,
               auto_collect=int(float(c.P[L]['row'].get('autoCollectCount') or 0)), v24_expo=c.ev._gc_expo(c.P)[L],
               v24=list(R.prior.BASE) + CELLS[cell], grass_attention_cap=.65)
    p = dataclasses.replace(p, gimmick_awareness=cfg)
    b = (K.KeyDigBot if cell == 'K2' else c.BotSimulator)(); b.set_rule_parity(p)
    layout = c.ev.base.level_layouts(c.P[L], 1)[0]; st = b._create_initial_state(layout, int(layout['max_moves'])); b._precompute_blocking_map(st)
    lock0 = sum(1 for s in st.dock if s.is_locked)
    wins = 0; reasons = Counter(); unlocked = 0
    for g in range(n):
        b._rng.seed(seed + g); end = b._play_game(b._fast_copy_state(st), p)
        if lock0 and sum(1 for s in end.dock if s.is_locked) < lock0: unlocked += 1
        if end.cleared: wins += 1
        else: reasons[c.ev.base.fail_reason(b, end)] += 1
    return dict(phase=phase, option=cell, L=L, theta=t, games=n, wins=wins, fail_reasons=dict(reasons), unlocked_games=unlocked,
                lock0=lock0, seedbase=seed, sec=time.time() - start)


def _p(name):
    p = OUT / name; assert p.resolve().parent == OUT.resolve(), p; return p


def load_rows():
    if not _p('rows.jsonl').exists(): return []
    out = []
    for line in _p('rows.jsonl').read_text().splitlines():
        try: out.append(json.loads(line))
        except ValueError: break
    return out


def ev(rows, phase, cell, Ls):
    return R.prior.evaluate([r for r in rows if r['phase'] == phase], phase, cell, Ls)


def compare(rows, phase, cand, Ls, strata):
    a, b = ev(rows, phase, cand, Ls), ev(rows, phase, 'B', Ls)
    st = {}
    for s, sl in strata.items():
        sa, sb = ev(rows, phase, cand, sl), ev(rows, phase, 'B', sl)
        st[s] = dict(joint_mse=(sa['joint_mse'], sb['joint_mse']), clear_mae=(sa['clear_mae'], sb['clear_mae']),
                     ok=sa['joint_mse'] <= 1.10 * sb['joint_mse'] + TOL)
    cond = dict(joint=a['joint_mse'] < b['joint_mse'], clear=a['clear_mae'] <= b['clear_mae'] + TOL,
                tv=PR.tv_mean(a) <= PR.tv_mean(b) + TOL, strata=all(v['ok'] for v in st.values()))
    return dict(joint_mse=(a['joint_mse'], b['joint_mse']), clear_mae=(a['clear_mae'], b['clear_mae']),
                tv=(PR.tv_mean(a), PR.tv_mean(b)), strata=st, conditions=cond, target_clear_mae_le_10pp=a['clear_mae'] <= .10)


def judge(rows, H, kdev, knew):
    have = {(r['phase'], r['option'], r['L'], r['theta']) for r in rows}
    full = lambda ph, cell, Ls: all((ph, cell, L, t) in have for L in Ls for t in R.THETAS)
    hm = [L for v in H.values() for L in v]; out = {}
    for cand in ('P2', 'P12'):
        if full('H', cand, hm) and full('H', 'B', hm):
            x = compare(rows, 'H', cand, hm, H); x['support'] = all(x['conditions'].values()); out['H_' + cand] = x
    if full('H', 'B', hm): out['H_B_clear_mae'] = ev(rows, 'H', 'B', hm)['clear_mae']
    ks = {s: [L for L in knew if kstratum(L) == s] for s in ('stack', 'craft')}
    ks = {s: v for s, v in ks.items() if v}
    for cand in ('K1', 'K2'):
        res = {}
        if full('KD', cand, kdev) and full('KD', 'B', kdev):
            a, b = ev(rows, 'KD', cand, kdev), ev(rows, 'KD', 'B', kdev)
            res['KD'] = dict(joint_mse=(a['joint_mse'], b['joint_mse']), clear_mae=(a['clear_mae'], b['clear_mae']))
            res['gate'] = a['joint_mse'] < b['joint_mse']
        if res.get('gate') and full('KR', cand, kdev) and full('KR', 'B', kdev) and full('KN', cand, knew) and full('KN', 'B', knew):
            r_ = compare(rows, 'KR', cand, kdev, {}); n_ = compare(rows, 'KN', cand, knew, ks)
            cond = dict(KR_joint=r_['conditions']['joint'], KR_clear=r_['conditions']['clear'], KN_joint=n_['conditions']['joint'],
                        KN_clear=n_['conditions']['clear'], KN_tv=n_['conditions']['tv'], KN_strata=n_['conditions']['strata'])
            res.update(KR=r_, KN=n_, conditions=cond, support=all(cond.values()))
        out[cand] = res
    return out


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    sha = hashlib.sha256((B_ / 'app/core/bot_simulator.py').read_bytes()).hexdigest(); assert sha == CORE == os.environ['EXPECTED_BOT_SHA256']
    kd_sha = hashlib.sha256((B_ / 'scripts/bot_key_dig_candidate_20261027.py').read_bytes()).hexdigest()
    doc = B_.parent / 'claudedocs/difficulty_personalization/57_bot_hard_maps_key_prereg_20261027.md'
    H, kdev, knew = select()
    if os.environ.get('SELECT_ONLY'):
        print(json.dumps(dict(H={s: [(L, round(c.target(L)[0], 3), c.A[L]['clean_ft_n']) for L in v] for s, v in H.items()},
                              kdev=kdev, knew=knew, kstrata={L: kstratum(L) for L in knew}, used_prior=used_prior(),
                              key_dig_sha=kd_sha)))
        return
    assert hashlib.sha256(doc.read_bytes()).hexdigest() == os.environ['PREREG_DOC_SHA256']
    man = dict(source_hash=sha, key_dig_candidate_sha256=kd_sha, prereg_doc_sha256=os.environ['PREREG_DOC_SHA256'], cells=CELLS,
               thetas=R.THETAS, weights=R.WEIGHTS, cap=.65, base=R.prior.BASE, tol=TOL, seeds=SEEDS, games=GAMES,
               H=H, kdev=kdev, knew=knew, used_prior=used_prior(), stop=dict(max_games=MAX_GAMES, max_sec=MAX_SEC, guard=G.__doc__),
               maps={L: dict(hash=hashlib.sha256(json.dumps(c.P[L]['map'], sort_keys=True).encode()).hexdigest(), features=c.P[L]['features'],
                             n=c.A[L]['clean_ft_n'], unlock=R.unlock(L)) for L in [L for v in H.values() for L in v] + kdev + knew},
               doc=__doc__)
    if _p('manifest.json').exists(): assert json.loads(_p('manifest.json').read_text()) == json.loads(json.dumps(man))
    else:
        tmp = _p('manifest.tmp'); tmp.write_text(json.dumps(man, indent=2)); os.replace(tmp, _p('manifest.json'))
    rows = load_rows()
    if _p('rows.jsonl').exists():
        tmp = _p('rows.tmp'); tmp.write_text(''.join(json.dumps(r) + '\n' for r in rows)); os.replace(tmp, _p('rows.jsonl'))
    done = {(r['phase'], r['option'], r['L'], r['theta']) for r in rows}; assert len(done) == len(rows)
    start = time.time(); spent = lambda: sum(r['games'] for r in rows)
    log = lambda m: (print(m, flush=True), _p('progress.log').open('a').write(m + '\n'))

    def run(phase, cell, L, t):
        if (phase, cell, L, t) in done: return True
        n = GAMES[phase]
        if spent() + n > MAX_GAMES or time.time() - start > MAX_SEC: log(f'STOP budget {spent()}'); return False
        if not G.wait_ok(log): return False
        row = measure(phase, cell, L, t, n, SEEDS[phase])
        with _p('rows.jsonl').open('a') as f:
            f.write(json.dumps(row) + '\n'); f.flush(); os.fsync(f.fileno())
        rows.append(row); done.add((phase, cell, L, t))
        log(f"ROW {phase} {cell} {L} {t} {row['wins']}/{n} unl{row['unlocked_games']} {row['sec']:.1f}s total{spent()}")
        return True

    for L in kdev:
        for cell in ('B', 'K1', 'K2'):
            for t in R.THETAS:
                if not run('KD', cell, L, t): return
    j = judge(rows, H, kdev, knew); passing = [k for k in ('K1', 'K2') if j[k].get('gate')]
    log(f"GATES {{'K1': {j['K1'].get('gate')}, 'K2': {j['K2'].get('gate')}}}")
    for L in [L for v in H.values() for L in v]:
        for cell in ('B', 'P2', 'P12'):
            for t in R.THETAS:
                if not run('H', cell, L, t): return
    if passing:
        for phase, Ls in (('KR', kdev), ('KN', knew)):
            for L in Ls:
                for cell in ['B'] + passing:
                    for t in R.THETAS:
                        if not run(phase, cell, L, t): return
    j = judge(rows, H, kdev, knew); j.update(rows=len(rows), games=spent(), rows_sha256=hashlib.sha256(_p('rows.jsonl').read_bytes()).hexdigest())
    tmp = _p('judgement.tmp'); tmp.write_text(json.dumps(j, indent=2)); os.replace(tmp, _p('judgement.json'))
    log(f'DONE {len(rows)} {spent()}')


if __name__ == '__main__':
    main()
