"""[내부 검증] 등껍질 레벨의 **난이도 커버리지** 실측.

질문: 등껍질(침식) 생성으로 S~D 전 구간 난이도를 만들 수 있나?
레버 3개를 실제 생성 경로에서 조합해 측정한다.
  1) 타일 종류 수 V (level_number 로 자동 결정 — 실전과 동일)
  2) 컨테이너 개수 (난이도 → TURTLE_CONTAINER_BY_DIFFICULTY)
  3) 속성 기믹 강도 (gimmick_intensity)

측정: 정적 등급/점수 + 봇 클리어율(casual/average/expert) + ÷3·격자·컨테이너 수.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any, Dict, List, Tuple

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from app.core.bot_simulator import BotSimulator  # noqa: E402
from app.core.generator import LevelGenerator  # noqa: E402
from app.models.bot_profile import BotType, get_profile  # noqa: E402
from app.models.level import GenerationParams  # noqa: E402
from verify_turtle_integration import DATA, div3_bad, floating_count  # noqa: E402
from app.core import level_shapes as LS  # noqa: E402

# (레벨번호, 목표난이도) — 실전 진행 곡선 근사. 레벨번호가 V(타일 종류 수)를 결정한다.
SAMPLES: List[Tuple[int, float]] = [
    (5, 0.10), (25, 0.20), (60, 0.30), (120, 0.40), (220, 0.50),
    (380, 0.60), (560, 0.70), (800, 0.80), (1100, 0.88), (1450, 0.95),
]
ATTR_POOL = ["ice", "chain", "grass", "link", "curtain", "unknown"]


def main(patterns: int = 4, iters: int = 40) -> None:
    gen = LevelGenerator()
    sim = BotSimulator()
    cps: Dict[str, Any] = json.loads((DATA / "custom_patterns.json").read_text())
    # [난이도별 패턴 선택] 실전과 동일하게 **목표 타일수에 맞는 모양**을 고른다.
    # 큰 패턴만 쓰면 초반 난이도가 과대평가된다(실측: lv5 에 111타일 → casual 0.42).
    # 프로덕션 실측 분포(p25=60 / median=78 / p75=105)를 선형 근사.
    pool = sorted([(v["turtle"]["total"], k) for k, v in cps.items()
                   if isinstance(v, dict) and v.get("turtle")])

    def pick(td: float, k: int) -> List[str]:
        want = 30 + 90 * td
        return [pid for _, pid in sorted(pool, key=lambda e: abs(e[0] - want))[:k]]

    print(f"등껍질 패턴 {len(pool)}개 — 난이도별 목표 타일수에 맞춰 선택\n")
    print(f"{'lv':>5s} {'tgt':>4s} {'pattern':10s} {'층':>2s} {'총':>4s} {'V':>2s} {'컨':>2s} "
          f"{'기믹':>4s} {'등급':>4s} {'정적':>4s} {'cas':>5s} {'avg':>5s} {'exp':>5s} {'chk':>4s}")
    grades: Dict[str, int] = {}
    for (ln, td) in SAMPLES:
        for pid in pick(td, patterns):
            p = GenerationParams(
                target_difficulty=td, level_number=ln, turtle_pattern_id=pid,
                obstacle_types=ATTR_POOL, gimmick_intensity=min(1.5, 0.4 + td),
            )
            res = gen.generate(p)
            lj = res.level_json
            n = int(lj.get("layer") or 0)
            total = gen._turtle_total_tiles(lj)
            cont = attrs = 0
            types = set()
            for i in range(n):
                for t in ((lj.get(f"layer_{i}") or {}).get("tiles") or {}).values():
                    if not (isinstance(t, list) and t):
                        continue
                    tt = str(t[0])
                    if tt.startswith(("craft_", "stack_")):
                        cont += 1
                    elif tt != "t0":
                        types.add(tt)
                    if len(t) > 1 and t[1]:
                        attrs += 1
            rates = []
            for bt in (BotType.CASUAL, BotType.AVERAGE, BotType.EXPERT):
                r = sim.simulate_with_profile(
                    lj, get_profile(bt), iterations=iters,
                    max_moves=int(lj.get("max_moves") or 0) or None, seed=1)
                rates.append(float(getattr(r, "clear_rate", 0.0) or 0.0))
            grade = str(res.grade).split(".")[-1]
            grades[grade] = grades.get(grade, 0) + 1
            bad = (bool(LS.assert_in_board(lj)) or bool(div3_bad(lj))
                   or floating_count(lj) > 0)
            print(f"{ln:5d} {td:4.2f} {pid:10s} {n:2d} {total:4d} {len(types):2d} {cont:2d} "
                  f"{attrs:4d} {grade:>4s} {res.actual_difficulty:4.2f} "
                  f"{rates[0]:5.2f} {rates[1]:5.2f} {rates[2]:5.2f} {'NG' if bad else 'ok':>4s}")

    print(f"\n등급 분포: {grades}")


if __name__ == "__main__":
    main(int(sys.argv[1]) if len(sys.argv) > 1 else 4)
