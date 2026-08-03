"""[유닛조립 v2 광역 검증] 표본 확대 — clear 분포로 데드락률 측정.

v1 실측: 조밀 유닛 ~40% 봇-언클리어러블(clear 0.0) → 프로덕션 1300/1500 붕괴.
v2(성긴대칭)가 그 비율을 얼마나 낮췄는지, OFF(현행)와 같은 조건에서 비교.
"""
import sys
import random
import statistics
from collections import Counter

sys.path.insert(0, "/Users/casualdev/TileMatchAutoLevel/backend")
from app.core.generator import LevelGenerator          # noqa: E402
from app.models.level import GenerationParams          # noqa: E402
from app.core.bot_simulator import BotSimulator        # noqa: E402
from app.core.solver import _clearability_type_counts  # noqa: E402
from app.models.bot_profile import BotType, get_profile  # noqa: E402

g = LevelGenerator()
sim = BotSimulator()
PROF = get_profile(BotType.AVERAGE)
ITERS = 10

# 난이도 전 구간 × 레벨대 — 30샘플
SAMPLES = []
for i, ln in enumerate([30, 80, 150, 220, 300, 380, 460, 540, 620, 700,
                        780, 860, 940, 1020, 1100, 1180, 1260, 1340, 1420, 1480]):
    td = round(0.15 + (ln / 1500) * 0.72, 2)
    SAMPLES.append((ln, td))


def run(ln, td, unit):
    random.seed(4242 + ln + (7 if unit else 0))
    p = GenerationParams(
        target_difficulty=td, grid_size=(7, 7), level_number=ln,
        pattern_type="aesthetic", pattern_index=(ln * 7 + 10) % 60,
        skip_deadlock_check=True,
        unit_assembly=unit,
        use_reverse_generation=False,
        size_diversity_start_level=11,
    )
    lj = g.generate(p).level_json
    res = sim.simulate_with_profile(lj, PROF, iterations=ITERS)
    clear = getattr(res, "clear_rate", 0.0)
    cnt = _clearability_type_counts(lj)
    return {
        "clear": float(clear),
        "tiles": g._collectable_tile_count(lj),
        "layers": len([1 for i in range(int(lj.get("layer", 0) or 0))
                       if (lj.get(f"layer_{i}") or {}).get("tiles")]),
        "div3_bad": bool({t: c for t, c in cnt.items() if c % 3}),
    }


print("=" * 84)
print(f"유닛조립 v2 광역 검증 — {len(SAMPLES)}샘플 × 봇 average {ITERS}회")
print("=" * 84)
print(f"{'Lv':>5} {'난이도':>5} | {'OFF':>6} {'타일':>5} {'층':>3} | {'ON(v2)':>7} {'타일':>5} {'층':>3} | 판정")
print("-" * 84)

off, on, off_dead, on_dead, div3_bad = [], [], [], [], []
for ln, td in SAMPLES:
    try:
        a = run(ln, td, False)
        b = run(ln, td, True)
        off.append(a["clear"]); on.append(b["clear"])
        if a["clear"] <= 0.001:
            off_dead.append(ln)
        if b["clear"] <= 0.001:
            on_dead.append(ln)
        if b["div3_bad"]:
            div3_bad.append(ln)
        mark = ""
        if b["clear"] <= 0.001:
            mark = "❌ON데드락"
        elif b["clear"] > a["clear"] + 0.1:
            mark = "✅ON우세"
        elif a["clear"] > b["clear"] + 0.1:
            mark = "△OFF우세"
        print(f"{ln:5} {td:5.2f} | {a['clear']:6.2f} {a['tiles']:5} {a['layers']:3} | "
              f"{b['clear']:7.2f} {b['tiles']:5} {b['layers']:3} | {mark}")
    except Exception as e:  # noqa: BLE001
        print(f"{ln:5} ERROR {type(e).__name__}: {str(e)[:60]}")

n = len(off)
print("-" * 84)
print(f"\n{'':14}{'OFF(현행)':>12}{'ON(v2)':>12}")
print(f"{'평균 clear':14}{statistics.mean(off):12.3f}{statistics.mean(on):12.3f}")
print(f"{'중앙 clear':14}{statistics.median(off):12.3f}{statistics.median(on):12.3f}")
print(f"{'데드락(0.0)':14}{len(off_dead):8}/{n:<3}{len(on_dead):8}/{n:<3}")
print(f"{'데드락률':14}{len(off_dead)/n*100:11.1f}%{len(on_dead)/n*100:11.1f}%")
print(f"{'clear>=0.3':14}{sum(1 for x in off if x>=0.3):8}/{n:<3}{sum(1 for x in on if x>=0.3):8}/{n:<3}")
print(f"\nOFF 데드락 레벨: {off_dead}")
print(f"ON  데드락 레벨: {on_dead}")
if div3_bad:
    print(f"⚠️ ÷3 위반(ON): {div3_bad}")
else:
    print("÷3 위반: 없음 ✅")

print()
v1_rate = 40.0
on_rate = len(on_dead) / n * 100
if on_rate <= len(off_dead) / n * 100 + 5:
    print(f"판정: ✅ v2 데드락률 {on_rate:.1f}% — 현행({len(off_dead)/n*100:.1f}%) 수준 이하. "
          f"v1(~{v1_rate:.0f}%) 대비 대폭 개선.")
else:
    print(f"판정: ❌ v2 데드락률 {on_rate:.1f}% — 현행({len(off_dead)/n*100:.1f}%)보다 높음. 추가 튜닝 필요.")
