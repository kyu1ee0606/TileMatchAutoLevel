"""P2 default adoption (2026-10-27): public_craft_belief in V24_DEFAULT (doc 68 PREREG support, user pre-approval).

The option only acts on the public-sample determinization path (hidden_common_samples, measurement BASE = prior.BASE).
Golden tests/golden/p2_default/def_golden.json was produced from the PRE-ADOPTION core (sha 39d2de55) with the
untouched make_skill_profile(theta, 'v2.4') / ('v1') profiles: the new core must reproduce it (P2 inert there).
Full reproduction/OFF parity: scripts/bot_p2_adopt_parity_20261027.py -> p2_adopt_20261027/adopt_parity.json.
"""
from __future__ import annotations

import dataclasses
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from app.core import bot_simulator as BS  # noqa: E402
from app.core.bot_simulator import BotSimulator, GameState, TileState  # noqa: E402
from app.core.mc_difficulty import make_skill_profile  # noqa: E402

P2 = "public_craft_belief"
B_ALIGN_ADDED = ("grass_skill_attention", "hidden_common_samples", "public_key_stack_plan")
PRE_ALIGN = tuple(x for x in BS.V24_DEFAULT if x not in B_ALIGN_ADDED)   # V24_DEFAULT before the B alignment (frozen list)
GOLD_PATH = Path(__file__).parent / "golden" / "p2_default" / "def_golden.json"
PREP = Path(__file__).resolve().parents[1] / "data/pv_sandbox/af_calibration/bot_compare_L32_500/prep.json"


def test_default_contains_p2_and_keeps_k1c():
    assert P2 in BS.V24_DEFAULT
    assert "key_first" in BS.V24_DEFAULT and "bomb_count_awareness" in BS.V24_DEFAULT
    assert "hidden_common_samples" in BS.V24_DEFAULT   # B alignment 2026-10-27: default == measurement BASE


def test_default_profile_turns_p2_on_v1_off():
    b = BotSimulator(); b.set_rule_parity(make_skill_profile(1.2, "v2.4"))
    assert P2 in b._v24
    b = BotSimulator(); b.set_rule_parity(make_skill_profile(1.2, "v1"))
    assert P2 not in b._v24


def _bot(v24):
    b = BotSimulator(); p = make_skill_profile(1.2, "v2.4")
    p = dataclasses.replace(p, gimmick_awareness=dict(p.gimmick_awareness, v24=list(v24)))
    b.set_rule_parity(p)
    return b


def _craft_state(secret="t1"):
    # board: t1 visible, dock: t1; craft box holds one unspawned tile whose true type is `secret`
    a = TileState("t1", 0, 0, 0)
    box = TileState(secret, 0, 3, 3, is_stack_tile=True, is_craft_tile=True, stack_index=0)
    return GameState(tiles={0: {"0_0": a}}, dock_tiles=[TileState("t1", 0, 1, 0)],
                     stacked_tiles={box.full_key: box}), box


@pytest.mark.parametrize("secret", ["t1", "t9"])
def test_public_path_samples_unspawned_craft_without_truth(secret):
    st, box = _craft_state(secret)
    b = _bot(list(BS.V24_DEFAULT) + ["hidden_common_samples"])
    assert b._v24_determinize(st)
    assert box.tile_type == "t1"   # triplet rule from public counts (t1 x2 visible) regardless of the hidden truth


def test_public_path_without_p2_refuses():
    st, box = _craft_state("t9")
    b = _bot([x for x in BS.V24_DEFAULT if x != P2] + ["hidden_common_samples"])
    assert b._v24_determinize(st) is False
    assert box.tile_type == "t9"


def test_default_only_path_does_not_touch_craft():
    st, box = _craft_state("t9")
    b = _bot(PRE_ALIGN)   # pre-alignment default-only path (no hidden_common_samples)
    b._v24_determinize(st)
    assert box.tile_type == "t9"


def _gold():
    if not PREP.exists() or not GOLD_PATH.exists():
        pytest.skip("measurement prep data / golden not present")
    import bot_p2_adopt_parity_20261027 as PA
    return PA, json.loads(GOLD_PATH.read_text())


@pytest.mark.parametrize("i", range(8))
def test_default_and_v1_profiles_equal_preadoption(i, monkeypatch):
    PA, gold = _gold()
    row = gold["rows"][i]
    # golden = pre-P2 core with the then-default list; the B alignment intentionally changes the raw v2.4 default path,
    # so freeze the pre-alignment list for it (v1 rows ignore V24_DEFAULT).
    monkeypatch.setattr(BS, "V24_DEFAULT", PRE_ALIGN)
    got = PA.play(BotSimulator, row["L"], row["theta"], row["ver"], gold["seedbase"] + row["g"])
    assert {k: got[k] for k in ("seq", "n", "cleared", "moves", "reason")} == {k: row[k] for k in ("seq", "n", "cleared", "moves", "reason")}


def test_b_align_default_equals_measurement_base_items():
    assert set(B_ALIGN_ADDED) <= set(BS.V24_DEFAULT)
    b = BotSimulator(); b.set_rule_parity(make_skill_profile(1.2, "v2.4"))
    assert set(B_ALIGN_ADDED) <= set(b._v24)
