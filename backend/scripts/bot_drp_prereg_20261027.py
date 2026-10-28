"""PREREG doc 70 (2026-10-28): dock_reserve_play D3 vs B''' (current default, core a89a29ab, measurement BASE).
Cells B''' / D3 (w1 10, w2 10, unscaled; constants from bot_drp_candidates_20261027).  Maps: 16 unused fixed maps (doc 70 §3).
Games per map x cell: theta .65 32 + .85 32 + 1.2 128 (weights .1164/.1255/.7580).  Seed 74M + layout*1000 + game.
Judge (4 conditions as docs 62/65/68, tol 1e-12): joint MSE <; clear MAE <=; strata (craft / non-craft) <=1.10x or +0.002; failure-category MAE <=.
Guard run_guard_20261027; STOP flag OUT/STOP; stop 6,300 games / 6 h; single process.
"""
import sys, json, time, hashlib, os
from pathlib import Path
B_ = Path(__file__).resolve().parents[1]; sys.path[:0] = [str(B_), str(B_ / 'scripts')]
import bot_drp_candidates_20261027 as D
import run_guard_20261027 as G
c = D.c; R = D.R; W = D.W
OUT = D.AFC / 'drp_prereg_20261027'
CORE = 'a89a29abb863949747f1c3550eef9b0833351240920ccb42594480c5668966ed'
TOL = 1e-12; ABS_ALLOW = 0.002; SEED = 74000000
GAMES = {.65: 32, .85: 32, 1.2: 128}; THETAS = list(GAMES)
CELLS = {"B'''": None, 'D3': dict(w1=10.0, w2=10.0, scaled=False)}
MAPS = [135, 202, 205, 206, 214, 226, 231, 233, 246, 247, 253, 262, 264, 299, 356, 369]
MAX_GAMES = 6300; MAX_SEC = 6 * 3600
stratum = lambda L: 'craft' if c.P[L]['features'].get('craft') else 'non-craft'
STRATA = ['craft', 'non-craft']


def evaluate(rows, cell, Ls):
    d = {(r['L'], r['theta']): r for r in rows if r['option'] == cell}
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


def judge(rows):
    have = {(r['option'], r['L'], r['theta']) for r in rows}
    if not all((x, L, t) in have for x in CELLS for L in MAPS for t in THETAS): return {}
    a, b = evaluate(rows, 'D3', MAPS), evaluate(rows, "B'''", MAPS); K = ('joint_mse', 'clear_mae', 'cat_mae', 'tv')
    strata = {}
    for s in STRATA:
        sl = [L for L in MAPS if stratum(L) == s]
        sa, sb = evaluate(rows, 'D3', sl), evaluate(rows, "B'''", sl)
        strata[s] = dict(n=len(sl), **{k: (sa[k], sb[k]) for k in K},
                         ok=(sa['joint_mse'] <= 1.10 * sb['joint_mse'] + TOL) or (sa['joint_mse'] - sb['joint_mse'] <= ABS_ALLOW + TOL))
    bands = {}
    for lo, hi, nm in ((0, .98, '.95-.98'), (.98, 1.01, '>=.98')):
        bl = [L for L in MAPS if lo <= c.target(L)[0] < hi]
        if bl:
            ba, bb = evaluate(rows, 'D3', bl), evaluate(rows, "B'''", bl)
            bands[nm] = dict(n=len(bl), **{k: (ba[k], bb[k]) for k in K})
    cond = dict(joint=a['joint_mse'] < b['joint_mse'], clear=a['clear_mae'] <= b['clear_mae'] + TOL,
                strata=all(v['ok'] for v in strata.values()), category=a['cat_mae'] <= b['cat_mae'] + TOL)
    per_map = {L: dict(af=round(c.target(L)[0], 4), B=round(x['predicted'][0], 4), D3=round(y['predicted'][0], 4))
               for L, x, y in zip(MAPS, evaluate(rows, "B'''", MAPS)['rows'], a['rows'])}
    return dict(N={k: (a[k], b[k]) for k in K}, strata=strata, bands=bands, conditions=cond, support=all(cond.values()), per_map=per_map)


def _p(name):
    p = OUT / name; assert p.resolve().parent == OUT.resolve(), p; return p


def main():
    sha = hashlib.sha256((B_ / 'app/core/bot_simulator.py').read_bytes()).hexdigest(); assert sha == CORE == os.environ['EXPECTED_BOT_SHA256']
    doc = B_.parent / 'claudedocs/difficulty_personalization/70_bot_dock_reserve_play_prereg_20261028.md'
    assert hashlib.sha256(doc.read_bytes()).hexdigest() == os.environ['PREREG_DOC_SHA256']
    OUT.mkdir(parents=True, exist_ok=True)
    exp = json.loads(_p('exposure.json').read_text()); expo = lambda L: any(exp['kind'][k] == 'af_compare' and L in v for k, v in exp['folders'].items())
    import bot_hard_key_prereg_20261027 as HK
    el = [L for L in sorted(set(c.P) & set(c.A)) if HK.eligible(L) and R.unlock(L) == 0 and not expo(L)]
    assert el == MAPS, (el, MAPS)
    man = dict(source_hash=sha, runner_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(), dev_runner_sha256=hashlib.sha256(Path(D.__file__).read_bytes()).hexdigest(),
               exposure_sha256=hashlib.sha256(_p('exposure.json').read_bytes()).hexdigest(), prereg_doc_sha256=os.environ['PREREG_DOC_SHA256'],
               base=D.BASE, cells=CELLS, games=GAMES, weights={t: W[t] for t in THETAS}, cap=.65, tol=TOL, abs_allow=ABS_ALLOW, seed=SEED, maps=MAPS,
               stop=dict(max_games=MAX_GAMES, max_sec=MAX_SEC, guard=G.__doc__, stop_flag=str(OUT / 'STOP')),
               map_info={L: dict(hash=hashlib.sha256(json.dumps(c.P[L]['map'], sort_keys=True).encode()).hexdigest(), features=c.P[L]['features'],
                                 af=c.target(L)[0], n=c.A[L]['clean_ft_n'], stratum=stratum(L)) for L in MAPS}, doc=__doc__)
    if _p('manifest.json').exists(): assert json.loads(_p('manifest.json').read_text()) == json.loads(json.dumps(man))
    else:
        tmp = _p('manifest.tmp'); tmp.write_text(json.dumps(man, indent=2)); os.replace(tmp, _p('manifest.json'))
    rows = []
    if _p('rows.jsonl').exists():
        for line in _p('rows.jsonl').read_text().splitlines():
            try: rows.append(json.loads(line))
            except ValueError: break
        tmp = _p('rows.tmp'); tmp.write_text(''.join(json.dumps(r) + '\n' for r in rows)); os.replace(tmp, _p('rows.jsonl'))
    done = {(r['option'], r['L'], r['theta']) for r in rows}; assert len(done) == len(rows)
    start = time.time(); spent = lambda: sum(r['games'] for r in rows)
    log = lambda m: (print(m, flush=True), _p('progress.log').open('a').write(m + '\n'))
    if os.environ.get('SELECT_ONLY'): print('ok', MAPS, len(MAPS) * 2 * 192); return
    for L in MAPS:
        for cell, drp in CELLS.items():
            for t in THETAS:
                if (cell, L, t) in done: continue
                if _p('STOP').exists(): log('STOP flag -> clean stop at row boundary'); return
                if spent() + GAMES[t] > MAX_GAMES or time.time() - start > MAX_SEC: log(f'STOP budget {spent()}'); return
                if not G.wait_ok(log): return
                row = D.measure('N', cell, drp, L, t, GAMES[t], SEED)
                with _p('rows.jsonl').open('a') as f: f.write(json.dumps(row) + '\n'); f.flush(); os.fsync(f.fileno())
                rows.append(row); done.add((cell, L, t))
                log(f"ROW {cell} {L} {t} {row['wins']}/{row['games']} {dict(row['fail_reasons'])} {row['sec']:.1f}s total{spent()}")
    j = judge(rows); j.update(rows=len(rows), games=spent(), rows_sha256=hashlib.sha256(_p('rows.jsonl').read_bytes()).hexdigest())
    tmp = _p('judgement.tmp'); tmp.write_text(json.dumps(j, indent=2)); os.replace(tmp, _p('judgement.json'))
    log(f'DONE {len(rows)} {spent()}')


if __name__ == '__main__':
    main()
