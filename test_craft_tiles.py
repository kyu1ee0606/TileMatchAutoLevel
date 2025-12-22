#!/usr/bin/env python3
"""Test craft tile emission logic with optimal bot."""

import sys
sys.path.insert(0, '/Users/casualdev/TileMatchAutoLevel/backend')

from app.core.bot_simulator import BotSimulator, BotProfile


def test_craft_tiles():
    """Test level with craft tiles to verify emission logic."""

    simulator = BotSimulator()

    # Create a test level with craft tiles
    # Layer 0: craft box with direction 'e' (emit to the right)
    # The craft box spawns tiles to the right position
    level_data = {
        "tiles": [
            # Layer 0: craft box at position (3, 3) with direction 'e'
            {"layerIdx": 0, "pos": "3_3", "tileType": "craft_s", "craft": "e", "stackCount": 3},
            # Some regular tiles
            {"layerIdx": 0, "pos": "1_1", "tileType": "t1", "craft": "", "stackCount": 1},
            {"layerIdx": 0, "pos": "1_2", "tileType": "t1", "craft": "", "stackCount": 1},
            {"layerIdx": 0, "pos": "1_3", "tileType": "t1", "craft": "", "stackCount": 1},
            {"layerIdx": 0, "pos": "2_1", "tileType": "t2", "craft": "", "stackCount": 1},
            {"layerIdx": 0, "pos": "2_2", "tileType": "t2", "craft": "", "stackCount": 1},
            {"layerIdx": 0, "pos": "2_3", "tileType": "t2", "craft": "", "stackCount": 1},
        ],
        "layer_cols": {0: 7},
        "goals": {"craft_s": 3},
        "max_moves": 100,
    }

    # Create bot profile
    optimal = BotProfile(
        name="Optimal",
        skill=1.0,
        pattern_recognition=1.0,
        planning=1.0,
        risk_tolerance=0.1,
        speed=1.0
    )

    print("=" * 70)
    print("Testing Craft Tile Emission Logic")
    print("=" * 70)
    print(f"Level: {len(level_data['tiles'])} tiles, goals: {level_data['goals']}")
    print()

    # Run simulation
    result = simulator.simulate_level(level_data, optimal)

    print(f"Result: {'CLEARED' if result.cleared else 'FAILED'}")
    print(f"Tiles picked: {result.tiles_picked}/{result.total_tiles}")
    print(f"Moves used: {result.moves_used}")
    print(f"Goals remaining: {result.goals_remaining}")
    print()

    if not result.cleared:
        print("⚠️  Optimal bot failed to clear the level!")
        print("This suggests craft tile emission logic may still have issues.")
    else:
        print("✅ Optimal bot successfully cleared the level!")
        print("Craft tile emission logic is working correctly.")

    print()


def test_craft_with_blocking():
    """Test craft tiles with spawn position initially blocked."""

    simulator = BotSimulator()

    # Create a test level where craft spawn position is initially blocked
    level_data = {
        "tiles": [
            # Layer 0: craft box at (3, 3) with direction 'e' (emits to 4, 3)
            {"layerIdx": 0, "pos": "3_3", "tileType": "craft_s", "craft": "e", "stackCount": 3},
            # Blocking tile at spawn position (4, 3)
            {"layerIdx": 0, "pos": "4_3", "tileType": "t1", "craft": "", "stackCount": 1},
            # Matching tiles for t1 to clear the blocking tile
            {"layerIdx": 0, "pos": "1_1", "tileType": "t1", "craft": "", "stackCount": 1},
            {"layerIdx": 0, "pos": "1_2", "tileType": "t1", "craft": "", "stackCount": 1},
            # Other tiles
            {"layerIdx": 0, "pos": "2_1", "tileType": "t2", "craft": "", "stackCount": 1},
            {"layerIdx": 0, "pos": "2_2", "tileType": "t2", "craft": "", "stackCount": 1},
            {"layerIdx": 0, "pos": "2_3", "tileType": "t2", "craft": "", "stackCount": 1},
        ],
        "layer_cols": {0: 7},
        "goals": {"craft_s": 3},
        "max_moves": 100,
    }

    optimal = BotProfile(
        name="Optimal",
        skill=1.0,
        pattern_recognition=1.0,
        planning=1.0,
        risk_tolerance=0.1,
        speed=1.0
    )

    print("=" * 70)
    print("Testing Craft Tiles with Initially Blocked Spawn Position")
    print("=" * 70)
    print(f"Level: {len(level_data['tiles'])} tiles")
    print("Craft spawn position (4,3) is initially blocked by t1 tile")
    print()

    result = simulator.simulate_level(level_data, optimal)

    print(f"Result: {'CLEARED' if result.cleared else 'FAILED'}")
    print(f"Tiles picked: {result.tiles_picked}/{result.total_tiles}")
    print(f"Moves used: {result.moves_used}")
    print(f"Goals remaining: {result.goals_remaining}")
    print()

    if not result.cleared:
        print("⚠️  Optimal bot failed to clear the level!")
        print("Issue: Bot may not be recognizing craft tiles after spawn unblocking.")
    else:
        print("✅ Optimal bot successfully cleared the level!")
        print("Craft tiles were properly emitted after spawn position was cleared.")

    print()


if __name__ == "__main__":
    test_craft_tiles()
    test_craft_with_blocking()
