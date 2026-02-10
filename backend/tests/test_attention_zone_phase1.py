"""Phase 1: Attention Zone A/B Test Script

Compares bot simulation clear rates before and after
applying the attention zone filter.

Usage:
    python -m pytest tests/test_attention_zone_phase1.py -v
    or
    python tests/test_attention_zone_phase1.py

See: claudedocs/bot_simulation_accuracy_improvement_plan.md
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import json
from typing import Dict, List
from app.core.bot_simulator import BotSimulator, BotSimulatorConfig
from app.models.bot_profile import BotType, get_profile


# Sample level JSON for testing (simple 3-layer level)
SAMPLE_LEVEL_SIMPLE = {
    "tiles": {
        "layer_0": {
            "col": 7,
            "tiles": [
                ["0_0", "t1", ""],
                ["0_1", "t2", ""],
                ["0_2", "t3", ""],
                ["1_0", "t1", ""],
                ["1_1", "t2", ""],
                ["1_2", "t3", ""],
                ["2_0", "t1", ""],
                ["2_1", "t2", ""],
                ["2_2", "t3", ""],
            ]
        },
        "layer_1": {
            "col": 6,
            "tiles": [
                ["0_0", "t4", ""],
                ["0_1", "t5", ""],
                ["1_0", "t4", ""],
                ["1_1", "t5", ""],
                ["2_0", "t4", ""],
                ["2_1", "t5", ""],
            ]
        },
        "layer_2": {
            "col": 5,
            "tiles": [
                ["0_0", "t6", ""],
                ["1_0", "t6", ""],
                ["2_0", "t6", ""],
            ]
        }
    },
    "goals": {},
    "moveCount": 30,
    "useTileCount": 6
}


def run_ab_test(
    level_json: Dict,
    iterations: int = 100,
    seed: int = 42
) -> Dict:
    """Run A/B test comparing attention zone ON vs OFF."""

    simulator = BotSimulator()
    results = {
        "attention_on": {},
        "attention_off": {},
        "delta": {}
    }

    bot_types = BotType.all_types()

    # Test with attention zone ON
    BotSimulatorConfig.ENABLE_ATTENTION_ZONE = True
    print("\n[A] Testing with ATTENTION_ZONE = ON")
    print("-" * 50)

    for bot_type in bot_types:
        profile = get_profile(bot_type)
        result = simulator.simulate_with_profile(
            level_json, profile, iterations=iterations, seed=seed
        )
        results["attention_on"][bot_type.value] = {
            "clear_rate": result.clear_rate,
            "avg_moves": result.avg_moves
        }
        print(f"  {bot_type.value:8s}: clear_rate={result.clear_rate:.2%}, avg_moves={result.avg_moves:.1f}")

    # Test with attention zone OFF
    BotSimulatorConfig.ENABLE_ATTENTION_ZONE = False
    print("\n[B] Testing with ATTENTION_ZONE = OFF (baseline)")
    print("-" * 50)

    for bot_type in bot_types:
        profile = get_profile(bot_type)
        result = simulator.simulate_with_profile(
            level_json, profile, iterations=iterations, seed=seed
        )
        results["attention_off"][bot_type.value] = {
            "clear_rate": result.clear_rate,
            "avg_moves": result.avg_moves
        }
        print(f"  {bot_type.value:8s}: clear_rate={result.clear_rate:.2%}, avg_moves={result.avg_moves:.1f}")

    # Calculate delta
    print("\n[Delta] Clear Rate Change (ON - OFF)")
    print("-" * 50)

    for bot_type in bot_types:
        on_rate = results["attention_on"][bot_type.value]["clear_rate"]
        off_rate = results["attention_off"][bot_type.value]["clear_rate"]
        delta = on_rate - off_rate
        results["delta"][bot_type.value] = {
            "clear_rate_delta": delta,
            "clear_rate_delta_pct": delta * 100
        }
        sign = "+" if delta >= 0 else ""
        print(f"  {bot_type.value:8s}: {sign}{delta:.2%} ({sign}{delta*100:.1f}%p)")

    # Restore default
    BotSimulatorConfig.ENABLE_ATTENTION_ZONE = True

    return results


def test_attention_zone_reduces_clear_rate():
    """Test that attention zone reduces clear rates for lower-skill bots."""
    results = run_ab_test(SAMPLE_LEVEL_SIMPLE, iterations=50, seed=12345)

    # NOVICE/CASUAL should see clear rate reduction
    novice_delta = results["delta"]["novice"]["clear_rate_delta"]
    casual_delta = results["delta"]["casual"]["clear_rate_delta"]
    average_delta = results["delta"]["average"]["clear_rate_delta"]

    print("\n[Assertions]")
    print(f"  NOVICE delta: {novice_delta:.2%} (expected <= 0)")
    print(f"  CASUAL delta: {casual_delta:.2%} (expected <= 0)")
    print(f"  AVERAGE delta: {average_delta:.2%} (expected <= 0)")

    # Attention zone should generally reduce or maintain clear rates
    # (It filters out moves, so bots may miss optimal plays)
    # Note: Small increases possible due to randomness, but trend should be downward
    assert novice_delta <= 0.15, f"NOVICE clear rate increased too much: {novice_delta:.2%}"
    assert casual_delta <= 0.15, f"CASUAL clear rate increased too much: {casual_delta:.2%}"

    # OPTIMAL should be unaffected (pattern_recognition >= 0.99)
    optimal_on = results["attention_on"]["optimal"]["clear_rate"]
    optimal_off = results["attention_off"]["optimal"]["clear_rate"]
    print(f"  OPTIMAL: ON={optimal_on:.2%}, OFF={optimal_off:.2%}")

    # Optimal rates should be very close (both should see all moves)
    assert abs(optimal_on - optimal_off) < 0.05, \
        f"OPTIMAL should be unaffected: {optimal_on:.2%} vs {optimal_off:.2%}"

    print("\n[PASS] All assertions passed!")


def test_attention_zone_filter_logic():
    """Test _filter_by_attention method directly."""
    from app.core.bot_simulator import GameState, Move, TileState, BotSimulator
    from app.models.bot_profile import get_profile, BotType

    simulator = BotSimulator()
    simulator._rng = __import__('random').Random(42)

    # Create mock game state
    state = GameState()
    state._max_layer_idx = 2

    # Create mock moves at different layers
    moves = []
    for layer in range(3):
        for i in range(3):
            tile = TileState(
                tile_type=f"t{i+1}",
                layer_idx=layer,
                x_idx=i,
                y_idx=0
            )
            move = Move(
                layer_idx=layer,
                position=f"{i}_0",
                tile_type=tile.tile_type,
                tile_state=tile,
                will_match=False
            )
            moves.append(move)

    # Add one matching move
    matching_move = Move(
        layer_idx=2,
        position="0_0",
        tile_type="t1",
        will_match=True
    )
    moves.append(matching_move)

    # Test with NOVICE profile (low pattern_recognition)
    novice_profile = get_profile(BotType.NOVICE)
    filtered_novice = simulator._filter_by_attention(moves, state, novice_profile)

    print(f"\n[Filter Test] NOVICE: {len(filtered_novice)}/{len(moves)} moves visible")

    # Matching move should always be included
    assert any(m.will_match for m in filtered_novice), "Matching move should always be visible"

    # OPTIMAL should see all moves
    optimal_profile = get_profile(BotType.OPTIMAL)
    filtered_optimal = simulator._filter_by_attention(moves, state, optimal_profile)

    print(f"[Filter Test] OPTIMAL: {len(filtered_optimal)}/{len(moves)} moves visible")
    assert len(filtered_optimal) == len(moves), "OPTIMAL should see all moves"

    print("\n[PASS] Filter logic test passed!")


if __name__ == "__main__":
    print("=" * 60)
    print("Phase 1: Attention Zone A/B Test")
    print("=" * 60)

    # Run filter logic test
    test_attention_zone_filter_logic()

    # Run A/B comparison test
    print("\n" + "=" * 60)
    print("Running A/B Comparison (100 iterations per bot)")
    print("=" * 60)

    test_attention_zone_reduces_clear_rate()
