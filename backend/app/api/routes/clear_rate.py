"""Real-user clear-rate prediction endpoint — parallel display next to the legacy predicted_clear_rate (docs 31 / 33).

Display only: returns no pass/fail verdict (clear_rate.select.verdict exists for the later selection path but is not used
here), and the legacy predicted_clear_rate / verification / upload values are untouched.
"""
from fastapi import APIRouter, HTTPException

from ...core.clear_rate import predict_editor_level
from ...models.schemas import (ClearRatePredictRequest, ClearRatePredictResponse, ClearRateTargetEvalRequest,
                               ClearRateTargetEvalResponse)

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
        out = X.evaluate_user_expected(load_model(), game_map, cond, req.placement_level, c or s, req.target,
                                       random_layout=random_layout(game_map))
        return ClearRateTargetEvalResponse(target_mode=mode, user_expected=out)
    return ClearRateTargetEvalResponse(target_mode=mode,
                                       bot_virtual=X.evaluate_bot_virtual(game_map, cond, s, c, req.target))
