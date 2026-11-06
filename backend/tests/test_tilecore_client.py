"""tilecore_client against the fake serve (no dotnet needed). Plan PLAN_CSHARP_BATCH_LIVE_20261106 §2 1-B."""
import copy
import json
import os
import random
import subprocess
import sys
import threading
import time

import pytest

from app.core import tilecore_client as tc
from app.core.bot_simulator import BotSimulator
from app.models.bot_profile import BotType, get_profile

sys.path.insert(0, os.path.dirname(__file__))
from fake_tilecore_serve import fake_games  # noqa: E402

FAKE = os.path.join(os.path.dirname(__file__), "fake_tilecore_serve.py")
LEVEL = {"layer": 2, "useTileCount": 3, "randSeed": 313612,
         "layer_0": {"col": "4", "row": "4", "tiles": {
             "0_0": ["t1", ""], "1_0": ["t1", ""], "2_0": ["t4", ""],
             "0_1": ["t4", ""], "1_1": ["t7", ""], "2_1": ["t7", ""],
             "0_2": ["t1", ""], "1_2": ["t4", ""], "2_2": ["t7", ""]}},
         "layer_1": {"col": "3", "row": "3", "tiles": {
             "0_0": ["t7", ""], "1_0": ["t4", ""], "2_0": ["t1", ""],
             "0_1": ["t1", ""], "1_1": ["t4", ""], "2_1": ["t7", ""],
             "0_2": ["t4", ""], "1_2": ["t1", ""], "2_2": ["t7", ""]}}}


@pytest.fixture
def profile():
    return get_profile(BotType.AVERAGE)


@pytest.fixture
def serve(monkeypatch, tmp_path):
    """serve(*fake_args) -> sets TILECORE_GEN=on + fake command; fresh worker/counters."""
    monkeypatch.setenv("TILECORE_SHADOW_DIR", str(tmp_path))
    monkeypatch.setenv("TILECORE_TIMEOUT_S", "5")
    monkeypatch.delenv("TILECORE_SERVE_SHA", raising=False)
    monkeypatch.delenv("TILECORE_SHADOW_SAMPLE", raising=False)
    tc.shutdown_all()
    tc.reset_counters()

    def _set(*args, mode="on", path="gen"):
        monkeypatch.setenv("TILECORE_SERVE_CMD", " ".join([sys.executable, "-I", FAKE, *args]))
        monkeypatch.setenv(tc._PATH_ENV[path], mode)
        tc.shutdown_all()
        tc.reset_counters()
    yield _set
    tc.shutdown_all()


def _expected(profile, seed, n=5, et=False, state=None):
    rng = random.Random()
    if state is not None:
        rng.setstate(state)
    games = fake_games(rng, n, et, reseed=seed)
    return tc._build_result(profile, games, tc.resolve_max_moves(LEVEL, None)), rng


def _py(profile, seed, n=5, state=None):
    s = BotSimulator()
    if state is not None:
        s._rng.setstate(state)
    return s.simulate_with_profile(copy.deepcopy(LEVEL), profile, iterations=n, seed=seed), s


# ───────── off ─────────
def test_off_never_spawns_and_matches_python(monkeypatch, profile):
    monkeypatch.delenv("TILECORE_GEN", raising=False)
    monkeypatch.setenv("TILECORE_SERVE_CMD", "/nonexistent/should-not-run")
    tc.shutdown_all()
    tc.reset_counters()
    a = tc.simulate(BotSimulator(), copy.deepcopy(LEVEL), profile, iterations=5, seed=7)
    b, _ = _py(profile, 7)
    assert a == b
    assert tc.counters() == {} and tc._workers == {}      # C# path never touched
    # seed=None: identical RNG consumption/end state as plain python
    s1, s2 = BotSimulator(), BotSimulator()
    st = random.Random(99).getstate()
    s1._rng.setstate(st), s2._rng.setstate(st)
    r1 = tc.simulate(s1, copy.deepcopy(LEVEL), profile, iterations=5)
    r2 = s2.simulate_with_profile(copy.deepcopy(LEVEL), profile, iterations=5)
    assert r1 == r2 and s1._rng.getstate() == s2._rng.getstate()


def test_shared_tilecore_var_not_read(monkeypatch):
    monkeypatch.setenv("TILECORE", "on")
    monkeypatch.delenv("TILECORE_GEN", raising=False)
    assert tc.path_mode("gen") == "off"
    monkeypatch.setenv("TILECORE_GEN", "bogus")
    assert tc.path_mode("gen") == "off"


# ───────── on, normal ─────────
def test_on_seeded(serve, profile):
    serve()
    res = tc.simulate(BotSimulator(), copy.deepcopy(LEVEL), profile, iterations=5, seed=11)
    exp, _ = _expected(profile, 11)
    assert res == exp
    assert tc.counters()["gen"]["cs_ok"] == 1 and tc.counters()["gen"]["fallback"] == 0
    assert tc.get_worker("gen").hello()["engine"].startswith("tilecore/7.")


def test_on_seed_none_state_roundtrip(serve, profile):
    serve()
    sim = BotSimulator()
    sim._rng.seed(12345)
    st0 = sim._rng.getstate()
    res = tc.simulate(sim, copy.deepcopy(LEVEL), profile, iterations=5)
    exp, rng_exp = _expected(profile, None, state=st0)
    assert res == exp
    assert sim._rng.getstate() == rng_exp.getstate()      # end state came back into the python RNG
    # second call continues from returned state (== chain on the expected side)
    res2 = tc.simulate(sim, copy.deepcopy(LEVEL), profile, iterations=3)
    exp2, rng2 = _expected(profile, None, n=3, state=rng_exp.getstate())
    assert res2 == exp2 and sim._rng.getstate() == rng2.getstate()


def test_rng_json_roundtrip():
    r = random.Random(5)
    [r.random() for _ in range(700)]
    st = tc.rng_state_to_json(r)
    r2 = random.Random()
    tc.rng_state_from_json(r2, json.loads(json.dumps(st)))
    assert r2.getstate() == r.getstate()
    r.gauss(0, 1)                                   # gauss_next set (odd call) -> not representable
    assert tc.rng_state_to_json(r) is None
    with pytest.raises(ValueError):
        tc.rng_state_from_json(r2, {"mt": [0] * 10, "index": 1})


def test_early_termination_games_count(serve, profile):
    serve()
    res = tc.simulate(BotSimulator(), copy.deepcopy(LEVEL), profile, iterations=40, seed=3, early_termination=True)
    exp, _ = _expected(profile, 3, n=40, et=True)
    assert res == exp and res.iterations <= 40


# ───────── fallbacks ─────────
def test_unsupported_falls_back(serve, profile):
    serve("--unsupported")
    res = tc.simulate(BotSimulator(), copy.deepcopy(LEVEL), profile, iterations=5, seed=7)
    assert res == _py(profile, 7)[0]
    c = tc.counters()["gen"]
    assert c["unsupported"] == 1 and c["fallback"] == 1 and c["cs_ok"] == 0
    assert tc.get_worker("gen").disabled_reason is None    # unsupported does not disable worker


def test_error_falls_back_seed_none_rng_restored(serve, profile):
    serve("--error")
    s1, s2 = BotSimulator(), BotSimulator()
    st = random.Random(42).getstate()
    s1._rng.setstate(st), s2._rng.setstate(st)
    r1 = tc.simulate(s1, copy.deepcopy(LEVEL), profile, iterations=5)
    r2 = s2.simulate_with_profile(copy.deepcopy(LEVEL), profile, iterations=5)
    assert r1 == r2 and s1._rng.getstate() == s2._rng.getstate()
    assert tc.counters()["gen"]["error"] == 1


def test_version_mismatch_disables(serve, profile):
    for args in (("--engine", "tilecore/6.0.0"), ("--proto", "2"), ("--rules", "xx")):
        serve(*args)
        for _ in range(2):
            res = tc.simulate(BotSimulator(), copy.deepcopy(LEVEL), profile, iterations=5, seed=7)
            assert res == _py(profile, 7)[0]
        w = tc.get_worker("gen")
        assert w.disabled_reason and "version mismatch" in w.disabled_reason
        assert w.starts == 1                                  # not respawned over and over
        assert tc.counters()["gen"]["fallback"] == 2


def test_sha_mismatch(serve, profile, monkeypatch):
    serve()
    monkeypatch.setenv("TILECORE_SERVE_SHA", "other")
    tc.shutdown_all()
    res = tc.simulate(BotSimulator(), copy.deepcopy(LEVEL), profile, iterations=5, seed=7)
    assert res == _py(profile, 7)[0]
    assert "sha" in tc.get_worker("gen").disabled_reason


def test_timeout_kills_and_falls_back(serve, profile, monkeypatch):
    serve("--hang")
    monkeypatch.setenv("TILECORE_TIMEOUT_S", "0.5")
    w = tc.get_worker("gen")
    t0 = time.time()
    res = tc.simulate(BotSimulator(), copy.deepcopy(LEVEL), profile, iterations=5, seed=7)
    assert res == _py(profile, 7)[0] and time.time() - t0 < 4
    assert tc.counters()["gen"]["timeout"] == 1
    assert w._proc is None                                    # killed
    # during backoff next call falls back immediately, no new spawn
    n = w.starts
    tc.simulate(BotSimulator(), copy.deepcopy(LEVEL), profile, iterations=5, seed=7)
    assert w.starts == n


def test_crash_then_restart(serve, profile):
    serve("--crash-after", "1")
    sim = BotSimulator()
    r1 = tc.simulate(sim, copy.deepcopy(LEVEL), profile, iterations=5, seed=7)        # ok
    assert r1 == _expected(profile, 7)[0]
    r2 = tc.simulate(sim, copy.deepcopy(LEVEL), profile, iterations=5, seed=7)        # crashes -> fallback
    assert r2 == _py(profile, 7)[0]
    c = tc.counters()["gen"]
    assert c["cs_ok"] == 1 and c["fallback"] == 1 and c["error"] == 1
    w = tc.get_worker("gen")
    w._retry_at = 0                                           # skip backoff wait
    r3 = tc.simulate(sim, copy.deepcopy(LEVEL), profile, iterations=5, seed=7)        # restarted process works
    assert r3 == _expected(profile, 7)[0] and w.starts == 2


def test_hello_missing_falls_back(serve, profile, monkeypatch):
    serve("--no-hello")
    monkeypatch.setenv("TILECORE_START_TIMEOUT_S", "0.5")
    tc.shutdown_all()
    res = tc.simulate(BotSimulator(), copy.deepcopy(LEVEL), profile, iterations=5, seed=7)
    assert res == _py(profile, 7)[0]


def test_spawn_impossible_falls_back(serve, profile, monkeypatch):
    serve()
    monkeypatch.setenv("TILECORE_SERVE_CMD", "/nonexistent/binary")
    tc.shutdown_all()
    assert tc.simulate(BotSimulator(), copy.deepcopy(LEVEL), profile, iterations=5, seed=7) == _py(profile, 7)[0]


def test_missing_state_seed_none_falls_back(serve, profile):
    serve("--no-state")
    s1, s2 = BotSimulator(), BotSimulator()
    st = random.Random(1).getstate()
    s1._rng.setstate(st), s2._rng.setstate(st)
    assert tc.simulate(s1, copy.deepcopy(LEVEL), profile, iterations=5) == \
        s2.simulate_with_profile(copy.deepcopy(LEVEL), profile, iterations=5)
    assert s1._rng.getstate() == s2._rng.getstate()


def test_honor_zero_seed_pre_reject(serve, profile):
    serve()
    lv = copy.deepcopy(LEVEL)
    lv["randSeed"] = 0
    tc.simulate(BotSimulator(), lv, profile, iterations=3, seed=7, honor_zero_seed=True)
    c = tc.counters()["gen"]
    assert c["unsupported"] == 1 and c["fallback"] == 1 and c["cs_ok"] == 0
    assert tc._workers["gen"].starts == 0 if "gen" in tc._workers else True


# ───────── concurrency: no lost requests ─────────
def test_concurrent_requests_all_answered(serve, profile):
    serve("--delay-ms", "100")
    out = {}

    def run(i):
        out[i] = tc.simulate(BotSimulator(), copy.deepcopy(LEVEL), profile, iterations=5, seed=100 + i)
    ts = [threading.Thread(target=run, args=(i,)) for i in range(12)]
    t0 = time.time()
    [t.start() for t in ts]
    [t.join(20) for t in ts]
    assert len(out) == 12
    for i in range(12):
        assert out[i] == _expected(profile, 100 + i)[0]
    assert tc.counters()["gen"]["cs_ok"] == 12 and time.time() - t0 < 1.0   # overlapped, not serialized (12*0.1s)


def test_crash_fails_all_pending_no_hang(serve, profile):
    serve("--crash-after", "0", "--delay-ms", "50")
    out = {}

    def run(i):
        out[i] = tc.simulate(BotSimulator(), copy.deepcopy(LEVEL), profile, iterations=5, seed=7)
    ts = [threading.Thread(target=run, args=(i,)) for i in range(4)]
    [t.start() for t in ts]
    [t.join(15) for t in ts]
    assert len(out) == 4 and all(v == _py(profile, 7)[0] for v in out.values())


# ───────── shadow ─────────
def test_shadow_returns_python_and_logs(serve, profile, tmp_path):
    serve(mode="shadow")
    res = tc.simulate(BotSimulator(), copy.deepcopy(LEVEL), profile, iterations=5, seed=7)
    assert res == _py(profile, 7)[0]
    rec = [json.loads(l) for l in (tmp_path / "gen_shadow_diff.jsonl").read_text().splitlines()]
    assert len(rec) == 1 and rec[0]["category"] == "mismatch"      # fake games differ from real python
    assert tc.counters()["gen"]["shadow_mismatch"] == 1


def test_shadow_unsupported_logged_not_mismatch(serve, profile, tmp_path):
    serve("--unsupported", mode="shadow")
    tc.simulate(BotSimulator(), copy.deepcopy(LEVEL), profile, iterations=5, seed=7)
    rec = json.loads((tmp_path / "gen_shadow_diff.jsonl").read_text().splitlines()[0])
    assert rec["category"] == "cs_unsupported" and tc.counters()["gen"]["shadow_mismatch"] == 0


def test_on_sample_compare(serve, profile, monkeypatch, tmp_path):
    serve()
    monkeypatch.setenv("TILECORE_SHADOW_SAMPLE", "1")
    tc.simulate(BotSimulator(), copy.deepcopy(LEVEL), profile, iterations=5, seed=7)
    assert tc.counters()["gen"]["shadow_mismatch"] == 1          # fake != python, but sampled and recorded
    assert (tmp_path / "gen_shadow_diff.jsonl").exists()


# ───────── sweep ─────────
def test_sweep_off_equals_original(monkeypatch):
    from app.core import mc_difficulty as mc
    monkeypatch.delenv("TILECORE_SWEEP", raising=False)
    monkeypatch.setenv("TILECORE_SERVE_CMD", "/nonexistent/should-not-run")
    tasks = [{"key": i, "theta": 0.3 + 0.2 * i, "level_json": copy.deepcopy(LEVEL), "rollouts": 4, "seed": 5}
             for i in range(2)]
    assert tc.sweep_points(copy.deepcopy(tasks)) == [mc.sweep_point_task(copy.deepcopy(t)) for t in tasks]


def test_sweep_on_unsupported_uses_python(serve, monkeypatch):
    from app.core import mc_difficulty as mc
    serve("--unsupported", mode="on", path="sweep")
    tasks = [{"key": i, "theta": 0.3 + 0.2 * i, "level_json": copy.deepcopy(LEVEL), "rollouts": 4, "seed": 5}
             for i in range(3)]
    assert tc.sweep_points(copy.deepcopy(tasks)) == [mc.sweep_point_task(copy.deepcopy(t)) for t in tasks]
    assert tc.counters()["sweep"]["unsupported"] == 3


def test_sweep_on_uses_cs(serve):
    serve(mode="on", path="sweep")
    t = {"key": "k", "theta": 0.5, "level_json": copy.deepcopy(LEVEL), "rollouts": 8, "seed": 5}
    r = tc.sweep_points([t])[0]
    from app.core import mc_difficulty as mc
    exp = tc._build_result(mc.make_skill_profile(0.5), fake_games(random.Random(), 8, True, reseed=5),
                           tc.resolve_max_moves(LEVEL, None))
    assert r["error"] is None and r["clear_rate"] == round(exp.clear_rate, 4) and r["iterations"] == exp.iterations
    assert r["avg_tiles_cleared"] == round(exp.avg_tiles_cleared, 2)


# ───────── protocol freeze (SERVE_PROTOCOL.md) details ─────────
def test_deadline_kind_counts_timeout_and_keeps_worker(serve, profile):
    serve("--deadline-err")
    res = tc.simulate(BotSimulator(), copy.deepcopy(LEVEL), profile, iterations=5, seed=7)
    assert res == _py(profile, 7)[0]
    c = tc.counters()["gen"]
    assert c["timeout"] == 1 and c["fallback"] == 1 and tc.get_worker("gen")._proc is not None


def test_rng_index_zero_accepted():
    r = random.Random(1)
    st = tc.rng_state_to_json(r)
    st["index"] = 0
    tc.rng_state_from_json(random.Random(), st)       # CPython accepts index 0 (protocol: 0..624)
    st["index"] = 625
    with pytest.raises(ValueError):
        tc.rng_state_from_json(random.Random(), st)


# ───────── review fixes (Codex cross-review) — each has a hard time cap (join timeouts / alarm) ─────────
def _big_level():
    lv = copy.deepcopy(LEVEL)
    lv["pad"] = "x" * 3_000_000          # >> pipe buffer (64 KB): write blocks when the peer never reads
    return lv


def test_blocked_write_does_not_hang_or_block_others(serve, profile, monkeypatch):
    """#1: peer never reads stdin; big request fills the pipe. Deadline must still fire (kill); 2nd caller not stuck."""
    serve("--no-read")
    monkeypatch.setenv("TILECORE_TIMEOUT_S", "1")
    out, t_done = {}, {}

    def run(i):
        out[i] = tc.simulate(BotSimulator(), _big_level(), profile, iterations=5, seed=7)
        t_done[i] = time.time()
    t0 = time.time()
    ts = [threading.Thread(target=run, args=(i,), daemon=True) for i in range(2)]
    [t.start() for t in ts]
    [t.join(15) for t in ts]
    assert len(out) == 2, "caller stuck on blocked pipe write"
    assert max(t_done.values()) - t0 < 8
    expect = _py(profile, 7)[0]           # 'pad' key is unused by the python sim
    assert all(v == expect for v in out.values())
    assert tc.get_worker("gen")._proc is None and tc.counters()["gen"]["fallback"] == 2


def test_reader_eof_with_live_process_is_reaped(serve, profile, monkeypatch):
    """#2: stdout closed but process alive -> process must be killed/reaped, not leaked or respawned."""
    procs = []
    real = subprocess.Popen

    def rec(*a, **k):
        p = real(*a, **k)
        procs.append(p)
        return p
    monkeypatch.setattr(subprocess, "Popen", rec)
    serve("--close-stdout")
    monkeypatch.setenv("TILECORE_START_TIMEOUT_S", "2")
    try:
        res = tc.simulate(BotSimulator(), copy.deepcopy(LEVEL), profile, iterations=5, seed=7)
        assert res == _py(profile, 7)[0]
        assert procs, "serve was never spawned"
        deadline = time.time() + 5
        while time.time() < deadline and any(p.poll() is None for p in procs):
            time.sleep(0.05)
        assert all(p.poll() is not None for p in procs), "serve process leaked after stdout EOF"
        assert len(procs) == 1
    finally:
        for p in procs:
            if p.poll() is None:
                p.kill()


@pytest.mark.skipif(not hasattr(os, "fork"), reason="needs fork")
def test_fork_child_gets_fresh_shadow_lock(tmp_path, monkeypatch):
    """#3: fork while another thread holds _SLOCK -> child must not deadlock in _shadow_log (alarm = 5 s cap)."""
    import signal
    monkeypatch.setenv("TILECORE_SHADOW_DIR", str(tmp_path))
    tc._SLOCK.acquire()
    held = tc._SLOCK
    pid = os.fork()
    if pid == 0:                              # child: never returns into pytest
        code = 1
        try:
            signal.alarm(5)                   # deadlock -> SIGALRM kills child (status != 0)
            tc._shadow_log("gen", {"child": True})
            code = 0
        finally:
            os._exit(code)
    held.release()
    deadline = time.time() + 15
    status = None
    while time.time() < deadline:
        p, st = os.waitpid(pid, os.WNOHANG)
        if p:
            status = st
            break
        time.sleep(0.05)
    if status is None:
        os.kill(pid, signal.SIGKILL)
        os.waitpid(pid, 0)
    assert status == 0, "forked child deadlocked on _SLOCK"
    assert '"child": true' in (tmp_path / "gen_shadow_diff.jsonl").read_text()
