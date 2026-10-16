"""New real-user clear-rate prediction — parallel display next to the legacy predicted_clear_rate (docs 31 / 33).

Display only: no pass/fail verdict, and the legacy predicted_clear_rate / verification / upload values are untouched.
"""
from fastapi import APIRouter, HTTPException

from ...core.clear_rate import predict
from ...models.schemas import ClearRatePredictRequest, ClearRatePredictResponse

router = APIRouter(prefix="/api/clear-rate", tags=["clear-rate"])


@router.post("/predict", response_model=ClearRatePredictResponse)
def predict_clear_rate(req: ClearRatePredictRequest) -> ClearRatePredictResponse:
    lj = req.level_json
    if not isinstance(lj.get("layer"), (int, str)) or not any(k.startswith("layer_") for k in lj):
        raise HTTPException(status_code=422, detail="level_json must contain 'layer' and 'layer_N' entries")
    res = predict(lj, req.placement_level,
                  target=req.target.value if req.target else None,
                  bot_measurement=req.bot_measurement.model_dump() if req.bot_measurement else None)
    return ClearRatePredictResponse(**res)
