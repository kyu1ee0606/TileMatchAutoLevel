"""[실험] 거북등껍질 침식 템플릿 생성 — 타당성 실측.

아이디어(사용자 제안):
  선정된 템플릿의 **layer_0 · layer_1 은 그대로 사용**하고,
  layer_1 부터 한 겹씩 깎아내며(완전받침 침식) 타일이 다 없어질 때까지 층을 추가한다.

검증 항목:
  1) 층수/타일수가 게임 제약 안에 들어오는가 (선언 그리드 ≤ 8, 층수 상한)
  2) 홀짝 정사각 격자 규칙 위반 없음 (level_shapes.assert_in_board)
  3) ÷3 (concrete 타입별 + t0 총합)
  4) floating 0 (모든 상위 타일이 아래층 받침을 가짐)
  5) 기존 검증기 통과 시 실제로 클리어 가능한가 (BotSimulator 클리어율)

침식 정의:
  상위 칸 (ux,uy) 는 **자기가 덮는 하위 칸이 전부 존재할 때만** 생성한다
  (`get_cover_offsets` 정본 오프셋의 역방향, all-조건).
  → 홀짝 교대 격자에서 2층마다 테두리 한 겹이 벗겨진다 = 거북등껍질.
  게임의 valid_support_mask 는 any-조건(1개만 덮어도 OK)이라 반대로 넓어진다 —
  침식에는 all-조건을 써야 한다.
"""
from __future__ import annotations

import copy
import json
import random
import sys
from collections import Counter
from pathlib import Path
from typing import Any, Dict, List, Set, Tuple

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core import level_shapes as LS  # noqa: E402
from app.core.bot_simulator import BotSimulator  # noqa: E402
from app.models.bot_profile import BotType, get_profile  # noqa: E402
from app.core.generator import LevelGenerator, select_color_balanced_tiles  # noqa: E402
from app.core.unit_templates import get_cover_offsets  # noqa: E402

Cell = Tuple[int, int]

MAX_DECLARED_DIM = 8      # 디바이스 가독성 상한(기존 규칙)
MAX_LAYERS = 12           # 스키마 상한


def cells_of(ld: Dict[str, Any]) -> Set[Cell]:
    out: Set[Cell] = set()
    for pos in (ld.get("tiles") or {}):
        try:
            x, y = map(int, pos.split("_"))
        except ValueError:
            continue
        out.add((x, y))
    return out


def peel(lower: Set[Cell], lower_layer: int, upper_layer: int,
         lower_col: int, upper_col: int, upper_rows: int) -> Set[Cell]:
    """완전받침 침식 — 덮는 하위 칸이 **전부** 있어야 상위 칸 생성."""
    offs = get_cover_offsets(lower_layer, upper_layer, lower_col, upper_col)
    out: Set[Cell] = set()
    for ux in range(upper_col):
        for uy in range(upper_rows):
            if all((ux - dx, uy - dy) in lower for dx, dy in offs):
                out.add((ux, uy))
    return out


def build_turtle(level_json: Dict[str, Any]) -> Dict[str, Any] | None:
    """layer_0/layer_1 보존 + layer_2.. 침식 생성. 실패 시 None."""
    lj = copy.deepcopy(level_json)
    try:
        n = int(lj.get("layer") or 0)
    except (TypeError, ValueError):
        return None
    if n < 2:
        return None
    l0, l1 = lj.get("layer_0"), lj.get("layer_1")
    if not isinstance(l0, dict) or not isinstance(l1, dict):
        return None
    try:
        base = int(l0.get("col"))
    except (TypeError, ValueError):
        return None
    if base > MAX_DECLARED_DIM:
        return None
    if not cells_of(l1):
        return None

    # 보존 2층만 남기고 나머지 제거
    for i in range(2, n):
        lj.pop(f"layer_{i}", None)

    cur = cells_of(l1)
    cur_layer, cur_col = 1, int(l1.get("col"))
    idx = 2
    while idx < MAX_LAYERS:
        ucol = base - (idx % 2)
        nxt = peel(cur, cur_layer, idx, cur_col, ucol, ucol)
        if not nxt:
            break
        lj[f"layer_{idx}"] = {
            # 소스 템플릿이 col/row 를 int 로 저장 → 타입 통일(문자열이면 봇 시뮬레이터의
            # `upper_layer_col > cur_layer_col` 비교에서 TypeError).
            "col": ucol, "row": ucol, "num": len(nxt),
            "tiles": {f"{x}_{y}": ["t0", ""] for (x, y) in sorted(nxt)},
        }
        cur, cur_layer, cur_col = nxt, idx, ucol
        idx += 1
    lj["layer"] = idx
    return lj


def floating_count(lj: Dict[str, Any]) -> int:
    """받침 없는(공중에 뜬) 상위 타일 수 — any-조건(게임 기준)."""
    bad = 0
    n = int(lj.get("layer") or 0)
    for i in range(1, n):
        ld, below = lj.get(f"layer_{i}"), lj.get(f"layer_{i-1}")
        if not isinstance(ld, dict) or not isinstance(below, dict):
            continue
        bc, uc = int(below.get("col")), int(ld.get("col"))
        offs = get_cover_offsets(i - 1, i, bc, uc)
        lower = cells_of(below)
        for (ux, uy) in cells_of(ld):
            if not any((ux - dx, uy - dy) in lower for dx, dy in offs):
                bad += 1
    return bad


def div3_report(lj: Dict[str, Any]) -> Tuple[Dict[str, int], int]:
    """concrete 타입별 개수 중 ÷3 위반분, t0 총합 나머지."""
    n = int(lj.get("layer") or 0)
    cnt: Counter[str] = Counter()
    for i in range(n):
        ld = lj.get(f"layer_{i}") or {}
        for tile in (ld.get("tiles") or {}).values():
            t = tile[0] if isinstance(tile, list) and tile else str(tile)
            cnt[t] += 1
    bad = {t: c for t, c in cnt.items()
           if t.startswith("t") and t[1:].isdigit() and t != "t0" and c % 3}
    return bad, cnt.get("t0", 0) % 3


def main(limit: int = 12, level_number: int = 300, iterations: int = 60) -> None:
    raw = json.loads(Path("data/level_shapes.json").read_text())
    shapes = [dict(v, id=k) for k, v in raw.items() if isinstance(v, dict)]
    gen = LevelGenerator()
    sim = BotSimulator()
    prof = get_profile(BotType.AVERAGE)

    ok = fail = 0
    rows: List[str] = []
    for entry in shapes[:limit]:
        sid = entry.get("id") or entry.get("shape_id") or "?"
        src = entry.get("level_json")
        if not src:
            rows.append(f"{sid:34s} SKIP no level_json")
            continue
        built = build_turtle(src)
        if not built:
            rows.append(f"{sid:34s} SKIP unbuildable")
            continue

        # from-level-shape 와 동일 파이프라인
        tile_types = select_color_balanced_tiles(6, seed=level_number)
        rng = random.Random(level_number)
        for i in range(int(built.get("layer") or 0)):
            ld = built.get(f"layer_{i}") or {}
            for tile in (ld.get("tiles") or {}).values():
                if isinstance(tile, list) and tile and tile[0] == "t0":
                    tile[0] = rng.choice(tile_types)
        try:
            built = gen._ensure_tutorial_unlock_gimmick(built, level_number)
            built = gen._finalize_divisibility_guarantee(built)
            built = gen._finalize_level(built)
        except Exception as e:  # noqa: BLE001
            rows.append(f"{sid:34s} FAIL pipeline {type(e).__name__}: {e}")
            fail += 1
            continue

        viol = LS.assert_in_board(built)
        bad3, t0rem = div3_report(built)
        flo = floating_count(built)
        nl = int(built.get("layer") or 0)
        per = [len((built.get(f"layer_{i}") or {}).get("tiles") or {}) for i in range(nl)]
        total = sum(per)

        try:
            res = sim.simulate_with_profile(built, prof, iterations=iterations,
                                            max_moves=int(built.get("max_moves") or 0) or None, seed=1)
            clear = float(getattr(res, "clear_rate", 0.0) or 0.0)
        except Exception as e:  # noqa: BLE001
            clear = -1.0
            import traceback
            rows.append(f"{sid:34s} simerr {type(e).__name__}: {e}\n" + traceback.format_exc()[-800:])

        # floating 은 소스 템플릿에서 이미 존재하는 경우가 있어(예: layer_0 이 빈 타운팝 모양)
        # 침식 로직의 결함과 구분해야 한다 → 원본 대비 '증가분'만 본다.
        flo_src = floating_count(src)
        good = (not viol) and (not bad3) and t0rem == 0 and flo <= flo_src and clear >= 0.30
        ok += good
        fail += (not good)
        rows.append(
            f"{sid:34s} 층{nl:2d} 타일{total:4d} {per} "
            f"board={len(viol)} div3={len(bad3)} t0rem={t0rem} float={flo}(src{flo_src}) clear={clear:.2f} "
            f"{'OK' if good else 'NG'}"
        )

    print("\n".join(rows))
    print(f"\n=== turtle-peel 결과: OK {ok} / NG {fail} (총 {ok+fail}) ===")


if __name__ == "__main__":
    main(int(sys.argv[1]) if len(sys.argv) > 1 else 12,
         int(sys.argv[2]) if len(sys.argv) > 2 else 300)
