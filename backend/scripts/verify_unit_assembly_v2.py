"""[유닛조립 v2 검증] 성긴-대칭 재설계가 봇 클리어율 정상인지.

계획 PLAN_unit_assembly_sparse_symmetric.md §3 불변식:
  - RL 봇 클리어율 정상(0.0 아님) — 최우선
  - reverse_generation 강제 안 함
  - deadlock 체크 ON
  - floating 0
  - ÷3
비교군: unit_assembly OFF(정상 경로) vs ON(v2).
"""
import sys
import random
import statistics

sys.path.insert(0, "/Users/casualdev/TileMatchAutoLevel/backend")
from app.core.generator import LevelGenerator          # noqa: E402
from app.models.level import GenerationParams          # noqa: E402
from app.core.bot_simulator import BotSimulator        # noqa: E402
from app.core.solver import _clearability_type_counts  # noqa: E402
from app.models.bot_profile import BotType, get_profile  # noqa: E402

g = LevelGenerator()
sim = BotSimulator()

LEVELS = [(30, 0.22), (100, 0.35), (400, 0.55), (800, 0.72), (1200, 0.85)]
ITERS = 12


def floating_count(lj):
    """상위 타일이 하위에 받침 없이 떠 있는 개수(0이어야 함)."""
    from app.core.unit_templates import get_cover_offsets
    n = int(lj.get("layer", 0) or 0)
    bad = 0
    for j in range(n - 1, 0, -1):
        up = lj.get(f"layer_{j}") or {}
        lo = lj.get(f"layer_{j-1}") or {}
        ut, lt = up.get("tiles") or {}, lo.get("tiles") or {}
        if not ut:
            continue
        try:
            uc, bc = int(up.get("col")), int(lo.get("col"))
        except (TypeError, ValueError):
            continue
        offs = get_cover_offsets(j - 1, j, bc, uc)
        for k in ut:
            x, y = map(int, k.split("_"))
            if not any(f"{x-dx}_{y-dy}" in lt for dx, dy in offs):
                bad += 1
    return bad


def measure(ln, td, unit):
    random.seed(1000 + ln + (1 if unit else 0))
    p = GenerationParams(
        target_difficulty=td, grid_size=(7, 7), level_number=ln,
        pattern_type="aesthetic", pattern_index=(ln * 7 + 10) % 60,
        skip_deadlock_check=True,              # 공정비교: 양쪽 동일(유닛 ON은 생성기가 내부 강제)
        unit_assembly=unit,
        use_reverse_generation=False,          # 계획: reverse 강제 금지(봇하드 주범)
        size_diversity_start_level=11,
    )
    lj = g.generate(p).level_json
    prof = get_profile(BotType.AVERAGE)
    res = sim.simulate_with_profile(lj, prof, iterations=ITERS)
    clear = res.get("clear_rate", 0) if isinstance(res, dict) else getattr(res, "clear_rate", 0)
    tiles = g._collectable_tile_count(lj)
    layers = [len((lj.get(f"layer_{i}") or {}).get("tiles") or {})
              for i in range(int(lj.get("layer", 0) or 0))]
    layers = [x for x in layers if x]
    cnt = _clearability_type_counts(lj)
    bad3 = {t: c for t, c in cnt.items() if c % 3}
    return {
        "clear": float(clear), "tiles": tiles, "layers": layers,
        "floating": floating_count(lj), "div3_bad": bad3,
    }


print("=" * 96)
print(f"유닛조립 v2(성긴대칭) 검증 — 봇 average {ITERS}회")
print("=" * 96)
print(f"{'Lv':>5} {'난이도':>6} | {'OFF clear':>9} {'타일':>5} {'층분포':<22} | "
      f"{'ON clear':>8} {'타일':>5} {'층분포':<22} {'fl(OFF/ON)':>11} {'÷3':>4}")
print("-" * 96)

off_rates, on_rates, fails = [], [], []
for ln, td in LEVELS:
    try:
        a = measure(ln, td, False)
        b = measure(ln, td, True)
        off_rates.append(a["clear"])
        on_rates.append(b["clear"])
        flag = ""
        if b["clear"] <= 0.001:
            flag = " ❌CLEAR0"
            fails.append(f"Lv{ln} clear=0")
        if b["floating"]:
            flag += " ❌FLOAT"
            fails.append(f"Lv{ln} floating={b['floating']}")
        if b["div3_bad"]:
            flag += " ❌÷3"
            fails.append(f"Lv{ln} div3={b['div3_bad']}")
        print(f"{ln:5} {td:6.2f} | {a['clear']:9.2f} {a['tiles']:5} {str(a['layers']):<22} | "
              f"{b['clear']:8.2f} {b['tiles']:5} {str(b['layers']):<22} {a['floating']}/{b['floating']:<3} "
              f"{'OK' if not b['div3_bad'] else 'NG':>4}{flag}")
    except Exception as e:  # noqa: BLE001
        import traceback
        print(f"{ln:5} ERROR {type(e).__name__}: {e}")
        traceback.print_exc()
        fails.append(f"Lv{ln} exception")

print("-" * 96)
if off_rates and on_rates:
    print(f"평균 clear  OFF {statistics.mean(off_rates):.2f}  →  ON {statistics.mean(on_rates):.2f}")
    print(f"최저 clear  OFF {min(off_rates):.2f}  →  ON {min(on_rates):.2f}")
print(f"\n{'✅ 전부 통과' if not fails else '❌ 실패: ' + str(fails)}")
