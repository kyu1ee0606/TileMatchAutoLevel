"""Two-mode experimental path (doc 35 §9): shared measure + store, mode B (virtual), mode selection, /target-eval."""
import ast
import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.core.clear_rate import BotMeasurement, cond_hash, finalize_game_conditions, load_model
from app.core.clear_rate import experiment as X
from app.core.clear_rate import guard
from app.core.clear_rate import virtual as V
from app.core.clear_rate.measure import (MeasurementStore, bot_config, bot_exposure, config_hash, measure,
                                         measure_theta)
from app.main import app

BACKEND = Path(__file__).resolve().parents[1]
FIX = json.loads((BACKEND / "tests/golden/clear_rate_L237.json").read_text(encoding="utf-8"))
LJ, L = FIX["level_json"], FIX["placement_level"]
A_KEYS = ("expected_ft_any", "range80_ft_any", "expected_unaided_lb", "expected_help_rate", "clear_rate_verdict",
          "predicted_clear_rate")


@pytest.fixture(scope="module")
def mdl():
    return load_model()


@pytest.fixture(scope="module")
def fin():
    return finalize_game_conditions(LJ, L)


@pytest.fixture(scope="module")
def client():
    return TestClient(app)


def meas(h, rows, *, band="C", protocol="theta085x512_v1", ver="v2.4", aids=None):
    return BotMeasurement(bot_version=ver, protocol=protocol, cond_hash=h, rows=tuple(rows), seed_band=band,
                          aids_simulated=aids)


# ── shared measurement = training protocol, on the final game conditions ─────────────────────────────────────
def test_measure_reproduces_training_row_from_editor_json(mdl, fin):
    """Editor JSON → finalize_game_conditions → cond_hash hits the training cache → the shared measure path with the
    training band reproduces the stored training row exactly (same bot, config, seeds)."""
    gm, cond = fin
    cached = mdl.bot_cache[cond_hash(gm, cond)]
    cfg = bot_config(bot_exposure(mdl.model["position"], L), cond)
    r = measure_theta(gm, cond, theta=0.85, games=128, seed_base=11_000_000, cfg=cfg)
    c = next(x for x in cached["rows"] if x["theta"] == 0.85)
    assert (r["wins"], r["fail_reasons"]) == (c["wins"], c["fail_reasons"])


def test_measure_tags_and_store_invalidation(mdl, fin, tmp_path, monkeypatch):
    import app.core.clear_rate.measure as M
    gm, cond = fin
    monkeypatch.setitem(M.PROTOCOLS, "tiny_test", ((0.85,), 4))
    expo = bot_exposure(mdl.model["position"], L)
    m, meta = measure(gm, cond, exposure=expo, protocol="tiny_test", seed_band="S")
    assert (m.cond_hash, m.seed_band, m.bot_version, m.aids_simulated) == (cond_hash(gm, cond), "S", "v2.4",
                                                                           {"booster": False, "revive": False})
    assert meta["seed_rule"].startswith("15,000,000") and meta["games"] == 4
    st = MeasurementStore(tmp_path / "m.json")
    st.put(m, meta)
    ch = meta["bot_config_hash"]
    assert st.get(m.cond_hash, "tiny_test", "S", ch) is not None
    assert st.get(m.cond_hash, "tiny_test", "C", ch) is None                      # other band
    assert st.get(m.cond_hash, "theta4x128_v1", "S", ch) is None                  # other protocol
    other_place = config_hash(bot_config(bot_exposure(mdl.model["position"], 480), cond))
    assert other_place != ch and st.get(m.cond_hash, "tiny_test", "S", other_place) is None  # placement → exposure
    cond2 = {**cond, "useTileCount": cond["useTileCount"] + 1}
    assert cond_hash(gm, cond2) != m.cond_hash                                    # changed conditions → new key
    assert MeasurementStore(tmp_path / "m.json").get(m.cond_hash, "tiny_test", "S", ch)[0].rows == m.rows


def test_measure_rejects_unknown_protocol_or_band(mdl, fin):
    gm, cond = fin
    expo = bot_exposure(mdl.model["position"], L)
    with pytest.raises(ValueError):
        measure(gm, cond, exposure=expo, protocol="theta9x9", seed_band="S")
    with pytest.raises(ValueError):
        measure(gm, cond, exposure=expo, protocol="theta4x128_v1", seed_band="X")


# ── mode B ────────────────────────────────────────────────────────────────────────────────────────────────────
def test_virtual_module_does_not_use_the_model():
    tree = ast.parse((BACKEND / "app/core/clear_rate/virtual.py").read_text(encoding="utf-8"))
    mods = {n.module for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)} | \
           {a.name for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names}
    assert not any(m and ("model" in m or "predict" in m or "select" in m) for m in mods), mods


def test_virtual_def_matches_bot_defaults():
    from app.core.bot_simulator import V24_DEFAULT
    d = V.DEFAULT_DEF
    assert d.behavior == tuple(V24_DEFAULT) and d.theta == 0.85 and d.help == "none"
    assert d.def_id == V.VirtualDef().def_id and len(d.def_id) == 16
    assert V.VirtualDef(theta=1.0).def_id != d.def_id


@pytest.mark.parametrize("wins,games,expect", [
    (77, 512, V.MET),            # 0.150
    (100, 512, V.MET),           # 0.195 (gap 0.045)
    (110, 512, V.NOT_MET),       # 0.215
    (0, 512, V.INSUFFICIENT),    # 0 wins ≠ impossible
    (20, 128, V.INSUFFICIENT),   # fewer games than the definition
])
def test_virtual_verdict_values(wins, games, expect):
    v = V.virtual_verdict(meas("h", [{"theta": 0.85, "games": games, "wins": wins}]), V.DEFAULT_DEF, 0.15, "h")
    assert v.bot_virtual_verdict == expect and v.real_user_status == "unverified"


def test_virtual_verdict_wide_interval_is_insufficient():
    d = V.VirtualDef(confirm_games=64)
    v = V.virtual_verdict(meas("h", [{"theta": 0.85, "games": 64, "wins": 32}]), d, 0.5, "h")
    assert v.bot_virtual_verdict == V.INSUFFICIENT and "반폭" in v.reason


@pytest.mark.parametrize("kw", [{"band": "S"}, {"protocol": "theta4x128_v1"}, {"ver": "v2.3"},
                                {"aids": {"booster": True, "revive": False}}])
def test_virtual_verdict_rejects_wrong_measurement(kw):
    v = V.virtual_verdict(meas("h", [{"theta": 0.85, "games": 512, "wins": 77}], **kw), V.DEFAULT_DEF, 0.15, "h")
    assert v.bot_virtual_verdict == V.INSUFFICIENT


def test_virtual_verdict_rejects_condition_mismatch():
    v = V.virtual_verdict(meas("old", [{"theta": 0.85, "games": 512, "wins": 77}]), V.DEFAULT_DEF, 0.15, "new")
    assert v.bot_virtual_verdict == V.INSUFFICIENT and "조건 해시" in v.reason


def test_select_virtual_ties_keep_index_order():
    assert V.select_virtual([(0, 0.3), (1, 0.1), (2, 0.2), (3, 0.2)], 0.2, k=2) == [(2, 0.2), (3, 0.2)]


# ── mode selection / separation ───────────────────────────────────────────────────────────────────────────────
@pytest.mark.parametrize("mode", [None, "", "auto", "USER_EXPECTED"])
def test_mode_required(mode):
    with pytest.raises(X.TargetModeError):
        X.require_mode(mode)


def test_user_expected_precheck(mdl):
    assert X.user_expected_precheck(mdl, 0.85, 157) == []
    assert "LOW_CONFIDENCE" in X.user_expected_precheck(mdl, 0.80, 157)
    assert "TARGET_OUT_OF_SUPPORT" in X.user_expected_precheck(mdl, 0.85, 60)   # 32-100 band starts at 0.915
    assert "LEVEL_OUT_OF_RANGE" in X.user_expected_precheck(mdl, 0.9, 600)


def test_bot_virtual_result_has_no_mode_a_fields(fin):
    gm, cond = fin
    h = cond_hash(gm, cond)
    out = X.evaluate_bot_virtual(gm, cond, None, meas(h, [{"theta": 0.85, "games": 512, "wins": 256}]), 0.5)
    assert out["bot_virtual_verdict"] == V.MET and out["real_user_status"] == "unverified"
    assert not any(k in out for k in A_KEYS)


def test_user_expected_out_of_support_has_no_number_and_no_b_fallback(mdl, fin):
    gm, cond = fin
    out = X.evaluate_user_expected(mdl, gm, cond, 600, None, 0.9, random_layout=False)
    assert out["prediction"]["expected_ft_any"] is None
    assert out["verdict"]["verdict"] == "INSUFFICIENT_EVIDENCE"
    assert not any(k.startswith("bot_virtual") for k in out) and out["target_mode"] == "user_expected"


def test_upload_conversion_ignores_bot_virtual_fields():
    from app.api.routes.gboost import _convert_to_townpop_format
    base = {**LJ, "layer": int(LJ["layer"])}
    lj = {**base, "bot_virtual_rate_c": 0.15, "bot_virtual_verdict": "BOT_TARGET_MET", "real_user_status": "unverified"}
    row = _convert_to_townpop_format(lj)
    assert not any("bot_virtual" in k or k == "real_user_status" for k in row)
    assert row == _convert_to_townpop_format(dict(base))


# ── API ───────────────────────────────────────────────────────────────────────────────────────────────────────
def test_api_target_eval_requires_mode(client):
    r = client.post("/api/clear-rate/target-eval", json={"target": 0.9, "level_json": LJ, "placement_level": L})
    assert r.status_code == 422


def test_api_target_eval_modes_are_separate(client, mdl, fin):
    gm, cond = fin
    h = cond_hash(gm, cond)
    cached = mdl.bot_cache[h]
    body = {"target": 0.9, "level_json": LJ, "placement_level": L,
            "bot_measurement_confirm": {**{k: cached[k] for k in ("bot_version", "protocol", "cond_hash", "rows")},
                                        "seed_band": "C"}}
    a = client.post("/api/clear-rate/target-eval", json={**body, "target_mode": "user_expected"}).json()
    assert a["target_mode"] == "user_expected" and a["bot_virtual"] is None
    assert a["user_expected"]["prediction"]["expected_ft_any"] is not None
    assert a["user_expected"]["verdict"]["bot_seed_confirmed"] is True
    b = client.post("/api/clear-rate/target-eval", json={**body, "target_mode": "bot_virtual", "target": 0.5}).json()
    assert b["target_mode"] == "bot_virtual" and b["user_expected"] is None
    # the cached measurement is theta4x128 → not the B confirmation protocol → measurement insufficient
    assert b["bot_virtual"]["bot_virtual_verdict"] == V.INSUFFICIENT
    assert b["bot_virtual"]["real_user_status"] == "unverified"
    assert not any(k in b["bot_virtual"] for k in A_KEYS)


# ── pilot 2: structural screen, bands, isolated generation ───────────────────────────────────────────────────
@pytest.mark.parametrize("placement", [L, 157, 268])
def test_structural_screen_is_subset_of_prediction_flags(mdl, placement):
    """The screen reports only flags the full prediction raises too, and a blocking screen means no normal verdict
    (no number or confidence low) — it never relaxes or replaces the prediction."""
    from app.core.clear_rate import predict_level
    gm, cond = finalize_game_conditions(LJ, placement)
    s = X.structural_screen(mdl, gm, cond, placement, random_layout=False)
    cached = dict(mdl.bot_cache[cond_hash(*finalize_game_conditions(LJ, L))])
    m = BotMeasurement.from_dict({**cached, "cond_hash": cond_hash(gm, cond)})
    p = predict_level(mdl, gm, cond, placement, m, random_layout=False)
    full = {f["code"] for f in p.evidence_flags}
    assert set(s["codes"]) <= full, set(s["codes"]) - full
    if s["blocking"]:
        assert not p.in_support or p.confidence == "low"


def test_virtual_def_bands_follow_definition():
    d = V.VirtualDef(search_protocol="theta085x512_v1", seed_bands=("S2B", "C2"))
    ok = meas("h", [{"theta": 0.85, "games": 512, "wins": 256}], band="C2")
    assert V.virtual_verdict(ok, d, 0.5, "h").bot_virtual_verdict == V.MET
    old = meas("h", [{"theta": 0.85, "games": 512, "wins": 256}], band="C")      # pilot-1 confirmation band
    assert V.virtual_verdict(old, d, 0.5, "h").bot_virtual_verdict == V.INSUFFICIENT
    assert d.def_id != V.DEFAULT_DEF.def_id


def test_seed_bands_do_not_overlap():
    from app.core.clear_rate.measure import LAYOUTS, PROTOCOLS, SEED_BANDS
    span = (LAYOUTS - 1) * 1000 + max(g for _, g in PROTOCOLS.values())       # max offset used by a band
    lo = sorted(SEED_BANDS.values())
    assert all(b - a > span for a, b in zip(lo, lo[1:]))
    assert PROTOCOLS["theta085x64_v1"] == ((0.85,), 64)


def test_isolated_generation_is_reproducible():
    import random as _r
    import sys
    sys.path.insert(0, str(BACKEND / "scripts"))
    import clear_rate_gen_pilot2 as P2
    spec = P2.PLAN["levels"][2]
    req = P2.build_request(spec["placement"], 0.4, _r.Random(7), spec)
    a, b = P2.generate_isolated(req, 7), P2.generate_isolated(req, 7)
    assert a["ok"] and json.dumps(a["level_json"], sort_keys=True) == json.dumps(b["level_json"], sort_keys=True)
    assert req["target_difficulty"] < 0.6 and req["max_layers"] <= 5


def test_seed_bands_avoid_other_experiments():
    """Pilot bands vs bands used elsewhere (bot_v24 training 11M, natural experiments 13M / 23M, pv pilots 1–9.1M)."""
    from app.core.clear_rate.measure import LAYOUTS, PROTOCOLS, SEED_BANDS
    span = (LAYOUTS - 1) * 1000 + max(g for _, g in PROTOCOLS.values())
    external = [1_000_000, 2_000_000, 3_000_000, 4_000_000, 5_000_000, 6_000_000, 7_000_000, 8_000_000, 9_100_000,
                13_000_000, 23_000_000]
    for name, b in SEED_BANDS.items():
        if name == "seed11M":
            continue
        assert all(abs(b - e) > span for e in external), name
    assert {"S3", "C3"} <= set(SEED_BANDS) and SEED_BANDS["S3"] != SEED_BANDS["C3"]


def test_a85_gate_and_band_do_not_overlap(mdl):
    """Doc 33 §15-1: with the active model the 80% upper bound is always 1 (quantile head at the target clip), and a
    prediction that passes the confidence gate is ≥ 0.92 > the 0.85 band top — so P(in band) < 0.5 for target 0.85.
    Pins the finding; if the model or zone table changes this test shows the analysis must be redone."""
    import math
    from app.core.clear_rate.select import target_band
    h = mdl.model["heads"]["ft_any"]

    def leaves(t):
        return leaves(t[3]) + leaves(t[4]) if t[0] == "node" else [t[1]]
    G = h["q_hi"]
    lower = G["base"] + G["lr"] * sum(min(leaves(t)) for t in G["trees"])
    assert lower + h["cqr_w"] >= math.log(0.99 / 0.01) - 1e-9   # model.range_to_prob → upper bound 1 for every input
    zones_low = [z for z in mdl.model["support"]["reliability"]["pred_bins"]
                 if z["mae"] >= guard.ZONE_LOW["mae_ge"] or z["coverage80"] < guard.ZONE_LOW["coverage80_lt"]]
    assert max(z["hi"] for z in zones_low) > target_band(0.85)[1]
