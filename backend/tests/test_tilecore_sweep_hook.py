"""rl_sim._parallel_point_sweep hook (plan 2-B): off == original bytes & C# untouched; on/shadow/fallback via fake serve."""
import copy
import json
import os
import random
import sys

import pytest

from app.api.routes import rl_sim
from app.core import mc_difficulty as mc
from app.core import tilecore_client as tc

sys.path.insert(0, os.path.dirname(__file__))
from fake_tilecore_serve import fake_games  # noqa: E402
from test_tilecore_client import LEVEL  # noqa: E402

FAKE = os.path.join(os.path.dirname(__file__), "fake_tilecore_serve.py")


class _Pool:
    """Inline stand-in for the ProcessPool; counts map() calls and the tasks they got."""
    def __init__(self):
        self.calls = []

    def map(self, fn, tasks, chunksize=1):
        tasks = list(tasks)
        self.calls.append((fn.__name__, len(tasks)))
        return [fn(copy.deepcopy(t)) for t in tasks]


@pytest.fixture
def env(monkeypatch, tmp_path):
    pool = _Pool()
    monkeypatch.setattr(rl_sim, "_get_pool", lambda: pool)
    monkeypatch.setenv("TILECORE_SHADOW_DIR", str(tmp_path))
    monkeypatch.setenv("TILECORE_TIMEOUT_S", "5")
    monkeypatch.delenv("TILECORE_SWEEP", raising=False)
    monkeypatch.delenv("TILECORE_SERVE_SHA", raising=False)
    tc.shutdown_all()
    tc.reset_counters()

    def serve(*args, mode="on"):
        monkeypatch.setenv("TILECORE_SERVE_CMD", " ".join([sys.executable, "-I", FAKE, *args]))
        monkeypatch.setenv("TILECORE_SWEEP", mode)
        tc.shutdown_all()
        tc.reset_counters()
    yield pool, serve
    tc.shutdown_all()


ITEMS = [("a", LEVEL), ("b", LEVEL)]
GRID = [0.2, 0.5, 0.8]


def _run():
    return rl_sim._parallel_point_sweep(copy.deepcopy(ITEMS), GRID, 8, 4242)


def _original(monkeypatch):
    """Reference = the pre-change line `list(pool.map(sweep_point_task, tasks, chunksize=1))`."""
    monkeypatch.setattr(tc, "run_sweep", lambda pool, tasks, path="sweep": list(pool.map(mc.sweep_point_task, tasks,
                                                                                         chunksize=1)))
    return _run()


def test_off_bytes_identical_and_cs_untouched(env, monkeypatch):
    pool, _ = env
    monkeypatch.setenv("TILECORE_SERVE_CMD", "/nonexistent/should-not-run")
    got = _run()
    assert pool.calls == [("sweep_point_task", 6)]
    assert tc._workers == {} and tc.counters() == {}
    ref = _original(monkeypatch)
    assert json.dumps(got, sort_keys=True) == json.dumps(ref, sort_keys=True)


def test_recorded_task_matches_original_point():
    t = {"key": "k", "theta": 0.5, "level_json": copy.deepcopy(LEVEL), "rollouts": 16, "seed": 5}
    rec = tc.sweep_point_task_recorded(copy.deepcopy(t))
    assert rec["point"] == mc.sweep_point_task(copy.deepcopy(t))
    assert len(rec["games"]) == rec["point"]["iterations"] and all(len(g) == 4 for g in rec["games"])


def test_on_uses_cs_values(env):
    pool, serve = env
    serve()
    got = _run()
    assert pool.calls == []                                   # nothing needed python
    c = tc.counters()["sweep"]
    assert c["cs_ok"] == 6 and c["fallback"] == 0
    exp = tc._build_result(mc.make_skill_profile(0.5), fake_games(random.Random(), 8, True, reseed=4242 + 1000),
                           tc.resolve_max_moves(LEVEL, None))
    p = next(x for x in got["a"]["skill_curve"] if x["theta"] == 0.5)
    assert p["clear_rate"] == round(exp.clear_rate, 4) and p["iterations"] == exp.iterations
    assert p["avg_tiles_cleared"] == round(exp.avg_tiles_cleared, 2)
    assert p["avg_moves"] == round(exp.avg_moves, 2)


def test_on_unsupported_falls_back_to_pool_same_as_original(env, monkeypatch):
    pool, serve = env
    serve("--unsupported")
    got = _run()
    assert pool.calls == [("sweep_point_task", 6)]            # all 6 points redone by python via the pool
    c = tc.counters()["sweep"]
    assert c["unsupported"] == 6 and c["fallback"] == 6
    assert json.dumps(got, sort_keys=True) == json.dumps(_original(monkeypatch), sort_keys=True)


def test_on_crash_midway_falls_back(env, monkeypatch):
    pool, serve = env
    serve("--crash-after", "2")
    got = _run()
    c = tc.counters()["sweep"]
    assert c["cs_ok"] + c["fallback"] == 6 and c["fallback"] >= 1
    assert sum(n for _, n in pool.calls) == c["fallback"]
    # points that fell back equal the python original (cs points differ: fake games)
    assert set(got) == {"a", "b"} and all(got[k]["error"] is None for k in got)


def test_on_version_mismatch_all_python(env, monkeypatch):
    pool, serve = env
    serve("--engine", "tilecore/6.0.0")
    got = _run()
    assert tc.get_worker("sweep").disabled_reason and tc.counters()["sweep"]["fallback"] == 6
    assert json.dumps(got, sort_keys=True) == json.dumps(_original(monkeypatch), sort_keys=True)


def test_non_v1_goes_straight_to_python(env):
    pool, serve = env
    serve()
    t = {"key": "k", "theta": 0.5, "level_json": copy.deepcopy(LEVEL), "rollouts": 8, "seed": 5, "bot_version": "v2"}
    out = tc.run_sweep(pool, [t])
    assert out == [mc.sweep_point_task(copy.deepcopy(t))] and tc.counters()["sweep"]["unsupported"] == 1


def test_shadow_returns_python_and_logs(env, monkeypatch, tmp_path):
    pool, serve = env
    serve(mode="shadow")
    got = _run()
    assert pool.calls == [("sweep_point_task_recorded", 6)]
    monkeypatch.setenv("TILECORE_SWEEP", "off")
    assert json.dumps(got, sort_keys=True) == json.dumps(_run(), sort_keys=True)     # python values unchanged
    rows = [json.loads(l) for l in (tmp_path / "sweep_shadow_diff.jsonl").read_text().splitlines()]
    assert len(rows) == 6 and {r["category"] for r in rows} == {"mismatch"}          # fake games != python
    assert tc.counters()["sweep"]["shadow_mismatch"] == 6


def test_shadow_cs_failure_never_raises(env, tmp_path):
    pool, serve = env
    serve("--error", mode="shadow")
    _run()
    rows = [json.loads(l) for l in (tmp_path / "sweep_shadow_diff.jsonl").read_text().splitlines()]
    assert {r["category"] for r in rows} == {"cs_error"}
