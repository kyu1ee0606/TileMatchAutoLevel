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
    header_oob_flagged: int = 0            # 헤더-OOB로 verification_passed=False 강제된 레벨 수
    header_oob_levels: List[int] = []       # 해당 레벨 번호(앞 50)
    rule_flagged: int = 0                  # 규칙 위반(사슬/폭탄/튜토리얼/timea)으로 강제된 레벨 수
    rule_levels: List[int] = []             # 해당 레벨 번호(앞 50)


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


def _scan_header_oob(lj: Dict[str, Any]) -> List[str]:
    """레벨 JSON의 헤더-경계 위반(OOB) 스캔. 반환: 위반 설명 리스트(비면 정상).

    게임은 층 헤더 col/row로 격자 생성(LayerSpawn) → 헤더 밖 좌표 타일은 스폰 안 됨(잘림)
    → 인게임 클리어 불가. RL sim/solver는 헤더 무시·타일 직접 읽어 통과시키므로 별도 검출 필요.
    검출: col/row<=0(헤더붕괴) OR 타일좌표 c>=col|r>=row|음수(경계초과).
    """
    out: List[str] = []
    try:
        n = int(lj.get("layer", 0) or 0)
    except (TypeError, ValueError):
        return out
    for i in range(n):
        v = lj.get(f"layer_{i}")
        if not isinstance(v, dict):
            continue
        tiles = v.get("tiles") or {}
        try:
            col = int(v.get("col")); row = int(v.get("row"))
        except (TypeError, ValueError):
            if tiles:
                out.append(f"L{i}:bad_header({v.get('col')}x{v.get('row')})")
            continue
        if tiles and (col <= 0 or row <= 0):
            out.append(f"L{i}:zero_header({col}x{row})")
            continue
        for coord in tiles:
            try:
                c, r = map(int, coord.split("_"))
            except (ValueError, AttributeError):
                continue
            if c < 0 or c >= col or r < 0 or r >= row:
                out.append(f"L{i}:{coord}>={col}x{row}")
    return out


def _enforce_header_bounds_gate(levels: List[Dict[str, Any]]) -> List[int]:
    """[안전망] 저장 경계 헤더-OOB 게이트 — 생성 경로 무관.

    헤더 밖 타일이 있는 레벨 = 인게임 클리어 불가(게임이 그 타일 스폰 안 함).
    meta.verification_passed=False + header_oob 강제 → 프로덕션 유출 차단. (멱등)
    """
    flagged: List[int] = []
    for l in levels:
        if not isinstance(l, dict):
            continue
        lj = l.get("level_json")
        if not isinstance(lj, dict):
            continue
        viol = _scan_header_oob(lj)
        if viol:
            m = l.setdefault("meta", {})
            m["verification_passed"] = False
            m["header_oob"] = viol[:20]
            ln = m.get("level_number")
            if isinstance(ln, int):
                flagged.append(ln)
    return flagged


def _scan_rule_violations(lj: Dict[str, Any], level_number: Optional[int]) -> Dict[str, Any]:
    """[RULE_GATE] 기믹/기획 규칙 위반 스캔. 반환: {규칙명: 내역} (비면 정상).

    RL 검증은 '클리어율'만 본다 → 규칙 위반은 난이도가 우연히 맞으면 통과해버린다.
    실측: 폭탄 언락 Lv291 이 기믹 0개로 출고됐는데, 실패 사유는 '폭탄 없음'이 아니라
    '너무 어려움' 이었다(우연히 걸린 것). 규칙은 별도 게이트로 봐야 한다.

    검출 항목(전부 게임 C# 대조로 실재 확인된 것만):
      chain_unreleasable : 해제 불가 사슬(수평 이웃이 전부 잠긴사슬/craft루트/없음)
                           → 게임 FailReason.Chain 도 미발동하는 무알림 소프트락
      bomb_range         : bomb_N 이 기획 3~5 밖 (시뮬 클램프와 불일치 → 난이도 왜곡)
      tutorial_missing   : 기믹 언락 첫 스테이지인데 해당 기믹 부재 (학습 기회 상실)
      timea_tight        : 제한시간이 가장 촉박한 티어 예산보다도 부족 (물리적 클리어 불가)
    """
    out: Dict[str, Any] = {}
    try:
        from ...core.generator import (
            LevelGenerator, BOMB_COUNTDOWN_MIN, BOMB_COUNTDOWN_MAX,
            TIMEA_BASE_MILLI, TIMEA_TIER_MILLI, TIMEA_MIN_SEC,
        )
    except Exception:  # noqa: BLE001
        return out
    gen = LevelGenerator()

    try:
        n_layers = int(lj.get("layer", 0) or 0)
    except (TypeError, ValueError):
        n_layers = 0

    # 1) 해제 불가 사슬 — 클로저 적용 전후 사슬 수 비교(복사본에서 판정, 원본 불변)
    try:
        import copy as _copy

        def _chain_count(x: Dict[str, Any]) -> int:
            c = 0
            for i in range(n_layers):
                tiles = (x.get(f"layer_{i}") or {}).get("tiles") or {}
                c += sum(1 for d in tiles.values()
                         if isinstance(d, list) and len(d) > 1 and d[1] == "chain")
            return c

        before = _chain_count(lj)
        if before:
            probe = gen._chain_release_closure(_copy.deepcopy(lj))
            after = _chain_count(probe)
            if after < before:
                out["chain_unreleasable"] = before - after
    except Exception:  # noqa: BLE001
        pass

    # 2) 폭탄 카운트다운 범위
    try:
        bad_bombs = []
        for i in range(n_layers):
            tiles = (lj.get(f"layer_{i}") or {}).get("tiles") or {}
            for pos, td in tiles.items():
                if not (isinstance(td, list) and len(td) > 1 and isinstance(td[1], str)):
                    continue
                a = td[1]
                if not a.startswith("bomb"):
                    continue
                parts = a.split("_")
                if len(parts) == 2 and parts[1].isdigit():
                    n = int(parts[1])
                    if not (BOMB_COUNTDOWN_MIN <= n <= BOMB_COUNTDOWN_MAX):
                        bad_bombs.append(f"L{i}:{pos}={a}")
                else:
                    bad_bombs.append(f"L{i}:{pos}={a}")
        if bad_bombs:
            out["bomb_range"] = bad_bombs[:10]
    except Exception:  # noqa: BLE001
        pass

    # 3) 튜토리얼(언락 첫 스테이지) 기믹 존재
    try:
        tut = gen.TUTORIAL_UNLOCK_LEVELS.get(int(level_number)) if level_number is not None else None
        if tut and tut != "key":  # key 는 게임 런타임 배치(unlockTile) 소관
            found = 0
            for i in range(n_layers):
                tiles = (lj.get(f"layer_{i}") or {}).get("tiles") or {}
                for _p, td in tiles.items():
                    if not (isinstance(td, list) and td):
                        continue
                    t0 = td[0] if isinstance(td[0], str) else ""
                    a = td[1] if len(td) > 1 and isinstance(td[1], str) else ""
                    if t0.startswith(tut) or a.startswith(tut):
                        found += 1
            if found == 0:
                out["tutorial_missing"] = tut
    except Exception:  # noqa: BLE001
        pass

    # 4) timea 예산 — 가장 촉박한 티어보다도 부족하면 물리적으로 불가
    try:
        ta = int(lj.get("timea") or 0)
        if ta > 0:
            tiles_n = gen._collectable_tile_count(lj)
            tightest = max(TIMEA_MIN_SEC,
                           -(-(tiles_n * TIMEA_BASE_MILLI * min(TIMEA_TIER_MILLI.values())) // 1_000_000))
            if ta < tightest:
                out["timea_tight"] = {"timea": ta, "tiles": tiles_n, "need": int(tightest)}
    except Exception:  # noqa: BLE001
        pass

    return out


def _enforce_rule_gate(levels: List[Dict[str, Any]]) -> List[int]:
    """[안전망] 저장 경계 규칙 게이트 — 위반 시 verification_passed=False 강제(재검증/재생성 유도).

    ÷3·헤더OOB 게이트와 동일 패턴(플래그 방식, 저장 자체는 막지 않음 → 낙관적 동시성 계약 유지).
    """
    flagged: List[int] = []
    for l in levels:
        if not isinstance(l, dict):
            continue
        lj = l.get("level_json")
        if not isinstance(lj, dict):
            continue
        m = l.setdefault("meta", {})
        viol = _scan_rule_violations(lj, m.get("level_number"))
        if viol:
            m["verification_passed"] = False
            m["rule_violations"] = viol
            ln = m.get("level_number")
            if isinstance(ln, int):
                flagged.append(ln)
        elif "rule_violations" in m:
            m.pop("rule_violations", None)  # 해소되면 제거(멱등)
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
    # [안전망] 헤더-OOB 게이트 — 헤더 밖 타일(게임서 잘림→클리어불가) 검출·플래그.
    oob_flagged = _enforce_header_bounds_gate(req.levels)
    # [안전망] 규칙 게이트 — 사슬 해제불가 / 폭탄 범위 / 튜토리얼 기믹 누락 / timea 부족.
    # RL 검증은 클리어율만 보므로 규칙 위반은 여기서 잡아 재검증·재생성으로 되돌린다.
    rule_flagged = _enforce_rule_gate(req.levels)
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
                             divisibility_levels=flagged[:50],
                             header_oob_flagged=len(oob_flagged),
                             header_oob_levels=oob_flagged[:50],
                             rule_flagged=len(rule_flagged),
                             rule_levels=rule_flagged[:50])


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
