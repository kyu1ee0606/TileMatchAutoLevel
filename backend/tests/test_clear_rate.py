"""Real-user clear-rate prediction (app/core/clear_rate, /api/clear-rate/predict) — docs 31 / 33."""
import copy
import hashlib
import json
import os
import subprocess
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.core.clear_rate import (BotMeasurement, cond_hash, finalize_game_conditions, judge, load_model,
                                 predict_editor_level, predict_level)
from app.core.clear_rate import guard
from app.core.clear_rate.features import FEATS, expit
from app.core.clear_rate.judge import p_in_band, target_band
from app.core.clear_rate.model import MODELS_DIR, gbm_predict, ridge_predict
from app.core.clear_rate.predict import ClearRatePrediction
from app.core.clear_rate.service import random_layout
from app.main import app

BACKEND = Path(__file__).resolve().parents[1]
FIX = json.loads((BACKEND / "tests/golden/clear_rate_L237.json").read_text(encoding="utf-8"))
LJ, L = FIX["level_json"], FIX["placement_level"]


@pytest.fixture(scope="module")
def mdl():
    return load_model()


@pytest.fixture(scope="module")
def client():
    return TestClient(app)


def codes(fl):
    return [f["code"] for f in fl]


def cached_measurement(mdl):
    gm, cond = finalize_game_conditions(LJ, L)
    return copy.deepcopy(mdl.bot_cache[cond_hash(gm, cond)])


# ── artifact ─────────────────────────────────────────────────────────────────────────────────────
def test_manifest_provenance(mdl):
    m = mdl.manifest
    assert m["bot_version"] == "v2.4" and m["bot_protocol"] == "theta4x128_v1"
    assert m["target_metric"] == "ft_any_v1"
    assert m["train_data"]["shard_commit"] == "b741f6a3" and m["train_data"]["n_levels"] == 379
    assert m["trained_at"] and m["gates"]["pass"]
    assert m["condition_fields"][:7] == ["useTileCount", "unlockTile", "autoCollectCount", "randSeed", "shuffleTile",
                                         "typeImbalance", "timea"]
    raw = (mdl.dir / "model.json").read_text(encoding="utf-8")
    assert hashlib.sha256(raw.encode()).hexdigest() == m["model_json_sha256"]
    assert mdl.model["features"] == FEATS


def test_no_post_release_inputs():
    """Inputs are map / position / bot only — no AF value of the level itself (help rate, clear rate)."""
    assert not [c for c in FEATS if any(k in c.lower() for k in ("help", "af_", "clear", "lb", "ub", "mid"))]


def test_pure_python_matches_training_numpy(mdl):
    H = mdl.model["heads"]
    for c in mdl.model["check"]:
        f = dict(zip(FEATS, c["x"]))
        for head, k in (("ft_any", "ft_logit"), ("unaided_lb", "lb_logit"), ("help_rate", "help_logit")):
            assert abs(mdl.predict_logit(head, f) - c[k]) < 1e-9
        a, b = gbm_predict(H["ft_any"]["q_lo"], c["x"]), gbm_predict(H["ft_any"]["q_hi"], c["x"])
        assert abs(min(a, b) - c["q_lo"]) < 1e-9 and abs(max(a, b) - c["q_hi"]) < 1e-9
        pt = H["ft_any"]["point"]
        assert abs(0.5 * (ridge_predict(pt["ridge"], c["x"]) + gbm_predict(pt["gbm"], c["x"])) - c["ft_logit"]) < 1e-9


# ── prediction path ──────────────────────────────────────────────────────────────────────────────
def test_editor_path_matches_training(mdl):
    r = predict_editor_level(LJ, L)
    assert r.status == "ok" and r.in_support and r.insufficient_reasons == []
    assert r.measurement["source"] == "cache" and r.measurement["cond_hash"] == r.cond_hash
    chk = next(c for c in mdl.model["check"] if c["L"] == L)
    assert abs(r.expected_ft_any - round(expit(chk["ft_logit"]), 4)) < 1e-9
    lo, hi = r.range80_ft_any
    assert 0 <= lo <= r.expected_ft_any <= hi <= 1
    assert 0 < r.expected_unaided_lb < r.expected_ft_any and 0 < r.expected_help_rate < 1
    assert set(r.bot_unaided_win_rate) == {"theta055", "theta065", "theta085", "theta100"}


def test_pure_function_equals_editor_path(mdl):
    gm, cond = finalize_game_conditions(LJ, L)
    meas = BotMeasurement.from_dict(cached_measurement(mdl), source="cache")
    a = predict_level(mdl, gm, cond, L, meas, random_layout=random_layout(gm))
    assert a == predict_editor_level(LJ, L)


def test_deterministic():
    assert predict_editor_level(copy.deepcopy(LJ), L) == predict_editor_level(copy.deepcopy(LJ), L)


def test_upload_auto_collect_rule_changes_conditions():
    _, c237 = finalize_game_conditions(LJ, 237)
    _, c240 = finalize_game_conditions(LJ, 240)
    assert c237["autoCollectCount"] == 0 and c240["autoCollectCount"] == 3


def test_placement_missing_gives_reason_not_number():
    r = predict_editor_level(LJ, None)
    assert r.status == "insufficient_evidence" and r.expected_ft_any is None and not r.in_support
    assert "PLACEMENT_MISSING" in r.insufficient_reasons


def test_level_out_of_range():
    r = predict_editor_level(LJ, 600)
    assert r.status == "insufficient_evidence" and r.expected_ft_any is None
    assert "LEVEL_OUT_OF_RANGE" in r.insufficient_reasons


@pytest.mark.parametrize("field,value", [("randSeed", 1), ("useTileCount", 11), ("shuffleTile", 1)])
def test_changed_game_condition_needs_measurement(field, value):
    lj = dict(copy.deepcopy(LJ), **{field: value})
    if field == "useTileCount":  # upload re-derives useTileCount from the tiles → change the tiles instead
        lj = copy.deepcopy(LJ)
        first = next(iter(lj["layer_0"]["tiles"]))
        lj["layer_0"]["tiles"][first] = ["t15", ""]
    r = predict_editor_level(lj, L)
    assert r.status == "measurement_required" and r.expected_ft_any is None
    assert r.insufficient_reasons == ["MEASUREMENT_MISSING"]


def test_g1_cat_help_level_is_insufficient(mdl):
    """G1: every 10th slot gets autoCollectCount=3 on upload; the training set has 0 such levels → no number."""
    assert mdl.model["support"]["condition_train_levels"]["cat_help"] == 0
    r = predict_editor_level(LJ, 240)
    assert r.status == "insufficient_evidence" and r.expected_ft_any is None and not r.in_support
    assert "CAT_HELP_UNSUPPORTED" in r.insufficient_reasons
    # with a (hypothetical) matching measurement it is still suppressed — the flag is about training support
    gm, cond = finalize_game_conditions(LJ, 240)
    meas = dict(cached_measurement(mdl), cond_hash=cond_hash(gm, cond))
    r3 = predict_editor_level(LJ, 240, bot_measurement=meas)
    assert r3.expected_ft_any is None and r3.insufficient_reasons == ["CAT_HELP_UNSUPPORTED"]
    # 'preserve' upload with autoCollectCount 0 → not a cat level at upload → no G1 flag
    r2 = predict_editor_level(LJ, 240, upload_opts={"auto_collect_mode": "preserve"})
    assert "CAT_HELP_UNSUPPORTED" not in r2.insufficient_reasons


def test_g4_time_limit_level_is_insufficient(mdl):
    assert mdl.model["support"]["condition_train_levels"]["time_limit"] == 0
    for key in ("timea", "timeAttack"):
        r = predict_editor_level(dict(LJ, **{key: 180}), L)
        assert r.status == "insufficient_evidence" and r.expected_ft_any is None
        assert "TIME_LIMIT_UNSUPPORTED" in r.insufficient_reasons


def test_measurement_condition_hash_must_match(mdl):
    meas = cached_measurement(mdl)
    ok = predict_editor_level(LJ, L, bot_measurement=meas)
    assert ok.status == "ok" and ok.measurement["source"] == "request"
    assert ok.expected_ft_any == predict_editor_level(LJ, L).expected_ft_any
    stale = predict_editor_level(LJ, L, bot_measurement=dict(meas, cond_hash="0" * 20))
    assert stale.status == "insufficient_evidence" and stale.expected_ft_any is None
    assert "BOT_CONDITION_MISMATCH" in stale.insufficient_reasons


def test_measurement_protocol_checked(mdl):
    meas = cached_measurement(mdl)
    bad = predict_editor_level(LJ, L, bot_measurement=dict(meas, bot_version="v2.3"))
    assert "BOT_PROTOCOL_MISMATCH" in bad.insufficient_reasons
    short = predict_editor_level(LJ, L, bot_measurement=dict(meas, rows=[dict(r, games=64) for r in meas["rows"]]))
    assert "BOT_PROTOCOL_MISMATCH" in short.insufficient_reasons
    unsolved = predict_editor_level(LJ, L, bot_measurement=dict(meas, rows=[dict(r, wins=0) for r in meas["rows"]]))
    assert "UNSOLVED" in unsolved.insufficient_reasons
    nosrc = predict_editor_level(LJ, L, bot_measurement=dict(meas, seed_band=""))
    assert "BOT_SOURCE_UNKNOWN" in nosrc.insufficient_reasons and nosrc.expected_ft_any is None
    noth = predict_editor_level(LJ, L, bot_measurement=dict(meas, rows=[r for r in meas["rows"] if r["theta"] != 0.55]))
    assert "BOT_PROTOCOL_MISMATCH" in noth.insufficient_reasons


def test_cache_measurement_gets_same_checks(mdl):
    """G3: a cached measurement whose stored cond_hash does not match is rejected exactly like a request one."""
    from app.core.clear_rate.model import ClearRateModel
    gm, cond = finalize_game_conditions(LJ, L)
    h = cond_hash(gm, cond)
    m2 = ClearRateModel.__new__(ClearRateModel)
    m2.__dict__.update(mdl.__dict__)
    m2.bot_cache = {h: dict(mdl.bot_cache[h], cond_hash="f" * 20, seed_band="")}
    r = predict_editor_level(LJ, L, model=m2)
    assert r.measurement["source"] == "cache" and r.expected_ft_any is None
    assert {"BOT_CONDITION_MISMATCH", "BOT_SOURCE_UNKNOWN"} <= set(r.insufficient_reasons)


# ── warning rules ────────────────────────────────────────────────────────────────────────────────
SUP = {"level_range": [32, 500], "gimmick_train_levels": {"ice": 16, "frog": 3, "stack": 0},
       "min_gimmick_levels": 10, "ood_min_features": 2, "feature_p01": [0.0] * len(FEATS),
       "feature_p99": [1.0] * len(FEATS), "target_p05_p95_by_segment": {"101-300": [0.84, 0.99]}}


def test_value_and_target_flags_thresholds():
    assert codes(guard.value_flags(0.849)) == ["LOW_CONFIDENCE"]
    assert codes(guard.value_flags(0.85)) == [] and codes(guard.value_flags(0.949)) == []
    assert codes(guard.value_flags(0.95)) == ["NEAR_CEILING"]
    assert codes(guard.target_flags(0.96, SUP, "101-300")) == ["NEAR_CEILING"]
    assert codes(guard.target_flags(0.80, SUP, "101-300")) == ["LOW_CONFIDENCE", "TARGET_OUT_OF_SUPPORT"]


def test_input_flags():
    assert codes(guard.input_flags(SUP, placement_level=None, gimmicks=["ice"])) == ["PLACEMENT_MISSING"]
    assert codes(guard.input_flags(SUP, placement_level=31, gimmicks=[])) == ["LEVEL_OUT_OF_RANGE"]
    assert codes(guard.input_flags(SUP, placement_level=501, gimmicks=[])) == ["LEVEL_OUT_OF_RANGE"]
    assert codes(guard.input_flags(SUP, placement_level=200, gimmicks=["ice", "frog", "stack"])) == \
        ["GIMMICK_LOW_TRAIN", "GIMMICK_UNSEEN"]


def test_feature_flags_and_confidence():
    f = {c: 0.5 for c in FEATS}
    f.update(gimmick_first=0.0, novelty=0.0, has_grass=0.0, has_chain=0.0)
    assert codes(guard.feature_flags(SUP, f)) == []
    assert codes(guard.feature_flags(SUP, dict(f, tiles=2.0))) == []
    assert codes(guard.feature_flags(SUP, dict(f, tiles=2.0, layers=-1.0))) == ["FEATURE_OOD"]
    fl = guard.feature_flags(SUP, dict(f, has_grass=1.0))
    assert codes(fl) == ["GIMMICK_BOT_WEAK"] and guard.confidence(fl) == "medium"
    fl = guard.feature_flags(SUP, dict(f, gimmick_first=1.0))
    assert codes(fl) == ["GIMMICK_FIRST"] and guard.confidence(fl) == "low"
    assert guard.confidence([]) == "high"


# ── verdict (library only) ───────────────────────────────────────────────────────────────────────
def _pred(expected, rng, conf="high", in_support=True, L_=200):
    return ClearRatePrediction(model_version="m", target_metric="ft_any_v1", bot_version="v2.4", bot_protocol="p",
                               placement_level=L_, cond_hash="h", status="ok" if in_support else "insufficient_evidence",
                               in_support=in_support, insufficient_reasons=[] if in_support else ["FEATURE_OOD"],
                               expected_ft_any=expected if in_support else None, range80_ft_any=rng, confidence=conf)


def test_p_in_band_symmetric_normal():
    # symmetric range in logit with sd 1 → band = ±1 sd → 0.6827
    import math
    mu, s = 1.0, 1.0
    rng = (expit(mu - 1.2815515655446004 * s), expit(mu + 1.2815515655446004 * s))
    p = p_in_band(expit(mu), rng, (expit(mu - s), expit(mu + s)))
    assert abs(p - math.erf(1 / math.sqrt(2))) < 1e-9


def test_judge_rules():
    sup = dict(SUP, target_p05_p95_by_segment={"101-300": [0.80, 0.99]})
    assert judge(_pred(0.90, (0.87, 0.93)), 0.90, sup).verdict == "PASS"
    v = judge(_pred(0.90, (0.87, 0.93)), 0.97, sup)
    assert v.verdict == "FAIL" and v.p_in_band < 0.5
    assert judge(_pred(0.90, (0.87, 0.93), in_support=False), 0.90, sup).verdict == "INSUFFICIENT_EVIDENCE"
    assert judge(_pred(0.90, (0.87, 0.93), conf="low"), 0.90, sup).verdict == "INSUFFICIENT_EVIDENCE"
    assert judge(_pred(0.90, (0.87, 0.93)), 0.82, sup).verdict == "INSUFFICIENT_EVIDENCE"     # target < 0.85
    assert judge(_pred(0.90, (0.87, 0.93)), 0.995, sup).verdict == "INSUFFICIENT_EVIDENCE"    # target out of support
    lo, hi = target_band(0.9)
    assert lo < 0.9 < hi


def test_judge_on_real_prediction(mdl):
    r = predict_editor_level(LJ, L)
    v = judge(r, r.expected_ft_any, mdl.model["support"])
    assert v.verdict in ("PASS", "INSUFFICIENT_EVIDENCE") and v.p_in_band is not None


# ── API schema ───────────────────────────────────────────────────────────────────────────────────
RESPONSE_KEYS = {"model_version", "target_metric", "bot_version", "bot_protocol", "placement_level", "cond_hash",
                 "status", "in_support", "insufficient_reasons", "evidence_flags", "expected_ft_any", "range80_ft_any",
                 "expected_unaided_lb", "expected_help_rate", "confidence", "measurement", "bot_unaided_win_rate"}


def test_api_predict(client):
    res = client.post("/api/clear-rate/predict", json={"level_json": LJ, "placement_level": L})
    assert res.status_code == 200
    body = res.json()
    assert set(body) == RESPONSE_KEYS
    assert body["status"] == "ok" and body["model_version"] == load_model().version
    assert "verdict" not in body


def test_api_rejects_bad_input(client, mdl):
    assert client.post("/api/clear-rate/predict", json={"level_json": {"foo": 1}, "placement_level": L}).status_code == 422
    assert client.post("/api/clear-rate/predict", json={"level_json": LJ, "placement_level": 0}).status_code == 422
    assert client.post("/api/clear-rate/predict", json={"level_json": LJ, "placement_level": L,
                                                        "help_rate_observed": 0.2}).status_code == 422  # extra=forbid
    meas = cached_measurement(mdl)
    meas.pop("cond_hash")
    body = client.post("/api/clear-rate/predict", json={"level_json": LJ, "placement_level": L,
                                                        "bot_measurement": {k: v for k, v in meas.items()
                                                                            if k in ("bot_version", "protocol", "seed_band", "rows")}}).json()
    assert body["status"] == "insufficient_evidence" and "BOT_CONDITION_MISMATCH" in body["insufficient_reasons"]
    r = client.post("/api/clear-rate/predict", json={"level_json": LJ})
    assert r.status_code == 200 and r.json()["status"] == "insufficient_evidence"


# ── training reproducibility ─────────────────────────────────────────────────────────────────────
TRAIN_PY = Path(os.environ.get("CLEAR_RATE_TRAIN_PYTHON", str(BACKEND.parent.parent / "TileMatchAutoLevel/analysis_venv/bin/python")))
TRAIN_DATA = BACKEND / "data/pv_sandbox/af_calibration/bot_v24/bot_v2.4f_no_rules_only.json"


@pytest.mark.skipif(not TRAIN_PY.exists() or not TRAIN_DATA.exists(),
                    reason="needs a numpy python (CLEAR_RATE_TRAIN_PYTHON) and the local AF/bot sandbox data")
def test_training_reproduces_saved_model(mdl):
    out = subprocess.run([str(TRAIN_PY), "-W", "ignore", str(BACKEND / "scripts/train_clear_rate_model.py"),
                          "--check", "--version", mdl.version], capture_output=True, text=True, timeout=600,
                         cwd=str(BACKEND.parent))
    assert out.returncode == 0, out.stdout[-2000:] + out.stderr[-2000:]
    assert json.loads(out.stdout.strip().splitlines()[-1]) == {"model_json_identical": True, "bot_cache_identical": True}


def test_active_version_registered():
    assert json.loads((MODELS_DIR / "active.json").read_text())["version"] == load_model().version
