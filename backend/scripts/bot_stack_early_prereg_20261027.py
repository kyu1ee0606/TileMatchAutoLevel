"""PREREG doc 62 (2026-10-27): stack_early re-check.  B' = new default (core 39d2de55, measurement BASE = prior.BASE,
which now contains K1C) vs B'+stack_early (26 §10 fitted w=8, no new constant).

Five thetas, fixed mixture [0,.1164,.1255,0,.7580], cap .65, no refit.
Maps (rule fixed before any AF-vs-bot error of these runs is seen):
  eligible = prep pool, not excluded, editor map same, AF n >= 100; unlockTile == 0.
  target   = eligible maps WITH a stack container; control = eligible maps WITHOUT stack (stack_early cannot act there:
             it only scores stack tiles -> expected identical, measured as a small check).
  exposure = k1c_prereg_20261027/exposure.json (measured rows) + doc 60 selection + doc 61 traced maps (AF-compare).
  tier 1 never AF-compared; tier 2 only broad diagnosis {gimmick_causes, dda_v24confirm_20261019, lowband};
  tier 3 other AF-compare exposure (NOT a new-map validation), used only to fill short cells;
  doc 61 diagnosis maps 378 / 57 / 275 / 388 are development-only and never selected.
  stratum (co-gimmick of the stack map): chain/link > bomb/grass > curtain/unknown > other (incl. craft).
  AF band <.80 / .80-.95 / >=.95; quota per stack stratum 2 / 2 / 1; control: 2 maps (>=.95 or .80-.95, tier 1 first).
  cell fill: tier 1 -> 2 -> 3, each by AF n desc (ties L); short cells stay short.
Random-layout maps (mode 'random', randSeed 0 in the game): measured over 8 layouts (layout seeds 1..8) x 4 games
  per theta (= 32 games, same per-map count); fixed maps: 1 layout x 32 games.  (doc 61 finding.)
Stages: N = all selected maps, seed 54M, cells B' / SE.  Rp (report) = first 2 stack maps, seed 55M.
Judge (SE vs B' on N, tolerance 1e-12 on <=):
  joint MSE < B';  clear MAE <= B';  every stratum (incl. control): joint <= 1.10 x B' OR joint - B' <= 0.002;
  failure-category MAE (unconditional Grass / Bomb / Normal) <= B'.  TV reported only.
Guard run_guard_20261027; STOP flag OUT/STOP; stop 9,000 games / 6 h.
"""
import sys, json, time, hashlib, os, dataclasses
from pathlib import Path
from collections import Counter
B_ = Path(__file__).resolve().parents[1]; sys.path[:0] = [str(B_), str(B_ / 'scripts')]
import bot_hard_key_prereg_20261027 as HK
import bot_combo_prereg_20261027 as C9
import run_guard_20261027 as G
c = HK.c; R = HK.R
AFC = B_ / 'data/pv_sandbox/af_calibration'
OUT = AFC / 'stack_early_prereg_20261027'
CORE = '39d2de55778afa1e1cc605b56c27773d2dcd961743b2e3dca52d79acc3a80c04'
TOL = 1e-12; ABS_ALLOW = 0.002
THETAS = list(R.THETAS); W = dict(zip(R.THETAS, R.WEIGHTS))
BASE = list(R.prior.BASE)
CELLS = {"B'": [], 'SE': ['stack_early']}
SEEDS = dict(N=54000000, Rp=55000000); GAMES = 32; N_LAYOUTS_RANDOM = 8
STRATA = ['chain/link', 'bomb/grass', 'curtain/unknown', 'other', 'control']
BANDS = ['<.80', '.80-.95', '>=.95']; QUOTA = {'<.80': 2, '.80-.95': 2, '>=.95': 1}
BROAD = {'gimmick_causes', 'dda_v24confirm_20261019', 'lowband'}
DIAG = {378, 57, 275, 388}
MAX_GAMES = 9000; MAX_SEC = 6 * 3600
band = C9.band


def stratum(L):
    f = c.P[L]['features']
    if not f.get('stack'): return 'control'
    if f.get('eff_chain') or f.get('eff_link'): return 'chain/link'
    if f.get('eff_bomb') or f.get('eff_grass'): return 'bomb/grass'
    if f.get('eff_curtain') or f.get('eff_unknown'): return 'curtain/unknown'
    return 'other'


def tiers_of():
    e = json.loads((AFC / 'k1c_prereg_20261027/exposure.json').read_text())
    m60 = json.loads((AFC / 'k1c_prereg_20261027/manifest.json').read_text()); s60 = {L for v in m60['selection'].values() for L in v}
    el = [L for L in sorted(set(c.P) & set(c.A)) if HK.eligible(L) and R.unlock(L) == 0 and L not in DIAG]
    t = {}
    for L in el:
        x = {k.split('/')[-1] for k, v in e['folders'].items() if e['kind'][k] == 'af_compare' and L in v} | ({'k1c'} if L in s60 else set())
        t[L] = 1 if not x else (2 if x <= BROAD else 3)
    return t


def select():
    t = tiers_of(); key = lambda L: (-c.A[L]['clean_ft_n'], L); sel, short = {}, {}
    for s in STRATA[:-1]:
        for b in BANDS:
            cell = []
            for tier in (1, 2, 3):
                cell += sorted([L for L, v in t.items() if v == tier and stratum(L) == s and band(L) == b and L not in cell], key=key)[:QUOTA[b] - len(cell)]
            sel[f'{s}|{b}'] = cell
            if len(cell) < QUOTA[b]: short[f'{s}|{b}'] = QUOTA[b] - len(cell)
    ctl = []
    for tier in (1, 2):
        for b in ('>=.95', '.80-.95'):
            ctl += sorted([L for L, v in t.items() if v == tier and stratum(L) == 'control' and band(L) == b and L not in ctl], key=key)[:2 - len(ctl)]
    sel['control|any'] = ctl
    tiers = {L: t[L] for v in sel.values() for L in v}
    return sel, short, tiers


def nmaps(sel): return [L for k in sel for L in sel[k]]


def rmaps(sel): return [L for k in sel if not k.startswith('control') for L in sel[k]][:2]


def layouts_for(L):
    if c.P[L]['mode'] == 'random':
        return c.ev.base.level_layouts(c.P[L], N_LAYOUTS_RANDOM)
    return c.ev.base.level_layouts(c.P[L], 1)


def measure(phase, cell, L, t, seed):
    start = time.time(); p = c.make_skill_profile(t, 'v2.4'); cfg = dict(p.gimmick_awareness); cfg.update(c.ev.v21.FIXED)
    cfg.update(alpha=dict(c.V21_AWARENESS_DEFAULTS['alpha']), gamma=dict(c.V21_AWARENESS_DEFAULTS['gamma']), exposure=c.EX[L], parity=None,
               auto_collect=int(float(c.P[L]['row'].get('autoCollectCount') or 0)), v24_expo=c.ev._gc_expo(c.P)[L],
               v24=BASE + CELLS[cell], grass_attention_cap=.65)
    p = dataclasses.replace(p, gimmick_awareness=cfg)
    lays = layouts_for(L); per = GAMES // len(lays)
    wins = 0; reasons = Counter(); n = 0
    for li, lay in enumerate(lays):
        b = c.BotSimulator(); b.set_rule_parity(p)
        st = b._create_initial_state(json.loads(json.dumps(lay)), int(lay['max_moves'])); b._precompute_blocking_map(st)
        for g in range(per):
            b._rng.seed(seed + li * 1000 + g); end = b._play_game(b._fast_copy_state(st), p); n += 1
            if end.cleared: wins += 1
            else: reasons[c.ev.base.fail_reason(b, end)] += 1
    return dict(phase=phase, option=cell, L=L, theta=t, games=n, layouts=len(lays), wins=wins, fail_reasons=dict(reasons),
                seedbase=seed, sec=time.time() - start)


def _p(name):
    p = OUT / name; assert p.resolve().parent == OUT.resolve(), p; return p


def load_rows():
    if not _p('rows.jsonl').exists(): return []
    out = []
    for line in _p('rows.jsonl').read_text().splitlines():
        try: out.append(json.loads(line))
        except ValueError: break
    return out


def evaluate(rows, phase, cell, Ls):
    return C9.evaluate(rows, phase, cell, Ls)


def judge(rows, sel, tiers):
    have = {(r['phase'], r['option'], r['L'], r['theta']) for r in rows}
    full = lambda ph, Ls: all((ph, x, L, t) in have for x in CELLS for L in Ls for t in THETAS)
    Ls = nmaps(sel)
    if not full('N', Ls): return {}
    a, b = evaluate(rows, 'N', 'SE', Ls), evaluate(rows, 'N', "B'", Ls)
    strata = {}
    for s in STRATA:
        sl = [L for L in Ls if stratum(L) == s]
        if not sl: continue
        sa, sb = evaluate(rows, 'N', 'SE', sl), evaluate(rows, 'N', "B'", sl)
        strata[s] = dict(n=len(sl), **{k: (sa[k], sb[k]) for k in ('joint_mse', 'clear_mae', 'cat_mae', 'tv')},
                         ok=(sa['joint_mse'] <= 1.10 * sb['joint_mse'] + TOL) or (sa['joint_mse'] - sb['joint_mse'] <= ABS_ALLOW + TOL),
                         ok_ratio=sa['joint_mse'] <= 1.10 * sb['joint_mse'] + TOL)
    bands = {}
    for bd in BANDS:
        bl = [L for L in Ls if band(L) == bd]
        if bl:
            ba, bb = evaluate(rows, 'N', 'SE', bl), evaluate(rows, 'N', "B'", bl)
            bands[bd] = dict(n=len(bl), **{k: (ba[k], bb[k]) for k in ('joint_mse', 'clear_mae', 'cat_mae', 'tv')})
    by_tier = {}
    for tr in (1, 2, 3):
        tl = [L for L in Ls if tiers[L] == tr]
        if tl:
            ta, tb = evaluate(rows, 'N', 'SE', tl), evaluate(rows, 'N', "B'", tl)
            by_tier[tr] = dict(n=len(tl), **{k: (ta[k], tb[k]) for k in ('joint_mse', 'clear_mae', 'cat_mae', 'tv')})
    cond = dict(joint=a['joint_mse'] < b['joint_mse'], clear=a['clear_mae'] <= b['clear_mae'] + TOL,
                strata=all(v['ok'] for v in strata.values()), category=a['cat_mae'] <= b['cat_mae'] + TOL)
    out = dict(N={k: (a[k], b[k]) for k in ('joint_mse', 'clear_mae', 'cat_mae', 'tv')}, strata=strata, bands=bands, by_tier=by_tier,
               conditions=cond, support=all(cond.values()), target_clear_mae_lt_10pp=dict(SE=a['clear_mae'] < .10, B=b['clear_mae'] < .10))
    rl = rmaps(sel)
    if all((p_, x, L, t) in have for p_ in ('Rp',) for x in CELLS for L in rl for t in THETAS):
        ra, rb = evaluate(rows, 'Rp', 'SE', rl), evaluate(rows, 'Rp', "B'", rl)
        out['Rp'] = dict(maps=rl, new_seed={k: (ra[k], rb[k]) for k in ('joint_mse', 'clear_mae')})
    return out


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    sha = hashlib.sha256((B_ / 'app/core/bot_simulator.py').read_bytes()).hexdigest(); assert sha == CORE == os.environ['EXPECTED_BOT_SHA256']
    exp_sha = hashlib.sha256((AFC / 'k1c_prereg_20261027/exposure.json').read_bytes()).hexdigest()
    sel, short, tiers = select()
    if os.environ.get('SELECT_ONLY'):
        print(json.dumps(dict(sel={k: [(L, round(c.target(L)[0], 3), c.A[L]['clean_ft_n'], tiers[L], c.P[L]['mode']) for L in v] for k, v in sel.items()},
                              short=short, n=len(nmaps(sel)), rp=rmaps(sel), base=BASE, exp_sha=exp_sha)))
        return
    doc = B_.parent / 'claudedocs/difficulty_personalization/62_bot_stack_early_prereg_20261027.md'
    assert hashlib.sha256(doc.read_bytes()).hexdigest() == os.environ['PREREG_DOC_SHA256']
    man = dict(source_hash=sha, exposure_sha256=exp_sha, prereg_doc_sha256=os.environ['PREREG_DOC_SHA256'], base=BASE, cells=CELLS,
               thetas=THETAS, weights=W, cap=.65, tol=TOL, abs_allow=ABS_ALLOW, seeds=SEEDS, games=GAMES, n_layouts_random=N_LAYOUTS_RANDOM,
               selection=sel, short=short, tiers=tiers, rp=rmaps(sel), diag_excluded=sorted(DIAG),
               stop=dict(max_games=MAX_GAMES, max_sec=MAX_SEC, guard=G.__doc__, stop_flag=str(OUT / 'STOP')),
               maps={L: dict(hash=hashlib.sha256(json.dumps(c.P[L]['map'], sort_keys=True).encode()).hexdigest(), features=c.P[L]['features'],
                             n=c.A[L]['clean_ft_n'], stratum=stratum(L), band=band(L), tier=tiers[L], mode=c.P[L]['mode']) for L in nmaps(sel)},
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
        if _p('STOP').exists(): log('STOP flag -> clean stop at row boundary'); return False
        if spent() + GAMES > MAX_GAMES or time.time() - start > MAX_SEC: log(f'STOP budget {spent()}'); return False
        if not G.wait_ok(log): return False
        row = measure(phase, cell, L, t, SEEDS[phase])
        with _p('rows.jsonl').open('a') as f:
            f.write(json.dumps(row) + '\n'); f.flush(); os.fsync(f.fileno())
        rows.append(row); done.add((phase, cell, L, t))
        log(f"ROW {phase} {cell} {L} {t} {row['wins']}/{row['games']} L{row['layouts']} {dict(row['fail_reasons'])} {row['sec']:.1f}s total{spent()}")
        return True

    for phase, Ls in (('N', nmaps(sel)), ('Rp', rmaps(sel))):
        for L in Ls:
            for cell in CELLS:
                for t in THETAS:
                    if not run(phase, cell, L, t): return
    j = judge(rows, sel, tiers); j.update(rows=len(rows), games=spent(), rows_sha256=hashlib.sha256(_p('rows.jsonl').read_bytes()).hexdigest())
    tmp = _p('judgement.tmp'); tmp.write_text(json.dumps(j, indent=2)); os.replace(tmp, _p('judgement.json'))
    log(f'DONE {len(rows)} {spent()}')


if __name__ == '__main__':
    main()
