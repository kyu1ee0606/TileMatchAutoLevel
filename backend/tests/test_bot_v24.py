"""Bot v2.4 — hidden-type information parity + cat-help (냥이의 도움) policy (26_bot_v24.md).

Tiny fixed boards: v2.3 vs v2.4 with only the relevant item on.
"""
import dataclasses

from app.core.bot_simulator import BotSimulator, TileEffectType
from app.core.mc_difficulty import make_skill_profile


def _level(layers, **extra):
    lj = {"layer": len(layers), "randSeed": 1, "useTileCount": 6, "unlockTile": 0, "max_moves": 200}
    for i, tiles in enumerate(layers):
        lj[f"layer_{i}"] = {"col": "7", "row": "7", "tiles": tiles, "num": str(len(tiles))}
    lj.update(extra)
    return lj


def _bot(lj, version="v2.3", v24=(), auto_collect=0, p_savvy=None):
    prof = make_skill_profile(1.0, version)
    cfg = dict(prof.gimmick_awareness)
    cfg["parity"] = None
    cfg["auto_collect"] = auto_collect
    if version == "v2.4":
        cfg["v24"] = list(v24)
        if p_savvy is not None:
            cfg["ac_p_savvy"] = p_savvy
    prof = dataclasses.replace(prof, gimmick_awareness=cfg)
    bot = BotSimulator()
    bot.set_rule_parity(prof)
    state = bot._create_initial_state(lj, int(lj["max_moves"]))
    bot._precompute_blocking_map(state)
    return bot, state, prof


def _move_at(bot, state, layer, pos):
    for m in bot._get_available_moves(state):
        if m.layer_idx == layer and m.position == pos:
            return m
    return None


def _score(bot, state, prof, layer, pos):
    bot._rng.seed(5)
    bot._v21_aware = {}
    return bot._score_move_with_profile(_move_at(bot, state, layer, pos), state, prof)


# Stack top t2 (dispenses t2) + an unknown t2 at layer 0 3_3 covered by layer 2 3_3.
UNKNOWN_COVERED = _level([
    {"0_0": ["stack_e", "", [2, "t1_t2"]], "3_3": ["t2", "unknown"], "5_5": ["t2", ""], "6_6": ["t1", ""],
     "6_5": ["t1", ""]},
    {},
    {"3_3": ["t3", ""], "0_6": ["t3", ""], "1_6": ["t3", ""]},
], goalCount={"stack_e": 1})


def test_unknown_type_hidden_while_covered():
    """Game: a covered unknown shows '?' and is revealed only when nothing covers it (TileEffect.cs:924-943)."""
    bot, st, _ = _bot(UNKNOWN_COVERED, "v2.4", ["unknown_hide"])
    unk = st.tiles[0]["3_3"]
    assert unk.effect_type == TileEffectType.UNKNOWN
    assert bot._v24_type_hidden(st, unk)
    assert bot._v2_step(st, _move_at(bot, st, 2, "3_3"))
    assert not bot._v24_type_hidden(st, unk)


def test_stack_impact_ignores_hidden_unknown_type():
    """v2.3's stack/craft impact bonus counted field tiles 'waiting' for the dispensed type, incl. covered unknowns
    whose type the player cannot see."""
    bot, st, prof = _bot(UNKNOWN_COVERED, "v2.3")
    s23 = _score(bot, st, prof, 0, "0_0")
    bot, st, prof = _bot(UNKNOWN_COVERED, "v2.4", [])
    assert _score(bot, st, prof, 0, "0_0") == s23                   # v2.4 with no item = v2.3
    bot, st, prof = _bot(UNKNOWN_COVERED, "v2.4", ["unknown_hide"])
    assert _score(bot, st, prof, 0, "0_0") < s23
    assert bot._v2_step(st, _move_at(bot, st, 2, "3_3"))              # once revealed, it counts again
    s_rev = _score(bot, st, prof, 0, "0_0")
    bot2, st2, prof2 = _bot(UNKNOWN_COVERED, "v2.3")
    assert bot2._v2_step(st2, _move_at(bot2, st2, 2, "3_3"))
    assert s_rev == _score(bot2, st2, prof2, 0, "0_0")


def test_exposed_unknown_gets_no_reveal_bonus():
    """An exposed unknown is already revealed in the game (TileEffect.cs:646-654) → no 'early reveal' bonus."""
    lj = _level([{"0_0": ["t1", "unknown"], "1_0": ["t1", ""], "2_0": ["t1", ""]}])
    bot, st, prof = _bot(lj, "v2.3")
    s23 = _score(bot, st, prof, 0, "0_0")
    bot, st, prof = _bot(lj, "v2.4", ["unknown_nobonus"])
    s24 = _score(bot, st, prof, 0, "0_0")
    assert s24 < s23
    bot, st, prof = _bot(lj, "v2.4", ["unknown_nobonus"])
    assert _score(bot, st, prof, 0, "1_0") == _score(*_bot(lj, "v2.3"), 0, "1_0")   # plain tiles unchanged


def test_closed_curtain_type_hidden():
    lj = _level([{"3_3": ["t1", "curtain_close"], "0_0": ["t1", ""]}, {}, {"3_3": ["t2", ""]}])
    bot, st, _ = _bot(lj, "v2.4", ["curtain_hide"])
    assert bot._v24_type_hidden(st, st.tiles[0]["3_3"])
    assert not bot._v24_type_hidden(st, st.tiles[0]["0_0"])


# ── 냥이의 도움 savvy policy ───────────────────────────────────────────────────────────────────
CAT4 = _level([{f"{x}_{2 * k}": [f"t{k + 1}", ""] for x in range(6) for k in range(4)}])


def _cat_state(savvy):
    bot, st, prof = _bot(CAT4, "v2.4", ["ac_policy"])
    for pos in ("0_0", "1_0"):                                       # dock: t1 (badge) + t1
        assert bot._v2_step(st, _move_at(bot, st, 0, pos))
    st._ac = {"buffer": {"t1": 2}, "badge": {"t1": 1}, "phase": "playing", "savvy": savvy}
    moves = bot._get_available_moves(st)
    for m in moves:
        m.score = _score(bot, st, prof, m.layer_idx, m.position)
    return bot, st, moves


def test_savvy_delays_last_badge_and_adds_new_types():
    """Game: when the last badge triple completes, the cat fills every incomplete type of this cycle's buffer
    (AutoCollectController.cs:549-564, 973-987) → savvy users fill the dock with new types first."""
    bot, st, moves = _cat_state(True)
    pick = bot._v24_savvy_select(moves, st)
    assert pick is not None and pick.tile_type != "t1"
    for _ in range(4):                                              # fill dock to 6 (= 7 slots − 1)
        m = bot._v24_savvy_select(moves, st)
        assert m.tile_type != "t1"
        assert bot._v2_step(st, m)
        for tt in [m.tile_type]:
            st._ac["buffer"][tt] = st._ac["buffer"].get(tt, 0) + 1
        moves = bot._get_available_moves(st)
        for mv in moves:
            mv.score = 0.0
    assert len(st.dock_tiles) == 6
    assert bot._v24_savvy_select(moves, st).tile_type == "t1"         # now trigger the collection


def test_naive_plays_as_usual():
    bot, st, moves = _cat_state(False)
    assert bot._v24_savvy_select(moves, st) is None


def test_p_savvy_draw_per_game():
    lj = CAT4
    for p, expect in ((1.0, True), (0.0, False)):
        bot, st, prof = _bot(lj, "v2.4", ["ac_policy"], auto_collect=1, p_savvy=p)
        bot._v23_game_start(st)
        assert st._ac["savvy"] is expect
        assert len(st.dock_tiles) == 3


def test_v24_without_items_equals_v23():
    lj = _level([{f"{x}_{y}": [f"t{(x + y) % 4 + 1}", "unknown" if (x + y) % 5 == 0 else ""]
                  for x in range(6) for y in range(6)},
                 {},
                 {f"{x}_{y}": [f"t{(x * y) % 4 + 1}", ""] for x in range(1, 5) for y in range(1, 4)}])
    out = []
    for ver in ("v2.3", "v2.4"):
        bot, st0, prof = _bot(lj, ver, [])
        res = []
        for g in range(6):
            bot._rng.seed(100 + g)
            s = bot._play_game(bot._fast_copy_state(st0), prof)
            res.append((s.cleared, s.moves_used, s.total_tiles_cleared))
        out.append(res)
    assert out[0] == out[1]


# ── curtain memory ─────────────────────────────────────────────────────────────────────────────
CURTAIN_LV = _level([{"0_0": ["t1", "curtain_open"], "2_0": ["t1", ""], "4_0": ["t2", ""],
                      "0_4": ["t3", "curtain_close"], "2_4": ["t3", ""]}])


def _cmem_bot(a):
    prof = make_skill_profile(1.0, "v2.4")
    cfg = dict(prof.gimmick_awareness)
    cfg.update(parity=None, auto_collect=0, v24=["curtain_memory_v24"], curtain_mem={"a": a, "b": 4.0, "c": 0.5})
    prof = dataclasses.replace(prof, gimmick_awareness=cfg)
    bot = BotSimulator()
    bot.set_rule_parity(prof)
    st = bot._create_initial_state(CURTAIN_LV, 200)
    bot._precompute_blocking_map(st)
    return bot, st


def _close(st, pos):
    st.tiles[0][pos].effect_data["is_open"] = False
    st.curtain_tiles[f"0_{pos}"] = False
    st.moves_used += 1


def test_curtain_remembered_type_counts_for_planning():
    """Seen open → closes → remembered (high a): counted as available next turn; forgotten (low a): unknown."""
    for a, expect in ((20.0, 2), (-20.0, 1)):
        bot, st = _cmem_bot(a)
        bot._v24_curtain_update(st)                               # sees t1 open at 0_0
        _close(st, "0_0")
        bot._v24_curtain_update(st)
        assert bot._get_accessible_type_counts(st).get("t1", 0) == expect
        assert bot._v24_type_hidden(st, st.tiles[0]["0_0"]) is (expect == 1)


def test_never_seen_closed_curtain_unknown():
    bot, st = _cmem_bot(20.0)
    bot._v24_curtain_update(st)
    assert bot._v24_type_hidden(st, st.tiles[0]["0_4"])
    assert bot._get_accessible_type_counts(st).get("t3", 0) == 1    # only the plain t3


def test_curtain_memory_decays_with_turns():
    bot, st = _cmem_bot(1.0)                                       # p(k) = σ(1 − 0.5k): k=1 0.62 … k=8 0.05
    bot._v24_curtain_update(st)
    _close(st, "0_0")
    bot._rng.seed(0)
    kept = []
    for _ in range(10):
        bot._v24_curtain_update(st)
        kept.append(not bot._v24_type_hidden(st, st.tiles[0]["0_0"]))
        st.moves_used += 1
    assert kept == sorted(kept, reverse=True)                       # once forgotten, stays forgotten
    assert not kept[-1]
