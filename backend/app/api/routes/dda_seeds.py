"""
DDA 시드 갱신 사전검사 / 익스포트 미리보기 API (문서 47).

둘 다 읽기 전용 — 저장·GameBoost 호출 없음. 저장은 프론트가 사용자 확인 후 맵에디터 내부(IndexedDB)에만 한다.
"""
from collections import Counter
from typing import Any, Dict, List

from fastapi import APIRouter
from pydantic import BaseModel, Field

from ...core import dda_seed_catalog as cat
from .gboost import _convert_to_townpop_format

router = APIRouter(prefix="/api/dda-seeds", tags=["dda-seeds"])


class PreviewLevel(BaseModel):
    level_number: int
    level_json: Dict[str, Any]


class PreviewRequest(BaseModel):
    levels: List[PreviewLevel] = Field(default_factory=list)


class ExportPreviewLevel(BaseModel):
    target_id: str
    level_json: Dict[str, Any]


class ExportPreviewRequest(BaseModel):
    board_id: str
    levels: List[ExportPreviewLevel] = Field(default_factory=list)


def _townpop(level_json: Dict[str, Any]) -> Dict[str, Any]:
    return _convert_to_townpop_format(dict(level_json))


@router.get("/catalog")
async def get_catalog_info() -> Dict[str, Any]:
    return cat.catalog_info()


@router.post("/preview")
async def preview(req: PreviewRequest) -> Dict[str, Any]:
    info = cat.catalog_info()
    results = []
    for lv in req.levels:
        try:
            results.append(cat.plan_level(lv.level_number, lv.level_json, _townpop(lv.level_json)))
        except Exception as e:  # 레벨 단위 실패는 목록으로 보고(전체 중단 없음)
            results.append({"level": lv.level_number, "action": "skip", "reason": "check_error", "detail": str(e)})
    return {
        "catalog": info,
        "summary": {
            "total": len(results),
            "byAction": dict(Counter(r["action"] for r in results)),
            "byReason": dict(Counter(f'{r["action"]}:{r["reason"]}' for r in results)),
        },
        "results": results,
    }


@router.post("/export-preview")
async def export_preview(req: ExportPreviewRequest) -> Dict[str, Any]:
    out = []
    for lv in req.levels:
        try:
            f = cat.export_fields(req.board_id, lv.target_id, lv.level_json, _townpop(lv.level_json))
        except Exception as e:
            f = {"ddaEasySeeds": "", "ddaHardSeeds": "", "reason": f"check_error:{e}"}
        if f is not None:
            out.append({"target_id": lv.target_id, **f})
    return {"board_id": req.board_id, "applies": req.board_id == cat.DDA_BOARD_ID, "results": out}
