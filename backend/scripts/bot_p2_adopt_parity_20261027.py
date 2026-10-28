"""P2 (public_craft_belief) default adoption parity (2026-10-27, doc 68 §7 support). argv[1] = byte copy of the
PRE-ADOPTION core (sha 39d2de55...).  The core change is V24_DEFAULT += public_craft_belief only.

A0: prior.BASE (measurement BASE, follows V24_DEFAULT) == doc-68 manifest base + public_craft_belief (as sets).
A1 (ON reproduction): new core, v24 = new prior.BASE (no extra) re-runs doc-68 N rows of the P2 cell for maps
    374, 331 (random, 16 layouts), 172, 197 at theta .65/.85 (32 games) + L374 theta 1.2 (128) -> wins and
    fail_reasons identical to p2_prereg_20261027/rows.jsonl.
A2 (OFF reproduction): new core, v24 = new prior.BASE minus public_craft_belief re-runs the same rows of the B' cell.
A3 (V24_DEFAULT-only path = DDA/default v2.4 profile without hcs; P2 must be inert): pre-adoption core vs new core,
    profile = make_skill_profile(theta, 'v2.4') untouched; maps 374, 331, 172, 277, 138 x theta .65/.85/1.2 x 2 games
    (seed 72M): chosen tile sequence, outcome, fail reason identical.
A4 (API/editor v1 path): same with make_skill_profile(theta, 'v1'), maps 374, 172 x theta .85/1.2 x 2 games.
Guard + STOP flag.  Writes OUT/adopt_parity.json.
"""
import sys, json, hashlib, importlib.util, os
from pathlib import Path
B_ = Path(__file__).resolve().parents[1]; sys.path[:0] = [str(B_), str(B_ / 'scripts')]
import bot_p2_prereg_20261027 as M
import run_guard_20261027 as G
from app.core import bot_simulator as NEW
c = M.c; R = M.R
AFC = B_ / 'data/pv_sandbox/af_calibration'
OUT = AFC / 'p2_adopt_20261027'
P2 = 'public_craft_belief'


def load_old(path):
    assert hashlib.sha256(Path(path).read_bytes()).hexdigest() == M.CORE
    spec = importlib.util.spec_from_file_location('app.core._bot_simulator_preadopt', path)
    m = importlib.util.module_from_spec(spec); m.__package__ = 'app.core'; sys.modules[spec.name] = m; spec.loader.exec_module(m)
    return m


def play(cls, L, t, ver, seed):
    layout = c.ev.base.level_layouts(c.P[L], 1)[0]
    b = cls(); p = c.make_skill_profile(t, ver); b.set_rule_parity(p)
    st = b._create_initial_state(json.loads(json.dumps(layout)), int(layout['max_moves'])); b._precompute_blocking_map(st)
    seq = []; orig = b._select_move_with_profile

    def rec(moves, state, profile, _o=orig):
        sel = _o(moves, state, profile)
        seq.append(None if sel is None or sel.tile_state is None else sel.tile_state.full_key)
        return sel
    b._select_move_with_profile = rec
    b._rng.seed(seed); e = b._play_game(b._fast_copy_state(st), p)
    return dict(seq=hashlib.sha256(json.dumps(seq).encode()).hexdigest()[:16], n=len(seq), cleared=e.cleared, moves=e.moves_used,
                reason=None if e.cleared else c.ev.base.fail_reason(b, e), v24=sorted(b._v24))


def main():
    old = load_old(sys.argv[1]); OUT.mkdir(parents=True, exist_ok=True)
    assert P2 in NEW.V24_DEFAULT and P2 not in old.V24_DEFAULT
    man = json.loads((AFC / 'p2_prereg_20261027/manifest.json').read_text())
    rows68 = {(r['option'], r['L'], r['theta']): r for r in map(json.loads, (AFC / 'p2_prereg_20261027/rows.jsonl').read_text().splitlines())
              if r['phase'] == 'N'}
    res = dict(A0=set(R.prior.BASE) == set(man['base']) | {P2}, A1=[], A2=[], A3=[], A4=[])
    print('A0', res['A0'], flush=True)
    stop = lambda: (OUT / 'STOP').exists() or not G.wait_ok()
    jobs = [(L, t) for L in (374, 331, 172, 197) for t in (.65, .85)] + [(374, 1.2)]
    for key, base, cell in (('A1', list(R.prior.BASE), 'P2'), ('A2', [x for x in R.prior.BASE if x != P2], "B'")):
        M.BASE = base
        for L, t in jobs:
            if stop(): print('STOP'); return
            r = M.measure('N', "B'", L, t, M.SEEDS['N']); ref = rows68[cell, L, t]
            same = (r['wins'], r['fail_reasons'], r['games']) == (ref['wins'], ref['fail_reasons'], ref['games'])
            res[key].append(dict(L=L, theta=t, wins=r['wins'], ref=ref['wins'], same=same)); print(key, L, t, same, r['wins'], ref['wins'], flush=True)
    for key, ver, maps, thetas in (('A3', 'v2.4', (374, 331, 172, 277, 138), (.65, .85, 1.2)), ('A4', 'v1', (374, 172), (.85, 1.2))):
        for L in maps:
            for t in thetas:
                for g in range(2):
                    if stop(): print('STOP'); return
                    a = play(old.BotSimulator, L, t, ver, 72000000 + g); b = play(NEW.BotSimulator, L, t, ver, 72000000 + g)
                    same = {k: v for k, v in a.items() if k != 'v24'} == {k: v for k, v in b.items() if k != 'v24'}
                    res[key].append(dict(L=L, theta=t, g=g, same=same, p2_in_new=P2 in b['v24']))
            print(key, L, all(x['same'] for x in res[key] if x['L'] == L), flush=True)
    summ = {k: (v if k == 'A0' else f"{sum(x['same'] for x in v)}/{len(v)}") for k, v in res.items()}
    games = sum(32 if t < 1 else 128 for _, t in jobs) * 2 + 2 * (len(res['A3']) + len(res['A4']))
    out = dict(summary=summ, games=games, new_core=hashlib.sha256((B_ / 'app/core/bot_simulator.py').read_bytes()).hexdigest(),
               old_core=M.CORE, detail=res)
    tmp = OUT / 'adopt_parity.tmp'; tmp.write_text(json.dumps(out, indent=2)); os.replace(tmp, OUT / 'adopt_parity.json')
    print('DONE', summ, games, flush=True)


if __name__ == '__main__':
    main()
