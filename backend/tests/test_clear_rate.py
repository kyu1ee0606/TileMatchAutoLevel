"""New real-user clear-rate prediction (app/core/clear_rate, /api/clear-rate/predict) — docs 31 / 33."""
import copy
import hashlib
import json
import os
import subprocess
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.core.clear_rate import guard
from app.core.clear_rate.features import FEATS, expit
from app.core.clear_rate.model import MODELS_DIR, gbm_predict, load_model, ridge_predict
from app.core.clear_rate.service import predict
from app.main import app

BACKEND = Path(__file__).resolve().parents[1]
FIX = json.loads((BACKEND / "tests/golden/clear_rate_L237.json").read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def mdl():
    return load_model()


@pytest.fixture(scope="module")
def client():
    return TestClient(app)


# ── artifact ─────────────────────────────────────────────────────────────────────────────────────
def test_manifest_provenance(mdl):
    m = mdl.manifest
    assert m["bot_version"] == "v2.4" and m["bot_protocol"] == "theta4x128_v1"
    assert m["target_metric"] == "ft_any_v1"
    assert m["train_data"]["shard_commit"] == "b741f6a3"
    assert m["train_data"]["n_levels"] == 379
    assert m["trained_at"] and m["gates"]["pass"]
    raw = (mdl.dir / "model.json").read_text(encoding="utf-8")
    assert hashlib.sha256(raw.encode()).hexdigest() == m["model_json_sha256"]
    assert mdl.model["features"] == FEATS


def test_pure_python_matches_training_numpy(mdl):
    """model.json 'check' rows hold numpy predictions made at training time."""
    H = mdl.model["heads"]
    for c in mdl.model["check"]:
        f = dict(zip(FEATS, c["x"]))
        for head, k in (("ft_any", "ft_logit"), ("unaided_lb", "lb_logit"), ("help_rate", "help_logit")):
            assert abs(mdl.predict_logit(head, f) - c[k]) < 1e-9
        q = H["ft_any"]
        a, b = gbm_predict(q["q_lo"], c["x"]), gbm_predict(q["q_hi"], c["x"])
        assert abs(min(a, b) - c["q_lo"]) < 1e-9 and abs(max(a, b) - c["q_hi"]) < 1e-9
        pt = H["ft_any"]["point"]
        assert abs(0.5 * (ridge_predict(pt["ridge"], c["x"]) + gbm_predict(pt["gbm"], c["x"])) - c["ft_logit"]) < 1e-9


# ── service ──────────────────────────────────────────────────────────────────────────────────────
def test_predict_live_map_from_cache_matches_training(mdl):
    r = predict(FIX["level_json"], FIX["placement_level"])
    assert r["status"] == "ok" and r["bot_source"] == "cache"
    chk = next(c for c in mdl.model["check"] if c["L"] == FIX["placement_level"])
    assert abs(r["expected"] - round(expit(chk["ft_logit"]), 4)) < 1e-9
    lo, hi = r["range80"]
    assert 0 <= lo <= r["expected"] <= hi <= 1
    assert 0 < r["aux"]["unaided_lb"] < r["expected"]
    assert 0 < r["aux"]["help_rate"] < 1
    assert r["confidence"] in ("high", "medium", "low")
    assert set(r["bot_success_reference"]) == {"theta055", "theta065", "theta085", "theta100"}


def test_predict_deterministic():
    a = predict(copy.deepcopy(FIX["level_json"]), 237)
    b = predict(copy.deepcopy(FIX["level_json"]), 237)
    assert a == b


def test_placement_missing_gives_reason_not_number():
    r = predict(FIX["level_json"], None)
    assert r["status"] == "insufficient_evidence" and r["expected"] is None
    assert [f["code"] for f in r["evidence_flags"]] == ["PLACEMENT_MISSING"]


def test_level_out_of_range():
    r = predict(FIX["level_json"], 600)
    assert r["status"] == "insufficient_evidence" and r["expected"] is None
    assert "LEVEL_OUT_OF_RANGE" in {f["code"] for f in r["evidence_flags"]}


def test_unmeasured_map_needs_measurement():
    lj = copy.deepcopy(FIX["level_json"])
    lj["useTileCount"] = int(lj["useTileCount"]) + 1  # different level config → no cached bot rows
    r = predict(lj, 237)
    assert r["status"] == "measurement_required" and r["expected"] is None and r["bot_source"] is None


def _rows_from_cache(mdl):
    key = predict(FIX["level_json"], 237)["map_hash"]
    return copy.deepcopy(mdl.bot_cache[key]["rows"])


def test_request_measurement_used_and_protocol_checked(mdl):
    rows = _rows_from_cache(mdl)
    ok = predict(FIX["level_json"], 237, bot_measurement={"bot_version": "v2.4", "protocol": "theta4x128_v1", "rows": rows})
    assert ok["status"] == "ok" and ok["bot_source"] == "request"
    assert ok["expected"] == predict(FIX["level_json"], 237)["expected"]
    bad = predict(FIX["level_json"], 237, bot_measurement={"bot_version": "v2.3", "protocol": "theta4x128_v1", "rows": rows})
    assert bad["status"] == "insufficient_evidence" and bad["expected"] is None
    assert "BOT_PROTOCOL_MISMATCH" in {f["code"] for f in bad["evidence_flags"]}
    short = predict(FIX["level_json"], 237, bot_measurement={"bot_version": "v2.4", "protocol": "theta4x128_v1",
                                                             "rows": [dict(r, games=64) for r in rows]})
    assert "BOT_PROTOCOL_MISMATCH" in {f["code"] for f in short["evidence_flags"]}


def test_unsolved_flag(mdl):
    rows = [dict(r, wins=0) for r in _rows_from_cache(mdl)]
    r = predict(FIX["level_json"], 237, bot_measurement={"bot_version": "v2.4", "protocol": "theta4x128_v1", "rows": rows})
    assert r["status"] == "insufficient_evidence"
    assert "UNSOLVED" in {f["code"] for f in r["evidence_flags"]}


def test_target_info_is_information_only():
    r = predict(FIX["level_json"], 237, target=0.80)
    codes = {f["code"] for f in r["evidence_flags"]}
    assert "LOW_CONFIDENCE" in codes and r["confidence"] == "low"
    assert r["target"]["value"] == 0.80 and isinstance(r["target"]["in_range80"], bool)
    assert "verdict" not in r


# ── warning rules ────────────────────────────────────────────────────────────────────────────────
SUP = {"level_range": [32, 500], "gimmick_train_levels": {"ice": 16, "frog": 3, "stack": 0},
       "min_gimmick_levels": 10, "ood_min_features": 2, "feature_p01": [0.0] * len(FEATS),
       "feature_p99": [1.0] * len(FEATS), "target_p05_p95_by_segment": {"101-300": [0.84, 0.99]}}


def codes(fl):
    return [f["code"] for f in fl]


def test_value_flags_thresholds():
    assert codes(guard.value_flags(0.849, None, SUP, "101-300")) == ["LOW_CONFIDENCE"]
    assert codes(guard.value_flags(0.85, None, SUP, "101-300")) == []
    assert codes(guard.value_flags(0.949, None, SUP, "101-300")) == []
    assert codes(guard.value_flags(0.95, None, SUP, "101-300")) == ["NEAR_CEILING"]
    assert codes(guard.value_flags(0.90, 0.96, SUP, "101-300")) == ["NEAR_CEILING"]
    assert codes(guard.value_flags(0.90, 0.80, SUP, "101-300")) == ["LOW_CONFIDENCE", "TARGET_OUT_OF_SUPPORT"]


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
    assert codes(guard.feature_flags(SUP, dict(f, tiles=2.0))) == []          # one feature outside: allowed
    assert codes(guard.feature_flags(SUP, dict(f, tiles=2.0, layers=-1.0))) == ["FEATURE_OOD"]
    fl = guard.feature_flags(SUP, dict(f, has_grass=1.0))
    assert codes(fl) == ["GIMMICK_BOT_WEAK"] and guard.confidence(fl) == "medium"
    fl = guard.feature_flags(SUP, dict(f, gimmick_first=1.0))
    assert codes(fl) == ["GIMMICK_FIRST"] and guard.confidence(fl) == "low"
    assert guard.confidence([]) == "high"
    assert guard.suppressed([guard.flag("FEATURE_OOD", "hard")])
    assert not guard.suppressed([guard.flag("TARGET_OUT_OF_SUPPORT", "hard"), guard.flag("NEAR_CEILING", "soft")])


# ── API schema ───────────────────────────────────────────────────────────────────────────────────
def test_api_predict(client):
    res = client.post("/api/clear-rate/predict", json={"level_json": FIX["level_json"], "placement_level": 237})
    assert res.status_code == 200
    body = res.json()
    assert set(body) == {"model_version", "target_metric", "bot_version", "status", "placement_level", "map_hash",
                         "expected", "range80", "confidence", "evidence_flags", "aux", "target", "bot_source",
                         "bot_success_reference"}
    assert body["status"] == "ok" and body["model_version"] == load_model().version


def test_api_rejects_bad_input(client):
    assert client.post("/api/clear-rate/predict", json={"level_json": {"foo": 1}, "placement_level": 237}).status_code == 422
    assert client.post("/api/clear-rate/predict", json={"level_json": FIX["level_json"], "placement_level": 0}).status_code == 422
    r = client.post("/api/clear-rate/predict", json={"level_json": FIX["level_json"]})
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
