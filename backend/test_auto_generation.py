#!/usr/bin/env python3
"""
Automated level generation test script.
Tests level generation across different difficulty ranges and analyzes accuracy.
"""

import asyncio
import time
import json
from typing import Dict, List, Tuple
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed

# Add app to path
sys.path.insert(0, '/Users/casualdev/TileMatchAutoLevel/backend')

from app.core.generator import LevelGenerator
from app.core.bot_simulator import BotSimulator
from app.core.analyzer import LevelAnalyzer
from app.models.level import GenerationParams
from app.models.bot_profile import BotType, get_profile

# Early exit threshold
EARLY_EXIT_THRESHOLD = 80.0


# Target clear rates calculation (same as in generate.py)
BASE_TARGET_RATES = {
    "novice": 0.40,
    "casual": 0.60,
    "average": 0.75,
    "expert": 0.90,
    "optimal": 0.98,
}


def calculate_target_clear_rates(target_difficulty: float) -> Dict[str, float]:
    """Calculate target clear rates based on target difficulty.

    EASY levels (0-0.4): All bots should have very high clear rates.
    MEDIUM levels (0.4-0.6): Transition zone with varied clear rates.
    HARD levels (0.6-1.0): Significant difficulty for all but optimal.
    """
    rates = {}

    # EASY levels (0-0.4): All bots should have very high clear rates
    if target_difficulty <= 0.4:
        t = target_difficulty / 0.4
        easy_rates = {
            "novice": 0.99 - t * 0.20,    # 99% -> 79%
            "casual": 0.99 - t * 0.15,    # 99% -> 84%
            "average": 0.99 - t * 0.10,   # 99% -> 89%
            "expert": 0.99 - t * 0.05,    # 99% -> 94%
            "optimal": 0.99 - t * 0.01,   # 99% -> 98%
        }
        for bot_type in BASE_TARGET_RATES:
            rates[bot_type] = easy_rates.get(bot_type, 0.95)
    elif target_difficulty <= 0.6:
        # MEDIUM levels (0.4-0.6): Transition zone
        t = (target_difficulty - 0.4) / 0.2
        medium_start = {"novice": 0.79, "casual": 0.84, "average": 0.89, "expert": 0.94, "optimal": 0.98}
        medium_end = {"novice": 0.55, "casual": 0.70, "average": 0.82, "expert": 0.92, "optimal": 0.98}
        for bot_type in BASE_TARGET_RATES:
            start = medium_start.get(bot_type, 0.80)
            end = medium_end.get(bot_type, 0.70)
            rates[bot_type] = start - t * (start - end)
    else:
        # HARD levels (0.6-1.0): Significant difficulty
        t = (target_difficulty - 0.6) / 0.4
        hard_start = {"novice": 0.55, "casual": 0.70, "average": 0.82, "expert": 0.92, "optimal": 0.98}
        hard_end = {"novice": 0.10, "casual": 0.25, "average": 0.50, "expert": 0.75, "optimal": 0.88}
        for bot_type in BASE_TARGET_RATES:
            start = hard_start.get(bot_type, 0.70)
            end = hard_end.get(bot_type, 0.40)
            rates[bot_type] = start - t * (start - end)

    for bot_type in rates:
        rates[bot_type] = max(0.01, min(0.99, rates[bot_type]))
    return rates


def calculate_match_score(actual_rates: Dict[str, float], target_rates: Dict[str, float]) -> Tuple[float, float, float]:
    """Calculate match score between actual and target clear rates."""
    gaps = []
    for bot_type in target_rates:
        actual = actual_rates.get(bot_type, 0)
        target = target_rates[bot_type]
        gap = abs(actual - target) * 100
        gaps.append(gap)

    if not gaps:
        return 100.0, 0.0, 0.0

    avg_gap = sum(gaps) / len(gaps)
    max_gap = max(gaps)
    weighted_gap = avg_gap * 0.6 + max_gap * 0.4
    match_score = max(0, 100 - weighted_gap * 2)

    return match_score, avg_gap, max_gap


def calculate_total_tiles(level_json: Dict) -> int:
    """Calculate total tiles including internal tiles in stack/craft containers."""
    total_tiles = 0
    num_layers = level_json.get("layer", 8)

    for i in range(num_layers):
        layer_key = f"layer_{i}"
        layer_data = level_json.get(layer_key, {})
        tiles = layer_data.get("tiles", {})

        for pos, tile_data in tiles.items():
            if isinstance(tile_data, list) and len(tile_data) > 0:
                tile_type = tile_data[0]
                if isinstance(tile_type, str) and (
                    tile_type.startswith("stack_") or tile_type.startswith("craft_")
                ):
                    stack_count = 1
                    if len(tile_data) > 2:
                        extra = tile_data[2]
                        if isinstance(extra, list) and len(extra) > 0:
                            stack_count = int(extra[0]) if extra[0] else 1
                        elif isinstance(extra, dict):
                            stack_count = int(extra.get("totalCount", extra.get("count", 1)))
                        elif isinstance(extra, (int, float)):
                            stack_count = int(extra)
                    total_tiles += stack_count
                else:
                    total_tiles += 1
            else:
                total_tiles += 1

    return total_tiles


def test_single_level(
    generator: LevelGenerator,
    bot_simulator: BotSimulator,
    analyzer: LevelAnalyzer,
    target_difficulty: float,
    simulation_iterations: int = 20,  # Reduced from 30
    max_retries: int = 5,
) -> Dict:
    """Test generation of a single level with given target difficulty."""

    # OPTIMIZATION: Adaptive simulation iterations based on difficulty
    if target_difficulty <= 0.3:
        effective_iterations = min(15, simulation_iterations)
    elif target_difficulty <= 0.5:
        effective_iterations = min(18, simulation_iterations)
    else:
        effective_iterations = simulation_iterations

    # CALIBRATED tile types based on difficulty
    if target_difficulty >= 0.85:
        tile_types = ["t0", "t2", "t3", "t4", "t5", "t6", "t7"]  # 7 types for extreme
    elif target_difficulty >= 0.7:
        tile_types = ["t0", "t2", "t3", "t4", "t5", "t6"]  # 6 types for very hard
    elif target_difficulty >= 0.5:
        tile_types = ["t0", "t2", "t4", "t5", "t6"]  # 5 types for hard
    elif target_difficulty >= 0.3:
        tile_types = ["t0", "t2", "t4", "t5"]  # 4 types for medium
    else:
        tile_types = ["t0", "t2", "t4"]  # 3 types for easy

    # CALIBRATED moves_ratio based on difficulty
    if target_difficulty <= 0.3:
        moves_ratio = 1.4  # Very easy
    elif target_difficulty <= 0.5:
        moves_ratio = 1.25  # Easy/Medium
    elif target_difficulty <= 0.7:
        moves_ratio = 1.15  # Hard
    elif target_difficulty <= 0.85:
        moves_ratio = 1.08  # Very Hard
    else:
        moves_ratio = 1.03  # Extreme

    # Determine obstacles based on difficulty
    if target_difficulty >= 0.7:
        obstacle_types = ["chain", "frog"]
    elif target_difficulty >= 0.5:
        obstacle_types = ["chain"]
    else:
        obstacle_types = []

    best_result = None
    best_match_score = -1
    best_data = {}

    bot_types = [BotType.NOVICE, BotType.CASUAL, BotType.AVERAGE, BotType.EXPERT, BotType.OPTIMAL]

    for attempt in range(max_retries):
        try:
            params = GenerationParams(
                target_difficulty=target_difficulty,
                grid_size=(7, 7),
                max_layers=7,
                tile_types=tile_types,
                obstacle_types=obstacle_types if obstacle_types else None,
                goals=[{"type": "craft", "direction": "s", "count": 3}],
            )

            result = generator.generate(params)
            level_json = result.level_json

            # Calculate total tiles
            total_tiles = calculate_total_tiles(level_json)

            # Apply calibrated move constraint based on difficulty
            original_max_moves = level_json.get("max_moves", 50)
            ratio_based_moves = max(total_tiles, int(total_tiles * moves_ratio))
            modified_max_moves = max(total_tiles, min(original_max_moves, ratio_based_moves))
            level_json["max_moves"] = modified_max_moves

            # Calculate target rates based on USER's target_difficulty (FIX!)
            target_rates = calculate_target_clear_rates(target_difficulty)

            # OPTIMIZATION: Run bot simulations in PARALLEL
            def run_bot_simulation(bot_type: BotType) -> Tuple[str, float]:
                profile = get_profile(bot_type)
                sim_result = bot_simulator.simulate_with_profile(
                    level_json,
                    profile,
                    iterations=effective_iterations,
                    max_moves=modified_max_moves,
                )
                return bot_type.value, sim_result.clear_rate

            actual_rates = {}
            with ThreadPoolExecutor(max_workers=5) as executor:
                futures = {executor.submit(run_bot_simulation, bt): bt for bt in bot_types}
                for future in as_completed(futures):
                    bot_name, clear_rate = future.result()
                    actual_rates[bot_name] = clear_rate

            # Calculate match score
            match_score, avg_gap, max_gap = calculate_match_score(actual_rates, target_rates)

            if match_score > best_match_score:
                best_match_score = match_score
                best_result = result
                best_data = {
                    "level_json": level_json,
                    "actual_rates": actual_rates,
                    "target_rates": target_rates,
                    "match_score": match_score,
                    "avg_gap": avg_gap,
                    "max_gap": max_gap,
                    "total_tiles": total_tiles,
                    "max_moves": modified_max_moves,
                    "attempt": attempt + 1,
                }

            # OPTIMIZATION: Early exit if match is good enough
            if match_score >= EARLY_EXIT_THRESHOLD:
                # Run static analysis only for final result
                static_report = analyzer.analyze(level_json)
                best_data["static_score"] = static_report.score
                best_data["static_grade"] = static_report.grade.value
                break

        except Exception as e:
            print(f"  Attempt {attempt + 1} failed: {e}")
            continue

    # Run static analysis for best result if not already done
    if best_data and "static_score" not in best_data:
        static_report = analyzer.analyze(best_data["level_json"])
        best_data["static_score"] = static_report.score
        best_data["static_grade"] = static_report.grade.value

    return best_data


def run_tests():
    """Run automated tests across different difficulty levels."""
    print("=" * 60)
    print("Automated Level Generation Test")
    print("=" * 60)

    generator = LevelGenerator()
    bot_simulator = BotSimulator()
    analyzer = LevelAnalyzer()

    # Test different difficulty levels
    difficulty_levels = [0.2, 0.35, 0.5, 0.65, 0.8]
    results = []

    for difficulty in difficulty_levels:
        print(f"\n[Testing target_difficulty = {difficulty:.0%}]")

        test_results = []
        for i in range(3):  # 3 tests per difficulty
            print(f"  Test {i + 1}/3...", end=" ", flush=True)
            start_time = time.time()

            data = test_single_level(
                generator,
                bot_simulator,
                analyzer,
                target_difficulty=difficulty,
                simulation_iterations=30,
                max_retries=5,
            )

            elapsed = time.time() - start_time

            if data:
                test_results.append(data)
                print(f"Match: {data['match_score']:.1f}% | "
                      f"Static: {data['static_score']:.1f} | "
                      f"Time: {elapsed:.1f}s")
            else:
                print("FAILED")

        if test_results:
            avg_match = sum(r['match_score'] for r in test_results) / len(test_results)
            avg_static = sum(r['static_score'] for r in test_results) / len(test_results)

            results.append({
                "target_difficulty": difficulty,
                "avg_match_score": avg_match,
                "avg_static_score": avg_static,
                "tests": test_results,
            })

    # Print summary
    print("\n" + "=" * 60)
    print("TEST SUMMARY")
    print("=" * 60)
    print(f"{'Target':<10} {'Avg Match':<12} {'Avg Static':<12} {'Status'}")
    print("-" * 50)

    for r in results:
        target = f"{r['target_difficulty']:.0%}"
        match = f"{r['avg_match_score']:.1f}%"
        static = f"{r['avg_static_score']:.1f}"
        status = "✓ Good" if r['avg_match_score'] >= 70 else "⚠ Needs Work"
        print(f"{target:<10} {match:<12} {static:<12} {status}")

    # Detailed analysis
    print("\n" + "=" * 60)
    print("DETAILED BOT ANALYSIS")
    print("=" * 60)

    for r in results:
        print(f"\n[Target: {r['target_difficulty']:.0%}]")

        # Average across all tests
        if r['tests']:
            avg_actual = {}
            avg_target = {}
            for bot in ['novice', 'casual', 'average', 'expert', 'optimal']:
                avg_actual[bot] = sum(t['actual_rates'].get(bot, 0) for t in r['tests']) / len(r['tests'])
                avg_target[bot] = r['tests'][0]['target_rates'].get(bot, 0)

            print(f"  {'Bot':<10} {'Target':<10} {'Actual':<10} {'Gap':<10}")
            print(f"  {'-' * 40}")
            for bot in ['novice', 'casual', 'average', 'expert', 'optimal']:
                target = avg_target[bot]
                actual = avg_actual[bot]
                gap = actual - target
                gap_str = f"+{gap:.0%}" if gap >= 0 else f"{gap:.0%}"
                print(f"  {bot:<10} {target:.0%}       {actual:.0%}       {gap_str}")

    return results


if __name__ == "__main__":
    run_tests()
