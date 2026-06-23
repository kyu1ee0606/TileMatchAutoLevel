"""
프로덕션 배치 로컬 파일 저장 — 같은 컴퓨터의 어느 브라우저든 동일 데이터 접근.

배경: 프론트는 프로덕션 레벨을 IndexedDB(브라우저-로컬)에 저장 → 다른 브라우저/프로필엔
안 보임. 백엔드(localhost)가 배치를 로컬 파일(backend/data/production/{batch_id}.json)로
보관하면, 같은 머신의 모든 브라우저가 동일 데이터를 읽고 쓸 수 있다.

배치 페이로드(batch 메타 + levels 배열)는 프론트 구조를 그대로 opaque JSON으로 저장한다
(서버는 ProductionLevel/Batch 타입을 미러링하지 않음 — 결합도 최소화).
"""
import json
import os
import time
import tempfile
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

router = APIRouter(prefix="/api/production", tags=["production-store"])

_STORE_DIR = os.path.normpath(
    os.path.join(os.path.dirname(__file__), "..", "..", "..", "data", "production")
)


def _ensure_dir() -> None:
    os.makedirs(_STORE_DIR, exist_ok=True)


def _safe_id(batch_id: str) -> str:
    """경로 주입 방지 — 파일명에 안전한 문자만 허용."""
    if not batch_id or any(c in batch_id for c in ("/", "\\", "..", "\0")):
        raise HTTPException(status_code=400, detail="invalid batch_id")
    return batch_id


def _path(batch_id: str) -> str:
    return os.path.join(_STORE_DIR, f"{_safe_id(batch_id)}.json")


class SaveBatchRequest(BaseModel):
    batch_id: str = Field(..., description="배치 고유 ID")
    batch: Dict[str, Any] = Field(..., description="배치 메타(opaque)")
    levels: List[Dict[str, Any]] = Field(default_factory=list, description="레벨 배열(opaque)")
    # 낙관적 동시성: 클라가 마지막으로 알던 버전. 서버 현재 버전과 다르면 409(다른 브라우저가
    # 먼저 수정). None이면 버전 검사 생략(강제 덮어쓰기 — 최초 저장/수동 강제용).
    base_version: Optional[int] = Field(default=None, description="클라가 마지막으로 안 서버 버전")


class BatchSummary(BaseModel):
    batch_id: str
    name: Optional[str] = None
    level_count: int
    saved_at: float
    size_bytes: int
    version: int = 0


class SaveBatchResponse(BaseModel):
    ok: bool
    batch_id: str
    level_count: int
    saved_at: float
    version: int
    divisibility_flagged: int = 0          # ÷3 위반으로 verification_passed=False 강제된 레벨 수
    divisibility_levels: List[int] = []     # 해당 레벨 번호(앞 50)


def _enforce_divisibility_gate(levels: List[Dict[str, Any]]) -> List[int]:
    """[안전망] 프로덕션 저장 경계 ÷3 게이트 — 생성 경로 무관.

    어떤 경로로 만들어졌든(역생성 우회/구버전/forward/수동편집) 매칭타입 ÷3 위반 =
    수학적으로 클리어 불가. 게임 분배(_clearability_type_counts, DB_Level.cs 포트) 기준으로
    위반 레벨을 검출해 meta.verification_passed=False + divisibility_violation 을 강제 →
    '불가능 레벨이 passed 로 프로덕션 유출'을 구조적으로 차단. (멱등)

    배경: v16 ÷3 게이트는 generator.generate() 안에만 있어, generate() 를 우회한 레벨은
    보호받지 못했다(실측: 1500 중 9 레벨 PROVEN_IMPOSSIBLE). 본 게이트가 최종 저장에서 모두 잡는다.
    """
    flagged: List[int] = []
    try:
        from ...core.solver import _clearability_type_counts
    except Exception:
        return flagged
    for l in levels:
        if not isinstance(l, dict):
            continue
        lj = l.get("level_json")
        if not isinstance(lj, dict):
            continue
        try:
            counts = _clearability_type_counts(lj)
            bad = {t: c for t, c in counts.items() if c % 3 != 0}
        except Exception:
            continue
        if bad:
            m = l.setdefault("meta", {})
            m["verification_passed"] = False
            m["divisibility_violation"] = bad
            ln = m.get("level_number")
            if isinstance(ln, int):
                flagged.append(ln)
    return flagged


def _current_version(batch_id: str) -> Optional[int]:
    """저장된 배치의 현재 버전(없으면 None)."""
    fp = _path(batch_id)
    if not os.path.exists(fp):
        return None
    try:
        with open(fp, "r", encoding="utf-8") as f:
            return int(json.load(f).get("version", 0))
    except Exception:
        return None


@router.put("/batches/{batch_id}", response_model=SaveBatchResponse)
def save_batch(batch_id: str, req: SaveBatchRequest) -> SaveBatchResponse:
    """배치 전체(메타+레벨)를 로컬 파일에 저장(덮어쓰기). 원자적 쓰기 + 낙관적 동시성 버전 검사."""
    _ensure_dir()
    bid = _safe_id(batch_id)
    cur = _current_version(bid)
    # 충돌 검사: base_version이 주어졌고 서버에 이미 있으며 버전이 다르면 거부(다른 브라우저 선수정).
    if req.base_version is not None and cur is not None and req.base_version != cur:
        raise HTTPException(
            status_code=409,
            detail={"message": "version conflict — 다른 브라우저에서 먼저 수정됨",
                    "server_version": cur, "your_base": req.base_version},
        )
    new_version = (cur or 0) + 1
    saved_at = time.time()
    # [안전망] ÷3 게이트 — 생성 경로 무관하게 클리어 불가(÷3 위반) 레벨을 저장 직전 검출·플래그.
    flagged = _enforce_divisibility_gate(req.levels)
    payload = {
        "batch_id": bid,
        "batch": req.batch,
        "levels": req.levels,
        "saved_at": saved_at,
        "version": new_version,
    }
    # 원자적 쓰기(임시파일 → rename)로 부분쓰기/손상 방지
    fd, tmp = tempfile.mkstemp(dir=_STORE_DIR, suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False)
        os.replace(tmp, _path(bid))
    except Exception:
        if os.path.exists(tmp):
            os.remove(tmp)
        raise
    return SaveBatchResponse(ok=True, batch_id=bid, level_count=len(req.levels),
                             saved_at=saved_at, version=new_version,
                             divisibility_flagged=len(flagged),
                             divisibility_levels=flagged[:50])


@router.get("/batches", response_model=List[BatchSummary])
def list_batches() -> List[BatchSummary]:
    """저장된 배치 요약 목록(최신 저장순)."""
    _ensure_dir()
    out: List[BatchSummary] = []
    for fn in os.listdir(_STORE_DIR):
        if not fn.endswith(".json"):
            continue
        fp = os.path.join(_STORE_DIR, fn)
        try:
            with open(fp, "r", encoding="utf-8") as f:
                data = json.load(f)
            out.append(BatchSummary(
                batch_id=data.get("batch_id", fn[:-5]),
                name=(data.get("batch") or {}).get("name"),
                level_count=len(data.get("levels") or []),
                saved_at=data.get("saved_at", os.path.getmtime(fp)),
                size_bytes=os.path.getsize(fp),
                version=int(data.get("version", 0)),
            ))
        except Exception:
            continue
    out.sort(key=lambda b: b.saved_at, reverse=True)
    return out


@router.get("/batches/{batch_id}")
def get_batch(batch_id: str) -> Dict[str, Any]:
    """배치 전체(메타+레벨) 로드."""
    fp = _path(batch_id)
    if not os.path.exists(fp):
        raise HTTPException(status_code=404, detail="batch not found")
    with open(fp, "r", encoding="utf-8") as f:
        return json.load(f)


@router.delete("/batches/{batch_id}")
def delete_batch(batch_id: str) -> Dict[str, Any]:
    """배치 파일 삭제."""
    fp = _path(batch_id)
    if os.path.exists(fp):
        os.remove(fp)
        return {"ok": True, "deleted": batch_id}
    raise HTTPException(status_code=404, detail="batch not found")
