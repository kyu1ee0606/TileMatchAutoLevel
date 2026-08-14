"""[등껍질 난이도 계수] 패턴별 난이도를 실측해 custom_patterns.json 의 turtle 메타에 기록.

왜 필요한가 (실측):
  같은 목표 난이도에서 패턴마다 클리어율이 크게 갈린다(lv60 avg 0.23~0.50).
  더 중요한 건 **타일수가 많을수록 쉽다**는 역방향 관계였다:
      lv220(V=9)  78_5x5(33타일) avg=0.00   /  34_7x7(59타일) avg=0.73  /  3_8x8(110타일) avg=0.40
  원인은 **타일수 ÷ 색 종류(V)**. 33타일에 9색이면 색당 3.7개뿐이라 7칸 도크가
  트리플 완성 전에 차버린다. 즉 '작은 등껍질 = 쉬움'이 아니라 **어려움**이다.
  → 총타일수만 보고 슬롯을 배정하면 난이도가 뒤집힌다. 그래서 V별로 실측해 둔다.

측정 프로토콜:
  - 기준 레벨(REF_LEVEL)로 1회 생성. **기믹·컨테이너 없음**(순수 모양 난이도 격리)
  - 생성 결과의 useTileCount 만 V로 바꿔가며 시뮬 → 생성 난수 영향 없이 V 효과만 분리
  - 봇 average / casual 클리어율 기록
  - coef = 1 − mean(avg 클리어율)  … 클수록 어려움

사용:
    python scripts/measure_turtle_difficulty.py            # 드라이런
    python scripts/measure_turtle_difficulty.py --apply    # turtle.difficulty 기록
"""
from __future__ import annotations

import copy
import json
import os
import sys
import tempfile
from pathlib import Path
from typing import Any, Dict, List

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.bot_simulator import BotSimulator  # noqa: E402
from app.core.generator import LevelGenerator  # noqa: E402
from app.models.bot_profile import BotType, get_profile  # noqa: E402
from app.models.level import GenerationParams  # noqa: E402

PATTERN_FILE = Path(__file__).resolve().parents[1] / "data" / "custom_patterns.json"
REF_LEVEL = 220            # tile_types 가 t0 인 구간(런타임 분배) → useTileCount 로 V 제어 가능
V_GRID = [6, 9, 12]        # 실제 그래프가 쓰는 범위를 위아래로 감싼다
ITERS = 150


def measure(gen: LevelGenerator, sim: BotSimulator, pid: str) -> Dict[str, Any] | None:
    # target_difficulty 를 낮게 줘 컨테이너 0개, obstacle_types 미지정 → 속성 기믹 0
    res = gen.generate(GenerationParams(
        target_difficulty=0.1, level_number=REF_LEVEL, turtle_pattern_id=pid))
    base = res.level_json
    if not base.get("_turtle_peel"):
        return None
    # t0 가 아닌 구체 타입으로 굳어졌으면 V 스윕이 무의미 → 스킵 표시
    t0_seen = any(
        isinstance(t, list) and t and t[0] == "t0"
        for i in range(int(base.get("layer") or 0))
        for t in ((base.get(f"layer_{i}") or {}).get("tiles") or {}).values())
    out: Dict[str, Any] = {"ref_level": REF_LEVEL, "t0_runtime": t0_seen, "by_v": {}}
    avgs: List[float] = []
    for v in V_GRID:
        lj = copy.deepcopy(base)
        lj["useTileCount"] = v
        # [측정 프로토콜] randSeed=0 + honor_zero_seed=True → **매 iteration 다른 색분배**.
        # 고정 randSeed 로 재면 전 iteration 이 같은 배치 1개를 반복해, 실수율이 낮은 봇
        # (expert 3%)은 그 배치 하나에 대해 all-or-nothing 이 된다. 실측:
        #   고정   cas 0.125 / avg 0.542 / exp 0.217   ← 사다리 역전
        #   랜덤   cas 0.242 / avg 0.533 / exp 0.767   ← 단조 복구
        # 난이도 '계수'는 배치 하나가 아니라 분포 전체의 기대값이어야 한다.
        lj["randSeed"] = 0
        rates = {}
        for key, bt in (("avg", BotType.AVERAGE), ("cas", BotType.CASUAL)):
            r = sim.simulate_with_profile(
                lj, get_profile(bt), iterations=ITERS,
                max_moves=int(lj.get("max_moves") or 0) or None,
                seed=0, honor_zero_seed=True)
            rates[key] = round(float(getattr(r, "clear_rate", 0.0) or 0.0), 3)
        out["by_v"][str(v)] = rates
        avgs.append(rates["avg"])
    out["coef"] = round(1.0 - (sum(avgs) / len(avgs)), 3)
    return out


def main(apply: bool = False) -> None:
    data: Dict[str, Any] = json.loads(PATTERN_FILE.read_text())
    gen, sim = LevelGenerator(), BotSimulator()
    targets = [k for k, v in data.items() if isinstance(v, dict) and v.get("turtle")]
    print(f"대상 {len(targets)}개 (기준 lv{REF_LEVEL}, V={V_GRID}, {ITERS}iter, 기믹/컨테이너 없음)\n")
    print(f"{'pattern':12s} {'총':>4s} {'층':>2s} " +
          " ".join(f"{'V'+str(v):>12s}" for v in V_GRID) + "  coef")
    rows = []
    for pid in targets:
        m = measure(gen, sim, pid)
        if not m:
            print(f"{pid:12s} 측정 실패(등껍질 미적용)")
            continue
        data[pid]["turtle"]["difficulty"] = m
        t = data[pid]["turtle"]
        cells = " ".join(
            f"{m['by_v'][str(v)]['avg']:.2f}/{m['by_v'][str(v)]['cas']:.2f}".rjust(12)
            for v in V_GRID)
        rows.append((m["coef"], pid, t["total"], t["depth"], cells))
    rows.sort()
    for coef, pid, total, depth, cells in rows:
        print(f"{pid:12s} {total:4d} {depth:2d} {cells}  {coef:.3f}")

    if rows:
        cs = [r[0] for r in rows]
        print(f"\ncoef 분포: min {min(cs):.3f} / median {cs[len(cs)//2]:.3f} / max {max(cs):.3f}")

    if not apply:
        print("\n(드라이런 — 파일 미변경. --apply 로 반영)")
        return
    fd, tmp = tempfile.mkstemp(dir=str(PATTERN_FILE.parent), suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False)
        os.replace(tmp, PATTERN_FILE)
    except Exception:
        if os.path.exists(tmp):
            os.remove(tmp)
        raise
    print(f"\n✅ {PATTERN_FILE} 갱신 완료")


if __name__ == "__main__":
    main(apply="--apply" in sys.argv)
