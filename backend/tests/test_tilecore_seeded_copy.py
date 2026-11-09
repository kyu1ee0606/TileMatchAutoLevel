"""Seeded copy (plan option (a)): randSeed<=0 + t0 levels are sent to C# as a per-call seeded COPY.

Python's own behaviour for such levels is time-seeded (zWellRandom seed==0 -> int(time.time())), so tests freeze time.time.
"""
import copy
import json
import os
import random
import sys
import time

import pytest

from app.core import tilecore_client as tc
from app.core.bot_simulator import BotSimulator
from app.models.bot_profile import BotType, get_profile

sys.path.insert(0, os.path.dirname(__file__))
from test_tilecore_client import LEVEL  # noqa: E402

FAKE = os.path.join(os.path.dirname(__file__), "fake_tilecore_serve.py")
NOW = 1_700_000_000.5
SEED = int(NOW) & 0xFFFFFFFF


@pytest.fixture
def profile():
    return get_profile(BotType.AVERAGE)


@pytest.fixture(autouse=True)
def frozen(monkeypatch, tmp_path):
    monkeypatch.setattr(time, "time", lambda: NOW)
    monkeypatch.setenv("TILECORE_SHADOW_DIR", str(tmp_path))
    monkeypatch.setenv("TILECORE_TIMEOUT_S", "5")
    monkeypatch.delenv("TILECORE_SERVE_SHA", raising=False)
    monkeypatch.delenv("TILECORE_SHADOW_SAMPLE", raising=False)
    monkeypatch.delenv("TILECORE_GEN", raising=False)
    tc.shutdown_all()
    tc.reset_counters()
    yield
    tc.shutdown_all()


def _lvl(kind):
    lv = copy.deepcopy(LEVEL)
    lv["randSeed"] = 0
    t = lv["layer_0"]["tiles"]
    if kind == "top":
        t["0_0"], t["1_0"], t["2_0"] = ["t0", ""], ["t0", ""], ["t0", ""]
    elif kind == "stack":
        t["0_0"] = ["stack_s", None, [3]]
    elif kind == "craft":
        t["0_0"] = ["craft_s", None, [3]]
    return lv


def _fake(monkeypatch, mode, *args):
    monkeypatch.setenv("TILECORE_SERVE_CMD", " ".join([sys.executable, "-I", FAKE, *args]))
    monkeypatch.setenv("TILECORE_GEN", mode)
    tc.shutdown_all()
    tc.reset_counters()


def _python_stub(monkeypatch, captured=None):
    """Replace the C# call by 'python on the level it was given' (so a seeded-copy comparison must come out same)."""
    def stub(path, level, profile, iterations, mm, seed, et, pre_state):
        if captured is not None:
            captured.append(level)
        sim = tc._RecordingSim()
        if pre_state:
            tc.rng_state_from_json(sim._rng, pre_state)
        sim.simulate_with_profile(level, profile, iterations=iterations, max_moves=mm, seed=seed, early_termination=et)
        games = [{"cleared": g[0], "failed": not g[0], "moves": g[1], "combo": g[2], "tiles_cleared": g[3]}
                 for g in sim.rec_games]
        return games, tc.rng_state_to_json(sim._rng)
    monkeypatch.setattr(tc, "_cs_call", stub)


def _off(lv, profile, st, iters=5, seed=None):
    sim = BotSimulator()
    sim._rng.setstate(st)
    r = sim.simulate_with_profile(copy.deepcopy(lv), profile, iterations=iters, seed=seed)
    return r, sim._rng.getstate()


# ───────── detection / injection ─────────
@pytest.mark.parametrize("kind", ["top", "stack", "craft"])
def test_injection_positions_original_untouched(monkeypatch, profile, kind):
    _fake(monkeypatch, "on")
    seen = []
    real = tc._cs_call
    monkeypatch.setattr(tc, "_cs_call", lambda path, level, *a, **k: (seen.append(level), real(path, level, *a, **k))[1])
    lv = _lvl(kind)
    before = copy.deepcopy(lv)
    tc.simulate(BotSimulator(), lv, profile, iterations=5)
    assert lv == before and lv["randSeed"] == 0                     # original never modified
    assert len(seen) == 1 and seen[0] is not lv and seen[0]["randSeed"] == SEED
    assert {k: v for k, v in seen[0].items() if k != "randSeed"} == {k: v for k, v in before.items() if k != "randSeed"}
    c = tc.counters()["gen"]
    assert c["seeded_copy"] == 1 and c["cs_ok"] == 1 and c["fallback"] == 0


def test_missing_randseed_key_counts_as_zero(monkeypatch, profile):
    _fake(monkeypatch, "on")
    lv = _lvl("top")
    del lv["randSeed"]
    tc.simulate(BotSimulator(), lv, profile, iterations=5)
    assert tc.counters()["gen"]["seeded_copy"] == 1 and "randSeed" not in lv


def test_no_copy_when_not_needed(monkeypatch, profile):
    _fake(monkeypatch, "on")
    pos = _lvl("top")
    pos["randSeed"] = 77                                             # positive seed: unchanged behaviour
    no_t0 = _lvl("none")                                             # randSeed 0 but nothing to distribute
    unlock = _lvl("top")
    unlock["xUnlockTile"] = 1                                        # python key-resolve path depends on randSeed==0
    empty_container = _lvl("top")
    empty_container["layer_0"]["tiles"]["0_0"] = ["stack_s", None, []]
    empty_container["layer_0"]["tiles"]["1_0"] = ["t1", ""]
    empty_container["layer_0"]["tiles"]["2_0"] = ["t4", ""]
    for lv in (pos, no_t0, unlock, empty_container):
        assert not tc._needs_seeded_copy(lv)
    tc.simulate(BotSimulator(), pos, profile, iterations=5)
    assert tc.counters()["gen"].get("seeded_copy", 0) == 0


def test_seed_source_consumes_no_rng(monkeypatch, profile):
    """Seed = wall clock only: global random and sim RNG untouched by the seeding itself."""
    st = random.getstate()
    tc._call_seed()
    tc._with_seed(_lvl("top"), 5)
    tc._needs_seeded_copy(_lvl("top"))
    assert random.getstate() == st
    assert tc._call_seed() == SEED
    monkeypatch.setattr(time, "time", lambda: 4294967296.0)         # & 0xFFFFFFFF == 0 -> 1 (0 would mean time seed)
    assert tc._call_seed() == 1


# ───────── modes ─────────
def test_off_untouched(monkeypatch, profile):
    monkeypatch.setenv("TILECORE_SERVE_CMD", "/nonexistent/should-not-run")
    st = random.Random(9).getstate()
    lv = _lvl("top")
    sim = BotSimulator()
    sim._rng.setstate(st)
    r = tc.simulate(sim, lv, profile, iterations=5)
    r0, st0 = _off(lv, profile, st)
    assert r == r0 and sim._rng.getstate() == st0 and tc.counters() == {} and tc._workers == {}


def test_on_uses_seeded_copy_result_and_rng_state(monkeypatch, profile):
    _fake(monkeypatch, "on")
    _python_stub(monkeypatch)
    st = random.Random(3).getstate()
    lv = _lvl("stack")
    sim = BotSimulator()
    sim._rng.setstate(st)
    r = tc.simulate(sim, lv, profile, iterations=5)
    ref, ref_st = _off(tc._with_seed(lv, SEED), profile, st)          # python on the same seeded copy
    assert r == ref and sim._rng.getstate() == ref_st
    assert tc.counters()["gen"]["seeded_copy"] == 1


def test_on_failure_falls_back_with_original_level(monkeypatch, profile):
    _fake(monkeypatch, "on", "--unsupported")
    st = random.Random(4).getstate()
    lv = _lvl("top")
    sim = BotSimulator()
    sim._rng.setstate(st)
    r = tc.simulate(sim, lv, profile, iterations=5)
    r0, st0 = _off(lv, profile, st)                                    # fallback == plain python on ORIGINAL level
    assert r == r0 and sim._rng.getstate() == st0
    c = tc.counters()["gen"]
    assert c["seeded_copy"] == 1 and c["fallback"] == 1 and c["unsupported"] == 1


@pytest.mark.parametrize("seed", [None, 5150])
def test_shadow_service_result_and_rng_identical_to_off(monkeypatch, profile, tmp_path, seed):
    _fake(monkeypatch, "shadow")
    _python_stub(monkeypatch)
    st = random.Random(5).getstate()
    gst = random.getstate()
    lv = _lvl("craft")
    before = copy.deepcopy(lv)
    sim = BotSimulator()
    sim._rng.setstate(st)
    r = tc.simulate(sim, lv, profile, iterations=5, seed=seed)
    r0, st0 = _off(lv, profile, st, seed=seed)
    assert r == r0 and sim._rng.getstate() == st0                      # service result + RNG end = off, original level
    assert lv == before and random.getstate() == gst
    c = tc.counters()["gen"]
    assert c["seeded_copy"] == 1 and c["seeded_same"] == 1 and c["seeded_mismatch"] == 0
    assert c["shadow_same"] == 0 and c["shadow_mismatch"] == 0           # kept apart from the normal columns
    rec = json.loads((tmp_path / "gen_shadow_diff.jsonl").read_text().splitlines()[0])
    assert rec["category"] == "same" and rec["seeded_copy"] is True and "py_ref_s" in rec


def test_shadow_seeded_mismatch_is_counted_separately(monkeypatch, profile, tmp_path):
    _fake(monkeypatch, "shadow")                                       # fake games differ from python -> mismatch
    tc.simulate(BotSimulator(), _lvl("top"), profile, iterations=5)
    c = tc.counters()["gen"]
    assert c["seeded_mismatch"] == 1 and c["shadow_mismatch"] == 0


def test_normal_shadow_unchanged_for_positive_seed(monkeypatch, profile, tmp_path):
    _fake(monkeypatch, "shadow")
    tc.simulate(BotSimulator(), copy.deepcopy(LEVEL), profile, iterations=5, seed=7)
    c = tc.counters()["gen"]
    assert c["shadow_mismatch"] == 1 and c["seeded_copy"] == 0
    rec = json.loads((tmp_path / "gen_shadow_diff.jsonl").read_text().splitlines()[0])
    assert "seeded_copy" not in rec


def test_on_sample_compare_marks_seeded(monkeypatch, profile, tmp_path):
    _fake(monkeypatch, "on")
    _python_stub(monkeypatch)
    monkeypatch.setenv("TILECORE_SHADOW_SAMPLE", "1")
    tc.simulate(BotSimulator(), _lvl("top"), profile, iterations=5)
    c = tc.counters()["gen"]
    assert c["seeded_same"] == 1 and c["shadow_same"] == 0
    rec = json.loads((tmp_path / "gen_shadow_diff.jsonl").read_text().splitlines()[0])
    assert rec["seeded_copy"] is True and rec["sampled_on"] is True


# ───────── detection mirrors bot_simulator (negative seeds, unlock, layer range) ─────────
def test_detection_matches_python_semantics():
    neg = _lvl("top")
    neg["randSeed"] = -5                                   # python: ``rand_seed if rand_seed > 0 else 0`` -> time seed
    assert tc._needs_seeded_copy(neg)
    none_seed = _lvl("top")
    none_seed["randSeed"] = None                           # python itself raises on None > 0 -> not ours
    assert not tc._needs_seeded_copy(none_seed)
    # python: unlock = get("xUnlockTile", get("unlockTile", 0)); xUnlockTile present (even 0) wins over unlockTile
    u1 = _lvl("top"); u1["xUnlockTile"] = 0; u1["unlockTile"] = 2
    u2 = _lvl("top"); u2["unlockTile"] = 2
    u3 = _lvl("top"); u3["xUnlockTile"] = 1
    assert tc._needs_seeded_copy(u1) and not tc._needs_seeded_copy(u2) and not tc._needs_seeded_copy(u3)
    # t0 beyond layer count is never read by python
    far = _lvl("none")
    far["layer_5"] = {"col": "3", "row": "3", "tiles": {"0_0": ["t0", ""]}}
    assert not tc._needs_seeded_copy(far)


def test_python_does_not_mutate_nested_level_objects(profile):
    """Shallow copy is enough: a simulate_with_profile call leaves every nested object of the level unchanged."""
    for kind in ("top", "stack", "craft"):
        lv = _lvl(kind)
        lv["randSeed"] = SEED
        before = copy.deepcopy(lv)
        BotSimulator().simulate_with_profile(lv, profile, iterations=3, seed=None)
        assert lv == before, kind


# ───────── report script: separated populations, required paths ─────────
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
import tilecore_shadow_report as rep  # noqa: E402


def _write(d, path, rows):
    with open(os.path.join(d, f"{path}_shadow_diff.jsonl"), "w") as f:
        for r in rows:
            f.write(json.dumps(dict({"ts": 1.0}, **r)) + "\n")


def _rows(n_normal, n_seeded, seeded_cat="same", normal_cat="same"):
    return ([{"category": normal_cat, "gim": ["ice"]}] * n_normal +
            [{"category": seeded_cat, "seeded_copy": True, "gim": ["t0", "rs0"]}] * n_seeded)


def test_report_never_merges_populations(tmp_path, capsys):
    _write(tmp_path, "gen", _rows(6, 4))
    _write(tmp_path, "sweep", _rows(6, 0))
    rc = rep.main(["--dir", str(tmp_path), "--min-calls", "5", "--min-gimmick", "1", "--json", str(tmp_path / "o.json")])
    out = capsys.readouterr().out
    assert rc == 0
    j = json.load(open(tmp_path / "o.json"))
    g = j["gen"]
    assert g["normal"]["n"] == 6 and g["normal"]["same"] == 6 and g["seeded_copy"]["n"] == 4 and g["seeded_copy"]["same"] == 4
    assert "same" not in {k for k in g if k not in ("normal", "seeded_copy", "gimmicks")}        # no top-level merged same
    assert set(g["gimmicks"]) == {"normal", "seeded_copy"}
    assert "ice" in g["gimmicks"]["normal"] and "ice" not in g["gimmicks"]["seeded_copy"]        # gimmick tables split too
    assert "t0" in g["gimmicks"]["seeded_copy"] and "t0" not in g["gimmicks"]["normal"]
    assert "<normal" in out and "<seeded_copy" in out and "same=10" not in out
    assert j["sweep"]["verdict_seeded_copy"] == "N/A"


def test_report_seeded_mismatch_fails_even_if_normal_ok(tmp_path):
    _write(tmp_path, "gen", _rows(6, 3, seeded_cat="mismatch"))
    _write(tmp_path, "sweep", _rows(6, 0))
    assert rep.main(["--dir", str(tmp_path), "--min-calls", "5"]) == 2


def test_report_seeded_error_rate_is_its_own_condition(tmp_path):
    _write(tmp_path, "gen", _rows(6, 10, seeded_cat="cs_error"))
    _write(tmp_path, "sweep", _rows(6, 0))
    assert rep.main(["--dir", str(tmp_path), "--min-calls", "5", "--json", str(tmp_path / "o.json")]) == 2
    j = json.load(open(tmp_path / "o.json"))
    assert j["gen"]["verdict_normal"] == "PASS" and j["gen"]["verdict_seeded_copy"].startswith("FAIL")


def test_report_missing_path_is_no_data_and_nonzero(tmp_path, capsys):
    _write(tmp_path, "gen", _rows(6, 0))
    assert rep.main(["--dir", str(tmp_path), "--min-calls", "5"]) == 3          # sweep log missing -> not passed
    assert "NO_DATA" in capsys.readouterr().out
    assert rep.main(["--dir", str(tmp_path), "--min-calls", "5", "--paths", "gen"]) == 0
    assert rep.main(["--dir", str(tmp_path / "nope")]) == 3


def test_report_normal_not_comparable_over_5pct_fails(tmp_path):
    _write(tmp_path, "gen", _rows(20, 0) + [{"category": "cs_unsupported", "gim": ["ice"]}] * 2)
    assert rep.main(["--dir", str(tmp_path), "--min-calls", "5", "--paths", "gen"]) == 2
