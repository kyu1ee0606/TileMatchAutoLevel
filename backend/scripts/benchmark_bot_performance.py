#!/usr/bin/env python3
"""Bot Simulation Performance Benchmark Script.

This script measures bot simulation performance before and after optimizations.
It uses benchmark levels from different tiers to test various complexity scenarios.

Usage:
    python benchmark_bot_performance.py [--iterations N] [--output FILE]
"""

import argparse
import json
import sys
import time
from dataclasses import dataclass, asdict
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Any, Optional

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from app.core.bot_simulator import BotSimulator, get_bot_simulator
from app.models.bot_profile import BotType, BotTeam, get_profile
from app.models.benchmark_level import (
    EASY_LEVELS, MEDIUM_LEVELS, BenchmarkLevel, DifficultyTier
)


@dataclass
class BenchmarkResult:
    """Result of a single benchmark run."""
    level_id: str
    level_name: str
    tier: str
    tile_count: int
    layer_count: int

    # Performance metrics
    total_time_ms: float
    avg_time_per_iteration_ms: float
    iterations: int

    # Per-bot metrics
    bot_times_ms: Dict[str, float]
    bot_clear_rates: Dict[str, float]

    # Memory (if available)
    memory_mb: Optional[float] = None


@dataclass
class BenchmarkSuite:
    """Complete benchmark suite results."""
    timestamp: str
    version: str
    iterations_per_bot: int
    total_time_seconds: float

    # Summary metrics
    avg_time_per_level_ms: float
    avg_time_per_simulation_ms: float
    slowest_level: str
    fastest_level: str

    # Detailed results
    results: List[Dict[str, Any]]

    def to_json(self) -> str:
        return json.dumps(asdict(self), indent=2, ensure_ascii=False)


def count_tiles(level_json: Dict) -> int:
    """Count total tiles in a level."""
    count = 0
    for key, value in level_json.items():
        if key.startswith("layer_") and isinstance(value, dict):
            tiles = value.get("tiles", {})
            count += len(tiles)
    return count


def count_layers(level_json: Dict) -> int:
    """Count layers in a level."""
    return sum(1 for key in level_json.keys() if key.startswith("layer_"))


def benchmark_level(
    level: BenchmarkLevel,
    simulator: BotSimulator,
    iterations_per_bot: int,
    bots: List[BotType]
) -> BenchmarkResult:
    """Benchmark a single level."""

    # Convert to simulator format
    level_json = level.to_simulator_format()

    # Get level metadata
    tile_count = count_tiles(level_json)
    layer_count = count_layers(level_json)

    bot_times = {}
    bot_clear_rates = {}
    total_start = time.perf_counter()

    for bot_type in bots:
        profile = get_profile(bot_type)

        bot_start = time.perf_counter()
        result = simulator.simulate_with_profile(
            level_json=level_json,
            profile=profile,
            iterations=iterations_per_bot,
            seed=42  # Fixed seed for reproducibility
        )
        bot_end = time.perf_counter()

        bot_times[bot_type.value] = (bot_end - bot_start) * 1000  # ms
        bot_clear_rates[bot_type.value] = result.clear_rate

    total_end = time.perf_counter()
    total_time_ms = (total_end - total_start) * 1000
    total_iterations = len(bots) * iterations_per_bot

    return BenchmarkResult(
        level_id=level.id,
        level_name=level.name,
        tier=level.difficulty_tier.value,
        tile_count=tile_count,
        layer_count=layer_count,
        total_time_ms=total_time_ms,
        avg_time_per_iteration_ms=total_time_ms / total_iterations,
        iterations=total_iterations,
        bot_times_ms=bot_times,
        bot_clear_rates=bot_clear_rates
    )


def run_benchmark_suite(
    levels: List[BenchmarkLevel],
    iterations_per_bot: int = 50,
    bots: Optional[List[BotType]] = None
) -> BenchmarkSuite:
    """Run complete benchmark suite."""

    if bots is None:
        bots = [BotType.CASUAL, BotType.AVERAGE, BotType.EXPERT, BotType.OPTIMAL]

    simulator = get_bot_simulator()
    results: List[BenchmarkResult] = []

    suite_start = time.perf_counter()

    print(f"\n{'='*60}")
    print(f"Bot Simulation Performance Benchmark")
    print(f"{'='*60}")
    print(f"Levels: {len(levels)}")
    print(f"Bots: {[b.value for b in bots]}")
    print(f"Iterations per bot: {iterations_per_bot}")
    print(f"Total simulations: {len(levels) * len(bots) * iterations_per_bot}")
    print(f"{'='*60}\n")

    for i, level in enumerate(levels):
        print(f"[{i+1}/{len(levels)}] Benchmarking: {level.name} ({level.difficulty_tier.value})...", end=" ", flush=True)

        result = benchmark_level(level, simulator, iterations_per_bot, bots)
        results.append(result)

        print(f"{result.total_time_ms:.1f}ms (avg: {result.avg_time_per_iteration_ms:.2f}ms/iter)")

    suite_end = time.perf_counter()
    total_seconds = suite_end - suite_start

    # Calculate summary metrics
    times = [r.total_time_ms for r in results]
    slowest = max(results, key=lambda r: r.total_time_ms)
    fastest = min(results, key=lambda r: r.total_time_ms)

    total_iterations = sum(r.iterations for r in results)

    suite = BenchmarkSuite(
        timestamp=datetime.now().isoformat(),
        version="1.0.0",  # Will be updated with git hash
        iterations_per_bot=iterations_per_bot,
        total_time_seconds=total_seconds,
        avg_time_per_level_ms=sum(times) / len(times),
        avg_time_per_simulation_ms=sum(times) / total_iterations,
        slowest_level=f"{slowest.level_id} ({slowest.total_time_ms:.1f}ms)",
        fastest_level=f"{fastest.level_id} ({fastest.total_time_ms:.1f}ms)",
        results=[asdict(r) for r in results]
    )

    return suite


def print_summary(suite: BenchmarkSuite):
    """Print benchmark summary."""
    print(f"\n{'='*60}")
    print("BENCHMARK SUMMARY")
    print(f"{'='*60}")
    print(f"Total time: {suite.total_time_seconds:.2f}s")
    print(f"Avg time per level: {suite.avg_time_per_level_ms:.1f}ms")
    print(f"Avg time per simulation: {suite.avg_time_per_simulation_ms:.3f}ms")
    print(f"Slowest level: {suite.slowest_level}")
    print(f"Fastest level: {suite.fastest_level}")
    print(f"{'='*60}")

    # Per-tier breakdown
    tier_results: Dict[str, List[Dict]] = {}
    for r in suite.results:
        tier = r["tier"]
        if tier not in tier_results:
            tier_results[tier] = []
        tier_results[tier].append(r)

    print("\nPer-Tier Performance:")
    for tier, results in tier_results.items():
        avg_time = sum(r["total_time_ms"] for r in results) / len(results)
        avg_tiles = sum(r["tile_count"] for r in results) / len(results)
        print(f"  {tier.upper():12} - Avg: {avg_time:7.1f}ms, Tiles: {avg_tiles:.0f}")

    # Per-bot breakdown
    print("\nPer-Bot Performance:")
    bot_total_times: Dict[str, float] = {}
    for r in suite.results:
        for bot, time_ms in r["bot_times_ms"].items():
            bot_total_times[bot] = bot_total_times.get(bot, 0) + time_ms

    for bot, total_time in sorted(bot_total_times.items()):
        avg_time = total_time / len(suite.results)
        print(f"  {bot:12} - Total: {total_time:7.1f}ms, Avg: {avg_time:.1f}ms/level")


def main():
    parser = argparse.ArgumentParser(description="Benchmark bot simulation performance")
    parser.add_argument("--iterations", "-i", type=int, default=50,
                       help="Iterations per bot (default: 50)")
    parser.add_argument("--output", "-o", type=str, default=None,
                       help="Output file for results (JSON)")
    parser.add_argument("--tier", "-t", type=str, choices=["easy", "medium", "all"],
                       default="all", help="Which tier(s) to benchmark")
    parser.add_argument("--quick", "-q", action="store_true",
                       help="Quick mode: 3 levels per tier, 20 iterations")

    args = parser.parse_args()

    # Select levels
    levels = []
    if args.tier in ["easy", "all"]:
        levels.extend(EASY_LEVELS)
    if args.tier in ["medium", "all"]:
        levels.extend(MEDIUM_LEVELS)

    # Quick mode
    iterations = args.iterations
    if args.quick:
        # Take first, middle, last level from each tier
        easy_sample = [EASY_LEVELS[0], EASY_LEVELS[4], EASY_LEVELS[9]]
        medium_sample = [MEDIUM_LEVELS[0], MEDIUM_LEVELS[4], MEDIUM_LEVELS[9]]
        levels = easy_sample + medium_sample
        iterations = min(20, args.iterations)
        print("Quick mode: Using 6 sample levels with reduced iterations")

    # Run benchmark
    suite = run_benchmark_suite(levels, iterations_per_bot=iterations)

    # Print summary
    print_summary(suite)

    # Save results
    if args.output:
        output_path = Path(args.output)
        output_path.write_text(suite.to_json(), encoding="utf-8")
        print(f"\nResults saved to: {output_path}")
    else:
        # Default output to claudedocs
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        default_output = Path(__file__).parent.parent.parent / "claudedocs" / f"benchmark_result_{timestamp}.json"
        default_output.parent.mkdir(exist_ok=True)
        default_output.write_text(suite.to_json(), encoding="utf-8")
        print(f"\nResults saved to: {default_output}")


if __name__ == "__main__":
    main()
