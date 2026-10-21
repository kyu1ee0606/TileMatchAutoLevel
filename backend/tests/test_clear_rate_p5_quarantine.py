"""P5 (doc 42): the 8 active-model bot_cache rows measured under a different bot setting are never used as evidence.

Fixture tests/golden/clear_rate_p5_quarantine.json = live maps + conditions (bot_v21/prep.json) of the 8 quarantined
levels and 4 normal training levels; their cond_hash is checked against the active bot_cache below.
Every bot-run / C-job entry point is patched to raise, so these tests prove 0 automatic measurements.
"""
import copy
import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.core.clear_rate import cond_hash, finalize_game_conditions, load_model
from app.core.clear_rate import guard
from app.main import app

BACKEND = Path(__file__).resolve().parents[1]
FIX = json.loads((BACKEND / "tests/golden/clear_rate_p5_quarantine.json").read_text(encoding="utf-8"))
G237 = json.loads((BACKEND / "tests/golden/clear_rate_L237.json").read_text(encoding="utf-8"))
QUAR = {int(k): v for k, v in FIX["quarantined"].items()}
NORMAL = {int(k): v for k, v in FIX["normal"].items()}
NORMAL[G237["placement_level"]] = G237["level_json"]
CODE = "BOT_CACHE_CONDITION_MISMATCH"
NUM_KEYS = ("expected_ft_any", "range80_ft_any", "expected_unaided_lb", "expected_help_rate", "confidence",
            "reliability")


def _boom(*a, **k):
    raise AssertionError("automatic bot measurement / C job must not be called")


@pytest.fixture(autouse=True)
def no_bot(monkeypatch):
    import app.core.bot_simulator as BS
    import app.core.clear_rate.confirm as CF
    import app.core.clear_rate.measure as M
    monkeypatch.setattr(BS, "BotSimulator", _boom)
    for name in ("measure", "measure_theta", "measure_cached"):
        monkeypatch.setattr(M, name, _boom)
    for name in ("submit", "run_pending", "_run"):
        monkeypatch.setattr(CF.ConfirmJobManager, name, _boom)
    monkeypatch.setattr(CF, "manager", _boom)


@pytest.fixture(scope="module")
def mdl():
    return load_model()


@pytest.fixture(scope="module")
def client():
    return TestClient(app)


def predict(client, lj, L, **kw):
    return client.post("/api/clear-rate/predict", json={"level_json": lj, "placement_level": L, **kw}).json()


def target_eval(client, lj, L, cached=True, **kw):
    body = {"target_mode": "user_expected", "target": 0.9, "level_json": lj, "placement_level": L,
            "use_cached_measurement": cached, **kw}
    return client.post("/api/clear-rate/target-eval", json=body).json()["user_expected"]


def codes(p):
    return [f["code"] for f in p["evidence_flags"]]


def assert_blocked(p):
    assert p["status"] == "insufficient_evidence" and p["in_support"] is False
    assert CODE in p["insufficient_reasons"]
    assert all(p[k] is None for k in NUM_KEYS)
    assert p["bot_unaided_win_rate"] == {}


def test_fixture_hits_the_quarantined_cache_rows(mdl):
    assert mdl.version == guard.QUARANTINE_MODEL
    assert {q[0] for q in guard.QUARANTINED_MEASUREMENTS.values()} == set(QUAR) == {429, 433, 441, 466, 479, 493,
                                                                                    494, 499}
    train = set(mdl.model["support"]["train_levels"])
    for L, lj in QUAR.items():
        h = cond_hash(*finalize_game_conditions(lj, L))
        hit = mdl.bot_cache[h]
        assert guard.QUARANTINED_MEASUREMENTS[h][0] == L == hit["L"] and L not in train
        assert guard.rows_sha256(hit["rows"]) == guard.QUARANTINED_MEASUREMENTS[h][1]
    assert set(NORMAL) <= train


# 1 ── each of the 8: /predict and target-eval(use_cached_measurement) → insufficient evidence, new code, no numbers
@pytest.mark.parametrize("L", sorted(QUAR))
def test_quarantined_cache_blocked_on_both_paths(client, L):
    p = predict(client, QUAR[L], L)
    assert_blocked(p)
    assert p["measurement"]["source"] == "cache"
    detail = next(f["detail"] for f in p["evidence_flags"] if f["code"] == CODE)
    assert "측정 조건 불일치" in detail and "근거 부족" in detail and "출처" not in detail
    a = target_eval(client, QUAR[L], L)
    assert_blocked(a["prediction"])
    assert a["verdict"]["verdict"] == "INSUFFICIENT_EVIDENCE"
    assert a["verdict"]["p_in_band"] is None and a["verdict"]["in_range80_reference"] is None


# 2 ── normal cache rows: responses identical to the guard switched off
@pytest.mark.parametrize("L", sorted(NORMAL))
def test_normal_cache_unchanged(client, monkeypatch, L):
    p1, a1 = predict(client, NORMAL[L], L), target_eval(client, NORMAL[L], L)
    monkeypatch.setattr(guard, "QUARANTINED_MEASUREMENTS", {})
    p0, a0 = predict(client, NORMAL[L], L), target_eval(client, NORMAL[L], L)
    assert json.dumps(p1, sort_keys=True) == json.dumps(p0, sort_keys=True)
    assert json.dumps(a1, sort_keys=True) == json.dumps(a0, sort_keys=True)
    assert CODE not in codes(p1) and p1["measurement"]["source"] == "cache" and p1["bot_unaided_win_rate"]


def test_guard_off_shows_what_was_blocked(client, monkeypatch):
    """Sanity: without the guard the same request used the mismatched rows (the P5 problem)."""
    monkeypatch.setattr(guard, "QUARANTINED_MEASUREMENTS", {})
    assert predict(client, QUAR[429], 429)["expected_ft_any"] is not None


# 3 ── same map at another slot number → same cond_hash → still blocked (keyed by hash, not level number)
@pytest.mark.parametrize("slot", [428, 431, 455])
def test_other_slot_same_map_blocked(client, slot):
    assert cond_hash(*finalize_game_conditions(QUAR[429], slot)) == cond_hash(*finalize_game_conditions(QUAR[429],
                                                                                                         429))
    assert_blocked(predict(client, QUAR[429], slot))
    assert_blocked(target_eval(client, QUAR[429], slot)["prediction"])


# 4 ── no false blocks: changed map with the same number; a new measurement supplied in the request
def changed_map(lj):
    out = copy.deepcopy(lj)
    tiles = out["layer_0"]["tiles"]
    a, b = [k for k, v in tiles.items() if v[1] == ""][:2]
    tiles[a][0], tiles[b][0] = tiles[b][0], tiles[a][0]
    if tiles[a][0] == tiles[b][0]:
        pytest.skip("swap kept the map identical")
    return out


def test_changed_map_same_level_not_blocked(client, mdl):
    lj = changed_map(QUAR[429])
    h = cond_hash(*finalize_game_conditions(lj, 429))
    assert h not in guard.QUARANTINED_MEASUREMENTS and h not in mdl.bot_cache
    p = predict(client, lj, 429)
    assert CODE not in codes(p) and p["status"] == "measurement_required"   # existing "measurement needed"


def test_request_measurement_keeps_g3(client, mdl):
    L, lj = 429, QUAR[429]
    h = cond_hash(*finalize_game_conditions(lj, L))
    bad = mdl.bot_cache[h]
    new_rows = copy.deepcopy(bad["rows"])
    new_rows[0]["wins"] = max(0, new_rows[0]["wins"] - 1)       # a different (new) measurement of the same map
    base = {k: bad[k] for k in ("bot_version", "protocol", "cond_hash")}
    ok = predict(client, lj, L, bot_measurement={**base, "rows": new_rows, "seed_band": "S"})
    assert CODE not in codes(ok) and ok["measurement"]["source"] == "request" and ok["status"] == "ok"
    assert ok["expected_ft_any"] is not None
    no_band = predict(client, lj, L, bot_measurement={**base, "rows": new_rows})   # G3 unchanged
    assert "BOT_SOURCE_UNKNOWN" in no_band["insufficient_reasons"] and CODE not in codes(no_band)
    relabel = predict(client, lj, L, bot_measurement={**base, "rows": bad["rows"], "seed_band": "C"})
    assert_blocked(relabel)                                     # same rows relabelled → still the same measurement
    a = target_eval(client, lj, L, cached=False,
                    bot_measurement_confirm={**base, "rows": new_rows, "seed_band": "C"})
    assert CODE not in codes(a["prediction"]) and a["prediction"]["measurement"]["source"] == "request"
    assert a["verdict"]["bot_seed_confirmed"] is True


def test_key_precision(mdl):
    from app.core.clear_rate.predict import BotMeasurement
    h = next(iter(guard.QUARANTINED_MEASUREMENTS))
    m = BotMeasurement.from_dict(mdl.bot_cache[h], source="cache")
    man = mdl.manifest
    assert guard.quarantined(man, m)
    assert not guard.quarantined({**man, "model_version": "cr-other"}, m)
    assert not guard.quarantined(man, BotMeasurement.from_dict({**mdl.bot_cache[h], "protocol": "theta4x256_v1"}))
    assert not guard.quarantined(man, BotMeasurement.from_dict({**mdl.bot_cache[h], "bot_version": "v2.5"}))


# 5 ── use_cached_measurement=False unchanged: no cache, no measurement, no new code
@pytest.mark.parametrize("L", [429, 499])
def test_cache_off_unchanged(client, L):
    a = target_eval(client, QUAR[L], L, cached=False)
    p = a["prediction"]
    assert p["measurement"] is None and p["status"] == "measurement_required" and CODE not in codes(p)
    assert p["expected_ft_any"] is None and a["verdict"]["verdict"] == "INSUFFICIENT_EVIDENCE"


def test_target_check_has_no_cache_path(client):
    """/verify/target-check takes no map, so it never reads bot_cache — response is unaffected by P5."""
    r = client.post("/api/clear-rate/verify/target-check", json={"items": [{"placement_level": 429, "target": 0.9}]})
    assert r.status_code == 200 and CODE not in r.json()["items"][0]["codes"]
