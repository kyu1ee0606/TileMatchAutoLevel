"""[등껍질 바닥] 미측정 항목의 난이도를 일괄 실측해 `turtle_bases.json` 에 기록.

측정 프로토콜은 `/debug/turtle-bases/{id}/measure` 와 동일:
  기믹·컨테이너 없이 1회 생성 → useTileCount 만 6/9/12 로 바꿔가며 시뮬
  → randSeed=0 + honor_zero_seed 로 **매 iteration 다른 색분배**
  (고정 시드로 재면 실수율 낮은 봇이 배치 하나에 all-or-nothing 이 되어 사다리가 역전된다)

coef = 1 − mean(avg 클리어율). 클수록 어려움. coef 없는 항목은 서브보스 자동 배정에서 제외되므로
새로 그린 바닥은 반드시 한 번 돌려야 실제로 쓰인다.

사용:
    python scripts/measure_turtle_bases.py            # 미측정만
    python scripts/measure_turtle_bases.py --all      # 전부 재측정
"""
from __future__ import annotations

import copy
import sys
import time
from pathlib import Path
from typing import Any, Dict, List

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core import turtle_bases as TB  # noqa: E402
from app.core.bot_simulator import BotSimulator  # noqa: E402
from app.core.generator import LevelGenerator  # noqa: E402
from app.models.bot_profile import BotType, get_profile  # noqa: E402

V_GRID = (6, 9, 12)
ITERS = 100


def measure_one(gen: LevelGenerator, sim: BotSimulator, entry: Dict[str, Any]) -> Dict[str, Any] | None:
    grid = int(entry.get("grid") or 8)
    cells = TB.parse_cells(entry.get("cells") or [], grid)
    stack = TB.peel_stack(cells, grid)
    if len(stack) < 2:
        return None
    level: Dict[str, Any] = {"layer": len(stack), "row": str(grid), "col": str(grid),
                             "useTileCount": 6, "randSeed": 0, "autoCollectCount": 0}
    gen._build_turtle_layers(level, stack)
    level = gen._finalize_divisibility_guarantee(level)
    level = gen._finalize_level(level)

    by_v: Dict[str, Any] = {}
    avgs: List[float] = []
    for v in V_GRID:
        lj = copy.deepcopy(level)
        lj["useTileCount"] = v
        lj["randSeed"] = 0
        rates = {}
        for key, bt in (("avg", BotType.AVERAGE), ("cas", BotType.CASUAL)):
            r = sim.simulate_with_profile(
                lj, get_profile(bt), iterations=ITERS,
                max_moves=int(lj.get("max_moves") or 0) or None,
                seed=0, honor_zero_seed=True)
            rates[key] = round(float(getattr(r, "clear_rate", 0.0) or 0.0), 3)
        by_v[str(v)] = rates
        avgs.append(rates["avg"])
    return {"ref": "turtle_base", "by_v": by_v, "coef": round(1.0 - sum(avgs) / len(avgs), 3)}


def main(all_: bool = False) -> None:
    entries = TB.list_bases(with_shape=False)
    todo = [e for e in entries
            if all_ or (e.get("difficulty") or {}).get("coef") is None]
    print(f"라이브러리 {len(entries)}종 · 측정 대상 {len(todo)}종 (V={list(V_GRID)}, {ITERS}iter)\n")
    gen, sim = LevelGenerator(), BotSimulator()
    t0 = time.time()
    done = fail = 0
    for i, e in enumerate(todo, 1):
        full = TB.get_base(e["id"])
        if not full:
            fail += 1
            continue
        d = measure_one(gen, sim, full)
        if not d:
            print(f"  [{i}/{len(todo)}] {e['id']} 측정 불가(침식 깊이 부족)")
            fail += 1
            continue
        TB.set_difficulty(e["id"], d)
        done += 1
        print(f"  [{i}/{len(todo)}] {e['id']:18s} {full['grid']}x{full['grid']} "
              f"coef {d['coef']:.3f}  V6/9/12 "
              f"{d['by_v']['6']['avg']:.2f}/{d['by_v']['9']['avg']:.2f}/{d['by_v']['12']['avg']:.2f}",
              flush=True)
    print(f"\n완료 {done} / 실패 {fail}  ({time.time() - t0:.0f}s)")
    left = [e["id"] for e in TB.list_bases(with_shape=False)
            if (e.get("difficulty") or {}).get("coef") is None]
    print(f"남은 미측정: {len(left)}")


if __name__ == "__main__":
    main(all_="--all" in sys.argv)
