"""
개선된 난이도 조절 시스템 테스트
목표: 그리드 크기 및 타일 타입 수 동적 조절로 난이도 범위 확장 검증
"""
import json
from app.core.generator import LevelGenerator
from app.core.bot_simulator import BotSimulator
from app.models.level import GenerationParams
from app.models.bot_profile import BotTeam


def test_improved_difficulty_range():
    """개선된 난이도 범위 테스트"""
    generator = LevelGenerator()
    simulator = BotSimulator()
    team = BotTeam.default_team(iterations_per_bot=30)

    # 테스트 설정 - 더 넓은 범위 테스트
    target_difficulties = [0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8]
    results = []

    print("=" * 80)
    print("개선된 난이도 범위 테스트")
    print("개선 사항:")
    print("  - 타일 타입 수 증가 (7개 → 9개 for 80%+)")
    print("  - 그리드 크기 동적 조절 (5x5~9x9)")
    print("  - moves_ratio 공격적 조정")
    print("=" * 80)

    for target in target_difficulties:
        # 그리드 크기 동적 설정 (개선된 v2 로직 반영)
        if target >= 0.85:
            grid_size = (5, 5)
            tile_types = ["t0", "t1", "t2", "t3", "t4", "t5", "t6", "t7", "t8"]  # 9 types
        elif target >= 0.75:
            grid_size = (6, 6)
            tile_types = ["t0", "t2", "t3", "t4", "t5", "t6", "t7", "t8"]  # 8 types
        elif target >= 0.6:
            grid_size = (6, 6)
            tile_types = ["t0", "t2", "t3", "t4", "t5", "t6", "t7"]  # 7 types
        elif target >= 0.5:
            grid_size = (7, 7)  # Larger grid to avoid overshoot
            tile_types = ["t0", "t2", "t3", "t4", "t5", "t6"]  # 6 types
        elif target >= 0.4:
            grid_size = (7, 7)
            tile_types = ["t0", "t2", "t4", "t5", "t6"]  # 5 types
        elif target >= 0.3:
            grid_size = (7, 7)
            tile_types = ["t0", "t2", "t4", "t5"]  # 4 types
        elif target >= 0.2:
            grid_size = (8, 8)
            tile_types = ["t0", "t2", "t4"]  # 3 types
        else:
            grid_size = (8, 8)
            tile_types = ["t0", "t2", "t4"]  # 3 types

        params = GenerationParams(
            target_difficulty=target,
            grid_size=grid_size,
            max_layers=7,
            tile_types=tile_types,
            obstacle_types=[],
            goals=[{"type": "craft", "direction": "s", "count": 3}],
        )

        # 레벨 생성
        result = generator.generate(params)
        level_json = result.level_json
        max_moves = level_json.get("max_moves", 30)

        # 봇 시뮬레이션
        sim_result = simulator.assess_difficulty(level_json, team=team, max_moves=max_moves)

        # overall_difficulty는 0-100 스케일, target은 0-1 스케일
        actual_normalized = sim_result.overall_difficulty / 100

        results.append({
            "target": target,
            "actual": actual_normalized,
            "grade": result.grade.value,
            "grid": f"{grid_size[0]}x{grid_size[1]}",
            "tile_count": len(tile_types),
        })

        diff = abs(target - actual_normalized)
        status = "✓" if diff < 0.1 else "✗" if diff > 0.2 else "△"
        print(f"목표: {target:.1%} → 실제: {actual_normalized:.1%} ({result.grade.value}) "
              f"[{grid_size[0]}x{grid_size[1]}, {len(tile_types)} types] {status}")

    # 분석 결과
    print("\n" + "=" * 80)
    print("분석 결과")
    print("=" * 80)

    actual_values = [r["actual"] for r in results]
    errors = [abs(r["target"] - r["actual"]) for r in results]

    print(f"  난이도 범위: {min(actual_values):.1%} ~ {max(actual_values):.1%}")
    print(f"  평균 오차: {sum(errors)/len(errors):.1%}")
    print(f"  최대 오차: {max(errors):.1%}")

    # 세부 분석
    print("\n[난이도별 상세]")
    for r in results:
        err = abs(r["target"] - r["actual"])
        print(f"  {r['target']:.0%}: 목표 {r['target']:.1%} vs 실제 {r['actual']:.1%} (오차 {err:.1%})")

    return results


def test_high_difficulty_with_obstacles():
    """고난이도 + 장애물 테스트"""
    generator = LevelGenerator()
    simulator = BotSimulator()
    team = BotTeam.default_team(iterations_per_bot=30)

    print("\n" + "=" * 80)
    print("고난이도 + 장애물 테스트 (목표: 60-80%)")
    print("=" * 80)

    configs = [
        # (target, grid_size, tile_types, obstacles)
        (0.6, (6, 6), ["t0", "t2", "t3", "t4", "t5", "t6", "t7"], ["chain"]),
        (0.7, (5, 5), ["t0", "t2", "t3", "t4", "t5", "t6", "t7", "t8"], ["chain", "frog"]),
        (0.8, (5, 5), ["t0", "t1", "t2", "t3", "t4", "t5", "t6", "t7", "t8"], ["chain", "frog", "ice"]),
    ]

    results = []
    for target, grid_size, tile_types, obstacles in configs:
        params = GenerationParams(
            target_difficulty=target,
            grid_size=grid_size,
            max_layers=7,
            tile_types=tile_types,
            obstacle_types=obstacles,
            goals=[{"type": "craft", "direction": "s", "count": 3}],
        )

        result = generator.generate(params)
        level_json = result.level_json
        max_moves = level_json.get("max_moves", 30)
        sim_result = simulator.assess_difficulty(level_json, team=team, max_moves=max_moves)
        actual_normalized = sim_result.overall_difficulty / 100

        results.append({
            "target": target,
            "actual": actual_normalized,
            "grade": result.grade.value,
        })

        diff = abs(target - actual_normalized)
        status = "✓" if diff < 0.1 else "✗"
        obs_str = ", ".join(obstacles)
        print(f"목표: {target:.1%} → 실제: {actual_normalized:.1%} ({result.grade.value}) "
              f"[{grid_size[0]}x{grid_size[1]}, {len(tile_types)} types, {obs_str}] {status}")

    return results


def main():
    print("=" * 80)
    print("개선된 자동 레벨 생성 시스템 테스트")
    print("=" * 80)

    # 기본 난이도 범위 테스트
    test_improved_difficulty_range()

    # 고난이도 테스트
    test_high_difficulty_with_obstacles()

    print("\n테스트 완료!")


if __name__ == "__main__":
    main()
