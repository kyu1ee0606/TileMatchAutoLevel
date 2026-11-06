"""Smoke/parity test against the REAL `tilecore serve` (release v7). Skipped unless TILECORE_REAL=1.

  TILECORE_REAL=1 python -m pytest tests/test_tilecore_client_real.py -s
Optional: TILECORE_REAL_LEVELS (default 40), TILECORE_REAL_DLL (default ~/tilecore/release/v7/bin/tilecore.dll),
          TILECORE_REAL_OUT (summary json, default /tmp/tilecore_client_real.json). serve runs with --threads 2.
Compares tilecore_client.simulate(...) with BotSimulator.simulate_with_profile: result fields (== on the dataclass)
and, for seed=None, the python RNG state after the call. Levels: ~/tilecore/harness/out/{gen,unlock}_levels.json.
"""
import copy
import json
import os
import random
import time

import pytest

from app.core import tilecore_client as tc
from app.core.bot_simulator import BotSimulator
from app.models.bot_profile import BotType, get_profile

DLL = os.path.expanduser(os.environ.get("TILECORE_REAL_DLL", "~/tilecore/release/v7/bin/tilecore.dll"))
HARNESS = os.path.expanduser("~/tilecore/harness/out")
pytestmark = pytest.mark.skipif(os.environ.get("TILECORE_REAL") != "1" or not os.path.exists(DLL),
                                reason="set TILECORE_REAL=1 (and have release/v7) to run against real serve")


def _levels(n):
    out = []
    for f in ("gen_levels.json", "unlock_levels.json"):
        out += list(json.load(open(os.path.join(HARNESS, f))).items())
    return out[:n]


def test_real_serve_parity(monkeypatch):
    n_levels = int(os.environ.get("TILECORE_REAL_LEVELS", "40"))
    levels = _levels(n_levels)
    assert len(levels) >= 30
    monkeypatch.setenv("TILECORE_GEN", "on")
    monkeypatch.setenv("TILECORE_SERVE_DLL", DLL)
    monkeypatch.setenv("TILECORE_SERVE_THREADS_GEN", "2")
    monkeypatch.setenv("TILECORE_TIMEOUT_S", "120")
    monkeypatch.setenv("TILECORE_SHADOW_DIR", "/tmp/tilecore_client_real_shadow")
    monkeypatch.delenv("TILECORE_SERVE_CMD", raising=False)
    monkeypatch.delenv("TILECORE_SHADOW_SAMPLE", raising=False)
    tc.shutdown_all()
    tc.reset_counters()
    opt, avg = get_profile(BotType.OPTIMAL), get_profile(BotType.AVERAGE)

    py_t = cs_t = 0.0
    calls = same = 0
    bad = []
    for li, (name, lj) in enumerate(levels):
        cases = [("gen_state", opt, 5, None, False), ("gen_state", avg, 3, None, False),
                 ("gen", opt, 6, 4242 + li, True)]
        for ci, (kind, prof, iters, seed, et) in enumerate(cases):
            a, b = BotSimulator(), BotSimulator()
            st = random.Random(1000003 * li + ci).getstate()
            a._rng.setstate(st), b._rng.setstate(st)
            t0 = time.perf_counter()
            exp = b.simulate_with_profile(copy.deepcopy(lj), prof, iterations=iters, seed=seed, early_termination=et)
            t1 = time.perf_counter()
            got = tc.simulate(a, copy.deepcopy(lj), prof, iterations=iters, seed=seed, early_termination=et,
                              path="gen")
            t2 = time.perf_counter()
            py_t += t1 - t0
            cs_t += t2 - t1
            calls += 1
            ok = got == exp and (seed is not None or a._rng.getstate() == b._rng.getstate())
            same += ok
            if not ok:
                bad.append((name, kind, got, exp))
    c = tc.counters()["gen"]
    w = tc.get_worker("gen")
    summary = {"levels": len(levels), "calls": calls, "identical": same, "counters": c, "py_s": round(py_t, 2),
               "cs_path_s": round(cs_t, 2), "hello": w.hello()}
    json.dump(summary, open(os.environ.get("TILECORE_REAL_OUT", "/tmp/tilecore_client_real.json"), "w"), indent=1)
    print("\nREAL SERVE SUMMARY", json.dumps({k: v for k, v in summary.items() if k != "hello"}))
    assert w.disabled_reason is None, w.disabled_reason
    assert w.hello()["dll_sha256"].startswith("18a80934")
    assert not bad, bad[:2]
    assert c["error"] == 0 and c["timeout"] == 0
    assert c["cs_ok"] + c["unsupported"] == calls and c["cs_ok"] >= 30
    assert same == calls
