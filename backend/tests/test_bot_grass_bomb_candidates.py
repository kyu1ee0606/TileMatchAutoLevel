"""G grass_cover_blindness / C bomb_count_awareness (runner-side subclass, doc 58 draft): OFF identity, inertness, shape."""
from __future__ import annotations

import dataclasses
import math
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from app.core.bot_simulator import BotSimulator, TileEffectType  # noqa: E402
from app.core.mc_difficulty import make_skill_profile  # noqa: E402
import bot_grass_bomb_candidates_20261027 as GC  # noqa: E402

PREP = Path(__file__).resolve().parents[1] / "data/pv_sandbox/af_calibration/bot_compare_L32_500/prep.json"


def _real():
    if not PREP.exists():
        pytest.skip("measurement prep data not present")
    import bot_hard_key_prereg_20261027 as HK
    return HK


def _measure_profile(HK, L, theta, extra):
    c, R = HK.c, HK.R
    p = c.make_skill_profile(theta, "v2.4"); cfg = dict(p.gimmick_awareness); cfg.update(c.ev.v21.FIXED)
    cfg.update(alpha=dict(c.V21_AWARENESS_DEFAULTS["alpha"]), gamma=dict(c.V21_AWARENESS_DEFAULTS["gamma"]), exposure=c.EX[L],
               parity=None, auto_collect=int(float(c.P[L]["row"].get("autoCollectCount") or 0)), v24_expo=c.ev._gc_expo(c.P)[L],
               v24=[x for x in R.prior.BASE if x not in ('key_first', 'bomb_count_awareness')] + list(extra),
               grass_attention_cap=.65)   # runner subclass = pre-port measurement tool (core cbc2e652): pre-K1C BASE
    return dataclasses.replace(p, gimmick_awareness=cfg)


def _play(HK, cls, L, profile, seed, max_picks=None):
    c = HK.c
    layout = c.ev.base.level_layouts(c.P[L], 1)[0]
    b = cls(); b.set_rule_parity(profile)
    st = b._create_initial_state(layout, int(layout["max_moves"])); b._precompute_blocking_map(st)
    seq = []
    orig = b._apply_move
    main = {}

    def rec(state, move, _o=orig):
        if state is main.get("s") and move.tile_state is not None:
            seq.append(move.tile_state.full_key)
        return _o(state, move)

    b._apply_move = rec
    s = b._fast_copy_state(st); main["s"] = s
    b._rng.seed(seed)
    end = b._play_game(s, profile)
    return seq, end.cleared, end.moves_used, c.ev.base.fail_reason(b, end)


@pytest.mark.parametrize("L", [152, 293, 322])
def test_off_identical_to_core(L):
    HK = _real()
    for theta in (.85, 1.2):
        p = _measure_profile(HK, L, theta, [])
        assert _play(HK, GC.GrassBombBot, L, p, 7) == _play(HK, BotSimulator, L, p, 7)


def test_g_inert_without_grass_and_c_inert_without_bombs():
    HK = _real()
    for L, opt in ((293, GC.G_OPT), (152, GC.C_OPT)):
        assert not (opt == GC.G_OPT and HK.c.P[L]["features"].get("eff_grass"))
        assert not (opt == GC.C_OPT and HK.c.P[L]["features"].get("eff_bomb"))
        for theta in (.85, 1.2):
            on = _measure_profile(HK, L, theta, [opt])
            off = _measure_profile(HK, L, theta, [])
            assert _play(HK, GC.GrassBombBot, L, on, 3) == _play(HK, BotSimulator, L, off, 3)


def _bomb_level(counters=(3,)):
    tiles = {}
    for i, k in enumerate(counters):
        tiles[f"{i}_0"] = ["t1", f"bomb_{k}"]
    for i in range(len(counters), 3 * ((len(counters) + 2) // 3)):
        tiles[f"{i}_0"] = ["t1", ""]
    for i in range(3):
        tiles[f"{i}_2"] = ["t2", ""]
    return {"layer": 1, "layer_0": {"col": "9", "row": "9", "tiles": tiles, "num": str(len(tiles))},
            "randSeed": 5, "useTileCount": 2, "unlockTile": 0}


def _cprof(theta, opts):
    p = make_skill_profile(theta, "v2.4")
    cfg = dict(p.gimmick_awareness); cfg["v24"] = list(opts)
    cfg.setdefault("alpha", {"bomb": -1.0, "grass": -2.0, "chain": -1.0}); cfg.setdefault("gamma", {"bomb": 2.0, "grass": 0.0, "chain": 0.0})
    cfg.setdefault("beta", 4.0); cfg.setdefault("l0", .5); cfg.setdefault("tau", 15.0)
    return dataclasses.replace(p, gimmick_awareness=cfg)


def _cbot(theta=1.2, opts=(GC.C_OPT,), counters=(3,)):
    p = _cprof(theta, opts)
    b = GC.GrassBombBot(); b.set_rule_parity(p)
    st = b._create_initial_state(_bomb_level(counters), 50); b._precompute_blocking_map(st)
    return b, p, st


def test_c_notice_probability_monotone_and_equal_at_one():
    for theta in (.65, .85, 1.2):
        b, p, st = _cbot(theta)
        ps = [b._c_p(p, k) for k in (1, 2, 3, 5, 10)]
        assert all(x > y for x, y in zip(ps, ps[1:]))                         # counter down -> notice up
        assert math.isclose(ps[0], BotSimulator._v21_p_aware(b, "bomb", p, True))   # == existing imminent value


def test_c_dedicated_rng_persistence_and_removal():
    b, p, st = _cbot(counters=(9, 9))
    b._c_profile = p
    import random as _r
    st._c_rng = _r.Random(1); st._c_noticed = frozenset()
    b._rng.seed(42); main0 = b._rng.getstate()
    for _ in range(200):
        b._c_update(st)
        if len(st._c_noticed) == 2:
            break
    assert b._rng.getstate() == main0                       # main RNG never used
    assert st._c_noticed == frozenset(st.bomb_tiles)        # both noticed eventually
    # persistence: a noticed bomb stays noticed with an RNG that would never notice again
    class Never:
        def random(self): return 1.0
    st._c_rng = Never()
    b._c_update(st)
    assert st._c_noticed == frozenset(st.bomb_tiles)
    gone = sorted(st.bomb_tiles)[0]
    st.bomb_tiles.pop(gone)                                  # defused / exploded
    b._c_update(st)
    assert gone not in st._c_noticed and len(st._c_noticed) == 1


def test_c_rollout_copy_clones_rng_and_set():
    b, p, st = _cbot(counters=(9,))
    b._c_profile = p
    import random as _r
    st._c_rng = _r.Random(3); st._c_noticed = frozenset()
    parent_rng = st._c_rng.getstate()
    s = b._v2_copy_state(st)
    for _ in range(50):
        b._c_update(s)
    assert st._c_rng.getstate() == parent_rng and st._c_noticed == frozenset()
    assert s._c_rng is not st._c_rng


def test_c_urgency_sees_only_noticed_bombs():
    b, p, st = _cbot(counters=(1,))
    bomb_tile = st.tiles[0]["0_0"]
    st._c_noticed = frozenset()
    assert b._bomb_urgency(0.0, st, bomb_tile) == 0.0          # unnoticed -> invisible
    st._c_noticed = frozenset(st.bomb_tiles)
    assert b._bomb_urgency(0.0, st, bomb_tile) == BotSimulator._bomb_urgency(b, 0.0, st, bomb_tile) > 0
    assert set(st.bomb_tiles) == st._c_noticed                  # restored


def test_c_game_start_reset_and_repeatable():
    b, p, st = _cbot(counters=(4, 6))
    res = []
    for _ in range(2):
        b._rng.seed(11)
        end = b._play_game(b._fast_copy_state(st), p)
        res.append((end.cleared, end.moves_used, tuple(sorted(getattr(end, "_c_noticed", ())))))
    assert res[0] == res[1]

def _covered_grass_level():
    # layer 0: grass at 1_1 (2 layers) with neighbours; layer 1 tile covers it (same cell)
    t0 = {"1_1": ["t1", "grass"], "0_1": ["t1", ""], "2_1": ["t1", ""], "1_0": ["t2", ""], "1_2": ["t2", ""], "3_3": ["t2", ""]}
    t1 = {"1_1": ["t3", ""], "4_4": ["t3", ""], "5_5": ["t3", ""]}
    return {"layer": 2, "layer_0": {"col": "7", "row": "7", "tiles": t0, "num": "6"},
            "layer_1": {"col": "7", "row": "7", "tiles": t1, "num": "3"}, "randSeed": 9, "useTileCount": 3, "unlockTile": 0}


def _gbot(opts, theta=1.2):
    p = make_skill_profile(theta, "v2.4")
    cfg = dict(p.gimmick_awareness); cfg["v24"] = list(opts)
    p = dataclasses.replace(p, gimmick_awareness=cfg)
    b = GC.GrassBombBot(); b.set_rule_parity(p)
    st = b._create_initial_state(_covered_grass_level(), 60); b._precompute_blocking_map(st)
    return b, p, st


def test_g_hides_only_covered_grass_and_restores():
    b, p, st = _gbot([GC.G_OPT])
    grass = st.tiles[0]["1_1"]
    assert grass.effect_type == TileEffectType.GRASS and b._is_blocked_by_upper(st, grass)
    assert b._covered_grass(st) == [grass]
    with b._hide_covered_grass(st):
        assert grass.effect_type == TileEffectType.NONE
    assert grass.effect_type == TileEffectType.GRASS
    # awareness draw: only covered grass on the board -> no grass draw, no RNG use
    b._rng.seed(1); s0 = b._rng.getstate()
    b._v21_draw_awareness(st, p)
    assert "grass" not in b._v21_aware and b._rng.getstate() == s0
    # OFF: same board draws grass awareness (consumes RNG)
    b2, p2, st2 = _gbot([])
    b2._rng.seed(1); s1 = b2._rng.getstate()
    b2._v21_draw_awareness(st2, p2)
    assert "grass" in b2._v21_aware and b2._rng.getstate() != s1


def test_g_isolation_penalty_ignores_covered_grass():
    b, p, st = _gbot([GC.G_OPT])
    nb = st.tiles[0]["0_1"]
    off = BotSimulator._grass_isolation_penalty(b, 0.0, st, p, nb)
    on = b._grass_isolation_penalty(0.0, st, p, nb)
    assert on == 0.0 and off <= 0.0


def test_g_determinize_strips_copy_only():
    b, p, st = _gbot([GC.G_OPT, "unknown_hide"])
    s = b._v2_copy_state(st)
    b._v24_determinize(s)
    assert s.tiles[0]["1_1"].effect_type == TileEffectType.NONE
    assert st.tiles[0]["1_1"].effect_type == TileEffectType.GRASS
