"""
[유닛 조립 레이어 생성 — S1] 소형 유닛 라이브러리 + 커버리지 valid_mask.

목적: 위층 STEP 축소본이 sparse(타일 미달) → 밀도 높은 소형 유닛(÷3·대칭·밀도≥70%)을
아래층이 받쳐주는 자리(valid_mask)에만 조립해 타일수·다양성 확보.

커버리지 오프셋은 generator.py `_is_position_covered_by_upper`(게임 FindAllUpperTiles 정본,
6789행)와 **동일 값** 사용. tune.py `_reveal_index` 와도 일치.
"""
from typing import Dict, List, Set, Tuple

Cell = Tuple[int, int]

# ── 커버리지 오프셋 (정본, generator.py:6789 = 게임 TileGroup.FindAllUpperTiles) ──
# is_blocked_by 의미: 하위 (col,row) 는 상위 (col+dx, row+dy) 에 덮인다.
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
    """상위 층에서 '받침(아래층 타일)이 있어 타일을 놓을 수 있는' 좌표 집합.

    원리: 상위 (ux,uy) 가 하위 (lx,ly) 를 덮으려면 (ux,uy) = (lx+dx, ly+dy) →
    (lx,ly) = (ux-dx, uy-dy). 이 하위 타일이 실제 존재하면 (ux,uy) 는 그 위에 얹힘(no-float).
    각 상위 칸이 하위 타일 1개 이상을 덮으면 floating 없음.
    """
    offsets = get_cover_offsets(lower_layer, upper_layer, lower_col, upper_col)
    mask: Set[Cell] = set()
    for ux in range(upper_col):
        for uy in range(upper_rows):
            for (dx, dy) in offsets:
                if (ux - dx, uy - dy) in lower_positions:
                    mask.add((ux, uy))
                    break
    return mask


# ── 소형 유닛 라이브러리 (÷3 · 밀도≥70%) ──
# 각 유닛 = 원점(0,0) 기준 상대 셀. bbox 최소화 정규화된 상태.
def _norm(cells: List[Cell]) -> Tuple[Cell, ...]:
    minx = min(c[0] for c in cells)
    miny = min(c[1] for c in cells)
    return tuple(sorted((x - minx, y - miny) for (x, y) in cells))


class Unit:
    __slots__ = ("name", "cells", "w", "h", "size")

    def __init__(self, name: str, cells: List[Cell]):
        self.name = name
        self.cells = _norm(cells)
        self.w = max(c[0] for c in self.cells) + 1
        self.h = max(c[1] for c in self.cells) + 1
        self.size = len(self.cells)

    def density(self) -> float:
        return self.size / (self.w * self.h)

    def placed(self, ox: int, oy: int) -> Set[Cell]:
        return {(x + ox, y + oy) for (x, y) in self.cells}


# Class-3 (3칸)
_U3 = [
    Unit("I3_h", [(0, 0), (1, 0), (2, 0)]),          # 1x3 가로 (100%)
    Unit("I3_v", [(0, 0), (0, 1), (0, 2)]),          # 3x1 세로 (100%)
    Unit("L3", [(0, 0), (0, 1), (1, 1)]),            # 2x2 코너 (75%)
    Unit("L3b", [(1, 0), (0, 1), (1, 1)]),           # 2x2 코너 반전 (75%)
]
# Class-6 (6칸)
_U6 = [
    Unit("R2x3", [(x, y) for x in range(2) for y in range(3)]),   # 2x3 꽉 (100%)
    Unit("R3x2", [(x, y) for x in range(3) for y in range(2)]),   # 3x2 꽉 (100%)
    Unit("P6", [(0, 0), (1, 0), (0, 1), (1, 1), (0, 2), (1, 2)]), # =R2x3 계열
    Unit("Step6", [(0, 0), (1, 0), (1, 1), (2, 1), (2, 2), (0, 1)]),  # 계단풍 (밀도 조정)
]
# Class-9 (9칸)
_U9 = [
    Unit("S3x3", [(x, y) for x in range(3) for y in range(3)]),   # 3x3 꽉 (100%)
    Unit("Plus9", [(1, 0), (0, 1), (1, 1), (2, 1), (1, 2), (0, 0), (2, 0), (0, 2), (2, 2)]),  # =3x3
    Unit("H9", [(0, 0), (0, 1), (0, 2), (2, 0), (2, 1), (2, 2), (1, 1), (1, 0), (1, 2)]),     # =3x3
]

# 밀도 게이트 통과분만 채택
_MIN_DENSITY = 0.70
UNITS_BY_SIZE: Dict[int, List[Unit]] = {
    3: [u for u in _U3 if u.density() >= _MIN_DENSITY],
    6: [u for u in _U6 if u.density() >= _MIN_DENSITY],
    9: [u for u in _U9 if u.density() >= _MIN_DENSITY],
}
ALL_UNITS: List[Unit] = [u for us in UNITS_BY_SIZE.values() for u in us]


def units_for_budget(budget: int) -> List[int]:
    """예산(타일수, 3배수)을 유닛 크기(3·6·9) 조합으로 분해. 큰 것 우선(밀집)."""
    budget = max(0, (budget // 3) * 3)
    out: List[int] = []
    for sz in (9, 6, 3):
        while budget >= sz and sz in UNITS_BY_SIZE and UNITS_BY_SIZE[sz]:
            out.append(sz)
            budget -= sz
    return out


# ── 자체 단위테스트 (착수 전 체크) ──
if __name__ == "__main__":
    ok = True
    # 1. 모든 유닛 ÷3 + 밀도≥70%
    for u in ALL_UNITS:
        if u.size % 3 != 0:
            print(f"FAIL ÷3: {u.name} size {u.size}"); ok = False
        if u.density() < _MIN_DENSITY:
            print(f"FAIL density: {u.name} {u.density():.2f}"); ok = False
    print(f"units: {[(u.name, u.size, round(u.density(),2)) for u in ALL_UNITS]}")

    # 2. valid_mask 정확성 — 홀짝 6·7 케이스
    # 하위 층0(col7, 짝수) 꽉참 → 상위 층1(col6, 홀수, 더 작음) valid_mask
    lower_full = {(x, y) for x in range(7) for y in range(7)}
    m = valid_support_mask(lower_full, 0, 1, 7, 6, 6)
    # 위작음 오프셋 {(-1,-1),(0,-1),(-1,0),(0,0)} → 상위(ux,uy) 덮는 하위 (ux+1,uy+1) 등 존재?
    # 하위 꽉참이므로 상위 전 칸 valid 기대 (6x6=36)
    print(f"mask(lower full 7x7 → upper 6x6): {len(m)} (expect 36)")
    if len(m) != 36:
        print("FAIL mask full"); ok = False

    # 3. 하위가 일부만(중앙 3x3) → 상위 valid_mask 축소 확인
    lower_partial = {(x, y) for x in range(2, 5) for y in range(2, 5)}  # 중앙 3x3
    m2 = valid_support_mask(lower_partial, 0, 1, 7, 6, 6)
    print(f"mask(lower 3x3 center → upper 6x6): {len(m2)} (>0, <36 expect)")
    if not (0 < len(m2) < 36):
        print("FAIL mask partial"); ok = False

    # 4. 예산 분해
    print(f"units_for_budget(24): {units_for_budget(24)} (sum={sum(units_for_budget(24))})")
    print(f"units_for_budget(20): {units_for_budget(20)} (sum={sum(units_for_budget(20))})")

    print("\n=== S1 CHECK:", "PASS ✅" if ok else "FAIL ❌", "===")
