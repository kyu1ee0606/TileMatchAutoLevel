"""Utility helper functions."""
from typing import Dict, Any, List, Optional
import json


def validate_level_json(level_json: Dict[str, Any]) -> tuple[bool, Optional[str]]:
    """
    Validate level JSON structure.

    Args:
        level_json: Level data to validate.

    Returns:
        Tuple of (is_valid, error_message).
    """
    # Check for required 'layer' field
    if "layer" not in level_json:
        return False, "Missing 'layer' field"

    num_layers = level_json.get("layer", 0)
    if not isinstance(num_layers, int) or num_layers < 1:
        return False, "'layer' must be a positive integer"

    # Check layer data
    for i in range(num_layers):
        layer_key = f"layer_{i}"
        if layer_key not in level_json:
            return False, f"Missing '{layer_key}'"

        layer_data = level_json[layer_key]
        if not isinstance(layer_data, dict):
            return False, f"'{layer_key}' must be an object"

        # Check required layer fields
        required_fields = ["col", "row", "tiles", "num"]
        for field in required_fields:
            if field not in layer_data:
                return False, f"'{layer_key}' missing '{field}' field"

        # Validate tiles
        tiles = layer_data.get("tiles", {})
        if not isinstance(tiles, dict):
            return False, f"'{layer_key}.tiles' must be an object"

        for pos, tile_data in tiles.items():
            # Validate position format (x_y)
            parts = pos.split("_")
            if len(parts) != 2:
                return False, f"Invalid tile position format: '{pos}'"

            try:
                int(parts[0])
                int(parts[1])
            except ValueError:
                return False, f"Invalid tile position coordinates: '{pos}'"

            # Validate tile data format [type, attribute, ?extra]
            if not isinstance(tile_data, list):
                return False, f"Tile data at '{pos}' must be an array"

            if len(tile_data) < 2:
                return False, f"Tile data at '{pos}' must have at least 2 elements"

    return True, None


def normalize_level_json(level_json: Dict[str, Any]) -> Dict[str, Any]:
    """
    Normalize level JSON to consistent format.

    Args:
        level_json: Level data to normalize.

    Returns:
        Normalized level JSON.
    """
    normalized = {"layer": level_json.get("layer", 8)}

    for i in range(normalized["layer"]):
        layer_key = f"layer_{i}"
        layer_data = level_json.get(layer_key, {})

        normalized[layer_key] = {
            "col": str(layer_data.get("col", "7")),
            "row": str(layer_data.get("row", "7")),
            "tiles": {},
            "num": "0",
        }

        tiles = layer_data.get("tiles", {})
        for pos, tile_data in tiles.items():
            if isinstance(tile_data, list) and len(tile_data) >= 2:
                # Ensure tile data is properly formatted
                normalized_tile = [tile_data[0], tile_data[1]]
                if len(tile_data) > 2:
                    normalized_tile.append(tile_data[2])
                normalized[layer_key]["tiles"][pos] = normalized_tile

        normalized[layer_key]["num"] = str(len(normalized[layer_key]["tiles"]))

    return normalized


def format_level_for_display(level_json: Dict[str, Any]) -> str:
    """
    Format level JSON for human-readable display.

    Args:
        level_json: Level data to format.

    Returns:
        Formatted string representation.
    """
    lines = []
    num_layers = level_json.get("layer", 8)

    lines.append(f"Level with {num_layers} layers:")
    lines.append("-" * 40)

    for i in range(num_layers - 1, -1, -1):  # Top to bottom
        layer_key = f"layer_{i}"
        layer_data = level_json.get(layer_key, {})
        tiles = layer_data.get("tiles", {})

        if tiles:
            cols = int(layer_data.get("col", 7))
            rows = int(layer_data.get("row", 7))
            tile_count = len(tiles)

            lines.append(f"\nLayer {i} ({cols}x{rows}, {tile_count} tiles):")

            # Create grid visualization
            grid = [[".  " for _ in range(cols)] for _ in range(rows)]

            for pos, tile_data in tiles.items():
                parts = pos.split("_")
                if len(parts) == 2:
                    x, y = int(parts[0]), int(parts[1])
                    if 0 <= x < cols and 0 <= y < rows:
                        tile_type = tile_data[0][:2]  # First 2 chars
                        attr = tile_data[1][:1] if tile_data[1] else " "
                        grid[y][x] = f"{tile_type}{attr}"

            for row in grid:
                lines.append("  " + " ".join(row))

    return "\n".join(lines)


def extract_tile_statistics(level_json: Dict[str, Any]) -> Dict[str, Any]:
    """
    Extract detailed tile statistics from level.

    Args:
        level_json: Level data to analyze.

    Returns:
        Dictionary with tile statistics.
    """
    stats = {
        "total_tiles": 0,
        "tiles_per_layer": {},
        "tile_types": {},
        "attributes": {},
        "goals": [],
        "positions_used": set(),
    }

    num_layers = level_json.get("layer", 8)

    for i in range(num_layers):
        layer_key = f"layer_{i}"
        layer_data = level_json.get(layer_key, {})
        tiles = layer_data.get("tiles", {})

        layer_count = len(tiles)
        stats["tiles_per_layer"][layer_key] = layer_count
        stats["total_tiles"] += layer_count

        for pos, tile_data in tiles.items():
            if isinstance(tile_data, list) and len(tile_data) >= 2:
                tile_type = tile_data[0]
                attribute = tile_data[1]

                # Count tile types
                stats["tile_types"][tile_type] = stats["tile_types"].get(tile_type, 0) + 1

                # Count attributes
                if attribute:
                    stats["attributes"][attribute] = stats["attributes"].get(attribute, 0) + 1

                # Track goals
                if tile_type in ("craft_s", "stack_s"):
                    goal_count = tile_data[2][0] if len(tile_data) > 2 and tile_data[2] else 1
                    stats["goals"].append({
                        "type": tile_type,
                        "count": goal_count,
                        "position": pos,
                        "layer": layer_key,
                    })

                stats["positions_used"].add(pos)

    # Convert set to list for JSON serialization
    stats["positions_used"] = list(stats["positions_used"])

    return stats
