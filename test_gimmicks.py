#!/usr/bin/env python3
"""
Gimmick-specific test script.
Tests each gimmick individually to verify correct simulation behavior.
"""

import requests
import json
import sys
from typing import Dict, Any, List

API_BASE = "http://localhost:8000"

# =============================================================================
# Test Level Definitions for Each Gimmick
# =============================================================================

def create_ice_test_level() -> Dict[str, Any]:
    """Ice gimmick test: 3-layer ice that decreases when other tiles are picked."""
    return {
        "layer": 1,
        "randSeed": 0,
        "useTileCount": 3,
        "goals": {"t1": 3, "t2": 3, "t3": 3},
        "max_moves": 20,
        "layer_0": {
            "tiles": {
                # Ice tiles (3 layers) - should need 3 other tile picks to become selectable
                "0_0": ["t1", "ice", {"ice_layer": 3}],
                "1_0": ["t1", "ice", {"ice_layer": 2}],
                "2_0": ["t1", "ice", {"ice_layer": 1}],
                # Normal tiles for matching
                "0_1": ["t2", ""],
                "1_1": ["t2", ""],
                "2_1": ["t2", ""],
                "0_2": ["t3", ""],
                "1_2": ["t3", ""],
                "2_2": ["t3", ""],
            },
            "col": 3
        }
    }

def create_bomb_test_level() -> Dict[str, Any]:
    """Bomb gimmick test: countdown decreases when other tiles are picked, game over at 0."""
    return {
        "layer": 1,
        "randSeed": 0,
        "useTileCount": 3,
        "goals": {"t1": 3, "t2": 3, "t3": 3},
        "max_moves": 20,
        "layer_0": {
            "tiles": {
                # Bomb tile with countdown 5
                "0_0": ["t1", "bomb", {"bomb_count": 5}],
                "1_0": ["t1", ""],
                "2_0": ["t1", ""],
                # Normal tiles
                "0_1": ["t2", ""],
                "1_1": ["t2", ""],
                "2_1": ["t2", ""],
                "0_2": ["t3", ""],
                "1_2": ["t3", ""],
                "2_2": ["t3", ""],
            },
            "col": 3
        }
    }

def create_chain_test_level() -> Dict[str, Any]:
    """Chain gimmick test: unlocked when left/right adjacent tile is cleared."""
    return {
        "layer": 1,
        "randSeed": 0,
        "useTileCount": 3,
        "goals": {"t1": 3, "t2": 3, "t3": 3},
        "max_moves": 20,
        "layer_0": {
            "tiles": {
                # Chain tile in middle - needs left or right neighbor cleared
                "0_0": ["t1", ""],
                "1_0": ["t1", "chain"],  # Chained - needs 0_0 or 2_0 cleared
                "2_0": ["t1", ""],
                # Normal tiles
                "0_1": ["t2", ""],
                "1_1": ["t2", ""],
                "2_1": ["t2", ""],
                "0_2": ["t3", ""],
                "1_2": ["t3", ""],
                "2_2": ["t3", ""],
            },
            "col": 3
        }
    }

def create_grass_test_level() -> Dict[str, Any]:
    """Grass gimmick test: needs adjacent tile clears to remove grass layers."""
    return {
        "layer": 1,
        "randSeed": 0,
        "useTileCount": 3,
        "goals": {"t1": 3, "t2": 3, "t3": 3},
        "max_moves": 20,
        "layer_0": {
            "tiles": {
                # Grass tile with 2 layers
                "1_1": ["t1", "grass", {"grass_layer": 2}],
                # Surrounding tiles for clearing
                "0_0": ["t1", ""],
                "1_0": ["t2", ""],
                "2_0": ["t1", ""],
                "0_1": ["t2", ""],
                "2_1": ["t2", ""],
                "0_2": ["t3", ""],
                "1_2": ["t3", ""],
                "2_2": ["t3", ""],
            },
            "col": 3
        }
    }

def create_link_test_level() -> Dict[str, Any]:
    """Link gimmick test: linked tiles are picked together (occupy 2 dock slots)."""
    return {
        "layer": 1,
        "randSeed": 0,
        "useTileCount": 3,
        "goals": {"t1": 6, "t2": 3, "t3": 3},  # 6 t1 (2 linked + 4 normal), 3 t2, 3 t3 = 12 tiles
        "max_moves": 20,
        "layer_0": {
            "tiles": {
                # Link pair (t1 linked east-west) - picked together, uses 2 dock slots
                "0_0": ["t1", "link_e"],  # Links to 1_0
                "1_0": ["t1", "link_w"],  # Links to 0_0
                # More t1 tiles to complete 6 total
                "2_0": ["t1", ""],
                "0_1": ["t1", ""],
                "1_1": ["t1", ""],
                "2_1": ["t1", ""],
                # t2 tiles (3)
                "0_2": ["t2", ""],
                "1_2": ["t2", ""],
                "2_2": ["t2", ""],
                # t3 tiles (3)
                "0_3": ["t3", ""],
                "1_3": ["t3", ""],
                "2_3": ["t3", ""],
            },
            "col": 3
        }
    }

def create_frog_test_level() -> Dict[str, Any]:
    """Frog gimmick test: frog jumps randomly to block other tiles."""
    return {
        "layer": 1,
        "randSeed": 42,
        "useTileCount": 3,
        "goals": {"t1": 3, "t2": 3, "t3": 3},
        "max_moves": 30,
        "layer_0": {
            "tiles": {
                # Frog tile
                "0_0": ["t1", "frog"],
                "1_0": ["t1", ""],
                "2_0": ["t1", ""],
                # Normal tiles
                "0_1": ["t2", ""],
                "1_1": ["t2", ""],
                "2_1": ["t2", ""],
                "0_2": ["t3", ""],
                "1_2": ["t3", ""],
                "2_2": ["t3", ""],
            },
            "col": 3
        }
    }

def create_stack_test_level() -> Dict[str, Any]:
    """Stack gimmick test: tiles push in specified direction when picked."""
    return {
        "layer": 1,
        "randSeed": 0,
        "useTileCount": 3,
        "goals": {"t1": 3, "t2": 3, "t3": 3},
        "max_moves": 20,
        "layer_0": {
            "tiles": {
                # Stack south - tiles push south when picked
                "1_0": ["t1", "stack_s", {"stack_tiles": ["t1", "t1"]}],
                # Normal tiles
                "0_0": ["t2", ""],
                "2_0": ["t2", ""],
                "0_1": ["t2", ""],
                "1_1": ["t3", ""],
                "2_1": ["t3", ""],
                "0_2": ["t3", ""],
                "1_2": ["t1", ""],
                "2_2": ["t1", ""],
            },
            "col": 3
        }
    }

def create_curtain_test_level() -> Dict[str, Any]:
    """Curtain gimmick test: tiles toggle between open/closed state."""
    return {
        "layer": 1,
        "randSeed": 0,
        "useTileCount": 3,
        "goals": {"t1": 3, "t2": 3, "t3": 3},
        "max_moves": 20,
        "layer_0": {
            "tiles": {
                # Curtain tile (closed initially)
                "0_0": ["t1", "curtain", {"is_open": False}],
                "1_0": ["t1", ""],
                "2_0": ["t1", ""],
                # Normal tiles
                "0_1": ["t2", ""],
                "1_1": ["t2", ""],
                "2_1": ["t2", ""],
                "0_2": ["t3", ""],
                "1_2": ["t3", ""],
                "2_2": ["t3", ""],
            },
            "col": 3
        }
    }

def create_teleport_test_level() -> Dict[str, Any]:
    """Teleport gimmick test: teleport tiles swap positions every 3 clicks."""
    return {
        "layer": 1,
        "randSeed": 0,
        "useTileCount": 4,
        "goals": {"t1": 3, "t2": 3, "t3": 3, "t4": 3},
        "max_moves": 30,
        "layer_0": {
            "tiles": {
                # Teleport tiles
                "0_0": ["t1", "teleport"],
                "2_0": ["t2", "teleport"],
                # Normal tiles
                "1_0": ["t1", ""],
                "0_1": ["t1", ""],
                "1_1": ["t2", ""],
                "2_1": ["t2", ""],
                "0_2": ["t3", ""],
                "1_2": ["t3", ""],
                "2_2": ["t3", ""],
                "0_3": ["t4", ""],
                "1_3": ["t4", ""],
                "2_3": ["t4", ""],
            },
            "col": 3
        }
    }

def create_craft_test_level() -> Dict[str, Any]:
    """Craft gimmick test: craft box produces tiles."""
    return {
        "layer": 1,
        "randSeed": 0,
        "useTileCount": 3,
        "goals": {"t1": 6, "t2": 3, "t3": 3},
        "max_moves": 30,
        "layer_0": {
            "tiles": {
                # Craft box that produces t1 tiles
                "1_0": ["craft_s", "", [3]],  # Produces 3 t1 tiles
                # Normal tiles
                "0_0": ["t1", ""],
                "2_0": ["t1", ""],
                "0_1": ["t1", ""],
                "1_1": ["t2", ""],
                "2_1": ["t2", ""],
                "0_2": ["t2", ""],
                "1_2": ["t3", ""],
                "2_2": ["t3", ""],
                "0_3": ["t3", ""],
            },
            "col": 3
        }
    }

# =============================================================================
# Test Runner
# =============================================================================

def run_simulation(level_json: Dict[str, Any], bot_type: str = "optimal", iterations: int = 10) -> Dict[str, Any]:
    """Run simulation via API."""
    response = requests.post(
        f"{API_BASE}/api/assess/multibot",
        json={
            "level_json": level_json,
            "bot_types": [bot_type],
            "iterations": iterations,
            "max_moves": level_json.get("max_moves", 30),
            "seed": level_json.get("randSeed", 42)
        }
    )
    return response.json()

def run_visual_simulation(level_json: Dict[str, Any], bot_type: str = "optimal") -> Dict[str, Any]:
    """Run visual simulation to see step-by-step behavior."""
    response = requests.post(
        f"{API_BASE}/api/simulate/visual",
        json={
            "level_json": level_json,
            "bot_types": [bot_type],
            "max_moves": level_json.get("max_moves", 30),
            "seed": level_json.get("randSeed", 42)
        }
    )
    return response.json()

def test_gimmick(name: str, level_creator, expected_clearable: bool = True):
    """Test a single gimmick."""
    print(f"\n{'='*60}")
    print(f"Testing: {name}")
    print('='*60)

    try:
        level_json = level_creator()

        # Run multi-bot simulation
        result = run_simulation(level_json, "optimal", 10)

        if "error" in result or "detail" in result:
            print(f"  ERROR: {result.get('error') or result.get('detail')}")
            return False

        # Check results - note: API uses "bot_results" not "results"
        bot_results = result.get("bot_results", [])
        if not bot_results:
            print(f"  ERROR: No bot results returned")
            print(f"  Response: {result}")
            return False

        optimal_result = bot_results[0]
        clear_rate = optimal_result.get("clear_rate", 0)
        avg_moves = optimal_result.get("avg_moves", 0)

        print(f"  Clear Rate: {clear_rate*100:.1f}%")
        print(f"  Avg Moves: {avg_moves:.1f}")

        # Visual simulation for detailed check
        visual_result = run_visual_simulation(level_json, "optimal")
        if "error" not in visual_result and "detail" not in visual_result:
            # Visual API returns bot_results array
            visual_bot_results = visual_result.get("bot_results", [])
            if visual_bot_results:
                bot_result = visual_bot_results[0]
                cleared = bot_result.get("cleared", False)
                total_moves = bot_result.get("total_moves", 0)
                print(f"  Visual Sim: {'CLEARED' if cleared else 'FAILED'} in {total_moves} moves")

                # Show gimmick state progression if available
                moves = bot_result.get("moves", [])
                if moves and not cleared:
                    last_move = moves[-1] if moves else {}
                    print(f"  Last Move: dock_after={last_move.get('dock_after', [])}")
            else:
                print(f"  Visual Sim: No bot results in response")

        # Determine pass/fail
        if expected_clearable:
            passed = clear_rate > 0.5
        else:
            passed = clear_rate < 0.5

        status = "PASS" if passed else "FAIL"
        print(f"\n  Result: {status}")
        return passed

    except Exception as e:
        print(f"  EXCEPTION: {str(e)}")
        import traceback
        traceback.print_exc()
        return False

def main():
    """Run all gimmick tests."""
    print("="*60)
    print("GIMMICK SIMULATION TESTS")
    print("="*60)

    # Check server
    try:
        response = requests.get(f"{API_BASE}/api/simulate/benchmark/list", timeout=5)
        print(f"Server Status: OK")
    except:
        print("ERROR: Server not running. Start with: cd backend && uvicorn main:app --reload")
        sys.exit(1)

    tests = [
        ("ICE (countdown on exposure)", create_ice_test_level, True),
        ("BOMB (countdown, game over at 0)", create_bomb_test_level, True),
        ("CHAIN (left/right unlock)", create_chain_test_level, True),
        ("GRASS (adjacent clear)", create_grass_test_level, True),
        ("LINK (paired selection)", create_link_test_level, True),
        ("FROG (random jump)", create_frog_test_level, True),
        ("STACK (directional push)", create_stack_test_level, True),
        ("CURTAIN (open/close toggle)", create_curtain_test_level, True),
        ("TELEPORT (swap every 3 clicks)", create_teleport_test_level, True),
        ("CRAFT (tile production)", create_craft_test_level, True),
    ]

    results = []
    for name, creator, expected in tests:
        passed = test_gimmick(name, creator, expected)
        results.append((name, passed))

    # Summary
    print("\n" + "="*60)
    print("SUMMARY")
    print("="*60)

    passed_count = sum(1 for _, p in results if p)
    total_count = len(results)

    for name, passed in results:
        status = "PASS" if passed else "FAIL"
        print(f"  [{status}] {name}")

    print(f"\nTotal: {passed_count}/{total_count} passed")

    return 0 if passed_count == total_count else 1

if __name__ == "__main__":
    sys.exit(main())
