"""
[유닛 조립 레이어 생성] 소형 유닛 라이브러리 + 커버리지 valid_mask.

- 유닛 = 위층 조립에 쓰는 소형 조각. 타일수 ÷3 필수(예산/클리어).
- 도형 생성기(rect·frame·plus·diamond·L·T·stairs)로 3~15칸 다양한 모양 자동 생성 → 시드.
- data/unit_templates.json 에 영속 → 패턴 디버거에서 편집(추가/삭제) 가능.
- 커버리지 오프셋 = generator.py `_is_position_covered_by_upper`(게임 FindAllUpperTiles 정본) 동일.
"""
import json
import os
from typing import Dict, List, Set, Tuple

Cell = Tuple[int, int]

# ── 커버리지 오프셋 (정본, generator.py:6789 = 게임 TileGroup.FindAllUpperTiles) ──
BLOCKING_OFFSETS_SAME_PARITY: Tuple[Cell, ...] = ((0, 0),)
BLOCKING_OFFSETS_UPPER_BIGGER: Tuple[Cell, ...] = ((0, 0), (1, 0), (0, 1), (1, 1))
BLOCKING_OFFSETS_UPPER_SMALLER: Tuple[Cell, ...] = ((-1, -1), (0, -1), (-1, 0), (0, 0))


def get_cover_offsets(lower_layer: int, upper_layer: int, lower_col: int, upper_col: int) -> Tuple[Cell, ...]:
    """하위 타일 (x,y) 를 덮는 상위 타일의 오프셋. (하위 기준 → 상위 위치 = (x+dx, y+dy))"""
    if lower_layer % 2 == upper_layer % 2:
        return BLOCKING_OFFSETS_SAME_PARITY
    if upper_col > lower_col:
        return BLOCKING_OFFSETS_UPPER_BIGGER
    return BLOCKING_OFFSETS_UPPER_SMALLER


def valid_support_mask(
    lower_positions: Set[Cell], lower_layer: int, upper_layer: int,
    lower_col: int, upper_col: int, upper_rows: int,
) -> Set[Cell]:
    """상위 층에서 '받침(아래층 타일)이 있어 타일을 놓을 수 있는' 좌표 집합. 각 상위 칸이
    하위 타일 1개 이상을 덮으면 floating 없음."""
    offsets = get_cover_offsets(lower_layer, upper_layer, lower_col, upper_col)
    mask: Set[Cell] = set()
    for ux in range(upper_col):
        for uy in range(upper_rows):
            for (dx, dy) in offsets:
                if (ux - dx, uy - dy) in lower_positions:
                    mask.add((ux, uy))
                    break
    return mask


# ── 유닛 클래스 ──
def _norm(cells: List[Cell]) -> Tuple[Cell, ...]:
    """원점 정규화 + **중복 제거**(dedupe). 겹친 셀 하나로."""
    uniq = {(x, y) for (x, y) in cells}
    minx = min(c[0] for c in uniq)
    miny = min(c[1] for c in uniq)
    return tuple(sorted((x - minx, y - miny) for (x, y) in uniq))


def is_connected(cells) -> bool:
    """4방(상하좌우) 인접 연결 여부. 끊긴 조각(대각선만·고립)은 False.
    유닛은 반드시 연결돼야 함 — 안 그러면 위층에 낱개로 흩어져 배치됨."""
    cs = {tuple(c) for c in cells}
    if not cs:
        return False
    seen: Set[Cell] = set()
    stack = [next(iter(cs))]
    while stack:
        c = stack.pop()
        if c in seen:
            continue
        seen.add(c)
        for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
            n = (c[0] + dx, c[1] + dy)
            if n in cs and n not in seen:
                stack.append(n)
    return len(seen) == len(cs)


class Unit:
    __slots__ = ("name", "cells", "w", "h", "size")

    def __init__(self, name: str, cells: List[Cell]):
        self.name = name
        self.cells = _norm(cells)  # dedupe 포함
        self.w = max(c[0] for c in self.cells) + 1
        self.h = max(c[1] for c in self.cells) + 1
        self.size = len(self.cells)

    def density(self) -> float:
        return self.size / (self.w * self.h)

    def placed(self, ox: int, oy: int) -> Set[Cell]:
        return {(x + ox, y + oy) for (x, y) in self.cells}

    def to_dict(self) -> Dict:
        return {"name": self.name, "cells": [list(c) for c in self.cells]}


# ── 도형 생성기 (÷3 · 다양한 모양) ──
def _rect(w: int, h: int) -> List[Cell]:
    return [(x, y) for x in range(w) for y in range(h)]


def _frame(n: int) -> List[Cell]:
    return [(x, y) for x in range(n) for y in range(n) if x in (0, n - 1) or y in (0, n - 1)]


def _plus(n: int) -> List[Cell]:
    c = n // 2
    return [(x, y) for x in range(n) for y in range(n) if x == c or y == c]


def _diamond(r: int) -> List[Cell]:
    return [(x, y) for x in range(2 * r + 1) for y in range(2 * r + 1) if abs(x - r) + abs(y - r) <= r]


def _L(a: int, b: int) -> List[Cell]:
    return [(0, y) for y in range(a)] + [(x, a - 1) for x in range(1, b)]


def _T(w: int, h: int) -> List[Cell]:
    c = w // 2
    return [(x, 0) for x in range(w)] + [(c, y) for y in range(1, h)]


def _stairs(n: int) -> List[Cell]:
    out = []
    for i in range(n):
        out.append((i, i))
        out.append((i, i + 1))
    return out


def _default_units() -> List[Unit]:
    """÷3 통과 + 적정 밀도(≥0.45)·bbox≤5 의 다양한 시드 유닛. 이름/모양 중복 제거."""
    cand: List[Tuple[str, List[Cell]]] = [
        # 3칸
        ("I3_h", [(0, 0), (1, 0), (2, 0)]),
        ("I3_v", [(0, 0), (0, 1), (0, 2)]),
        ("L3", [(0, 0), (0, 1), (1, 1)]),
        ("V3", [(0, 0), (1, 0), (1, 1)]),
        # 6칸
        ("R2x3", _rect(2, 3)),
        ("R3x2", _rect(3, 2)),
        ("L6", [(0, 0), (0, 1), (0, 2), (1, 2), (2, 2), (1, 0)]),   # L 굽음
        ("T6", _T(3, 4)),                                          # 3 + 3
        ("S6", [(1, 0), (2, 0), (0, 1), (1, 1), (0, 2), (1, 2)]),  # S 지그재그
        ("P6", [(0, 0), (1, 0), (0, 1), (1, 1), (0, 2), (1, 2)]),  # 2x3(=R2x3, dedup)
        # 9칸 (밀집: 3×3, 3×4 부분)
        ("S3x3", _rect(3, 3)),
        ("U9", [(0, 0), (0, 1), (0, 2), (0, 3), (1, 3), (2, 3), (2, 0), (2, 1), (2, 2)]),  # U 3×4
        ("H9", [(0, 0), (0, 1), (0, 2), (0, 3), (1, 1), (1, 2), (2, 0), (2, 1), (2, 2), (2, 3)][:9]),
        ("plus9", [(1, 0), (0, 1), (1, 1), (2, 1), (1, 2), (0, 0), (2, 0), (0, 2), (2, 2)]),  # =3×3(dedup)
        ("stairs9", _stairs(3) + [(0, 3), (1, 4), (2, 5)][:3]),
        ("L9", [(0, 0), (0, 1), (0, 2), (0, 3), (1, 3), (2, 3), (3, 3), (1, 0), (2, 0)][:9]),
        # 12칸 (4×4 계열)
        ("frame4", _frame(4)),                  # 4x4 테두리 = 12 (링)
        ("R3x4", _rect(3, 4)),
        ("R4x3", _rect(4, 3)),
        ("plus12", [(1, 0), (2, 0), (1, 1), (2, 1), (0, 1), (0, 2), (3, 1), (3, 2), (1, 2), (2, 2), (1, 3), (2, 3)]),  # 두꺼운 십자
        ("diamond12", [(1, 0), (2, 0), (0, 1), (1, 1), (2, 1), (3, 1), (0, 2), (1, 2), (2, 2), (3, 2), (1, 3), (2, 3)]),  # 마름모 4×4
        # 15칸 (5×5·3×5 계열)
        ("R3x5", _rect(3, 5)),
        ("R5x3", _rect(5, 3)),
        ("T15", [(0, 0), (1, 0), (2, 0), (3, 0), (4, 0),          # T(연결, 15칸)
                 (1, 1), (2, 1), (3, 1), (1, 2), (2, 2), (3, 2), (1, 3), (2, 3), (3, 3), (2, 4)]),
        ("diamond15", [(2, 0), (1, 1), (2, 1), (3, 1), (0, 2), (1, 2), (2, 2), (3, 2), (4, 2),  # 꽉 찬 마름모(연결, 15칸)
                       (1, 3), (2, 3), (3, 3), (1, 4), (2, 4), (3, 4)]),
    ]
    seen_sig: Set[Tuple] = set()
    out: List[Unit] = []
    for name, cells in cand:
        if not cells or len(set(map(tuple, cells))) % 3 != 0:  # 유니크 셀 기준 ÷3
            continue
        if not is_connected(cells):  # [핵심] 끊긴 유닛 배제 — 흩어짐 방지
            continue
        u = Unit(name, cells)
        if not (3 <= u.size <= 15):
            continue
        if max(u.w, u.h) > 5 or u.density() < 0.45:  # bbox·밀도 게이트
            continue
        if u.cells in seen_sig:
            continue
        seen_sig.add(u.cells)
        out.append(u)
    return out


# ── 영속 (data/unit_templates.json) ──
_STORE = os.path.normpath(os.path.join(os.path.dirname(__file__), "..", "..", "data", "unit_templates.json"))
_CACHE: List[Unit] = []
_MTIME: float = -1.0


def _load() -> List[Unit]:
    """json 있으면 로드, 없으면 기본 시드 후 저장. 파일 변경 시 자동 갱신."""
    global _CACHE, _MTIME
    try:
        mtime = os.path.getmtime(_STORE)
        if _CACHE and mtime == _MTIME:
            return _CACHE
        with open(_STORE, encoding="utf-8") as f:
            data = json.load(f)
        units = []
        dirty = False
        for d in data.get("units", []):
            cells = [tuple(c) for c in d.get("cells", [])]
            uniq = {tuple(c) for c in cells}
            # [핵심] 연결·÷3(유니크)·3~15칸만 로드. 끊긴/중복 유닛은 흩어짐 유발 → 제외 + 저장 정리.
            if uniq and len(uniq) % 3 == 0 and 3 <= len(uniq) <= 15 and is_connected(uniq):
                units.append(Unit(d["name"], cells))
            else:
                dirty = True
        if units:
            if dirty:  # 불량 유닛 걸러낸 뒤 정리본 저장
                _save(units)
                try:
                    mtime = os.path.getmtime(_STORE)
                except OSError:
                    pass
            _CACHE, _MTIME = units, mtime
            return units
    except (OSError, ValueError, KeyError):
        pass
    # 시드
    units = _default_units()
    _save(units)
    try:
        _MTIME = os.path.getmtime(_STORE)
    except OSError:
        _MTIME = -1.0
    _CACHE = units
    return units


def _save(units: List[Unit]) -> None:
    os.makedirs(os.path.dirname(_STORE), exist_ok=True)
    with open(_STORE, "w", encoding="utf-8") as f:
        json.dump({"units": [u.to_dict() for u in units]}, f, ensure_ascii=False, indent=1)
    global _MTIME, _CACHE
    _CACHE = units
    try:
        _MTIME = os.path.getmtime(_STORE)
    except OSError:
        _MTIME = -1.0


def all_units() -> List[Unit]:
    return _load()


def units_by_size() -> Dict[int, List[Unit]]:
    out: Dict[int, List[Unit]] = {}
    for u in _load():
        out.setdefault(u.size, []).append(u)
    return out


def available_sizes() -> List[int]:
    return sorted(units_by_size().keys())


def units_for_budget(budget: int) -> List[int]:
    """예산(÷3)을 가용 유닛 크기로 분해. 큰 것 우선(밀집·큰 모양)."""
    budget = max(0, (budget // 3) * 3)
    sizes = sorted(units_by_size().keys(), reverse=True)  # 큰 것 우선
    out: List[int] = []
    for sz in sizes:
        while budget >= sz:
            out.append(sz)
            budget -= sz
    return out


# CRUD (편집용)
def save_unit(name: str, cells: List[Cell]) -> Tuple[bool, str]:
    uniq = {tuple(c) for c in cells}
    if not uniq or len(uniq) % 3 != 0:
        return False, "타일수가 3의 배수여야 함(÷3)"
    if len(uniq) < 3 or len(uniq) > 15:
        return False, "3~15칸 범위"
    if not is_connected(uniq):  # [핵심] 끊긴 유닛 저장 거부 — 위층 흩어짐 방지
        return False, "유닛 셀이 상하좌우로 모두 연결돼야 함(대각선/고립 불가)"
    cells = [tuple(c) for c in uniq]
    u = Unit(name, cells)
    units = [x for x in _load() if x.name != name]
    units.append(u)
    _save(units)
    return True, "saved"


def delete_unit(name: str) -> bool:
    units = _load()
    left = [u for u in units if u.name != name]
    if len(left) == len(units):
        return False
    _save(left)
    return True


def reset_units() -> int:
    units = _default_units()
    _save(units)
    return len(units)


if __name__ == "__main__":
    us = all_units()
    print(f"units: {len(us)}")
    for u in us:
        assert u.size % 3 == 0, u.name
        print(f"  {u.name:12} {u.size:2}칸 {u.w}x{u.h} d{u.density():.2f}")
    print("sizes:", available_sizes())
    print("budget 30:", units_for_budget(30))
