#!/usr/bin/env python3
"""
Test script for gimmick unlock system validation.

Generates 55 levels (all gimmicks unlock by level 55 with 5-level intervals)
and validates that each level correctly uses only unlocked gimmicks.
"""
import asyncio
import httpx
import json
from typing import Dict, List, Set

# Gimmick unlock schedule (5-level intervals)
GIMMICK_UNLOCK_LEVELS = {
    "chain": 5,
    "frog": 10,
    "ice": 15,
    "link": 20,
    "grass": 25,
    "bomb": 30,
    "curtain": 35,
    "teleport": 40,
    "crate": 45,
    "craft": 50,
    "stack": 55,
}

ALL_GIMMICKS = list(GIMMICK_UNLOCK_LEVELS.keys())
API_BASE = "http://localhost:8000"


def get_unlocked_gimmicks(level_number: int) -> Set[str]:
    """Get set of gimmicks unlocked at a given level."""
    return {
        gimmick for gimmick, unlock_level in GIMMICK_UNLOCK_LEVELS.items()
        if unlock_level <= level_number
    }


def extract_gimmicks_from_level(level_json: Dict) -> Set[str]:
    """Extract all gimmicks present in a level."""
    gimmicks = set()
    num_layers = level_json.get("layer", 8)

    for i in range(num_layers):
        layer_key = f"layer_{i}"
        layer_data = level_json.get(layer_key, {})
        tiles = layer_data.get("tiles", {})

        for pos, tile_data in tiles.items():
            if not isinstance(tile_data, list) or len(tile_data) < 1:
                continue

            tile_type = tile_data[0]
            attribute = tile_data[1] if len(tile_data) > 1 else None

            # Check tile type for craft/stack
            if isinstance(tile_type, str):
                if tile_type.startswith("craft_"):
                    gimmicks.add("craft")
                elif tile_type.startswith("stack_"):
                    gimmicks.add("stack")

            # Check attribute for other gimmicks
            if attribute:
                if attribute == "chain":
                    gimmicks.add("chain")
                elif attribute == "frog":
                    gimmicks.add("frog")
                elif attribute.startswith("ice"):
                    gimmicks.add("ice")
                elif attribute.startswith("grass"):
                    gimmicks.add("grass")
                elif attribute.startswith("link"):
                    gimmicks.add("link")
                elif attribute == "bomb":
                    gimmicks.add("bomb")
                elif attribute == "crate":
                    gimmicks.add("crate")
                elif attribute.startswith("teleport"):
                    gimmicks.add("teleport")
                elif attribute == "curtain":
                    gimmicks.add("curtain")

    return gimmicks


async def generate_level(client: httpx.AsyncClient, level_number: int, difficulty: float) -> Dict:
    """Generate a single level with gimmick unlock system."""
    unlocked = list(get_unlocked_gimmicks(level_number))

    # Use empty list (not None) to explicitly request no gimmicks when none are unlocked
    # None would allow the generator to use defaults
    request = {
        "target_difficulty": difficulty,
        "grid_size": [7, 7],
        "max_layers": 5,
        "obstacle_types": unlocked,  # Empty list = no obstacles
        "auto_select_gimmicks": True,
        "available_gimmicks": unlocked,  # Empty list = no gimmicks available
        "gimmick_unlock_levels": GIMMICK_UNLOCK_LEVELS,
        "level_number": level_number,
        "gimmick_intensity": 1.0,
    }

    response = await client.post(
        f"{API_BASE}/api/generate/validated",
        json=request,
        timeout=60.0
    )

    if response.status_code != 200:
        raise Exception(f"Level {level_number} generation failed: {response.text}")

    return response.json()


async def run_test():
    """Run the full test suite."""
    print("=" * 60)
    print("Gimmick Unlock System Test")
    print("=" * 60)
    print(f"\nGimmick unlock schedule (5-level intervals):")
    for gimmick, level in sorted(GIMMICK_UNLOCK_LEVELS.items(), key=lambda x: x[1]):
        print(f"  Level {level:2d}: {gimmick}")
    print()

    results = {
        "total_levels": 0,
        "successful": 0,
        "failed": 0,
        "validation_passed": 0,
        "gimmick_violations": [],
        "errors": [],
    }

    async with httpx.AsyncClient() as client:
        # Test levels at key unlock points
        test_levels = [1, 5, 10, 15, 20, 25, 30, 35, 40, 45, 50, 55]

        # Also add a few random levels
        test_levels.extend([3, 7, 12, 23, 33, 47])
        test_levels = sorted(set(test_levels))

        print(f"Testing {len(test_levels)} levels: {test_levels}\n")

        for level_num in test_levels:
            results["total_levels"] += 1

            # Calculate difficulty based on level number (0.2 ~ 0.8 range)
            difficulty = min(0.8, 0.2 + (level_num / 100))

            try:
                print(f"Level {level_num:2d} (difficulty={difficulty:.2f})... ", end="", flush=True)

                response = await generate_level(client, level_num, difficulty)

                if "level_json" not in response:
                    print("ERROR: No level_json in response")
                    results["errors"].append(f"Level {level_num}: No level_json")
                    results["failed"] += 1
                    continue

                level_json = response["level_json"]
                validation_passed = response.get("validation_passed", False)

                # Extract gimmicks from level
                used_gimmicks = extract_gimmicks_from_level(level_json)
                unlocked_gimmicks = get_unlocked_gimmicks(level_num)

                # Check for violations (using gimmicks that shouldn't be unlocked)
                violations = used_gimmicks - unlocked_gimmicks

                if violations:
                    print(f"VIOLATION: Used {violations} before unlock!")
                    results["gimmick_violations"].append({
                        "level": level_num,
                        "used": list(used_gimmicks),
                        "unlocked": list(unlocked_gimmicks),
                        "violations": list(violations)
                    })
                    results["failed"] += 1
                else:
                    results["successful"] += 1
                    if validation_passed:
                        results["validation_passed"] += 1

                    status = "PASS" if validation_passed else "PASS (no validation)"
                    gimmick_list = ", ".join(sorted(used_gimmicks)) if used_gimmicks else "none"
                    print(f"{status} | Gimmicks: {gimmick_list}")

            except Exception as e:
                print(f"ERROR: {e}")
                results["errors"].append(f"Level {level_num}: {str(e)}")
                results["failed"] += 1

    # Print summary
    print("\n" + "=" * 60)
    print("TEST SUMMARY")
    print("=" * 60)
    print(f"Total levels tested: {results['total_levels']}")
    print(f"Successful: {results['successful']}")
    print(f"Failed: {results['failed']}")
    print(f"Validation passed: {results['validation_passed']}")

    if results["gimmick_violations"]:
        print(f"\nGimmick Violations ({len(results['gimmick_violations'])}):")
        for v in results["gimmick_violations"]:
            print(f"  Level {v['level']}: Used {v['violations']} illegally")

    if results["errors"]:
        print(f"\nErrors ({len(results['errors'])}):")
        for e in results["errors"]:
            print(f"  {e}")

    # Overall result
    print("\n" + "=" * 60)
    if results["failed"] == 0 and results["successful"] > 0:
        print("RESULT: ALL TESTS PASSED!")
    else:
        print(f"RESULT: {results['failed']} TESTS FAILED")
    print("=" * 60)

    return results["failed"] == 0


if __name__ == "__main__":
    success = asyncio.run(run_test())
    exit(0 if success else 1)
