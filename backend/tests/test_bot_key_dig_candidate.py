"""K2 candidate key_container_dig (runner-side subclass, doc 57): OFF identity and ON behaviour."""
from __future__ import annotations

import dataclasses
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from app.core.bot_simulator import BotSimulator, Move  # noqa: E402
from app.core.mc_difficulty import make_skill_profile  # noqa: E402
import bot_key_dig_candidate_20261027 as K  # noqa: E402


def _profile(theta, v24):
    p = make_skill_profile(theta, "v2.4")
    cfg = dict(p.gimmick_awareness)
    cfg["v24"] = list(v24)
    return dataclasses.replace(p, gimmick_awareness=cfg)


def _stack_key_level(unlock=1):
    tiles = {"0_0": ["stack_n", "", [6, "t5_key_t9_t8_key_key"]]}
    for i, t in enumerate(["t5", "t5", "t9", "t9", "t8", "t8", "t1", "t1", "t1"]):
        tiles[f"{i}_2"] = [t, ""]
    return {"layer": 1, "layer_0": {"col": "10", "row": "10", "tiles": tiles, "num": str(len(tiles))},
            "randSeed": 612053, "useTileCount": 11, "unlockTile": unlock}


def _play(cls, level, profile, seed):
    b = cls()
    b.set_rule_parity(profile)
    st = b._create_initial_state(level, 60)
    b._precompute_blocking_map(st)
    seq = []
    orig = b._apply_move

    def rec(state, move, _o=orig):
        if move.tile_state is not None:
            seq.append(move.tile_state.full_key)
        return _o(state, move)

    b._apply_move = rec
    b._rng.seed(seed)
    end = b._play_game(b._fast_copy_state(st), profile)
    return seq, end.cleared, end.moves_used


def test_off_identical_to_core():
    for v24 in (["key_first"], []):
        p = _profile(1.2, v24)
        for seed in (1, 2, 3):
            assert _play(K.KeyDigBot, _stack_key_level(), p, seed) == _play(BotSimulator, _stack_key_level(), p, seed)


def test_on_without_locks_identical():
    p_on = _profile(1.2, ["key_first", K.OPTION])
    p_off = _profile(1.2, ["key_first"])
    for seed in (1, 2):
        assert _play(K.KeyDigBot, _stack_key_level(0), p_on, seed) == _play(BotSimulator, _stack_key_level(0), p_off, seed)


def test_on_bonus_for_key_container_after_first_key():
    b = K.KeyDigBot()
    b.set_rule_parity(_profile(1.2, ["key_first", K.OPTION]))
    st = b._create_initial_state(_stack_key_level(), 60)
    b._precompute_blocking_map(st)
    top = st.tiles[0]["0_0"]
    b._apply_move(st, next(m for m in b._get_available_moves(st) if m.tile_state is top))   # key 1
    b._apply_move(st, next(m for m in b._get_available_moves(st) if m.tile_state is st.tiles[0]["0_0"]))  # key 2
    moves = b._get_available_moves(st)
    dig = next(m for m in moves if m.tile_state is st.tiles[0]["0_0"])
    assert dig.tile_type == "t8"
    other = next(m for m in moves if m.tile_state is not None and not m.tile_state.is_stack_tile)
    dc = len(st.dock_tiles)
    off = BotSimulator._v24_behaviour_bonus(b, dig, st, dc, 0)
    on = b._v24_behaviour_bonus(dig, st, dc, 0)
    assert on - off == b._v24_bp["key_first_w"] * b._v24_skill()
    assert b._v24_behaviour_bonus(other, st, dc, 0) == BotSimulator._v24_behaviour_bonus(b, other, st, dc, 0)


def test_no_bonus_when_dock_tight():
    b = K.KeyDigBot()
    b.set_rule_parity(_profile(1.2, ["key_first", K.OPTION]))
    st = b._create_initial_state(_stack_key_level(), 60)
    b._precompute_blocking_map(st)
    for _ in range(2):
        b._apply_move(st, next(m for m in b._get_available_moves(st) if m.tile_state is st.tiles[0]["0_0"]))
    dig = next(m for m in b._get_available_moves(st) if m.tile_state is st.tiles[0]["0_0"])
    assert b._v24_behaviour_bonus(dig, st, 3, 0) == BotSimulator._v24_behaviour_bonus(b, dig, st, 3, 0)  # free = 6-3 = 3 < 4
