"""Level generator engine with difficulty targeting."""
import random
import time
from typing import Dict, List, Any, Optional, Tuple, Set
from dataclasses import dataclass

from ..models.level import (
    GenerationParams,
    GenerationResult,
    DifficultyGrade,
    TILE_TYPES,
)
from .analyzer import get_analyzer


class LevelGenerator:
    """Generates levels with target difficulty."""

    # Default tile types for generation
    DEFAULT_TILE_TYPES = ["t0", "t2", "t4", "t5", "t6"]
    OBSTACLE_TILE_TYPES = ["t8", "t9"]
    SPECIAL_TILE_TYPES = ["t10", "t11", "t12", "t14", "t15"]
    GOAL_TYPES = ["craft_s", "stack_s"]

    # Generation parameters
    MAX_ADJUSTMENT_ITERATIONS = 30
    DIFFICULTY_TOLERANCE = 5.0  # ±5 points

    def generate(self, params: GenerationParams) -> GenerationResult:
        """
        Generate a level with target difficulty.

        Args:
            params: Generation parameters including target difficulty.

        Returns:
            GenerationResult with generated level and actual difficulty.
        """
        start_time = time.time()

        # Create initial level structure
        level = self._create_base_structure(params)

        # Populate layers with tiles based on target difficulty
        level = self._populate_layers(level, params)

        # Add obstacles and attributes
        level = self._add_obstacles(level, params)

        # Add goals
        level = self._add_goals(level, params)

        # Adjust to target difficulty
        level = self._adjust_difficulty(level, params.target_difficulty)

        # Calculate final metrics
        analyzer = get_analyzer()
        report = analyzer.analyze(level)

        generation_time_ms = int((time.time() - start_time) * 1000)

        return GenerationResult(
            level_json=level,
            actual_difficulty=report.score / 100.0,
            grade=report.grade,
            generation_time_ms=generation_time_ms,
        )

    def _create_base_structure(self, params: GenerationParams) -> Dict[str, Any]:
        """Create the base level structure with empty layers."""
        cols, rows = params.grid_size
        level = {"layer": params.max_layers}

        for i in range(params.max_layers):
            # Alternating grid sizes (odd layers are smaller)
            layer_cols = str(cols + 1 if i % 2 == 0 else cols)
            layer_rows = str(rows + 1 if i % 2 == 0 else rows)

            level[f"layer_{i}"] = {
                "col": layer_cols,
                "row": layer_rows,
                "tiles": {},
                "num": "0",
            }

        return level

    def _populate_layers(
        self, level: Dict[str, Any], params: GenerationParams
    ) -> Dict[str, Any]:
        """Populate layers with tiles based on difficulty."""
        target = params.target_difficulty
        cols, rows = params.grid_size

        # Determine number of active layers based on difficulty
        min_active_layers = 3
        max_active_layers = params.max_layers - 2  # Leave some layers empty
        active_layer_count = min_active_layers + int(
            (max_active_layers - min_active_layers) * target
        )

        # Start from top layer and work down
        active_layers = list(range(params.max_layers - 1, params.max_layers - 1 - active_layer_count, -1))

        tile_types = params.tile_types or self.DEFAULT_TILE_TYPES

        for layer_idx in active_layers:
            layer_key = f"layer_{layer_idx}"
            is_odd_layer = layer_idx % 2 == 1

            # Calculate layer dimensions
            layer_cols = cols if is_odd_layer else cols + 1
            layer_rows = rows if is_odd_layer else rows + 1

            # Calculate tile density based on layer position and difficulty
            # Top layers have higher density
            layer_position_factor = (layer_idx - min(active_layers)) / max(1, len(active_layers) - 1)
            base_density = 0.3 + (target * 0.5)  # 30-80% base density
            layer_density = base_density * (0.5 + layer_position_factor * 0.5)

            # Generate positions for this layer
            positions = self._generate_layer_positions(
                layer_cols, layer_rows, layer_density
            )

            tiles = {}
            for pos in positions:
                tile_type = random.choice(tile_types)
                tiles[pos] = [tile_type, ""]

            level[layer_key]["tiles"] = tiles
            level[layer_key]["num"] = str(len(tiles))

        return level

    def _generate_layer_positions(
        self, cols: int, rows: int, density: float
    ) -> List[str]:
        """Generate tile positions for a layer based on density."""
        all_positions = []
        for x in range(cols):
            for y in range(rows):
                all_positions.append(f"{x}_{y}")

        # Select positions based on density
        target_count = max(1, int(len(all_positions) * density))
        selected = random.sample(all_positions, min(target_count, len(all_positions)))

        return selected

    def _add_obstacles(
        self, level: Dict[str, Any], params: GenerationParams
    ) -> Dict[str, Any]:
        """Add obstacles and attributes to tiles."""
        obstacle_types = params.obstacle_types or ["chain", "frog"]
        target = params.target_difficulty

        # Calculate target obstacle counts based on difficulty
        num_layers = level.get("layer", 8)
        total_tiles = sum(
            len(level.get(f"layer_{i}", {}).get("tiles", {}))
            for i in range(num_layers)
        )

        # Obstacle count scales with difficulty
        chain_target = int(total_tiles * target * 0.15)  # Up to 15% chains
        frog_target = int(total_tiles * target * 0.08)  # Up to 8% frogs
        link_target = int(total_tiles * target * 0.05)  # Up to 5% links

        obstacles_added = {"chain": 0, "frog": 0, "link": 0}

        # Add obstacles to tiles (prefer upper layers)
        for i in range(num_layers - 1, -1, -1):
            layer_key = f"layer_{i}"
            tiles = level.get(layer_key, {}).get("tiles", {})

            for pos, tile_data in tiles.items():
                if not isinstance(tile_data, list) or len(tile_data) < 2:
                    continue

                # Skip goal tiles
                if tile_data[0] in self.GOAL_TYPES:
                    continue

                # Skip if already has attribute
                if tile_data[1]:
                    continue

                # Random selection with probability based on remaining quota
                if "chain" in obstacle_types and obstacles_added["chain"] < chain_target:
                    if random.random() < 0.2:
                        tile_data[1] = "chain"
                        obstacles_added["chain"] += 1
                        continue

                if "frog" in obstacle_types and obstacles_added["frog"] < frog_target:
                    if random.random() < 0.15:
                        tile_data[1] = "frog"
                        obstacles_added["frog"] += 1
                        continue

                if obstacles_added["link"] < link_target:
                    if random.random() < 0.1:
                        tile_data[1] = random.choice(["link_w", "link_n"])
                        obstacles_added["link"] += 1

        return level

    def _add_goals(
        self, level: Dict[str, Any], params: GenerationParams
    ) -> Dict[str, Any]:
        """Add goal tiles to the level."""
        goals = params.goals or [{"type": "craft_s", "count": 3}]

        # Find the topmost active layer
        num_layers = level.get("layer", 8)
        top_layer_idx = None

        for i in range(num_layers - 1, -1, -1):
            layer_key = f"layer_{i}"
            if level.get(layer_key, {}).get("tiles", {}):
                top_layer_idx = i
                break

        if top_layer_idx is None:
            return level

        layer_key = f"layer_{top_layer_idx}"
        tiles = level[layer_key]["tiles"]

        # Find the bottom row positions for goals
        cols = int(level[layer_key]["col"])
        rows = int(level[layer_key]["row"])
        bottom_row = rows - 1

        # Place goals at bottom row
        goal_positions = []
        center_col = cols // 2

        for i, goal in enumerate(goals):
            # Position goals near center bottom
            col = center_col - len(goals) // 2 + i
            if col >= 0 and col < cols:
                pos = f"{col}_{bottom_row}"
                goal_positions.append(pos)

                goal_type = goal.get("type", "craft_s")
                goal_count = goal.get("count", 3)
                tiles[pos] = [goal_type, "", [goal_count]]

        # Update tile count
        level[layer_key]["num"] = str(len(tiles))

        return level

    def _adjust_difficulty(
        self, level: Dict[str, Any], target: float
    ) -> Dict[str, Any]:
        """Adjust level to match target difficulty within tolerance."""
        analyzer = get_analyzer()
        target_score = target * 100

        for iteration in range(self.MAX_ADJUSTMENT_ITERATIONS):
            report = analyzer.analyze(level)
            current_score = report.score
            diff = target_score - current_score

            if abs(diff) <= self.DIFFICULTY_TOLERANCE:
                break

            if diff > 0:
                # Need to increase difficulty
                level = self._increase_difficulty(level)
            else:
                # Need to decrease difficulty
                level = self._decrease_difficulty(level)

        return level

    def _increase_difficulty(self, level: Dict[str, Any]) -> Dict[str, Any]:
        """Apply a random modification to increase difficulty."""
        modifications = [
            self._add_chain_to_tile,
            self._add_frog_to_tile,
            self._add_tile_to_layer,
            self._increase_goal_count,
        ]

        modifier = random.choice(modifications)
        return modifier(level)

    def _decrease_difficulty(self, level: Dict[str, Any]) -> Dict[str, Any]:
        """Apply a random modification to decrease difficulty."""
        modifications = [
            self._remove_chain_from_tile,
            self._remove_frog_from_tile,
            self._remove_tile_from_layer,
            self._decrease_goal_count,
        ]

        modifier = random.choice(modifications)
        return modifier(level)

    def _add_chain_to_tile(self, level: Dict[str, Any]) -> Dict[str, Any]:
        """Add chain attribute to a random tile."""
        return self._add_attribute_to_tile(level, "chain")

    def _add_frog_to_tile(self, level: Dict[str, Any]) -> Dict[str, Any]:
        """Add frog attribute to a random tile."""
        return self._add_attribute_to_tile(level, "frog")

    def _add_attribute_to_tile(
        self, level: Dict[str, Any], attribute: str
    ) -> Dict[str, Any]:
        """Add an attribute to a random tile without one."""
        num_layers = level.get("layer", 8)

        # Collect all tiles without attributes
        candidates = []
        for i in range(num_layers):
            layer_key = f"layer_{i}"
            tiles = level.get(layer_key, {}).get("tiles", {})
            for pos, tile_data in tiles.items():
                if (
                    isinstance(tile_data, list)
                    and len(tile_data) >= 2
                    and not tile_data[1]
                    and tile_data[0] not in self.GOAL_TYPES
                ):
                    candidates.append((layer_key, pos))

        if candidates:
            layer_key, pos = random.choice(candidates)
            level[layer_key]["tiles"][pos][1] = attribute

        return level

    def _remove_chain_from_tile(self, level: Dict[str, Any]) -> Dict[str, Any]:
        """Remove chain attribute from a random tile."""
        return self._remove_attribute_from_tile(level, "chain")

    def _remove_frog_from_tile(self, level: Dict[str, Any]) -> Dict[str, Any]:
        """Remove frog attribute from a random tile."""
        return self._remove_attribute_from_tile(level, "frog")

    def _remove_attribute_from_tile(
        self, level: Dict[str, Any], attribute: str
    ) -> Dict[str, Any]:
        """Remove a specific attribute from a random tile."""
        num_layers = level.get("layer", 8)

        # Find tiles with the attribute
        candidates = []
        for i in range(num_layers):
            layer_key = f"layer_{i}"
            tiles = level.get(layer_key, {}).get("tiles", {})
            for pos, tile_data in tiles.items():
                if (
                    isinstance(tile_data, list)
                    and len(tile_data) >= 2
                    and tile_data[1] == attribute
                ):
                    candidates.append((layer_key, pos))

        if candidates:
            layer_key, pos = random.choice(candidates)
            level[layer_key]["tiles"][pos][1] = ""

        return level

    def _add_tile_to_layer(self, level: Dict[str, Any]) -> Dict[str, Any]:
        """Add a new tile to a random layer."""
        num_layers = level.get("layer", 8)

        # Find a layer with tiles but with available positions
        for _ in range(10):  # Try up to 10 times
            layer_idx = random.randint(3, num_layers - 1)
            layer_key = f"layer_{layer_idx}"
            layer_data = level.get(layer_key, {})
            tiles = layer_data.get("tiles", {})

            cols = int(layer_data.get("col", 7))
            rows = int(layer_data.get("row", 7))

            # Find available position
            for _ in range(20):
                x = random.randint(0, cols - 1)
                y = random.randint(0, rows - 1)
                pos = f"{x}_{y}"

                if pos not in tiles:
                    tile_type = random.choice(self.DEFAULT_TILE_TYPES)
                    tiles[pos] = [tile_type, ""]
                    level[layer_key]["num"] = str(len(tiles))
                    return level

        return level

    def _remove_tile_from_layer(self, level: Dict[str, Any]) -> Dict[str, Any]:
        """Remove a tile from a random layer."""
        num_layers = level.get("layer", 8)

        # Find layers with tiles that can be removed
        candidates = []
        for i in range(num_layers):
            layer_key = f"layer_{i}"
            tiles = level.get(layer_key, {}).get("tiles", {})

            for pos, tile_data in tiles.items():
                # Don't remove goal tiles
                if isinstance(tile_data, list) and tile_data[0] not in self.GOAL_TYPES:
                    candidates.append((layer_key, pos))

        if candidates:
            layer_key, pos = random.choice(candidates)
            del level[layer_key]["tiles"][pos]
            level[layer_key]["num"] = str(len(level[layer_key]["tiles"]))

        return level

    def _increase_goal_count(self, level: Dict[str, Any]) -> Dict[str, Any]:
        """Increase the count of a random goal."""
        return self._modify_goal_count(level, 1)

    def _decrease_goal_count(self, level: Dict[str, Any]) -> Dict[str, Any]:
        """Decrease the count of a random goal."""
        return self._modify_goal_count(level, -1)

    def _modify_goal_count(self, level: Dict[str, Any], delta: int) -> Dict[str, Any]:
        """Modify a goal's count by delta."""
        num_layers = level.get("layer", 8)

        # Find goal tiles
        goals = []
        for i in range(num_layers):
            layer_key = f"layer_{i}"
            tiles = level.get(layer_key, {}).get("tiles", {})

            for pos, tile_data in tiles.items():
                if (
                    isinstance(tile_data, list)
                    and len(tile_data) >= 3
                    and tile_data[0] in self.GOAL_TYPES
                ):
                    goals.append((layer_key, pos))

        if goals:
            layer_key, pos = random.choice(goals)
            tile_data = level[layer_key]["tiles"][pos]

            if len(tile_data) >= 3 and isinstance(tile_data[2], list):
                new_count = max(1, tile_data[2][0] + delta)
                tile_data[2][0] = new_count

        return level


# Singleton instance
_generator = None


def get_generator() -> LevelGenerator:
    """Get or create generator singleton instance."""
    global _generator
    if _generator is None:
        _generator = LevelGenerator()
    return _generator
