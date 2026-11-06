"""TILECORE switch for solver.solve_level (plan PLAN_CSHARP_ACCELERATION_20261102 §0-A).

off (default) must not touch the C# path; shadow must return the Python result unchanged and only log.
"""
import copy
import json
import os

import pytest

from app.core import solver, tilecore_shadow

# 9 tiles, 3 types, no t0 -> solvable in 9 moves
TINY = {"layer": 1, "useTileCount": 3, "randSeed": 313612,
        "layer_0": {"col": "3", "row": "3", "num": "9", "tiles": {
            "0_0": ["t1", ""], "1_0": ["t1", ""], "2_0": ["t1", ""],
            "0_1": ["t4", ""], "1_1": ["t4", ""], "2_1": ["t4", ""],
            "0_2": ["t7", ""], "1_2": ["t7", ""], "2_2": ["t7", ""]}}}

# t0 board + randSeed 0 (game = clock-based layout)
SEED0 = {"layer": 1, "useTileCount": 2, "layer_0": {"col": "3", "row": "2", "tiles": {
    "0_0": ["t0", ""], "1_0": ["t0", ""], "2_0": ["t0", ""],
    "0_1": ["t0", ""], "1_1": ["t0", ""], "2_1": ["t0", ""]}}}


@pytest.fixture
def log(tmp_path, monkeypatch):
    p = tmp_path / "shadow.jsonl"
    monkeypatch.setenv("TILECORE_SHADOW_LOG", str(p))
    return p


def _lines(p):
    return [json.loads(l) for l in p.read_text().splitlines()] if p.exists() else []


@pytest.mark.parametrize("val,expect", [(None, "off"), ("", "off"), ("off", "off"), ("OFF", "off"),
                                        ("bogus", "off"), ("shadow", "shadow"), ("on", "shadow")])
def test_mode(monkeypatch, val, expect):
    if val is None:
        monkeypatch.delenv("TILECORE", raising=False)
    else:
        monkeypatch.setenv("TILECORE", val)
    assert tilecore_shadow.mode() == expect


def test_off_never_calls_shadow(monkeypatch, log):
    monkeypatch.delenv("TILECORE", raising=False)

    def boom(*a, **k):
        raise AssertionError("shadow called in off mode")
    monkeypatch.setattr(tilecore_shadow, "shadow_solve", boom)
    r = solver.solve_level(copy.deepcopy(TINY))
    assert r == solver._solve_level_py(copy.deepcopy(TINY), solver.DEFAULT_NODE_BUDGET, solver.DEFAULT_TIME_BUDGET_S)
    assert r["verdict"] == "PROVEN_SOLVABLE"
    assert not log.exists()


def test_shadow_missing_binary_keeps_python_result(monkeypatch, log, tmp_path):
    monkeypatch.setenv("TILECORE", "shadow")
    monkeypatch.setenv("TILECORE_FASTJUDGE_DLL", str(tmp_path / "nope.dll"))
    inp = copy.deepcopy(TINY)
    r = solver.solve_level(inp)
    assert inp == TINY                                   # input not mutated
    assert json.dumps(r, sort_keys=True) == json.dumps(
        solver._solve_level_py(copy.deepcopy(TINY), solver.DEFAULT_NODE_BUDGET, solver.DEFAULT_TIME_BUDGET_S), sort_keys=True)
    (line,) = _lines(log)
    assert line["category"] == "cs_error" and line["cs"]["reason"].startswith("fastjudge_missing")


def test_shadow_internal_error_is_swallowed(monkeypatch, log):
    monkeypatch.setenv("TILECORE", "shadow")

    def boom(*a, **k):
        raise RuntimeError("x")
    monkeypatch.setattr(tilecore_shadow, "fastjudge_solve", boom)
    r = solver.solve_level(copy.deepcopy(TINY))
    assert r["verdict"] == "PROVEN_SOLVABLE"
    assert _lines(log)[0]["category"] == "shadow_internal_error"


@pytest.mark.parametrize("py,cs,reason,cat", [
    ("PROVEN_SOLVABLE", "PATH", "", "same"),
    ("PROVEN_IMPOSSIBLE", "IMPOSSIBLE", "", "same"),
    ("UNCERTAIN", "UNKNOWN", "budget_5.0s", "same"),
    ("UNCERTAIN", "PATH", "", "py_uncertain_cs_decided"),
    ("PROVEN_SOLVABLE", "UNKNOWN", "node_cap_60000", "py_decided_cs_unknown"),
    ("PROVEN_SOLVABLE", "IMPOSSIBLE", "", "contradiction"),
    ("PROVEN_IMPOSSIBLE", "PATH", "", "contradiction"),
    ("PROVEN_SOLVABLE", "UNKNOWN", "unsupported:frog", "cs_unsupported"),
    ("PROVEN_SOLVABLE", "UNKNOWN", "error:Exception: randSeed 0 = time-based", "cs_unsupported_seed0"),
    ("PROVEN_SOLVABLE", "CS_ERROR", "timeout_35s", "cs_error"),
])
def test_classify(py, cs, reason, cat):
    assert tilecore_shadow.classify(py, cs, reason) == cat


def test_row_mapping():
    lj = dict(copy.deepcopy(TINY), xShuffleTile=2, xTypeImbalance=5, unlockTile=1, useTileCount=40)
    row = tilecore_shadow.to_fastjudge_row(lj)
    assert row["shuffleTile"] == 2 and row["typeImbalance"] == 5 and row["unlockTile"] == 1
    assert row["useTileCount"] == 15                      # BotSimulator MAX_USE_TILE_COUNT cap
    assert row["map"]["layer_0"]["tiles"] == TINY["layer_0"]["tiles"] and row["map"]["layer_0"]["col"] == "3"


def test_bs_baked_level_replaces_t0_without_mutation():
    inp = copy.deepcopy(SEED0)
    baked = tilecore_shadow.bs_baked_level(inp)
    assert inp == SEED0
    types = [td[0] for td in baked["layer_0"]["tiles"].values()]
    assert "t0" not in types and len(types) == 6


DLL = os.environ.get("TILECORE_FASTJUDGE_DLL") or tilecore_shadow._DEFAULT_DLL


@pytest.mark.skipif(not os.path.exists(DLL), reason="FastJudge snapshot not present")
def test_shadow_real_fastjudge(monkeypatch, log):
    monkeypatch.setenv("TILECORE", "shadow")
    monkeypatch.delenv("TILECORE_FASTJUDGE_DLL", raising=False)
    r1 = solver.solve_level(copy.deepcopy(TINY))
    r2 = solver.solve_level(copy.deepcopy(SEED0))
    assert r1["verdict"] == "PROVEN_SOLVABLE"
    a, b = _lines(log)
    assert a["category"] == "same" and a["cs"]["verdict"] == "PATH"
    assert b["cs"]["t0_source"] == "bs_baked_seed0"
    assert b["category"] == tilecore_shadow.classify(r2["verdict"], b["cs"]["verdict"], b["cs"].get("reason", ""))
