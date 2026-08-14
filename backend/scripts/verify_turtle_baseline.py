"""[회귀 기준선] 등껍질 변경 **이전/이후** 를 같은 잣대로 비교하기 위한 축약 검증.

verify_turtle_integration.py 의 B/C/E(cap=ON) 만 실행하고, 신규 파라미터
(enforce_layer_cap / turtle_pattern_id)를 **쓰지 않는다** → git stash 로 되돌린
변경 전 코드에서도 그대로 돌아간다. 두 결과의 OK 수를 비교하면
"NG 가 원래 그런 것"인지 "내 변경이 깬 것"인지 구분된다.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from app.core.bot_simulator import BotSimulator  # noqa: E402
from app.core.generator import LevelGenerator  # noqa: E402
from app.models.level import GenerationParams  # noqa: E402
from verify_turtle_integration import DATA, check, template_pipeline  # noqa: E402


def main(sample: int = 6) -> None:
    gen = LevelGenerator()
    sim = BotSimulator()
    cps = json.loads((DATA / "custom_patterns.json").read_text())

    print("[B] 커스텀 패턴 → 절차생성")
    okb = 0
    plain = [k for k, v in cps.items() if isinstance(v, dict) and not v.get("turtle")][:sample]
    for pid in plain:
        try:
            idx = int(pid.split("_")[0])
        except ValueError:
            continue
        res = gen.generate(GenerationParams(target_difficulty=0.5, level_number=320,
                                            pattern_index=idx, pattern_type="aesthetic"))
        okb += check(pid, res.level_json, sim)

    print("\n[C] 층별 패턴")
    okc = 0
    shapes = json.loads((DATA / "level_shapes.json").read_text())
    sids = [k for k, v in shapes.items() if isinstance(v, dict) and v.get("level_json")][:sample]
    for sid in sids:
        lv = max(int(shapes[sid].get("min_level") or 0), 320)
        lj = template_pipeline(gen, shapes[sid]["level_json"], lv)
        okc += check(sid.replace("21ff4576052__", ""), lj, sim)

    print("\n[E] 절차생성(기본 상한)")
    oke = 0
    trials = [(f"diff{d}", GenerationParams(target_difficulty=d, level_number=320))
              for d in (0.3, 0.5, 0.7)]
    for tag, p in trials:
        oke += check(tag, gen.generate(p).level_json, sim)

    print(f"\n=== 기준선 요약: B {okb}/{len(plain)}  C {okc}/{len(sids)}  E {oke}/{len(trials)} ===")


if __name__ == "__main__":
    main(int(sys.argv[1]) if len(sys.argv) > 1 else 6)
