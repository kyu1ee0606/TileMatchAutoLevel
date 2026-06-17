"""
[v16 🅑] 절차적 패턴 모양 생성기 (÷3 보장 + 미적 스코어링).

수동 ASCII/custom_patterns 라이브러리를 사람이 일일이 찍던 방식의 한계(다양성·÷3 누락)를
대체한다. 대칭 기반으로 다양한 모양을 절차적으로 생성하고, 각 후보의 채움 셀 수를 **정확히
3의 배수**로 보정해 레벨 생성 시 `_finalize_divisibility_guarantee`가 타일을 떨어뜨리지 않도록
한다(= 시각적 모양 보존). 미적 점수(대칭·연결성·단일홀 없음·채움률)로 랭킹해 상위 후보만 반환.

설계 메모:
- positions는 기존 라이브러리와 동일한 "x_y" 문자열 포맷 (custom_patterns.json 호환).
- grid_size G는 '가시 footprint'(4~7). 레벨 parity(짝수층 +1)와 무관하게 모양 자체를 정의한다.
- ÷3 보정은 '제거 우선'(돌출부/저연결 셀) — 추가는 새 홀/비대칭을 만들기 쉬워 차선.
- 단일 셀 빈 구멍(solid 블록 한가운데 1칸 비는 것)은 사용자가 지적한 '깨진 비주얼'의 핵심이라
  생성 단계에서 메우고, 점수에서도 강하게 감점한다.
"""
from __future__ import annotations

import math
import random
from typing import Dict, List, Optional, Set, Tuple

Cell = Tuple[int, int]

SYMMETRY_MODES = ("both", "h", "v", "rot180", "quad", "none")
_NEI4 = ((1, 0), (-1, 0), (0, 1), (0, -1))


# ───────────────────────── 대칭 ─────────────────────────
def _orbit(x: int, y: int, g: int, mode: str) -> Set[Cell]:
    """대칭군 하에서 (x,y)의 궤도(자기 자신 포함)."""
    pts: Set[Cell] = {(x, y)}
    mx, my = g - 1 - x, g - 1 - y
    if mode in ("h", "both", "quad"):
        pts.add((mx, y))
    if mode in ("v", "both", "quad"):
        pts.add((x, my))
    if mode in ("both", "rot180", "quad"):
        pts.add((mx, my))
    if mode == "quad":  # 4-fold 회전대칭(정사각 전제): 전치 추가
        for px, py in list(pts):
            pts.add((py, px))
            pts.add((g - 1 - py, g - 1 - px))
    return pts


def _symmetrize(cells: Set[Cell], g: int, mode: str) -> Set[Cell]:
    out: Set[Cell] = set()
    for (x, y) in cells:
        out |= _orbit(x, y, g, mode)
    return out


# ──────────────────── 연결성/홀 유틸 ────────────────────
def _components(cells: Set[Cell]) -> List[Set[Cell]]:
    """4-연결 컴포넌트 분해."""
    seen: Set[Cell] = set()
    comps: List[Set[Cell]] = []
    for c in cells:
        if c in seen:
            continue
        stack = [c]
        comp: Set[Cell] = set()
        while stack:
            cur = stack.pop()
            if cur in seen:
                continue
            seen.add(cur)
            comp.add(cur)
            cx, cy = cur
            for dx, dy in _NEI4:
                nb = (cx + dx, cy + dy)
                if nb in cells and nb not in seen:
                    stack.append(nb)
        comps.append(comp)
    return comps


def _largest_component(cells: Set[Cell]) -> Set[Cell]:
    comps = _components(cells)
    return max(comps, key=len) if comps else set()


def _single_holes(cells: Set[Cell], g: int) -> Set[Cell]:
    """4방향이 모두 채워진(또는 그리드 밖) 빈 셀 = '깨진' 단일 구멍."""
    holes: Set[Cell] = set()
    if not cells:
        return holes
    xs = [c[0] for c in cells]
    ys = [c[1] for c in cells]
    x0, x1, y0, y1 = min(xs), max(xs), min(ys), max(ys)
    for y in range(y0, y1 + 1):
        for x in range(x0, x1 + 1):
            if (x, y) in cells:
                continue
            surrounded = True
            for dx, dy in _NEI4:
                nb = (x + dx, y + dy)
                # 바운딩박스 내부에서 빈 이웃이 있으면 단일홀 아님
                if x0 <= nb[0] <= x1 and y0 <= nb[1] <= y1 and nb not in cells:
                    surrounded = False
                    break
            if surrounded:
                holes.add((x, y))
    return holes


def _fill_single_holes(cells: Set[Cell], g: int) -> Set[Cell]:
    out = set(cells)
    for _ in range(4):  # 메우면 새 홀이 생길 수 있어 몇 번 반복
        holes = _single_holes(out, g)
        if not holes:
            break
        out |= holes
    return out


# ──────────────────── 모양 생성 전략 ────────────────────
def _strat_blob(g: int, rng: random.Random, fill: float) -> Set[Cell]:
    """중심에서 반경 노이즈를 준 둥근 덩어리."""
    cx, cy = (g - 1) / 2, (g - 1) / 2
    base_r = math.sqrt(fill * g * g / math.pi)
    cells: Set[Cell] = set()
    for y in range(g):
        for x in range(g):
            d = math.hypot(x - cx, y - cy)
            jitter = rng.uniform(-0.6, 0.6)
            if d <= base_r + jitter:
                cells.add((x, y))
    return cells


def _strat_diamond(g: int, rng: random.Random, fill: float) -> Set[Cell]:
    cx, cy = (g - 1) / 2, (g - 1) / 2
    r = (fill * g * g / 2) ** 0.5 + rng.uniform(-0.3, 0.5)
    return {(x, y) for y in range(g) for x in range(g)
            if abs(x - cx) + abs(y - cy) <= r}


def _strat_ring(g: int, rng: random.Random, fill: float) -> Set[Cell]:
    cx, cy = (g - 1) / 2, (g - 1) / 2
    outer = math.sqrt((fill + 0.25) * g * g / math.pi)
    inner = max(0.8, outer - rng.uniform(1.0, 1.8))
    return {(x, y) for y in range(g) for x in range(g)
            if inner <= math.hypot(x - cx, y - cy) <= outer}


def _strat_random(g: int, rng: random.Random, fill: float) -> Set[Cell]:
    """기본영역 무작위 채움(대칭화 전제) — 유기적 다양성."""
    half = (g + 1) // 2
    cells: Set[Cell] = set()
    for y in range(g):
        for x in range(half):
            if rng.random() < fill:
                cells.add((x, y))
    return cells


def _strat_frame(g: int, rng: random.Random, fill: float) -> Set[Cell]:
    """테두리 + 내부 일부 — 액자형."""
    cells = {(x, y) for x in range(g) for y in range(g)
             if x in (0, g - 1) or y in (0, g - 1)}
    for y in range(1, g - 1):
        for x in range(1, g - 1):
            if rng.random() < max(0.0, fill - 0.4):
                cells.add((x, y))
    return cells


_STRATS = (_strat_blob, _strat_diamond, _strat_ring, _strat_random, _strat_frame)


# ──────────────────── 모티프(인식 가능한 '특정 모양') ────────────────────
# 비대칭 모드에서 문자·화살표·기호 같은 '특정 모양을 나타내는 창의적 배치'를 생성한다.
# 정규화 좌표(0~1, y는 아래로 증가)의 선분(stroke)/다각형(fill)으로 정의 → 임의 g로 래스터화해
# 모든 사이즈에 일관된 모양을 만든다. 일부는 좌우/상하 비대칭이라 'none' 모드 다양성을 크게 늘린다.

def _pt_seg_dist(px: float, py: float, x0: float, y0: float, x1: float, y1: float) -> float:
    dx, dy = x1 - x0, y1 - y0
    if dx == 0 and dy == 0:
        return math.hypot(px - x0, py - y0)
    t = max(0.0, min(1.0, ((px - x0) * dx + (py - y0) * dy) / (dx * dx + dy * dy)))
    return math.hypot(px - (x0 + t * dx), py - (y0 + t * dy))


def _raster_strokes(g: int, segs: List[Tuple[float, float, float, float]], thick: float) -> Set[Cell]:
    """선분 집합을 g×g 격자에 두께 thick(셀 단위)로 래스터화."""
    cells: Set[Cell] = set()
    for x in range(g):
        cxp, cyp = x + 0.5, 0.0
        for y in range(g):
            cyp = y + 0.5
            for (a, b, c, d) in segs:
                if _pt_seg_dist(cxp, cyp, a * g, b * g, c * g, d * g) <= thick:
                    cells.add((x, y))
                    break
    return cells


def _fill_polygon(g: int, poly: List[Tuple[float, float]]) -> Set[Cell]:
    """정규화 다각형 내부를 g×g 격자로 채움(짝수-홀수 규칙)."""
    pts = [(px * g, py * g) for px, py in poly]
    cells: Set[Cell] = set()
    n = len(pts)
    for x in range(g):
        for y in range(g):
            px, py = x + 0.5, y + 0.5
            inside = False
            j = n - 1
            for i in range(n):
                xi, yi = pts[i]
                xj, yj = pts[j]
                if ((yi > py) != (yj > py)) and (px < (xj - xi) * (py - yi) / (yj - yi + 1e-9) + xi):
                    inside = not inside
                j = i
            if inside:
                cells.add((x, y))
    return cells


def _thick(g: int) -> float:
    return max(0.6, 0.135 * g)


# 모티프 정의: 이름 → (종류, 데이터). stroke=선분리스트, fill=다각형.
_MOTIF_STROKES: Dict[str, List[Tuple[float, float, float, float]]] = {
    "L": [(0.30, 0.12, 0.30, 0.86), (0.30, 0.86, 0.80, 0.86)],
    "T": [(0.15, 0.18, 0.85, 0.18), (0.50, 0.18, 0.50, 0.86)],
    "F": [(0.32, 0.12, 0.32, 0.88), (0.32, 0.12, 0.78, 0.12), (0.32, 0.48, 0.68, 0.48)],
    "E": [(0.32, 0.12, 0.32, 0.88), (0.32, 0.12, 0.78, 0.12), (0.32, 0.50, 0.68, 0.50), (0.32, 0.88, 0.78, 0.88)],
    "H": [(0.25, 0.12, 0.25, 0.88), (0.75, 0.12, 0.75, 0.88), (0.25, 0.50, 0.75, 0.50)],
    "Z": [(0.20, 0.16, 0.80, 0.16), (0.80, 0.16, 0.20, 0.86), (0.20, 0.86, 0.80, 0.86)],
    "N": [(0.25, 0.88, 0.25, 0.12), (0.25, 0.12, 0.78, 0.88), (0.78, 0.88, 0.78, 0.12)],
    "Y": [(0.20, 0.12, 0.50, 0.50), (0.80, 0.12, 0.50, 0.50), (0.50, 0.50, 0.50, 0.88)],
    "X": [(0.20, 0.16, 0.80, 0.84), (0.80, 0.16, 0.20, 0.84)],
    "arrow_up": [(0.50, 0.88, 0.50, 0.16), (0.50, 0.16, 0.26, 0.44), (0.50, 0.16, 0.74, 0.44)],
    "arrow_ne": [(0.18, 0.86, 0.82, 0.20), (0.82, 0.20, 0.50, 0.20), (0.82, 0.20, 0.82, 0.54)],
    "check": [(0.18, 0.55, 0.42, 0.80), (0.42, 0.80, 0.82, 0.22)],
    "bolt": [(0.62, 0.10, 0.34, 0.52), (0.34, 0.52, 0.56, 0.52), (0.56, 0.52, 0.30, 0.90)],
    "plus": [(0.50, 0.16, 0.50, 0.84), (0.18, 0.50, 0.82, 0.50)],
    "flag": [(0.26, 0.10, 0.26, 0.90), (0.26, 0.14, 0.78, 0.14), (0.78, 0.14, 0.78, 0.46), (0.78, 0.46, 0.26, 0.46)],
    "step": [(0.18, 0.85, 0.40, 0.85), (0.40, 0.85, 0.40, 0.58), (0.40, 0.58, 0.62, 0.58), (0.62, 0.58, 0.62, 0.30), (0.62, 0.30, 0.84, 0.30)],
}
_MOTIF_FILLS: Dict[str, List[Tuple[float, float]]] = {
    "triangle": [(0.5, 0.10), (0.90, 0.88), (0.10, 0.88)],
    "tri_right": [(0.14, 0.12), (0.86, 0.5), (0.14, 0.88)],
    "tri_corner": [(0.12, 0.12), (0.88, 0.12), (0.12, 0.88)],   # 비대칭 직각삼각형
    "heart": [(0.5, 0.32), (0.30, 0.12), (0.12, 0.30), (0.5, 0.90), (0.88, 0.30), (0.70, 0.12)],
}
_MOTIF_NAMES: List[str] = list(_MOTIF_STROKES.keys()) + list(_MOTIF_FILLS.keys())


def _make_motif(name: str, g: int) -> Set[Cell]:
    if name in _MOTIF_STROKES:
        return _raster_strokes(g, _MOTIF_STROKES[name], _thick(g))
    if name in _MOTIF_FILLS:
        return _fill_polygon(g, _MOTIF_FILLS[name])
    return set()


# ──────────────────── ÷3 보정 ────────────────────
def _removal_priority(cells: Set[Cell]) -> List[Cell]:
    """제거 우선순위: 채워진 이웃이 적은(돌출/끝) 셀부터. 동률은 바깥쪽부터."""
    if not cells:
        return []
    cx = sum(c[0] for c in cells) / len(cells)
    cy = sum(c[1] for c in cells) / len(cells)

    def deg(c: Cell) -> int:
        return sum(1 for dx, dy in _NEI4 if (c[0] + dx, c[1] + dy) in cells)

    return sorted(cells, key=lambda c: (deg(c), -math.hypot(c[0] - cx, c[1] - cy)))


def _enforce_div3(cells: Set[Cell], g: int) -> Optional[Set[Cell]]:
    """채움 수를 정확히 ÷3으로. 연결성 유지하며 돌출부 r개 제거. 실패 시 None."""
    cur = set(cells)
    r = len(cur) % 3
    if r == 0:
        return cur if cur else None
    # 제거 후보를 우선순위대로 시도하되, 제거가 컴포넌트를 쪼개지 않는 것만 채택
    removed = 0
    for c in _removal_priority(cur):
        if removed >= r:
            break
        trial = cur - {c}
        if not trial:
            continue
        # 연결성 보존(원래 단일 컴포넌트였다면 유지)
        if len(_components(trial)) <= max(1, len(_components(cur))):
            cur = trial
            removed += 1
    if removed < r:
        # 제거로 못 맞추면 인접 셀 추가로 보정 (3 - r)개
        need = 3 - r
        frontier = sorted(
            {(c[0] + dx, c[1] + dy) for c in cur for dx, dy in _NEI4
             if 0 <= c[0] + dx < g and 0 <= c[1] + dy < g and (c[0] + dx, c[1] + dy) not in cur},
            key=lambda nb: -sum(1 for dx, dy in _NEI4 if (nb[0] + dx, nb[1] + dy) in cur),
        )
        for nb in frontier:
            if need <= 0:
                break
            cur.add(nb)
            need -= 1
        if len(cur) % 3 != 0:
            return None
    return cur


# ──────────────────── 미적 스코어 ────────────────────
def _symmetry_score(cells: Set[Cell], g: int) -> float:
    if not cells:
        return 0.0
    best = 0.0
    for mode in ("both", "h", "v", "rot180"):
        match = sum(1 for c in cells if _orbit(c[0], c[1], g, mode) <= cells)
        best = max(best, match / len(cells))
    return best


def _compactness(cells: Set[Cell]) -> float:
    """윤곽 매끄러움/둥글기. 같은 면적에서 둘레가 짧을수록(=둥글고 깔끔할수록) 1에 가까움.
    들쭉날쭉한 윤곽/가시 모양은 둘레가 길어 낮은 점수."""
    area = len(cells)
    if area == 0:
        return 0.0
    perimeter = 0
    for (x, y) in cells:
        for dx, dy in _NEI4:
            if (x + dx, y + dy) not in cells:
                perimeter += 1
    if perimeter <= 0:
        return 1.0
    ideal = 4.0 * math.sqrt(area)  # 정사각/원형 근사의 이상 둘레
    return max(0.0, min(1.0, ideal / perimeter))


def _score(cells: Set[Cell], g: int, fill_range: Tuple[float, float]) -> Tuple[float, Dict]:
    area = len(cells)
    if area == 0:
        return 0.0, {}
    sym = _symmetry_score(cells, g)
    comps = _components(cells)
    conn = 1.0 if len(comps) == 1 else max(0.0, 1.0 - 0.34 * (len(comps) - 1))
    holes = len(_single_holes(cells, g))
    solidity = max(0.0, 1.0 - 0.5 * holes)  # 단일홀 1개당 -0.5 (강한 감점)
    compact = _compactness(cells)           # 윤곽 매끄러움(둥글기)
    fr = area / (g * g)
    lo, hi = fill_range
    mid = (lo + hi) / 2
    fill_score = math.exp(-((fr - mid) ** 2) / (2 * (0.18 ** 2)))
    # 비주얼 품질: 대칭 우선 + 단일컴포넌트 + 단일홀 없음 + 매끄러운 윤곽 + 적정 채움
    composite = 0.34 * sym + 0.20 * conn + 0.20 * solidity + 0.16 * compact + 0.10 * fill_score
    return composite, {
        "symmetry": round(sym, 3),
        "connectivity": round(conn, 3),
        "solidity": round(solidity, 3),
        "compactness": round(compact, 3),
        "single_holes": holes,
        "fill_rate": round(fr, 3),
        "components": len(comps),
    }


# ──────────────────── 공개 API ────────────────────
def _to_positions(cells: Set[Cell]) -> List[str]:
    return [f"{x}_{y}" for (x, y) in sorted(cells, key=lambda c: (c[1], c[0]))]


def _grid_of(cells: Set[Cell], g: int) -> List[List[int]]:
    grid = [[0] * g for _ in range(g)]
    for (x, y) in cells:
        if 0 <= x < g and 0 <= y < g:
            grid[y][x] = 1
    return grid


def _make_cells(g: int, strat, mode: str, fill: float, rng: random.Random) -> Optional[Set[Cell]]:
    """단일 사이즈 모양 1개 생성: 전략→대칭화→연결성→단일홀메움→÷3 보장. 실패 시 None."""
    cells = _symmetrize(strat(g, rng, fill), g, mode)
    cells = _largest_component(cells)
    cells = _fill_single_holes(cells, g)
    if len(cells) < 6 or len(cells) > g * g:
        return None
    cells = _enforce_div3(cells, g)
    if not cells or len(cells) % 3 != 0:
        return None
    cells = _fill_single_holes(cells, g)
    if len(cells) % 3 != 0:
        cells = _enforce_div3(cells, g)
        if not cells or len(cells) % 3 != 0:
            return None
    return cells


def _make_motif_cells(name: str, g: int) -> Optional[Set[Cell]]:
    """모티프(특정 모양) 1개를 사이즈 g로: 래스터화→연결성→÷3 보장. 모양 보존 위해
    단일홀 메움은 하되 대칭화는 하지 않는다(비대칭 모양 유지). 실패 시 None."""
    cells = _make_motif(name, g)
    cells = _largest_component(cells)         # 끊긴 획 조각 제거
    cells = _fill_single_holes(cells, g)
    if len(cells) < 5 or len(cells) > g * g:
        return None
    cells = _enforce_div3(cells, g)           # 돌출부 제거로 ÷3(획 끝부터 → 모양 영향 최소)
    if not cells or len(cells) % 3 != 0:
        return None
    return cells


def synthesize_concepts(
    min_grid: int,
    max_grid: int,
    count: int = 12,
    symmetry: Optional[str] = None,
    fill_range: Tuple[float, float] = (0.45, 0.85),
    seed: Optional[int] = None,
    oversample: int = 8,
) -> List[Dict]:
    """
    [v16 🅑] '모양 컨셉' 묶음 생성. 한 컨셉 = (전략·대칭·채움률 고정)을 [min_grid..max_grid]
    모든 그리드 사이즈로 렌더한 변형 묶음. 레벨은 레이어마다 grid/grid+1 사이즈를 번갈아 쓰므로
    한 인덱스에 필요한 모든 사이즈 변형이 있어야 일관된 모양으로 렌더된다.

    각 변형은 ÷3 보장. 컨셉은 모든 사이즈를 빠짐없이 채워야 채택 가능(불완전 컨셉은 폐기).

    Returns:
        [{symmetry, strategy, score, sizes:[g...], variants:[{grid_size,positions,count,grid,breakdown}]}]
        (score 내림차순)
    """
    min_grid = max(4, int(min_grid))
    max_grid = max(min_grid, int(max_grid))
    sizes = list(range(min_grid, max_grid + 1))
    rng = random.Random(seed)
    strat_names = {s: n for s, n in zip(_STRATS, ("blob", "diamond", "ring", "random", "frame"))}

    concepts: List[Dict] = []
    seen_concept: Set[Tuple] = set()
    attempts = max(count * oversample, 24)
    for _ in range(attempts):
        # 모드/생성방식 결정.
        # - 'none' 요청: 항상 모티프(특정 모양) → 창의적·인식 가능한 비대칭 배치.
        # - 대칭 모드 요청: 기하 전략 + 해당 대칭.
        # - 자동(None): 40% 모티프(비대칭 특정모양) + 60% 대칭 기하 → 둘 다 풍부히.
        if symmetry == "none":
            use_motif, mode = True, "none"
        elif symmetry in SYMMETRY_MODES:
            use_motif, mode = False, symmetry
        else:
            if rng.random() < 0.4:
                use_motif, mode = True, "none"
            else:
                use_motif, mode = False, rng.choice(("both", "h", "v", "rot180", "quad"))

        if use_motif:
            motif = rng.choice(_MOTIF_NAMES)
            strat_label = f"motif:{motif}"
        else:
            strat = rng.choice(_STRATS)
            strat_label = strat_names[strat]
        fill = rng.uniform(*fill_range)
        cseed = rng.randint(0, 2**31 - 1)  # 컨셉 시드: 모든 사이즈에 동일 적용 → 일관성

        variants: List[Dict] = []
        ok = True
        for g in sizes:
            if use_motif:
                cells = _make_motif_cells(motif, g)  # 결정적: 모든 사이즈 동일 모양
            else:
                # 같은 컨셉 파라미터를 모든 사이즈에 적용. 사이즈별 fill 미세 변동 허용(÷3 보조).
                cells = None
                for fadj in (0.0, -0.07, 0.07, -0.14, 0.14):
                    f = min(0.92, max(0.25, fill + fadj))
                    cells = _make_cells(g, strat, mode, f, random.Random(cseed))
                    if cells:
                        break
            if not cells:
                ok = False
                break
            sc, bd = _score(cells, g, fill_range)
            variants.append({
                "grid_size": g,
                "positions": _to_positions(cells),
                "count": len(cells),
                "grid": _grid_of(cells, g),
                "score": round(sc, 4),
                "breakdown": bd,
            })
        if not ok or len(variants) != len(sizes):
            continue

        # 컨셉 중복 제거: 가장 큰 사이즈 변형의 셀 시그니처 기준
        big = variants[-1]
        sig = (mode, strat_label, tuple(sorted(tuple(map(int, p.split("_"))) for p in big["positions"])))
        if sig in seen_concept:
            continue
        seen_concept.add(sig)

        agg = round(sum(v["score"] for v in variants) / len(variants), 4)
        concepts.append({
            "symmetry": mode,
            "strategy": strat_label,
            "score": agg,
            "sizes": sizes,
            "variants": variants,
        })

    concepts.sort(key=lambda c: c["score"], reverse=True)

    # [v16] 매 생성마다 다른 모양이 나오도록 '품질 풀에서 시드 기반 무작위 추출'.
    # 점수 상위만 결정적으로 반환하면(특히 결정적 모티프) 시드를 바꿔도 같은 셋이 나온다.
    # → 점수 상위 풀(품질 보장)을 만든 뒤 rng로 섞어 다양성 선택 → 시드별로 다른 셋.
    pool_size = min(len(concepts), max(count * 3, count + 12))
    pool = concepts[:pool_size]
    rng.shuffle(pool)

    # 다양성 선택: 최대 사이즈 변형의 Jaccard 유사도로 중복 컨셉 억제
    def _big_cells(c: Dict) -> Set[Cell]:
        return {tuple(map(int, p.split("_"))) for p in c["variants"][-1]["positions"]}

    picked: List[Dict] = []
    picked_cells: List[Set[Cell]] = []
    for c in pool:
        if len(picked) >= count:
            break
        cs = _big_cells(c)
        if any(len(cs & pc) / (len(cs | pc) or 1) >= 0.82 for pc in picked_cells):
            continue
        picked.append(c)
        picked_cells.append(cs)
    if len(picked) < count:
        chosen = {id(p) for p in picked}
        for c in pool + concepts:  # 풀 우선, 모자라면 전체에서 보충
            if len(picked) >= count:
                break
            if id(c) not in chosen:
                picked.append(c)
                chosen.add(id(c))
    # 표시는 품질 우선(점수 내림차순) — '무엇을' 뽑을지는 시드 기반, '순서'는 점수.
    picked = picked[:count]
    picked.sort(key=lambda c: c["score"], reverse=True)
    return picked


def synthesize_patterns(
    max_grid: int,
    count: int = 12,
    min_grid: Optional[int] = None,
    symmetry: Optional[str] = None,
    fill_range: Tuple[float, float] = (0.45, 0.85),
    seed: Optional[int] = None,
    oversample: int = 8,
) -> List[Dict]:
    """
    절차적으로 ÷3-보장 패턴 후보를 생성·랭킹해 상위 `count`개 반환.

    Args:
        max_grid: 최대 그리드 한 변(가시 footprint, 보통 4~7). 4로 클램프 하한.
        count: 반환할 후보 수.
        min_grid: 최소 그리드(미지정 시 max_grid와 동일 → 단일 사이즈).
        symmetry: 고정 대칭모드(SYMMETRY_MODES). None이면 모드를 다양하게 섞음.
        fill_range: 목표 채움률 범위(미적 점수 중심).
        seed: 재현용 시드.
        oversample: 후보당 과샘플 배수(많이 만들고 상위만 채택 → 품질↑·다양성↑).

    Returns:
        [{positions, grid_size, count, symmetry, score, breakdown}] (score 내림차순)
    """
    max_grid = max(4, int(max_grid))
    min_grid = max(4, int(min_grid)) if min_grid else max_grid
    if min_grid > max_grid:
        min_grid = max_grid
    rng = random.Random(seed)

    raw: List[Dict] = []
    seen_sig: Set[Tuple] = set()
    attempts = max(count * oversample, 24)
    for _ in range(attempts):
        g = rng.randint(min_grid, max_grid)
        mode = symmetry if symmetry in SYMMETRY_MODES else rng.choice(("both", "h", "v", "rot180", "quad"))
        fill = rng.uniform(*fill_range)
        strat = rng.choice(_STRATS)

        cells = _symmetrize(strat(g, rng, fill), g, mode)
        if mode != "none":
            # 일부 전략은 이미 대칭(blob/diamond/ring) → 무해. random/frame은 대칭화 필수
            pass
        cells = _largest_component(cells)          # 연결성 확보
        cells = _fill_single_holes(cells, g)       # 깨진 단일홀 제거
        if len(cells) < 6 or len(cells) > g * g - 0:
            continue
        cells = _enforce_div3(cells, g)            # ÷3 보장
        if not cells or len(cells) % 3 != 0:
            continue
        cells = _fill_single_holes(cells, g)
        if len(cells) % 3 != 0:                    # 홀 메우며 깨졌으면 재보정
            cells = _enforce_div3(cells, g)
            if not cells or len(cells) % 3 != 0:
                continue

        sig = (g, tuple(sorted(cells)))
        if sig in seen_sig:
            continue
        seen_sig.add(sig)

        sc, bd = _score(cells, g, fill_range)
        raw.append({
            "positions": _to_positions(cells),
            "grid_size": g,
            "count": len(cells),
            "symmetry": mode,
            "score": round(sc, 4),
            "breakdown": bd,
        })

    raw.sort(key=lambda r: r["score"], reverse=True)

    # 다양성 선택: 고점수 우선이되 이미 뽑힌 후보와 너무 유사(Jaccard≥0.82)하면 건너뜀.
    # 후보가 부족하면 유사도 제약을 풀어 count를 채운다.
    def _cells_of(r: Dict) -> Set[Cell]:
        return {tuple(map(int, p.split("_"))) for p in r["positions"]}

    picked: List[Dict] = []
    picked_cells: List[Tuple[int, Set[Cell]]] = []
    for r in raw:
        if len(picked) >= count:
            break
        cs = _cells_of(r)
        too_similar = False
        for g2, pc in picked_cells:
            if g2 != r["grid_size"]:
                continue
            inter = len(cs & pc)
            union = len(cs | pc) or 1
            if inter / union >= 0.82:
                too_similar = True
                break
        if not too_similar:
            picked.append(r)
            picked_cells.append((r["grid_size"], cs))
    # 다양성으로 모자라면 남은 고점수로 채움
    if len(picked) < count:
        chosen = {id(p) for p in picked}
        for r in raw:
            if len(picked) >= count:
                break
            if id(r) not in chosen:
                picked.append(r)
    return picked[:count]
