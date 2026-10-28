"""K1C core port parity (2026-10-27). argv[1] = byte copy of the PRE-PORT core (sha cbc2e652...).

P1 (port == subclass): pre-port core + runner subclass GrassBombBot (C) vs new core BotSimulator, both with
   v24 = BASE + key_first + bomb_count_awareness; doc-60 maps x 5 thetas x 2 games (seed 52M): chosen tile sequence,
   outcome, fail reason identical.
P2 (doc 60 reproduction): new core re-runs doc-60 N rows for maps 277 (key), 352, 467 (bomb), all thetas, 32 games,
   seed 48M -> wins / fail_reasons identical to k1c_prereg_20261027/rows.jsonl (K1C cell).
P3 (OFF invariance): pre-port vs new core with v24 = pre-adoption BASE (explicit list without K1C) on the same maps + 3 maps without key/bomb,
   5 thetas x 2 games: identical sequences.
Writes OUT/port_parity.json and the repo golden tests/golden/k1c_port/port_golden.json (P1 subset sequences).
"""
import sys, json, hashlib, importlib.util, dataclasses, os
from pathlib import Path
from collections import Counter
B_ = Path(__file__).resolve().parents[1]; sys.path[:0] = [str(B_), str(B_ / 'scripts')]
import bot_hard_key_prereg_20261027 as HK
import run_guard_20261027 as G
from app.core import bot_simulator as NEW
c = HK.c; R = HK.R
AFC = B_ / 'data/pv_sandbox/af_calibration'
OUT = AFC / 'k1c_port_20261027'
GOLD = B_ / 'tests/golden/k1c_port/port_golden.json'
K1C = ['key_first', 'bomb_count_awareness']


def load_old(path):
    assert hashlib.sha256(Path(path).read_bytes()).hexdigest().startswith('cbc2e652')
    spec = importlib.util.spec_from_file_location('app.core._bot_simulator_preport', path)
    m = importlib.util.module_from_spec(spec); m.__package__ = 'app.core'; sys.modules[spec.name] = m; spec.loader.exec_module(m)
    src = (B_ / 'scripts/bot_grass_bomb_candidates_20261027.py').read_text().replace(
        'from app.core.bot_simulator import BotSimulator, TileEffectType',
        'from app.core._bot_simulator_preport import BotSimulator, TileEffectType')
    ns = {'__name__': 'gc_preport', '__file__': str(B_ / 'scripts/bot_grass_bomb_candidates_20261027.py')}
    exec(compile(src, 'gc_preport', 'exec'), ns)
    return m, ns['GrassBombBot']


def prof(L, t, v24):
    p = c.make_skill_profile(t, 'v2.4'); cfg = dict(p.gimmick_awareness); cfg.update(c.ev.v21.FIXED)
    cfg.update(alpha=dict(c.V21_AWARENESS_DEFAULTS['alpha']), gamma=dict(c.V21_AWARENESS_DEFAULTS['gamma']), exposure=c.EX[L], parity=None,
               auto_collect=int(float(c.P[L]['row'].get('autoCollectCount') or 0)), v24_expo=c.ev._gc_expo(c.P)[L], v24=v24, grass_attention_cap=.65)
    return dataclasses.replace(p, gimmick_awareness=cfg)


def play(cls, L, t, v24, seed, layout):
    b = cls(); p = prof(L, t, v24); b.set_rule_parity(p)
    st = b._create_initial_state(json.loads(json.dumps(layout)), int(layout['max_moves'])); b._precompute_blocking_map(st)
    seq = []; orig = b._select_move_with_profile

    def rec(moves, state, profile, _o=orig):
        sel = _o(moves, state, profile)
        seq.append(None if sel is None or sel.tile_state is None else sel.tile_state.full_key)
        return sel
    b._select_move_with_profile = rec
    b._rng.seed(seed); e = b._play_game(b._fast_copy_state(st), p)
    return dict(seq=hashlib.sha256(json.dumps(seq).encode()).hexdigest()[:16], n=len(seq), cleared=e.cleared, moves=e.moves_used,
                reason=None if e.cleared else c.ev.base.fail_reason(b, e))


def main():
    old, OldGC = load_old(sys.argv[1])
    OUT.mkdir(parents=True, exist_ok=True)
    m60 = json.loads((AFC / 'k1c_prereg_20261027/manifest.json').read_text())
    maps60 = [L for v in m60['selection'].values() for L in v]
    base = [x for x in R.prior.BASE if x not in K1C]   # pre-adoption BASE (prior.BASE follows V24_DEFAULT, which now contains K1C)
    res = dict(P1=[], P2=[], P3=[])
    gold = []
    for L in maps60:
        layout = c.ev.base.level_layouts(c.P[L], 1)[0]
        for t in R.THETAS:
            for g in range(2):
                if not G.wait_ok(): return
                a = play(OldGC, L, t, base + K1C, 52000000 + g, layout); b = play(NEW.BotSimulator, L, t, base + K1C, 52000000 + g, layout)
                res['P1'].append(dict(L=L, theta=t, g=g, same=a == b))
                if L in (277, 352) and t in (.85, 1.2): gold.append(dict(L=L, theta=t, g=g, **a))
        print('P1', L, all(r['same'] for r in res['P1'] if r['L'] == L), flush=True)
    rows60 = {(r['L'], r['theta']): r for r in map(json.loads, (AFC / 'k1c_prereg_20261027/rows.jsonl').read_text().splitlines())
              if r['phase'] == 'N' and r['option'] == 'K1C'}
    for L in (277, 352, 467):
        layout = c.ev.base.level_layouts(c.P[L], 1)[0]
        for t in R.THETAS:
            if not G.wait_ok(): return
            b = NEW.BotSimulator(); p = prof(L, t, base + K1C); b.set_rule_parity(p)
            st = b._create_initial_state(json.loads(json.dumps(layout)), int(layout['max_moves'])); b._precompute_blocking_map(st)
            wins = 0; fr = Counter()
            for g in range(32):
                b._rng.seed(48000000 + g); e = b._play_game(b._fast_copy_state(st), p)
                if e.cleared: wins += 1
                else: fr[c.ev.base.fail_reason(b, e)] += 1
            ref = rows60[(L, t)]
            res['P2'].append(dict(L=L, theta=t, wins=wins, ref_wins=ref['wins'], fr=dict(fr), ref_fr=ref['fail_reasons'],
                                  same=wins == ref['wins'] and dict(fr) == ref['fail_reasons']))
        print('P2', L, [r['same'] for r in res['P2'] if r['L'] == L], flush=True)
    for L in maps60[:6] + [115, 57, 162]:
        layout = c.ev.base.level_layouts(c.P[L], 1)[0]
        for t in R.THETAS:
            for g in range(2):
                a = play(old.BotSimulator, L, t, base, 53000000 + g, layout); b = play(NEW.BotSimulator, L, t, base, 53000000 + g, layout)
                res['P3'].append(dict(L=L, theta=t, g=g, same=a == b))
        print('P3', L, all(r['same'] for r in res['P3'] if r['L'] == L), flush=True)
    summ = {k: dict(n=len(v), same=sum(r['same'] for r in v)) for k, v in res.items()}
    summ['games'] = 2 * len(res['P1']) + 32 * len(res['P2']) + 2 * len(res['P3'])
    summ['new_core_sha'] = hashlib.sha256((B_ / 'app/core/bot_simulator.py').read_bytes()).hexdigest()
    (OUT / 'port_parity.json').write_text(json.dumps(dict(summary=summ, **res), indent=1))
    GOLD.parent.mkdir(parents=True, exist_ok=True)
    GOLD.write_text(json.dumps(dict(source='pre-port core cbc2e652 + runner subclass GrassBombBot (doc 58-60)', v24_extra=K1C,
                                    seedbase=52000000, rows=gold), indent=1))
    print(json.dumps(summ))


if __name__ == '__main__':
    main()
