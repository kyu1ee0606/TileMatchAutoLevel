"""
프로덕션 배치 로컬 파일 저장 — 같은 컴퓨터의 어느 브라우저든 동일 데이터 접근.

배경: 프론트는 프로덕션 레벨을 IndexedDB(브라우저-로컬)에 저장 → 다른 브라우저/프로필엔
안 보임. 백엔드(localhost)가 배치를 로컬 파일(backend/data/production/{batch_id}.json)로
보관하면, 같은 머신의 모든 브라우저가 동일 데이터를 읽고 쓸 수 있다.

배치 페이로드(batch 메타 + levels 배열)는 프론트 구조를 그대로 opaque JSON으로 저장한다
(서버는 ProductionLevel/Batch 타입을 미러링하지 않음 — 결합도 최소화).
"""
import json
import logging
import os
import time
import tempfile
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

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


# ── 배치 목록 인덱스 ──────────────────────────────────────────────────────────
# 목록 API 는 이름/개수/버전만 필요한데, 예전엔 배치 파일 전체를 json.load 했다.
# 실측: 파일 360개 · 총 1.3GB → 목록 1회에 22~95초. 프론트 axios 타임아웃(30s)을 넘겨
# "서버 목록 조회 실패: timeout of 30000ms exceeded" 로 터졌고, 앱 마운트마다 발생했다.
# → (mtime, size) 로 유효성을 판정하는 사이드카 인덱스를 두고, 바뀐 파일만 파싱한다.
_INDEX_PATH = os.path.join(_STORE_DIR, "_index.json")


def _load_index() -> Dict[str, Any]:
    try:
        with open(_INDEX_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return {}


def _save_index(idx: Dict[str, Any]) -> None:
    fd, tmp = tempfile.mkstemp(dir=_STORE_DIR, suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(idx, f, ensure_ascii=False)
        os.replace(tmp, _INDEX_PATH)
    except Exception:  # noqa: BLE001
        if os.path.exists(tmp):
            os.remove(tmp)


def _index_entry(batch_id: str, batch: Dict[str, Any], level_count: int,
                 saved_at: float, version: int, fp: str) -> Dict[str, Any]:
    st = os.stat(fp)
    return {
        "batch_id": batch_id,
        "name": (batch or {}).get("name"),
        "level_count": level_count,
        "saved_at": saved_at,
        "size_bytes": st.st_size,
        "version": version,
        "_mtime": st.st_mtime,
    }


class SaveBatchRequest(BaseModel):
    batch_id: str = Field(..., description="배치 고유 ID")
    batch: Dict[str, Any] = Field(..., description="배치 메타(opaque)")
    levels: List[Dict[str, Any]] = Field(default_factory=list, description="레벨 배열(opaque)")
    # 낙관적 동시성: 클라가 마지막으로 알던 버전. 서버 현재 버전과 다르면 409(다른 브라우저가
    # 먼저 수정). None이면 버전 검사 생략(강제 덮어쓰기 — 최초 저장/수동 강제용).
    base_version: Optional[int] = Field(default=None, description="클라가 마지막으로 안 서버 버전")
    # [델타 저장] True 면 levels 를 **변경분으로만** 보고 기존 저장본에 병합한다.
    #
    # 왜: 예전엔 무조건 전량 교체라, 순차검증처럼 레벨 몇 개만 바뀌는 상황에서도
    # 클라가 1500레벨(4.9MB)을 매번 IndexedDB 에서 읽어 직렬화해 올렸다(디바운스 4초).
    # 실측 레벨당 3.3KB · 동시성 10 → 실제 변경분은 33KB 인데 150배를 보내던 셈이고,
    # 브라우저 힙이 그 주기로 계단식으로 쌓였다(순차검증 중 탭 사망 의심 원인).
    #
    # 병합 키는 meta.level_number. 저장본에 없는 번호는 추가된다.
    # batch(메타)는 부분 전송에서도 **항상 통째로** 교체한다 — 카운터/타임스탬프류라 작고,
    # 부분 병합하면 오히려 정합이 깨진다.
    partial: bool = Field(default=False, description="levels 를 변경분으로만 보고 기존본에 병합")


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
        m = l.setdefault("meta", {})
        if bad:
            m["verification_passed"] = False
            m["divisibility_violation"] = bad
            ln = m.get("level_number")
            if isinstance(ln, int):
                flagged.append(ln)
        elif "divisibility_violation" in m:
            # [낙인 해제] 예전엔 위반을 찍기만 하고 **해소돼도 지우지 않았다**. 그래서 레벨을
            # 고친 뒤에도 메타에 표식이 남아 배포 게이트가 계속 차단했다
            # (실측: ÷3 복구 완료 후 19개가 실제 위반 0건인데 'div3' 사유로 업로드 차단).
            # 게이트는 이 필드를 보고 판단하므로, 스캔이 해소도 반영해야 멱등이 성립한다.
            m.pop("divisibility_violation", None)
            # verification_passed 는 되살리지 않는다 — 난이도 판정은 별개이고,
            # ÷3 이 풀렸다고 목표 난이도를 만족한다는 뜻은 아니다. 재검증이 확정한다.
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
      oversized_grid     : 층 헤더 col/row 가 8 초과 (디바이스 가독성 한계 — 타일이 너무 작아짐)
      gimmick_unlock_violation : 해당 레벨에서 미해금 기믹이 배치됨
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

    # 5) 선언 격자 초과 — 층 헤더 col/row 가 디바이스 가독성 상한(8)을 넘음
    #    `_scan_header_oob` 는 '타일이 헤더 밖인가'만 보고 **헤더 자체가 큰 것**은 못 잡는다.
    #    실측: 타운팝 원본 템플릿 73건이 10x10 선언으로 출고됨(여백이 없어 크롭 불가한 D타입인데
    #    규격 게이트가 보스 슬롯에만 걸려 있었다). 10칸 격자는 타일이 너무 작아 플레이 불가.
    try:
        _MAX_DECLARED = 8
        worst = 0
        for i in range(n_layers):
            ld = lj.get(f"layer_{i}")
            if not isinstance(ld, dict):
                continue
            try:
                worst = max(worst, int(ld.get("col")), int(ld.get("row")))
            except (TypeError, ValueError):
                continue
        if worst > _MAX_DECLARED:
            out["oversized_grid"] = {"declared": worst, "max": _MAX_DECLARED}
    except Exception:  # noqa: BLE001
        pass

    # 6) 기믹 언락 위반 — 해당 레벨에서 아직 해금되지 않은 기믹이 배치됨
    #    라우트는 필터하지만 생성기를 직접 호출하는 경로(후처리 스크립트 등)는 우회 가능했다.
    #    실측: 서브보스 149개 중 23개 위반(curtain 23·unknown 18·grass 7·link 4·chain 2·ice 2).
    #    저장 경계에서 잡으면 생성 경로와 무관하게 전 배치가 보호된다.
    try:
        if level_number is not None:
            from ...models.leveling_config import PROFESSIONAL_GIMMICK_UNLOCK as _G
            unlock = {g: int(c.unlock_level) for g, c in _G.items()}

            def _norm(a: str) -> str:
                a = str(a)
                for pre in ("link", "curtain", "bomb", "teleport"):
                    if a.startswith(pre):
                        return pre
                return a

            used: Dict[str, int] = {}
            for i in range(n_layers):
                for td in ((lj.get(f"layer_{i}") or {}).get("tiles") or {}).values():
                    if not (isinstance(td, list) and td):
                        continue
                    tt = str(td[0])
                    if tt.startswith("craft_"):
                        used["craft"] = used.get("craft", 0) + 1
                    elif tt.startswith("stack_"):
                        used["stack"] = used.get("stack", 0) + 1
                    if len(td) > 1 and td[1]:
                        g = _norm(td[1])
                        used[g] = used.get(g, 0) + 1
            bad = {g: {"count": c, "unlock": unlock[g]}
                   for g, c in used.items()
                   if g in unlock and level_number < unlock[g]}
            if bad:
                out["gimmick_unlock_violation"] = bad
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

    # [델타 병합] 부분 전송이면 기존 저장본을 읽어 level_number 기준으로 갈아끼운다.
    # 아래 게이트 3종은 전부 레벨 단위 순회라(_enforce_*), 델타에만 적용해도 논리가 성립한다
    # — 이미 저장된 레벨은 그때 이미 검사받았다.
    levels_in = req.levels
    merged_levels: Optional[List[Dict[str, Any]]] = None
    if req.partial:
        fp = _path(bid)
        if not os.path.exists(fp):
            # 서버에 배치가 없는데 델타만 받으면 나머지 레벨이 통째로 유실된다.
            raise HTTPException(status_code=409, detail={
                "message": "서버에 배치가 없습니다 — 최초 저장은 전체(partial=false)여야 합니다",
            })
        try:
            with open(fp, "r", encoding="utf-8") as f:
                base_levels: List[Dict[str, Any]] = json.load(f).get("levels") or []
        except Exception as ex:  # noqa: BLE001
            # 기존본을 못 읽으면 델타만 남아 1500개가 날아간다 → 저장 자체를 거부한다.
            raise HTTPException(status_code=409, detail={
                "message": f"기존 배치를 읽을 수 없어 부분 저장을 거부합니다({type(ex).__name__}) — 전체 저장(partial=false)으로 재시도하세요",
            })

        def _lnum(l: Dict[str, Any]) -> Any:
            m = l.get("meta") if isinstance(l, dict) else None
            return m.get("level_number") if isinstance(m, dict) else None

        by_num: Dict[Any, Dict[str, Any]] = {}
        order: List[Any] = []
        for l in base_levels:
            k = _lnum(l)
            if k is None:
                continue
            if k not in by_num:
                order.append(k)
            by_num[k] = l
        applied = 0
        for l in levels_in:
            k = _lnum(l)
            if k is None:
                continue
            if k not in by_num:
                order.append(k)
            by_num[k] = l
            applied += 1
        merged_levels = [by_num[k] for k in order]
        # 검증·운영 확인용. uvicorn 기본 설정에서 INFO 는 안 보여 warning 으로 낸다
        # (델타 저장은 드물지 않지만, 전량 저장으로 잘못 도는 걸 즉시 알아채는 값이 크다).
        logger.warning(f"[SAVE_PARTIAL] {bid}: 델타 {applied}건 병합 → 총 {len(merged_levels)}개")
    # [안전망] ÷3 게이트 — 생성 경로 무관하게 클리어 불가(÷3 위반) 레벨을 저장 직전 검출·플래그.
    flagged = _enforce_divisibility_gate(req.levels)
    # [안전망] 헤더-OOB 게이트 — 헤더 밖 타일(게임서 잘림→클리어불가) 검출·플래그.
    oob_flagged = _enforce_header_bounds_gate(req.levels)
    # [안전망] 규칙 게이트 — 사슬 해제불가 / 폭탄 범위 / 튜토리얼 기믹 누락 / timea 부족.
    # RL 검증은 클리어율만 보므로 규칙 위반은 여기서 잡아 재검증·재생성으로 되돌린다.
    rule_flagged = _enforce_rule_gate(req.levels)
    # 게이트는 req.levels(델타)에 플래그를 **제자리로** 찍는다. merged_levels 는 같은 dict 를
    # 참조하므로 플래그가 그대로 반영된다 — 따로 옮길 필요 없다.
    out_levels = merged_levels if merged_levels is not None else req.levels
    payload = {
        "batch_id": bid,
        "batch": req.batch,
        "levels": out_levels,
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
    # 인덱스 갱신 — 다음 목록 조회가 이 파일을 재파싱하지 않도록(저장 직후가 가장 흔한 경로)
    try:
        _idx = _load_index()
        _idx[bid] = _index_entry(bid, req.batch, len(out_levels), saved_at, new_version, _path(bid))
        _save_index(_idx)
    except Exception:  # noqa: BLE001
        pass  # 인덱스는 캐시일 뿐 — 실패해도 목록 조회가 재파싱으로 복구

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
    """저장된 배치 요약 목록(최신 저장순).

    인덱스 캐시 기반 — (mtime, size) 가 일치하면 파일을 열지 않는다.
    바뀐/새 파일만 파싱하므로 정상 상태에선 디렉터리 stat 스캔 비용만 든다.
    """
    _ensure_dir()
    idx = _load_index()
    out: List[BatchSummary] = []
    seen: set = set()
    dirty = False

    for fn in os.listdir(_STORE_DIR):
        if not fn.endswith(".json") or fn == "_index.json":
            continue
        fp = os.path.join(_STORE_DIR, fn)
        bid = fn[:-5]
        seen.add(bid)
        try:
            st = os.stat(fp)
        except OSError:
            continue
        e = idx.get(bid)
        if not (isinstance(e, dict) and e.get("_mtime") == st.st_mtime
                and e.get("size_bytes") == st.st_size):
            # 캐시 미스(신규·수정) → 이 파일만 파싱해 인덱스 갱신
            try:
                with open(fp, "r", encoding="utf-8") as f:
                    data = json.load(f)
            except Exception:  # noqa: BLE001
                continue
            e = _index_entry(
                data.get("batch_id", bid), data.get("batch") or {},
                len(data.get("levels") or []),
                data.get("saved_at", st.st_mtime),
                int(data.get("version", 0)), fp)
            idx[bid] = e
            dirty = True
        out.append(BatchSummary(
            batch_id=e["batch_id"], name=e.get("name"),
            level_count=int(e.get("level_count") or 0),
            saved_at=float(e.get("saved_at") or 0.0),
            size_bytes=int(e.get("size_bytes") or 0),
            version=int(e.get("version") or 0),
        ))

    # 삭제된 배치의 인덱스 항목 정리
    for stale in [k for k in idx if k not in seen]:
        idx.pop(stale, None)
        dirty = True
    if dirty:
        _save_index(idx)

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
