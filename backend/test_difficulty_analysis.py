"""
자동 레벨 생성 시스템 난이도 분석 테스트
목표: 난이도 불일치 패턴 분석 및 개선점 도출
"""
import json
from app.core.generator import LevelGenerator
from app.core.bot_simulator import BotSimulator
from app.models.level import GenerationParams
from app.models.bot_profile import BotTeam

def test_difficulty_range():
    """다양한 목표 난이도에 대한 생성 결과 분석"""
    generator = LevelGenerator()
    simulator = BotSimulator()
    team = BotTeam.default_team(iterations_per_bot=50)

    # 테스트 설정
    target_difficulties = [0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8]
    results = []

    print("=" * 80)
    print("난이도 범위 테스트: 장애물 없음")
    print("=" * 80)

    for target in target_difficulties:
        params = GenerationParams(
            target_difficulty=target,
            grid_size=(7, 7),
            max_layers=7,
            tile_types=["t0", "t2", "t4", "t5", "t6"],
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
            "clear_rates": {r.bot_type.value: r.clear_rate for r in sim_result.bot_results},
        })

        diff = abs(target - actual_normalized)
        status = "✓" if diff < 0.1 else "✗"
        print(f"목표: {target:.1%} → 실제: {actual_normalized:.1%} ({result.grade.value}) {status}")

    print("\n" + "=" * 80)
    print("난이도 범위 테스트: 장애물 포함 (Chain, Ice)")
    print("=" * 80)

    results_with_obstacles = []
    for target in target_difficulties:
        params = GenerationParams(
            target_difficulty=target,
            grid_size=(7, 7),
            max_layers=7,
            tile_types=["t0", "t2", "t4", "t5", "t6"],
            obstacle_types=["chain", "ice"],
            goals=[{"type": "craft", "direction": "s", "count": 3}],
        )

        result = generator.generate(params)
        level_json = result.level_json
        max_moves = level_json.get("max_moves", 30)
        sim_result = simulator.assess_difficulty(level_json, team=team, max_moves=max_moves)

        actual_normalized = sim_result.overall_difficulty / 100

        results_with_obstacles.append({
            "target": target,
            "actual": actual_normalized,
            "grade": result.grade.value,
        })

        diff = abs(target - actual_normalized)
        status = "✓" if diff < 0.1 else "✗"
        print(f"목표: {target:.1%} → 실제: {actual_normalized:.1%} ({result.grade.value}) {status}")

    # 분석 결과
    print("\n" + "=" * 80)
    print("분석 결과")
    print("=" * 80)

    print("\n[장애물 없음]")
    actual_without = [r["actual"] for r in results]
    print(f"  난이도 범위: {min(actual_without):.1%} ~ {max(actual_without):.1%}")
    print(f"  평균 오차: {sum(abs(r['target']-r['actual']) for r in results)/len(results):.1%}")

    print("\n[장애물 있음]")
    actual_with = [r["actual"] for r in results_with_obstacles]
    print(f"  난이도 범위: {min(actual_with):.1%} ~ {max(actual_with):.1%}")
    print(f"  평균 오차: {sum(abs(r['target']-r['actual']) for r in results_with_obstacles)/len(results_with_obstacles):.1%}")

    return results, results_with_obstacles


def test_parameter_sensitivity():
    """파라미터별 난이도 영향도 분석"""
    generator = LevelGenerator()
    simulator = BotSimulator()
    team = BotTeam.default_team(iterations_per_bot=30)

    base_params = {
        "target_difficulty": 0.5,
        "grid_size": (7, 7),
        "max_layers": 7,
        "tile_types": ["t0", "t2", "t4", "t5", "t6"],
        "obstacle_types": [],
        "goals": [{"type": "craft", "direction": "s", "count": 3}],
    }

    print("\n" + "=" * 80)
    print("파라미터 민감도 분석")
    print("=" * 80)

    # 1. 레이어 수 변경
    print("\n[레이어 수 영향]")
    for layers in [3, 5, 7]:
        params = GenerationParams(**{**base_params, "max_layers": layers})
        result = generator.generate(params)
        max_moves = result.level_json.get("max_moves", 30)
        sim = simulator.assess_difficulty(result.level_json, team=team, max_moves=max_moves)
        print(f"  {layers} layers → {sim.overall_difficulty/100:.1%}")

    # 2. 타일 타입 수 변경
    print("\n[타일 타입 수 영향]")
    tile_configs = [
        ["t0", "t2", "t4"],           # 3개
        ["t0", "t2", "t4", "t5", "t6"], # 5개
        ["t0", "t1", "t2", "t3", "t4", "t5", "t6"], # 7개
    ]
    for tiles in tile_configs:
        params = GenerationParams(**{**base_params, "tile_types": tiles})
        result = generator.generate(params)
        max_moves = result.level_json.get("max_moves", 30)
        sim = simulator.assess_difficulty(result.level_json, team=team, max_moves=max_moves)
        print(f"  {len(tiles)} types → {sim.overall_difficulty/100:.1%}")

    # 3. 그리드 크기 변경
    print("\n[그리드 크기 영향]")
    for size in [(5, 5), (7, 7), (8, 8)]:
        params = GenerationParams(**{**base_params, "grid_size": size})
        result = generator.generate(params)
        max_moves = result.level_json.get("max_moves", 30)
        sim = simulator.assess_difficulty(result.level_json, team=team, max_moves=max_moves)
        print(f"  {size[0]}x{size[1]} → {sim.overall_difficulty/100:.1%}")

    # 4. 골 수 변경
    print("\n[골 수 영향]")
    goal_configs = [
        [{"type": "craft", "direction": "s", "count": 3}],  # 1개
        [{"type": "craft", "direction": "s", "count": 3}, {"type": "craft", "direction": "n", "count": 3}],  # 2개
        [{"type": "craft", "direction": "s", "count": 3}, {"type": "craft", "direction": "n", "count": 3},
         {"type": "craft", "direction": "e", "count": 3}, {"type": "craft", "direction": "w", "count": 3}],  # 4개
    ]
    for goals in goal_configs:
        params = GenerationParams(**{**base_params, "goals": goals})
        result = generator.generate(params)
        max_moves = result.level_json.get("max_moves", 30)
        sim = simulator.assess_difficulty(result.level_json, team=team, max_moves=max_moves)
        print(f"  {len(goals)} goals → {sim.overall_difficulty/100:.1%}")

    # 5. 장애물 조합
    print("\n[장애물 조합 영향]")
    obstacle_configs = [
        [],                    # 없음
        ["chain"],            # Chain만
        ["ice"],              # Ice만
        ["chain", "ice"],     # Chain + Ice
        ["chain", "ice", "frog"],  # Chain + Ice + Frog
    ]
    for obstacles in obstacle_configs:
        params = GenerationParams(**{**base_params, "obstacle_types": obstacles})
        result = generator.generate(params)
        max_moves = result.level_json.get("max_moves", 30)
        sim = simulator.assess_difficulty(result.level_json, team=team, max_moves=max_moves)
        obs_str = ", ".join(obstacles) if obstacles else "없음"
        print(f"  [{obs_str}] → {sim.overall_difficulty/100:.1%}")


def main():
    print("=" * 80)
    print("자동 레벨 생성 시스템 난이도 분석 테스트")
    print("=" * 80)

    # 난이도 범위 테스트
    test_difficulty_range()

    # 파라미터 민감도 분석
    test_parameter_sensitivity()

    print("\n테스트 완료!")


if __name__ == "__main__":
    main()
