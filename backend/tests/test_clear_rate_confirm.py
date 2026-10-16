"""Validation-tab C confirmation jobs (doc 38 §10). Bot runs are replaced by a fake runner except in the tiny
measure() cancel test — the real C measurement is a manual, approved step (doc 38 §12)."""
import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.core.clear_rate import BotMeasurement, cond_hash, finalize_game_conditions, load_model
from app.core.clear_rate import confirm as CF
from app.core.clear_rate import measure as M
from app.main import app

BACKEND = Path(__file__).resolve().parents[1]
FIX = json.loads((BACKEND / "tests/golden/clear_rate_L237.json").read_text(encoding="utf-8"))
LJ, L = FIX["level_json"], FIX["placement_level"]


@pytest.fixture(scope="module")
def mdl():
    return load_model()


class FakeRunner:
    """Stands in for measure.measure: returns the model's cached rows for the map, tagged with the requested band."""

    def __init__(self, mdl, *, games_scale=1, fail=None, on_call=None):
        self.mdl, self.calls, self.games_scale, self.fail, self.on_call = mdl, 0, games_scale, fail, on_call

    def __call__(self, game_map, cond, *, exposure, protocol, seed_band, should_stop=None, on_row=None):
        self.calls += 1
        if self.on_call:
            self.on_call()
        if should_stop is not None and should_stop():
            raise M.MeasurementCancelled("stop")
        if self.fail:
            raise self.fail
        h = cond_hash(game_map, cond)
        ref = self.mdl.bot_cache[cond_hash(*finalize_game_conditions(LJ, L))]
        rows = tuple({**r, "games": int(r["games"] * self.games_scale)} for r in ref["rows"])
        cfg = M.bot_config(exposure, cond)
        m = BotMeasurement(bot_version=M.BOT_VERSION, protocol=protocol, cond_hash=h, rows=rows, seed_band=seed_band,
                           source="measure", aids_simulated=dict(M.NO_AIDS))
        if on_row:
            on_row(sum(r["games"] for r in rows))
        return m, {"bot_config": cfg, "bot_config_hash": M.config_hash(cfg), "games": sum(r["games"] for r in rows)}


def make(tmp_path, mdl, **kw):
    runner = kw.pop("runner", None) or FakeRunner(mdl)
    return CF.ConfirmJobManager(tmp_path, model_loader=lambda: mdl, runner=runner, start_threads=False, **kw), runner


def submit(mgr, lj=LJ, level=L, h=None):
    h = h or mgr.plan(lj, level)["cond_hash"]
    return mgr.submit(level_json=lj, placement_level=level, expected_cond_hash=h, map_id=f"b:{level}", batch_id="b")


# ── band registry / kinds / versions ──────────────────────────────────────────────────────────────────────────
def test_band_registry_has_no_collision_and_cv_is_the_only_confirm_band():
    assert CF.band_registry_problems() == []
    assert M.SEED_BANDS["CV"] == 22_000_000 and CF.CONFIRM_BANDS == ("CV",)
    for band in ("seed11M", "S", "C", "C2", "C3", "S3", "P2", "", None):
        assert CF.measurement_kind(band) == CF.KIND_EXPLORATION, band
    assert CF.measurement_kind("CV") == CF.KIND_CONFIRM


def test_band_registry_detects_collision(monkeypatch):
    monkeypatch.setitem(M.SEED_BANDS, "CV", 23_000_100)
    assert any("external" in p for p in CF.band_registry_problems())


def test_judge_version_tracks_thresholds(monkeypatch):
    v = CF.judge_version()
    assert v == CF.judge_version() and v.startswith("judge-")
    import app.core.clear_rate.select as S
    monkeypatch.setitem(S.PROPOSED, "p_in_band_pass", 0.4)
    assert CF.judge_version() != v


def test_active_model_protocol_matches_measure(mdl):
    assert CF.protocol_problems(mdl) == []


# ── submit / duplicate / reuse ────────────────────────────────────────────────────────────────────────────────
def test_plan_fixes_conditions_and_games(tmp_path, mdl):
    mgr, runner = make(tmp_path, mdl)
    p = mgr.plan(LJ, L)
    gm, cond = finalize_game_conditions(LJ, L)
    assert p["cond_hash"] == cond_hash(gm, cond) and p["seed_band"] == "CV" and p["games_planned"] == 512
    assert p["existing"] is None and runner.calls == 0 and not any(k.startswith("_") for k in p)


def test_submit_refuses_changed_conditions(tmp_path, mdl):
    mgr, runner = make(tmp_path, mdl)
    with pytest.raises(CF.ConfirmRejected) as e:
        submit(mgr, h="stale-hash")
    assert e.value.code == "CONDITION_CHANGED" and runner.calls == 0


def test_submit_refuses_protocol_mismatch(tmp_path, mdl, monkeypatch):
    mgr, runner = make(tmp_path, mdl)
    h = mgr.plan(LJ, L)["cond_hash"]
    monkeypatch.setattr(M, "BOT_VERSION", "v2.5")
    with pytest.raises(CF.ConfirmRejected) as e:
        submit(mgr, h=h)
    assert e.value.code == "PROTOCOL_MISMATCH" and runner.calls == 0


def test_submit_refuses_unsupported_input(tmp_path, mdl):
    mgr, runner = make(tmp_path, mdl)
    with pytest.raises(CF.ConfirmRejected) as e:
        submit(mgr, level=600)
    assert e.value.code == "UNSUPPORTED_INPUT" and "LEVEL_OUT_OF_RANGE" in e.value.detail


def test_duplicate_submit_joins_active_job_then_reuses_done(tmp_path, mdl):
    mgr, runner = make(tmp_path, mdl)
    a = submit(mgr)
    b = submit(mgr)
    assert a["created"] and not b["created"] and b["reused"] == "active"
    assert a["job"]["job_id"] == b["job"]["job_id"] and a["job"]["status"] == CF.QUEUED
    mgr.run_pending()
    c = submit(mgr)
    assert c["reused"] == "done" and c["job"]["job_id"] == a["job"]["job_id"] and runner.calls == 1


# ── completion / evaluation ───────────────────────────────────────────────────────────────────────────────────
def test_done_job_is_stored_as_confirm_and_evaluates_like_request_c(tmp_path, mdl):
    mgr, _ = make(tmp_path, mdl)
    jid = submit(mgr)["job"]["job_id"]
    mgr.run_pending()
    job = mgr.get(jid)
    assert job["status"] == CF.DONE and job["games_done"] == 512 and job["measurement_ref"].split("|")[2] == "CV"
    rec = M.MeasurementStore(tmp_path / "measurements.json").data[job["measurement_ref"]]
    assert rec["meta"]["measurement_kind"] == "confirm" and rec["meta"]["job_id"] == jid
    out = mgr.evaluate(job_id=jid, level_json=LJ, placement_level=L, target=0.9)
    v, prov = out["user_expected"]["verdict"], out["provenance"]
    assert v["bot_seed_confirmed"] is True
    assert not any(f["code"] == "SELECTION_UNCONFIRMED" for f in v["target_flags"])
    assert prov["measurement_kind"] == "confirm" and prov["seed_band"] == "CV" and prov["games_completed"] == 512
    assert prov["judge_version"] == CF.judge_version() and prov["model_version"] == mdl.version
    # same rows supplied as pilot-1 C through /target-eval → identical judgment (logic and thresholds unchanged)
    from app.core.clear_rate import experiment as X
    from app.core.clear_rate.service import random_layout
    gm, cond = finalize_game_conditions(LJ, L)
    c = BotMeasurement.from_dict({**mdl.bot_cache[cond_hash(gm, cond)], "seed_band": "C"})
    ref = X.evaluate_user_expected(mdl, gm, cond, L, c, 0.9, random_layout=random_layout(gm))["verdict"]
    assert (v["verdict"], v["p_in_band"]) == (ref["verdict"], ref["p_in_band"])


def test_evaluate_refuses_changed_map_or_placement(tmp_path, mdl):
    mgr, _ = make(tmp_path, mdl)
    jid = submit(mgr)["job"]["job_id"]
    mgr.run_pending()
    lj2 = json.loads(json.dumps(LJ))
    lj2["randSeed"] = int(lj2.get("randSeed") or 0) + 7
    assert mgr.plan(lj2, L)["cond_hash"] != mgr.get(jid)["cond_hash"]   # randSeed is a GAME_FIELDS member
    for kw in ({"level_json": lj2, "placement_level": L}, {"level_json": LJ, "placement_level": 480}):
        with pytest.raises(CF.ConfirmRejected) as e:
            mgr.evaluate(job_id=jid, target=0.9, **kw)
        assert e.value.code == "MEASUREMENT_INVALIDATED"


def test_training_cache_is_never_accepted_as_c(tmp_path, mdl):
    """A seed11M (training cache) record in the store, even under a done job, is not a C measurement."""
    mgr, _ = make(tmp_path, mdl)
    jid = submit(mgr)["job"]["job_id"]
    mgr.run_pending()
    ref = mgr.get(jid)["measurement_ref"]
    rec = mgr.store.data[ref]
    rec["meta"].pop("measurement_kind")                 # e.g. a record written by a search / training path
    with pytest.raises(CF.ConfirmRejected) as e:
        mgr.evaluate(job_id=jid, level_json=LJ, placement_level=L, target=0.9)
    assert e.value.code == "MEASUREMENT_MISSING"
    rec["meta"]["measurement_kind"] = "confirm"
    rec["measurement"]["seed_band"] = "seed11M"
    with pytest.raises(CF.ConfirmRejected) as e:
        mgr.evaluate(job_id=jid, level_json=LJ, placement_level=L, target=0.9)
    assert e.value.code == "NOT_CONFIRM"


# ── cancel / failure / partial / restart ──────────────────────────────────────────────────────────────────────
def test_cancel_queued_job(tmp_path, mdl):
    mgr, runner = make(tmp_path, mdl)
    jid = submit(mgr)["job"]["job_id"]
    assert mgr.cancel(jid)["status"] == CF.CANCELLED
    mgr.run_pending()
    assert runner.calls == 0 and mgr.get(jid)["status"] == CF.CANCELLED
    with pytest.raises(CF.ConfirmRejected) as e:
        mgr.evaluate(job_id=jid, level_json=LJ, placement_level=L, target=0.9)
    assert e.value.code == "JOB_NOT_DONE"


def test_cancel_running_job_stores_nothing(tmp_path, mdl):
    holder = {}
    runner = FakeRunner(mdl, on_call=lambda: holder["mgr"].cancel(holder["jid"]))
    mgr, _ = make(tmp_path, mdl, runner=runner)
    holder.update(mgr=mgr, jid=submit(mgr)["job"]["job_id"])
    mgr.run_pending()
    job = mgr.get(holder["jid"])
    assert job["status"] == CF.CANCELLED and job["cancel_requested"] and job["measurement_ref"] is None
    assert mgr.store.data == {}


def test_failure_is_recorded_and_not_retried(tmp_path, mdl):
    mgr, runner = make(tmp_path, mdl, runner=FakeRunner(mdl, fail=RuntimeError("boom")))
    jid = submit(mgr)["job"]["job_id"]
    mgr.run_pending()
    job = mgr.get(jid)
    assert job["status"] == CF.FAILED and "boom" in job["error"] and runner.calls == 1
    assert mgr.store.data == {} and len(mgr.jobs.jobs) == 1          # no automatic retry / no other map picked


def test_partial_measurement_is_not_a_completed_c(tmp_path, mdl):
    mgr, _ = make(tmp_path, mdl, runner=FakeRunner(mdl, games_scale=0.5))
    jid = submit(mgr)["job"]["job_id"]
    mgr.run_pending()
    job = mgr.get(jid)
    assert job["status"] == CF.FAILED and "games" in job["error"] and mgr.store.data == {}


def test_restart_marks_active_jobs_interrupted(tmp_path, mdl):
    mgr, _ = make(tmp_path, mdl)
    jid = submit(mgr)["job"]["job_id"]
    mgr.jobs.update(jid, status=CF.RUNNING, games_done=128)
    again, _ = make(tmp_path, mdl)
    job = again.get(jid)
    assert job["status"] == CF.FAILED and job["interrupted"] and job["games_done"] == 128
    assert again.submit(level_json=LJ, placement_level=L, expected_cond_hash=job["cond_hash"])["created"]


def test_measure_should_stop_between_rows(mdl, monkeypatch):
    gm, cond = finalize_game_conditions(LJ, L)
    monkeypatch.setitem(M.PROTOCOLS, "tiny_test2", ((0.55, 0.85), 2))
    expo = M.bot_exposure(mdl.model["position"], L)
    seen = []
    with pytest.raises(M.MeasurementCancelled):
        M.measure(gm, cond, exposure=expo, protocol="tiny_test2", seed_band="CV",
                  should_stop=lambda: len(seen) >= 1, on_row=seen.append)
    assert seen == [2]


# ── API ───────────────────────────────────────────────────────────────────────────────────────────────────────
@pytest.fixture()
def api(tmp_path, mdl, monkeypatch):
    mgr, runner = make(tmp_path, mdl)
    monkeypatch.setattr(CF, "_MANAGER", mgr)
    return TestClient(app), mgr, runner


def test_api_plan_submit_query_evaluate(api):
    client, mgr, runner = api
    plan = client.post("/api/clear-rate/verify/plan", json={"items": [{"level_json": LJ, "placement_level": L,
                                                                       "map_id": "b:237"}]}).json()
    assert plan["seed_band"] == "CV" and plan["max_concurrent"] == 2 and "실유저" in plan["note"]
    it = plan["items"][0]
    body = {"level_json": LJ, "placement_level": L, "map_id": "b:237", "target_mode": "user_expected",
            "expected_cond_hash": it["cond_hash"]}
    r = client.post("/api/clear-rate/verify/jobs", json=body).json()
    jid = r["job"]["job_id"]
    assert r["created"] and client.post("/api/clear-rate/verify/jobs", json=body).json()["reused"] == "active"
    q = client.post("/api/clear-rate/verify/jobs/query", json={"job_ids": [jid, "nope"]}).json()["jobs"]
    assert q[jid]["status"] == "queued" and q["nope"] is None
    assert client.post("/api/clear-rate/verify/evaluate",
                       json={"job_id": jid, "target": 0.9, "level_json": LJ, "placement_level": L}).status_code == 409
    mgr.run_pending()
    e = client.post("/api/clear-rate/verify/evaluate",
                    json={"job_id": jid, "target": 0.9, "level_json": LJ, "placement_level": L}).json()
    assert e["measurement_kind"] == "confirm" and e["user_expected"]["verdict"]["bot_seed_confirmed"] is True
    assert runner.calls == 1


@pytest.mark.parametrize("mode", [None, "bot_virtual"])
def test_api_submit_mode_a_only(api, mode):
    client, _, runner = api
    body = {"level_json": LJ, "placement_level": L, "expected_cond_hash": "x"}
    if mode:
        body["target_mode"] = mode
    assert client.post("/api/clear-rate/verify/jobs", json=body).status_code == 422 and runner.calls == 0


def test_api_target_check_separates_entry_from_judgeability(api):
    client, _, _ = api
    r = client.post("/api/clear-rate/verify/target-check", json={"items": [
        {"placement_level": 157, "target": 0.9}, {"placement_level": 157, "target": 0.8},
        {"placement_level": 600, "target": 0.9}]}).json()["items"]
    assert r[0]["judgeable"] is True
    assert r[1]["judgeable"] is False and "LOW_CONFIDENCE" in r[1]["codes"] and r[1]["target"] == 0.8  # not raised
    assert "LEVEL_OUT_OF_RANGE" in r[2]["codes"]


def test_api_cancel_unknown_job(api):
    client, _, _ = api
    assert client.post("/api/clear-rate/verify/jobs/nope/cancel").status_code == 404
