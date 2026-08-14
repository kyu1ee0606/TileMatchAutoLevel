"""[실험2] 기존 템플릿 중 '두꺼운 바닥'만 선정해 거북등껍질 침식 스택 생성.

실험1 결론: 침식 깊이는 **바닥 두께**로만 결정된다. 타운팝 층별패턴은 윤곽선/성긴 모양이라
layer_1 기준 침식이 1~2겹에서 끝났다. 6×6 솔리드는 6층(90타일)이 정상 생성됐다.

이번엔 모델을 바꾼다: 템플릿의 **layer_0 (또는 가장 조밀한 층) 만 바닥으로 채택**하고
그 위를 전부 침식으로 쌓는다(원본 상위층 폐기). 두께가 나오는 모양만 골라 쓴다.

선정 기준:
  - 침식 깊이 ≥ MIN_DEPTH 층
  - 총 타일수 ≤ MAX_TILES (프로덕션 p75≈105 기준)
  - 선언 격자 ≤ 8

출력: 선정 목록 + 파이프라인(÷3·격자·floating) + 봇 클리어율.
"""
from __future__ import annotations

import copy
import json
import random
import sys
from pathlib import Path
from typing import Any, Dict, List, Set, Tuple

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from app.core import level_shapes as LS  # noqa: E402
from app.core.bot_simulator import BotSimulator  # noqa: E402
from app.core.generator import LevelGenerator, select_color_balanced_tiles  # noqa: E402
from app.models.bot_profile import BotType, get_profile  # noqa: E402
from exp_turtle_peel import cells_of, div3_report, floating_count, peel  # noqa: E402

Cell = Tuple[int, int]

MAX_DIM = 8
MIN_DEPTH = 4
MAX_TILES = 130


def peel_stack(base_cells: Set[Cell], base_col: int) -> List[Tuple[int, int, Set[Cell]]]:
    """바닥 1층에서 시작해 다 깎일 때까지. [(layer_idx, col, cells)]"""
    out = [(0, base_col, set(base_cells))]
    cur, cl, cc = set(base_cells), 0, base_col
    idx = 1
    while idx < 12:
        u = base_col - (idx % 2)
        nxt = peel(cur, cl, idx, cc, u, u)
        if not nxt:
            break
        out.append((idx, u, nxt))
        cur, cl, cc = nxt, idx, u
        idx += 1
    return out


def to_level(stack: List[Tuple[int, int, Set[Cell]]], base_col: int,
             src_layer0: Dict[str, Any] | None) -> Dict[str, Any]:
    """스택 → level_json. 바닥층은 원본 타일값(기믹) 보존, 위층은 t0."""
    lj: Dict[str, Any] = {
        "layer": len(stack), "row": base_col, "col": base_col,
        "useTileCount": 6, "randSeed": 1, "autoCollectCount": 0,
    }
    src_tiles = (src_layer0 or {}).get("tiles") or {}
    for (li, col, cells) in stack:
        tiles: Dict[str, Any] = {}
        for (x, y) in sorted(cells):
            pos = f"{x}_{y}"
            if li == 0 and pos in src_tiles and isinstance(src_tiles[pos], list):
                tiles[pos] = copy.deepcopy(src_tiles[pos])   # 바닥 기믹 보존
            else:
                tiles[pos] = ["t0", ""]
        lj[f"layer_{li}"] = {"col": col, "row": col, "num": len(tiles), "tiles": tiles}
    return lj


def pipeline(lj: Dict[str, Any], level_number: int) -> Dict[str, Any]:
    """/generate/from-level-shape 와 동일 순서."""
    gen = LevelGenerator()
    lj = copy.deepcopy(lj)
    tile_types = select_color_balanced_tiles(6, seed=level_number)
    rng = random.Random(level_number)
    for i in range(int(lj.get("layer") or 0)):
        for tile in ((lj.get(f"layer_{i}") or {}).get("tiles") or {}).values():
            if isinstance(tile, list) and tile and tile[0] == "t0":
                tile[0] = rng.choice(tile_types)
    lj = gen._ensure_tutorial_unlock_gimmick(lj, level_number)
    lj = gen._finalize_divisibility_guarantee(lj)
    lj = gen._finalize_level(lj)
    return lj


def best_base_layer(src: Dict[str, Any]) -> Tuple[Set[Cell], int, Dict[str, Any]] | None:
    """소스에서 침식 바닥으로 쓸 층 선택 — **짝수 인덱스(큰 격자) 중 가장 조밀한 층**.
    (홀수층은 격자가 1 작아 base 로 쓰면 스택 폭이 줄어든다.)"""
    best = None
    n = int(src.get("layer") or 0)
    for i in range(n):
        if i % 2:
            continue
        ld = src.get(f"layer_{i}")
        if not isinstance(ld, dict):
            continue
        try:
            col = int(ld.get("col"))
        except (TypeError, ValueError):
            continue
        if col > MAX_DIM:
            continue
        cs = cells_of(ld)
        if not cs:
            continue
        if best is None or len(cs) > len(best[0]):
            best = (cs, col, ld)
    return best


def main(level_number: int = 320, iterations: int = 40, show: int = 3) -> None:
    raw = json.loads(Path("data/level_shapes.json").read_text())
    sim = BotSimulator()

    picked: List[Tuple[str, List[Tuple[int, int, Set[Cell]]], int, Dict[str, Any]]] = []
    scanned = 0
    for sid, entry in raw.items():
        if not isinstance(entry, dict):
            continue
        src = entry.get("level_json") or {}
        base = best_base_layer(src)
        if not base:
            continue
        scanned += 1
        cells, col, ld = base
        stack = peel_stack(cells, col)
        total = sum(len(c) for _, _, c in stack)
        if len(stack) >= MIN_DEPTH and total <= MAX_TILES:
            picked.append((sid, stack, col, ld))

    print(f"스캔 {scanned}개 → 선정 {len(picked)}개 (깊이≥{MIN_DEPTH}, 총타일≤{MAX_TILES})\n")
    print(f"{'id':34s} {'base':>4s} {'층':>2s} {'층별':30s} {'총':>4s} "
          f"{'board':>5s} {'div3':>4s} {'flo':>3s} {'casual':>6s} {'avg':>5s} {'expert':>6s}")

    okc = 0
    for sid, stack, col, ld in picked:
        lj = to_level(stack, col, ld)
        try:
            out = pipeline(lj, level_number)
        except Exception as e:  # noqa: BLE001
            print(f"{sid:34s} PIPELINE FAIL {type(e).__name__}: {e}")
            continue
        nl = int(out.get("layer") or 0)
        per = [len((out.get(f"layer_{i}") or {}).get("tiles") or {}) for i in range(nl)]
        viol = LS.assert_in_board(out)
        bad3, t0r = div3_report(out)
        flo = floating_count(out)
        rates = []
        for bt in (BotType.CASUAL, BotType.AVERAGE, BotType.EXPERT):
            try:
                r = sim.simulate_with_profile(
                    out, get_profile(bt), iterations=iterations,
                    max_moves=int(out.get("max_moves") or 0) or None, seed=1)
                rates.append(float(getattr(r, "clear_rate", 0.0) or 0.0))
            except Exception:  # noqa: BLE001
                rates.append(-1.0)
        good = (not viol) and (not bad3) and t0r == 0 and flo == 0 and rates[1] >= 0.30
        okc += good
        print(f"{sid:34s} {col:4d} {nl:2d} {str(per):30s} {sum(per):4d} "
              f"{len(viol):5d} {len(bad3):4d} {flo:3d} "
              f"{rates[0]:6.2f} {rates[1]:5.2f} {rates[2]:6.2f} {'OK' if good else 'NG'}")

    print(f"\n=== 선정본 검증: OK {okc} / {len(picked)} ===")

    for sid, stack, col, ld in picked[:show]:
        print(f"\n--- {sid} (base={col}) ---")
        for li, c, cells in stack:
            print(f"  layer_{li} (col={c}, n={len(cells)})")
            for y in range(c):
                print("    " + "".join("#" if (x, y) in cells else "." for x in range(c)))


if __name__ == "__main__":
    main(int(sys.argv[1]) if len(sys.argv) > 1 else 320)
