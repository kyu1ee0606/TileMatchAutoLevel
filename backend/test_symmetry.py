#!/usr/bin/env python3
"""Test symmetry and pattern generation"""
import requests
import json

BASE_URL = "http://localhost:8000/api/generate"

def generate_level(pattern_type: str, symmetry_mode: str) -> dict:
    """Generate a level with the given settings"""
    payload = {
        "grid_size": [7, 7],
        "max_layers": 3,
        "tile_types": ["t0", "t1", "t2"],
        "obstacle_types": [],
        "goals": [{"type": "craft", "direction": "s", "count": 1}],
        "pattern_type": pattern_type,
        "symmetry_mode": symmetry_mode,
        "target_difficulty": 0.3
    }
    response = requests.post(BASE_URL, json=payload)
    return response.json()

def extract_positions(level_json: dict) -> set:
    """Extract all tile positions from level_json"""
    positions = set()
    for i in range(20):  # Check up to 20 layers
        layer_key = f"layer_{i}"
        if layer_key in level_json:
            layer_data = level_json[layer_key]
            if isinstance(layer_data, dict) and "tiles" in layer_data:
                tiles = layer_data["tiles"]
                if isinstance(tiles, dict):
                    for pos_key in tiles.keys():
                        x, y = map(int, pos_key.split("_"))
                        positions.add((x, y))
    return positions

def visualize_level(level_json: dict, title: str):
    """Visualize level positions in a grid"""
    positions = extract_positions(level_json)

    print(f"\n{'='*30}")
    print(f"{title}")
    print(f"{'='*30}")

    for y in range(7):
        row = ""
        for x in range(7):
            row += "■ " if (x, y) in positions else "□ "
        print(row)

    print(f"Total positions: {len(positions)}")

def check_symmetry(level_json: dict, symmetry_mode: str) -> tuple[bool, str]:
    """Check if the level has the expected symmetry - per layer

    Note: Goal tiles (craft_*, stack_*) are excluded from symmetry checks
    as they are functional elements that don't need to be symmetric.
    """
    if symmetry_mode == "none":
        return True, "No symmetry check needed"

    base_cols, base_rows = 7, 7  # Base grid size

    for i in range(20):
        layer_key = f"layer_{i}"
        if layer_key not in level_json:
            continue

        layer_data = level_json[layer_key]
        if not isinstance(layer_data, dict) or "tiles" not in layer_data:
            continue

        tiles = layer_data.get("tiles", {})
        if not tiles:
            continue

        # Determine layer dimensions
        is_odd_layer = i % 2 == 1
        cols = base_cols if is_odd_layer else base_cols + 1
        rows = base_rows if is_odd_layer else base_rows + 1

        positions = set()
        for pos_key, tile_data in tiles.items():
            # Skip goal tiles - they don't need to be symmetric
            if isinstance(tile_data, list) and len(tile_data) > 0:
                tile_type = tile_data[0]
                if tile_type.startswith("craft_") or tile_type.startswith("stack_"):
                    continue
            x, y = map(int, pos_key.split("_"))
            positions.add((x, y))

        if symmetry_mode == "horizontal":
            for (x, y) in positions:
                mirror_x = cols - 1 - x
                if 0 <= mirror_x < cols and (mirror_x, y) not in positions:
                    return False, f"Layer {i}: Missing horizontal mirror at ({mirror_x}, {y}) for ({x}, {y})"

        elif symmetry_mode == "vertical":
            for (x, y) in positions:
                mirror_y = rows - 1 - y
                if 0 <= mirror_y < rows and (x, mirror_y) not in positions:
                    return False, f"Layer {i}: Missing vertical mirror at ({x}, {mirror_y}) for ({x}, {y})"

        elif symmetry_mode == "both":
            for (x, y) in positions:
                mirror_x = cols - 1 - x
                mirror_y = rows - 1 - y
                if 0 <= mirror_x < cols and (mirror_x, y) not in positions:
                    return False, f"Layer {i}: Missing horizontal mirror at ({mirror_x}, {y}) for ({x}, {y})"
                if 0 <= mirror_y < rows and (x, mirror_y) not in positions:
                    return False, f"Layer {i}: Missing vertical mirror at ({x}, {mirror_y}) for ({x}, {y})"
                if 0 <= mirror_x < cols and 0 <= mirror_y < rows and (mirror_x, mirror_y) not in positions:
                    return False, f"Layer {i}: Missing diagonal mirror at ({mirror_x}, {mirror_y}) for ({x}, {y})"

    return True, f"{symmetry_mode.capitalize()} symmetry OK"

def main():
    test_cases = [
        ("random", "none"),
        ("geometric", "none"),
        ("geometric", "horizontal"),
        ("geometric", "vertical"),
        ("geometric", "both"),
        ("clustered", "none"),
        ("clustered", "horizontal"),
        ("clustered", "vertical"),
        ("clustered", "both"),
    ]

    results = []

    for pattern, symmetry in test_cases:
        title = f"{pattern.upper()} + {symmetry.upper()}"
        try:
            result = generate_level(pattern, symmetry)
            if "error" in result:
                print(f"\n❌ {title}: ERROR - {result['error']}")
                results.append((title, False, result.get("error", "Unknown error")))
                continue

            level_json = result.get("level_json", {})
            visualize_level(level_json, title)

            # Check symmetry
            is_symmetric, message = check_symmetry(level_json, symmetry)
            if is_symmetric:
                print(f"✅ {message}")
                results.append((title, True, message))
            else:
                print(f"❌ {message}")
                results.append((title, False, message))

        except Exception as e:
            print(f"\n❌ {title}: EXCEPTION - {e}")
            results.append((title, False, str(e)))

    # Summary
    print("\n" + "="*50)
    print("SUMMARY")
    print("="*50)
    passed = sum(1 for _, ok, _ in results if ok)
    total = len(results)
    print(f"Passed: {passed}/{total}")

    for title, ok, message in results:
        status = "✅" if ok else "❌"
        print(f"{status} {title}: {message}")

    return passed == total

if __name__ == "__main__":
    success = main()
    exit(0 if success else 1)
