#!/usr/bin/env python3
"""Profile bot simulation to identify bottlenecks."""

import cProfile
import pstats
import sys
from io import StringIO
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from app.core.bot_simulator import get_bot_simulator
from app.models.bot_profile import BotType, get_profile
from app.models.benchmark_level import MEDIUM_LEVELS


def run_simulation():
    """Run simulation for profiling."""
    simulator = get_bot_simulator()
    level = MEDIUM_LEVELS[4]  # medium_05 - slowest level
    level_json = level.to_simulator_format()

    # Run only OPTIMAL bot with 10 iterations
    profile = get_profile(BotType.OPTIMAL)
    result = simulator.simulate_with_profile(
        level_json=level_json,
        profile=profile,
        iterations=10,
        seed=42
    )
    print(f"Clear rate: {result.clear_rate}")
    return result


if __name__ == "__main__":
    profiler = cProfile.Profile()
    profiler.enable()

    run_simulation()

    profiler.disable()

    # Print top 30 functions by cumulative time
    s = StringIO()
    ps = pstats.Stats(profiler, stream=s).sort_stats('cumulative')
    ps.print_stats(30)
    print(s.getvalue())
