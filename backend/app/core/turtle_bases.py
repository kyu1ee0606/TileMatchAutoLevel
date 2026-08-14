"""[등껍질 바닥 패턴 라이브러리] 침식 스택의 **바닥 1층 모양**만 모아두는 전용 저장소.

왜 별도 저장소인가:
  기존 `custom_patterns.json` 은 크기별(4x4~9x9) 일반 패턴 라이브러리이고, 등껍질과 무관한
  경로(절차생성·층 순환 등)에서도 쓰인다. 거기에 등껍질 전용 항목을 섞으면 서로의 규칙이
  간섭한다(등껍질은 '두께'가 필수, 일반 패턴은 성긴 모양도 유효).
  → 등껍질 바닥은 여기에만 모으고, 기존 49종은 **복사**해 넣는다(원본 불변).

엔트리 형식:
    "tb_xxx": {
      "name": "육각 성채",
      "grid": 8,                       # 바닥층 격자(7 또는 8 — 짝수층 헤더 크기)
      "cells": ["2_0", "3_0", ...],    # 바닥층 채움 좌표
      "enabled": true,
      "source": "custom_patterns:3_8x8" | "manual",
      "turtle":     {depth, total, per_layer},          # 저장 시 자동 계산
      "difficulty": {by_v:{...}, coef}                  # 측정 API 로 채움(선택)
    }

`difficulty` 가 없는 항목은 서브보스 자동 배정 후보에서 제외된다(난이도를 모르면 배정 불가).
모양 미리보기/수동 지정에는 그대로 쓸 수 있다.
"""
from __future__ import annotations

import json
import os
import tempfile
from typing import Any, Dict, List, Optional, Set, Tuple

_THIS = os.path.dirname(os.path.abspath(__file__))
STORE_PATH = os.path.normpath(os.path.join(_THIS, "..", "..", "data", "turtle_bases.json"))

# 등껍질 자격 기준 — 실험(exp_turtle_select.py) 실측 근거
MIN_DEPTH = 4      # 3층 이하는 기존 스택과 구분 안 됨

# [타일 예산] `turtle.total` 은 **순수 침식 셀 수**이고, 실제 생성물은 여기에
#   ÷3 패딩 + craft/stack 컨테이너 내부 타일이 더해진다.
#   실측(103종 × 난이도 3조건 = 309건): 초과분 min 0 / p50 5 / p90 12 / **max 13**.
#   유일 변수는 난이도(컨테이너 개수) — td0.15→0~2, td0.55→4~9, td0.92→8~13.
#   저장 시점엔 배정될 난이도를 모르므로 생성 기반 검증은 느리기만 하고 부정확하다
#   → 상수 마진으로 최악값을 커버한다. 실측 최대 13에 여유 3을 더해 16.
TURTLE_MAX_OVERHEAD = 16
# 실생성 기준 상한. 프로덕션 실측 최대 타일수는 178, 등껍질 실생성 최대는 138 이었다.
EFFECTIVE_MAX_TOTAL = 145
# 검증에 쓰는 순수 셀 상한(= 실생성 상한 − 최악 오버헤드). 저장 비용은 그대로 0.
MAX_TOTAL = EFFECTIVE_MAX_TOTAL - TURTLE_MAX_OVERHEAD

ALLOWED_GRIDS = (7, 8)   # 신규 등록용. 복사 유입분은 원래 격자를 유지한다.


def _load() -> Dict[str, Any]:
    try:
        with open(STORE_PATH, "r", encoding="utf-8") as f:
            d = json.load(f)
        return d if isinstance(d, dict) else {}
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return {}


def _save(d: Dict[str, Any]) -> None:
    os.makedirs(os.path.dirname(STORE_PATH), exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=os.path.dirname(STORE_PATH), suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(d, f, ensure_ascii=False)
        os.replace(tmp, STORE_PATH)
    except Exception:
        if os.path.exists(tmp):
            os.remove(tmp)
        raise


def parse_cells(cells: List[str], grid: int) -> Set[Tuple[int, int]]:
    out: Set[Tuple[int, int]] = set()
    for c in cells or []:
        try:
            x, y = map(int, str(c).split("_"))
        except ValueError:
            continue
        if 0 <= x < grid and 0 <= y < grid:
            out.add((x, y))
    return out


def peel_stack(cells: Set[Tuple[int, int]], grid: int
               ) -> List[Tuple[int, int, Set[Tuple[int, int]]]]:
    """생성기와 **동일한** 완전받침 침식(정본 재사용 — 로직 이중화 금지)."""
    from .generator import LevelGenerator
    return LevelGenerator._turtle_peel_stack(cells, grid)


def compute_turtle_meta(cells: List[str], grid: int) -> Dict[str, Any]:
    cs = parse_cells(cells, grid)
    stack = peel_stack(cs, grid)
    per = [len(c) for _, _, c in stack]
    total = sum(per)
    return {"depth": len(stack), "total": total, "per_layer": per, "base": grid,
            # 실생성 예상 최대 = 순수 셀 + 최악 오버헤드(÷3 패딩 + 컨테이너 내부 타일)
            "est_max_total": total + TURTLE_MAX_OVERHEAD}


def validate(cells: List[str], grid: int) -> Optional[str]:
    """등록 가능 여부. 문제 있으면 사유 문자열, 없으면 None."""
    if grid not in (5, 6, 7, 8, 9):
        return f"격자 {grid} 미지원"
    cs = parse_cells(cells, grid)
    if not cs:
        return "셀이 비어 있음"
    meta = compute_turtle_meta(cells, grid)
    if meta["depth"] < MIN_DEPTH:
        return f"침식 깊이 {meta['depth']} < {MIN_DEPTH} — 바닥이 너무 얇음(두껍게 그려야 층이 쌓임)"
    if meta["total"] > MAX_TOTAL:
        # 사용자가 보는 숫자는 '실생성 예상 최대' 로 통일한다(순수 셀만 보면 오해한다).
        return (f"실생성 예상 최대 {meta['total'] + TURTLE_MAX_OVERHEAD}타일 "
                f"> {EFFECTIVE_MAX_TOTAL} — 타일 예산 초과 "
                f"(순수 {meta['total']} + 패딩·컨테이너 최대 {TURTLE_MAX_OVERHEAD})")
    return None


def list_bases(enabled_only: bool = False, with_shape: bool = True) -> List[Dict[str, Any]]:
    d = _load()
    out: List[Dict[str, Any]] = []
    for k, v in d.items():
        if not isinstance(v, dict):
            continue
        if enabled_only and not v.get("enabled", True):
            continue
        e = {kk: vv for kk, vv in v.items() if kk != "cells"}
        e["id"] = k
        e["cell_count"] = len(v.get("cells") or [])
        if with_shape:
            grid = int(v.get("grid") or 8)
            e["cells"] = list(v.get("cells") or [])
            e["layers"] = [{"col": col, "cells": [f"{x}_{y}" for (x, y) in sorted(cs)]}
                           for (_li, col, cs) in peel_stack(parse_cells(e["cells"], grid), grid)]
        out.append(e)
    out.sort(key=lambda e: ((e.get("difficulty") or {}).get("coef") is None,
                            (e.get("difficulty") or {}).get("coef") or 0, e["id"]))
    return out


def get_base(base_id: str) -> Optional[Dict[str, Any]]:
    v = _load().get(base_id)
    return dict(v, id=base_id) if isinstance(v, dict) else None


def put_base(base_id: str, name: str, grid: int, cells: List[str],
             enabled: bool = True, source: str = "manual") -> Dict[str, Any]:
    d = _load()
    prev = d.get(base_id) or {}
    entry: Dict[str, Any] = {
        "name": name or base_id,
        "grid": int(grid),
        "cells": sorted(set(cells or [])),
        "enabled": bool(enabled),
        "source": source,
        "turtle": compute_turtle_meta(cells, int(grid)),
    }
    # 모양이 그대로면 기존 난이도 측정값 유지, 바뀌면 폐기(측정값이 모양과 어긋나면 안 됨)
    if prev.get("cells") == entry["cells"] and prev.get("difficulty"):
        entry["difficulty"] = prev["difficulty"]
    d[base_id] = entry
    _save(d)
    return dict(entry, id=base_id)


def delete_base(base_id: str) -> bool:
    d = _load()
    if base_id not in d:
        return False
    d.pop(base_id)
    _save(d)
    return True


def set_difficulty(base_id: str, difficulty: Dict[str, Any]) -> bool:
    d = _load()
    if base_id not in d:
        return False
    d[base_id]["difficulty"] = difficulty
    _save(d)
    return True
