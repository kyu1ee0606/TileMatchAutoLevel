"""K1C adoption (2026-10-27): C = bomb_count_awareness ported into the core, K1 + C in V24_DEFAULT (doc 60 §7, doc 62).

Golden tests/golden/k1c_port/port_golden.json was produced from the PRE-PORT core (sha cbc2e652):
  rows     : runner subclass GrassBombBot (doc 58-60) with v24 = BASE + K1C   -> the ported core must match (port parity)
  off_rows : pre-port core with v24 = pre-adoption BASE (no K1C)              -> the new core must match (OFF invariance)
"""
from __future__ import annotations

import dataclasses
import json
import math
import random
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from app.core import bot_simulator as BS  # noqa: E402
from app.core.bot_simulator import BotSimulator  # noqa: E402
from app.core.mc_difficulty import make_skill_profile  # noqa: E402

GOLD = json.loads((Path(__file__).parent / "golden" / "k1c_port" / "port_golden.json").read_text())
PREP = Path(__file__).resolve().parents[1] / "data/pv_sandbox/af_calibration/bot_compare_L32_500/prep.json"
C = "bomb_count_awareness"


def test_defaults_contain_k1c_and_option_registered():
    assert "key_first" in BS.V24_DEFAULT and C in BS.V24_DEFAULT


def _real():
    if not PREP.exists():
        pytest.skip("measurement prep data not present")
    import bot_k1c_port_parity_20261027 as PP
    return PP


@pytest.mark.parametrize("row", GOLD["rows"], ids=lambda r: f"on-L{r['L']}-t{r['theta']}-g{r['g']}")
def test_port_equals_subclass(row):
    PP = _real()
    layout = PP.c.ev.base.level_layouts(PP.c.P[row["L"]], 1)[0]
    got = PP.play(BotSimulator, row["L"], row["theta"], GOLD["off_v24"] + GOLD["v24_extra"], GOLD["seedbase"] + row["g"], layout)
    assert got == {k: row[k] for k in ("seq", "n", "cleared", "moves", "reason")}


@pytest.mark.parametrize("row", GOLD["off_rows"], ids=lambda r: f"off-L{r['L']}-t{r['theta']}-g{r['g']}")
def test_off_equals_preport(row):
    PP = _real()
    layout = PP.c.ev.base.level_layouts(PP.c.P[row["L"]], 1)[0]
    got = PP.play(BotSimulator, row["L"], row["theta"], GOLD["off_v24"], GOLD["off_seedbase"] + row["g"], layout)
    assert got == {k: row[k] for k in ("seq", "n", "cleared", "moves", "reason")}


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


def _prof(theta, v24):
    p = make_skill_profile(theta, "v2.4")
    cfg = dict(p.gimmick_awareness); cfg["v24"] = v24
    cfg.setdefault("alpha", {"bomb": -1.0, "grass": -2.0, "chain": -1.0}); cfg.setdefault("gamma", {"bomb": 2.0, "grass": 0.0, "chain": 0.0})
    cfg.setdefault("beta", 4.0); cfg.setdefault("l0", .5); cfg.setdefault("tau", 15.0)
    return dataclasses.replace(p, gimmick_awareness=cfg)


def _bot(theta=1.2, v24=None, counters=(3,)):
    p = _prof(theta, v24)
    b = BotSimulator(); b.set_rule_parity(p)
    st = b._create_initial_state(_bomb_level(counters), 50); b._precompute_blocking_map(st)
    return b, p, st


def test_default_profile_turns_c_on():
    b, p, st = _bot(v24=None)
    assert C in b._v24 and "key_first" in b._v24


def test_c_probability_monotone_and_equal_at_one():
    for theta in (.65, .85, 1.2):
        b, p, st = _bot(theta)
        ps = [b._v24_c_p(p, k) for k in (1, 2, 3, 5, 10)]
        assert all(x > y for x, y in zip(ps, ps[1:]))
        assert math.isclose(ps[0], b._v21_p_aware("bomb", p, True))


def test_c_dedicated_rng_persistence_and_removal():
    b, p, st = _bot(counters=(9, 9))
    b._c_profile = p
    st._c_rng = random.Random(1); st._c_noticed = frozenset()
    b._rng.seed(42); main0 = b._rng.getstate()
    for _ in range(200):
        b._v24_c_update(st)
        if len(st._c_noticed) == 2:
            break
    assert b._rng.getstate() == main0 and st._c_noticed == frozenset(st.bomb_tiles)

    class Never:
        def random(self): return 1.0
    st._c_rng = Never(); b._v24_c_update(st)
    assert st._c_noticed == frozenset(st.bomb_tiles)
    gone = sorted(st.bomb_tiles)[0]; st.bomb_tiles.pop(gone); b._v24_c_update(st)
    assert gone not in st._c_noticed and len(st._c_noticed) == 1


def test_c_copies_clone_rng_and_set():
    b, p, st = _bot(counters=(9,))
    b._c_profile = p
    st._c_rng = random.Random(3); st._c_noticed = frozenset()
    parent = st._c_rng.getstate()
    for s in (b._v2_copy_state(st), b._fast_copy_state(st)):
        for _ in range(30):
            b._v24_c_update(s)
        assert s._c_rng is not st._c_rng
    assert st._c_rng.getstate() == parent and st._c_noticed == frozenset()


def test_c_urgency_only_noticed_and_off_unmasked():
    b, p, st = _bot(counters=(1,))
    tile = st.tiles[0]["0_0"]
    st._c_noticed = frozenset()
    assert b._bomb_urgency(0.0, st, tile) == 0.0
    st._c_noticed = frozenset(st.bomb_tiles)
    assert b._bomb_urgency(0.0, st, tile) == b._bomb_urgency_core(0.0, st, tile) > 0
    off, p2, st2 = _bot(v24=["unknown_hide"], counters=(1,))
    st2._c_noticed = frozenset()
    assert off._bomb_urgency(0.0, st2, st2.tiles[0]["0_0"]) > 0          # OFF: no mask


def test_c_off_never_creates_rng():
    b, p, st = _bot(v24=["unknown_hide", "key_first"], counters=(4, 6))
    b._rng.seed(11)
    end = b._play_game(b._fast_copy_state(st), p)
    assert getattr(end, "_c_rng", None) is None and end._c_noticed == frozenset()


def test_c_game_start_reset_and_repeatable():
    b, p, st = _bot(counters=(4, 6))
    res = []
    for _ in range(2):
        b._rng.seed(11)
        end = b._play_game(b._fast_copy_state(st), p)
        res.append((end.cleared, end.moves_used, tuple(sorted(end._c_noticed))))
    assert res[0] == res[1]
