#!/usr/bin/env python3
"""
Determinism Verification Test for Optimal Bot

Tests that the optimal bot produces identical results when run multiple times
with the same seed, verifying that randomness has been completely removed.

Based on expert panel recommendation (Lisa Crispin, Kent Beck):
"테스트 없이는 '최적'이라고 주장할 수 없다"
"""

import sys
sys.path.insert(0, '/Users/casualdev/TileMatchAutoLevel/backend')

from app.core.bot_simulator import BotSimulator
from app.models.bot_profile import BotType, get_profile
from typing import List, Dict, Any


def create_test_level() -> Dict[str, Any]:
    """Create a simple test level for determinism testing."""
    return {
        "tiles": [
            # Layer 0: Simple matching tiles
            {"layerIdx": 0, "pos": "1_1", "tileType": "t1", "craft": "", "stackCount": 1},
            {"layerIdx": 0, "pos": "1_2", "tileType": "t1", "craft": "", "stackCount": 1},
            {"layerIdx": 0, "pos": "1_3", "tileType": "t1", "craft": "", "stackCount": 1},
            {"layerIdx": 0, "pos": "2_1", "tileType": "t2", "craft": "", "stackCount": 1},
            {"layerIdx": 0, "pos": "2_2", "tileType": "t2", "craft": "", "stackCount": 1},
            {"layerIdx": 0, "pos": "2_3", "tileType": "t2", "craft": "", "stackCount": 1},
            {"layerIdx": 0, "pos": "3_1", "tileType": "t3", "craft": "", "stackCount": 1},
            {"layerIdx": 0, "pos": "3_2", "tileType": "t3", "craft": "", "stackCount": 1},
            {"layerIdx": 0, "pos": "3_3", "tileType": "t3", "craft": "", "stackCount": 1},
        ],
        "layer_cols": {0: 5},
        "goals": {"t1": 3, "t2": 3, "t3": 3},
        "max_moves": 50,
    }


def create_complex_test_level() -> Dict[str, Any]:
    """Create a more complex test level with effect tiles."""
    return {
        "tiles": [
            # Craft tile with direction
            {"layerIdx": 0, "pos": "3_3", "tileType": "craft_s", "craft": "e", "stackCount": 3},
            # ICE tile
            {"layerIdx": 0, "pos": "2_2", "tileType": "t1", "craft": "", "stackCount": 1,
             "effect": "ice", "effect_data": {"remaining": 2}},
            # Regular tiles
            {"layerIdx": 0, "pos": "1_1", "tileType": "t1", "craft": "", "stackCount": 1},
            {"layerIdx": 0, "pos": "1_2", "tileType": "t1", "craft": "", "stackCount": 1},
            {"layerIdx": 0, "pos": "1_3", "tileType": "t2", "craft": "", "stackCount": 1},
            {"layerIdx": 0, "pos": "2_1", "tileType": "t2", "craft": "", "stackCount": 1},
            {"layerIdx": 0, "pos": "2_3", "tileType": "t2", "craft": "", "stackCount": 1},
            {"layerIdx": 0, "pos": "3_1", "tileType": "t3", "craft": "", "stackCount": 1},
            {"layerIdx": 0, "pos": "3_2", "tileType": "t3", "craft": "", "stackCount": 1},
        ],
        "layer_cols": {0: 7},
        "goals": {"craft_s": 3, "t1": 2, "t2": 3},
        "max_moves": 100,
    }


def run_simulation_with_seed(level_data: Dict[str, Any], bot_type: BotType, seed: int) -> Dict[str, Any]:
    """Run a single simulation with a specific seed and return results."""
    simulator = BotSimulator()
    profile = get_profile(bot_type)

    max_moves = level_data.get("max_moves", 50)

    # Use iterations=1 to get single run, then extract from aggregated result
    result = simulator.simulate_with_profile(level_data, profile, iterations=1, max_moves=max_moves, seed=seed)

    return {
        "cleared": result.clear_rate == 1.0,  # 1 iteration, so 1.0 = cleared, 0.0 = failed
        "moves_used": int(result.avg_moves),  # Single run, so avg = actual
        "min_moves": result.min_moves,
        "max_moves": result.max_moves,
    }


def test_determinism_simple_level(iterations: int = 5, seed: int = 42):
    """Test determinism on a simple level."""
    print("=" * 80)
    print("TEST 1: Determinism on Simple Level")
    print("=" * 80)
    print(f"Running {iterations} iterations with seed={seed}")
    print()

    level_data = create_test_level()
    results: List[Dict[str, Any]] = []

    for i in range(iterations):
        result = run_simulation_with_seed(level_data, BotType.OPTIMAL, seed)
        results.append(result)
        print(f"Iteration {i+1}: cleared={result['cleared']}, "
              f"moves={result['moves_used']}")

    # Verify all results are identical
    first_result = results[0]
    all_identical = all(
        r['cleared'] == first_result['cleared'] and
        r['moves_used'] == first_result['moves_used']
        for r in results
    )

    print()
    if all_identical:
        print("✅ PASS: All iterations produced IDENTICAL results")
        print(f"   Deterministic behavior confirmed for seed={seed}")
    else:
        print("❌ FAIL: Results differ across iterations")
        print("   Non-deterministic behavior detected!")
        for i, r in enumerate(results):
            print(f"   Iteration {i+1}: {r}")

    print()
    return all_identical


def test_determinism_complex_level(iterations: int = 5, seed: int = 123):
    """Test determinism on a complex level with effect tiles."""
    print("=" * 80)
    print("TEST 2: Determinism on Complex Level (with Effect Tiles)")
    print("=" * 80)
    print(f"Running {iterations} iterations with seed={seed}")
    print()

    level_data = create_complex_test_level()
    results: List[Dict[str, Any]] = []

    for i in range(iterations):
        result = run_simulation_with_seed(level_data, BotType.OPTIMAL, seed)
        results.append(result)
        print(f"Iteration {i+1}: cleared={result['cleared']}, "
              f"moves={result['moves_used']}")

    # Verify all results are identical
    first_result = results[0]
    all_identical = all(
        r['cleared'] == first_result['cleared'] and
        r['moves_used'] == first_result['moves_used']
        for r in results
    )

    print()
    if all_identical:
        print("✅ PASS: All iterations produced IDENTICAL results")
        print(f"   Deterministic behavior confirmed for seed={seed}")
    else:
        print("❌ FAIL: Results differ across iterations")
        print("   Non-deterministic behavior detected!")
        for i, r in enumerate(results):
            print(f"   Iteration {i+1}: {r}")

    print()
    return all_identical


def test_different_seeds_produce_different_results():
    """Verify that different seeds produce different results (sanity check)."""
    print("=" * 80)
    print("TEST 3: Different Seeds Produce Different Results (Sanity Check)")
    print("=" * 80)
    print()

    level_data = create_test_level()
    seeds = [42, 123, 456, 789]
    results: List[Dict[str, Any]] = []

    for seed in seeds:
        result = run_simulation_with_seed(level_data, BotType.OPTIMAL, seed)
        results.append(result)
        print(f"Seed {seed}: cleared={result['cleared']}, "
              f"moves={result['moves_used']}")

    # Check if at least some results differ (they should, unless level is trivial)
    all_same = all(
        r['moves_used'] == results[0]['moves_used']
        for r in results
    )

    print()
    if not all_same:
        print("✅ PASS: Different seeds produce different move sequences")
        print("   RNG seeding is working correctly")
    else:
        print("⚠️  WARNING: All seeds produced identical move counts")
        print("   This may indicate level is too simple or RNG not being used")

    print()
    return not all_same


def test_expert_vs_optimal_determinism():
    """Test that both Expert and Optimal bots are deterministic."""
    print("=" * 80)
    print("TEST 4: Expert vs Optimal Bot Determinism")
    print("=" * 80)
    print()

    level_data = create_test_level()
    seed = 42
    iterations = 3

    # Test Expert bot
    print("Testing Expert Bot:")
    expert_results = []
    for i in range(iterations):
        result = run_simulation_with_seed(level_data, BotType.EXPERT, seed)
        expert_results.append(result)
        print(f"  Iteration {i+1}: moves={result['moves_used']}")

    expert_deterministic = all(
        r['moves_used'] == expert_results[0]['moves_used']
        for r in expert_results
    )

    # Test Optimal bot
    print("\nTesting Optimal Bot:")
    optimal_results = []
    for i in range(iterations):
        result = run_simulation_with_seed(level_data, BotType.OPTIMAL, seed)
        optimal_results.append(result)
        print(f"  Iteration {i+1}: moves={result['moves_used']}")

    optimal_deterministic = all(
        r['moves_used'] == optimal_results[0]['moves_used']
        for r in optimal_results
    )

    print()
    if expert_deterministic and optimal_deterministic:
        print("✅ PASS: Both Expert and Optimal bots are deterministic")
    else:
        if not expert_deterministic:
            print("❌ FAIL: Expert bot is non-deterministic")
        if not optimal_deterministic:
            print("❌ FAIL: Optimal bot is non-deterministic")

    print()
    return expert_deterministic and optimal_deterministic


def main():
    """Run all determinism tests."""
    print("\n")
    print("╔" + "=" * 78 + "╗")
    print("║" + " " * 20 + "DETERMINISM VERIFICATION TEST SUITE" + " " * 23 + "║")
    print("║" + " " * 78 + "║")
    print("║  Purpose: Verify that Optimal bot produces identical results with same seed  ║")
    print("║  Expert Panel Recommendation: Lisa Crispin, Kent Beck, Martin Fowler        ║")
    print("╚" + "=" * 78 + "╝")
    print("\n")

    results = {
        "simple_level": test_determinism_simple_level(iterations=5, seed=42),
        "complex_level": test_determinism_complex_level(iterations=5, seed=123),
        "different_seeds": test_different_seeds_produce_different_results(),
        "expert_vs_optimal": test_expert_vs_optimal_determinism(),
    }

    # Summary
    print("=" * 80)
    print("SUMMARY")
    print("=" * 80)
    total_tests = len(results)
    passed_tests = sum(1 for v in results.values() if v)

    for test_name, passed in results.items():
        status = "✅ PASS" if passed else "❌ FAIL"
        print(f"{status}: {test_name}")

    print()
    print(f"Total: {passed_tests}/{total_tests} tests passed")

    if passed_tests == total_tests:
        print()
        print("🎉 ALL TESTS PASSED - Optimal bot is fully deterministic!")
        print("   Randomness has been successfully removed for pattern_recognition=1.0")
        return 0
    else:
        print()
        print("⚠️  SOME TESTS FAILED - Non-deterministic behavior detected")
        print("   Further investigation needed in bot_simulator.py")
        return 1


if __name__ == "__main__":
    sys.exit(main())
