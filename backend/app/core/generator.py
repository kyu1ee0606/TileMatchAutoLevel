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

        # CRITICAL: First ensure tile count is divisible by 3
        # This may add/remove tiles which could affect obstacle validity
        level = self._ensure_tile_count_divisible_by_3(level, params)

        # CRITICAL: Then validate obstacles AFTER all tile modifications
        # This ensures all obstacles (chain, link, grass) have valid clearable neighbors
        # Must be called LAST to catch any issues from tile count adjustment
        level = self._validate_and_fix_obstacles(level)

        # Final check: if obstacle removal broke divisibility, fix it again
        level = self._ensure_tile_count_divisible_by_3(level, params)

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

        # CRITICAL: Ensure total tile count is divisible by 3
        total_tiles = sum(
            len(level.get(f"layer_{i}", {}).get("tiles", {}))
            for i in range(params.max_layers)
        )

        remainder = total_tiles % 3
        if remainder != 0:
            # Need to adjust tile count
            tiles_to_adjust = 3 - remainder

            # Find the first non-empty layer to add tiles
            for layer_idx in active_layers:
                layer_key = f"layer_{layer_idx}"
                tiles = level[layer_key]["tiles"]
                is_odd_layer = layer_idx % 2 == 1
                layer_cols = cols if is_odd_layer else cols + 1
                layer_rows = rows if is_odd_layer else rows + 1

                # Find available positions
                all_positions = [f"{x}_{y}" for x in range(layer_cols) for y in range(layer_rows)]
                used_positions = set(tiles.keys())
                available_positions = [p for p in all_positions if p not in used_positions]

                if len(available_positions) >= tiles_to_adjust:
                    # Add tiles to this layer
                    for i in range(tiles_to_adjust):
                        pos = available_positions[i]
                        tile_type = random.choice(tile_types)
                        tiles[pos] = [tile_type, ""]
                    level[layer_key]["num"] = str(len(tiles))
                    break

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

        # IMPORTANT: Ensure tile count is divisible by 3 for match-3 game
        target_count = (target_count // 3) * 3
        if target_count == 0:
            target_count = 3  # Minimum 3 tiles

        selected = random.sample(all_positions, min(target_count, len(all_positions)))

        return selected

    def _add_obstacles(
        self, level: Dict[str, Any], params: GenerationParams
    ) -> Dict[str, Any]:
        """Add obstacles and attributes to tiles following game rules."""
        obstacle_types = params.obstacle_types or ["chain", "frog"]
        target = params.target_difficulty

        # Calculate target obstacle counts based on difficulty
        num_layers = level.get("layer", 8)
        total_tiles = sum(
            len(level.get(f"layer_{i}", {}).get("tiles", {}))
            for i in range(num_layers)
        )

        # Helper to get target count for an obstacle type
        def get_target(obstacle_type: str, default_ratio: float) -> int:
            if params.obstacle_counts and obstacle_type in params.obstacle_counts:
                config = params.obstacle_counts[obstacle_type]
                min_count = config.get("min", 0)
                max_count = config.get("max", 10)
                return random.randint(min_count, max_count)
            # Legacy behavior: scale with difficulty
            return int(total_tiles * target * default_ratio)

        # Get target counts (use configured values or calculate from difficulty)
        chain_target = get_target("chain", 0.15)  # Up to 15% chains
        frog_target = get_target("frog", 0.08)  # Up to 8% frogs
        link_target = get_target("link", 0.05)  # Up to 5% links (pairs)
        grass_target = get_target("grass", 0.10)  # Up to 10% grass

        obstacles_added = {"chain": 0, "frog": 0, "link": 0, "grass": 0}

        # Add frog obstacles (no special rules)
        if "frog" in obstacle_types:
            level = self._add_frog_obstacles(level, frog_target, obstacles_added)

        # Add chain obstacles (must have clearable LEFT or RIGHT neighbor)
        if "chain" in obstacle_types:
            level = self._add_chain_obstacles(level, chain_target, obstacles_added)

        # Add link obstacles (must create valid pairs with clearable neighbor)
        if "link" in obstacle_types:
            level = self._add_link_obstacles(level, link_target, obstacles_added)

        # Add grass obstacles (must have at least 2 clearable neighbors in 4 directions)
        if "grass" in obstacle_types:
            level = self._add_grass_obstacles(level, grass_target, obstacles_added)

        return level

    def _add_frog_obstacles(
        self, level: Dict[str, Any], target: int, counter: Dict[str, int]
    ) -> Dict[str, Any]:
        """Add frog obstacles (no special placement rules)."""
        num_layers = level.get("layer", 8)

        for i in range(num_layers - 1, -1, -1):
            if counter["frog"] >= target:
                break

            layer_key = f"layer_{i}"
            tiles = level.get(layer_key, {}).get("tiles", {})

            for pos, tile_data in list(tiles.items()):
                if counter["frog"] >= target:
                    break

                if not isinstance(tile_data, list) or len(tile_data) < 2:
                    continue

                # Skip goal tiles and tiles with attributes
                if tile_data[0] in self.GOAL_TYPES or tile_data[1]:
                    continue

                if random.random() < 0.15:
                    tile_data[1] = "frog"
                    counter["frog"] += 1

        return level

    def _add_chain_obstacles(
        self, level: Dict[str, Any], target: int, counter: Dict[str, int]
    ) -> Dict[str, Any]:
        """
        Add chain obstacles following the rule:
        Chain tiles MUST have at least one clearable neighbor on LEFT or RIGHT (same row).
        Chain is released by clearing adjacent tiles on the left or right side only.
        """
        num_layers = level.get("layer", 8)

        # Collect all tiles by layer with their positions
        layer_tiles = {}
        for i in range(num_layers):
            layer_key = f"layer_{i}"
            tiles = level.get(layer_key, {}).get("tiles", {})
            if tiles:
                layer_tiles[i] = {
                    "tiles": tiles,
                    "cols": int(level[layer_key].get("col", 8)),
                    "rows": int(level[layer_key].get("row", 8))
                }

        # Try to add chains
        attempts = 0
        max_attempts = target * 10  # Prevent infinite loop

        while counter["chain"] < target and attempts < max_attempts:
            attempts += 1

            # Pick a random layer with tiles
            available_layers = list(layer_tiles.keys())
            if not available_layers:
                break

            layer_idx = random.choice(available_layers)
            layer_data = layer_tiles[layer_idx]
            tiles = layer_data["tiles"]

            # Pick a random tile
            positions = list(tiles.keys())
            if not positions:
                continue

            pos = random.choice(positions)
            tile_data = tiles[pos]

            # Skip if not valid
            if not isinstance(tile_data, list) or len(tile_data) < 2:
                continue
            if tile_data[0] in self.GOAL_TYPES or tile_data[1]:
                continue

            # Parse position (format is row_col)
            try:
                row, col = map(int, pos.split('_'))
            except:
                continue

            # Chain only checks LEFT and RIGHT neighbors (same column, row±1)
            # In frontend display: row maps to x-axis (horizontal), so row±1 is left/right on screen
            neighbors = [
                (row-1, col),  # Left (on screen)
                (row+1, col),  # Right (on screen)
            ]

            valid_chain = False
            for nx, ny in neighbors:
                neighbor_pos = f"{nx}_{ny}"
                if neighbor_pos not in tiles:
                    continue

                neighbor_data = tiles[neighbor_pos]
                if not isinstance(neighbor_data, list) or len(neighbor_data) < 2:
                    continue

                # Skip goal tiles
                if neighbor_data[0] in self.GOAL_TYPES:
                    continue

                # RULE: Neighbor must be clearable (no obstacle or frog only)
                if neighbor_data[1] and neighbor_data[1] != "frog":
                    continue

                # Valid chain position found!
                valid_chain = True
                break

            if valid_chain:
                tile_data[1] = "chain"
                counter["chain"] += 1

        return level

    def _add_grass_obstacles(
        self, level: Dict[str, Any], target: int, counter: Dict[str, int]
    ) -> Dict[str, Any]:
        """
        Add grass obstacles following the rule:
        Grass tiles MUST have at least 2 clearable neighbors in 4 directions (up/down/left/right).
        Grass is released by clearing adjacent tiles (needs at least 2 to be clearable).
        """
        num_layers = level.get("layer", 8)

        # Collect all tiles by layer
        layer_tiles = {}
        for i in range(num_layers):
            layer_key = f"layer_{i}"
            tiles = level.get(layer_key, {}).get("tiles", {})
            if tiles:
                layer_tiles[i] = tiles

        attempts = 0
        max_attempts = target * 10

        while counter["grass"] < target and attempts < max_attempts:
            attempts += 1

            available_layers = list(layer_tiles.keys())
            if not available_layers:
                break

            layer_idx = random.choice(available_layers)
            tiles = layer_tiles[layer_idx]

            positions = list(tiles.keys())
            if not positions:
                continue

            pos = random.choice(positions)
            tile_data = tiles[pos]

            if not isinstance(tile_data, list) or len(tile_data) < 2:
                continue
            if tile_data[0] in self.GOAL_TYPES or tile_data[1]:
                continue

            try:
                row, col = map(int, pos.split('_'))
            except:
                continue

            # Grass checks all 4 directions
            neighbors = [
                (row-1, col),  # Up
                (row+1, col),  # Down
                (row, col-1),  # Left
                (row, col+1),  # Right
            ]

            clearable_count = 0
            for nrow, ncol in neighbors:
                npos = f"{nrow}_{ncol}"
                if npos in tiles:
                    ndata = tiles[npos]
                    if (isinstance(ndata, list) and len(ndata) >= 2 and
                        (not ndata[1] or ndata[1] == "frog") and
                        ndata[0] not in self.GOAL_TYPES):
                        clearable_count += 1

            # RULE: Must have at least 2 clearable neighbors
            if clearable_count >= 2:
                tile_data[1] = "grass"
                counter["grass"] += 1

        return level

    def _add_link_obstacles(
        self, level: Dict[str, Any], target: int, counter: Dict[str, int]
    ) -> Dict[str, Any]:
        """
        Add link obstacles following the rules:
        1. Linked tiles must have their partner tile exist in the connected direction.
        2. At least ONE of the link pair must have a clearable neighbor (excluding the link partner).
           This ensures the link can be released.
        """
        num_layers = level.get("layer", 8)

        # Collect all tiles by layer
        layer_tiles = {}
        for i in range(num_layers):
            layer_key = f"layer_{i}"
            tiles = level.get(layer_key, {}).get("tiles", {})
            if tiles:
                layer_tiles[i] = tiles

        attempts = 0
        max_attempts = target * 10

        while counter["link"] < target and attempts < max_attempts:
            attempts += 1

            # Pick a random layer
            available_layers = list(layer_tiles.keys())
            if not available_layers:
                break

            layer_idx = random.choice(available_layers)
            tiles = layer_tiles[layer_idx]

            # Pick a random tile
            positions = list(tiles.keys())
            if not positions:
                continue

            pos1 = random.choice(positions)
            tile_data1 = tiles[pos1]

            # Skip if not valid
            if not isinstance(tile_data1, list) or len(tile_data1) < 2:
                continue
            if tile_data1[0] in self.GOAL_TYPES or tile_data1[1]:
                continue

            # Parse position (format is row_col)
            try:
                row1, col1 = map(int, pos1.split('_'))
            except:
                continue

            # Try to find a valid partner in one of 4 directions (row_col format)
            directions = [
                ("link_n", (row1-1, col1)),  # North (up = row-1)
                ("link_s", (row1+1, col1)),  # South (down = row+1)
                ("link_w", (row1, col1-1)),  # West (left = col-1)
                ("link_e", (row1, col1+1)),  # East (right = col+1)
            ]

            valid_link = False
            for link_type, (row2, col2) in directions:
                pos2 = f"{row2}_{col2}"

                # RULE 1: Partner tile MUST exist
                if pos2 not in tiles:
                    continue

                tile_data2 = tiles[pos2]
                if not isinstance(tile_data2, list) or len(tile_data2) < 2:
                    continue

                # Skip goal tiles and tiles with attributes
                if tile_data2[0] in self.GOAL_TYPES or tile_data2[1]:
                    continue

                # RULE 2: At least one of the link pair must have a clearable neighbor
                # (excluding the link partner itself)
                has_clearable = self._link_pair_has_clearable_neighbor(
                    tiles, pos1, pos2, row1, col1, row2, col2
                )
                if not has_clearable:
                    continue

                # Valid link pair found!
                # Determine opposite direction
                opposite = {
                    "link_n": "link_s",
                    "link_s": "link_n",
                    "link_w": "link_e",
                    "link_e": "link_w"
                }

                tile_data1[1] = link_type
                tile_data2[1] = opposite[link_type]
                counter["link"] += 2  # Count both tiles
                valid_link = True
                break

            if valid_link:
                pass  # Successfully added link pair

        return level

    def _link_pair_has_clearable_neighbor(
        self, tiles: Dict, pos1: str, pos2: str,
        row1: int, col1: int, row2: int, col2: int
    ) -> bool:
        """
        Check if at least one tile in the link pair has a clearable neighbor.
        A clearable neighbor is a tile without obstacle attribute (or frog only).
        The link partner itself doesn't count as a clearable neighbor.
        """
        # Get all neighbors for both tiles (excluding each other)
        neighbors1 = [
            (row1+1, col1), (row1-1, col1), (row1, col1+1), (row1, col1-1)
        ]
        neighbors2 = [
            (row2+1, col2), (row2-1, col2), (row2, col2+1), (row2, col2-1)
        ]

        # Check neighbors of tile 1 (excluding pos2)
        for nrow, ncol in neighbors1:
            npos = f"{nrow}_{ncol}"
            if npos == pos2:
                continue
            if npos in tiles:
                ndata = tiles[npos]
                if (isinstance(ndata, list) and len(ndata) >= 2 and
                    (not ndata[1] or ndata[1] == "frog") and
                    ndata[0] not in self.GOAL_TYPES):
                    return True

        # Check neighbors of tile 2 (excluding pos1)
        for nrow, ncol in neighbors2:
            npos = f"{nrow}_{ncol}"
            if npos == pos1:
                continue
            if npos in tiles:
                ndata = tiles[npos]
                if (isinstance(ndata, list) and len(ndata) >= 2 and
                    (not ndata[1] or ndata[1] == "frog") and
                    ndata[0] not in self.GOAL_TYPES):
                    return True

        return False

    def _add_goals(
        self, level: Dict[str, Any], params: GenerationParams
    ) -> Dict[str, Any]:
        """Add goal tiles to the level."""
        # Use None check instead of falsy check to allow empty list
        goals = params.goals if params.goals is not None else [{"type": "craft_s", "count": 3}]

        # If goals is empty list, skip adding goals
        if not goals:
            return level

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
        """Apply a random modification to increase difficulty.

        Note: Obstacle modifications (chain, frog) are removed to respect
        user-specified obstacle counts from obstacle_counts parameter.
        Difficulty is adjusted primarily through tile count and goal changes.
        """
        modifications = [
            self._add_tile_to_layer,
            self._increase_goal_count,
        ]

        modifier = random.choice(modifications)
        return modifier(level)

    def _decrease_difficulty(self, level: Dict[str, Any]) -> Dict[str, Any]:
        """Apply a random modification to decrease difficulty.

        Note: Obstacle modifications (chain, frog) are removed to respect
        user-specified obstacle counts from obstacle_counts parameter.
        Difficulty is adjusted primarily through tile count and goal changes.
        """
        modifications = [
            self._remove_tile_from_layer,
            self._decrease_goal_count,
        ]

        modifier = random.choice(modifications)
        return modifier(level)

    def _add_chain_to_tile(self, level: Dict[str, Any]) -> Dict[str, Any]:
        """
        Add chain attribute to a random tile.
        RULE: Chain tiles MUST have at least one clearable neighbor on LEFT or RIGHT (same row).
        Chain is released by clearing adjacent tiles on the left or right side.
        """
        num_layers = level.get("layer", 8)

        # Collect candidates: tiles without attributes that have a clearable LEFT or RIGHT neighbor
        candidates = []
        for i in range(num_layers):
            layer_key = f"layer_{i}"
            tiles = level.get(layer_key, {}).get("tiles", {})

            for pos, tile_data in tiles.items():
                # Skip if already has attribute or is goal tile
                if not isinstance(tile_data, list) or len(tile_data) < 2:
                    continue
                if tile_data[1] or tile_data[0] in self.GOAL_TYPES:
                    continue

                # Check if has clearable neighbor on LEFT or RIGHT
                try:
                    row, col = map(int, pos.split('_'))
                except:
                    continue

                # Only check LEFT (row-1) and RIGHT (row+1) neighbors (on screen)
                neighbors = [
                    (row-1, col),  # Left (on screen)
                    (row+1, col),  # Right (on screen)
                ]

                has_clearable_neighbor = False
                for nrow, ncol in neighbors:
                    npos = f"{nrow}_{ncol}"
                    if npos in tiles:
                        ndata = tiles[npos]
                        # Clearable = no obstacle or frog only
                        if (isinstance(ndata, list) and len(ndata) >= 2 and
                            (not ndata[1] or ndata[1] == "frog") and
                            ndata[0] not in self.GOAL_TYPES):
                            has_clearable_neighbor = True
                            break

                if has_clearable_neighbor:
                    candidates.append((layer_key, pos))

        if candidates:
            layer_key, pos = random.choice(candidates)
            level[layer_key]["tiles"][pos][1] = "chain"

        return level

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
        """Remove a tile from a random layer.

        IMPORTANT: Do not remove tiles that are neighbors of chain/link/grass obstacles,
        as this would make them impossible to clear.
        """
        num_layers = level.get("layer", 8)

        # Find layers with tiles that can be removed
        candidates = []
        for i in range(num_layers):
            layer_key = f"layer_{i}"
            tiles = level.get(layer_key, {}).get("tiles", {})

            for pos, tile_data in tiles.items():
                # Don't remove goal tiles
                if not isinstance(tile_data, list) or tile_data[0] in self.GOAL_TYPES:
                    continue

                # Don't remove tiles with obstacles
                if len(tile_data) >= 2 and tile_data[1]:
                    continue

                # Check if this tile is a neighbor of a chain (left or right on screen)
                # If removed, the chain would have no clearable neighbor
                try:
                    row, col = map(int, pos.split('_'))
                except:
                    continue

                is_critical_neighbor = False

                # Check if left neighbor (row-1) is chain (on screen)
                left_pos = f"{row-1}_{col}"
                if left_pos in tiles:
                    left_data = tiles[left_pos]
                    if isinstance(left_data, list) and len(left_data) >= 2 and left_data[1] == "chain":
                        # Check if chain has other clearable neighbor (left side = row-2)
                        other_side = f"{row-2}_{col}"
                        if other_side not in tiles:
                            # This tile is the only clearable neighbor for the chain
                            is_critical_neighbor = True

                # Check if right neighbor (row+1) is chain (on screen)
                right_pos = f"{row+1}_{col}"
                if right_pos in tiles:
                    right_data = tiles[right_pos]
                    if isinstance(right_data, list) and len(right_data) >= 2 and right_data[1] == "chain":
                        # Check if chain has other clearable neighbor (right side = row+2)
                        other_side = f"{row+2}_{col}"
                        if other_side not in tiles:
                            # This tile is the only clearable neighbor for the chain
                            is_critical_neighbor = True

                if not is_critical_neighbor:
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

    def _ensure_tile_count_divisible_by_3(
        self, level: Dict[str, Any], params: GenerationParams
    ) -> Dict[str, Any]:
        """
        Ensure the total number of NORMAL tiles (excluding goal tiles) is divisible by 3.
        This is critical for match-3 games to be completable.

        IMPORTANT: Goal tiles (craft_s, stack_s) are NOT matched, so they should not be counted.
        Only normal tiles that can be matched need to be divisible by 3.
        """
        num_layers = level.get("layer", 8)

        # Count ONLY normal tiles (exclude goal tiles)
        normal_tiles = 0
        for i in range(num_layers):
            layer_key = f"layer_{i}"
            tiles = level.get(layer_key, {}).get("tiles", {})
            for pos, tile_data in tiles.items():
                if isinstance(tile_data, list) and len(tile_data) > 0:
                    tile_type = tile_data[0]
                    # Exclude goal tiles from count
                    if tile_type not in self.GOAL_TYPES:
                        normal_tiles += 1

        remainder = normal_tiles % 3

        if remainder == 0:
            return level

        tiles_to_adjust = 3 - remainder

        # Find layers with tiles (prefer upper layers)
        active_layers = []
        for i in range(num_layers - 1, -1, -1):
            layer_key = f"layer_{i}"
            if level.get(layer_key, {}).get("tiles", {}):
                active_layers.append(i)

        if not active_layers:
            return level

        # Try to add tiles to an existing layer
        tile_types = params.tile_types or self.DEFAULT_TILE_TYPES

        for layer_idx in active_layers:
            layer_key = f"layer_{layer_idx}"
            tiles = level[layer_key]["tiles"]
            is_odd_layer = layer_idx % 2 == 1

            # Calculate layer dimensions
            cols, rows = params.grid_size
            layer_cols = cols if is_odd_layer else cols + 1
            layer_rows = rows if is_odd_layer else rows + 1

            # Find available positions
            all_positions = [
                f"{x}_{y}" for x in range(layer_cols) for y in range(layer_rows)
            ]
            used_positions = set(tiles.keys())
            available_positions = [p for p in all_positions if p not in used_positions]

            if len(available_positions) >= tiles_to_adjust:
                # Add tiles to this layer
                for i in range(tiles_to_adjust):
                    pos = available_positions[i]
                    tile_type = random.choice(tile_types)
                    tiles[pos] = [tile_type, ""]

                level[layer_key]["num"] = str(len(tiles))
                break

        return level

    def _validate_and_fix_obstacles(self, level: Dict[str, Any]) -> Dict[str, Any]:
        """
        Final validation pass to ensure all obstacles follow game rules.
        This is called AFTER all modifications (difficulty adjustment, tile addition, etc.)

        Rules:
        1. Chain tiles: At least ONE neighbor must be clearable (no obstacle attribute)
        2. Link tiles: Partner tile MUST exist AND at least one of the pair must have clearable neighbor
        """
        num_layers = level.get("layer", 8)

        for i in range(num_layers):
            layer_key = f"layer_{i}"
            tiles = level.get(layer_key, {}).get("tiles", {})
            if not tiles:
                continue

            # Collect invalid obstacles to remove
            invalid_obstacles = []
            # Track validated link pairs to avoid double-checking
            validated_link_pairs = set()

            for pos, tile_data in tiles.items():
                if not isinstance(tile_data, list) or len(tile_data) < 2:
                    continue

                attr = tile_data[1]

                # Validate chain tiles - Chain only checks LEFT and RIGHT (on screen)
                if attr == "chain":
                    row, col = map(int, pos.split('_'))
                    # Only LEFT (row-1) and RIGHT (row+1) neighbors on screen
                    neighbors = [
                        (row-1, col),  # Left (on screen)
                        (row+1, col),  # Right (on screen)
                    ]

                    has_clearable_neighbor = False
                    for nrow, ncol in neighbors:
                        npos = f"{nrow}_{ncol}"
                        if npos in tiles:
                            ndata = tiles[npos]
                            # Check if neighbor is clearable (no obstacle or frog only)
                            if (isinstance(ndata, list) and len(ndata) >= 2 and
                                (not ndata[1] or ndata[1] == "frog")):
                                has_clearable_neighbor = True
                                break

                    if not has_clearable_neighbor:
                        invalid_obstacles.append(pos)

                # Validate link tiles
                elif attr.startswith("link_"):
                    row, col = map(int, pos.split('_'))

                    # Determine partner position
                    if attr == "link_n":
                        partner_pos = f"{row-1}_{col}"
                        expected = "link_s"
                        prow, pcol = row-1, col
                    elif attr == "link_s":
                        partner_pos = f"{row+1}_{col}"
                        expected = "link_n"
                        prow, pcol = row+1, col
                    elif attr == "link_w":
                        partner_pos = f"{row}_{col-1}"
                        expected = "link_e"
                        prow, pcol = row, col-1
                    elif attr == "link_e":
                        partner_pos = f"{row}_{col+1}"
                        expected = "link_w"
                        prow, pcol = row, col+1
                    else:
                        continue

                    # Create pair key (sorted to avoid duplicates)
                    pair_key = tuple(sorted([pos, partner_pos]))
                    if pair_key in validated_link_pairs:
                        continue
                    validated_link_pairs.add(pair_key)

                    # RULE 1: Check if partner exists and has correct link type
                    valid_link = False
                    if partner_pos in tiles:
                        partner_data = tiles[partner_pos]
                        if (isinstance(partner_data, list) and len(partner_data) >= 2 and
                            partner_data[1] == expected):
                            valid_link = True

                    if not valid_link:
                        invalid_obstacles.append(pos)
                        continue

                    # RULE 2: At least one of the link pair must have clearable neighbor
                    has_clearable = self._link_pair_has_clearable_neighbor(
                        tiles, pos, partner_pos, row, col, prow, pcol
                    )
                    if not has_clearable:
                        # Remove both link tiles
                        invalid_obstacles.append(pos)
                        invalid_obstacles.append(partner_pos)

                # Validate grass tiles - must have at least 2 clearable neighbors in 4 directions
                elif attr == "grass" or attr.startswith("grass_"):
                    row, col = map(int, pos.split('_'))
                    neighbors = [
                        (row-1, col),  # Up
                        (row+1, col),  # Down
                        (row, col-1),  # Left
                        (row, col+1),  # Right
                    ]

                    clearable_count = 0
                    for nrow, ncol in neighbors:
                        npos = f"{nrow}_{ncol}"
                        if npos in tiles:
                            ndata = tiles[npos]
                            if (isinstance(ndata, list) and len(ndata) >= 2 and
                                (not ndata[1] or ndata[1] == "frog")):
                                clearable_count += 1

                    # RULE: Must have at least 2 clearable neighbors
                    if clearable_count < 2:
                        invalid_obstacles.append(pos)

            # Remove invalid obstacles
            for pos in invalid_obstacles:
                if pos in tiles and tiles[pos][1]:
                    tiles[pos][1] = ""

        return level


# Singleton instance
_generator = None


def get_generator() -> LevelGenerator:
    """Get or create generator singleton instance."""
    global _generator
    if _generator is None:
        _generator = LevelGenerator()
    return _generator
