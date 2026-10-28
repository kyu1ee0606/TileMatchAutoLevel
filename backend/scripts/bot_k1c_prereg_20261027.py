"""PREREG doc 60 (2026-10-27): small adoption check B (current default) vs K1C = K1 (key_first) + C (bomb_count_awareness,
per-bomb persistent awareness; runner-side subclass). P2 / G / K2 excluded. Budget <= 10,000 games.

Core bot_simulator.py fixed (CORE). Five thetas, fixed mixture [0,.1164,.1255,0,.7580], cap .65, BASE rules, no refit.
Scope: only maps where K1 or C can act (unlockTile > 0 or a bomb effect). On every other map K1C == B by construction
  (K1 needs a locked slot, C needs a bomb; OFF-identity tests), so they are not measured.
Map rule (before any AF-vs-bot error of these runs is seen):
  eligible = prep pool, not excluded, editor map same, AF n >= 100; target = eligible with key or bomb.
  exposure = k1c_prereg_20261027/exposure.json (MEASURED rows only, not manifest exclusion lists; scan rule inside).
  tier 1 (fresh)  : never measured in an AF-compare run.
  tier 2 (weak)   : AF-compare exposure only in broad diagnosis runs {gimmick_causes, dda_v24confirm_20261019, lowband}
                    -> NOT a new-map validation (AF error seen in broad diagnosis, never used to build K1 or C).
  tier 3 (reuse)  : held-out validation maps of doc 57 KN / doc 58 V not used in doc 59 -> NOT a new-map validation
                    (K1 resp. C were judged on them).
  stratum: key (unlockTile > 0) else bomb.  AF band <.80 / .80-.95 / >=.95.  quota per band: bomb 6, key 3.
  each (stratum, band) cell: tier 1, then tier 2, then tier 3, each by AF n desc (ties L); short cells stay short.
Stages: N = all selected maps, seed 48M x32, cells B / K1C.
        Rp (report only, budget permitting) = first 2 selected maps per stratum, seed 49.5M x32.
Judge (K1C vs B on N, tolerance 1e-12 on <=):
  joint MSE < B;  clear MAE <= B;
  every stratum: joint MSE <= 1.10 x B  OR  joint MSE - B <= 0.002 (absolute allowance, doc 60 §4);
  failure-category MAE (unconditional Grass / Bomb / Normal) <= B.   TV reported only (doc 59 §4 reason).
Reports: per stratum / AF band / tier, target clear MAE < 10%p.
Guard: run_guard_20261027. STOP flag OUT/STOP. Stop 10,000 games / 6 h.
"""
import sys, json, time, hashlib, os, dataclasses
from pathlib import Path
from collections import Counter
B_ = Path(__file__).resolve().parents[1]; sys.path[:0] = [str(B_), str(B_ / 'scripts')]
import bot_hard_key_prereg_20261027 as HK
import bot_combo_prereg_20261027 as C9
import bot_grass_bomb_candidates_20261027 as GCM
import run_guard_20261027 as G
c = HK.c; R = HK.R
AFC = B_ / 'data/pv_sandbox/af_calibration'
OUT = AFC / 'k1c_prereg_20261027'
CORE = 'cbc2e652c53d8d5f028d5513aa566f9285d3e5869663980b9b7d34cb34f68a8b'
TOL = 1e-12
THETAS = list(R.THETAS); W = dict(zip(R.THETAS, R.WEIGHTS))
CELLS = {'B': [], 'K1C': ['key_first', GCM.C_OPT]}
SEEDS = dict(N=48000000, Rp=49500000); GAMES = dict(N=32, Rp=32)
STRATA = ['key', 'bomb']
BANDS = ['<.80', '.80-.95', '>=.95']; QUOTA = {'key': 3, 'bomb': 6}
BROAD = {'gimmick_causes', 'dda_v24confirm_20261019', 'lowband'}
ABS_ALLOW = 0.002
MAX_GAMES = 10000; MAX_SEC = 6 * 3600


def stratum(L):
    return 'key' if R.unlock(L) > 0 else 'bomb'


def band(L):
    x = c.target(L)[0]
    return '<.80' if x < .80 else ('.80-.95' if x < .95 else '>=.95')


def tiers_of():
    e = json.loads((OUT / 'exposure.json').read_text())
    el = [L for L in sorted(set(c.P) & set(c.A)) if HK.eligible(L)]
    tgt = [L for L in el if R.unlock(L) > 0 or c.P[L]['features'].get('eff_bomb')]
    expo = lambda L: {k.split('/')[-1] for k, v in e['folders'].items() if e['kind'][k] == 'af_compare' and L in v}
    m57 = json.loads((AFC / 'hard_key_prereg_20261027/manifest.json').read_text())
    m58 = json.loads((AFC / 'grass_bomb_prereg_20261027/manifest.json').read_text())
    m59 = json.loads((AFC / 'combo_prereg_20261027/manifest.json').read_text())
    s59 = {L for v in m59['selection'].values() for L in v}
    reuse = (set(m57['knew']) | {L for v in m58['val'].values() for L in v}) - s59
    t = {}
    for L in tgt:
        x = expo(L)
        if not x: t[L] = 1
        elif x <= BROAD: t[L] = 2
        elif L in reuse: t[L] = 3
    return t


def select():
    t = tiers_of()
    key = lambda L: (-c.A[L]['clean_ft_n'], L)
    sel, short = {}, {}
    for s in STRATA:
        for b in BANDS:
            cell = []
            for tier in (1, 2, 3):
                pool = sorted([L for L, v in t.items() if v == tier and stratum(L) == s and band(L) == b and L not in cell], key=key)
                cell += pool[:QUOTA[s] - len(cell)]
            sel[f'{s}|{b}'] = cell
            if len(cell) < QUOTA[s]: short[f'{s}|{b}'] = QUOTA[s] - len(cell)
    tiers = {L: t[L] for v in sel.values() for L in v}
    return sel, short, tiers


def nmaps(sel): return [L for k in sel for L in sel[k]]


def rmaps(sel):
    out = []
    for s in STRATA:
        out += [L for b in BANDS for L in sel[f'{s}|{b}']][:2]
    return out


def measure(phase, cell, L, t, n, seed):
    start = time.time(); p = c.make_skill_profile(t, 'v2.4'); cfg = dict(p.gimmick_awareness); cfg.update(c.ev.v21.FIXED)
    cfg.update(alpha=dict(c.V21_AWARENESS_DEFAULTS['alpha']), gamma=dict(c.V21_AWARENESS_DEFAULTS['gamma']), exposure=c.EX[L], parity=None,
               auto_collect=int(float(c.P[L]['row'].get('autoCollectCount') or 0)), v24_expo=c.ev._gc_expo(c.P)[L],
               v24=list(R.prior.BASE) + CELLS[cell], grass_attention_cap=.65)
    p = dataclasses.replace(p, gimmick_awareness=cfg)
    b = (c.BotSimulator if cell == 'B' else GCM.GrassBombBot)(); b.set_rule_parity(p)
    layout = c.ev.base.level_layouts(c.P[L], 1)[0]; st = b._create_initial_state(layout, int(layout['max_moves'])); b._precompute_blocking_map(st)
    wins = 0; reasons = Counter()
    for g in range(n):
        b._rng.seed(seed + g); end = b._play_game(b._fast_copy_state(st), p)
        if end.cleared: wins += 1
        else: reasons[c.ev.base.fail_reason(b, end)] += 1
    return dict(phase=phase, option=cell, L=L, theta=t, games=n, wins=wins, fail_reasons=dict(reasons), seedbase=seed, sec=time.time() - start)


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
    d = {(r['L'], r['theta']): r for r in rows if r['phase'] == phase and r['option'] == cell}
    out = []
    for L in Ls:
        vs = [c.vector(d[L, t]) for t in THETAS]; ws = [W[t] for t in THETAS]
        p = [sum(w * v[j] for w, v in zip(ws, vs)) for j in range(len(c.CATS))]; a = c.target(L)
        out.append(dict(L=L, predicted=p, actual=a, clear_error=p[0] - a[0],
                        joint_mse=sum((x - y) ** 2 for x, y in zip(p, a)) / len(c.CATS),
                        cat_mae=sum(abs(p[j] - a[j]) for j in (1, 2, 3)) / 3,
                        failure_tv=sum(abs(x / (1 - p[0]) - y / (1 - a[0])) for x, y in zip(p[1:], a[1:])) / 2 if p[0] < 1 and a[0] < 1 else None))
    tv = [x['failure_tv'] for x in out if x['failure_tv'] is not None]
    return dict(rows=out, joint_mse=sum(x['joint_mse'] for x in out) / len(out), clear_mae=sum(abs(x['clear_error']) for x in out) / len(out),
                cat_mae=sum(x['cat_mae'] for x in out) / len(out), tv=sum(tv) / len(tv) if tv else 0.0)


def judge(rows, sel, tiers):
    have = {(r['phase'], r['option'], r['L'], r['theta']) for r in rows}
    full = lambda ph, Ls: all((ph, x, L, t) in have for x in CELLS for L in Ls for t in THETAS)
    Ls = nmaps(sel)
    if not full('N', Ls): return {}
    a, b = evaluate(rows, 'N', 'K1C', Ls), evaluate(rows, 'N', 'B', Ls)
    strata = {}
    for s in STRATA:
        sl = [L for L in Ls if stratum(L) == s]
        if not sl: continue
        sa, sb = evaluate(rows, 'N', 'K1C', sl), evaluate(rows, 'N', 'B', sl)
        strata[s] = dict(n=len(sl), joint_mse=(sa['joint_mse'], sb['joint_mse']), clear_mae=(sa['clear_mae'], sb['clear_mae']),
                         cat_mae=(sa['cat_mae'], sb['cat_mae']), tv=(sa['tv'], sb['tv']), ok=(sa['joint_mse'] <= 1.10 * sb['joint_mse'] + TOL) or (sa['joint_mse'] - sb['joint_mse'] <= ABS_ALLOW + TOL),
                         ok_ratio=sa['joint_mse'] <= 1.10 * sb['joint_mse'] + TOL)
    bands = {}
    for bd in BANDS:
        bl = [L for L in Ls if band(L) == bd]
        if bl:
            ba, bb = evaluate(rows, 'N', 'K1C', bl), evaluate(rows, 'N', 'B', bl)
            bands[bd] = dict(n=len(bl), **{k: (ba[k], bb[k]) for k in ('joint_mse', 'clear_mae', 'cat_mae', 'tv')})
    cond = dict(joint=a['joint_mse'] < b['joint_mse'], clear=a['clear_mae'] <= b['clear_mae'] + TOL,
                strata=all(v['ok'] for v in strata.values()), category=a['cat_mae'] <= b['cat_mae'] + TOL)
    tier1 = {}
    for tr in (1, 2, 3):
        tl = [L for L in Ls if tiers[L] == tr]
        if tl:
            ta, tb = evaluate(rows, 'N', 'K1C', tl), evaluate(rows, 'N', 'B', tl)
            tier1[tr] = dict(n=len(tl), **{k: (ta[k], tb[k]) for k in ('joint_mse', 'clear_mae', 'cat_mae', 'tv')})
    out = dict(N={k: (a[k], b[k]) for k in ('joint_mse', 'clear_mae', 'cat_mae', 'tv')}, strata=strata, bands=bands,
               conditions=cond, support=all(cond.values()), by_tier=tier1,
               target_clear_mae_lt_10pp=dict(K1C=a['clear_mae'] < .10, B=b['clear_mae'] < .10))
    rl = rmaps(sel)
    if full('Rp', rl):
        ra, rb = evaluate(rows, 'Rp', 'K1C', rl), evaluate(rows, 'Rp', 'B', rl)
        na, nb = evaluate(rows, 'N', 'K1C', rl), evaluate(rows, 'N', 'B', rl)
        out['Rp'] = dict(maps=rl, new_seed={k: (ra[k], rb[k]) for k in ('joint_mse', 'clear_mae')},
                         same_maps_N={k: (na[k], nb[k]) for k in ('joint_mse', 'clear_mae')})
    return out


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    sha = hashlib.sha256((B_ / 'app/core/bot_simulator.py').read_bytes()).hexdigest(); assert sha == CORE == os.environ['EXPECTED_BOT_SHA256']
    cand_sha = hashlib.sha256((B_ / 'scripts/bot_grass_bomb_candidates_20261027.py').read_bytes()).hexdigest()
    scan_sha = hashlib.sha256((OUT / 'exposure.json').read_bytes()).hexdigest()
    sel, short, tiers = select()
    if os.environ.get('SELECT_ONLY'):
        print(json.dumps(dict(sel={k: [(L, round(c.target(L)[0], 3), c.A[L]['clean_ft_n'], tiers[L]) for L in v] for k, v in sel.items()},
                              short=short, n=len(nmaps(sel)), rp=rmaps(sel), cand_sha=cand_sha, scan_sha=scan_sha)))
        return
    doc = B_.parent / 'claudedocs/difficulty_personalization/60_bot_k1c_adoption_prereg_20261027.md'
    assert hashlib.sha256(doc.read_bytes()).hexdigest() == os.environ['PREREG_DOC_SHA256']
    man = dict(source_hash=sha, candidates_sha256=cand_sha, exposure_sha256=scan_sha, prereg_doc_sha256=os.environ['PREREG_DOC_SHA256'],
               cells=CELLS, thetas=THETAS, weights=W, cap=.65, base=R.prior.BASE, tol=TOL, seeds=SEEDS, games=GAMES,
               selection=sel, short=short, tiers=tiers, rp=rmaps(sel), abs_allow=ABS_ALLOW, broad=sorted(BROAD),
               stop=dict(max_games=MAX_GAMES, max_sec=MAX_SEC, guard=G.__doc__, stop_flag=str(OUT / 'STOP')),
               maps={L: dict(hash=hashlib.sha256(json.dumps(c.P[L]['map'], sort_keys=True).encode()).hexdigest(), features=c.P[L]['features'],
                             n=c.A[L]['clean_ft_n'], stratum=stratum(L), band=band(L), tier=tiers[L]) for L in nmaps(sel)},
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
        n = GAMES[phase]
        if spent() + n > MAX_GAMES or time.time() - start > MAX_SEC: log(f'STOP budget {spent()}'); return False
        if not G.wait_ok(log): return False
        row = measure(phase, cell, L, t, n, SEEDS[phase])
        with _p('rows.jsonl').open('a') as f:
            f.write(json.dumps(row) + '\n'); f.flush(); os.fsync(f.fileno())
        rows.append(row); done.add((phase, cell, L, t))
        log(f"ROW {phase} {cell} {L} {t} {row['wins']}/{n} {dict(row['fail_reasons'])} {row['sec']:.1f}s total{spent()}")
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
