#!/usr/bin/env python3
"""
Automatic Level Difficulty Validation Tool

Validates benchmark levels by running 100 iterations and comparing
actual clear rates with expected clear rates.

Usage:
    python3 validate_level_difficulty.py [level_id] [--iterations N] [--tolerance PERCENT]

    level_id: Optional specific level to test (e.g., easy_01, medium_05)
              If not provided, tests all levels in a tier
    --iterations: Number of test iterations (default: 100)
    --tolerance: Acceptable deviation percentage (default: 15)

Examples:
    python3 validate_level_difficulty.py easy_01
    python3 validate_level_difficulty.py --iterations 200 --tolerance 10
    python3 validate_level_difficulty.py medium  # Test all MEDIUM tier
"""

import sys
import argparse
from typing import Dict, List, Optional
from dataclasses import dataclass

sys.path.insert(0, '/Users/casualdev/TileMatchAutoLevel/backend')

from app.core.bot_simulator import BotSimulator
from app.models.bot_profile import BotType, get_profile
from app.models.benchmark_level import (
    DifficultyTier,
    get_benchmark_level_by_id,
    get_benchmark_set,
    BenchmarkLevel,
)


@dataclass
class ValidationResult:
    """Result of validating a single level."""
    level_id: str
    level_name: str
    bot_type: BotType
    expected_rate: float
    actual_rate: float
    deviation: float  # Percentage points difference
    within_tolerance: bool
    status: str  # "PASS", "WARN", "FAIL"


@dataclass
class LevelValidationSummary:
    """Summary of all validation results for a level."""
    level_id: str
    level_name: str
    results: List[ValidationResult]
    overall_pass: bool
    warnings: int
    failures: int


def validate_level(
    level: BenchmarkLevel,
    iterations: int = 100,
    tolerance: float = 15.0,
    seed: int = 42,
) -> LevelValidationSummary:
    """
    Validate a single level by testing all bot types.

    Args:
        level: BenchmarkLevel to test
        iterations: Number of test iterations per bot
        tolerance: Acceptable deviation in percentage points (e.g., 15 = ±15%)
        seed: Random seed for reproducibility

    Returns:
        LevelValidationSummary with validation results
    """
    print(f"\n{'='*80}")
    print(f"Validating: {level.name} ({level.id})")
    print(f"{'='*80}")

    simulator = BotSimulator()
    level_data = level.to_simulator_format()
    max_moves = level.level_json.get("max_moves", 50)

    results: List[ValidationResult] = []
    warnings = 0
    failures = 0

    bot_types = [BotType.NOVICE, BotType.CASUAL, BotType.AVERAGE, BotType.EXPERT, BotType.OPTIMAL]

    for bot_type in bot_types:
        profile = get_profile(bot_type)
        expected_rate = level.expected_clear_rates.get(bot_type.value, 0.0)

        # Run simulation
        result = simulator.simulate_with_profile(
            level_data,
            profile,
            iterations=iterations,
            max_moves=max_moves,
            seed=seed,
        )

        actual_rate = result.clear_rate
        deviation = abs(actual_rate - expected_rate) * 100  # Convert to percentage points

        # Determine status
        if deviation <= tolerance:
            status = "PASS"
            status_icon = "✅"
        elif deviation <= tolerance * 1.5:  # Warning zone (15% -> 22.5%)
            status = "WARN"
            status_icon = "⚠️"
            warnings += 1
        else:
            status = "FAIL"
            status_icon = "❌"
            failures += 1

        within_tolerance = (deviation <= tolerance)

        validation_result = ValidationResult(
            level_id=level.id,
            level_name=level.name,
            bot_type=bot_type,
            expected_rate=expected_rate,
            actual_rate=actual_rate,
            deviation=deviation,
            within_tolerance=within_tolerance,
            status=status,
        )
        results.append(validation_result)

        # Print result
        print(f"{status_icon} {bot_type.value:8s}: "
              f"Expected {expected_rate:5.1%}, "
              f"Actual {actual_rate:5.1%}, "
              f"Deviation {deviation:4.1f}% - {status}")

    overall_pass = (failures == 0)

    summary = LevelValidationSummary(
        level_id=level.id,
        level_name=level.name,
        results=results,
        overall_pass=overall_pass,
        warnings=warnings,
        failures=failures,
    )

    # Print summary
    print(f"\n{'─'*80}")
    if overall_pass and warnings == 0:
        print(f"✅ Level {level.id}: ALL PASS")
    elif overall_pass:
        print(f"⚠️  Level {level.id}: PASS with {warnings} warnings")
    else:
        print(f"❌ Level {level.id}: FAIL ({failures} failures, {warnings} warnings)")

    return summary


def validate_tier(
    tier: DifficultyTier,
    iterations: int = 100,
    tolerance: float = 15.0,
    seed: int = 42,
) -> List[LevelValidationSummary]:
    """
    Validate all levels in a difficulty tier.

    Returns:
        List of LevelValidationSummary for each level in the tier
    """
    print(f"\n{'='*80}")
    print(f"VALIDATING TIER: {tier.value.upper()}")
    print(f"Iterations: {iterations}, Tolerance: ±{tolerance}%")
    print(f"{'='*80}")

    try:
        benchmark_set = get_benchmark_set(tier)
    except ValueError as e:
        print(f"\n❌ Error: {e}")
        return []

    summaries: List[LevelValidationSummary] = []

    for level in benchmark_set.levels:
        summary = validate_level(level, iterations, tolerance, seed)
        summaries.append(summary)

    # Print overall tier summary
    print(f"\n{'='*80}")
    print(f"TIER SUMMARY: {tier.value.upper()}")
    print(f"{'='*80}")

    total_levels = len(summaries)
    passed_levels = sum(1 for s in summaries if s.overall_pass)
    total_warnings = sum(s.warnings for s in summaries)
    total_failures = sum(s.failures for s in summaries)

    print(f"Levels Tested: {total_levels}")
    print(f"Passed: {passed_levels}/{total_levels}")
    print(f"Total Warnings: {total_warnings}")
    print(f"Total Failures: {total_failures}")

    if passed_levels == total_levels and total_warnings == 0:
        print(f"\n🎉 ALL LEVELS PASSED VALIDATION")
    elif passed_levels == total_levels:
        print(f"\n⚠️  ALL LEVELS PASSED WITH {total_warnings} WARNINGS")
        print(f"   Consider adjusting expected clear rates or level difficulty")
    else:
        print(f"\n❌ {total_levels - passed_levels} LEVELS FAILED VALIDATION")
        print(f"   Failed levels need difficulty adjustment or updated expected rates")

    # List failed levels
    if total_failures > 0:
        print(f"\nFailed Levels:")
        for summary in summaries:
            if not summary.overall_pass:
                print(f"  - {summary.level_id}: {summary.failures} bot(s) out of tolerance")

    # List warning levels
    if total_warnings > 0:
        print(f"\nWarning Levels:")
        for summary in summaries:
            if summary.overall_pass and summary.warnings > 0:
                print(f"  - {summary.level_id}: {summary.warnings} bot(s) near tolerance limit")

    return summaries


def suggest_adjustments(summary: LevelValidationSummary) -> None:
    """
    Suggest difficulty adjustments based on validation results.
    """
    print(f"\n{'='*80}")
    print(f"ADJUSTMENT SUGGESTIONS: {summary.level_id}")
    print(f"{'='*80}")

    # Analyze which bots are off
    too_easy = []
    too_hard = []

    for result in summary.results:
        if result.actual_rate > result.expected_rate + 0.10:  # 10% higher
            too_easy.append((result.bot_type, result.deviation))
        elif result.actual_rate < result.expected_rate - 0.10:  # 10% lower
            too_hard.append((result.bot_type, result.deviation))

    if too_easy:
        print("\n⚠️  Level is TOO EASY for:")
        for bot_type, deviation in too_easy:
            print(f"   - {bot_type.value}: +{deviation:.1f}% above expected")
        print("\n   Suggestions to increase difficulty:")
        print("   1. Increase tile count (add 6-12 tiles)")
        print("   2. Increase tile variety (add 1-2 tile types)")
        print("   3. Reduce max_moves by 20-30%")
        print("   4. Add effect tiles (ICE, GRASS, LINK)")
        print("   5. Add deeper layer blocking")

    if too_hard:
        print("\n⚠️  Level is TOO HARD for:")
        for bot_type, deviation in too_hard:
            print(f"   - {bot_type.value}: -{deviation:.1f}% below expected")
        print("\n   Suggestions to decrease difficulty:")
        print("   1. Reduce tile count (remove 6-12 tiles)")
        print("   2. Reduce tile variety (remove 1-2 tile types)")
        print("   3. Increase max_moves by 20-30%")
        print("   4. Remove effect tiles or reduce complexity")
        print("   5. Simplify layer blocking patterns")

    if not too_easy and not too_hard:
        print("\n✅ No major adjustments needed")
        if summary.warnings > 0:
            print("   Minor tweaks may improve accuracy:")
            for result in summary.results:
                if result.status == "WARN":
                    if result.actual_rate > result.expected_rate:
                        print(f"   - {result.bot_type.value}: Slightly too easy (+{result.deviation:.1f}%)")
                    else:
                        print(f"   - {result.bot_type.value}: Slightly too hard (-{result.deviation:.1f}%)")


def main():
    parser = argparse.ArgumentParser(
        description="Validate benchmark level difficulty",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__
    )
    parser.add_argument(
        "target",
        nargs="?",
        help="Level ID (e.g., easy_01) or tier (easy, medium) to validate. If not provided, validates all tiers."
    )
    parser.add_argument(
        "--iterations",
        type=int,
        default=100,
        help="Number of test iterations per bot (default: 100)"
    )
    parser.add_argument(
        "--tolerance",
        type=float,
        default=15.0,
        help="Acceptable deviation percentage points (default: 15)"
    )
    parser.add_argument(
        "--seed",
        type=int,
        default=42,
        help="Random seed for reproducibility (default: 42)"
    )
    parser.add_argument(
        "--suggest",
        action="store_true",
        help="Show adjustment suggestions for failed levels"
    )

    args = parser.parse_args()

    print("\n")
    print("╔" + "=" * 78 + "╗")
    print("║" + " " * 18 + "LEVEL DIFFICULTY VALIDATION" + " " * 33 + "║")
    print("╚" + "=" * 78 + "╝")

    summaries: List[LevelValidationSummary] = []

    if not args.target:
        # Validate all tiers
        for tier in [DifficultyTier.EASY, DifficultyTier.MEDIUM]:
            tier_summaries = validate_tier(tier, args.iterations, args.tolerance, args.seed)
            summaries.extend(tier_summaries)

    elif args.target.lower() in ["easy", "medium", "hard", "expert", "impossible"]:
        # Validate specific tier
        tier = DifficultyTier(args.target.lower())
        summaries = validate_tier(tier, args.iterations, args.tolerance, args.seed)

    else:
        # Validate specific level
        try:
            level = get_benchmark_level_by_id(args.target)
            summary = validate_level(level, args.iterations, args.tolerance, args.seed)
            summaries = [summary]
        except ValueError as e:
            print(f"\n❌ Error: {e}")
            return 1

    # Show suggestions if requested
    if args.suggest and summaries:
        for summary in summaries:
            if not summary.overall_pass or summary.warnings > 0:
                suggest_adjustments(summary)

    # Final summary
    if summaries:
        print(f"\n{'='*80}")
        print("FINAL SUMMARY")
        print(f"{'='*80}")

        total_levels = len(summaries)
        passed_levels = sum(1 for s in summaries if s.overall_pass)
        total_warnings = sum(s.warnings for s in summaries)
        total_failures = sum(s.failures for s in summaries)

        print(f"Total Levels Validated: {total_levels}")
        print(f"Passed: {passed_levels}/{total_levels}")
        print(f"Total Warnings: {total_warnings}")
        print(f"Total Failures: {total_failures}")

        if passed_levels == total_levels and total_warnings == 0:
            print(f"\n🎉 ALL VALIDATION PASSED")
            return 0
        elif passed_levels == total_levels:
            print(f"\n⚠️  VALIDATION PASSED WITH WARNINGS")
            print(f"   Run with --suggest flag for adjustment recommendations")
            return 0
        else:
            print(f"\n❌ VALIDATION FAILED")
            print(f"   Run with --suggest flag for adjustment recommendations")
            return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
