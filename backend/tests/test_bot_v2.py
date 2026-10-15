"""Bot v2 (skill-monotone move selection, 12_bot_v2.md).

- v1 stays the default and its per-game outcomes are pinned (golden recorded from the pre-v2 code path;
  pre/post byte identity of a wider 20-level snapshot is in bot_v2/regress_*.json).
- v2 is opt-in via BotProfile.bot_version / make_skill_profile(θ, "v2") and fixes the θ valley and the
  θ1.0 early return on the pinned levels.
"""
import json
import os

import pytest

from app.core.mc_difficulty import make_skill_profile, run_skill_sweep
from app.core.pv.evaluate import run_games_task
from app.models.bot_profile import BotType, get_profile

GOLDEN = os.path.join(os.path.dirname(__file__), "golden", "bot_v2", "v1_golden.json")


@pytest.fixture(scope="module")
def golden():
    with open(GOLDEN, encoding="utf-8") as f:
        return json.load(f)


def _rate(level_json, theta, ver, games=60, seed_base=1000):
    r = run_games_task({"key": "k", "theta": theta, "level_json": level_json, "seed_base": seed_base,
                        "start": 0, "count": games, "bot_version": ver})
    return sum(r["wins"]) / games


def test_default_version_is_v1():
    assert make_skill_profile(0.5).bot_version == "v1"
    assert make_skill_profile(0.5, "v2").bot_version == "v2"
    assert get_profile(BotType.EXPERT).bot_version == "v1"


@pytest.mark.parametrize("level", ["55", "123"])
def test_v1_outcomes_unchanged(golden, level):
    lj = golden[level]["level_json"]
    for th, exp in golden[level]["v1_expected"].items():
        r = run_games_task({"key": level, "theta": float(th), "level_json": lj, "seed_base": 1000,
                            "start": 0, "count": 20})
        assert r["wins"] == exp["wins"], (level, th)
        assert r["dockMax"] == exp["dockMax"], (level, th)


def test_v1_explicit_flag_equals_default(golden):
    lj = golden["55"]["level_json"]
    a = run_games_task({"key": "a", "theta": 0.47, "level_json": lj, "seed_base": 7, "start": 0, "count": 10})
    b = run_games_task({"key": "a", "theta": 0.47, "level_json": lj, "seed_base": 7, "start": 0, "count": 10,
                        "bot_version": "v1"})
    assert a["wins"] == b["wins"] and a["dockMax"] == b["dockMax"]


def test_v2_removes_valley(golden):
    # v1 on Lv55: θ0.47 (6/20) far below θ0.29 (18/20). v2 must not dip.
    lj = golden["55"]["level_json"]
    assert _rate(lj, 0.47, "v2") >= _rate(lj, 0.29, "v2")


def test_v2_theta1_is_top(golden):
    for level in ("55", "123"):
        lj = golden[level]["level_json"]
        assert _rate(lj, 1.0, "v2") >= _rate(lj, 0.85, "v2") - 0.05, level


def test_search_tier_only_in_v2():
    assert make_skill_profile(1.2, "v2").search_rollouts == 2
    assert make_skill_profile(1.1, "v2").search_rollouts == 1
    assert make_skill_profile(1.0, "v2").search_rollouts == 0
    assert make_skill_profile(1.2).search_rollouts == 0           # v1 clamps θ to 1.0 as before
    assert make_skill_profile(1.2) == make_skill_profile(1.0)


def test_search_tier_runs(golden):
    lj = golden["123"]["level_json"]
    r = run_games_task({"key": "s", "theta": 1.2, "level_json": lj, "seed_base": 1000, "start": 0, "count": 4,
                        "bot_version": "v2"})
    assert len(r["wins"]) == 4 and sum(r["wins"]) >= 2


def test_sweep_accepts_bot_version(golden):
    lj = golden["55"]["level_json"]
    v1 = run_skill_sweep(lj, skill_grid=[0.47], rollouts_per_point=8)
    v1b = run_skill_sweep(lj, skill_grid=[0.47], rollouts_per_point=8, bot_version="v1")
    assert v1 == v1b
    v2 = run_skill_sweep(lj, skill_grid=[0.47], rollouts_per_point=8, bot_version="v2")
    assert "predicted_clear_rate" in v2


# ── v2.1: bomb / grass awareness (16_bot_v21_gimmick_awareness.md) ──────────────────────────────────
V21_BOMB = os.path.join(os.path.dirname(__file__), "golden", "bot_v2", "v21_bomb_level.json")


def _games(level_json, theta, ver, n=40, seed_base=500):
    return run_games_task({"key": "k", "theta": theta, "level_json": level_json, "seed_base": seed_base,
                           "start": 0, "count": n, "bot_version": ver})


def test_v21_profile_carries_awareness():
    p = make_skill_profile(0.85, "v2.1")
    assert p.bot_version == "v2.1" and p.gimmick_awareness["theta"] == 0.85
    assert make_skill_profile(0.85, "v2").gimmick_awareness is None
    assert make_skill_profile(1.2, "v2.1").search_rollouts == 2


def test_v21_equals_v2_without_bomb_or_grass(golden):
    # Lv55 / Lv123 have neither bomb nor grass: no awareness draw happens, so v2.1 must replay v2 exactly.
    for level in ("55", "123"):
        lj = golden[level]["level_json"]
        for th in (0.29, 0.85):
            a, b = _games(lj, th, "v2", 20), _games(lj, th, "v2.1", 20)
            assert a["wins"] == b["wins"] and a["dockMax"] == b["dockMax"], (level, th)


def test_v21_unaware_bomb_explodes_more():
    # Lv302 (bomb): v2 at θ1.0 handles the countdown perfectly; v2.1 often does not notice it (users fail by Bomb).
    with open(V21_BOMB, encoding="utf-8") as f:
        lj = json.load(f)["level_json"]
    assert sum(_games(lj, 1.0, "v2")["wins"]) > sum(_games(lj, 1.0, "v2.1")["wins"]) + 10
