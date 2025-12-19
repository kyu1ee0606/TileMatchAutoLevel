#!/usr/bin/env python3
"""Test script to debug stack tile selection issue."""
import json
import sys
sys.path.insert(0, '/Users/casualdev/TileMatchAutoLevel/backend')

from app.api.routes.simulate import VisualSimulator

# Level 28 with stack tiles
level_json = {
    "layer": 4,
    "randSeed": 12345,
    "useTileCount": 6,
    "goalCount": {"stack_s": 6},
    "layer_0": {
        "col": 7,
        "row": 7,
        "tiles": {}
    },
    "layer_1": {
        "col": 7,
        "row": 7,
        "tiles": {}
    },
    "layer_2": {
        "col": 7,
        "row": 7,
        "tiles": {}
    },
    "layer_3": {
        "col": 7,
        "row": 7,
        "tiles": {
            "3_3": ["stack_e", None, [6]]  # Stack with 6 tiles at position 3_3
        }
    }
}

print("=" * 60)
print("Testing Stack Tile Selection via VisualSimulator")
print("=" * 60)

simulator = VisualSimulator()

# Run simulation for "average" bot
print("\nRunning simulation with average bot...")
result, stack_craft_types = simulator.simulate_bot(
    level_json,
    bot_type="average",
    max_moves=30,
    seed=42,
    initial_state_seed=42,
)

print(f"\nstack_craft_types_map: {stack_craft_types}")
print(f"\nFirst move (if any):")
if result.moves:
    move = result.moves[0]
    print(f"  layer_idx: {move.layer_idx}")
    print(f"  position: {move.position}")
    print(f"  tile_type: {move.tile_type}")
    print(f"\nExpected: tile_type should match the LAST element of stack_craft_types['3_3_3']")
    if '3_3_3' in stack_craft_types:
        types = stack_craft_types['3_3_3']
        print(f"  stack_craft_types['3_3_3'] = {types}")
        print(f"  Expected top tile (types[-1]): {types[-1]}")
        print(f"  Actual move tile_type: {move.tile_type}")
        if move.tile_type == types[-1]:
            print("  ✅ MATCH!")
        else:
            print("  ❌ MISMATCH!")
