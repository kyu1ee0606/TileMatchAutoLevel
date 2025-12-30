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
    # NOTE: t0 is the "random tile" that gets converted to t1~t{useTileCount} at runtime
    # So we use t0 plus some explicit tile types (t2~t5)
    # This gives useTileCount=5, meaning t0 can become t1~t5
    DEFAULT_TILE_TYPES = ["t0", "t2", "t4", "t5"]  # Removed t6 to match useTileCount=5
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

        Raises:
            ValueError: If layer_tile_configs total is not divisible by 3.
        """
        start_time = time.time()

        # Check if user has specified per-layer tile configs (strict mode)
        # In strict mode, we respect user's tile counts exactly
        has_strict_tile_config = bool(params.layer_tile_configs) and len(params.layer_tile_configs) > 0

        # Calculate total goal inner tiles (craft_s with count=3 means 3 additional tiles inside)
        # Goal tiles are visual tiles that CONTAIN inner tiles, not replace them
        # Example: 21+21 tiles + craft_s(3) = 42 visual tiles + 3 inner tiles = 45 actual tiles
        goal_inner_tiles = 0
        goals = params.goals if params.goals is not None else [{"type": "craft_s", "count": 3}]
        if goals:
            for goal in goals:
                goal_count = goal.get("count", 3)
                goal_inner_tiles += goal_count

        # Validate: In strict mode, total tile count (including goal inner tiles) must be divisible by 3
        if has_strict_tile_config:
            # Visual tiles from config (includes goal tiles as 1 visual tile each)
            config_tiles = sum(config.count for config in params.layer_tile_configs)
            # Actual tiles = visual tiles + goal inner tiles
            # Goal tile itself is counted in config_tiles, but it contains inner tiles that need to be added
            # Example: 42 config tiles + 3 inner tiles = 45 actual tiles
            actual_tiles = config_tiles + goal_inner_tiles

            if actual_tiles % 3 != 0:
                raise ValueError(
                    f"실제 타일 수({actual_tiles})가 3의 배수가 아닙니다. "
                    f"(설정 타일 {config_tiles}개 + 골 내부 타일 {goal_inner_tiles}개 = {actual_tiles}개) "
                    f"클리어가 불가능하므로 생성할 수 없습니다. "
                    f"(예: 총 설정 타일을 {config_tiles - (actual_tiles % 3)} 또는 {config_tiles + (3 - actual_tiles % 3)}로 조정)"
                )

        # Create initial level structure
        level = self._create_base_structure(params)

        # Populate layers with tiles based on target difficulty
        level = self._populate_layers(level, params)

        # Add obstacles and attributes
        level = self._add_obstacles(level, params)

        # Add goals (in strict mode, replace existing tiles instead of adding)
        level = self._add_goals(level, params, strict_mode=has_strict_tile_config)

        # Adjust to target difficulty (only if NOT using strict tile config)
        # When user specifies exact tile counts, don't modify them for difficulty
        if not has_strict_tile_config:
            level = self._adjust_difficulty(level, params.target_difficulty)

        # CRITICAL: Ensure tile count is divisible by 3 (only if NOT using strict config)
        # When user specifies exact counts, they are responsible for divisibility
        if not has_strict_tile_config:
            level = self._ensure_tile_count_divisible_by_3(level, params)

        # CRITICAL: Validate obstacles AFTER all tile modifications
        # This ensures all obstacles (chain, link, grass) have valid clearable neighbors
        level = self._validate_and_fix_obstacles(level)

        # Final check: if obstacle removal broke divisibility, fix it again (only if not strict)
        if not has_strict_tile_config:
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

        # Calculate useTileCount from tile_types
        # t0 is random tile, t1~t15 are actual types
        # useTileCount determines how many types t0 can become (t1~t{useTileCount})
        tile_types = params.tile_types or self.DEFAULT_TILE_TYPES
        actual_tile_types = [t for t in tile_types if t != 't0' and t.startswith('t') and t[1:].isdigit()]
        if actual_tile_types:
            # Find the highest tile number used
            max_tile_num = max(int(t[1:]) for t in actual_tile_types)
            use_tile_count = max_tile_num
        else:
            # Only t0, use default
            use_tile_count = 5

        level = {
            "layer": params.max_layers,
            "useTileCount": use_tile_count,
            "randSeed": random.randint(1, 999999),
        }

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
        """Populate layers with tiles based on difficulty and user configuration."""
        target = params.target_difficulty
        cols, rows = params.grid_size

        tile_types = params.tile_types or self.DEFAULT_TILE_TYPES

        # Check if per-layer tile configs are provided (they take priority)
        has_layer_tile_configs = bool(params.layer_tile_configs) and len(params.layer_tile_configs) > 0

        if has_layer_tile_configs:
            # Use ONLY the layers specified in layer_tile_configs
            # This gives full control to the user
            active_layers = sorted(
                [c.layer for c in params.layer_tile_configs],
                reverse=True  # Start from top layer
            )
            active_layer_count = len(active_layers)

            # Build per-layer tile counts from config
            layer_tile_counts: Dict[int, int] = {}
            for config in params.layer_tile_configs:
                layer_tile_counts[config.layer] = config.count

            # Total is sum of configured counts
            total_target = sum(layer_tile_counts.values())
        else:
            # Legacy behavior: determine layers from active_layer_count or difficulty
            if params.active_layer_count is not None:
                active_layer_count = min(params.active_layer_count, params.max_layers)
            else:
                # Default: use all available layers (since user sets maxLayers directly now)
                # Minimum 1 layer, maximum is all layers
                min_active_layers = 1
                max_active_layers = params.max_layers
                active_layer_count = min_active_layers + int(
                    (max_active_layers - min_active_layers) * target
                )
                active_layer_count = max(1, min(active_layer_count, params.max_layers))

            # Start from top layer and work down
            active_layers = list(range(params.max_layers - 1, params.max_layers - 1 - active_layer_count, -1))

            # Calculate total tile count target
            if params.total_tile_count is not None:
                total_target = (params.total_tile_count // 3) * 3
                if total_target < 9:
                    total_target = 9
            else:
                max_tiles_per_layer = (cols + 1) * (rows + 1)
                base_tiles = int(max_tiles_per_layer * active_layer_count * (0.3 + target * 0.4))
                total_target = (base_tiles // 3) * 3
                if total_target < 9:
                    total_target = 9

            # Build per-layer tile counts - distribute evenly
            layer_tile_counts = {}
            tiles_per_layer = total_target // len(active_layers)
            extra_tiles = total_target % len(active_layers)

            for i, layer_idx in enumerate(active_layers):
                layer_tile_counts[layer_idx] = tiles_per_layer + (1 if i < extra_tiles else 0)

        # Collect all positions across all layers
        all_layer_positions: List[Tuple[int, str]] = []  # (layer_idx, pos)

        for layer_idx in active_layers:
            layer_key = f"layer_{layer_idx}"
            is_odd_layer = layer_idx % 2 == 1

            # Calculate layer dimensions
            layer_cols = cols if is_odd_layer else cols + 1
            layer_rows = rows if is_odd_layer else rows + 1

            # Get target tile count for this layer
            target_count = layer_tile_counts.get(layer_idx, 0)
            if target_count <= 0:
                continue

            # Generate positions for this layer
            positions = self._generate_layer_positions_for_count(
                layer_cols, layer_rows, target_count
            )

            for pos in positions:
                all_layer_positions.append((layer_idx, pos))

        # CRITICAL: Distribute tile types ensuring each type has count divisible by 3
        # Calculate how many tiles of each type we need
        total_positions = len(all_layer_positions)
        num_tile_types = len(tile_types)

        # Each type should get roughly equal share, but must be divisible by 3
        tiles_per_type = (total_positions // num_tile_types // 3) * 3
        if tiles_per_type < 3:
            tiles_per_type = 3

        # Create a list of tile types to assign (each type appears in multiples of 3)
        tile_assignments = []
        for tile_type in tile_types:
            tile_assignments.extend([tile_type] * tiles_per_type)

        # If we have more positions than assignments, add more tiles (in groups of 3)
        while len(tile_assignments) < len(all_layer_positions):
            tile_type = random.choice(tile_types)
            tile_assignments.extend([tile_type] * 3)

        # If we have more assignments than positions, trim excess positions
        # and ensure remaining is still divisible by 3 per type
        if len(tile_assignments) > len(all_layer_positions):
            # Trim positions to match tile assignments
            all_layer_positions = all_layer_positions[:len(tile_assignments)]

        # Or trim tile_assignments to match positions (keeping multiples of 3)
        while len(tile_assignments) > len(all_layer_positions):
            # Remove 3 tiles of a random type
            tile_type = random.choice(tile_types)
            count = 0
            new_assignments = []
            for t in tile_assignments:
                if t == tile_type and count < 3:
                    count += 1
                    continue
                new_assignments.append(t)
            if count == 3:
                tile_assignments = new_assignments
            else:
                # Couldn't remove 3 of this type, try shuffling
                break

        # Shuffle assignments for random distribution
        random.shuffle(tile_assignments)

        # Initialize tiles dict for each layer
        for layer_idx in active_layers:
            level[f"layer_{layer_idx}"]["tiles"] = {}

        # Assign tiles to positions
        for i, (layer_idx, pos) in enumerate(all_layer_positions):
            if i < len(tile_assignments):
                tile_type = tile_assignments[i]
            else:
                # Fallback (shouldn't happen)
                tile_type = random.choice(tile_types)

            layer_key = f"layer_{layer_idx}"
            level[layer_key]["tiles"][pos] = [tile_type, ""]

        # Update tile counts
        for layer_idx in active_layers:
            layer_key = f"layer_{layer_idx}"
            level[layer_key]["num"] = str(len(level[layer_key]["tiles"]))

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

    def _generate_layer_positions_for_count(
        self, cols: int, rows: int, target_count: int
    ) -> List[str]:
        """Generate tile positions for a layer with specific count."""
        all_positions = []
        for x in range(cols):
            for y in range(rows):
                all_positions.append(f"{x}_{y}")

        # Clamp to available positions
        actual_count = min(target_count, len(all_positions))
        if actual_count <= 0:
            return []

        selected = random.sample(all_positions, actual_count)
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

        # Check if per-layer obstacle configs are provided (they take priority)
        has_layer_obstacle_configs = bool(params.layer_obstacle_configs)

        # Helper to get target count for an obstacle type (global)
        # Only used when per-layer configs are NOT provided
        def get_global_target(obstacle_type: str, default_ratio: float) -> int:
            if has_layer_obstacle_configs:
                # Per-layer configs take priority, don't use global targets for distribution
                return 0
            if params.obstacle_counts and obstacle_type in params.obstacle_counts:
                config = params.obstacle_counts[obstacle_type]
                min_count = config.get("min", 0)
                max_count = config.get("max", 10)
                return random.randint(min_count, max_count)
            # Legacy behavior: scale with difficulty
            return int(total_tiles * target * default_ratio)

        # Helper to get per-layer obstacle target
        def get_layer_target(layer_idx: int, obstacle_type: str) -> Optional[int]:
            config = params.get_layer_obstacle_config(layer_idx, obstacle_type)
            if config is not None:
                min_count, max_count = config
                return random.randint(min_count, max_count)
            return None

        # All supported obstacle types
        ALL_OBSTACLE_TYPES = ["chain", "frog", "link", "grass", "ice", "bomb", "curtain", "teleport", "crate"]

        # Build per-layer obstacle targets
        layer_targets: Dict[int, Dict[str, int]] = {}
        configured_totals: Dict[str, int] = {obs: 0 for obs in ALL_OBSTACLE_TYPES}

        for i in range(num_layers):
            layer_targets[i] = {}
            for obs_type in ALL_OBSTACLE_TYPES:
                layer_target = get_layer_target(i, obs_type)
                if layer_target is not None:
                    layer_targets[i][obs_type] = layer_target
                    configured_totals[obs_type] += layer_target

        # Get global targets (use configured values or calculate from difficulty)
        # These are only used when per-layer configs are NOT provided
        global_targets = {
            "chain": get_global_target("chain", 0.15),
            "frog": get_global_target("frog", 0.08),
            "link": get_global_target("link", 0.05),
            "grass": get_global_target("grass", 0.10),
            "ice": get_global_target("ice", 0.12),
            "bomb": get_global_target("bomb", 0.05),
            "curtain": get_global_target("curtain", 0.08),
            "teleport": get_global_target("teleport", 0.04),
            "crate": get_global_target("crate", 0.06),
        }

        # Distribute remaining to unconfigured layers
        # Only if per-layer configs are NOT provided
        if not has_layer_obstacle_configs:
            unconfigured_layers = []
            for i in range(num_layers):
                layer_key = f"layer_{i}"
                if level.get(layer_key, {}).get("tiles", {}):
                    unconfigured_layers.append(i)

            for obs_type in ALL_OBSTACLE_TYPES:
                remaining = max(0, global_targets[obs_type] - configured_totals[obs_type])
                if remaining > 0 and unconfigured_layers:
                    # Distribute remaining to layers without specific config
                    layers_needing = [
                        l for l in unconfigured_layers
                        if obs_type not in layer_targets.get(l, {})
                    ]
                    if layers_needing:
                        per_layer = remaining // len(layers_needing)
                        extra = remaining % len(layers_needing)
                        for idx, layer_idx in enumerate(layers_needing):
                            if layer_idx not in layer_targets:
                                layer_targets[layer_idx] = {}
                            layer_targets[layer_idx][obs_type] = per_layer + (1 if idx < extra else 0)

        obstacles_added = {obs: 0 for obs in ALL_OBSTACLE_TYPES}

        # Add obstacles per layer
        for layer_idx in range(num_layers):
            targets = layer_targets.get(layer_idx, {})

            # Add frog obstacles (no special rules)
            if "frog" in obstacle_types:
                frog_target = targets.get("frog", 0)
                if frog_target > 0:
                    level = self._add_frog_obstacles_to_layer(
                        level, layer_idx, frog_target, obstacles_added
                    )

            # Add chain obstacles (must have clearable LEFT or RIGHT neighbor)
            if "chain" in obstacle_types:
                chain_target = targets.get("chain", 0)
                if chain_target > 0:
                    level = self._add_chain_obstacles_to_layer(
                        level, layer_idx, chain_target, obstacles_added
                    )

            # Add link obstacles (must create valid pairs with clearable neighbor)
            if "link" in obstacle_types:
                link_target = targets.get("link", 0)
                if link_target > 0:
                    level = self._add_link_obstacles_to_layer(
                        level, layer_idx, link_target, obstacles_added
                    )

            # Add grass obstacles (must have at least 2 clearable neighbors)
            if "grass" in obstacle_types:
                grass_target = targets.get("grass", 0)
                if grass_target > 0:
                    level = self._add_grass_obstacles_to_layer(
                        level, layer_idx, grass_target, obstacles_added
                    )

            # Add ice obstacles (covers tile, must be cleared by adjacent matches)
            if "ice" in obstacle_types:
                ice_target = targets.get("ice", 0)
                if ice_target > 0:
                    level = self._add_ice_obstacles_to_layer(
                        level, layer_idx, ice_target, obstacles_added
                    )

            # Add bomb obstacles (countdown bomb)
            if "bomb" in obstacle_types:
                bomb_target = targets.get("bomb", 0)
                if bomb_target > 0:
                    level = self._add_bomb_obstacles_to_layer(
                        level, layer_idx, bomb_target, obstacles_added
                    )

            # Add curtain obstacles (hides tile until adjacent match)
            if "curtain" in obstacle_types:
                curtain_target = targets.get("curtain", 0)
                if curtain_target > 0:
                    level = self._add_curtain_obstacles_to_layer(
                        level, layer_idx, curtain_target, obstacles_added
                    )

            # Add teleport obstacles (paired teleport tiles)
            if "teleport" in obstacle_types:
                teleport_target = targets.get("teleport", 0)
                if teleport_target > 0:
                    level = self._add_teleport_obstacles_to_layer(
                        level, layer_idx, teleport_target, obstacles_added
                    )

            # Add crate obstacles (must be matched to break)
            if "crate" in obstacle_types:
                crate_target = targets.get("crate", 0)
                if crate_target > 0:
                    level = self._add_crate_obstacles_to_layer(
                        level, layer_idx, crate_target, obstacles_added
                    )

        return level

    def _add_frog_obstacles_to_layer(
        self, level: Dict[str, Any], layer_idx: int, target: int, counter: Dict[str, int]
    ) -> Dict[str, Any]:
        """Add frog obstacles to a specific layer (no special placement rules)."""
        layer_key = f"layer_{layer_idx}"
        tiles = level.get(layer_key, {}).get("tiles", {})
        added = 0

        positions = list(tiles.keys())
        random.shuffle(positions)

        for pos in positions:
            if added >= target:
                break

            tile_data = tiles[pos]
            if not isinstance(tile_data, list) or len(tile_data) < 2:
                continue

            # Skip goal tiles and tiles with attributes
            if tile_data[0] in self.GOAL_TYPES or tile_data[1]:
                continue

            tile_data[1] = "frog"
            added += 1
            counter["frog"] += 1

        return level

    def _add_chain_obstacles_to_layer(
        self, level: Dict[str, Any], layer_idx: int, target: int, counter: Dict[str, int]
    ) -> Dict[str, Any]:
        """Add chain obstacles to a specific layer (must have clearable LEFT/RIGHT neighbor)."""
        layer_key = f"layer_{layer_idx}"
        tiles = level.get(layer_key, {}).get("tiles", {})
        if not tiles:
            return level

        added = 0
        attempts = 0
        max_attempts = target * 10

        positions = list(tiles.keys())

        while added < target and attempts < max_attempts:
            attempts += 1

            pos = random.choice(positions)
            tile_data = tiles[pos]

            if not isinstance(tile_data, list) or len(tile_data) < 2:
                continue
            if tile_data[0] in self.GOAL_TYPES or tile_data[1]:
                continue

            try:
                # Position format is "col_row" (x_y)
                col, row = map(int, pos.split('_'))
            except:
                continue

            # Chain only checks LEFT and RIGHT neighbors (col±1 = left/right on screen)
            neighbors = [
                (col-1, row),  # Left (on screen)
                (col+1, row),  # Right (on screen)
            ]

            valid_chain = False
            for ncol, nrow in neighbors:
                npos = f"{ncol}_{nrow}"
                if npos not in tiles:
                    continue
                ndata = tiles[npos]
                if not isinstance(ndata, list) or len(ndata) < 2:
                    continue
                if ndata[0] in self.GOAL_TYPES:
                    continue
                # Neighbor must be clearable (no obstacle or frog only)
                if ndata[1] and ndata[1] != "frog":
                    continue
                valid_chain = True
                break

            if valid_chain:
                tile_data[1] = "chain"
                added += 1
                counter["chain"] += 1

        return level

    def _add_link_obstacles_to_layer(
        self, level: Dict[str, Any], layer_idx: int, target: int, counter: Dict[str, int]
    ) -> Dict[str, Any]:
        """Add link obstacles to a specific layer.

        Link tiles point to a direction and MUST have a tile in that direction.
        IMPORTANT: Only ONE tile in a linked pair should have the link attribute.
        The target tile must NOT have any attribute (including other links).
        A tile that is already a link target CANNOT be targeted by another link.

        Position format is "col_row" (x_y).
        - link_n: points north (up), tile must exist at row-1 (y-1)
        - link_s: points south (down), tile must exist at row+1 (y+1)
        - link_w: points west (left), tile must exist at col-1 (x-1)
        - link_e: points east (right), tile must exist at col+1 (x+1)
        """
        layer_key = f"layer_{layer_idx}"
        tiles = level.get(layer_key, {}).get("tiles", {})
        if not tiles:
            return level

        added = 0
        attempts = 0
        max_attempts = target * 15

        positions = list(tiles.keys())

        # Track positions that are already link targets
        # This prevents multiple links pointing to the same tile
        linked_targets: set = set()

        # Also collect existing link targets from tiles that already have link attributes
        for pos, tile_data in tiles.items():
            if isinstance(tile_data, list) and len(tile_data) >= 2 and tile_data[1]:
                attr = tile_data[1]
                if attr.startswith("link_"):
                    try:
                        col, row = map(int, pos.split('_'))
                        # Calculate target position based on link direction
                        if attr == "link_n":
                            linked_targets.add(f"{col}_{row - 1}")
                        elif attr == "link_s":
                            linked_targets.add(f"{col}_{row + 1}")
                        elif attr == "link_w":
                            linked_targets.add(f"{col - 1}_{row}")
                        elif attr == "link_e":
                            linked_targets.add(f"{col + 1}_{row}")
                    except:
                        pass

        while added < target and attempts < max_attempts:
            attempts += 1

            pos = random.choice(positions)
            tile_data = tiles[pos]

            if not isinstance(tile_data, list) or len(tile_data) < 2:
                continue
            if tile_data[0] in self.GOAL_TYPES or tile_data[1]:
                continue

            # Source tile must not be a link target already
            if pos in linked_targets:
                continue

            try:
                # Position format is "col_row" (x_y)
                col, row = map(int, pos.split('_'))
            except:
                continue

            # Direction mapping: link type -> target position
            # Position format: f"{col}_{row}"
            # link_n points north (up), so row-1
            # link_s points south (down), so row+1
            # link_w points west (left), so col-1
            # link_e points east (right), so col+1
            directions = [
                ("link_n", col, row - 1),  # North (up)
                ("link_s", col, row + 1),  # South (down)
                ("link_w", col - 1, row),  # West (left)
                ("link_e", col + 1, row),  # East (right)
            ]
            random.shuffle(directions)

            for link_type, target_col, target_row in directions:
                target_pos = f"{target_col}_{target_row}"

                # CRITICAL: The linked direction MUST have a tile
                if target_pos not in tiles:
                    continue

                # CRITICAL: Target must NOT already be a link target
                if target_pos in linked_targets:
                    continue

                target_tile = tiles[target_pos]
                if not isinstance(target_tile, list) or len(target_tile) < 2:
                    continue

                # Target tile must be a valid clearable tile (not a goal)
                if target_tile[0] in self.GOAL_TYPES:
                    continue

                # CRITICAL: Target tile must NOT have any attribute
                # This prevents both tiles in a pair from having link attributes
                # (which would count as 2 links instead of 1)
                if target_tile[1]:
                    continue

                # Valid link found - assign the link type
                tile_data[1] = link_type
                added += 1
                counter["link"] += 1

                # Mark target as linked (cannot be targeted by another link)
                linked_targets.add(target_pos)
                # Also mark source as linked target to prevent it from being targeted
                linked_targets.add(pos)
                break

        return level

    def _add_grass_obstacles_to_layer(
        self, level: Dict[str, Any], layer_idx: int, target: int, counter: Dict[str, int]
    ) -> Dict[str, Any]:
        """Add grass obstacles to a specific layer (must have 2+ clearable neighbors)."""
        layer_key = f"layer_{layer_idx}"
        tiles = level.get(layer_key, {}).get("tiles", {})
        if not tiles:
            return level

        added = 0
        attempts = 0
        max_attempts = target * 10

        positions = list(tiles.keys())

        while added < target and attempts < max_attempts:
            attempts += 1

            pos = random.choice(positions)
            tile_data = tiles[pos]

            if not isinstance(tile_data, list) or len(tile_data) < 2:
                continue
            if tile_data[0] in self.GOAL_TYPES or tile_data[1]:
                continue

            try:
                # Position format is "col_row" (x_y)
                col, row = map(int, pos.split('_'))
            except:
                continue

            # Grass checks all 4 directions
            neighbors = [
                (col, row-1),  # Up
                (col, row+1),  # Down
                (col-1, row),  # Left
                (col+1, row),  # Right
            ]

            clearable_count = 0
            for ncol, nrow in neighbors:
                npos = f"{ncol}_{nrow}"
                if npos in tiles:
                    ndata = tiles[npos]
                    if (isinstance(ndata, list) and len(ndata) >= 2 and
                        (not ndata[1] or ndata[1] == "frog") and
                        ndata[0] not in self.GOAL_TYPES):
                        clearable_count += 1

            # Must have at least 2 clearable neighbors
            if clearable_count >= 2:
                tile_data[1] = "grass"
                added += 1
                counter["grass"] += 1

        return level

    def _add_ice_obstacles_to_layer(
        self, level: Dict[str, Any], layer_idx: int, target: int, counter: Dict[str, int]
    ) -> Dict[str, Any]:
        """Add ice obstacles to a specific layer.
        Ice covers tiles and must be cleared by adjacent matches.
        Can have 1-3 layers of ice (ice_1, ice_2, ice_3).
        """
        layer_key = f"layer_{layer_idx}"
        tiles = level.get(layer_key, {}).get("tiles", {})
        if not tiles:
            return level

        added = 0
        positions = list(tiles.keys())
        random.shuffle(positions)

        for pos in positions:
            if added >= target:
                break

            tile_data = tiles[pos]
            if not isinstance(tile_data, list) or len(tile_data) < 2:
                continue

            # Skip goal tiles and tiles with attributes
            if tile_data[0] in self.GOAL_TYPES or tile_data[1]:
                continue

            # Random ice level (1-3), weighted toward lower levels
            ice_level = random.choices([1, 2, 3], weights=[0.5, 0.35, 0.15])[0]
            tile_data[1] = f"ice_{ice_level}"
            added += 1
            counter["ice"] += 1

        return level

    def _add_bomb_obstacles_to_layer(
        self, level: Dict[str, Any], layer_idx: int, target: int, counter: Dict[str, int]
    ) -> Dict[str, Any]:
        """Add bomb obstacles to a specific layer.
        Bombs have a countdown and explode if not cleared in time.
        """
        layer_key = f"layer_{layer_idx}"
        tiles = level.get(layer_key, {}).get("tiles", {})
        if not tiles:
            return level

        added = 0
        positions = list(tiles.keys())
        random.shuffle(positions)

        for pos in positions:
            if added >= target:
                break

            tile_data = tiles[pos]
            if not isinstance(tile_data, list) or len(tile_data) < 2:
                continue

            # Skip goal tiles and tiles with attributes
            if tile_data[0] in self.GOAL_TYPES or tile_data[1]:
                continue

            # Set bomb with countdown (stored in extra field)
            countdown = random.randint(5, 10)
            tile_data[1] = "bomb"
            if len(tile_data) < 3:
                tile_data.append([countdown])
            else:
                tile_data[2] = [countdown]
            added += 1
            counter["bomb"] += 1

        return level

    def _add_curtain_obstacles_to_layer(
        self, level: Dict[str, Any], layer_idx: int, target: int, counter: Dict[str, int]
    ) -> Dict[str, Any]:
        """Add curtain obstacles to a specific layer.
        Curtain hides the tile underneath until an adjacent match is made.
        """
        layer_key = f"layer_{layer_idx}"
        tiles = level.get(layer_key, {}).get("tiles", {})
        if not tiles:
            return level

        added = 0
        attempts = 0
        max_attempts = target * 10

        positions = list(tiles.keys())

        while added < target and attempts < max_attempts:
            attempts += 1

            pos = random.choice(positions)
            tile_data = tiles[pos]

            if not isinstance(tile_data, list) or len(tile_data) < 2:
                continue
            if tile_data[0] in self.GOAL_TYPES or tile_data[1]:
                continue

            try:
                # Position format is "col_row" (x_y)
                col, row = map(int, pos.split('_'))
            except:
                continue

            # Curtain needs at least one adjacent tile to be cleared
            neighbors = [
                (col, row-1), (col, row+1),
                (col-1, row), (col+1, row),
            ]

            has_neighbor = False
            for ncol, nrow in neighbors:
                npos = f"{ncol}_{nrow}"
                if npos in tiles:
                    ndata = tiles[npos]
                    if (isinstance(ndata, list) and len(ndata) >= 2 and
                        ndata[0] not in self.GOAL_TYPES):
                        has_neighbor = True
                        break

            if has_neighbor:
                tile_data[1] = "curtain_close"
                added += 1
                counter["curtain"] += 1

        return level

    def _add_teleport_obstacles_to_layer(
        self, level: Dict[str, Any], layer_idx: int, target: int, counter: Dict[str, int]
    ) -> Dict[str, Any]:
        """Add teleport obstacles to a specific layer.
        Teleports work in pairs - clearing one affects the paired teleport.
        """
        layer_key = f"layer_{layer_idx}"
        tiles = level.get(layer_key, {}).get("tiles", {})
        if not tiles:
            return level

        # Need at least 2 tiles for a teleport pair
        if len(tiles) < 2:
            return level

        added = 0
        # Teleports are added in pairs
        pairs_to_add = target // 2
        if pairs_to_add == 0 and target > 0:
            pairs_to_add = 1

        available_positions = [
            pos for pos, data in tiles.items()
            if isinstance(data, list) and len(data) >= 2 and
            data[0] not in self.GOAL_TYPES and not data[1]
        ]
        random.shuffle(available_positions)

        pair_id = 0
        for i in range(0, len(available_positions) - 1, 2):
            if pair_id >= pairs_to_add:
                break

            pos1 = available_positions[i]
            pos2 = available_positions[i + 1]

            # Set teleport with pair ID
            tiles[pos1][1] = "teleport"
            if len(tiles[pos1]) < 3:
                tiles[pos1].append([pair_id])
            else:
                tiles[pos1][2] = [pair_id]

            tiles[pos2][1] = "teleport"
            if len(tiles[pos2]) < 3:
                tiles[pos2].append([pair_id])
            else:
                tiles[pos2][2] = [pair_id]

            added += 2
            counter["teleport"] += 2
            pair_id += 1

        return level

    def _add_crate_obstacles_to_layer(
        self, level: Dict[str, Any], layer_idx: int, target: int, counter: Dict[str, int]
    ) -> Dict[str, Any]:
        """Add crate obstacles to a specific layer.
        Crates block tiles and must be broken by matches.
        """
        layer_key = f"layer_{layer_idx}"
        tiles = level.get(layer_key, {}).get("tiles", {})
        if not tiles:
            return level

        added = 0
        attempts = 0
        max_attempts = target * 10

        positions = list(tiles.keys())

        while added < target and attempts < max_attempts:
            attempts += 1

            pos = random.choice(positions)
            tile_data = tiles[pos]

            if not isinstance(tile_data, list) or len(tile_data) < 2:
                continue
            if tile_data[0] in self.GOAL_TYPES or tile_data[1]:
                continue

            try:
                # Position format is "col_row" (x_y)
                col, row = map(int, pos.split('_'))
            except:
                continue

            # Crate needs at least one clearable neighbor
            neighbors = [
                (col, row-1), (col, row+1),
                (col-1, row), (col+1, row),
            ]

            has_clearable = False
            for ncol, nrow in neighbors:
                npos = f"{ncol}_{nrow}"
                if npos in tiles:
                    ndata = tiles[npos]
                    if (isinstance(ndata, list) and len(ndata) >= 2 and
                        (not ndata[1] or ndata[1] == "frog") and
                        ndata[0] not in self.GOAL_TYPES):
                        has_clearable = True
                        break

            if has_clearable:
                tile_data[1] = "crate"
                added += 1
                counter["crate"] += 1

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

            # Parse position (format is col_row = x_y)
            try:
                col, row = map(int, pos.split('_'))
            except:
                continue

            # Chain only checks LEFT and RIGHT neighbors (col±1 = left/right on screen)
            neighbors = [
                (col-1, row),  # Left (on screen)
                (col+1, row),  # Right (on screen)
            ]

            valid_chain = False
            for ncol, nrow in neighbors:
                neighbor_pos = f"{ncol}_{nrow}"
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
                # Position format is "col_row" (x_y)
                col, row = map(int, pos.split('_'))
            except:
                continue

            # Grass checks all 4 directions
            neighbors = [
                (col, row-1),  # Up
                (col, row+1),  # Down
                (col-1, row),  # Left
                (col+1, row),  # Right
            ]

            clearable_count = 0
            for ncol, nrow in neighbors:
                npos = f"{ncol}_{nrow}"
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
        2. ONLY ONE tile in a linked pair has the link attribute (not both).
        3. The target tile must NOT have any attribute.
        4. A tile that is already a link target CANNOT be targeted by another link.

        Position format is "col_row" (x_y).
        """
        num_layers = level.get("layer", 8)

        # Collect all tiles by layer
        layer_tiles = {}
        for i in range(num_layers):
            layer_key = f"layer_{i}"
            tiles = level.get(layer_key, {}).get("tiles", {})
            if tiles:
                layer_tiles[i] = tiles

        # Track positions that are already link targets (per layer)
        # This prevents multiple links pointing to the same tile
        linked_targets_per_layer: Dict[int, set] = {i: set() for i in layer_tiles.keys()}

        # Collect existing link targets from tiles that already have link attributes
        for layer_idx, tiles in layer_tiles.items():
            for pos, tile_data in tiles.items():
                if isinstance(tile_data, list) and len(tile_data) >= 2 and tile_data[1]:
                    attr = tile_data[1]
                    if attr.startswith("link_"):
                        try:
                            col, row = map(int, pos.split('_'))
                            # Calculate target position based on link direction
                            if attr == "link_n":
                                linked_targets_per_layer[layer_idx].add(f"{col}_{row - 1}")
                            elif attr == "link_s":
                                linked_targets_per_layer[layer_idx].add(f"{col}_{row + 1}")
                            elif attr == "link_w":
                                linked_targets_per_layer[layer_idx].add(f"{col - 1}_{row}")
                            elif attr == "link_e":
                                linked_targets_per_layer[layer_idx].add(f"{col + 1}_{row}")
                            # Also add source position as it's part of a link pair
                            linked_targets_per_layer[layer_idx].add(pos)
                        except:
                            pass

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
            linked_targets = linked_targets_per_layer[layer_idx]

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

            # Source tile must not be a link target already
            if pos1 in linked_targets:
                continue

            # Parse position (format is col_row = x_y)
            try:
                col1, row1 = map(int, pos1.split('_'))
            except:
                continue

            # Try to find a valid partner in one of 4 directions
            directions = [
                ("link_n", col1, row1 - 1),  # North (up = row-1)
                ("link_s", col1, row1 + 1),  # South (down = row+1)
                ("link_w", col1 - 1, row1),  # West (left = col-1)
                ("link_e", col1 + 1, row1),  # East (right = col+1)
            ]
            random.shuffle(directions)

            valid_link = False
            for link_type, col2, row2 in directions:
                pos2 = f"{col2}_{row2}"

                # RULE 1: Partner tile MUST exist
                if pos2 not in tiles:
                    continue

                # CRITICAL: Target must NOT already be a link target
                if pos2 in linked_targets:
                    continue

                tile_data2 = tiles[pos2]
                if not isinstance(tile_data2, list) or len(tile_data2) < 2:
                    continue

                # Skip goal tiles
                if tile_data2[0] in self.GOAL_TYPES:
                    continue

                # CRITICAL: Target tile must NOT have any attribute
                # This ensures only one tile in the pair has link attribute
                if tile_data2[1]:
                    continue

                # Valid link found - assign the link type to ONLY the source tile
                tile_data1[1] = link_type
                counter["link"] += 1  # Count as 1 link (not 2)

                # Mark both source and target as linked (cannot be targeted by another link)
                linked_targets.add(pos1)
                linked_targets.add(pos2)
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
        self, level: Dict[str, Any], params: GenerationParams, strict_mode: bool = False
    ) -> Dict[str, Any]:
        """Add goal tiles to the level.

        In strict mode (when layer_tile_configs is specified), goal tiles REPLACE
        existing tiles rather than being added, to maintain exact tile counts.

        Direction rules for goals:
        - craft_s / stack_s: outputs tiles downward (row+1), cannot be at bottom row
        - craft_n / stack_n: outputs tiles upward (row-1), cannot be at top row
        - craft_e / stack_e: outputs tiles rightward (col+1), cannot be at rightmost column
        - craft_w / stack_w: outputs tiles leftward (col-1), cannot be at leftmost column

        Stack additional rule: output position must not overlap with existing tiles
        """
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

        def get_output_direction(goal_type: str) -> tuple:
            """Get output direction offset (col_offset, row_offset) for goal type."""
            direction = goal_type[-1] if goal_type else 's'
            if direction == 's':
                return (0, 1)   # output downward
            elif direction == 'n':
                return (0, -1)  # output upward
            elif direction == 'e':
                return (1, 0)   # output rightward
            elif direction == 'w':
                return (-1, 0)  # output leftward
            return (0, 1)  # default: south

        def is_valid_goal_position(col: int, row: int, goal_type: str) -> bool:
            """Check if position is valid for goal considering output direction."""
            col_off, row_off = get_output_direction(goal_type)
            output_col = col + col_off
            output_row = row + row_off

            # Check output position is within bounds
            if output_col < 0 or output_col >= cols:
                return False
            if output_row < 0 or output_row >= rows:
                return False

            # For stack goals, output position must not overlap with existing tiles
            if goal_type.startswith("stack"):
                output_pos = f"{output_col}_{output_row}"
                if output_pos in tiles:
                    return False

            return True

        def get_preferred_row_for_direction(goal_type: str) -> int:
            """Get preferred starting row based on goal direction."""
            direction = goal_type[-1] if goal_type else 's'
            if direction == 's':
                # South: prefer upper rows (not bottom row)
                return 0
            elif direction == 'n':
                # North: prefer lower rows (not top row)
                return rows - 1
            else:
                # East/West: prefer bottom row
                return rows - 1

        def get_row_search_order(goal_type: str) -> range:
            """Get row search order based on goal direction."""
            direction = goal_type[-1] if goal_type else 's'
            if direction == 's':
                # South: search from top to bottom-1
                return range(0, rows - 1)
            elif direction == 'n':
                # North: search from bottom to top+1
                return range(rows - 1, 0, -1)
            else:
                # East/West: search from bottom to top
                return range(rows - 1, -1, -1)

        # In strict mode, goals are ADDED (not replacing existing tiles)
        # Goal tiles contain inner tiles, so:
        # - Visual tiles = config tiles + num_goals
        # - Actual tiles = config tiles + goal_inner_tiles
        # Example: 21+21 config + craft(3) = 42 visual + 1 goal = 43 visual, 42 + 3 = 45 actual

        # Find available positions for goals (positions not already occupied)
        center_col = cols // 2
        placed_positions = set()  # Track positions used by goals (including output positions)

        for i, goal in enumerate(goals):
            goal_type = goal.get("type", "craft_s")
            goal_count = goal.get("count", 3)

            # Calculate preferred column near center
            target_col = center_col - len(goals) // 2 + i
            target_col = max(0, min(cols - 1, target_col))

            # Find valid position considering direction rules
            pos = None
            row_order = get_row_search_order(goal_type)

            # Try target column first, then expand search
            for try_row in row_order:
                # Search columns in spiral order from target
                for col_offset in range(cols):
                    for direction in ([0] if col_offset == 0 else [-1, 1]):
                        try_col = target_col + col_offset * direction
                        if try_col < 0 or try_col >= cols:
                            continue

                        try_pos = f"{try_col}_{try_row}"

                        # Check if position is not occupied and not already used
                        if try_pos in tiles or try_pos in placed_positions:
                            continue

                        # Check if this position is valid for the goal direction
                        if not is_valid_goal_position(try_col, try_row, goal_type):
                            continue

                        # For stack, also check output position is not in placed_positions
                        if goal_type.startswith("stack"):
                            col_off, row_off = get_output_direction(goal_type)
                            output_pos = f"{try_col + col_off}_{try_row + row_off}"
                            if output_pos in placed_positions:
                                continue

                        pos = try_pos
                        break
                    if pos:
                        break
                if pos:
                    break

            if pos:
                placed_positions.add(pos)
                # For stack, also reserve output position
                if goal_type.startswith("stack"):
                    col_off, row_off = get_output_direction(goal_type)
                    p_col, p_row = map(int, pos.split("_"))
                    output_pos = f"{p_col + col_off}_{p_row + row_off}"
                    placed_positions.add(output_pos)

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

        Note: Obstacle and goal modifications are removed to respect
        user-specified settings. Difficulty is adjusted primarily through
        tile count changes only.
        """
        # Only use tile modifications - goal count should respect user's settings
        return self._add_tile_to_layer(level)

    def _decrease_difficulty(self, level: Dict[str, Any]) -> Dict[str, Any]:
        """Apply a random modification to decrease difficulty.

        Note: Obstacle and goal modifications are removed to respect
        user-specified settings. Difficulty is adjusted primarily through
        tile count changes only.
        """
        # Only use tile modifications - goal count should respect user's settings
        return self._remove_tile_from_layer(level)

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
                    # Position format is "col_row" (x_y)
                    col, row = map(int, pos.split('_'))
                except:
                    continue

                # Only check LEFT (col-1) and RIGHT (col+1) neighbors (on screen)
                neighbors = [
                    (col-1, row),  # Left (on screen)
                    (col+1, row),  # Right (on screen)
                ]

                has_clearable_neighbor = False
                for ncol, nrow in neighbors:
                    npos = f"{ncol}_{nrow}"
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
        """Add a new tile to a random layer that already has tiles.

        Uses tiles that respect the level's useTileCount setting.
        Only adds to layers that already have tiles (respects user's layer config).
        """
        num_layers = level.get("layer", 8)
        use_tile_count = level.get("useTileCount", 5)

        # Build valid tile types based on useTileCount
        # t0 is always valid (random tile), plus t1~t{useTileCount}
        valid_tile_types = ["t0"] + [f"t{i}" for i in range(1, use_tile_count + 1)]

        # Find layers that already have tiles (respect user's layer config)
        active_layer_indices = []
        for i in range(num_layers):
            layer_key = f"layer_{i}"
            if level.get(layer_key, {}).get("tiles", {}):
                active_layer_indices.append(i)

        if not active_layer_indices:
            return level

        # Find a layer with tiles but with available positions
        for _ in range(10):  # Try up to 10 times
            # Only use layers that already have tiles
            layer_idx = random.choice(active_layer_indices)
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
                    tile_type = random.choice(valid_tile_types)
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
                    # Position format is "col_row" (x_y)
                    col, row = map(int, pos.split('_'))
                except:
                    continue

                is_critical_neighbor = False

                # Check if left neighbor (col-1) is chain (on screen)
                left_pos = f"{col-1}_{row}"
                if left_pos in tiles:
                    left_data = tiles[left_pos]
                    if isinstance(left_data, list) and len(left_data) >= 2 and left_data[1] == "chain":
                        # Check if chain has other clearable neighbor (left side = col-2)
                        other_side = f"{col-2}_{row}"
                        if other_side not in tiles:
                            # This tile is the only clearable neighbor for the chain
                            is_critical_neighbor = True

                # Check if right neighbor (col+1) is chain (on screen)
                right_pos = f"{col+1}_{row}"
                if right_pos in tiles:
                    right_data = tiles[right_pos]
                    if isinstance(right_data, list) and len(right_data) >= 2 and right_data[1] == "chain":
                        # Check if chain has other clearable neighbor (right side = col+2)
                        other_side = f"{col+2}_{row}"
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
        Ensure EACH tile type count is divisible by 3 for match-3 completion.

        CRITICAL FIX: Not just total count, but EACH TYPE must be divisible by 3!
        Example: If we have 4x t0, 5x t1, 3x t2 (total 12, divisible by 3)
                 But t0=4 (not divisible), t1=5 (not divisible) -> UNPLAYABLE!

        This function adjusts tile types to ensure each has count divisible by 3.

        Also ensures all tiles are within useTileCount range (t0~t{useTileCount}).
        """
        num_layers = level.get("layer", 8)
        use_tile_count = level.get("useTileCount", 5)

        # Valid tile types based on useTileCount
        # t0 is random tile that becomes t1~t{useTileCount}
        valid_tile_set = {"t0"} | {f"t{i}" for i in range(1, use_tile_count + 1)}
        valid_tile_types = ["t0"] + [f"t{i}" for i in range(1, use_tile_count + 1)]

        # Step 0: Convert out-of-range tiles to valid range
        for i in range(num_layers):
            layer_key = f"layer_{i}"
            tiles = level.get(layer_key, {}).get("tiles", {})
            for pos, tile_data in tiles.items():
                if isinstance(tile_data, list) and len(tile_data) > 0:
                    tile_type = tile_data[0]
                    # Skip goal tiles
                    if tile_type in self.GOAL_TYPES:
                        continue
                    # Check if tile type is out of valid range
                    if tile_type.startswith("t") and tile_type not in valid_tile_set:
                        # Convert to a random valid tile type
                        tile_data[0] = random.choice(valid_tile_types)

        # Step 1: Count each tile type across all layers
        # IMPORTANT: Also count internal tiles in craft/stack containers as t0
        type_counts: Dict[str, int] = {}
        type_positions: Dict[str, List[Tuple[int, str]]] = {}  # type -> [(layer_idx, pos), ...]

        for i in range(num_layers):
            layer_key = f"layer_{i}"
            tiles = level.get(layer_key, {}).get("tiles", {})
            for pos, tile_data in tiles.items():
                if isinstance(tile_data, list) and len(tile_data) > 0:
                    tile_type = tile_data[0]
                    # For craft/stack tiles, count internal tiles as t0
                    if tile_type in self.GOAL_TYPES or tile_type.startswith("stack_"):
                        # [count] = number of internal t0 tiles
                        if len(tile_data) > 2 and isinstance(tile_data[2], list) and tile_data[2]:
                            internal_count = int(tile_data[2][0]) if tile_data[2][0] else 0
                            type_counts["t0"] = type_counts.get("t0", 0) + internal_count
                    else:
                        type_counts[tile_type] = type_counts.get(tile_type, 0) + 1
                        if tile_type not in type_positions:
                            type_positions[tile_type] = []
                        type_positions[tile_type].append((i, pos))

        if not type_counts:
            return level

        # Step 2: Find types that need adjustment
        # Strategy: Reassign tiles from types with remainder to types that need more
        types_needing_add = []  # (type, tiles_needed) - needs 1 or 2 more to reach multiple of 3
        types_with_excess = []  # (type, excess_count, positions) - has 1 or 2 extra

        for tile_type, count in type_counts.items():
            remainder = count % 3
            if remainder == 0:
                continue
            elif remainder == 1:
                # Need 2 more, or remove 1
                types_needing_add.append((tile_type, 2))
            else:  # remainder == 2
                # Need 1 more, or remove 2
                types_needing_add.append((tile_type, 1))

        if not types_needing_add:
            return level

        # Step 3: Find available positions to add tiles
        active_layers = []
        for i in range(num_layers - 1, -1, -1):
            layer_key = f"layer_{i}"
            if level.get(layer_key, {}).get("tiles", {}):
                active_layers.append(i)

        if not active_layers:
            return level

        # Collect available positions across all active layers
        available_positions: List[Tuple[int, str]] = []  # (layer_idx, pos)
        cols, rows = params.grid_size

        for layer_idx in active_layers:
            layer_key = f"layer_{layer_idx}"
            tiles = level[layer_key]["tiles"]
            is_odd_layer = layer_idx % 2 == 1
            layer_cols = cols if is_odd_layer else cols + 1
            layer_rows = rows if is_odd_layer else rows + 1

            all_positions = [f"{x}_{y}" for x in range(layer_cols) for y in range(layer_rows)]
            used_positions = set(tiles.keys())
            for pos in all_positions:
                if pos not in used_positions:
                    available_positions.append((layer_idx, pos))

        # Step 4: Add tiles to reach multiples of 3 for each type
        for tile_type, tiles_needed in types_needing_add:
            for _ in range(tiles_needed):
                if not available_positions:
                    break
                layer_idx, pos = available_positions.pop(0)
                layer_key = f"layer_{layer_idx}"
                level[layer_key]["tiles"][pos] = [tile_type, ""]
                level[layer_key]["num"] = str(len(level[layer_key]["tiles"]))

        # Step 5: Final verification - if still have issues, reassign existing tiles
        # Recount after additions
        type_counts_final: Dict[str, int] = {}
        for i in range(num_layers):
            layer_key = f"layer_{i}"
            tiles = level.get(layer_key, {}).get("tiles", {})
            for pos, tile_data in tiles.items():
                if isinstance(tile_data, list) and len(tile_data) > 0:
                    tile_type = tile_data[0]
                    if tile_type not in self.GOAL_TYPES:
                        type_counts_final[tile_type] = type_counts_final.get(tile_type, 0) + 1

        # Check if any type still has remainder
        still_broken = [(t, c % 3) for t, c in type_counts_final.items() if c % 3 != 0]

        if still_broken:
            # Last resort: reassign tiles between types to balance
            # Find types with excess (remainder 1 or 2) and types that could absorb
            # Change some tiles from one type to another
            for broken_type, remainder in still_broken:
                # Find a type with opposite remainder that can balance
                for other_type, other_count in type_counts_final.items():
                    if other_type == broken_type:
                        continue
                    other_remainder = other_count % 3
                    # If changing tiles can help both
                    # e.g., broken has remainder 1, other has remainder 2
                    # -> move 1 tile from broken to other: broken-1 (rem 0), other+1 (rem 0)
                    if (remainder == 1 and other_remainder == 2) or \
                       (remainder == 2 and other_remainder == 1):
                        # Find a tile of broken_type and change it to other_type
                        tiles_changed = 0
                        tiles_to_change = 1 if remainder == 1 else 2

                        for i in range(num_layers):
                            if tiles_changed >= tiles_to_change:
                                break
                            layer_key = f"layer_{i}"
                            tiles = level.get(layer_key, {}).get("tiles", {})
                            for pos, tile_data in tiles.items():
                                if tiles_changed >= tiles_to_change:
                                    break
                                if isinstance(tile_data, list) and len(tile_data) > 0:
                                    if tile_data[0] == broken_type:
                                        tile_data[0] = other_type
                                        tiles_changed += 1
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

            for pos, tile_data in tiles.items():
                if not isinstance(tile_data, list) or len(tile_data) < 2:
                    continue

                attr = tile_data[1]

                # Validate chain tiles - Chain only checks LEFT and RIGHT (on screen)
                # Position format is "col_row" (x_y)
                if attr == "chain":
                    col, row = map(int, pos.split('_'))
                    # Only LEFT (col-1) and RIGHT (col+1) neighbors on screen
                    neighbors = [
                        (col-1, row),  # Left (on screen)
                        (col+1, row),  # Right (on screen)
                    ]

                    has_clearable_neighbor = False
                    for ncol, nrow in neighbors:
                        npos = f"{ncol}_{nrow}"
                        if npos in tiles:
                            ndata = tiles[npos]
                            # Check if neighbor is clearable (no obstacle or frog only)
                            if (isinstance(ndata, list) and len(ndata) >= 2 and
                                (not ndata[1] or ndata[1] == "frog")):
                                has_clearable_neighbor = True
                                break

                    if not has_clearable_neighbor:
                        invalid_obstacles.append(pos)

                # Validate link tiles - connected direction MUST have a tile
                # Position format is "col_row" (x_y)
                elif attr.startswith("link_"):
                    col, row = map(int, pos.split('_'))

                    # Determine the position that the link points to
                    # link_n points north (up), so there must be a tile at row-1
                    # link_s points south (down), so there must be a tile at row+1
                    # link_w points west (left), so there must be a tile at col-1
                    # link_e points east (right), so there must be a tile at col+1
                    if attr == "link_n":
                        target_pos = f"{col}_{row-1}"
                    elif attr == "link_s":
                        target_pos = f"{col}_{row+1}"
                    elif attr == "link_w":
                        target_pos = f"{col-1}_{row}"
                    elif attr == "link_e":
                        target_pos = f"{col+1}_{row}"
                    else:
                        continue

                    # CRITICAL: The linked direction MUST have a tile
                    valid_link = False
                    if target_pos in tiles:
                        target_data = tiles[target_pos]
                        if isinstance(target_data, list) and len(target_data) >= 2:
                            # Target must not be a goal tile
                            if target_data[0] not in self.GOAL_TYPES:
                                valid_link = True

                    if not valid_link:
                        invalid_obstacles.append(pos)

                # Validate grass tiles - must have at least 2 clearable neighbors in 4 directions
                # Position format is "col_row" (x_y)
                elif attr == "grass" or attr.startswith("grass_"):
                    col, row = map(int, pos.split('_'))
                    neighbors = [
                        (col, row-1),  # Up
                        (col, row+1),  # Down
                        (col-1, row),  # Left
                        (col+1, row),  # Right
                    ]

                    clearable_count = 0
                    for ncol, nrow in neighbors:
                        npos = f"{ncol}_{nrow}"
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
