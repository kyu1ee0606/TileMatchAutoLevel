"""허들 구간 추천 API (/api/hurdle-rec) — 게임 레포 range_rec/run.sh 실행·상태·결과 조회.

정의: app.core.hurdle_range_rec. 게임부스트 접속·쓰기 없음. 게임 레포는 읽기만(맵툴 실행 출력은 backend/data/hurdle_rec/).
"""
from __future__ import annotations

from typing import List, Optional

from fastapi import APIRouter, HTTPException
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel, Field

from ...core import hurdle_range_rec as R

router = APIRouter(prefix="/api/hurdle-rec", tags=["hurdle-rec"])


class RunRequest(BaseModel):
    since: Optional[str] = Field(default=None, description="YYYY-MM-DD (Event Time ≥)")
    until: Optional[str] = Field(default=None, description="YYYY-MM-DD (Event Time <)")
    versions: Optional[List[str]] = Field(default=None, description="비우면 도구 config.json versions")
    keep_dda_var: bool = False
    memo: str = ""


@router.get("/info")
def info():
    return {**R.tool_info(), "running": R.running_job()}


@router.post("/run")
def run(req: RunRequest):
    try:
        return R.start(req.since or None, req.until or None, req.versions, req.keep_dda_var, req.memo)
    except RuntimeError as e:
        raise HTTPException(status_code=409, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.get("/status")
def status(job_id: Optional[str] = None):
    """job_id 없으면 실행 중 작업(없으면 가장 최근 작업)."""
    if job_id:
        v = R.job_view(job_id)
        if not v:
            raise HTTPException(status_code=404, detail="작업 없음")
        return v
    cur = R.running_job()
    if cur:
        return cur
    jobs = R._jobs()
    return R.job_view(jobs[-1]["id"]) if jobs else {"status": "idle"}


@router.post("/stop/{job_id}")
def stop(job_id: str):
    try:
        return R.stop(job_id)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="작업 없음")


@router.get("/runs")
def runs():
    return {"runs": R.list_runs()}


@router.get("/history")
def history(limit: int = 100):
    return {"history": R.history(limit)}


@router.get("/result")
def result(run_id: Optional[str] = None):
    """run_id = 'maptool:<id>' | 'game:<폴더>' | 'latest'(기본)."""
    r = R.get_result(run_id)
    if not r:
        raise HTTPException(status_code=404, detail="결과 없음")
    return r


@router.get("/report", response_class=PlainTextResponse)
def report(run_id: Optional[str] = None):
    t = R.get_report(run_id)
    if t is None:
        raise HTTPException(status_code=404, detail="REPORT.md 없음")
    return t
