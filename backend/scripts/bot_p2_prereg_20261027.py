"""PREREG doc 68 (2026-10-27): rule-parity fix P2 — B' (current default, core 39d2de55, prior.BASE incl. K1C)
vs B'+public_craft_belief (P2: unspawned craft contents = public remain counter, types sampled by the triplet rule;
without it the theta>1 search is refused whenever an unspawned craft tile remains, bot_simulator.py:5589; doc 67).

Games per map x cell: theta .65 32 + .85 32 + 1.2 128 = 192 (weights .1164/.1255/.7580; .55/1.0 weight 0, not run).
Random-layout maps: bot_layouts_util_20261027 (16 layouts). Seeds: N 68M, Rp 69M (+ layout*1000 + game).
Maps (rule, before any AF-vs-bot error of these runs is seen):
  exposure = p2_prereg_20261027/exposure.json (measured rows of every output folder, docs 56-67 included).
  eligible = prep pool (L32-500, the only local AF cache), not excluded, editor map same, AF n >= 100, unlockTile 0,
             with a craft container.  Only tier 1 (no AF-compare exposure).
  selection: all random-layout maps; all fixed maps with AF clear < .95; fixed maps with AF >= .95 by AF n desc
             (ties L) until 20 maps in total.
  stratum: craft-random / craft-fixed.
Stages: N = 20 maps, cells B' / P2.  Rp (report) = first random-layout map, new seed.
Judge (P2 vs B', N, tolerance 1e-12 on <=): joint MSE < B'; clear MAE <= B'; every stratum joint <= 1.10 x B' OR
  joint - B' <= 0.002; failure-category MAE (unconditional Grass/Bomb/Normal) <= B'.  TV reported only.
Guard run_guard_20261027; STOP flag OUT/STOP; stop 8,500 games / 8 h.
"""
import sys, json, time, hashlib, os, dataclasses
from pathlib import Path
from collections import Counter
B_ = Path(__file__).resolve().parents[1]; sys.path[:0] = [str(B_), str(B_ / 'scripts')]
import bot_stack_early_prereg_20261027 as S62
import bot_layouts_util_20261027 as LU
import run_guard_20261027 as G
c = S62.c; R = S62.R; HK = S62.HK
AFC = B_ / 'data/pv_sandbox/af_calibration'
OUT = AFC / 'p2_prereg_20261027'
CORE = '39d2de55778afa1e1cc605b56c27773d2dcd961743b2e3dca52d79acc3a80c04'
TOL = 1e-12; ABS_ALLOW = 0.002
GAMES = {.65: 32, .85: 32, 1.2: 128}; THETAS = list(GAMES)
W = dict(zip(R.THETAS, R.WEIGHTS)); assert W[.55] == 0 and W[1.0] == 0
BASE = list(R.prior.BASE)
CELLS = {"B'": [], 'P2': ['public_craft_belief']}
SEEDS = dict(N=68000000, Rp=69000000)
MIN_MAPS = 12; MAX_GAMES = 8500; MAX_SEC = 8 * 3600; N_MAPS = 20
band = S62.band
STRATA = ['craft-random', 'craft-fixed']


def stratum(L):
    return 'craft-random' if c.P[L]['mode'] == 'random' else 'craft-fixed'


def select():
    e = json.loads((OUT / 'exposure.json').read_text())
    expo = lambda L: any(e['kind'][k] == 'af_compare' and L in v for k, v in e['folders'].items())
    el = [L for L in sorted(set(c.P) & set(c.A)) if HK.eligible(L) and R.unlock(L) == 0 and c.P[L]['features'].get('craft') and not expo(L)]
    key = lambda L: (-c.A[L]['clean_ft_n'], L)
    rnd = sorted([L for L in el if c.P[L]['mode'] == 'random'], key=key)
    hard = sorted([L for L in el if c.P[L]['mode'] != 'random' and c.target(L)[0] < .95], key=key)
    easy = sorted([L for L in el if c.P[L]['mode'] != 'random' and c.target(L)[0] >= .95], key=key)
    target = rnd + hard + easy[:max(0, N_MAPS - len(rnd) - len(hard))]
    return target, []


def measure(phase, cell, L, t, seed):
    start = time.time(); p = c.make_skill_profile(t, 'v2.4'); cfg = dict(p.gimmick_awareness); cfg.update(c.ev.v21.FIXED)
    cfg.update(alpha=dict(c.V21_AWARENESS_DEFAULTS['alpha']), gamma=dict(c.V21_AWARENESS_DEFAULTS['gamma']), exposure=c.EX[L], parity=None,
               auto_collect=int(float(c.P[L]['row'].get('autoCollectCount') or 0)), v24_expo=c.ev._gc_expo(c.P)[L],
               v24=BASE + CELLS[cell], grass_attention_cap=.65)
    p = dataclasses.replace(p, gimmick_awareness=cfg)
    plan = LU.layouts_for(c, L, GAMES[t])
    wins = 0; reasons = Counter(); n = 0
    for li, (lay, ng, _) in enumerate(plan):
        b = c.BotSimulator(); b.set_rule_parity(p)
        st = b._create_initial_state(json.loads(json.dumps(lay)), int(lay['max_moves'])); b._precompute_blocking_map(st)
        for g in range(ng):
            b._rng.seed(seed + li * 1000 + g); end = b._play_game(b._fast_copy_state(st), p); n += 1
            if end.cleared: wins += 1
            else: reasons[c.ev.base.fail_reason(b, end)] += 1
    return dict(phase=phase, option=cell, L=L, theta=t, games=n, layouts=len(plan), wins=wins, fail_reasons=dict(reasons),
                seedbase=seed, sec=time.time() - start)


def evaluate(rows, phase, cell, Ls):
    d = {(r['L'], r['theta']): r for r in rows if r['phase'] == phase and r['option'] == cell}
    out = []
    for L in Ls:
        vs = [c.vector(d[L, t]) for t in THETAS]; ws = [W[t] for t in THETAS]
        p = [sum(w * v[j] for w, v in zip(ws, vs)) for j in range(len(c.CATS))]; a = c.target(L)
        out.append(dict(L=L, predicted=p, actual=a, clear_error=p[0] - a[0], joint_mse=sum((x - y) ** 2 for x, y in zip(p, a)) / len(c.CATS),
                        cat_mae=sum(abs(p[j] - a[j]) for j in (1, 2, 3)) / 3,
                        failure_tv=sum(abs(x / (1 - p[0]) - y / (1 - a[0])) for x, y in zip(p[1:], a[1:])) / 2 if p[0] < 1 and a[0] < 1 else None))
    tv = [x['failure_tv'] for x in out if x['failure_tv'] is not None]
    return dict(rows=out, joint_mse=sum(x['joint_mse'] for x in out) / len(out), clear_mae=sum(abs(x['clear_error']) for x in out) / len(out),
                cat_mae=sum(x['cat_mae'] for x in out) / len(out), tv=sum(tv) / len(tv) if tv else 0.0)


def judge(rows, Ls, rp):
    have = {(r['phase'], r['option'], r['L'], r['theta']) for r in rows}
    full = lambda ph, ls: all((ph, x, L, t) in have for x in CELLS for L in ls for t in THETAS)
    if not full('N', Ls): return {}
    a, b = evaluate(rows, 'N', 'P2', Ls), evaluate(rows, 'N', "B'", Ls)
    strata = {}
    for s in STRATA:
        sl = [L for L in Ls if stratum(L) == s]
        if not sl: continue
        sa, sb = evaluate(rows, 'N', 'P2', sl), evaluate(rows, 'N', "B'", sl)
        strata[s] = dict(n=len(sl), **{k: (sa[k], sb[k]) for k in ('joint_mse', 'clear_mae', 'cat_mae', 'tv')},
                         ok=(sa['joint_mse'] <= 1.10 * sb['joint_mse'] + TOL) or (sa['joint_mse'] - sb['joint_mse'] <= ABS_ALLOW + TOL),
                         ok_ratio=sa['joint_mse'] <= 1.10 * sb['joint_mse'] + TOL)
    bands = {}
    for bd in S62.BANDS:
        bl = [L for L in Ls if band(L) == bd]
        if bl:
            ba, bb = evaluate(rows, 'N', 'P2', bl), evaluate(rows, 'N', "B'", bl)
            bands[bd] = dict(n=len(bl), **{k: (ba[k], bb[k]) for k in ('joint_mse', 'clear_mae', 'cat_mae', 'tv')})
    cond = dict(joint=a['joint_mse'] < b['joint_mse'], clear=a['clear_mae'] <= b['clear_mae'] + TOL,
                strata=all(v['ok'] for v in strata.values()), category=a['cat_mae'] <= b['cat_mae'] + TOL)
    out = dict(N={k: (a[k], b[k]) for k in ('joint_mse', 'clear_mae', 'cat_mae', 'tv')}, strata=strata, bands=bands, conditions=cond,
               support=all(cond.values()), target_clear_mae_lt_10pp=dict(P2=a['clear_mae'] < .10, B=b['clear_mae'] < .10))
    if full('Rp', rp):
        ra, rb = evaluate(rows, 'Rp', 'P2', rp), evaluate(rows, 'Rp', "B'", rp)
        na, nb = evaluate(rows, 'N', 'P2', rp), evaluate(rows, 'N', "B'", rp)
        out['Rp'] = dict(maps=rp, new_seed={k: (ra[k], rb[k]) for k in ('joint_mse', 'clear_mae')}, same_maps_N={k: (na[k], nb[k]) for k in ('joint_mse', 'clear_mae')})
    return out


def _p(name):
    p = OUT / name; assert p.resolve().parent == OUT.resolve(), p; return p


def main():
    sha = hashlib.sha256((B_ / 'app/core/bot_simulator.py').read_bytes()).hexdigest(); assert sha == CORE == os.environ['EXPECTED_BOT_SHA256']
    exp_sha = hashlib.sha256((OUT / 'exposure.json').read_bytes()).hexdigest()
    target, control = select(); Ls = target + control; rp = [L for L in target if c.P[L]['mode'] == 'random'][:1]
    if os.environ.get('SELECT_ONLY'):
        print(json.dumps(dict(target=[(L, stratum(L), round(c.target(L)[0], 3), c.A[L]['clean_ft_n'], c.P[L]['mode']) for L in target],
                              control=[(L, round(c.target(L)[0], 3), c.A[L]['clean_ft_n'], c.P[L]['mode']) for L in control],
                              n_target=len(target), rp=rp, exp_sha=exp_sha, games=2 * 192 * (len(Ls) + len(rp)))))
        return
    if len(target) < MIN_MAPS: print('TOO_FEW_MAPS', len(target)); sys.exit(3)
    doc = B_.parent / 'claudedocs/difficulty_personalization/68_bot_p2_craft_parity_prereg_20261027.md'
    assert hashlib.sha256(doc.read_bytes()).hexdigest() == os.environ['PREREG_DOC_SHA256']
    man = dict(source_hash=sha, exposure_sha256=exp_sha, prereg_doc_sha256=os.environ['PREREG_DOC_SHA256'], base=BASE, cells=CELLS,
               games=GAMES, weights={t: W[t] for t in THETAS}, cap=.65, tol=TOL, abs_allow=ABS_ALLOW, seeds=SEEDS, layout_rule=LU.__doc__,
               target=target, control=control, rp=rp,
               stop=dict(max_games=MAX_GAMES, max_sec=MAX_SEC, guard=G.__doc__, stop_flag=str(OUT / 'STOP')),
               maps={L: dict(hash=hashlib.sha256(json.dumps(c.P[L]['map'], sort_keys=True).encode()).hexdigest(), features=c.P[L]['features'],
                             n=c.A[L]['clean_ft_n'], stratum=stratum(L), band=band(L), mode=c.P[L]['mode']) for L in Ls}, doc=__doc__)
    if _p('manifest.json').exists(): assert json.loads(_p('manifest.json').read_text()) == json.loads(json.dumps(man))
    else:
        tmp = _p('manifest.tmp'); tmp.write_text(json.dumps(man, indent=2)); os.replace(tmp, _p('manifest.json'))
    rows = []
    if _p('rows.jsonl').exists():
        for line in _p('rows.jsonl').read_text().splitlines():
            try: rows.append(json.loads(line))
            except ValueError: break
        tmp = _p('rows.tmp'); tmp.write_text(''.join(json.dumps(r) + '\n' for r in rows)); os.replace(tmp, _p('rows.jsonl'))
    done = {(r['phase'], r['option'], r['L'], r['theta']) for r in rows}; assert len(done) == len(rows)
    start = time.time(); spent = lambda: sum(r['games'] for r in rows)
    log = lambda m: (print(m, flush=True), _p('progress.log').open('a').write(m + '\n'))

    def run(phase, cell, L, t):
        if (phase, cell, L, t) in done: return True
        if _p('STOP').exists(): log('STOP flag -> clean stop at row boundary'); return False
        if spent() + GAMES[t] > MAX_GAMES or time.time() - start > MAX_SEC: log(f'STOP budget {spent()}'); return False
        if not G.wait_ok(log): return False
        row = measure(phase, cell, L, t, SEEDS[phase])
        with _p('rows.jsonl').open('a') as f:
            f.write(json.dumps(row) + '\n'); f.flush(); os.fsync(f.fileno())
        rows.append(row); done.add((phase, cell, L, t))
        log(f"ROW {phase} {cell} {L} {t} {row['wins']}/{row['games']} L{row['layouts']} {dict(row['fail_reasons'])} {row['sec']:.1f}s total{spent()}")
        return True

    for phase, ls in (('N', Ls), ('Rp', rp)):
        for L in ls:
            for cell in CELLS:
                for t in THETAS:
                    if not run(phase, cell, L, t): return
    j = judge(rows, Ls, rp); j.update(rows=len(rows), games=spent(), rows_sha256=hashlib.sha256(_p('rows.jsonl').read_bytes()).hexdigest())
    tmp = _p('judgement.tmp'); tmp.write_text(json.dumps(j, indent=2)); os.replace(tmp, _p('judgement.json'))
    log(f'DONE {len(rows)} {spent()}')


if __name__ == '__main__':
    main()
