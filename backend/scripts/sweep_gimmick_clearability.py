"""기믹별 클리어 가능성 스윕 — '유저가 실제로 플레이하면 깰 수 있나'.

키타일 사건의 교훈: A* 는 우리 모델로 판정하므로, 우리 모델이 게임과 어긋나면
**멀쩡하다고 오판한다**(실제로 Lv111 을 PROVEN_SOLVABLE 로 통과시켰다).
그래서 세 가지를 같이 본다:

  1) A*        — 구조적 확정 판정 (÷3, 완전탐색). 단 UNRELIABLE_GIMMICKS 는 UNCERTAIN.
  2) 봇 시뮬   — 유저 대리 플레이. EXPERT 가 여러 번 돌려 한 번도 못 깨면 의심.
  3) 게임분배  — DB_Level.cs 포팅본으로 최종 타일 구성 검사(÷3/키/인덱스).

기믹이 든 레벨을 골고루 뽑아, 셋 중 하나라도 '불가' 신호를 내면 보고한다.
"""
import json
import random
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.core.bot_simulator import get_bot_simulator          # noqa: E402
from app.core.solver import solve_level                       # noqa: E402
from app.models.bot_profile import BotType, get_profile       # noqa: E402
from scripts.verify_key_fix import defects                    # noqa: E402

GIMMICKS = ["ice", "grass", "chain", "link", "curtain", "unknown",
            "bomb", "teleporter", "frog", "craft", "stack"]


def gimmicks_of(lj: dict) -> set:
    out = set()
    for i in range(int(lj.get("layer", 0) or 0)):
        for td in (lj.get(f"layer_{i}") or {}).get("tiles", {}).values():
            if not (isinstance(td, list) and td and isinstance(td[0], str)):
                continue
            t = td[0]
            if t.startswith("craft_"):
                out.add("craft")
            elif t.startswith("stack_"):
                out.add("stack")
            g = td[1] if len(td) > 1 and isinstance(td[1], str) else ""
            if g:
                out.add("bomb" if g.startswith("bomb") else g.split("_")[0])
    return out


def main(path: str, per_gimmick: int = 8, iters: int = 40):
    d = json.load(open(path))
    print(f"배치: {d['batch'].get('name', '?')[:60]}")
    print(f"기믹당 {per_gimmick}레벨 × 봇 {iters}회\n")

    by_g = defaultdict(list)
    for e in d["levels"]:
        ln = e.get("meta", {}).get("level_number")
        lj = e.get("level_json") or {}
        if ln is None:
            continue
        for g in gimmicks_of(lj):
            by_g[g].append((ln, lj))

    rnd = random.Random(20260818)
    sim = get_bot_simulator()
    prof = get_profile(BotType.EXPERT)

    suspects = []
    print(f"{'기믹':<11}{'Lv':>6}  {'A*':<18}{'봇클리어':>9}  {'구조결함':<22}")
    print("-" * 74)

    for g in GIMMICKS:
        pool = by_g.get(g, [])
        if not pool:
            print(f"{g:<11}  (해당 레벨 없음)")
            continue
        # 난이도 스펙트럼이 골고루 잡히도록 레벨번호 순 균등 표본
        pool.sort(key=lambda x: x[0])
        step = max(1, len(pool) // per_gimmick)
        sample = pool[::step][:per_gimmick]
        if len(sample) < per_gimmick and len(pool) > len(sample):
            sample += rnd.sample(pool, min(per_gimmick - len(sample), len(pool)))

        for ln, lj in sample:
            df = defects(lj)
            sv = solve_level(lj, node_budget=250000, time_budget_s=8.0)
            try:
                r = sim.simulate_with_profile(lj, prof, iterations=iters,
                                              max_moves=lj.get("max_moves"), seed=12345)
                cr = r.clear_rate
            except Exception as ex:  # noqa: BLE001
                cr = -1.0
                df = dict(df or {}, bot_error=repr(ex)[:60])

            flag = ""
            if sv["verdict"] == "PROVEN_IMPOSSIBLE" or df or cr == 0.0 or cr < 0:
                flag = "  ⚠️"
                suspects.append((g, ln, sv["verdict"], cr, df))
            print(f"{g:<11}{ln:>6}  {sv['verdict']:<18}{cr:>8.0%}  {str(df or '-'):<22}{flag}")

    print("\n" + "=" * 74)
    print(f"의심 {len(suspects)}건")
    for g, ln, v, cr, df in suspects:
        print(f"  [{g}] Lv{ln}  A*={v}  봇={cr:.0%}  결함={df or '-'}")
    return suspects


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1
         else "data/production/batch_1786011385119_qi96gz8x5.json",
         int(sys.argv[2]) if len(sys.argv) > 2 else 8,
         int(sys.argv[3]) if len(sys.argv) > 3 else 40)
