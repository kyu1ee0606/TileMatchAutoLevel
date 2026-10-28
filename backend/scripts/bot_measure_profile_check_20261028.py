"""Check (doc 26, 2026-10-28): shared make_measure_profile cfg == validation-runner cfg, then ~200 games identical.
Runner cfg = bot_drp_candidates_20261027.profile (drp None) and the inline code of bot_p2_prereg_20261027.measure (replicated).
Rows: 12 levels x theta {.65, 1.2}; first layout of bot_layouts_util plan; 8 games/row at theta .65, 8 at 1.2 -> 192 games per profile.
No DDA run.  Run with the repo venv; single process; AFTER any running measurement finishes."""
import sys, json, dataclasses, hashlib
from pathlib import Path
B_ = Path(__file__).resolve().parents[1]; sys.path[:0] = [str(B_), str(B_ / 'scripts')]
import bot_drp_candidates_20261027 as D
import bot_measure_profile as MP
c = D.c
LEVELS = [40, 52, 135, 202, 233, 247, 299, 331, 388, 450, 100, 275]


def p2_cfg_profile(L, t):
    p = c.make_skill_profile(t, 'v2.4'); cfg = dict(p.gimmick_awareness); cfg.update(c.ev.v21.FIXED)
    cfg.update(alpha=dict(c.V21_AWARENESS_DEFAULTS['alpha']), gamma=dict(c.V21_AWARENESS_DEFAULTS['gamma']), exposure=c.EX[L], parity=None,
               auto_collect=int(float(c.P[L]['row'].get('autoCollectCount') or 0)), v24_expo=c.ev._gc_expo(c.P)[L],
               v24=list(D.BASE), grass_attention_cap=.65)
    return dataclasses.replace(p, gimmick_awareness=cfg)


def main():
    ac = [L for L in LEVELS if float(c.P[L]['row'].get('autoCollectCount') or 0) > 0]
    print('levels', LEVELS, 'auto_collect>0:', ac); assert ac, 'need an auto_collect level'
    cfg_ok = 0; games = 0; same = 0
    for L in LEVELS:
        for t in (.65, 1.2):
            a, _ = MP.make_measure_profile(t, L); b = D.profile(L, t, None); p = p2_cfg_profile(L, t)
            assert a == b == p, (L, t); assert list(a.gimmick_awareness) == list(b.gimmick_awareness) and a.gimmick_awareness['v24'] == b.gimmick_awareness['v24']
            assert json.dumps(a.gimmick_awareness) == json.dumps(b.gimmick_awareness)
            cfg_ok += 1
            plan = D.LU.layouts_for(c, L, 16); lay = plan[0][0]
            res = []
            for prof in (a, b):
                bot = c.BotSimulator(); bot.set_rule_parity(prof)
                st = bot._create_initial_state(json.loads(json.dumps(lay)), int(lay['max_moves'])); bot._precompute_blocking_map(st)
                out = []
                for g in range(8):
                    bot._rng.seed(75000000 + g); e = bot._play_game(bot._fast_copy_state(st), prof); out.append((bool(e.cleared), e.total_tiles_cleared))
                res.append(out); games += 8
            assert res[0] == res[1], (L, t); same += 8
    # fallback rule
    for L in (1, 31, 501, 1200):
        pr, info = MP.make_measure_profile(1.0, L); print('fallback', L, info, pr.gimmick_awareness['exposure'], pr.gimmick_awareness['v24_expo'])
    assert MP.exposure_for(32)[2] == 'cache' and MP.exposure_for(500)[2] == 'cache'
    print(f'OK cfg_equal={cfg_ok} rows, games identical {same}/{games} (shared profile played {games // 2} + runner profile {games // 2})')


if __name__ == '__main__':
    main()
