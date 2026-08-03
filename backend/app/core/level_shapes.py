"""[층별 패턴(Level Shapes)] 층마다 고정 모양을 갖는 레벨 스택 저장소.

기존 패턴 라이브러리(`custom_patterns.json`)와 저장 모델이 다르다:
  패턴 라이브러리 : `{index}_{S}x{S}` — 한 모양의 **그리드 크기별 변형**
  층별 패턴(여기) : `{id}` — 레벨 1개 = **층마다 다른 고정 모양**의 스택 전체

원본 `level_templates.json`(타운팝 임포트분 211개)은 **읽기 전용**으로 두고,
인게임 규격(최대변 8)으로 크롭한 결과만 이 저장소에 사본으로 넣는다 → 원본 보존·재크롭 가능.

## 게임 격자 규칙 (확인 완료)
`TileGroup.cs:548` `UpdateLayerRowCount(xLayer, xRow)` → **레벨 단위 `row` 하나**로 격자 생성.
`:1196/1200` `LayerSpawn(rowCount)` / `LayerSpawn(rowCount-1)` → 짝수층 S×S, 홀수층 (S-1)×(S-1) **정사각**.
`TileLayer.cs:51`·`TileRow.cs:78-84` 루프는 `j < N` → `x >= N` 키는 **조용히 미스폰**.
출고측 `gboost.py:391` 은 `layer_0.row` 를 보드 크기로 내보낸다.
∴ 크롭 기준축은 **`layer_0.row`**, 검증은 `N_i = row_0 - (i % 2)`.
"""
from __future__ import annotations

import copy
import json
import os
import tempfile
from typing import Any, Dict, List, Optional, Tuple

_STORE = os.path.normpath(
    os.path.join(os.path.dirname(__file__), "..", "..", "data", "level_shapes.json"))

# 기믹 → 해금 레벨 (generator.TUTORIAL_UNLOCK_LEVELS 미러). 이 기믹이 있으면 그 레벨 이상에만 배정.
GIMMICK_MIN_LEVEL: Dict[str, int] = {
    "craft": 11, "stack": 21, "ice": 31, "link": 51, "chain": 81, "key": 111,
    "grass": 151, "unknown": 191, "curtain": 241, "bomb": 291, "frog": 391,
    "teleport": 441, "teleporter": 441,
}


# ───────────────────────── 저장소 I/O ─────────────────────────
def _load() -> Dict[str, Any]:
    try:
        with open(_STORE, "r", encoding="utf-8") as f:
            d = json.load(f)
            return d if isinstance(d, dict) else {}
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def _save(data: Dict[str, Any]) -> None:
    """원자적 저장(임시파일 → replace). 워커 다중 실행 시 파일 손상 방지."""
    d = os.path.dirname(_STORE)
    os.makedirs(d, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=d, suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False)
        os.replace(tmp, _STORE)
    except Exception:
        if os.path.exists(tmp):
            os.remove(tmp)
        raise


# ───────────────────────── 분석 헬퍼 ─────────────────────────
def _layers(lj: Dict[str, Any]) -> List[Tuple[int, int, int, Dict[str, Any]]]:
    """(층index, col, row, tiles) — 타일 있는 층만."""
    out = []
    try:
        n = int(lj.get("layer", 0) or 0)
    except (TypeError, ValueError):
        return out
    for i in range(n):
        L = lj.get(f"layer_{i}")
        if not isinstance(L, dict):
            continue
        t = L.get("tiles") or {}
        if not t:
            continue
        try:
            out.append((i, int(L.get("col")), int(L.get("row")), t))
        except (TypeError, ValueError):
            continue
    return out


def board_size(lj: Dict[str, Any]) -> int:
    """게임이 실제로 쓰는 보드 크기 = layer_0.row (없으면 최대 row 폴백)."""
    L0 = lj.get("layer_0")
    if isinstance(L0, dict):
        try:
            v = int(L0.get("row"))
            if v > 0:
                return v
        except (TypeError, ValueError):
            pass
    ls = _layers(lj)
    return max((r for _, _, r, _ in ls), default=0)


def assert_in_board(lj: Dict[str, Any]) -> List[str]:
    """게임 격자 모델로 하드 검증. 반환: 위반 목록(비면 정상).

    N_i = row_0 - (i % 2). x,y 둘 다 N_i 미만이어야 스폰된다.
    """
    base = board_size(lj)
    if base <= 0:
        return ["board_size=0"]
    bad: List[str] = []
    for i, _c, _r, tiles in _layers(lj):
        n = base - (i % 2)
        for p in tiles:
            try:
                x, y = map(int, p.split("_"))
            except ValueError:
                continue
            if x < 0 or y < 0 or x >= n or y >= n:
                bad.append(f"L{i}:{p}>={n}")
    return bad


def gimmicks_of(lj: Dict[str, Any]) -> List[str]:
    """레벨이 쓰는 기믹 종류(컨테이너 타입 + 속성)."""
    s = set()
    for _i, _c, _r, tiles in _layers(lj):
        for _p, td in tiles.items():
            if not (isinstance(td, list) and td):
                continue
            t0 = td[0] if isinstance(td[0], str) else ""
            a = td[1] if len(td) > 1 and isinstance(td[1], str) else ""
            if t0.startswith("craft_"):
                s.add("craft")
            elif t0.startswith("stack_"):
                s.add("stack")
            elif t0 == "t16" or t0 == "key":
                s.add("key")
            if a:
                base = a.split("_")[0] if not a.startswith("bomb") else "bomb"
                if base in ("link", "curtain"):
                    s.add(base)
                elif base in GIMMICK_MIN_LEVEL:
                    s.add(base)
    return sorted(s)


def min_level_for(lj: Dict[str, Any]) -> int:
    """이 모양을 배정할 수 있는 **최소 레벨**. 기믹 해금 규칙 위반 방지.

    실측: 타운팝 템플릿 211개 중 101개(48%)가 해금 전 기믹 보유(커튼만 63개).
    배정 시 이 값으로 필터하지 않으면 커튼이 190레벨 일찍 등장한다.
    """
    return max((GIMMICK_MIN_LEVEL.get(g, 0) for g in gimmicks_of(lj)), default=0)


def silhouette_iou(a: Dict[str, Any], b: Dict[str, Any], shift: Tuple[int, int] = (0, 0)) -> float:
    """층별 실루엣 IoU 평균. b 좌표에 shift 를 더해 a 좌표계로 맞춰 비교."""
    dx, dy = shift
    am = {i: set(t.keys()) for i, _, _, t in _layers(a)}
    bm = {}
    for i, _, _, t in _layers(b):
        s = set()
        for p in t:
            try:
                x, y = map(int, p.split("_"))
            except ValueError:
                continue
            s.add(f"{x+dx}_{y+dy}")
        bm[i] = s
    vals = []
    for i, o in am.items():
        c = bm.get(i, set())
        u = len(o | c)
        if u:
            vals.append(len(o & c) / u)
    return sum(vals) / len(vals) if vals else 0.0


def uniform_crop(lj: Dict[str, Any], target: int) -> Tuple[Dict[str, Any], int, Tuple[int, int, int, int]]:
    """전 층 동일량 크롭(홀짝 유지). 반환 (신레벨, 손실타일수, (l,r,t,b)).

    기준축은 `layer_0.row`(= 게임 보드 크기). 좌우/상하 대칭으로 자른다.
    """
    base = board_size(lj)
    need = base - target
    if need <= 0:
        return copy.deepcopy(lj), 0, (0, 0, 0, 0)
    lcut, rcut = need // 2, need - need // 2
    tcut, bcut = need // 2, need - need // 2
    new = copy.deepcopy(lj)
    lost = 0
    try:
        n = int(new.get("layer", 0) or 0)
    except (TypeError, ValueError):
        n = 0
    for i in range(n):
        L = new.get(f"layer_{i}")
        if not isinstance(L, dict):
            continue
        tiles = L.get("tiles") or {}
        try:
            c, r = int(L.get("col")), int(L.get("row"))
        except (TypeError, ValueError):
            continue
        nc, nr = c - lcut - rcut, r - tcut - bcut
        nt = {}
        for p, v in tiles.items():
            try:
                x, y = map(int, p.split("_"))
            except ValueError:
                continue
            nx, ny = x - lcut, y - tcut
            if 0 <= nx < nc and 0 <= ny < nr:
                nt[f"{nx}_{ny}"] = v
            else:
                lost += 1
        was_str = isinstance(L.get("col"), str)
        L["col"] = str(nc) if was_str else nc
        L["row"] = str(nr) if was_str else nr
        L["tiles"] = nt
        L["num"] = str(len(nt))
    return new, lost, (lcut, rcut, tcut, bcut)


# ───────────────────────── CRUD ─────────────────────────
def list_shapes(enabled_only: bool = False) -> List[Dict[str, Any]]:
    """요약 목록(level_json 제외 — 페이로드 절감)."""
    d = _load()
    out = []
    for k, v in d.items():
        if not isinstance(v, dict):
            continue
        if enabled_only and not v.get("enabled", True):
            continue
        out.append({kk: vv for kk, vv in v.items() if kk != "level_json"} | {"id": k})
    out.sort(key=lambda e: (e.get("min_level", 0), e.get("id", "")))
    return out


def get_shape(shape_id: str) -> Optional[Dict[str, Any]]:
    v = _load().get(shape_id)
    if isinstance(v, dict):
        return {**v, "id": shape_id}
    return None


def put_shape(shape_id: str, entry: Dict[str, Any]) -> None:
    d = _load()
    d[shape_id] = entry
    _save(d)


def put_many(entries: Dict[str, Dict[str, Any]]) -> int:
    d = _load()
    d.update(entries)
    _save(d)
    return len(entries)


def patch_shape(shape_id: str, **fields) -> bool:
    d = _load()
    if shape_id not in d or not isinstance(d[shape_id], dict):
        return False
    d[shape_id].update(fields)
    _save(d)
    return True


def delete_shape(shape_id: str) -> bool:
    d = _load()
    if shape_id not in d:
        return False
    del d[shape_id]
    _save(d)
    return True
