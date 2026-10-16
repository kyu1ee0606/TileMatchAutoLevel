"""Real-user clear-rate prediction endpoint — parallel display next to the legacy predicted_clear_rate (docs 31 / 33).

Display only: returns no pass/fail verdict (clear_rate.judge exists for the later selection path but is not used
here), and the legacy predicted_clear_rate / verification / upload values are untouched.
"""
from fastapi import APIRouter, HTTPException

from ...core.clear_rate import predict_editor_level
from ...models.schemas import ClearRatePredictRequest, ClearRatePredictResponse

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
