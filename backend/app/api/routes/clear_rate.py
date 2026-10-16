"""Real-user clear-rate prediction endpoint — parallel display next to the legacy predicted_clear_rate (docs 31 / 33).

Display only: returns no pass/fail verdict (clear_rate.select.verdict exists for the later selection path but is not used
here), and the legacy predicted_clear_rate / verification / upload values are untouched.
"""
from fastapi import APIRouter, HTTPException

from ...core.clear_rate import predict_editor_level
from ...models.schemas import (ClearRatePredictRequest, ClearRatePredictResponse, ClearRateTargetCheckRequest,
                               ClearRateTargetCheckResponse, ClearRateTargetEvalRequest, ClearRateTargetEvalResponse,
                               ClearRateVerifyEvaluateRequest, ClearRateVerifyEvaluateResponse,
                               ClearRateVerifyJobsQuery, ClearRateVerifyJobsResponse, ClearRateVerifyPlanRequest,
                               ClearRateVerifyPlanResponse, ClearRateVerifySubmitRequest,
                               ClearRateVerifySubmitResponse)

router = APIRouter(prefix="/api/clear-rate", tags=["clear-rate"])


@router.post("/predict", response_model=ClearRatePredictResponse)
def predict_clear_rate(req: ClearRatePredictRequest) -> ClearRatePredictResponse:
    lj = req.level_json
    if not isinstance(lj.get("layer"), (int, str)) or not any(k.startswith("layer_") for k in lj):
        raise HTTPException(status_code=422, detail="level_json must contain 'layer' and 'layer_N' entries")
    pred = predict_editor_level(lj, req.placement_level,
                                bot_measurement=req.bot_measurement.model_dump() if req.bot_measurement else None,
                                upload_opts=req.upload_opts.model_dump() if req.upload_opts else None)
    return ClearRatePredictResponse(**pred.to_dict())


@router.post("/target-eval", response_model=ClearRateTargetEvalResponse)
def target_eval(req: ClearRateTargetEvalRequest) -> ClearRateTargetEvalResponse:
    """Experimental two-mode path (doc 35 §9): target_mode is required (no default), computes from the supplied
    measurements only (no bot run). Not called by generation, verification or upload; A never falls back to B."""
    from ...core.clear_rate import experiment as X
    from ...core.clear_rate import finalize_game_conditions, load_model
    from ...core.clear_rate.predict import BotMeasurement
    from ...core.clear_rate.service import random_layout
    lj = req.level_json
    if not isinstance(lj.get("layer"), (int, str)) or not any(k.startswith("layer_") for k in lj):
        raise HTTPException(status_code=422, detail="level_json must contain 'layer' and 'layer_N' entries")
    mode = X.require_mode(req.target_mode)
    game_map, cond = finalize_game_conditions(lj, req.placement_level,
                                              req.upload_opts.model_dump() if req.upload_opts else None)
    s = BotMeasurement.from_dict(req.bot_measurement_search.model_dump()) if req.bot_measurement_search else None
    c = BotMeasurement.from_dict(req.bot_measurement_confirm.model_dump()) if req.bot_measurement_confirm else None
    if mode == X.USER_EXPECTED:
        if req.placement_level is None:
            raise HTTPException(status_code=422, detail="user_expected needs placement_level")
        mdl = load_model()
        meas = c or s
        if meas is None and req.use_cached_measurement:
            # Opt-in (validation tab, doc 38): same cache lookup as /predict. Cache band is not a confirm band,
            # so the verdict stays INSUFFICIENT_EVIDENCE (SELECTION_UNCONFIRMED) — judgment logic unchanged.
            from ...core.clear_rate import cond_hash
            hit = mdl.bot_cache.get(cond_hash(game_map, cond))
            meas = BotMeasurement.from_dict(hit, source="cache") if hit else None
        out = X.evaluate_user_expected(mdl, game_map, cond, req.placement_level, meas, req.target,
                                       random_layout=random_layout(game_map))
        return ClearRateTargetEvalResponse(target_mode=mode, user_expected=out)
    return ClearRateTargetEvalResponse(target_mode=mode,
                                       bot_virtual=X.evaluate_bot_virtual(game_map, cond, s, c, req.target))


# ── Validation tab C confirmation (doc 38 §10) — explicit user action only, mode A only ─────────────────────────
C_NOTE = "C 측정은 봇 측정 재현성 확인이며 실유저 클리어율 독립 검증이 아님"


def _check_level_json(lj):
    if not isinstance(lj.get("layer"), (int, str)) or not any(k.startswith("layer_") for k in lj):
        raise HTTPException(status_code=422, detail="level_json must contain 'layer' and 'layer_N' entries")


def _rejected(e):
    status = 422 if e.code in ("UNSUPPORTED_INPUT",) else 409
    return HTTPException(status_code=status, detail={"code": e.code, "detail": e.detail})


@router.post("/verify/plan", response_model=ClearRateVerifyPlanResponse)
def verify_plan(req: ClearRateVerifyPlanRequest) -> ClearRateVerifyPlanResponse:
    """Fix map + final conditions (cond_hash) and show planned games / existing jobs. Runs no bot."""
    from ...core.clear_rate import confirm as CF
    mgr, items = CF.manager(), []
    for it in req.items:
        _check_level_json(it.level_json)
        try:
            p = mgr.plan(it.level_json, it.placement_level, it.upload_opts.model_dump() if it.upload_opts else None)
            items.append({"map_id": it.map_id, "placement_level": it.placement_level, **p})
        except Exception as e:  # noqa: BLE001 — per-map error, other maps still planned
            items.append({"map_id": it.map_id, "placement_level": it.placement_level,
                          "error": f"{type(e).__name__}: {e}"})
    return ClearRateVerifyPlanResponse(items=items, seed_band=CF.CONFIRM_BAND, max_concurrent=CF.MAX_CONCURRENT,
                                       judge_version=CF.judge_version(), note=C_NOTE)


@router.post("/verify/jobs", response_model=ClearRateVerifySubmitResponse)
def verify_submit(req: ClearRateVerifySubmitRequest) -> ClearRateVerifySubmitResponse:
    from ...core.clear_rate import confirm as CF
    _check_level_json(req.level_json)
    try:
        out = CF.manager().submit(level_json=req.level_json, placement_level=req.placement_level,
                                  expected_cond_hash=req.expected_cond_hash, map_id=req.map_id,
                                  batch_id=req.batch_id,
                                  upload_opts=req.upload_opts.model_dump() if req.upload_opts else None)
    except CF.ConfirmRejected as e:
        raise _rejected(e)
    except (KeyError, ValueError, TypeError) as e:   # malformed level → no job created
        raise HTTPException(status_code=422, detail=f"{type(e).__name__}: {e}")
    return ClearRateVerifySubmitResponse(**out)


@router.post("/verify/jobs/query", response_model=ClearRateVerifyJobsResponse)
def verify_jobs(req: ClearRateVerifyJobsQuery) -> ClearRateVerifyJobsResponse:
    from ...core.clear_rate import confirm as CF
    mgr = CF.manager()
    return ClearRateVerifyJobsResponse(jobs={j: mgr.get(j) for j in req.job_ids})


@router.get("/verify/jobs/{job_id}")
def verify_job(job_id: str):
    from ...core.clear_rate import confirm as CF
    job = CF.manager().get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="unknown job")
    return job


@router.post("/verify/jobs/{job_id}/cancel")
def verify_cancel(job_id: str):
    from ...core.clear_rate import confirm as CF
    try:
        return CF.manager().cancel(job_id)
    except KeyError:
        raise HTTPException(status_code=404, detail="unknown job")


@router.post("/verify/evaluate", response_model=ClearRateVerifyEvaluateResponse)
def verify_evaluate(req: ClearRateVerifyEvaluateRequest) -> ClearRateVerifyEvaluateResponse:
    """Verdict from a completed validation-tab C measurement (server-side record; rows are never taken from the
    request, so a training / exploration measurement cannot be passed off as C)."""
    from ...core.clear_rate import confirm as CF
    _check_level_json(req.level_json)
    try:
        out = CF.manager().evaluate(job_id=req.job_id, level_json=req.level_json,
                                    placement_level=req.placement_level, target=req.target,
                                    upload_opts=req.upload_opts.model_dump() if req.upload_opts else None)
    except KeyError:
        raise HTTPException(status_code=404, detail="unknown job")
    except CF.ConfirmRejected as e:
        raise _rejected(e)
    return ClearRateVerifyEvaluateResponse(target_mode="user_expected", measurement_kind="confirm", **out)


@router.post("/verify/target-check", response_model=ClearRateTargetCheckResponse)
def verify_target_check(req: ClearRateTargetCheckRequest) -> ClearRateTargetCheckResponse:
    """'Target can be entered' vs 'the active model can judge it': user_expected_precheck per (level, target).
    Reports only — never changes the target and never switches to mode B."""
    from ...core.clear_rate import experiment as X
    from ...core.clear_rate import load_model
    mdl = load_model()
    items = []
    for it in req.items:
        codes = X.user_expected_precheck(mdl, it.target, it.placement_level)
        items.append({"placement_level": it.placement_level, "target": it.target, "codes": codes,
                      "judgeable": not codes})
    return ClearRateTargetCheckResponse(model_version=mdl.version, items=items)
