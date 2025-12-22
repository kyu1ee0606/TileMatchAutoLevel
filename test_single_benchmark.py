#!/usr/bin/env python3
"""Test a single benchmark level for debugging."""

import sys
sys.path.insert(0, '/Users/casualdev/TileMatchAutoLevel/backend')

from app.core.bot_simulator import BotSimulator
from app.models.bot_profile import BotType, get_profile
from app.models.benchmark_level import get_benchmark_level_by_id
import json


def test_level(level_id: str, bot_type: BotType = BotType.OPTIMAL):
    """Test a single level with detailed output."""
    level = get_benchmark_level_by_id(level_id)

    print(f"Testing Level: {level.name} ({level.id})")
    print(f"Description: {level.description}")
    print(f"Tags: {', '.join(level.tags)}")
    print()

    # Convert to simulator format
    level_data = level.to_simulator_format()

    print("Converted Level Data:")
    print(json.dumps(level_data, indent=2))
    print()

    # Run simulation
    simulator = BotSimulator()
    profile = get_profile(bot_type)
    max_moves = level.level_json.get("max_moves", 50)

    result = simulator.simulate_with_profile(
        level_data,
        profile,
        iterations=1,
        max_moves=max_moves,
        seed=42,
    )

    print(f"\n{bot_type.value} Bot Result:")
    print(f"  Clear Rate: {result.clear_rate * 100:.0f}%")
    print(f"  Moves Used: {result.avg_moves:.1f}")
    print(f"  Min Moves: {result.min_moves}")
    print(f"  Max Moves: {result.max_moves}")


if __name__ == "__main__":
    # Test CHAIN level (failing)
    print("=" * 80)
    test_level("easy_04")
    print("\n" + "=" * 80 + "\n")

    # Test basic level (working)
    test_level("easy_01")
