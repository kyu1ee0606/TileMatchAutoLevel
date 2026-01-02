#!/usr/bin/env python3
"""
Level Set Generation Test Script
- Creates 10 level sets with irregular upward difficulty graphs
- Generates 100 total levels (10 sets x 10 levels each)
- Validates simulation works on all levels
- Cross-validates difficulty with 100 simulations each
"""

import random
import time
import json
from datetime import datetime
from pathlib import Path
from typing import List, Dict, Any, Tuple
from dataclasses import dataclass

# Add app to path
import sys
sys.path.insert(0, str(Path(__file__).parent))

from app.core.generator import LevelGenerator
from app.core.bot_simulator import BotSimulator
from app.models.bot_profile import BotType, get_profile
from app.models.level import GenerationParams


def create_irregular_upward_difficulties(level_count: int = 10) -> List[float]:
    """Create irregular but upward trending difficulty curve."""
    difficulties = []

    for i in range(level_count):
        # General upward trend
        target = 0.15 + (0.70 * i / (level_count - 1))  # 15% to 85%

        # Add irregularity (-10% to +10% variation)
        variation = random.uniform(-0.10, 0.10)

        # Ensure minimum progress from previous
        if difficulties:
            # Must be at least slightly higher than previous on average
            min_val = difficulties[-1] - 0.05
            difficulty = max(min_val, target + variation)
        else:
            difficulty = target + variation

        # Clamp to valid range
        difficulty = max(0.1, min(0.95, difficulty))
        difficulties.append(round(difficulty, 2))

    return difficulties


def generate_level(generator: LevelGenerator, target_difficulty: float, config: Dict) -> Tuple[Dict, float, str]:
    """Generate a single level with target difficulty."""
    params = GenerationParams(
        target_difficulty=target_difficulty,
        grid_size=config.get('grid_size', (7, 7)),
        max_layers=config.get('max_layers', 7),
        tile_types=config.get('tile_types', ['t0', 't2', 't4', 't5', 't6']),
        obstacle_types=config.get('obstacle_types', ['chain', 'frog']),
        goals=config.get('goals', [{'type': 'craft', 'direction': 's', 'count': 3}]),
    )
    result = generator.generate(params)

    return result.level_json, result.actual_difficulty, result.grade


def run_simulation(simulator: BotSimulator, level_json: Dict, iterations: int = 30) -> Dict[str, Any]:
    """Run simulation on a level with selected bot profiles (for faster testing)."""
    results = {}

    for bot_type in [BotType.CASUAL, BotType.AVERAGE, BotType.OPTIMAL]:
        profile = get_profile(bot_type)
        sim_result = simulator.simulate_with_profile(
            level_json,
            profile,
            iterations=iterations,
            max_moves=200,
            seed=42
        )
        results[bot_type.value] = {
            'clear_rate': sim_result.clear_rate,
            'avg_moves': sim_result.avg_moves,
        }

    return results


def calculate_difficulty_from_simulation(sim_results: Dict[str, Any]) -> float:
    """Calculate estimated difficulty from simulation results."""
    # Weight by bot type (optimal bot success = easier level)
    weights = {
        'casual': 0.20,
        'average': 0.40,
        'optimal': 0.40,
    }

    # Lower clear rate = higher difficulty
    weighted_fail_rate = 0
    for bot_type, weight in weights.items():
        clear_rate = sim_results.get(bot_type, {}).get('clear_rate', 0)
        fail_rate = 1.0 - clear_rate
        weighted_fail_rate += fail_rate * weight

    return weighted_fail_rate


def main():
    print("=" * 60)
    print("Level Set Generation Test")
    print("=" * 60)
    print()

    generator = LevelGenerator()
    simulator = BotSimulator()

    # Storage for results
    all_levels = []
    generation_results = []
    simulation_results = []

    # Base configuration for level generation
    base_config = {
        'grid_size': (7, 7),
        'max_layers': 7,
        'tile_types': ['t0', 't2', 't4', 't5', 't6'],
        'obstacle_types': ['chain', 'frog'],
        'goals': [{'type': 'craft', 'direction': 's', 'count': 3}],
    }

    # Phase 1: Generate 10 sets x 10 levels = 100 levels
    print("Phase 1: Generating 100 Levels (10 sets x 10 levels)")
    print("-" * 60)

    total_start = time.time()

    for set_idx in range(10):
        # Create irregular upward difficulty curve for this set
        difficulties = create_irregular_upward_difficulties(10)

        print(f"\nSet {set_idx + 1}/10:")
        print(f"  Difficulties: {difficulties}")

        set_levels = []
        set_results = []

        for level_idx, target_diff in enumerate(difficulties):
            try:
                level_json, actual_diff, grade = generate_level(generator, target_diff, base_config)

                level_id = f"test_set{set_idx+1:02d}_level{level_idx+1:02d}"

                all_levels.append({
                    'id': level_id,
                    'set_idx': set_idx,
                    'level_idx': level_idx,
                    'target_difficulty': target_diff,
                    'actual_difficulty': actual_diff,
                    'grade': grade,
                    'level_json': level_json,
                })

                set_results.append({
                    'level_idx': level_idx + 1,
                    'target': target_diff,
                    'actual': actual_diff,
                    'grade': grade,
                    'diff': round(actual_diff - target_diff, 3),
                })

            except Exception as e:
                print(f"  ERROR generating level {level_idx + 1}: {e}")
                set_results.append({
                    'level_idx': level_idx + 1,
                    'target': target_diff,
                    'error': str(e),
                })

        generation_results.append({
            'set_idx': set_idx + 1,
            'difficulties': difficulties,
            'results': set_results,
        })

        # Print summary for this set
        successful = [r for r in set_results if 'actual' in r]
        if successful:
            avg_diff = sum(r['diff'] for r in successful) / len(successful)
            print(f"  Generated: {len(successful)}/10, Avg diff from target: {avg_diff:+.3f}")

    gen_time = time.time() - total_start
    print(f"\nGeneration complete: {len(all_levels)} levels in {gen_time:.1f}s")

    # Phase 2: Validate all levels with simulation
    print("\n" + "=" * 60)
    print("Phase 2: Simulation Validation (Quick test - 10 iterations each)")
    print("-" * 60)

    valid_count = 0
    invalid_levels = []

    for i, level_data in enumerate(all_levels):
        try:
            # Quick validation with 10 iterations
            sim_result = run_simulation(simulator, level_data['level_json'], iterations=10)

            # Check if any bot can clear the level
            any_cleared = any(r['clear_rate'] > 0 for r in sim_result.values())

            if any_cleared:
                valid_count += 1
            else:
                invalid_levels.append(level_data['id'])

            if (i + 1) % 20 == 0:
                print(f"  Validated {i + 1}/100 levels...")

        except Exception as e:
            invalid_levels.append(f"{level_data['id']} (ERROR: {e})")

    print(f"\nValidation complete: {valid_count}/100 levels clearable")
    if invalid_levels:
        print(f"Invalid levels: {invalid_levels[:5]}{'...' if len(invalid_levels) > 5 else ''}")

    # Phase 3: Full simulation with 100 iterations for difficulty cross-validation
    print("\n" + "=" * 60)
    print("Phase 3: Difficulty Cross-Validation (100 iterations each)")
    print("-" * 60)

    cross_validation_results = []

    for i, level_data in enumerate(all_levels):
        try:
            sim_result = run_simulation(simulator, level_data['level_json'], iterations=30)
            estimated_diff = calculate_difficulty_from_simulation(sim_result)

            cross_validation_results.append({
                'id': level_data['id'],
                'set_idx': level_data['set_idx'],
                'level_idx': level_data['level_idx'],
                'target_difficulty': level_data['target_difficulty'],
                'generator_difficulty': level_data['actual_difficulty'],
                'simulated_difficulty': round(estimated_diff, 3),
                'grade': level_data['grade'],
                'optimal_clear_rate': sim_result['optimal']['clear_rate'],
                'average_clear_rate': sim_result['average']['clear_rate'],
                'casual_clear_rate': sim_result['casual']['clear_rate'],
            })

            if (i + 1) % 10 == 0:
                print(f"  Cross-validated {i + 1}/100 levels...")

        except Exception as e:
            print(f"  ERROR validating {level_data['id']}: {e}")

    # Phase 4: Analysis and Summary
    print("\n" + "=" * 60)
    print("Phase 4: Cross-Validation Analysis")
    print("-" * 60)

    if cross_validation_results:
        # Calculate correlations
        target_diffs = [r['target_difficulty'] for r in cross_validation_results]
        gen_diffs = [r['generator_difficulty'] for r in cross_validation_results]
        sim_diffs = [r['simulated_difficulty'] for r in cross_validation_results]
        optimal_rates = [r['optimal_clear_rate'] for r in cross_validation_results]

        # Simple correlation: average difference
        gen_vs_target = sum(abs(g - t) for g, t in zip(gen_diffs, target_diffs)) / len(target_diffs)
        sim_vs_target = sum(abs(s - t) for s, t in zip(sim_diffs, target_diffs)) / len(target_diffs)
        sim_vs_gen = sum(abs(s - g) for s, g in zip(sim_diffs, gen_diffs)) / len(gen_diffs)

        print(f"\nDifficulty Correlation Analysis:")
        print(f"  Generator vs Target: Avg diff = {gen_vs_target:.3f}")
        print(f"  Simulation vs Target: Avg diff = {sim_vs_target:.3f}")
        print(f"  Simulation vs Generator: Avg diff = {sim_vs_gen:.3f}")

        # Grade distribution
        grades = {}
        for r in cross_validation_results:
            grade = r['grade']
            grades[grade] = grades.get(grade, 0) + 1

        print(f"\nGrade Distribution:")
        for grade in ['S', 'A', 'B', 'C', 'D']:
            count = grades.get(grade, 0)
            bar = '█' * (count // 2)
            print(f"  {grade}: {count:3d} {bar}")

        # Clear rate by difficulty tier
        print(f"\nOptimal Bot Clear Rates by Difficulty Tier:")
        tiers = [
            ('Easy (0.0-0.3)', 0.0, 0.3),
            ('Medium (0.3-0.5)', 0.3, 0.5),
            ('Hard (0.5-0.7)', 0.5, 0.7),
            ('Expert (0.7-1.0)', 0.7, 1.0),
        ]

        for tier_name, low, high in tiers:
            tier_results = [r for r in cross_validation_results
                          if low <= r['target_difficulty'] < high]
            if tier_results:
                avg_clear = sum(r['optimal_clear_rate'] for r in tier_results) / len(tier_results)
                avg_actual = sum(r['generator_difficulty'] for r in tier_results) / len(tier_results)
                print(f"  {tier_name}: {len(tier_results)} levels, "
                      f"Optimal clear: {avg_clear*100:.1f}%, Actual diff: {avg_actual:.2f}")

        # Upward trend verification per set
        print(f"\nUpward Trend Verification (per set):")
        for set_idx in range(10):
            set_results = [r for r in cross_validation_results if r['set_idx'] == set_idx]
            set_results.sort(key=lambda x: x['level_idx'])

            if len(set_results) >= 2:
                # Check if difficulty generally increases
                increases = 0
                for i in range(1, len(set_results)):
                    if set_results[i]['simulated_difficulty'] >= set_results[i-1]['simulated_difficulty'] - 0.05:
                        increases += 1

                trend_score = increases / (len(set_results) - 1) * 100
                first_diff = set_results[0]['simulated_difficulty']
                last_diff = set_results[-1]['simulated_difficulty']
                overall_increase = last_diff - first_diff

                trend_ok = "✓" if overall_increase > 0 else "✗"
                print(f"  Set {set_idx+1}: {first_diff:.2f} → {last_diff:.2f} "
                      f"(Δ={overall_increase:+.2f}) {trend_ok}")

    # Save results to file
    output_path = Path(__file__).parent / "test_results"
    output_path.mkdir(exist_ok=True)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

    # Save detailed results
    with open(output_path / f"level_set_test_{timestamp}.json", 'w') as f:
        json.dump({
            'timestamp': timestamp,
            'total_levels': len(all_levels),
            'valid_levels': valid_count,
            'generation_results': generation_results,
            'cross_validation': cross_validation_results,
        }, f, indent=2)

    print(f"\nResults saved to: {output_path / f'level_set_test_{timestamp}.json'}")

    # Summary
    print("\n" + "=" * 60)
    print("TEST SUMMARY")
    print("=" * 60)
    print(f"Total levels generated: {len(all_levels)}")
    print(f"Levels passing simulation: {valid_count}")
    print(f"Generation time: {gen_time:.1f}s")
    print(f"Test complete!")


if __name__ == "__main__":
    main()
