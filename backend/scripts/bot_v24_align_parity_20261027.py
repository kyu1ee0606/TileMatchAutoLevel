"""B alignment parity (2026-10-27, user decision): V24_DEFAULT += the three items the measurement BASE adds
(grass_skill_attention, hidden_common_samples, public_key_stack_plan), so that the V24_DEFAULT-only path (profile
without an explicit cfg['v24']) runs the same rule set as the measurement BASE (prior.BASE).
argv[1] = byte copy of the PRE-ALIGNMENT core (sha 4b31534c...).

B0: set(new V24_DEFAULT) == set(old prior.BASE) == set(new prior.BASE)  (prior.BASE = V24_DEFAULT + the same 3 ->
    duplicates are harmless: set_rule_parity takes a frozenset).
B1 (default-only == measurement BASE): measurement cfg (FIXED, exposure, v24_expo, auto_collect, cap .65) per map;
    old core with v24 = old prior.BASE (explicit)  vs  new core with cfg['v24'] absent (-> V24_DEFAULT)  vs  new core with
    v24 = new prior.BASE (explicit).  10 maps (bomb, craft, curtain, link, key, grass, stack, chain, unknown, ice +
    autoCollect) x theta .65/.85/1.2 x 2 games (seed 74M) -> chosen tile sequence, outcome, moves, fail reason identical.
B2 (measurement BASE path unchanged): new core re-runs doc-68 N rows of the P2 cell (L172, L197 x theta .65/.85, 32 games,
    bot_p2_prereg_20261027.measure with BASE = new prior.BASE) -> wins / fail_reasons identical; doc-69 L82 P2 cell games
    g 0..3 (theta 1.2, seed 70M) -> chosen key sequence and outcome identical to l82_trace_20261027/trace_rows.jsonl.
B3 (API/editor v1 path): old vs new make_skill_profile(theta, 'v1'), maps 374, 172 x theta .85/1.2 x 2 games.
Report only (expected to differ = the intended DDA behaviour change): raw make_skill_profile(theta, 'v2.4') (the DDA
    script path) old vs new core on the B1 maps x theta x 1 game -> same / differ counts and wins.
Guard + STOP flag.  Writes OUT/align_parity.json.
"""
import sys, json, hashlib, importlib.util, os, dataclasses
from pathlib import Path
B_ = Path(__file__).resolve().parents[1]; sys.path[:0] = [str(B_), str(B_ / 'scripts')]
import bot_p2_prereg_20261027 as M
import trace_parity_20261026 as TP
import run_guard_20261027 as G
from app.core import bot_simulator as NEW
c = M.c; R = M.R
AFC = B_ / 'data/pv_sandbox/af_calibration'
OUT = AFC / 'b_align_20261027'
OLD_SHA = '4b31534c74ca47c703127bb598ae71e2204ea74f3088be3a368839cdfc1f53e0'
ADD = ['grass_skill_attention', 'hidden_common_samples', 'public_key_stack_plan']
B1_MAPS = [374, 331, 138, 277, 269, 275, 388, 378, 197, 40]
THETAS = (.65, .85, 1.2)


def load_old(path):
    assert hashlib.sha256(Path(path).read_bytes()).hexdigest() == OLD_SHA
    spec = importlib.util.spec_from_file_location('app.core._bot_simulator_prealign', path)
    m = importlib.util.module_from_spec(spec); m.__package__ = 'app.core'; sys.modules[spec.name] = m; spec.loader.exec_module(m)
    return m


def meas_prof(L, t, v24):
    p = c.make_skill_profile(t, 'v2.4'); cfg = dict(p.gimmick_awareness); cfg.update(c.ev.v21.FIXED)
    cfg.update(alpha=dict(c.V21_AWARENESS_DEFAULTS['alpha']), gamma=dict(c.V21_AWARENESS_DEFAULTS['gamma']), exposure=c.EX[L], parity=None,
               auto_collect=int(float(c.P[L]['row'].get('autoCollectCount') or 0)), v24_expo=c.ev._gc_expo(c.P)[L], grass_attention_cap=.65)
    if v24 is not None:
        cfg['v24'] = list(v24)
    assert ('v24' in cfg) == (v24 is not None)
    return dataclasses.replace(p, gimmick_awareness=cfg)


def play(cls, L, p, seed):
    layout = c.ev.base.level_layouts(c.P[L], 1)[0]
    b = TP.recorder(cls)(); b.set_rule_parity(p)
    st = b._create_initial_state(json.loads(json.dumps(layout)), int(layout['max_moves'])); b._precompute_blocking_map(st)
    b._rng.seed(seed); e = b._play_game(b._fast_copy_state(st), p)
    return dict(seq=hashlib.sha256(json.dumps(b.choice_keys).encode()).hexdigest()[:16], n=len(b.choice_keys), cleared=e.cleared,
                moves=e.moves_used, reason=None if e.cleared else c.ev.base.fail_reason(b, e)), sorted(b._v24)


def main():
    old = load_old(sys.argv[1]); OUT.mkdir(parents=True, exist_ok=True)
    old_base = list(old.V24_DEFAULT) + ADD
    new_base = list(R.prior.BASE)
    res = dict(B0=dict(new_default_eq_old_base=set(NEW.V24_DEFAULT) == set(old_base),
                       new_base_eq_old_base=set(new_base) == set(old_base),
                       added=sorted(set(NEW.V24_DEFAULT) - set(old.V24_DEFAULT)), removed=sorted(set(old.V24_DEFAULT) - set(NEW.V24_DEFAULT))),
               B1=[], B2=[], B3=[], DDA=[])
    print('B0', res['B0'], flush=True)
    stop = lambda: (OUT / 'STOP').exists() or not G.wait_ok()
    games = 0
    for L in B1_MAPS:
        for t in THETAS:
            for g in range(2):
                if stop(): print('STOP'); return
                s = 74000000 + g
                a, va = play(old.BotSimulator, L, meas_prof(L, t, old_base), s)
                b, vb = play(NEW.BotSimulator, L, meas_prof(L, t, None), s)
                d, vd = play(NEW.BotSimulator, L, meas_prof(L, t, new_base), s); games += 3
                res['B1'].append(dict(L=L, theta=t, g=g, same=a == b == d, rules_same=va == vb == vd, old=a, default_only=b))
        print('B1', L, all(x['same'] and x['rules_same'] for x in res['B1'] if x['L'] == L), flush=True)
    rows68 = {(r['option'], r['L'], r['theta']): r for r in map(json.loads, (AFC / 'p2_prereg_20261027/rows.jsonl').read_text().splitlines())
              if r['phase'] == 'N'}
    M.BASE = new_base
    for L, t in ((172, .65), (172, .85), (197, .65), (197, .85)):
        if stop(): print('STOP'); return
        r = M.measure('N', "B'", L, t, M.SEEDS['N']); ref = rows68['P2', L, t]; games += r['games']
        same = (r['wins'], r['fail_reasons'], r['games']) == (ref['wins'], ref['fail_reasons'], ref['games'])
        res['B2'].append(dict(src='68', L=L, theta=t, wins=r['wins'], ref=ref['wins'], same=same)); print('B2 68', L, t, same, flush=True)
    tr = {(r['cell'], r['g']): r for r in map(json.loads, (AFC / 'l82_trace_20261027/trace_rows.jsonl').read_text().splitlines())}
    layout = c.ev.base.level_layouts(c.P[82], 1)[0]
    for g in range(4):
        if stop(): print('STOP'); return
        p = meas_prof(82, 1.2, new_base)
        b = TP.recorder(NEW.BotSimulator)(); b.set_rule_parity(p)
        st = b._create_initial_state(json.loads(json.dumps(layout)), int(layout['max_moves'])); b._precompute_blocking_map(st)
        b._rng.seed(70000000 + g); e = b._play_game(b._fast_copy_state(st), p); games += 1
        ref = tr['P2', g]
        same = b.choice_keys == ref['keys'] and e.cleared == ref['cleared']
        res['B2'].append(dict(src='69', L=82, theta=1.2, g=g, same=same)); print('B2 69', g, same, flush=True)
    for L in (374, 172):
        for t in (.85, 1.2):
            for g in range(2):
                if stop(): print('STOP'); return
                a, _ = play(old.BotSimulator, L, c.make_skill_profile(t, 'v1'), 74000000 + g)
                b, _ = play(NEW.BotSimulator, L, c.make_skill_profile(t, 'v1'), 74000000 + g); games += 2
                res['B3'].append(dict(L=L, theta=t, g=g, same=a == b))
    print('B3', all(x['same'] for x in res['B3']), flush=True)
    for L in B1_MAPS:
        for t in THETAS:
            if stop(): print('STOP'); return
            a, _ = play(old.BotSimulator, L, c.make_skill_profile(t, 'v2.4'), 74000000)
            b, _ = play(NEW.BotSimulator, L, c.make_skill_profile(t, 'v2.4'), 74000000); games += 2
            res['DDA'].append(dict(L=L, theta=t, same=a == b, old_cleared=a['cleared'], new_cleared=b['cleared']))
    print('DDA', sum(x['same'] for x in res['DDA']), '/', len(res['DDA']), flush=True)
    summ = dict(B0=all(v for k, v in res['B0'].items() if k.endswith('base')),
                B1=f"{sum(x['same'] and x['rules_same'] for x in res['B1'])}/{len(res['B1'])}",
                B2=f"{sum(x['same'] for x in res['B2'])}/{len(res['B2'])}", B3=f"{sum(x['same'] for x in res['B3'])}/{len(res['B3'])}",
                DDA_raw_same_report_only=f"{sum(x['same'] for x in res['DDA'])}/{len(res['DDA'])}",
                DDA_raw_wins_old_new=[sum(x['old_cleared'] for x in res['DDA']), sum(x['new_cleared'] for x in res['DDA'])])
    out = dict(summary=summ, games=games, new_core=hashlib.sha256((B_ / 'app/core/bot_simulator.py').read_bytes()).hexdigest(),
               old_core=OLD_SHA, detail=res)
    tmp = OUT / 'align_parity.tmp'; tmp.write_text(json.dumps(out, indent=2)); os.replace(tmp, OUT / 'align_parity.json')
    print('DONE', summ, games, flush=True)


if __name__ == '__main__':
    main()
