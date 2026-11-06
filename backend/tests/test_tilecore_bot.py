"""TILECORE bot shadow for /analyze/autoplay (plan PLAN_CSHARP_ACCELERATION_20261102 §0-A, stage ①/②).

off (default) must keep the original code path and bytes; shadow must return the Python result unchanged and only log;
C# failures must never reach the service; C# `unsupported` rows are counted separately (not as mismatches).
"""
import copy
import dataclasses
import json
import os
import stat
import time

import pytest

from app.api.routes import analyze, generate
from app.core import tilecore_bot
from app.core.analyzer import LevelAnalyzer
from app.core.bot_simulator import BotSimulator
from app.models.bot_profile import get_profile
from app.models.schemas import AutoPlayRequest

HAS_CS = os.path.exists(tilecore_bot._DEFAULT_DLL)
needs_cs = pytest.mark.skipif(not HAS_CS, reason="tilecore release dll not present")

# 2 layers, 18 tiles, 3 types, explicit types (no t0) + fixed randSeed
SMALL = {"layer": 2, "useTileCount": 3, "randSeed": 313612,
         "layer_0": {"col": "4", "row": "4", "tiles": {
             "0_0": ["t1", ""], "1_0": ["t1", ""], "2_0": ["t4", ""],
             "0_1": ["t4", ""], "1_1": ["t7", ""], "2_1": ["t7", ""],
             "0_2": ["t1", ""], "1_2": ["t4", ""], "2_2": ["t7", ""]}},
         "layer_1": {"col": "3", "row": "3", "tiles": {
             "0_0": ["t7", ""], "1_0": ["t4", ""], "2_0": ["t1", ""],
             "0_1": ["t1", ""], "1_1": ["t4", ""], "2_1": ["t7", ""],
             "0_2": ["t4", ""], "1_2": ["t1", ""], "2_2": ["t7", ""]}}}

# t0 board + randSeed 0 -> C# refuses (python seeds the distributor from the clock) = unsupported
SEED0 = {"layer": 1, "useTileCount": 2, "layer_0": {"col": "3", "row": "2", "tiles": {
    "0_0": ["t0", ""], "1_0": ["t0", ""], "2_0": ["t0", ""],
    "0_1": ["t0", ""], "1_1": ["t0", ""], "2_1": ["t0", ""]}}}


class _InlinePool:
    """Stand-in for the autoplay ProcessPool (same pickled-copy semantics, no extra processes)."""
    def map(self, fn, tasks):
        return [fn(copy.deepcopy(t)) for t in tasks]


@pytest.fixture
def log(tmp_path, monkeypatch):
    p = tmp_path / "bot_shadow.jsonl"
    monkeypatch.setenv("TILECORE_BOT_SHADOW_LOG", str(p))
    monkeypatch.delenv("TILECORE", raising=False)
    monkeypatch.delenv("TILECORE_BOT", raising=False)
    monkeypatch.setenv("TILECORE_BOT_SYNC", "1")
    monkeypatch.setattr(generate, "_get_autoplay_pool", lambda: _InlinePool())
    return p


def _lines(p):
    return [json.loads(l) for l in p.read_text().splitlines()] if p.exists() else []


def _autoplay(level, seed, profiles=("average", "optimal"), iterations=10):
    req = AutoPlayRequest(level_json=copy.deepcopy(level), iterations=iterations, bot_profiles=list(profiles), seed=seed)
    d = analyze.analyze_autoplay(req, analyzer=LevelAnalyzer()).model_dump()
    d.pop("execution_time_ms")
    return d


# ───────────── switch ─────────────

@pytest.mark.parametrize("tc,tcb,expect", [
    (None, None, "off"), ("", None, "off"), ("off", None, "off"), ("bogus", None, "off"),
    ("shadow", None, "shadow"), ("on", None, "shadow"), ("SHADOW", None, "shadow"),
    ("shadow", "off", "off"), (None, "shadow", "shadow"), ("off", "on", "shadow"), ("shadow", "", "shadow")])
def test_mode(monkeypatch, tc, tcb, expect):
    for k, v in (("TILECORE", tc), ("TILECORE_BOT", tcb)):
        if v is None:
            monkeypatch.delenv(k, raising=False)
        else:
            monkeypatch.setenv(k, v)
    assert tilecore_bot.mode() == expect


# ───────────── off = original bytes ─────────────

def _reference_chunk(args):
    """Body of analyze._run_bot_sim_chunk before the TILECORE hook (verbatim)."""
    profile_name, level_json, iterations, max_moves, seed, early_term = args
    simulator = BotSimulator()
    profile = get_profile(profile_name)
    result = simulator.simulate_with_profile(level_json=level_json, profile=profile, iterations=iterations,
                                             max_moves=max_moves, seed=seed, early_termination=early_term)
    n = result.iterations
    return {"profile": profile_name, "n": n, "cleared": round(result.clear_rate * n),
            "sum_moves": result.avg_moves * n, "sum_combo": result.avg_combo * n,
            "min_moves": result.min_moves, "max_moves": result.max_moves, "mean_moves": result.avg_moves,
            "m2_moves": (result.std_moves ** 2) * (n - 1) if n > 1 else 0.0}


@pytest.mark.parametrize("profile,seed,et", [("average", 11, True), ("optimal", 5, False), ("novice", 99, True)])
def test_off_chunk_bytes_identical(log, monkeypatch, profile, seed, et):
    monkeypatch.setattr(tilecore_bot, "submit", lambda *a, **k: (_ for _ in ()).throw(AssertionError("submit in off")))
    args = (profile, copy.deepcopy(SMALL), 12, 60, seed, et)
    got = analyze._run_bot_sim_chunk(copy.deepcopy(args))
    ref = _reference_chunk(copy.deepcopy(args))
    assert json.dumps(got, sort_keys=False) == json.dumps(ref, sort_keys=False)
    assert "tc_shadow" not in got


def test_off_autoplay_no_log_and_no_cs(log, monkeypatch):
    called = []
    monkeypatch.setattr(tilecore_bot, "run_cs_jobs", lambda *a, **k: called.append(1))
    monkeypatch.setattr(tilecore_bot, "run_python_recorded", lambda *a, **k: called.append(2))
    _autoplay(SMALL, seed=7)
    assert called == [] and not log.exists()


# ───────────── shadow = python result unchanged ─────────────

@pytest.mark.parametrize("profile,et", [("average", True), ("expert", False), ("optimal", True)])
def test_recording_simulator_same_result(profile, et):
    p = get_profile(profile)
    a = BotSimulator().simulate_with_profile(copy.deepcopy(SMALL), p, iterations=15, max_moves=60, seed=3,
                                             early_termination=et)
    b, rec = tilecore_bot.run_python_recorded(copy.deepcopy(SMALL), p, 15, 60, 3, early_termination=et)
    assert dataclasses.asdict(a) == dataclasses.asdict(b)
    assert len(rec["cleared"]) == b.iterations == rec["n"]
    assert rec["cleared"].count("1") == round(b.clear_rate * b.iterations)


def test_shadow_response_identical_to_off_even_when_cs_missing(log, monkeypatch, tmp_path):
    off = _autoplay(SMALL, seed=21)
    monkeypatch.setenv("TILECORE", "shadow")
    monkeypatch.setenv("TILECORE_BOT_DLL", str(tmp_path / "nope.dll"))
    sh = _autoplay(SMALL, seed=21)
    assert json.dumps(off, sort_keys=True) == json.dumps(sh, sort_keys=True)
    ls = _lines(log)
    assert [l["category"] for l in ls] == ["cs_error", "cs_error"]
    assert ls[0]["cs"]["error"].startswith("tilecore_missing:")


@needs_cs
def test_shadow_log_format_same(log, monkeypatch):
    off = _autoplay(SMALL, seed=4242)
    monkeypatch.setenv("TILECORE", "shadow")
    sh = _autoplay(SMALL, seed=4242)
    assert json.dumps(off, sort_keys=True) == json.dumps(sh, sort_keys=True)
    ls = _lines(log)
    assert len(ls) == 2
    for l in ls:
        for k in ("ts", "kind", "input_hash", "profile", "bot_type", "seed", "n", "max_moves", "py", "cs",
                  "category", "unsupported_reason", "cs_bin"):
            assert k in l, k
        for side in ("py", "cs"):
            for k in ("any_clear", "first_clear_rng", "clears", "clear_rate", "cleared", "sec"):
                assert k in l[side], (side, k)
        assert l["kind"] == "autoplay" and l["seed"] == 4242 and len(l["input_hash"]) == 16
        assert l["category"] == "same", l
        assert l["py"]["cleared"] == l["cs"]["cleared"] and len(l["py"]["cleared"]) == l["n"]
        if l["py"]["any_clear"]:
            assert l["py"]["first_clear_rng"] == 4242 + l["py"]["cleared"].index("1")
    stats = {s["profile"]: s for s in sh["bot_stats"]}
    for l in ls:
        name = {"Average Bot": "average", "Optimal Bot": "optimal"}.get(l["profile"], l["profile"])
        if name in stats:
            assert abs(stats[name]["clear_rate"] - l["py"]["clear_rate"]) < 1e-6


# ───────────── unsupported / skip / summary ─────────────

@needs_cs
def test_unsupported_counted_separately(log, monkeypatch):
    monkeypatch.setenv("TILECORE", "shadow")
    _autoplay(SEED0, seed=1)                       # randSeed 0 + t0 -> C# unsupported
    p = dataclasses.replace(get_profile("optimal"), pattern_recognition=1.0)   # PR>=1.0 -> unsupported
    _, rec = tilecore_bot.run_python_recorded(copy.deepcopy(SMALL), p, 10, 60, 8)
    tilecore_bot.submit(SMALL, 60, [rec])
    ls = _lines(log)
    cats = [l["category"] for l in ls]
    assert cats == ["cs_unsupported"] * 3, cats
    assert "randSeed" in ls[0]["unsupported_reason"]
    assert "pattern_recognition" in ls[2]["unsupported_reason"]
    s = tilecore_bot.summarize(str(log))
    assert s["categories"] == {"cs_unsupported": 3} and "mismatch" not in s["categories"]


def test_seed_none_is_skipped_not_compared(log, monkeypatch):
    monkeypatch.setenv("TILECORE", "shadow")
    monkeypatch.setattr(tilecore_bot, "run_cs_jobs", lambda *a, **k: (_ for _ in ()).throw(AssertionError("cs ran")))
    _autoplay(SMALL, seed=None)
    assert [l["category"] for l in _lines(log)] == ["skip_seed_none", "skip_seed_none"]


def test_mismatch_classification():
    rec = {"profile": {"name": "x", "bot_type": "average"}, "seed": 100, "n": 4, "cleared": "0110", "py_sec": 0.1}
    rows = [{"id": "r0", "game": i, "cleared": c == "1", "ms": 1.0} for i, c in enumerate("0100")]
    l = tilecore_bot.compare_record(SMALL, 60, rec, rows, None, 0.2, "autoplay", "h")
    assert l["category"] == "mismatch" and l["first_diff_game"] == 2 and l["diff_games"] == 1
    assert l["py"]["first_clear_rng"] == 101 and l["cs"]["first_clear_rng"] == 101
    assert l["py"]["clear_rate"] == 0.5 and l["cs"]["clear_rate"] == 0.25


# ───────────── error isolation ─────────────

def _fake_dotnet(tmp_path, body):
    f = tmp_path / "fake_dotnet.sh"
    f.write_text("#!/bin/sh\n" + body + "\n")
    f.chmod(f.stat().st_mode | stat.S_IEXEC)
    return str(f)


@pytest.mark.parametrize("body,prefix", [("sleep 5", "timeout_"), ("echo boom >&2; exit 3", "exit_3")])
def test_cs_crash_or_timeout_isolated(log, monkeypatch, tmp_path, body, prefix):
    off = _autoplay(SMALL, seed=9)
    dll = tmp_path / "fake.dll"
    dll.write_text("")
    monkeypatch.setenv("TILECORE", "shadow")
    monkeypatch.setenv("TILECORE_BOT_DLL", str(dll))
    monkeypatch.setenv("TILECORE_DOTNET", _fake_dotnet(tmp_path, body))
    monkeypatch.setenv("TILECORE_BOT_TIMEOUT_S", "1")
    sh = _autoplay(SMALL, seed=9)
    assert json.dumps(off, sort_keys=True) == json.dumps(sh, sort_keys=True)
    ls = _lines(log)
    assert {l["category"] for l in ls} == {"cs_error"} and all(l["cs"]["error"].startswith(prefix) for l in ls)


def test_spawn_error_and_internal_error_isolated(log, monkeypatch, tmp_path):
    dll = tmp_path / "fake.dll"
    dll.write_text("")
    monkeypatch.setenv("TILECORE_BOT_DLL", str(dll))
    monkeypatch.setenv("TILECORE_DOTNET", str(tmp_path / "no_such_dotnet"))
    rec = {"profile": {"name": "x"}, "seed": 1, "n": 2, "cleared": "11", "py_sec": 0.0}
    out = tilecore_bot.process_request(SMALL, 60, [rec])
    assert out[0]["category"] == "cs_error" and out[0]["cs"]["error"].startswith("spawn:")
    monkeypatch.setattr(tilecore_bot, "level_hash", lambda *_: 1 / 0)
    assert tilecore_bot.process_request(SMALL, 60, [rec]) == []          # swallowed
    assert _lines(log)[-1]["category"] == "shadow_internal_error"
    monkeypatch.setattr(tilecore_bot, "process_request", lambda *a, **k: 1 / 0)
    tilecore_bot.submit(SMALL, 60, [rec])                                # sync path: swallowed too


def test_background_queue_does_not_block(log, monkeypatch, tmp_path):
    monkeypatch.delenv("TILECORE_BOT_SYNC", raising=False)
    dll = tmp_path / "fake.dll"
    dll.write_text("")
    monkeypatch.setenv("TILECORE_BOT_DLL", str(dll))
    monkeypatch.setenv("TILECORE_DOTNET", _fake_dotnet(tmp_path, "sleep 1; exit 1"))
    rec = {"profile": {"name": "x"}, "seed": 1, "n": 2, "cleared": "11", "py_sec": 0.0}
    t0 = time.perf_counter()
    tilecore_bot.submit(SMALL, 60, [rec])
    assert time.perf_counter() - t0 < 0.3
    assert tilecore_bot.drain(10)
    assert [l["category"] for l in _lines(log)] == ["cs_error"]


def test_queue_full_drops_with_line(log, monkeypatch):
    import queue as _q
    monkeypatch.delenv("TILECORE_BOT_SYNC", raising=False)
    full = _q.Queue(maxsize=1)
    full.put(None)
    monkeypatch.setattr(tilecore_bot, "_get_queue", lambda: full)
    rec = {"profile": {"name": "x"}, "seed": 1, "n": 2, "cleared": "11", "py_sec": 0.0}
    tilecore_bot.submit(SMALL, 60, [rec])
    assert [l["category"] for l in _lines(log)] == ["dropped_queue_full"]
