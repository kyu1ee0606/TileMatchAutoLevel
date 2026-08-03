"""[유닛조립 v2 배치 실측] 소규모 배치 생성 + 순차검증 라운드 모사 → 통과율 A/B.

계획 PLAN_unit_assembly_sparse_symmetric.md §6:
  "재활성 전 반드시 배치 생성 → 순차검증 통과율 실측(단일샷 아님)."

프론트 순차검증을 백엔드에서 모사:
  라운드 반복 = [측정(RL 스킬스윕 대체: 봇 프로필 스윕)] → [실패분 재생성(offset 학습)]
  통과 기준 = |예측 - 목표| <= TOL  AND  clear > 0
"""
import sys
import random
import argparse
import statistics

sys.path.insert(0, "/Users/casualdev/TileMatchAutoLevel/backend")
from app.core.generator import LevelGenerator            # noqa: E402
from app.models.level import GenerationParams            # noqa: E402
from app.core.bot_simulator import BotSimulator          # noqa: E402
from app.models.bot_profile import BotType, get_profile  # noqa: E402

g = LevelGenerator()
sim = BotSimulator()
# 스킬 스윕(프론트 RL 스윕 근사) — 초보~숙련 가중 평균
SWEEP = [(BotType.NOVICE, 0.15), (BotType.CASUAL, 0.25),
         (BotType.AVERAGE, 0.35), (BotType.EXPERT, 0.25)]
PROFS = [(get_profile(bt), w) for bt, w in SWEEP]
ITERS = 6
TOL = 0.15          # |예측-목표| 허용
MAX_ROUNDS = 4


def target_clear_for(td):
    """목표 클리어율 ≈ 1 - 난이도 (프론트 동적 목표의 단순 근사)."""
    return max(0.15, min(0.95, 1.0 - td))


def measure(lj):
    tot, wsum = 0.0, 0.0
    for prof, w in PROFS:
        r = sim.simulate_with_profile(lj, prof, iterations=ITERS)
        tot += getattr(r, "clear_rate", 0.0) * w
        wsum += w
    return tot / (wsum or 1)


def gen_level(ln, td, unit, offset, seed):
    random.seed(seed)
    ml = max(2, min(10, 3 + int(td * 7) + offset))
    p = GenerationParams(
        target_difficulty=max(0.05, min(0.95, td + offset * 0.03)),
        grid_size=(7, 7), level_number=ln,
        pattern_type="aesthetic", pattern_index=(seed * 7 + 10) % 60,
        max_layers=ml,
        skip_deadlock_check=True,
        unit_assembly=unit,
        use_reverse_generation=False,
        size_diversity_start_level=11,
    )
    return g.generate(p).level_json


def run_batch(levels, unit, label):
    """levels = [(ln, td)]. 순차검증 라운드 모사 → 통과율."""
    state = {}
    for ln, td in levels:
        state[ln] = {"td": td, "offset": 0, "passed": False, "best": None, "gap": 9.9}

    for rnd in range(1, MAX_ROUNDS + 1):
        pending = [ln for ln in state if not state[ln]["passed"]]
        if not pending:
            break
        for ln in pending:
            s = state[ln]
            seed = 9000 + ln * 13 + rnd
            try:
                lj = gen_level(ln, s["td"], unit, s["offset"], seed)
                pred = measure(lj)
            except Exception:  # noqa: BLE001
                continue
            tgt = target_clear_for(s["td"])
            gap = pred - tgt
            if abs(gap) < abs(s["gap"]):
                s["gap"] = gap
                s["best"] = pred
            if pred > 0.0 and abs(gap) <= TOL:
                s["passed"] = True
            else:
                # offset 학습: 너무 어려우면 쉽게(+), 너무 쉬우면 어렵게(-)
                s["offset"] = max(-3, min(3, s["offset"] + (1 if gap < 0 else -1)))
        done = sum(1 for v in state.values() if v["passed"])
        print(f"  [{label}] 라운드{rnd}: 통과 {done}/{len(levels)}")

    passed = sum(1 for v in state.values() if v["passed"])
    zero = sum(1 for v in state.values() if (v["best"] or 0) <= 0.001)
    gaps = [abs(v["gap"]) for v in state.values() if v["gap"] < 9]
    return {
        "passed": passed, "total": len(levels), "zero": zero,
        "mean_gap": statistics.mean(gaps) if gaps else 0,
        "fails": sorted(ln for ln, v in state.items() if not v["passed"]),
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--count", type=int, default=40, help="샘플 레벨 수")
    args = ap.parse_args()

    # 난이도 전 구간 균등 샘플
    step = max(1, 1500 // args.count)
    levels = [(ln, round(0.15 + (ln / 1500) * 0.72, 2))
              for ln in range(30, 1500, step)][:args.count]

    print("=" * 72)
    print(f"유닛조립 v2 배치 A/B — {len(levels)}레벨 × 최대 {MAX_ROUNDS}라운드 (TOL={TOL})")
    print("=" * 72)

    print("\n[OFF] 현행 경로")
    off = run_batch(levels, False, "OFF")
    print("\n[ON] 유닛조립 v2(성긴대칭)")
    on = run_batch(levels, True, "ON ")

    n = len(levels)
    print("\n" + "=" * 72)
    print(f"{'':18}{'OFF(현행)':>14}{'ON(v2)':>14}")
    print(f"{'통과':18}{off['passed']}/{n:<12}{on['passed']}/{n:<12}")
    print(f"{'통과율':18}{off['passed']/n*100:13.1f}%{on['passed']/n*100:13.1f}%")
    print(f"{'clear=0 잔존':18}{off['zero']:14}{on['zero']:14}")
    print(f"{'평균 |gap|':18}{off['mean_gap']:14.3f}{on['mean_gap']:14.3f}")
    print(f"\nOFF 미통과: {off['fails'][:15]}")
    print(f"ON  미통과: {on['fails'][:15]}")

    d = on['passed'] - off['passed']
    print()
    if d >= 0:
        print(f"판정: ✅ v2 통과율이 현행 대비 {d:+d}개 — 재활성 후보 (배치 실측 기준 열세 아님)")
    else:
        print(f"판정: ❌ v2 통과율이 현행 대비 {d:+d}개 — 추가 튜닝 필요")


if __name__ == "__main__":
    main()
