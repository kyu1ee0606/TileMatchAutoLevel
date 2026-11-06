"""DDA 시드 이력 장부 API (/api/dda-ledger) — 스냅샷 목록·세션(업로드 1회) 열기/마감·비교·타임라인·기준점.

저장·분류 정의: app.core.dda_seed_ledger. 수정·삭제 API 는 없다(추가만).
서버 접근: 마감 시 재조회(읽기)·기준점 from-server(읽기)만. 쓰기 없음.
"""
from __future__ import annotations

import os
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import Response
from pydantic import BaseModel, Field

from ...clients.gboost import GBoostClient
from ...core import dda_seed_catalog as _dda
from ...core import dda_seed_ledger as L
from ...core import infinity_relabel as _inf
from ..deps import get_gboost

router = APIRouter(prefix="/api/dda-ledger", tags=["dda-ledger"])

INFINITY_OFFSET = 500


class SessionOpenRequest(BaseModel):
    board: str = _dda.DDA_BOARD_ID
    memo: str = ""
    tag: str = ""
    batch_id: str = ""
    batch_name: str = ""
    source: str = "export_tab"
    options: Dict[str, Any] = Field(default_factory=dict)


class SessionNoteRequest(BaseModel):
    note: Dict[str, Any] = Field(default_factory=dict)


class SessionFinalizeRequest(BaseModel):
    client_counts: Dict[str, Any] = Field(default_factory=dict)
    readback: bool = True


class BaselineFileRequest(BaseModel):
    path: str
    memo: str = ""
    tag: str = "v0"


class BaselineServerRequest(BaseModel):
    memo: str = ""
    tag: str = ""


class BatchLevel(BaseModel):
    level_number: int
    level_json: Dict[str, Any]


class BatchPlanRequest(BaseModel):
    base: Optional[str] = Field(default=None, description="비교 기준 스냅샷 id(없으면 최신 비-dryrun 스냅샷)")
    batch_id: str = ""
    batch_name: str = ""
    levels: List[BatchLevel]
    infinity_mode: str = Field(default="append", description="off | append | only")
    infinity_relabel: bool = True
    infinity_source_start: int = 501
    infinity_source_end: int = 1530
    persist: bool = Field(default=False, description="True 면 결과를 dryrun 스냅샷으로 저장(목록에 '가상' 표시)")
    memo: str = ""
    tag: str = ""
    q: str = ""
    only_changed: bool = True
    klass: str = ""


def _err(e: Exception) -> HTTPException:
    return HTTPException(status_code=404 if "no such" in str(e) else 400, detail=str(e))


@router.get("/lock-model")
async def lock_model():
    return L.LOCK_MODEL


@router.get("/snapshots")
async def list_snapshots(include_dryrun: bool = True):
    return {"snapshots": L.list_snapshots(include_dryrun=include_dryrun), "dir": L.ledger_dir(),
            "lockModel": L.LOCK_MODEL}


@router.get("/snapshots/{sid}")
async def get_snapshot(sid: str, rows: bool = False):
    try:
        doc = L.load(sid)
    except L.LedgerError as e:
        raise _err(e)
    out = L.summary(doc)
    if rows:
        out["rows"] = doc.get("rows")
        out["notes"] = doc.get("notes")
        out["options"] = doc.get("options")
    return out


@router.post("/sessions")
async def open_session(req: SessionOpenRequest):
    try:
        return L.open_session(kind="upload", board=req.board, memo=req.memo, tag=req.tag, batch_id=req.batch_id,
                              batch_name=req.batch_name, source=req.source, options=req.options)
    except L.LedgerError as e:
        raise _err(e)


@router.post("/sessions/{sid}/notes")
async def add_note(sid: str, req: SessionNoteRequest):
    try:
        L.append_note(sid, req.note)
    except L.LedgerError as e:
        raise _err(e)
    return {"ok": True}


@router.post("/sessions/{sid}/finalize")
async def finalize_session(sid: str, req: SessionFinalizeRequest, client: GBoostClient = Depends(get_gboost)):
    """마감: (선택) 업로드 후 서버 재조회(읽기만) → 스냅샷 파일 생성. 이미 마감된 세션은 400."""
    try:
        L._check_id(sid)
        if L._is_closed(sid):
            raise L.LedgerError(f"session already finalized: {sid}")
        rb = await L.readback_session(client, sid) if req.readback else {"ok": False, "skipped": True}
        s = L.finalize(sid, req.client_counts)
    except L.LedgerError as e:
        raise _err(e)
    return {**s, "readbackResult": rb}


def _diff_response(res: Dict[str, Any], fmt: str, name: str):
    if fmt == "csv":
        return Response(content=L.diff_csv(res["items"]).encode("utf-8-sig"), media_type="text/csv; charset=utf-8",
                        headers={"Content-Disposition": f'attachment; filename="{name}.csv"'})
    return res


@router.get("/diff")
async def diff(a: str, b: str, q: str = "", only_changed: bool = True, klass: str = "",
               format: str = Query(default="json", pattern="^(json|csv)$"), limit: int = 0):
    try:
        da, db = L.load(a), L.load(b)
    except L.LedgerError as e:
        raise _err(e)
    res = L.diff_snapshots(da, db, q=q, only_changed=only_changed, klass=klass)
    if format == "json" and limit > 0:
        res["truncated"] = len(res["items"]) > limit
        res["items"] = res["items"][:limit]
    return _diff_response(res, format, f"dda_seed_diff_{a}_vs_{b}")


@router.get("/levels/{row_id}/timeline")
async def level_timeline(row_id: str, include_dryrun: bool = False):
    return L.timeline(row_id, include_dryrun=include_dryrun)


@router.post("/baseline/from-file")
async def baseline_from_file(req: BaselineFileRequest):
    """서버 원본 파일(real_array load 원문 {__keys,__vals})로 기준점 스냅샷 생성. 서버 호출 없음."""
    p = os.path.expanduser(req.path)
    if not p.endswith(".json") or not os.path.isfile(p):
        raise HTTPException(status_code=400, detail=f"json 파일이 아님/없음: {p}")
    try:
        return L.baseline_from_raw_file(p, memo=req.memo, tag=req.tag)
    except (L.LedgerError, ValueError, KeyError) as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/baseline/from-server")
async def baseline_from_server(req: BaselineServerRequest, client: GBoostClient = Depends(get_gboost)):
    """levels 보드 전체를 읽기만 해서 기준점 스냅샷 생성(쓰기 없음)."""
    if not client.is_configured:
        raise HTTPException(status_code=503, detail="GBoost client not configured")
    try:
        board = await client.load_board_rows(_dda.DDA_BOARD_ID)
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=f"서버 조회 실패: {e}")
    rows = L.rows_from_server_board(board.get("rows") or {})
    return L.create_snapshot(kind="baseline", rows=rows, memo=req.memo or "기준점 — 서버 읽기", tag=req.tag,
                             source="server_read", options={"rawSha256": board.get("raw_sha256"),
                                                            "rawBytes": board.get("raw_bytes")})


# ── 배치 기준 가상 스냅샷(계획) ─────────────────────────────────────────────────────
def plan_rows_from_batch(levels: List[Dict[str, Any]], base_rows: Dict[str, Dict[str, Any]], *,
                         infinity_mode: str = "append", infinity_relabel: bool = True,
                         infinity_source_start: int = 501, infinity_source_end: int = 1530) -> Dict[str, Dict[str, Any]]:
    """배치 레벨 → 업로드 경로와 같은 계산(무한 치환 → 변환 → 시드 열 선택 → 판정 근거 게이트)으로 '보낼 값' 계획.
    판정 근거 게이트의 서버 값 = 기준 스냅샷의 유효 값(서버 조회 없음). 서버 쓰기·조회 없음."""
    from .gboost import _convert_to_townpop_format as conv
    by_num = {int(l["level_number"]): l["level_json"] for l in levels}
    targets = []
    if infinity_mode != "only":
        targets += [(f"level_{n}", lj) for n, lj in sorted(by_num.items())]
    if infinity_mode in ("append", "only"):
        for n in range(max(1, infinity_source_start), infinity_source_end + 1):
            if n in by_num:
                targets.append((f"infinity_{n - INFINITY_OFFSET}", by_num[n]))
    out: Dict[str, Dict[str, Any]] = {}
    for tid, lj in targets:
        src, relabel = _inf.prepare_export_level_json(tid, lj, infinity_relabel)
        original = dict(src)
        tp = conv(src)
        f = _dda.export_fields(_dda.DDA_BOARD_ID, tid, original, tp) or {}
        tp, ev = _dda.apply_export_fields_with_evidence(_dda.DDA_BOARD_ID, tid, original, tp)
        base = base_rows.get(tid)
        before = None
        if base:
            seeds = L.effective_seeds(base)
            before = {k: v for k, v in seeds.items() if v is not None}
        dropped = _dda.evidence_gate(before, tp, ev)
        rec = L.build_row_record(row_id=tid, source="batch_plan", status="planned", payload=tp, level_json=original,
                                 field_reasons=f.get("fieldReasons"), field_evidence=ev, dropped=dropped,
                                 relabel=relabel, server_before="unknown")
        if base:
            rec["serverBefore"] = {"exists": True, "seeds": L.effective_seeds(base),
                                   "mapSha256": L.effective_map_sha(base),
                                   "useTileCount": L.effective_use_tile_count(base), "fromSnapshot": True}
        out[tid] = rec
    return out


def _latest_base_id() -> Optional[str]:
    snaps = [s for s in L.list_snapshots(include_dryrun=False) if s.get("status") == "finalized"]
    return snaps[-1]["id"] if snaps else None


@router.post("/diff-batch")
async def diff_batch(req: BatchPlanRequest, format: str = Query(default="json", pattern="^(json|csv)$"), limit: int = 0):
    """기준 스냅샷 vs 현재 배치(업로드하면 보낼 값). persist=True 면 dryrun 스냅샷으로 저장."""
    base_id = req.base or _latest_base_id()
    if not base_id:
        raise HTTPException(status_code=400, detail="기준 스냅샷이 없습니다 — 먼저 기준점(v0)을 만드세요")
    try:
        base = L.load(base_id)
    except L.LedgerError as e:
        raise _err(e)
    if req.infinity_mode not in ("off", "append", "only"):
        raise HTTPException(status_code=400, detail="infinity_mode must be off|append|only")
    rows = plan_rows_from_batch([l.model_dump() for l in req.levels], base.get("rows") or {},
                                infinity_mode=req.infinity_mode, infinity_relabel=req.infinity_relabel,
                                infinity_source_start=req.infinity_source_start,
                                infinity_source_end=req.infinity_source_end)
    saved = None
    if req.persist:
        saved = L.create_snapshot(kind="dryrun", rows=rows, memo=req.memo or "가상 — 배치 기준 계획(업로드 아님)",
                                  tag=req.tag, batch_id=req.batch_id, batch_name=req.batch_name, source="batch_plan",
                                  options={"base": base_id, "infinity_mode": req.infinity_mode,
                                           "infinity_relabel": req.infinity_relabel})
        virt = L.load(saved["id"])
    else:
        virt = {"id": "(virtual)", "kind": "dryrun", "status": "virtual", "batchId": req.batch_id,
                "batchName": req.batch_name, "rows": rows, "memo": "가상 — 저장 안 함"}
    res = L.diff_snapshots(base, virt, q=req.q, only_changed=req.only_changed, klass=req.klass)
    res["saved"] = saved
    if format == "json" and limit > 0:
        res["truncated"] = len(res["items"]) > limit
        res["items"] = res["items"][:limit]
    return _diff_response(res, format, f"dda_seed_diff_{base_id}_vs_batch")
