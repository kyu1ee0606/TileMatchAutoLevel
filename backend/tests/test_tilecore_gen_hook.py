"""Generator stuck-check hook (TILECORE_GEN) — `_quick_deadlock_check` / `_fix_same_type_blocking`.

Plan PLAN_CSHARP_BATCH_LIVE_20261106 stage 2-A.  Uses the fake serve from test_tilecore_client (no dotnet).
Byte-identical C# vs python on real levels is checked by scripts/tilecore_gen_replay.py, not here.
"""
import copy
import os
import random
import sys

import pytest

from app.core import tilecore_client as tc
from app.core.bot_simulator import BotSimulator
from app.core.generator import LevelGenerator

sys.path.insert(0, os.path.dirname(__file__))
from fake_tilecore_serve import fake_games  # noqa: E402

FAKE = os.path.join(os.path.dirname(__file__), "fake_tilecore_serve.py")
LEVEL = {"layer": 2, "useTileCount": 3, "randSeed": 313612, "max_moves": 30,
         "layer_0": {"col": "4", "row": "4", "tiles": {
             "0_0": ["t1", ""], "1_0": ["t1", ""], "2_0": ["t4", ""],
             "0_1": ["t4", ""], "1_1": ["t7", ""], "2_1": ["t7", ""],
             "0_2": ["t1", ""], "1_2": ["t4", ""], "2_2": ["t7", ""]}},
         "layer_1": {"col": "3", "row": "3", "tiles": {
             "0_0": ["t7", ""], "1_0": ["t4", ""], "2_0": ["t1", ""],
             "0_1": ["t1", ""], "1_1": ["t4", ""], "2_1": ["t7", ""],
             "0_2": ["t4", ""], "1_2": ["t1", ""], "2_2": ["t7", ""]}}}


def _t0_level():
    lv = copy.deepcopy(LEVEL)
    for i in range(2):
        for v in lv[f"layer_{i}"]["tiles"].values():
            v[0] = "t0"
    return lv


@pytest.fixture(autouse=True)
def pinned(monkeypatch, tmp_path):
    """Every BotSimulator() starts from the same RNG state; fake-serve plumbing; clean worker state."""
    orig = BotSimulator.__init__

    def init(self, *a, **k):
        orig(self, *a, **k)
        self._rng.seed(123)
    monkeypatch.setattr(BotSimulator, "__init__", init)
    monkeypatch.setenv("TILECORE_SHADOW_DIR", str(tmp_path))
    monkeypatch.setenv("TILECORE_TIMEOUT_S", "5")
    monkeypatch.delenv("TILECORE_SERVE_SHA", raising=False)
    monkeypatch.delenv("TILECORE_SHADOW_SAMPLE", raising=False)
    monkeypatch.delenv("TILECORE_GEN", raising=False)
    tc.shutdown_all()
    tc.reset_counters()
    yield
    tc.shutdown_all()


def _serve(monkeypatch, *args, mode="on"):
    monkeypatch.setenv("TILECORE_SERVE_CMD", " ".join([sys.executable, "-I", FAKE, *args]))
    monkeypatch.setenv("TILECORE_GEN", mode)
    tc.shutdown_all()
    tc.reset_counters()


def _gen_counters():
    return tc.counters().get("gen", {})


def _quick(max_moves=30):
    return LevelGenerator()._quick_deadlock_check(copy.deepcopy(LEVEL), max_moves=max_moves)


def _fix(lv):
    random.seed(5)          # the "no better seed" branch uses the global random.randint
    return LevelGenerator()._fix_same_type_blocking(lv, [("0_0", "1_0", "t1")])


def _python_reference_quick(max_moves=30):
    """The pre-hook code path, spelled out: BotSimulator().simulate_with_profile(...)."""
    from app.models.bot_profile import get_profile
    sim = BotSimulator()
    res = sim.simulate_with_profile(level_json=copy.deepcopy(LEVEL), profile=get_profile("optimal"),
                                    iterations=5, max_moves=max_moves, seed=None)
    return res


# ───────── off (default) ─────────
def test_off_equals_original_path_and_never_touches_cs(monkeypatch):
    monkeypatch.setenv("TILECORE_SERVE_CMD", "/nonexistent/must-not-run")
    out = _quick()
    ref = _python_reference_quick()
    assert out["clear_rate"] == ref.clear_rate and out["avg_moves"] == ref.avg_moves
    assert out["has_deadlock"] == (ref.clear_rate < 0.3)
    fixed = _fix(_t0_level())
    assert tc.counters() == {} and tc._workers == {}            # C# never touched, no worker created


def test_off_explicit_value_same_as_unset(monkeypatch):
    a = _quick()
    monkeypatch.setenv("TILECORE_GEN", "off")
    assert _quick() == a and tc.counters() == {}


# ───────── on ─────────
def test_on_quick_deadlock_uses_cs_and_advances_rng(monkeypatch):
    _serve(monkeypatch)
    out = _quick()
    exp = fake_games(random.Random(123), 5, False, reseed=None)
    assert out["clear_rate"] == sum(1 for g in exp if g["cleared"]) / 5
    c = _gen_counters()
    assert c["cs_ok"] == 1 and c["fallback"] == 0


def test_on_fix_same_type_blocking_uses_cs(monkeypatch):
    _serve(monkeypatch)
    lv = _t0_level()
    out = _fix(lv)
    c = _gen_counters()
    assert c["cs_ok"] >= 1 and c["fallback"] == 0
    # one BotSimulator reused over candidates: first candidate's fake 3-game clear rate decides the first adoption
    rng = random.Random(123)
    first = fake_games(rng, 3, False, reseed=None)
    if any(g["cleared"] for g in first):
        assert out["randSeed"] == lv["randSeed"] + 137


# ───────── shadow ─────────
def test_shadow_returns_python_result_and_runs_cs(monkeypatch):
    off = _quick()
    _serve(monkeypatch, mode="shadow")
    sh = _quick()
    assert sh == off                                             # shadow answer == python answer
    c = _gen_counters()
    assert c["cs_ok"] == 1 and c["shadow_same"] + c["shadow_mismatch"] == 1     # fake games differ -> mismatch logged
    assert os.path.exists(os.path.join(os.environ["TILECORE_SHADOW_DIR"], "gen_shadow_diff.jsonl"))


# ───────── fallback ─────────
@pytest.mark.parametrize("fault,key", [("--error", "error"), ("--unsupported", "unsupported"),
                                       ("--crash-after 0", "error")])
def test_cs_failure_falls_back_to_identical_python_result(monkeypatch, fault, key):
    off = _quick()
    off_fix = _fix(_t0_level())
    _serve(monkeypatch, *fault.split())
    assert _quick() == off
    assert _fix(_t0_level()) == off_fix                          # whole 50-candidate loop falls back unchanged
    c = _gen_counters()
    assert c[key] >= 1 and c["fallback"] >= 1 and c["cs_ok"] == 0


def test_cs_not_installed_falls_back(monkeypatch):
    off = _quick()
    monkeypatch.setenv("TILECORE_GEN", "on")
    monkeypatch.setenv("TILECORE_SERVE_CMD", "/nonexistent/binary")
    tc.shutdown_all()
    tc.reset_counters()
    assert _quick() == off
    assert _gen_counters()["fallback"] >= 1
