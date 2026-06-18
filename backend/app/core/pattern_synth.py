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


def _tf_pt(x: float, y: float, rot: int, flip: bool) -> Tuple[float, float]:
    """정규화 좌표를 중심(0.5,0.5) 기준 변형: flip(좌우반전) 후 rot×90° 회전."""
    if flip:
        x = 1.0 - x
    dx, dy = x - 0.5, y - 0.5
    for _ in range(rot % 4):
        dx, dy = -dy, dx  # 90° 회전
    return 0.5 + dx, 0.5 + dy


def _make_motif(name: str, g: int, rot: int = 0, flip: bool = False, thick_mul: float = 1.0) -> Set[Cell]:
    """모티프를 회전/반전/두께 변형해 래스터화. 변형으로 ~20 기본형 → 수백 고유형 확장."""
    if name in _MOTIF_STROKES:
        segs = [(*_tf_pt(a, b, rot, flip), *_tf_pt(c, d, rot, flip))
                for (a, b, c, d) in _MOTIF_STROKES[name]]
        return _raster_strokes(g, segs, _thick(g) * thick_mul)
    if name in _MOTIF_FILLS:
        poly = [_tf_pt(px, py, rot, flip) for (px, py) in _MOTIF_FILLS[name]]
        return _fill_polygon(g, poly)
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


def _enforce_div3_symmetric(cells: Set[Cell], g: int, mode: str) -> Optional[Set[Cell]]:
    """대칭(mode) 유지하며 ÷3 보정. 외곽 셀의 '궤도(orbit)'를 통째로 제거 →
    한쪽만 깎여 비대칭/nick 되는 문제 방지. orbit 단위라 제거량이 곧 대칭 보존.
    단일 셀 깎기(_enforce_div3)와 달리 좌우/상하 균형 유지. 실패 시 일반 보정 폴백."""
    if mode == "none":
        return _enforce_div3(cells, g)
    cur = set(cells)
    r = len(cur) % 3
    if r == 0:
        return cur if cur else None

    def deg(c: Cell, s: Set[Cell]) -> int:
        return sum(1 for dx, dy in _NEI4 if (c[0] + dx, c[1] + dy) in s)

    cx = sum(c[0] for c in cur) / len(cur)
    cy = sum(c[1] for c in cur) / len(cur)
    # 후보 궤도: 외곽(저연결·바깥) 셀 기준, 중복 제거. 제거량 ≡ r(mod 3)인 궤도 우선.
    seen_orbit: Set[Tuple] = set()
    orbits: List[Set[Cell]] = []
    for c in sorted(cur, key=lambda c: (deg(c, cur), -math.hypot(c[0] - cx, c[1] - cy))):
        orb = _orbit(c[0], c[1], g, mode) & cur
        key = tuple(sorted(orb))
        if key in seen_orbit or not orb:
            continue
        seen_orbit.add(key)
        orbits.append(orb)

    # 단일 궤도 제거로 ÷3 + 연결성 유지되는 것 채택
    for orb in orbits:
        if len(orb) % 3 != r % 3:
            continue
        trial = cur - orb
        if not trial:
            continue
        if len(_components(trial)) <= max(1, len(_components(cur))) and len(trial) % 3 == 0:
            return trial
    # 두 궤도 조합 (작은 모양에서 단일로 안 맞을 때)
    for i in range(len(orbits)):
        for j in range(i + 1, len(orbits)):
            orb = orbits[i] | orbits[j]
            if len(orb) % 3 != r % 3:
                continue
            trial = cur - orb
            if trial and len(trial) % 3 == 0 and len(_components(trial)) <= max(1, len(_components(cur))):
                return trial
    # 대칭 보존 실패 → 일반 보정 폴백(÷3은 보장)
    return _enforce_div3(cur, g)


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


def _protrusion_count(cells: Set[Cell]) -> int:
    """채워진 이웃이 1개 이하인 셀 수 = 가시·스파이크·외톨이(=nick). 시각적 '찌그러짐' 핵심."""
    return sum(
        1 for c in cells
        if sum(1 for dx, dy in _NEI4 if (c[0] + dx, c[1] + dy) in cells) <= 1
    )


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
    spikes = _protrusion_count(cells)
    # 깔끔함: 가시/스파이크 셀이 적을수록 1. 면적 대비 비율로 평가(작은 모양 과민 방지).
    clean = max(0.0, 1.0 - spikes / max(4.0, area * 0.5))
    fr = area / (g * g)
    lo, hi = fill_range
    mid = (lo + hi) / 2
    fill_score = math.exp(-((fr - mid) ** 2) / (2 * (0.18 ** 2)))
    # 비주얼 품질(프로덕션): 대칭 + 단일컴포넌트 + 단일홀 없음 + 깔끔윤곽(가시 없음) + 적정채움.
    # compact(둥글기) 가중을 낮춰 '둥근 블롭 수렴' 완화, clean(가시 제거)을 크게.
    composite = (0.30 * sym + 0.16 * conn + 0.18 * solidity
                 + 0.20 * clean + 0.10 * compact + 0.06 * fill_score)
    return composite, {
        "symmetry": round(sym, 3),
        "connectivity": round(conn, 3),
        "solidity": round(solidity, 3),
        "compactness": round(compact, 3),
        "cleanliness": round(clean, 3),
        "single_holes": holes,
        "protrusions": spikes,
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
    """단일 사이즈 모양 1개 생성: 전략→대칭화→연결성→단일홀메움→대칭보존 ÷3 보장. 실패 시 None."""
    cells = _symmetrize(strat(g, rng, fill), g, mode)
    cells = _largest_component(cells)
    cells = _fill_single_holes(cells, g)
    if len(cells) < 6 or len(cells) > g * g:
        return None
    cells = _enforce_div3_symmetric(cells, g, mode)   # 대칭 유지하며 ÷3 (한쪽 깎임 방지)
    if not cells or len(cells) % 3 != 0:
        return None
    cells = _fill_single_holes(cells, g)
    if len(cells) % 3 != 0:
        cells = _enforce_div3_symmetric(cells, g, mode)
        if not cells or len(cells) % 3 != 0:
            return None
    return cells


def _make_motif_cells(name: str, g: int, rot: int = 0, flip: bool = False,
                      thick_mul: float = 1.0, sym_mode: Optional[str] = None) -> Optional[Set[Cell]]:
    """모티프(특정 모양) 1개를 사이즈 g·변형으로: 래스터화→(옵션)대칭화→연결성→÷3 보장.
    sym_mode 지정 시 해당 대칭으로 미러 → 좌우/상하 반듯한 '예쁜' 버전(프로덕션용).
    None이면 원형 모양 유지(비대칭 다양성). 실패 시 None."""
    cells = _make_motif(name, g, rot, flip, thick_mul)
    if sym_mode and sym_mode != "none":
        cells = _symmetrize(cells, g, sym_mode)       # 대칭 강제 → 항상 반듯
    cells = _largest_component(cells)         # 끊긴 획 조각 제거
    cells = _fill_single_holes(cells, g)
    if len(cells) < 5 or len(cells) > g * g:
        return None
    if sym_mode and sym_mode != "none":
        cells = _enforce_div3_symmetric(cells, g, sym_mode)  # 대칭 보존 ÷3
    else:
        cells = _enforce_div3(cells, g)       # 돌출부 제거로 ÷3(획 끝부터 → 모양 영향 최소)
    if not cells or len(cells) % 3 != 0:
        return None
    return cells


# ──────────────────── 템플릿 기반 변형 (사람 제작 라이브러리 씨앗) ────────────────────
# 사람이 손제작한 custom_patterns.json(인덱스 0~60)을 '씨앗'으로 회전·반전 변형해
# 창의적 모양을 만든다. 시작점이 이미 검증된 미려 모양이라 결과 품질이 추상 모티프보다 높다.
# 템플릿은 대부분 사이즈별(4x4~9x9) 변형을 이미 보유 → 번들 사이즈를 그대로 끌어 씀.

import os
import json as _json

_TEMPLATE_PATH = os.path.normpath(
    os.path.join(os.path.dirname(__file__), "..", "..", "data", "custom_patterns.json")
)
_TEMPLATES_CACHE: Optional[Dict[int, Dict[int, Set[Cell]]]] = None
_TEMPLATES_MTIME: float = 0.0


def _load_templates() -> Dict[int, Dict[int, Set[Cell]]]:
    """custom_patterns.json → {index: {grid_size: cells}}. 파일 변경 시 자동 갱신.
    인덱스 64+(synth 자동저장분)는 제외 → 사람 제작 0~60만 씨앗으로 사용. 없으면 {}."""
    global _TEMPLATES_CACHE, _TEMPLATES_MTIME
    try:
        mtime = os.path.getmtime(_TEMPLATE_PATH)
    except OSError:
        return {}
    if _TEMPLATES_CACHE is not None and mtime == _TEMPLATES_MTIME:
        return _TEMPLATES_CACHE
    out: Dict[int, Dict[int, Set[Cell]]] = {}
    try:
        with open(_TEMPLATE_PATH, encoding="utf-8") as f:
            data = _json.load(f)
    except (OSError, ValueError):
        return {}
    for key, val in data.items():
        try:
            idx = int(key.split("_", 1)[0])
        except ValueError:
            continue
        if idx >= 64:           # synth 자동저장분은 씨앗에서 제외(사람 제작만)
            continue
        positions = val.get("positions") if isinstance(val, dict) else val
        if not positions:
            continue
        cells = {tuple(map(int, p.split("_"))) for p in positions}
        if not cells:
            continue
        g = max(max(c) for c in cells) + 1
        out.setdefault(idx, {})[g] = cells
    _TEMPLATES_CACHE = out
    _TEMPLATES_MTIME = mtime
    return out


def _transform_cells(cells: Set[Cell], g: int, rot: int, flip: bool) -> Set[Cell]:
    """g×g 격자 내에서 셀 집합을 flip(좌우반전)→rot×90° 회전."""
    out: Set[Cell] = set()
    for (x, y) in cells:
        if flip:
            x = g - 1 - x
        for _ in range(rot % 4):
            x, y = g - 1 - y, x       # 90° 회전
        out.add((x, y))
    return out


def _rescale_cells(cells: Set[Cell], src_g: int, dst_g: int) -> Set[Cell]:
    """템플릿을 다른 그리드 사이즈로 최근접 리스케일(해당 사이즈 변형이 없을 때 폴백)."""
    if src_g == dst_g:
        return set(cells)
    out: Set[Cell] = set()
    for y in range(dst_g):
        for x in range(dst_g):
            sx = min(src_g - 1, int((x + 0.5) * src_g / dst_g))
            sy = min(src_g - 1, int((y + 0.5) * src_g / dst_g))
            if (sx, sy) in cells:
                out.add((x, y))
    return out


def _center_cells(cells: Set[Cell], g: int) -> Set[Cell]:
    """셀 집합의 바운딩박스를 g×g 격자 중앙으로 이동(변형 후 구석 쏠림 방지)."""
    if not cells:
        return cells
    xs = [c[0] for c in cells]
    ys = [c[1] for c in cells]
    w = max(xs) - min(xs) + 1
    h = max(ys) - min(ys) + 1
    ox = (g - w) // 2 - min(xs)
    oy = (g - h) // 2 - min(ys)
    return {(x + ox, y + oy) for (x, y) in cells}


def _make_template_cells(idx: int, g: int, rot: int, flip: bool,
                         templates: Dict[int, Dict[int, Set[Cell]]]) -> Optional[Set[Cell]]:
    """템플릿 idx를 사이즈 g·변형(rot/flip)으로: 사이즈 변형 우선, 없으면 최근접 리스케일.
    변형→중앙정렬→연결성→단일홀메움→÷3 보장. 실패 시 None."""
    sizes = templates.get(idx)
    if not sizes:
        return None
    base = sizes.get(g)
    if base is None:                       # 해당 사이즈 없으면 가장 가까운 사이즈에서 리스케일
        src_g = min(sizes.keys(), key=lambda s: abs(s - g))
        base = _rescale_cells(sizes[src_g], src_g, g)
    cells = _transform_cells(base, g, rot, flip)
    cells = _center_cells(cells, g)        # 변형으로 틀어진 위치를 중앙 재정렬
    cells = _largest_component(cells)
    cells = _fill_single_holes(cells, g)
    if len(cells) < 5 or len(cells) > g * g:
        return None
    if len(cells) % 3 != 0:
        cells = _enforce_div3(cells, g)    # 템플릿 대칭축 불명 → 일반 보정(돌출부 제거)
    if not cells or len(cells) % 3 != 0:
        return None
    return cells


# ──────────────────── 2차: disabled 제외 · 대칭 perturbation · 재조합 ────────────────────
_PATTERN_CONFIG_PATH = os.path.normpath(
    os.path.join(os.path.dirname(__file__), "..", "..", "data", "pattern_config.json")
)


def _disabled_template_indices() -> Set[int]:
    """pattern_config.json의 disabled_patterns(사이즈별 dict 또는 리스트) → 비활성 인덱스 합집합.
    사람이 '쓰지 말라'고 끈 템플릿은 씨앗에서 제외(의도 존중)."""
    try:
        with open(_PATTERN_CONFIG_PATH, encoding="utf-8") as f:
            cfg = _json.load(f)
    except (OSError, ValueError):
        return set()
    dis = cfg.get("disabled_patterns", [])
    out: Set[int] = set()
    if isinstance(dis, dict):
        for lst in dis.values():
            for v in (lst or []):
                try:
                    out.add(int(v))
                except (ValueError, TypeError):
                    continue
    elif isinstance(dis, list):
        for v in dis:
            try:
                out.add(int(v))
            except (ValueError, TypeError):
                continue
    return out


def _dominant_sym_mode(cells: Set[Cell], g: int) -> str:
    """셀 집합이 가장 잘 맞는 대칭 모드. perturbation을 이 축으로 해야 대칭 유지됨."""
    best, best_m = -1.0, "both"
    for m in ("both", "quad", "v", "h", "rot180"):
        match = sum(1 for c in cells if _orbit(c[0], c[1], g, m) <= cells)
        frac = match / len(cells) if cells else 0.0
        if frac > best:
            best, best_m = frac, m
    return best_m


def _perturb_symmetric(cells: Set[Cell], g: int, rng: random.Random) -> Optional[Set[Cell]]:
    """템플릿 셀을 대칭(궤도) 단위로 약하게 성장/수축 → 같은 씨앗에서 변종 다수.
    대칭축·연결성·÷3 유지. 실패(불변식 깸) 시 None → 호출측이 원본 사용."""
    if len(cells) < 6:
        return None
    mode = _dominant_sym_mode(cells, g)
    grow = rng.random() < 0.5
    cur = set(cells)
    if grow:
        # 프런티어(셀에 인접한 빈칸)의 궤도 하나를 추가
        frontier = {(c[0] + dx, c[1] + dy)
                    for c in cur for dx, dy in _NEI4
                    if 0 <= c[0] + dx < g and 0 <= c[1] + dy < g and (c[0] + dx, c[1] + dy) not in cur}
        if not frontier:
            return None
        seed = rng.choice(sorted(frontier))
        orb = _orbit(seed[0], seed[1], g, mode) & {(x, y) for x in range(g) for y in range(g)}
        cand = cur | orb
    else:
        # 외곽 저연결 셀의 궤도 하나를 제거
        def deg(c):
            return sum(1 for dx, dy in _NEI4 if (c[0] + dx, c[1] + dy) in cur)
        outer = sorted(cur, key=lambda c: (deg(c), c))
        seed = outer[0]
        orb = _orbit(seed[0], seed[1], g, mode) & cur
        cand = cur - orb
    cand = _largest_component(cand)
    cand = _fill_single_holes(cand, g)
    if len(cand) < 6 or len(cand) > g * g:
        return None
    if len(cand) % 3 != 0:
        cand = _enforce_div3_symmetric(cand, g, mode)
    if not cand or len(cand) % 3 != 0:
        return None
    if cand == set(cells):          # 변화 없으면 의미 없음
        return None
    return cand


def _recombine_cells(a: Set[Cell], b: Set[Cell], g: int, op: str) -> Optional[Set[Cell]]:
    """두 템플릿 셀을 합집합/교집합으로 재조합 → 새 모양. 정리·÷3 보장. 실패 시 None."""
    cells = (a | b) if op == "union" else (a & b)
    cells = _largest_component(cells)
    cells = _fill_single_holes(cells, g)
    if len(cells) < 6 or len(cells) > g * g:
        return None
    cells = _center_cells(cells, g)
    if len(cells) % 3 != 0:
        cells = _enforce_div3(cells, g)
    if not cells or len(cells) % 3 != 0:
        return None
    return cells


# ──────────────────── 셀룰러 스프라이트 (Space Invaders 계보, 손 안 타는 창의 모양) ────────────────────
# 반쪽 중앙가중 시드 → 미러 대칭 → CA(고립셀 제거) 정제 → 연결성·÷3.
# 무작위지만 좌우대칭이라 인간 눈에 '크리처/엠블럼'으로 인지됨. 사람 손 0.
def _seed_left_weighted(g: int, rng: random.Random, fill: float) -> Set[Cell]:
    """왼쪽 절반을 중앙축·중심 가중 확률로 채움. 가운데일수록 채움 확률↑ → 뼈대 형성(안 흩어짐)."""
    half = (g + 1) // 2
    cx, cy = (g - 1) / 2, (g - 1) / 2
    norm = math.hypot(cx, cy) + 1e-9
    cells: Set[Cell] = set()
    for y in range(g):
        for x in range(half):
            d = math.hypot(x - cx, y - cy) / norm
            spine = 1.0 if x == half - 1 else 0.0       # 미러 축(중앙열) 보강
            p = min(0.95, max(0.0, fill * (1.25 - 0.7 * d) + 0.15 * spine))
            if rng.random() < p:
                cells.add((x, y))
    return cells


def _ca_deisolate(cells: Set[Cell], g: int) -> Set[Cell]:
    """CA 1패스: 8이웃 중 채워진 이웃 2개 미만인 셀 제거(고립·파편 픽셀 정리). 대칭 입력→대칭 출력."""
    def nb8(c: Cell) -> int:
        return sum(1 for dx in (-1, 0, 1) for dy in (-1, 0, 1)
                   if (dx or dy) and (c[0] + dx, c[1] + dy) in cells)
    return {c for c in cells if nb8(c) >= 2}


def _make_cellular_cells(g: int, rng: random.Random, fill: float) -> Optional[Set[Cell]]:
    """셀룰러 스프라이트 1개: 중앙가중 반쪽시드 → 좌우미러 → CA정제 → 연결성·중앙정렬·÷3.
    좌우대칭 크리처/엠블럼. 실패(너무 작음·÷3 불가) 시 None."""
    cells = _symmetrize(_seed_left_weighted(g, rng, fill), g, "h")
    cells = _ca_deisolate(cells, g)
    cells = _symmetrize(_largest_component(cells), g, "h")   # 연결성+대칭 재보장
    cells = _fill_single_holes(cells, g)
    if len(cells) < 6 or len(cells) > g * g:
        return None
    cells = _center_cells(cells, g)                          # 수직/수평 중앙정렬
    if len(cells) % 3 != 0:
        cells = _enforce_div3_symmetric(cells, g, "h")
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
    pretty: bool = True,
    min_quality: float = 0.55,
    use_templates: bool = True,
    template_ratio: float = 0.30,
    cellular_ratio: float = 0.30,
    cellular_only: bool = False,
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
    # 사람 제작 템플릿(0~60)을 씨앗으로 변형 → 창의적·고품질 모양. 비어있으면 기존 경로만.
    templates = _load_templates() if use_templates else {}
    disabled = _disabled_template_indices()           # 사람이 끈 템플릿은 씨앗 제외
    tmpl_keys = [i for i in templates.keys() if i not in disabled]

    concepts: List[Dict] = []
    seen_concept: Set[Tuple] = set()
    # pretty 게이트가 후보를 많이 걸러내므로 시도 횟수를 키워 목표 count를 채운다.
    attempts = max(count * oversample * (3 if pretty else 1), 48)
    for _ in range(attempts):
        # 모드/생성방식 결정.
        # - 'none' 요청: 항상 모티프(특정 모양). pretty면 대칭화로 반듯, 아니면 원형 비대칭.
        # - 대칭 모드 요청: 기하 전략 + 해당 대칭.
        # - 자동(None): 템플릿 변형(주력) + 모티프 + 대칭 기하 혼합. pretty면 전부 깔끔.
        motif_sym: Optional[str] = None  # 모티프 대칭화 모드(None=원형 유지)
        use_template = False
        use_cellular = False
        if cellular_only:
            # 순수 셀룰러 전용: 템플릿·모티프·기하 전부 배제, CA 스프라이트만 생성.
            use_cellular, use_motif, mode = True, False, "cellular"
        elif symmetry == "none":
            use_motif, mode = True, "none"
            # 사용자가 명시적으로 비대칭 원하면 그대로(원형 모양 유지)
        elif symmetry in SYMMETRY_MODES:
            use_motif, mode = False, symmetry
        else:
            r = rng.random()
            t_cut = template_ratio if tmpl_keys else 0.0       # 템플릿 없으면 0
            c_cut = t_cut + cellular_ratio                     # 셀룰러 스프라이트 구간
            if r < t_cut:
                use_template, use_motif = True, False
                mode = "template"
            elif r < c_cut:
                use_cellular, use_motif = True, False          # Space Invaders식 크리처
                mode = "cellular"
            elif r < c_cut + (1 - c_cut) * 0.45:
                use_motif = True
                # 자동 + pretty: 모티프를 대칭화 → 반듯한 '예쁜' 버전. 라벨도 대칭 모드로.
                motif_sym = rng.choice(("v", "h", "both", "quad")) if pretty else None
                mode = motif_sym or "none"
            else:
                use_motif, mode = False, rng.choice(("both", "h", "v", "rot180", "quad"))

        t_submode = "plain"   # plain(회전/반전) | perturb(대칭변주) | recombine(재조합)
        t_idx2 = None
        if use_template:
            t_idx = rng.choice(tmpl_keys)
            t_rot = rng.randint(0, 3)
            t_flip = rng.random() < 0.5
            # 서브모드: plain은 원본 회전뿐이라 '기존과 똑같아 보임' → 비중 축소.
            # 변주·재조합(원본과 다른 모양) 위주: 30% plain · 40% perturb · 30% recombine.
            rsub = rng.random()
            if rsub < 0.30:
                t_submode = "plain"
            elif rsub < 0.70:
                t_submode = "perturb"
            elif len(tmpl_keys) >= 2:
                t_submode = "recombine"
                t_idx2 = rng.choice([k for k in tmpl_keys if k != t_idx])
            else:
                t_submode = "perturb"
            rmark = "↻" * t_rot + ("⇋" if t_flip else "")
            if t_submode == "perturb":
                strat_label = f"tmpl:{t_idx}{rmark}~p"
            elif t_submode == "recombine":
                strat_label = f"tmpl:{t_idx}+{t_idx2}"
            else:
                strat_label = f"tmpl:{t_idx}{rmark}"
        elif use_cellular:
            cell_bucket = rng.randint(0, 5)   # 패밀리 6개로 분산 → 라운드로빈서 여러 개 표면화
            strat_label = f"cellular#{cell_bucket}"
        elif use_motif:
            motif = rng.choice(_MOTIF_NAMES)
            # 변형(회전·반전·두께)으로 ~20 기본형을 수백 고유형으로 확장 → 개수 상한↑·다양성↑
            m_rot = rng.randint(0, 3)
            m_flip = rng.random() < 0.5
            m_thick = rng.choice((0.85, 1.0, 1.0, 1.2))
            rmark = "↻" * m_rot + ("⇋" if m_flip else "")
            sym_tag = f"⊕{motif_sym}" if motif_sym else ""
            strat_label = f"motif:{motif}{rmark}{sym_tag}"
        else:
            strat = rng.choice(_STRATS)
            strat_label = strat_names[strat]
        fill = rng.uniform(*fill_range)
        cseed = rng.randint(0, 2**31 - 1)  # 컨셉 시드: 모든 사이즈에 동일 적용 → 일관성

        variants: List[Dict] = []
        ok = True
        for g in sizes:
            if use_template:
                if t_submode == "recombine":
                    ca = _make_template_cells(t_idx, g, t_rot, t_flip, templates)
                    cb = _make_template_cells(t_idx2, g, 0, False, templates)
                    cells = _recombine_cells(ca, cb, g, "union") if (ca and cb) else None
                else:
                    cells = _make_template_cells(t_idx, g, t_rot, t_flip, templates)
                    if cells and t_submode == "perturb":
                        p = _perturb_symmetric(cells, g, random.Random(cseed + g))
                        if p:
                            cells = p   # 변주 성공 시 교체, 실패 시 원본 유지
            elif use_cellular:
                # 사이즈별 시드(cseed+g)로 셀룰러 스프라이트. fill 변동으로 ÷3 보조.
                cells = None
                for fadj in (0.0, 0.1, -0.1, 0.2):
                    cells = _make_cellular_cells(g, random.Random(cseed + g), min(0.85, max(0.4, fill + fadj)))
                    if cells:
                        break
            elif use_motif:
                cells = _make_motif_cells(motif, g, m_rot, m_flip, m_thick, sym_mode=motif_sym)
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
            # 품질 게이트: 단일홀/가시 과다 → '찌그러진' 변형 폐기.
            # plain 템플릿만 면제(사람 검증된 의도 모양). perturb/recombine은 합성이라 검증.
            tmpl_exempt = use_template and t_submode == "plain"
            # 셀룰러는 다리·안테나(돌출)가 크리처 특징이라 가시 게이트 면제(단일홀·점수는 적용).
            spike_cap = 10**9 if use_cellular else max(2, len(cells) // 6)
            if pretty and not tmpl_exempt and (
                bd.get("single_holes", 0) > 0
                or bd.get("protrusions", 0) > spike_cap):
                ok = False
                break
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
        # 못생긴 컨셉 컷. plain 템플릿만 면제(perturb/recombine은 합성이라 검증).
        if pretty and not (use_template and t_submode == "plain") and agg < min_quality:
            continue
        concepts.append({
            "symmetry": mode,
            "strategy": strat_label,
            "score": agg,
            "sizes": sizes,
            "variants": variants,
        })

    # [v16] '같은 모양만 반복' 문제 해결: 점수순 선택은 대칭 모티프(T·plus·triangle…)에
    # 편향돼 매번 같은 base 형태가 나온다. 대신 **base 형태별 라운드로빈**으로 선택 →
    # 매 생성마다 서로 다른 base 형태가 골고루, 시드별로 다른 셋.
    def _big_cells(c: Dict) -> Set[Cell]:
        return {tuple(map(int, p.split("_"))) for p in c["variants"][-1]["positions"]}

    def _family(c: Dict) -> str:
        # 변형마크(↻⇋)·대칭태그(⊕mode) 제거한 base 형태 키. 기하 전략은 전략명 그대로.
        s = c["strategy"]
        if s.startswith("tmpl:"):
            # 회전(↻⇋)만 묶고 서브모드(plain/perturb~p/recombine+)는 별도 패밀리 →
            # 라운드로빈에서 변주·재조합도 표면화(다양성↑). 같은 인덱스 plain은 한 패밀리.
            body = s[5:]
            if "+" in body:                       # recombine: 두 인덱스 조합이 곧 패밀리
                return f"tmpl:{body}"
            if body.endswith("~p"):               # perturb: base+~p
                return "tmpl:" + body[:-2].rstrip("↻⇋") + "~p"
            return "tmpl:" + body.rstrip("↻⇋")    # plain
        s = s.replace("motif:", "")
        if "⊕" in s:
            s = s.split("⊕")[0]
        return s.rstrip("↻⇋")

    # [v16] 카테고리 할당량 선택. 순수 패밀리 라운드로빈은 패밀리 수가 많은 템플릿(50개)이
    # 출력을 독점(생성비율 무관) → '기존 템플릿과 똑같아 보임'. 대신 카테고리별 목표 비중으로
    # 슬롯을 배분하고, 카테고리 내부에서만 패밀리 라운드로빈 → 창의(cellular)·변형이 확실히 표면화.
    def _category(c: Dict) -> str:
        s = c["strategy"]
        if s.startswith("cellular"):
            return "cellular"
        if s.startswith("tmpl:"):
            body = s[5:]
            return "tmpl_var" if ("+" in body or body.endswith("~p")) else "tmpl_plain"
        if s.startswith("motif:"):
            return "motif"
        return "geom"

    # 목표 출력 비중(합 1.0). plain 템플릿(원본 회전뿐=익숙함)은 최소, 창의·변형 우선.
    weights = [("cellular", 0.30), ("tmpl_var", 0.22), ("motif", 0.20),
               ("geom", 0.18), ("tmpl_plain", 0.10)]

    from collections import defaultdict
    cat_fam: Dict[str, Dict[str, List[Dict]]] = defaultdict(lambda: defaultdict(list))
    for c in concepts:
        cat_fam[_category(c)][_family(c)].append(c)
    for cat in cat_fam:
        for f in cat_fam[cat]:
            rng.shuffle(cat_fam[cat][f])

    picked: List[Dict] = []
    picked_cells: List[Set[Cell]] = []

    def _pick_from(cat: str, n: int) -> int:
        if n <= 0 or cat not in cat_fam:
            return 0
        fams = list(cat_fam[cat].keys())
        rng.shuffle(fams)
        got, fi, guard = 0, 0, 0
        while got < n and guard < n * 40 + 50 and any(cat_fam[cat][f] for f in fams):
            guard += 1
            f = fams[fi % len(fams)]
            fi += 1
            if not cat_fam[cat][f]:
                continue
            c = cat_fam[cat][f].pop()
            cs = _big_cells(c)
            if any(len(cs & pc) / (len(cs | pc) or 1) >= 0.82 for pc in picked_cells):
                continue
            picked.append(c)
            picked_cells.append(cs)
            got += 1
        return got

    # 1차: 카테고리별 목표 할당
    for cat, w in weights:
        _pick_from(cat, round(count * w))
    # 2차: 부족분을 남은 컨셉으로 채움(카테고리 순회)
    guard = 0
    while len(picked) < count and guard < count * 20:
        guard += 1
        before = len(picked)
        for cat, _ in weights:
            if len(picked) >= count:
                break
            _pick_from(cat, 1)
        if len(picked) == before:      # 더 못 뽑음 → 종료
            break
    return picked[:count]


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
