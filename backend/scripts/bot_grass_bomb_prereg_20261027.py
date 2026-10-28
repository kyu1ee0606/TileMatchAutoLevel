"""PREREG doc 58 (draft 2026-10-27): grass_cover_blindness (G) / bomb_count_awareness (C) / both (GC) vs B.

Core bot_simulator.py fixed (CORE). Candidates in scripts/bot_grass_bomb_candidates_20261027.py (subclass, sha in manifest).
B = BASE rules only (doc 56/57 B; K1/K2/P2 not adopted -> not in B). cap .65, fixed mixture, no refit.
Thetas: only the non-zero-weight tiers .65 / .85 / 1.2 are run (weights of .55 / 1.0 are 0 -> identical judgement).
Sets (eligible = prep pool, not excluded, editor map same, AF n >= 100):
  GS = eligible maps with grass effect, BS = eligible maps with bomb effect (a map with both is in both).
  USED = USED_PRIOR (doc 57) + every doc 57 map (their AF-vs-bot errors were viewed).
  dev  (D gate seed 42M x16, R new seed 43M x32): per set the 8 USED maps with largest AF n (ties: L).
  val  (V, other maps, seed 44M x32):              per set the 12 non-USED maps with largest AF n (ties: L).
  Split fixed by this rule before any bot run of these candidates; no constant is fitted (G, C have none).
Cells: GS maps -> B, G, ALL;  BS maps -> B, C, ALL;  maps in both sets -> B, G, C, GC, ALL.
  ALL = K1 (key_first) + P2 (public_craft_belief) + G + C: adoption estimate, always run, reported vs B (no verdict).
  K2 excluded (user decision). C = per-bomb persistent awareness (replaces bomb_threat_memory; not combined).
  (G is inert without grass, C without bombs: proven by tests, so GC == G on grass-only and == C on bomb-only maps.)
Judge per set (G on GS, C on BS; GC on GS U BS using GC rows where measured, else the inert-equal G/C rows):
  gate D: joint MSE < B (failed -> not run in R / V)
  R: joint MSE < B and clear MAE <= B
  V: joint MSE < B, clear MAE <= B, mean failure TV <= B, gimmick-failure MAE (Grass% for GS, Bomb% for BS) <= B
  tolerance 1e-12 on every <=.
Target (reported, not judged): per set V clear MAE < 10%p and gimmick-failure MAE.
M (descriptive, not judged): every eligible map with BOTH grass and bomb (seed 45M x32), cells B/G/C/GC — the only
  maps where GC differs from G or C; reported per map. Run after V regardless of gates.
Guard: run_guard_20261027. STOP flag: create OUT/STOP -> stops cleanly at the next row boundary (resumable).
Stop: 16,000 games, 6 h. Writes only inside OUT; row checkpoints; atomic manifest/judgement.
"""
import sys, json, time, hashlib, os, dataclasses
from pathlib import Path
from collections import Counter
B_ = Path(__file__).resolve().parents[1]; sys.path[:0] = [str(B_), str(B_ / 'scripts')]
import bot_hard_key_prereg_20261027 as HK
import bot_grass_bomb_candidates_20261027 as GCM
import run_guard_20261027 as G
c = HK.c; R = HK.R
OUT = B_ / 'data/pv_sandbox/af_calibration/grass_bomb_prereg_20261027'
CORE = 'cbc2e652c53d8d5f028d5513aa566f9285d3e5869663980b9b7d34cb34f68a8b'
TOL = 1e-12
THETAS = [.65, .85, 1.2]
W = dict(zip(R.THETAS, R.WEIGHTS))
CELLS = {'B': [], 'G': [GCM.G_OPT], 'C': [GCM.C_OPT], 'GC': [GCM.G_OPT, GCM.C_OPT],
         'ALL': ['key_first', 'public_craft_belief', GCM.G_OPT, GCM.C_OPT]}
SEEDS = dict(D=42000000, R=43000000, V=44000000, M=45000000)
GAMES = dict(D=16, R=32, V=32, M=32)
NDEV, NVAL = 8, 12
MAX_GAMES = 18000; MAX_SEC = 6 * 3600


def used():
    man = json.loads((B_ / 'data/pv_sandbox/af_calibration/hard_key_prereg_20261027/manifest.json').read_text())
    return sorted(set(HK.used_prior()) | {L for v in man['H'].values() for L in v} | set(man['kdev']) | set(man['knew']))


def select():
    U = set(used()); Ls = sorted(set(c.P) & set(c.A)); el = [L for L in Ls if HK.eligible(L)]
    sets = {'grass': [L for L in el if c.P[L]['features'].get('eff_grass')],
            'bomb': [L for L in el if c.P[L]['features'].get('eff_bomb')]}
    key = lambda L: (-c.A[L]['clean_ft_n'], L)
    dev = {s: sorted([L for L in v if L in U], key=key)[:NDEV] for s, v in sets.items()}
    val = {s: sorted([L for L in v if L not in U], key=key)[:NVAL] for s, v in sets.items()}
    return sets, dev, val


def both_maps():
    return sorted(L for L in sorted(set(c.P) & set(c.A)) if HK.eligible(L)
                  and c.P[L]['features'].get('eff_grass') and c.P[L]['features'].get('eff_bomb'))


def cells_for(L):
    f = c.P[L]['features']; g, b = bool(f.get('eff_grass')), bool(f.get('eff_bomb'))
    return ['B'] + (['G'] if g else []) + (['C'] if b else []) + (['GC'] if g and b else []) + ['ALL']


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


def evaluate(rows, phase, cell, Ls, inert=True):
    """doc 56 evaluate on the non-zero-weight tiers; GC falls back to the inert-equal G / C rows on single-gimmick maps."""
    d = {(r['L'], r['theta']): r for r in rows if r['phase'] == phase and r['option'] == cell}
    if inert and cell == 'GC':
        for L in Ls:
            alt = 'G' if c.P[L]['features'].get('eff_grass') else 'C'
            if (L, THETAS[0]) not in d:
                for r in rows:
                    if r['phase'] == phase and r['option'] == alt and r['L'] == L: d[L, r['theta']] = r
    out = []
    for L in Ls:
        vs = [c.vector(d[L, t]) for t in THETAS]; ws = [W[t] for t in THETAS]
        p = [sum(w * v[j] for w, v in zip(ws, vs)) for j in range(len(c.CATS))]; a = c.target(L)
        out.append(dict(L=L, predicted=p, actual=a, clear_error=p[0] - a[0],
                        joint_mse=sum((x - y) ** 2 for x, y in zip(p, a)) / len(c.CATS),
                        grass_err=p[1] - a[1], bomb_err=p[2] - a[2],
                        failure_tv=sum(abs(x / (1 - p[0]) - y / (1 - a[0])) for x, y in zip(p[1:], a[1:])) / 2 if p[0] < 1 and a[0] < 1 else None))
    m = lambda k: sum(abs(x[k]) for x in out) / len(out)
    tv = [x['failure_tv'] for x in out if x['failure_tv'] is not None]
    return dict(rows=out, joint_mse=sum(x['joint_mse'] for x in out) / len(out), clear_mae=m('clear_error'),
                grass_mae=m('grass_err'), bomb_mae=m('bomb_err'), tv=sum(tv) / len(tv) if tv else 0.0)


def judge(rows, sets, dev, val):
    have = {(r['phase'], r['option'], r['L'], r['theta']) for r in rows}
    def full(ph, cell, Ls):
        for L in Ls:
            cl = cell if cell in cells_for(L) else ('G' if c.P[L]['features'].get('eff_grass') else 'C')
            if not all((ph, cl, L, t) in have for t in THETAS): return False
        return True
    out = {}
    for cand, scope in (('G', ['grass']), ('C', ['bomb']), ('GC', ['grass', 'bomb'])):
        dl = sorted({L for s in scope for L in dev[s]}); vl = sorted({L for s in scope for L in val[s]})
        gk = {'G': 'grass_mae', 'C': 'bomb_mae'}.get(cand)
        res = {}
        if full('D', cand, dl) and full('D', 'B', dl):
            a, b = evaluate(rows, 'D', cand, dl), evaluate(rows, 'D', 'B', dl)
            res['D'] = dict(joint_mse=(a['joint_mse'], b['joint_mse']), clear_mae=(a['clear_mae'], b['clear_mae'])); res['gate'] = a['joint_mse'] < b['joint_mse']
        if res.get('gate') and all(full(ph, x, Ls) for ph, Ls in (('R', dl), ('V', vl)) for x in (cand, 'B')):
            ra, rb = evaluate(rows, 'R', cand, dl), evaluate(rows, 'R', 'B', dl)
            va, vb = evaluate(rows, 'V', cand, vl), evaluate(rows, 'V', 'B', vl)
            cond = dict(R_joint=ra['joint_mse'] < rb['joint_mse'], R_clear=ra['clear_mae'] <= rb['clear_mae'] + TOL,
                        V_joint=va['joint_mse'] < vb['joint_mse'], V_clear=va['clear_mae'] <= vb['clear_mae'] + TOL,
                        V_tv=va['tv'] <= vb['tv'] + TOL)
            if gk: cond['V_gimmick'] = va[gk] <= vb[gk] + TOL
            else: cond['V_gimmick'] = va['grass_mae'] + va['bomb_mae'] <= vb['grass_mae'] + vb['bomb_mae'] + TOL
            res.update(R={k: (ra[k], rb[k]) for k in ('joint_mse', 'clear_mae', 'grass_mae', 'bomb_mae', 'tv')},
                       V={k: (va[k], vb[k]) for k in ('joint_mse', 'clear_mae', 'grass_mae', 'bomb_mae', 'tv')},
                       conditions=cond, support=all(cond.values()),
                       target=dict(V_clear_mae_lt_10pp=va['clear_mae'] < .10, V_clear_mae=va['clear_mae']))
        out[cand] = res
    # ALL = K1 + P2 + G + C: adoption estimate, reported vs B on GS U BS (same condition set, not a candidate verdict)
    al = sorted({L for v in dev.values() for L in v}); vl = sorted({L for v in val.values() for L in v}); rep = {}
    for ph, Ls in (('D', al), ('R', al), ('V', vl)):
        if full(ph, 'ALL', Ls) and full(ph, 'B', Ls):
            a_, b_ = evaluate(rows, ph, 'ALL', Ls), evaluate(rows, ph, 'B', Ls)
            rep[ph] = {k: (a_[k], b_[k]) for k in ('joint_mse', 'clear_mae', 'grass_mae', 'bomb_mae', 'tv')}
    out['ALL_report'] = rep
    return out


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    sha = hashlib.sha256((B_ / 'app/core/bot_simulator.py').read_bytes()).hexdigest(); assert sha == CORE == os.environ['EXPECTED_BOT_SHA256']
    cand_sha = hashlib.sha256((B_ / 'scripts/bot_grass_bomb_candidates_20261027.py').read_bytes()).hexdigest()
    sets, dev, val = select()
    if os.environ.get('SELECT_ONLY'):
        print(json.dumps(dict(sets={s: len(v) for s, v in sets.items()}, dev=dev, val=val, both=both_maps(),
                              cells={L: cells_for(L) for L in sorted({L for d in (dev, val) for v in d.values() for L in v})},
                              cand_sha=cand_sha)))
        return
    doc = B_.parent / 'claudedocs/difficulty_personalization/58_bot_grass_bomb_perception_20261027.md'
    assert hashlib.sha256(doc.read_bytes()).hexdigest() == os.environ['PREREG_DOC_SHA256']
    man = dict(source_hash=sha, candidates_sha256=cand_sha, prereg_doc_sha256=os.environ['PREREG_DOC_SHA256'], cells=CELLS,
               thetas=THETAS, weights=W, cap=.65, base=R.prior.BASE, tol=TOL, seeds=SEEDS, games=GAMES, dev=dev, val=val, both=both_maps(),
               used=used(), stop=dict(max_games=MAX_GAMES, max_sec=MAX_SEC, guard=G.__doc__, stop_flag=str(OUT / 'STOP')),
               maps={L: dict(hash=hashlib.sha256(json.dumps(c.P[L]['map'], sort_keys=True).encode()).hexdigest(),
                             features=c.P[L]['features'], n=c.A[L]['clean_ft_n'], cells=cells_for(L))
                     for L in sorted({L for d in (dev, val) for v in d.values() for L in v} | set(both_maps()))}, doc=__doc__)
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

    devmaps = sorted({L for v in dev.values() for L in v}); valmaps = sorted({L for v in val.values() for L in v})
    for L in devmaps:
        for cell in cells_for(L):
            for t in THETAS:
                if not run('D', cell, L, t): return
    j = judge(rows, sets, dev, val); passing = {k for k in ('G', 'C', 'GC') if j[k].get('gate')}
    log(f"GATES {{'G': {j['G'].get('gate')}, 'C': {j['C'].get('gate')}, 'GC': {j['GC'].get('gate')}}}")
    need = lambda L: ['B'] + [x for x in cells_for(L)[1:] if x in passing or x == 'ALL' or (x in ('G', 'C') and 'GC' in passing)]
    if True:   # ALL is always run (adoption estimate); gated candidates only if their gate passed
        for phase, Ls in (('R', devmaps), ('V', valmaps)):
            for L in Ls:
                for cell in need(L):
                    for t in THETAS:
                        if not run(phase, cell, L, t): return
    for L in both_maps():
        for cell in ('B', 'G', 'C', 'GC', 'ALL'):
            for t in THETAS:
                if not run('M', cell, L, t): return
    j = judge(rows, sets, dev, val)
    j['M'] = {L: {cell: evaluate(rows, 'M', cell, [L], inert=False)['rows'][0] for cell in ('B', 'G', 'C', 'GC', 'ALL')} for L in both_maps()}
    j.update(rows=len(rows), games=spent(), rows_sha256=hashlib.sha256(_p('rows.jsonl').read_bytes()).hexdigest())
    tmp = _p('judgement.tmp'); tmp.write_text(json.dumps(j, indent=2)); os.replace(tmp, _p('judgement.json'))
    log(f'DONE {len(rows)} {spent()}')


if __name__ == '__main__':
    main()
