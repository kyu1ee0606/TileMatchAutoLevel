"""라이브 levels 보드 전체 백업 · 복원(미리보기 → 확인 → 실행) API (/api/live-backup).

정의·근거: app.core.live_backup. 서버 접근:
  - 백업 시작: 보드 전체 읽기 1회(쓰기 없음)
  - 복원 미리보기: 현재 서버 보드 읽기 1회(쓰기 없음) — current_backup 을 주면 서버 대신 그 백업과 비교(서버 호출 없음)
  - 복원 실행: 사람이 미리보기 확인 + confirm_text="복원" 후에만. 행별 update(new=0) — 이 API 의 유일한 쓰기.
삭제·수정 API 없음.
"""
from __future__ import annotations

import asyncio
import os
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from ...clients.gboost import GBoostClient
from ...core import dda_seed_catalog as _dda
from ...core import dda_seed_ledger as L
from ...core import live_backup as B
from ..deps import get_gboost

router = APIRouter(prefix="/api/live-backup", tags=["live-backup"])


class BackupStartRequest(BaseModel):
    board: str = _dda.DDA_BOARD_ID
    memo: str = ""
    wait: bool = False


class ImportFileRequest(BaseModel):
    path: str
    memo: str = ""


class BaseRef(BaseModel):
    type: str = Field(..., description="backup | snapshot")
    id: str


class PreviewRequest(BaseModel):
    base: BaseRef
    scope_snapshot: Optional[str] = Field(default=None, description="이 장부 업로드 스냅샷이 덮어쓴 행·열만 되돌림")
    q: str = Field(default="", description="레벨 필터(5, 10-20, i3 …)")
    columns: List[str] = Field(default_factory=list, description="이 열만(비우면 전체)")
    current_backup: Optional[str] = Field(default=None, description="현재 서버 대신 비교할 백업 id(서버 호출 없음)")


class ExecuteRequest(BaseModel):
    plan_id: str
    plan_digest: str
    confirm_text: str
    allow_unverified: bool = False
    sleep_ms: int = Field(default=50, ge=0, le=5000)
    wait: bool = False


def _bad(e: Exception) -> HTTPException:
    return HTTPException(status_code=404 if "no such" in str(e) else 400, detail=str(e))


@router.get("/status")
async def status():
    return {**B.backup_status(), "dir": B.backup_dir(), "staleHours": B.STALE_HOURS}


@router.get("/backups")
async def list_backups():
    return {"backups": B.list_backups(), "dir": B.backup_dir()}


@router.get("/backups/{bid}")
async def get_backup(bid: str):
    try:
        doc = B.load_backup(bid)
    except B.BackupError as e:
        raise _bad(e)
    return {k: v for k, v in doc.items() if k not in ("raw", "rows")}


@router.post("/backups/start")
async def start_backup(req: BackupStartRequest, client: GBoostClient = Depends(get_gboost)):
    """보드 전체 읽기(쓰기 없음) → 파일 저장. wait=False 면 작업 id 반환(진행률은 /jobs/{id})."""
    if not client.is_configured:
        raise HTTPException(status_code=503, detail="GBoost client not configured")
    job = B.new_job("backup")

    async def run():
        try:
            job["result"] = await B.take_backup(client, req.board, req.memo,
                                                progress=lambda ph: job.__setitem__("phase", ph))
            job["status"], job["phase"] = "done", "done"
        except Exception as e:  # noqa: BLE001
            job["status"], job["error"] = "failed", str(e)

    if req.wait:
        await run()
    else:
        asyncio.get_running_loop().create_task(run())
    return B.job_view(job["id"])


@router.post("/backups/import-file")
async def import_file(req: ImportFileRequest):
    """예전 readback 원문 파일(real_array {__keys,__vals})을 백업으로 등록. 서버 호출 없음. stale 경고 대상."""
    p = os.path.expanduser(req.path)
    if not p.endswith(".json") or not os.path.isfile(p):
        raise HTTPException(status_code=400, detail=f"json 파일이 아님/없음: {p}")
    try:
        return B.import_raw_file(p, req.memo)
    except (B.BackupError, ValueError) as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/jobs/{jid}")
async def job(jid: str):
    j = B.job_view(jid)
    if not j:
        raise HTTPException(status_code=404, detail="no such job (서버 재시작 시 사라짐)")
    return j


@router.post("/restore/preview")
async def restore_preview(req: PreviewRequest, client: GBoostClient = Depends(get_gboost)):
    """1단계: 기준(백업/업로드 스냅샷 직전 값)으로 되돌리는 payload 계획 + 저장. 쓰기 없음."""
    try:
        if req.base.type == "backup":
            base_rows, meta, scope = B.base_from_backup(req.base.id)
        elif req.base.type == "snapshot":
            base_rows, meta, scope = B.base_from_snapshot(req.base.id)
        else:
            raise B.BackupError("base.type must be backup|snapshot")
        if req.scope_snapshot:
            scope = B.scope_from_snapshot(req.scope_snapshot)
        if req.current_backup:
            cur_rows = B.load_backup(req.current_backup)["rows"]
            cur_src = {"type": "backup", "id": req.current_backup}
        else:
            if not client.is_configured:
                raise HTTPException(status_code=503, detail="GBoost client not configured (current_backup 으로 오프라인 비교 가능)")
            try:
                got = await client.load_board_rows(_dda.DDA_BOARD_ID)
            except Exception as e:  # noqa: BLE001
                raise HTTPException(status_code=502, detail=f"현재 서버 읽기 실패: {e}")
            cur_rows = got.get("rows") or {}
            cur_src = {"type": "server", "rawSha256": got.get("raw_sha256")}
    except (B.BackupError, L.LedgerError) as e:
        raise _bad(e)
    ids = L.parse_level_query(req.q)
    plan = B.build_plan(base_rows, cur_rows, scope=scope, ids=ids, columns=req.columns or None)
    meta_all = {"board": _dda.DDA_BOARD_ID, "base": meta, "currentSource": cur_src,
                "scope": {"snapshot": req.scope_snapshot or (req.base.id if req.base.type == "snapshot" else None),
                          "q": req.q, "columns": req.columns},
                "warnings": B.base_warnings(meta)}
    doc = B.save_plan(plan, meta_all)
    return B.preview_summary(doc)


@router.get("/restore/plans/{pid}")
async def get_plan(pid: str, sample: int = 50):
    try:
        return B.preview_summary(B.load_plan(pid), sample=sample)
    except B.BackupError as e:
        raise _bad(e)


@router.post("/restore/execute")
async def restore_execute(req: ExecuteRequest, client: GBoostClient = Depends(get_gboost)):
    """2단계(사람만): 미리보기 plan_id·planDigest·confirm_text="복원" 확인 후 행별 update(new=0)."""
    try:
        doc = B.load_plan(req.plan_id)
    except B.BackupError as e:
        raise _bad(e)
    if req.confirm_text != B.CONFIRM_TEXT or req.plan_digest != doc["planDigest"]:
        raise HTTPException(status_code=400, detail="확인 문구 또는 planDigest 불일치 — 미리보기를 다시 확인하세요")
    if not client.is_configured:
        raise HTTPException(status_code=503, detail="GBoost client not configured")
    job = B.new_job("restore")
    job["total"] = doc["plan"]["rowCount"]

    def prog(i, n):
        job["current"], job["total"], job["phase"] = i, n, "writing"

    async def run():
        try:
            job["result"] = await B.execute_plan(client, req.plan_id, req.plan_digest, req.confirm_text,
                                                 allow_unverified=req.allow_unverified, sleep_s=req.sleep_ms / 1000,
                                                 progress=prog)
            job["status"], job["phase"] = "done", "done"
        except Exception as e:  # noqa: BLE001
            job["status"], job["error"] = "failed", str(e)

    if req.wait:
        await run()
    else:
        asyncio.get_running_loop().create_task(run())
    return B.job_view(job["id"])
