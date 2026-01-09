"""Level generator engine with difficulty targeting."""
import logging
import random
import time
from typing import Dict, List, Any, Optional, Tuple, Set
from dataclasses import dataclass

logger = logging.getLogger(__name__)

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
    # All goal types - craft and stack with all 4 directions (s=south, n=north, e=east, w=west)
    GOAL_TYPES = [
        "craft_s", "craft_n", "craft_e", "craft_w",
        "stack_s", "stack_n", "stack_e", "stack_w"
    ]

    # Generation parameters
    MAX_ADJUSTMENT_ITERATIONS = 30
    DIFFICULTY_TOLERANCE = 5.0  # ±5 points

    # Maximum useTileCount - user can specify up to 15 tile types
    # Note: More tile types = harder levels (with 7-slot dock)
    MAX_USE_TILE_COUNT = 15

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
                # Handle both dict and GoalConfig objects
                if hasattr(goal, 'count'):
                    goal_count = goal.count
                else:
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
            # Pass max tile count to prevent adding tiles beyond the target
            max_tiles = params.total_tile_count if params.total_tile_count else None
            level = self._adjust_difficulty(level, params.target_difficulty, max_tiles=max_tiles, params=params)

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

        # Auto-calculate max_moves based on total tiles
        level["max_moves"] = self._calculate_max_moves(level)

        generation_time_ms = int((time.time() - start_time) * 1000)

        return GenerationResult(
            level_json=level,
            actual_difficulty=report.score / 100.0,
            grade=report.grade,
            generation_time_ms=generation_time_ms,
        )

    def reshuffle_positions(self, level: Dict[str, Any], params: Optional[GenerationParams] = None) -> Dict[str, Any]:
        """
        Reshuffle tile positions while keeping tile types, gimmicks, and layer structure.

        This method:
        1. Extracts all tile data (type, gimmick, extra) from each layer
        2. Generates new positions using smart placement for gimmick tiles
        3. Places tiles with neighbor-dependent gimmicks (chain, link, grass) first
        4. Ensures these tiles have valid neighbors

        Args:
            level: Existing level JSON to reshuffle
            params: Optional generation params for validation

        Returns:
            New level JSON with reshuffled positions
        """
        import copy
        new_level = copy.deepcopy(level)

        num_layers = new_level.get("layer", 8)

        # Gimmicks that require at least one clearable neighbor
        NEIGHBOR_DEPENDENT_GIMMICKS = {'chain', 'link', 'link_s', 'link_n', 'link_e', 'link_w', 'grass'}

        for layer_idx in range(num_layers):
            layer_key = f"layer_{layer_idx}"
            if layer_key not in new_level:
                continue

            layer_data = new_level[layer_key]
            tiles = layer_data.get("tiles", {})
            if not tiles:
                continue

            # Extract tile data into categories
            goal_tiles = []           # [(tile_type, gimmick, extra), ...]
            gimmick_tiles = []        # Tiles with neighbor-dependent gimmicks
            other_gimmick_tiles = []  # Tiles with other gimmicks (ice, frog, bomb, etc.)
            plain_tiles = []          # Tiles without gimmicks

            for pos, tile_data in tiles.items():
                if not isinstance(tile_data, list):
                    continue
                tile_type = tile_data[0] if len(tile_data) > 0 else "t0"
                gimmick = tile_data[1] if len(tile_data) > 1 else ""
                extra = tile_data[2] if len(tile_data) > 2 else None

                if tile_type.startswith("craft_") or tile_type.startswith("stack_"):
                    goal_tiles.append((tile_type, gimmick, extra))
                elif gimmick and any(gimmick.startswith(g) for g in NEIGHBOR_DEPENDENT_GIMMICKS):
                    gimmick_tiles.append((tile_type, gimmick, extra))
                elif gimmick:
                    other_gimmick_tiles.append((tile_type, gimmick, extra))
                else:
                    plain_tiles.append((tile_type, gimmick, extra))

            # Get grid dimensions from layer
            cols = int(layer_data.get("col", 8))
            rows = int(layer_data.get("row", 8))

            # Helper to get required adjacent positions based on gimmick type
            def get_required_adjacent(pos_str, gimmick_type=""):
                col, row = map(int, pos_str.split("_"))
                adj = []

                # Chain only checks LEFT and RIGHT (horizontal neighbors)
                if gimmick_type == "chain":
                    directions = [(-1, 0), (1, 0)]  # Left, Right only
                # Link checks specific direction
                elif gimmick_type.startswith("link_"):
                    if gimmick_type == "link_n":
                        directions = [(0, -1)]  # North
                    elif gimmick_type == "link_s":
                        directions = [(0, 1)]   # South
                    elif gimmick_type == "link_e":
                        directions = [(1, 0)]   # East
                    elif gimmick_type == "link_w":
                        directions = [(-1, 0)]  # West
                    else:
                        directions = [(-1, 0), (1, 0), (0, -1), (0, 1)]
                else:
                    # Default: all 4 directions
                    directions = [(-1, 0), (1, 0), (0, -1), (0, 1)]

                for dc, dr in directions:
                    nc, nr = col + dc, row + dr
                    if 0 <= nc < cols and 0 <= nr < rows:
                        adj.append(f"{nc}_{nr}")
                return adj

            # Generate all positions and shuffle
            all_positions = [f"{c}_{r}" for c in range(cols) for r in range(rows)]
            random.shuffle(all_positions)

            new_tiles = {}
            used_positions = set()

            # STEP 1: Place plain tiles first (they will be neighbors for gimmick tiles)
            # Place them in a cluster pattern to ensure connectivity
            random.shuffle(plain_tiles)
            for tile_type, gimmick, extra in plain_tiles:
                for pos in all_positions:
                    if pos not in used_positions:
                        used_positions.add(pos)
                        if extra is not None:
                            new_tiles[pos] = [tile_type, gimmick, extra]
                        else:
                            new_tiles[pos] = [tile_type, gimmick]
                        break

            # STEP 2: Place neighbor-dependent gimmick tiles using gimmick-specific neighbor rules
            random.shuffle(gimmick_tiles)
            for tile_type, gimmick, extra in gimmick_tiles:
                placed = False
                # Find a position with valid neighbor for this specific gimmick type
                candidates = []
                for pos in all_positions:
                    if pos in used_positions:
                        continue
                    # Check required adjacent positions for this gimmick type
                    required_adj = get_required_adjacent(pos, gimmick)
                    for adj_pos in required_adj:
                        if adj_pos in new_tiles:
                            adj_tile = new_tiles[adj_pos]
                            # Plain tile = no gimmick attribute, or frog (clearable)
                            if len(adj_tile) >= 2 and (not adj_tile[1] or adj_tile[1] == "frog"):
                                candidates.append(pos)
                                break

                if candidates:
                    random.shuffle(candidates)
                    pos = candidates[0]
                    used_positions.add(pos)
                    if extra is not None:
                        new_tiles[pos] = [tile_type, gimmick, extra]
                    else:
                        new_tiles[pos] = [tile_type, gimmick]
                    placed = True

                # Fallback: place anywhere if no good position found
                if not placed:
                    for pos in all_positions:
                        if pos not in used_positions:
                            used_positions.add(pos)
                            if extra is not None:
                                new_tiles[pos] = [tile_type, gimmick, extra]
                            else:
                                new_tiles[pos] = [tile_type, gimmick]
                            break

            # STEP 3: Place other gimmick tiles (ice, frog, bomb, etc.)
            random.shuffle(other_gimmick_tiles)
            for tile_type, gimmick, extra in other_gimmick_tiles:
                for pos in all_positions:
                    if pos not in used_positions:
                        used_positions.add(pos)
                        if extra is not None:
                            new_tiles[pos] = [tile_type, gimmick, extra]
                        else:
                            new_tiles[pos] = [tile_type, gimmick]
                        break

            # STEP 4: Place goal tiles (respecting direction constraints)
            for tile_type, gimmick, extra in goal_tiles:
                direction = tile_type[-1] if tile_type else 's'
                valid_positions = []

                for pos in all_positions:
                    if pos in used_positions:
                        continue
                    col, row = map(int, pos.split("_"))

                    # Check direction constraints
                    if direction == 's' and row >= rows - 1:
                        continue
                    if direction == 'n' and row <= 0:
                        continue
                    if direction == 'e' and col >= cols - 1:
                        continue
                    if direction == 'w' and col <= 0:
                        continue

                    valid_positions.append(pos)

                if valid_positions:
                    random.shuffle(valid_positions)
                    pos = valid_positions[0]
                    used_positions.add(pos)
                    if extra is not None:
                        new_tiles[pos] = [tile_type, gimmick, extra]
                    else:
                        new_tiles[pos] = [tile_type, gimmick]
                else:
                    # FALLBACK: If no valid position found, place in any available position
                    # This ensures goals are never lost during reshuffle
                    for pos in all_positions:
                        if pos not in used_positions:
                            used_positions.add(pos)
                            if extra is not None:
                                new_tiles[pos] = [tile_type, gimmick, extra]
                            else:
                                new_tiles[pos] = [tile_type, gimmick]
                            break

            # Update layer with new tiles
            layer_data["tiles"] = new_tiles
            layer_data["num"] = str(len(new_tiles))

        # Re-validate obstacles (should preserve most gimmicks now)
        new_level = self._validate_and_fix_obstacles(new_level)

        # Recalculate max_moves
        new_level["max_moves"] = self._calculate_max_moves(new_level)

        # Generate new random seed
        new_level["randSeed"] = random.randint(100000, 999999)

        return new_level

    def _calculate_max_moves(self, level: Dict[str, Any]) -> int:
        """Calculate max_moves based on total tiles in the level.

        Counts all tiles including internal tiles in stack/craft.
        """
        total_tiles = 0
        num_layers = level.get("layer", 8)

        for i in range(num_layers):
            layer_key = f"layer_{i}"
            layer_data = level.get(layer_key, {})
            tiles = layer_data.get("tiles", {})

            for pos, tile_data in tiles.items():
                if isinstance(tile_data, list) and len(tile_data) > 0:
                    tile_type = tile_data[0]
                    # Check for stack/craft tiles
                    if isinstance(tile_type, str) and (tile_type.startswith("stack_") or tile_type.startswith("craft_")):
                        # Get internal tile count from tile_data[2]
                        stack_count = 1
                        if len(tile_data) > 2:
                            extra = tile_data[2]
                            if isinstance(extra, list) and len(extra) > 0:
                                stack_count = int(extra[0]) if extra[0] else 1
                            elif isinstance(extra, dict):
                                stack_count = int(extra.get("totalCount", extra.get("count", 1)))
                            elif isinstance(extra, (int, float)):
                                stack_count = int(extra)
                        total_tiles += stack_count
                    else:
                        # Normal tile
                        total_tiles += 1
                else:
                    total_tiles += 1

        # Return total tiles as max_moves (minimum 30)
        return max(30, total_tiles)

    def _create_base_structure(self, params: GenerationParams) -> Dict[str, Any]:
        """Create the base level structure with empty layers."""
        cols, rows = params.grid_size

        # Calculate useTileCount from tile_types
        # Count ALL tile types including t0
        tile_types = params.tile_types or self.DEFAULT_TILE_TYPES
        # Filter to only valid tile types (t0~t15)
        valid_tile_types = [t for t in tile_types if t.startswith('t') and (t == 't0' or t[1:].isdigit())]
        if valid_tile_types:
            # Use exactly what user specified (count all including t0)
            tile_count = len(valid_tile_types)
            use_tile_count = min(self.MAX_USE_TILE_COUNT, tile_count)
        else:
            # No valid tiles, use default of 5
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

    def _select_layer_pattern_indices(
        self, active_layers: List[int], base_pattern_index: Optional[int] = None
    ) -> Dict[int, int]:
        """Select varied pattern indices for each layer to create geometric diversity.

        Pattern Categories (50 patterns total):
        - 0-9: Basic shapes (rectangle, diamond, oval, cross, donut, etc.)
        - 10-14: Arrow/Direction patterns
        - 15-19: Star/Celestial patterns
        - 20-29: Letter shapes (H, I, L, U, X, Y, Z, S, O, C)
        - 30-39: Advanced geometric (triangles, hourglass, stairs, pyramid, zigzag)
        - 40-44: Frame/Border patterns
        - 45-49: Artistic patterns (butterfly, flower, islands, stripes, honeycomb)

        Strategy: Select patterns from different categories for adjacent layers
        to create visually interesting, non-repetitive geometric compositions.

        Args:
            active_layers: List of layer indices that will be populated
            base_pattern_index: If specified, use as base; otherwise auto-select

        Returns:
            Dict mapping layer_idx -> pattern_index
        """
        # Define pattern categories with complementary aesthetics
        # Each category has patterns that look distinct from each other
        pattern_categories = [
            [0, 1, 2],      # Basic shapes: rectangle, diamond, oval
            [3, 4, 5],      # Structural: cross, donut, chevron
            [10, 11, 12],   # Directional: arrows
            [15, 16, 17],   # Celestial: stars
            [30, 31, 32],   # Geometric: triangles, hourglass
            [40, 41, 42],   # Frames: borders
            [6, 7, 8, 9],   # Misc basic shapes
            [33, 34, 35],   # More advanced geometric
        ]

        # Flatten for random selection if needed
        all_patterns = [p for cat in pattern_categories for p in cat]

        layer_patterns: Dict[int, int] = {}
        used_categories: Set[int] = set()

        # Sort layers to ensure consistent ordering (top to bottom)
        sorted_layers = sorted(active_layers, reverse=True)

        for i, layer_idx in enumerate(sorted_layers):
            if base_pattern_index is not None and i == 0:
                # Use base pattern for first layer
                layer_patterns[layer_idx] = base_pattern_index
                # Find which category this belongs to
                for cat_idx, cat in enumerate(pattern_categories):
                    if base_pattern_index in cat:
                        used_categories.add(cat_idx)
                        break
            else:
                # Select from a different category than recent layers
                available_categories = [
                    cat_idx for cat_idx in range(len(pattern_categories))
                    if cat_idx not in used_categories
                ]

                # If all categories used, reset but avoid immediate repeat
                if not available_categories:
                    used_categories.clear()
                    # Keep the most recent category excluded
                    if i > 0:
                        prev_layer = sorted_layers[i - 1]
                        prev_pattern = layer_patterns.get(prev_layer, 0)
                        for cat_idx, cat in enumerate(pattern_categories):
                            if prev_pattern in cat:
                                used_categories.add(cat_idx)
                                break
                    available_categories = [
                        cat_idx for cat_idx in range(len(pattern_categories))
                        if cat_idx not in used_categories
                    ]

                if available_categories:
                    selected_cat_idx = random.choice(available_categories)
                    selected_pattern = random.choice(pattern_categories[selected_cat_idx])
                    used_categories.add(selected_cat_idx)
                else:
                    # Fallback: random pattern avoiding immediate repeat
                    prev_pattern = layer_patterns.get(sorted_layers[i - 1], -1) if i > 0 else -1
                    candidates = [p for p in all_patterns if p != prev_pattern]
                    selected_pattern = random.choice(candidates) if candidates else random.choice(all_patterns)

                layer_patterns[layer_idx] = selected_pattern

        return layer_patterns

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
            # Determine layers from active_layer_count or calculate based on difficulty
            if params.active_layer_count is not None:
                active_layer_count = min(params.active_layer_count, params.max_layers)
            else:
                # Tile Buster style layer count based on difficulty:
                # - S grade (0-0.2): 2-3 layers (tutorial, simple)
                # - A grade (0.2-0.4): 3-4 layers (easy-medium)
                # - B grade (0.4-0.6): 4-5 layers (medium)
                # - C grade (0.6-0.8): 5-6 layers (hard)
                # - D grade (0.8-1.0): 6-8 layers (very hard)
                min_layers = max(1, params.min_layers)
                max_layers = params.max_layers

                # Tutorial mode: For very low difficulty (≤0.15), use 2-3 layers
                is_tutorial_mode = target <= 0.15
                if is_tutorial_mode:
                    max_layers = min(max_layers, 3)
                    min_layers = min(min_layers, 2)
                elif target < 0.4:
                    # A grade: 3-4 layers
                    min_layers = max(min_layers, 3)
                    max_layers = min(max_layers, 4)
                elif target < 0.6:
                    # B grade: 4-5 layers
                    min_layers = max(min_layers, 4)
                    max_layers = min(max_layers, 5)
                elif target < 0.8:
                    # C grade: 5-6 layers
                    min_layers = max(min_layers, 5)
                    max_layers = min(max_layers, 6)
                else:
                    # D grade: 6-8 layers (use full range)
                    min_layers = max(min_layers, 6)

                # Ensure min <= max
                if min_layers > max_layers:
                    min_layers = max_layers

                # Linear interpolation based on difficulty within grade range
                layer_range = max_layers - min_layers
                active_layer_count = min_layers + int(layer_range * target)

                # Clamp to valid range
                active_layer_count = max(min_layers, min(max_layers, active_layer_count))

            # Update level["layer"] to reflect actual active layer count
            level["layer"] = active_layer_count

            # Use layers 0 to active_layer_count-1 (bottom to top)
            active_layers = list(range(active_layer_count))

            # Calculate total tile count target
            if params.total_tile_count is not None:
                total_target = (params.total_tile_count // 3) * 3
                if total_target < 9:
                    total_target = 9
            else:
                # Tile Buster style tile count ranges:
                # - Early levels (tutorial): 30-45 tiles, simple layout
                # - Mid levels: 45-60 tiles, moderate complexity
                # - Late levels: 60-90 tiles, high complexity
                #
                # S grade (0-0.2): Tutorial style, 30-45 tiles
                # A grade (0.2-0.4): Easy-medium, 45-60 tiles
                # B grade (0.4-0.6): Medium, 54-72 tiles
                # C grade (0.6-0.8): Hard, 66-84 tiles
                # D grade (0.8-1.0): Very hard, 78-99 tiles
                if target < 0.2:
                    # S grade: tutorial style
                    min_tiles = 30
                    max_tiles = 45
                elif target < 0.4:
                    # A grade: easy-medium
                    min_tiles = 45
                    max_tiles = 60
                elif target < 0.6:
                    # B grade: medium
                    min_tiles = 54
                    max_tiles = 72
                elif target < 0.8:
                    # C grade: hard
                    min_tiles = 66
                    max_tiles = 84
                else:
                    # D grade: very hard
                    min_tiles = 78
                    max_tiles = 99

                # Linear interpolation within the grade range
                if target < 0.2:
                    t = target / 0.2
                elif target < 0.4:
                    t = (target - 0.2) / 0.2
                elif target < 0.6:
                    t = (target - 0.4) / 0.2
                elif target < 0.8:
                    t = (target - 0.6) / 0.2
                else:
                    t = (target - 0.8) / 0.2

                base_tiles = int(min_tiles + (max_tiles - min_tiles) * t)
                base_tiles = max(min_tiles, min(max_tiles, base_tiles))
                total_target = (base_tiles // 3) * 3
                if total_target < 30:
                    total_target = 30

            # Build per-layer tile counts - distribute evenly
            layer_tile_counts = {}
            tiles_per_layer = total_target // len(active_layers)
            extra_tiles = total_target % len(active_layers)

            for i, layer_idx in enumerate(active_layers):
                layer_tile_counts[layer_idx] = tiles_per_layer + (1 if i < extra_tiles else 0)

        # Collect all positions across all layers
        all_layer_positions: List[Tuple[int, str]] = []  # (layer_idx, pos)

        # Generate varied pattern indices for each layer (for aesthetic mode)
        # This creates geometric diversity by using different patterns per layer
        layer_pattern_indices = self._select_layer_pattern_indices(
            active_layers, base_pattern_index=params.pattern_index
        )

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

            # Use layer-specific pattern index for geometric diversity
            layer_pattern_index = layer_pattern_indices.get(layer_idx, params.pattern_index)

            # Generate positions for this layer with symmetry and pattern options
            positions = self._generate_layer_positions_for_count(
                layer_cols, layer_rows, target_count,
                symmetry_mode=params.symmetry_mode,
                pattern_type=params.pattern_type,
                pattern_index=layer_pattern_index  # Use varied pattern per layer
            )

            for pos in positions:
                all_layer_positions.append((layer_idx, pos))

        # CRITICAL: Ensure total positions is divisible by 3
        # When layers are full, clamping may break divisibility
        total_positions = len(all_layer_positions)
        remainder = total_positions % 3

        # For symmetric patterns, we can't just remove random positions
        # as it would break the symmetry. Only remove if no symmetry.
        symmetry = params.symmetry_mode or "none"
        if remainder > 0 and symmetry == "none":
            # Remove excess positions to make divisible by 3
            # Remove from the end (random positions anyway)
            all_layer_positions = all_layer_positions[:total_positions - remainder]
        elif remainder > 0 and symmetry != "none":
            # For symmetric patterns, add dummy positions to reach divisible by 3
            # We'll use already existing positions (they'll just be duplicated in assignment)
            # This is a simple workaround - the tile assignment handles extra positions
            pass  # Let the tile assignment code handle the non-divisibility

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

        # If we have more assignments than positions, trim to match
        # (positions are already divisible by 3 from earlier check)
        if len(tile_assignments) > len(all_layer_positions):
            tile_assignments = tile_assignments[:len(all_layer_positions)]

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
        self, cols: int, rows: int, density: float,
        symmetry_mode: Optional[str] = None, pattern_type: Optional[str] = None
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

        selected = self._generate_positions_with_pattern(
            cols, rows, target_count, symmetry_mode, pattern_type
        )

        return selected

    def _generate_layer_positions_for_count(
        self, cols: int, rows: int, target_count: int,
        symmetry_mode: Optional[str] = None, pattern_type: Optional[str] = None,
        pattern_index: Optional[int] = None
    ) -> List[str]:
        """Generate tile positions for a layer with specific count."""
        # Clamp to available positions
        max_positions = cols * rows
        actual_count = min(target_count, max_positions)
        if actual_count <= 0:
            return []

        selected = self._generate_positions_with_pattern(
            cols, rows, actual_count, symmetry_mode, pattern_type, pattern_index
        )
        return selected

    def _generate_positions_with_pattern(
        self, cols: int, rows: int, target_count: int,
        symmetry_mode: Optional[str] = None, pattern_type: Optional[str] = None,
        pattern_index: Optional[int] = None
    ) -> List[str]:
        """Generate positions with symmetry and pattern options."""
        # Default to geometric pattern for more regular shapes
        pattern = pattern_type or "geometric"

        # Resolve symmetry mode: convert None or "none" to random single-axis
        # "both" is now preserved to enable 4-way symmetry for aesthetic patterns
        if symmetry_mode is None or symmetry_mode == "none":
            symmetry = random.choice(["horizontal", "vertical"])
        else:
            symmetry = symmetry_mode

        # Generate base positions based on pattern type
        if pattern == "aesthetic":
            # Aesthetic mode: generate pattern then apply symmetry mirroring
            raw_positions = self._generate_aesthetic_positions(cols, rows, target_count, pattern_index)
            # Apply symmetry to aesthetic patterns too
            base_positions = self._apply_symmetry_to_positions(cols, rows, raw_positions, symmetry, target_count)
        elif pattern == "geometric":
            base_positions = self._generate_geometric_positions(cols, rows, target_count, symmetry)
        elif pattern == "clustered":
            base_positions = self._generate_clustered_positions(cols, rows, target_count, symmetry)
        else:  # random
            base_positions = self._generate_random_positions(cols, rows, target_count, symmetry)

        return base_positions

    def _generate_aesthetic_positions(
        self, cols: int, rows: int, target_count: int,
        pattern_index: Optional[int] = None
    ) -> List[str]:
        """Generate visually appealing positions using 50 diverse patterns.

        Patterns are inspired by high-level stages from Tile Buster, Triple Match 3D,
        Tile Explorer, and other popular tile-matching puzzle games.

        Categories:
        - 0-9: Basic shapes (rectangle, diamond, oval, cross, donut, etc.)
        - 10-14: Arrow/Direction patterns
        - 15-19: Star/Celestial patterns
        - 20-29: Letter shapes (H, I, L, U, X, Y, Z, S, O, C)
        - 30-39: Advanced geometric (triangles, hourglass, stairs, pyramid, zigzag)
        - 40-44: Frame/Border patterns
        - 45-49: Artistic patterns (butterfly, flower, islands, stripes, honeycomb)

        Args:
            cols: Grid columns
            rows: Grid rows
            target_count: Target number of tiles
            pattern_index: If specified (0-49), forces use of that specific pattern.
                          None = auto-select best pattern based on target_count.
        """
        import math
        center_x, center_y = cols / 2.0, rows / 2.0

        # ============ Category 1: Basic Shapes (0-9) ============

        # Pattern 0: Filled Rectangle
        def filled_rectangle():
            aspect_ratio = cols / rows
            rect_height = int((target_count / aspect_ratio) ** 0.5)
            rect_width = int(rect_height * aspect_ratio)
            if rect_width * rect_height < target_count:
                rect_width += 1
            if rect_width * rect_height < target_count:
                rect_height += 1
            start_x = int((cols - rect_width) / 2)
            start_y = int((rows - rect_height) / 2)
            positions = []
            for x in range(start_x, min(cols, start_x + rect_width)):
                for y in range(start_y, min(rows, start_y + rect_height)):
                    if x >= 0 and y >= 0:
                        positions.append(f"{x}_{y}")
            return positions

        # Pattern 1: Diamond/Rhombus shape
        def diamond_shape():
            radius = int((target_count * 2) ** 0.5)
            positions = []
            for x in range(cols):
                for y in range(rows):
                    dist = abs(x - center_x + 0.5) + abs(y - center_y + 0.5)
                    if dist <= radius:
                        positions.append(f"{x}_{y}")
            return positions

        # Pattern 2: Oval/Ellipse shape
        def oval_shape():
            radius_x = int((target_count * cols / (rows * 3.14)) ** 0.5) + 1
            radius_y = int((target_count * rows / (cols * 3.14)) ** 0.5) + 1
            positions = []
            for x in range(cols):
                for y in range(rows):
                    dx = (x - center_x + 0.5) / max(1, radius_x)
                    dy = (y - center_y + 0.5) / max(1, radius_y)
                    if dx * dx + dy * dy <= 1.0:
                        positions.append(f"{x}_{y}")
            return positions

        # Pattern 3: Plus/Cross shape
        def cross_shape():
            positions = []
            arm_width = max(2, int(cols * 0.4))
            arm_height = max(2, int(rows * 0.4))
            start_x = int((cols - arm_width) / 2)
            start_y = int((rows - arm_height) / 2)
            for x in range(cols):
                for y in range(start_y, min(rows, start_y + arm_height)):
                    positions.append(f"{x}_{y}")
            for x in range(start_x, min(cols, start_x + arm_width)):
                for y in range(rows):
                    if f"{x}_{y}" not in positions:
                        positions.append(f"{x}_{y}")
            return positions

        # Pattern 4: Donut shape (hollow center)
        def donut_shape():
            outer_radius = int((target_count / 2.5) ** 0.5) + 2
            inner_radius = max(1, outer_radius // 3)
            positions = []
            for x in range(cols):
                for y in range(rows):
                    dist = ((x - center_x + 0.5) ** 2 + (y - center_y + 0.5) ** 2) ** 0.5
                    if inner_radius <= dist <= outer_radius:
                        positions.append(f"{x}_{y}")
            return positions

        # Pattern 5: Concentric diamond
        def concentric_diamond():
            positions = []
            outer_radius = int((target_count * 2) ** 0.5)
            for x in range(cols):
                for y in range(rows):
                    dist = abs(x - center_x + 0.5) + abs(y - center_y + 0.5)
                    if dist <= outer_radius:
                        positions.append(f"{x}_{y}")
            return positions

        # Pattern 6: Corner-anchored pattern
        def corner_anchored():
            positions = []
            corner_size = max(1, min(cols, rows) // 4)
            for x in range(cols):
                for y in range(rows):
                    is_corner = (
                        (x < corner_size and y < corner_size) or
                        (x < corner_size and y >= rows - corner_size) or
                        (x >= cols - corner_size and y < corner_size) or
                        (x >= cols - corner_size and y >= rows - corner_size)
                    )
                    if not is_corner:
                        positions.append(f"{x}_{y}")
            return positions

        # Pattern 7: Hexagonal-ish pattern
        def hexagonal():
            positions = []
            radius = int((target_count / 2.6) ** 0.5) + 1
            for x in range(cols):
                for y in range(rows):
                    dx = abs(x - center_x + 0.5)
                    dy = abs(y - center_y + 0.5) * 1.15
                    dist = max(dx, dy, (dx + dy) * 0.55)
                    if dist <= radius:
                        positions.append(f"{x}_{y}")
            return positions

        # Pattern 8: Heart shape
        def heart_shape():
            positions = []
            scale = max(cols, rows) / 8
            for x in range(cols):
                for y in range(rows):
                    nx = (x - center_x + 0.5) / scale
                    ny = -(y - center_y + 0.5) / scale + 0.5
                    value = (nx**2 + ny**2 - 1)**3 - (nx**2) * (ny**3)
                    if value <= 0.5:
                        positions.append(f"{x}_{y}")
            return positions

        # Pattern 9: T-shape
        def t_shape():
            positions = []
            bar_height = max(2, rows // 4)
            stem_width = max(2, cols // 3)
            stem_start_x = int((cols - stem_width) / 2)
            for x in range(cols):
                for y in range(bar_height):
                    positions.append(f"{x}_{y}")
            for x in range(stem_start_x, min(cols, stem_start_x + stem_width)):
                for y in range(bar_height, rows):
                    positions.append(f"{x}_{y}")
            return positions

        # ============ Category 2: Arrow/Direction Patterns (10-14) ============

        # Pattern 10: Arrow Up
        def arrow_up():
            positions = []
            tip_y = 0
            base_y = rows - 1
            arrow_width = max(2, cols // 3)
            start_x = int((cols - arrow_width) / 2)
            # Arrow head (triangle)
            for y in range(rows // 2):
                width = max(1, (y + 1) * 2)
                sx = int(center_x - width / 2)
                for x in range(sx, min(cols, sx + width)):
                    if 0 <= x < cols:
                        positions.append(f"{x}_{y}")
            # Arrow stem
            for x in range(start_x, min(cols, start_x + arrow_width)):
                for y in range(rows // 2, rows):
                    positions.append(f"{x}_{y}")
            return positions

        # Pattern 11: Arrow Down
        def arrow_down():
            positions = []
            arrow_width = max(2, cols // 3)
            start_x = int((cols - arrow_width) / 2)
            # Arrow stem (top)
            for x in range(start_x, min(cols, start_x + arrow_width)):
                for y in range(rows // 2):
                    positions.append(f"{x}_{y}")
            # Arrow head (triangle pointing down)
            for y in range(rows // 2, rows):
                rel_y = y - rows // 2
                width = max(1, cols - rel_y * 2)
                sx = int(center_x - width / 2)
                for x in range(sx, min(cols, sx + width)):
                    if 0 <= x < cols and width > 0:
                        positions.append(f"{x}_{y}")
            return positions

        # Pattern 12: Arrow Left
        def arrow_left():
            positions = []
            arrow_height = max(2, rows // 3)
            start_y = int((rows - arrow_height) / 2)
            # Arrow head (triangle pointing left)
            for x in range(cols // 2):
                height = max(1, (x + 1) * 2)
                sy = int(center_y - height / 2)
                for y in range(sy, min(rows, sy + height)):
                    if 0 <= y < rows:
                        positions.append(f"{x}_{y}")
            # Arrow stem
            for y in range(start_y, min(rows, start_y + arrow_height)):
                for x in range(cols // 2, cols):
                    positions.append(f"{x}_{y}")
            return positions

        # Pattern 13: Arrow Right
        def arrow_right():
            positions = []
            arrow_height = max(2, rows // 3)
            start_y = int((rows - arrow_height) / 2)
            # Arrow stem (left side)
            for y in range(start_y, min(rows, start_y + arrow_height)):
                for x in range(cols // 2):
                    positions.append(f"{x}_{y}")
            # Arrow head (triangle pointing right)
            for x in range(cols // 2, cols):
                rel_x = x - cols // 2
                height = max(1, rows - rel_x * 2)
                sy = int(center_y - height / 2)
                for y in range(sy, min(rows, sy + height)):
                    if 0 <= y < rows and height > 0:
                        positions.append(f"{x}_{y}")
            return positions

        # Pattern 14: Chevron (double arrow)
        def chevron_pattern():
            positions = []
            thickness = max(2, min(cols, rows) // 4)
            for x in range(cols):
                for y in range(rows):
                    # V shape
                    v_dist = abs(y - (rows - 1 - abs(x - center_x + 0.5) * rows / cols * 0.8))
                    if v_dist <= thickness:
                        positions.append(f"{x}_{y}")
            return positions

        # ============ Category 3: Star/Celestial Patterns (15-19) ============

        # Pattern 15: Five-pointed Star
        def star_five_point():
            positions = []
            radius = min(cols, rows) / 2.5
            inner_radius = radius * 0.4
            for x in range(cols):
                for y in range(rows):
                    dx = x - center_x + 0.5
                    dy = y - center_y + 0.5
                    angle = math.atan2(dy, dx)
                    dist = (dx**2 + dy**2) ** 0.5
                    # Star shape formula
                    star_angle = (angle + math.pi) % (2 * math.pi / 5)
                    star_radius = inner_radius + (radius - inner_radius) * abs(math.cos(star_angle * 2.5))
                    if dist <= star_radius:
                        positions.append(f"{x}_{y}")
            return positions

        # Pattern 16: Six-pointed Star (Star of David)
        def star_six_point():
            positions = []
            radius = min(cols, rows) / 2.5
            for x in range(cols):
                for y in range(rows):
                    dx = x - center_x + 0.5
                    dy = y - center_y + 0.5
                    # Two overlapping triangles
                    tri1 = (dy <= radius * 0.5 - abs(dx) * 0.866) or (dy >= -radius * 0.5 + abs(dx) * 0.866 and dy <= 0)
                    tri2 = (dy >= -radius * 0.5 + abs(dx) * 0.866) or (dy <= radius * 0.5 - abs(dx) * 0.866 and dy >= 0)
                    dist = abs(dx) + abs(dy) * 0.7
                    if dist <= radius:
                        positions.append(f"{x}_{y}")
            return positions

        # Pattern 17: Crescent Moon
        def crescent_moon():
            positions = []
            outer_radius = min(cols, rows) / 2.2
            inner_radius = outer_radius * 0.7
            offset_x = outer_radius * 0.5
            for x in range(cols):
                for y in range(rows):
                    dx = x - center_x + 0.5
                    dy = y - center_y + 0.5
                    outer_dist = (dx**2 + dy**2) ** 0.5
                    inner_dist = ((dx + offset_x)**2 + dy**2) ** 0.5
                    if outer_dist <= outer_radius and inner_dist > inner_radius:
                        positions.append(f"{x}_{y}")
            return positions

        # Pattern 18: Sun Burst
        def sun_burst():
            positions = []
            core_radius = min(cols, rows) / 4
            ray_length = min(cols, rows) / 2.5
            num_rays = 8
            for x in range(cols):
                for y in range(rows):
                    dx = x - center_x + 0.5
                    dy = y - center_y + 0.5
                    dist = (dx**2 + dy**2) ** 0.5
                    angle = math.atan2(dy, dx)
                    # Core circle
                    if dist <= core_radius:
                        positions.append(f"{x}_{y}")
                    # Rays
                    elif dist <= ray_length:
                        ray_angle = (angle + math.pi) % (2 * math.pi / num_rays)
                        if ray_angle < math.pi / num_rays * 0.5 or ray_angle > 2 * math.pi / num_rays - math.pi / num_rays * 0.5:
                            positions.append(f"{x}_{y}")
            return positions

        # Pattern 19: Spiral
        def spiral():
            positions = []
            max_radius = min(cols, rows) / 2.2
            turns = 2.5
            thickness = max(1.5, min(cols, rows) / 8)
            for x in range(cols):
                for y in range(rows):
                    dx = x - center_x + 0.5
                    dy = y - center_y + 0.5
                    dist = (dx**2 + dy**2) ** 0.5
                    if dist < 0.5:
                        positions.append(f"{x}_{y}")
                        continue
                    angle = math.atan2(dy, dx)
                    expected_dist = (angle + math.pi) / (2 * math.pi) * max_radius / turns
                    for i in range(int(turns) + 1):
                        check_dist = expected_dist + i * max_radius / turns
                        if abs(dist - check_dist) <= thickness:
                            positions.append(f"{x}_{y}")
                            break
            return positions

        # ============ Category 4: Letter Shapes (20-29) ============

        # Pattern 20: Letter H
        def letter_H():
            positions = []
            bar_width = max(2, cols // 4)
            for x in range(bar_width):
                for y in range(rows):
                    positions.append(f"{x}_{y}")
            for x in range(cols - bar_width, cols):
                for y in range(rows):
                    positions.append(f"{x}_{y}")
            mid_y = rows // 2
            bar_height = max(2, rows // 4)
            for x in range(bar_width, cols - bar_width):
                for y in range(mid_y - bar_height // 2, mid_y + bar_height // 2 + 1):
                    positions.append(f"{x}_{y}")
            return positions

        # Pattern 21: Letter I
        def letter_I():
            positions = []
            bar_height = max(2, rows // 4)
            stem_width = max(2, cols // 3)
            stem_start = int((cols - stem_width) / 2)
            # Top bar
            for x in range(cols):
                for y in range(bar_height):
                    positions.append(f"{x}_{y}")
            # Bottom bar
            for x in range(cols):
                for y in range(rows - bar_height, rows):
                    positions.append(f"{x}_{y}")
            # Stem
            for x in range(stem_start, stem_start + stem_width):
                for y in range(bar_height, rows - bar_height):
                    positions.append(f"{x}_{y}")
            return positions

        # Pattern 22: Letter L
        def letter_L():
            positions = []
            bar_width = max(2, cols // 3)
            bar_height = max(2, rows // 4)
            # Vertical bar
            for x in range(bar_width):
                for y in range(rows):
                    positions.append(f"{x}_{y}")
            # Horizontal bar at bottom
            for x in range(bar_width, cols):
                for y in range(rows - bar_height, rows):
                    positions.append(f"{x}_{y}")
            return positions

        # Pattern 23: Letter U
        def letter_U():
            positions = []
            bar_width = max(2, cols // 4)
            bar_height = max(2, rows // 4)
            # Left vertical
            for x in range(bar_width):
                for y in range(rows):
                    positions.append(f"{x}_{y}")
            # Right vertical
            for x in range(cols - bar_width, cols):
                for y in range(rows):
                    positions.append(f"{x}_{y}")
            # Bottom connector
            for x in range(bar_width, cols - bar_width):
                for y in range(rows - bar_height, rows):
                    positions.append(f"{x}_{y}")
            return positions

        # Pattern 24: Letter X
        def letter_X():
            positions = []
            thickness = max(1.5, min(cols, rows) / 5)
            for x in range(cols):
                for y in range(rows):
                    # Diagonal 1 (top-left to bottom-right)
                    d1 = abs((x - center_x) - (y - center_y) * cols / rows)
                    # Diagonal 2 (top-right to bottom-left)
                    d2 = abs((x - center_x) + (y - center_y) * cols / rows)
                    if d1 <= thickness or d2 <= thickness:
                        positions.append(f"{x}_{y}")
            return positions

        # Pattern 25: Letter Y
        def letter_Y():
            positions = []
            stem_width = max(2, cols // 3)
            stem_start = int((cols - stem_width) / 2)
            mid_y = rows // 2
            thickness = max(1.5, cols / 5)
            # Top diagonals
            for x in range(cols):
                for y in range(mid_y):
                    d1 = abs((x - center_x) - (y - mid_y) * cols / rows)
                    d2 = abs((x - center_x) + (y - mid_y) * cols / rows)
                    if d1 <= thickness or d2 <= thickness:
                        positions.append(f"{x}_{y}")
            # Bottom stem
            for x in range(stem_start, stem_start + stem_width):
                for y in range(mid_y, rows):
                    positions.append(f"{x}_{y}")
            return positions

        # Pattern 26: Letter Z
        def letter_Z():
            positions = []
            bar_height = max(2, rows // 4)
            thickness = max(1.5, min(cols, rows) / 5)
            # Top bar
            for x in range(cols):
                for y in range(bar_height):
                    positions.append(f"{x}_{y}")
            # Bottom bar
            for x in range(cols):
                for y in range(rows - bar_height, rows):
                    positions.append(f"{x}_{y}")
            # Diagonal
            for x in range(cols):
                for y in range(bar_height, rows - bar_height):
                    expected_x = cols - 1 - (y - bar_height) * cols / (rows - 2 * bar_height)
                    if abs(x - expected_x) <= thickness:
                        positions.append(f"{x}_{y}")
            return positions

        # Pattern 27: Letter S
        def letter_S():
            positions = []
            bar_height = max(2, rows // 5)
            bar_width = max(2, cols // 4)
            # Top bar
            for x in range(cols):
                for y in range(bar_height):
                    positions.append(f"{x}_{y}")
            # Upper left vertical
            for x in range(bar_width):
                for y in range(bar_height, rows // 2):
                    positions.append(f"{x}_{y}")
            # Middle bar
            for x in range(cols):
                for y in range(rows // 2 - bar_height // 2, rows // 2 + bar_height // 2 + 1):
                    positions.append(f"{x}_{y}")
            # Lower right vertical
            for x in range(cols - bar_width, cols):
                for y in range(rows // 2 + 1, rows - bar_height):
                    positions.append(f"{x}_{y}")
            # Bottom bar
            for x in range(cols):
                for y in range(rows - bar_height, rows):
                    positions.append(f"{x}_{y}")
            return positions

        # Pattern 28: Letter O (ring)
        def letter_O():
            positions = []
            outer_rx = cols / 2.2
            outer_ry = rows / 2.2
            inner_rx = outer_rx * 0.5
            inner_ry = outer_ry * 0.5
            for x in range(cols):
                for y in range(rows):
                    dx = (x - center_x + 0.5) / outer_rx
                    dy = (y - center_y + 0.5) / outer_ry
                    outer_dist = dx * dx + dy * dy
                    dx2 = (x - center_x + 0.5) / inner_rx
                    dy2 = (y - center_y + 0.5) / inner_ry
                    inner_dist = dx2 * dx2 + dy2 * dy2
                    if outer_dist <= 1.0 and inner_dist >= 1.0:
                        positions.append(f"{x}_{y}")
            return positions

        # Pattern 29: Letter C
        def letter_C():
            positions = []
            outer_rx = cols / 2.2
            outer_ry = rows / 2.2
            inner_rx = outer_rx * 0.5
            inner_ry = outer_ry * 0.5
            gap_width = cols / 3
            for x in range(cols):
                for y in range(rows):
                    dx = (x - center_x + 0.5) / outer_rx
                    dy = (y - center_y + 0.5) / outer_ry
                    outer_dist = dx * dx + dy * dy
                    dx2 = (x - center_x + 0.5) / inner_rx
                    dy2 = (y - center_y + 0.5) / inner_ry
                    inner_dist = dx2 * dx2 + dy2 * dy2
                    # C shape - open on the right
                    if outer_dist <= 1.0 and inner_dist >= 1.0 and x < cols - gap_width:
                        positions.append(f"{x}_{y}")
            return positions

        # ============ Category 5: Advanced Geometric (30-39) ============

        # Pattern 30: Triangle Up
        def triangle_up():
            positions = []
            for y in range(rows):
                width = int((rows - y) * cols / rows)
                start_x = int((cols - width) / 2)
                for x in range(start_x, min(cols, start_x + width)):
                    if 0 <= x < cols:
                        positions.append(f"{x}_{y}")
            return positions

        # Pattern 31: Triangle Down
        def triangle_down():
            positions = []
            for y in range(rows):
                width = int((y + 1) * cols / rows)
                start_x = int((cols - width) / 2)
                for x in range(start_x, min(cols, start_x + width)):
                    if 0 <= x < cols:
                        positions.append(f"{x}_{y}")
            return positions

        # Pattern 32: Hourglass
        def hourglass():
            positions = []
            for y in range(rows):
                # Distance from center row
                dist_from_center = abs(y - center_y)
                width = int(cols * (dist_from_center / center_y + 0.3))
                width = max(2, min(cols, width))
                start_x = int((cols - width) / 2)
                for x in range(start_x, min(cols, start_x + width)):
                    if 0 <= x < cols:
                        positions.append(f"{x}_{y}")
            return positions

        # Pattern 33: Bowtie
        def bowtie():
            positions = []
            for y in range(rows):
                dist_from_center = abs(y - center_y)
                width = int(cols * (1 - dist_from_center / center_y * 0.7))
                width = max(2, min(cols, width))
                start_x = int((cols - width) / 2)
                for x in range(start_x, min(cols, start_x + width)):
                    if 0 <= x < cols:
                        positions.append(f"{x}_{y}")
            return positions

        # Pattern 34: Stairs Ascending (left to right)
        def stairs_ascending():
            positions = []
            num_steps = min(cols, rows) // 2
            step_width = cols // num_steps
            step_height = rows // num_steps
            for step in range(num_steps):
                x_start = step * step_width
                y_start = rows - (step + 1) * step_height
                for x in range(x_start, min(cols, x_start + step_width + 1)):
                    for y in range(max(0, y_start), rows):
                        positions.append(f"{x}_{y}")
            return positions

        # Pattern 35: Stairs Descending
        def stairs_descending():
            positions = []
            num_steps = min(cols, rows) // 2
            step_width = cols // num_steps
            step_height = rows // num_steps
            for step in range(num_steps):
                x_start = step * step_width
                y_end = (step + 1) * step_height
                for x in range(x_start, min(cols, x_start + step_width + 1)):
                    for y in range(min(rows, y_end)):
                        positions.append(f"{x}_{y}")
            return positions

        # Pattern 36: Pyramid
        def pyramid():
            positions = []
            levels = min(rows, cols // 2)
            for level in range(levels):
                y = rows - 1 - level
                width = (level + 1) * 2 - 1
                start_x = int((cols - width) / 2)
                for x in range(start_x, min(cols, start_x + width)):
                    if 0 <= x < cols and 0 <= y < rows:
                        positions.append(f"{x}_{y}")
            return positions

        # Pattern 37: Inverted Pyramid
        def inverted_pyramid():
            positions = []
            levels = min(rows, cols // 2)
            for level in range(levels):
                y = level
                width = (levels - level) * 2 - 1
                start_x = int((cols - width) / 2)
                for x in range(start_x, min(cols, start_x + width)):
                    if 0 <= x < cols:
                        positions.append(f"{x}_{y}")
            return positions

        # Pattern 38: Zigzag Horizontal
        def zigzag_horizontal():
            positions = []
            amplitude = rows // 3
            period = cols // 3
            thickness = max(2, rows // 4)
            for x in range(cols):
                base_y = int(center_y + amplitude * math.sin(x * 2 * math.pi / period))
                for y in range(max(0, base_y - thickness), min(rows, base_y + thickness + 1)):
                    positions.append(f"{x}_{y}")
            return positions

        # Pattern 39: Wave Pattern
        def wave_pattern():
            positions = []
            num_waves = 3
            wave_height = rows // (num_waves * 2)
            for x in range(cols):
                for y in range(rows):
                    wave_offset = int(wave_height * math.sin(x * 2 * math.pi / (cols / 2)))
                    if (y + wave_offset) % (rows // num_waves) < rows // num_waves // 2:
                        positions.append(f"{x}_{y}")
            return positions

        # ============ Category 6: Frame/Border Patterns (40-44) ============

        # Pattern 40: Frame Border
        def frame_border():
            positions = []
            border_width = max(2, min(cols, rows) // 4)
            for x in range(cols):
                for y in range(rows):
                    if x < border_width or x >= cols - border_width or y < border_width or y >= rows - border_width:
                        positions.append(f"{x}_{y}")
            return positions

        # Pattern 41: Double Frame
        def double_frame():
            positions = []
            outer_width = max(1, min(cols, rows) // 6)
            gap = max(1, min(cols, rows) // 6)
            inner_width = max(1, min(cols, rows) // 6)
            for x in range(cols):
                for y in range(rows):
                    # Outer frame
                    if x < outer_width or x >= cols - outer_width or y < outer_width or y >= rows - outer_width:
                        positions.append(f"{x}_{y}")
                    # Inner frame
                    inner_start = outer_width + gap
                    inner_end_x = cols - outer_width - gap
                    inner_end_y = rows - outer_width - gap
                    if inner_start <= x < inner_end_x and inner_start <= y < inner_end_y:
                        if x < inner_start + inner_width or x >= inner_end_x - inner_width or y < inner_start + inner_width or y >= inner_end_y - inner_width:
                            positions.append(f"{x}_{y}")
            return positions

        # Pattern 42: Corner Triangles
        def corner_triangles():
            positions = []
            tri_size = min(cols, rows) // 3
            for x in range(cols):
                for y in range(rows):
                    # Top-left
                    if x + y < tri_size:
                        positions.append(f"{x}_{y}")
                    # Top-right
                    elif (cols - 1 - x) + y < tri_size:
                        positions.append(f"{x}_{y}")
                    # Bottom-left
                    elif x + (rows - 1 - y) < tri_size:
                        positions.append(f"{x}_{y}")
                    # Bottom-right
                    elif (cols - 1 - x) + (rows - 1 - y) < tri_size:
                        positions.append(f"{x}_{y}")
            return positions

        # Pattern 43: Center Hollow (filled corners, hollow center)
        def center_hollow():
            positions = []
            hollow_size = min(cols, rows) // 3
            hollow_x_start = int((cols - hollow_size) / 2)
            hollow_y_start = int((rows - hollow_size) / 2)
            for x in range(cols):
                for y in range(rows):
                    # Not in center hollow
                    if not (hollow_x_start <= x < hollow_x_start + hollow_size and hollow_y_start <= y < hollow_y_start + hollow_size):
                        positions.append(f"{x}_{y}")
            return positions

        # Pattern 44: Window Panes (4 quadrants)
        def window_panes():
            positions = []
            gap = max(1, min(cols, rows) // 6)
            mid_x = cols // 2
            mid_y = rows // 2
            for x in range(cols):
                for y in range(rows):
                    # Not in center cross
                    if not (mid_x - gap <= x < mid_x + gap or mid_y - gap <= y < mid_y + gap):
                        positions.append(f"{x}_{y}")
            return positions

        # ============ Category 7: Artistic Patterns (45-49) ============

        # Pattern 45: Butterfly
        def butterfly():
            positions = []
            wing_radius = min(cols, rows) / 2.5
            body_width = max(1, cols // 6)
            for x in range(cols):
                for y in range(rows):
                    dx = abs(x - center_x + 0.5)
                    dy = y - center_y + 0.5
                    # Wings (two circles offset from center)
                    wing_dist = ((dx - wing_radius * 0.5) ** 2 + dy ** 2) ** 0.5
                    # Body (center column)
                    if wing_dist <= wing_radius * 0.7 or dx <= body_width / 2:
                        positions.append(f"{x}_{y}")
            return positions

        # Pattern 46: Flower Pattern (petals around center)
        def flower_pattern():
            positions = []
            petal_radius = min(cols, rows) / 3
            center_radius = min(cols, rows) / 6
            num_petals = 6
            for x in range(cols):
                for y in range(rows):
                    dx = x - center_x + 0.5
                    dy = y - center_y + 0.5
                    dist = (dx ** 2 + dy ** 2) ** 0.5
                    # Center
                    if dist <= center_radius:
                        positions.append(f"{x}_{y}")
                    else:
                        # Petals
                        angle = math.atan2(dy, dx)
                        for i in range(num_petals):
                            petal_angle = i * 2 * math.pi / num_petals
                            petal_cx = center_x + math.cos(petal_angle) * petal_radius * 0.7
                            petal_cy = center_y + math.sin(petal_angle) * petal_radius * 0.7
                            petal_dist = ((x - petal_cx) ** 2 + (y - petal_cy) ** 2) ** 0.5
                            if petal_dist <= petal_radius * 0.5:
                                positions.append(f"{x}_{y}")
                                break
            return positions

        # Pattern 47: Scattered Islands
        def scattered_islands():
            positions = []
            # Create 4-6 island clusters
            random.seed(42)  # Deterministic for consistency
            num_islands = min(6, max(4, (cols * rows) // 30))
            islands = []
            for _ in range(num_islands):
                ix = random.randint(1, cols - 2)
                iy = random.randint(1, rows - 2)
                ir = random.uniform(1.5, min(cols, rows) / 4)
                islands.append((ix, iy, ir))
            for x in range(cols):
                for y in range(rows):
                    for ix, iy, ir in islands:
                        if ((x - ix) ** 2 + (y - iy) ** 2) ** 0.5 <= ir:
                            positions.append(f"{x}_{y}")
                            break
            return positions

        # Pattern 48: Diagonal Stripes
        def diagonal_stripes():
            positions = []
            stripe_width = max(2, min(cols, rows) // 4)
            for x in range(cols):
                for y in range(rows):
                    if ((x + y) // stripe_width) % 2 == 0:
                        positions.append(f"{x}_{y}")
            return positions

        # Pattern 49: Honeycomb
        def honeycomb():
            positions = []
            cell_size = max(2, min(cols, rows) // 4)
            for x in range(cols):
                for y in range(rows):
                    # Offset every other row
                    offset = (cell_size // 2) if (y // cell_size) % 2 == 1 else 0
                    cell_x = (x + offset) // cell_size
                    cell_y = y // cell_size
                    # Create hexagonal-ish cells
                    local_x = (x + offset) % cell_size
                    local_y = y % cell_size
                    # Fill cells but leave small gaps
                    if local_x > 0 and local_x < cell_size - 1 and local_y > 0 and local_y < cell_size - 1:
                        positions.append(f"{x}_{y}")
            return positions

        # ============ Build Pattern List ============

        all_patterns = [
            # Category 1: Basic Shapes (0-9)
            ("filled_rectangle", filled_rectangle),       # 0
            ("diamond_shape", diamond_shape),             # 1
            ("oval_shape", oval_shape),                   # 2
            ("cross_shape", cross_shape),                 # 3
            ("donut_shape", donut_shape),                 # 4
            ("concentric_diamond", concentric_diamond),   # 5
            ("corner_anchored", corner_anchored),         # 6
            ("hexagonal", hexagonal),                     # 7
            ("heart_shape", heart_shape),                 # 8
            ("t_shape", t_shape),                         # 9
            # Category 2: Arrow/Direction (10-14)
            ("arrow_up", arrow_up),                       # 10
            ("arrow_down", arrow_down),                   # 11
            ("arrow_left", arrow_left),                   # 12
            ("arrow_right", arrow_right),                 # 13
            ("chevron_pattern", chevron_pattern),         # 14
            # Category 3: Star/Celestial (15-19)
            ("star_five_point", star_five_point),         # 15
            ("star_six_point", star_six_point),           # 16
            ("crescent_moon", crescent_moon),             # 17
            ("sun_burst", sun_burst),                     # 18
            ("spiral", spiral),                           # 19
            # Category 4: Letter Shapes (20-29)
            ("letter_H", letter_H),                       # 20
            ("letter_I", letter_I),                       # 21
            ("letter_L", letter_L),                       # 22
            ("letter_U", letter_U),                       # 23
            ("letter_X", letter_X),                       # 24
            ("letter_Y", letter_Y),                       # 25
            ("letter_Z", letter_Z),                       # 26
            ("letter_S", letter_S),                       # 27
            ("letter_O", letter_O),                       # 28
            ("letter_C", letter_C),                       # 29
            # Category 5: Advanced Geometric (30-39)
            ("triangle_up", triangle_up),                 # 30
            ("triangle_down", triangle_down),             # 31
            ("hourglass", hourglass),                     # 32
            ("bowtie", bowtie),                           # 33
            ("stairs_ascending", stairs_ascending),       # 34
            ("stairs_descending", stairs_descending),     # 35
            ("pyramid", pyramid),                         # 36
            ("inverted_pyramid", inverted_pyramid),       # 37
            ("zigzag_horizontal", zigzag_horizontal),     # 38
            ("wave_pattern", wave_pattern),               # 39
            # Category 6: Frame/Border (40-44)
            ("frame_border", frame_border),               # 40
            ("double_frame", double_frame),               # 41
            ("corner_triangles", corner_triangles),       # 42
            ("center_hollow", center_hollow),             # 43
            ("window_panes", window_panes),               # 44
            # Category 7: Artistic (45-49)
            ("butterfly", butterfly),                     # 45
            ("flower_pattern", flower_pattern),           # 46
            ("scattered_islands", scattered_islands),     # 47
            ("diagonal_stripes", diagonal_stripes),       # 48
            ("honeycomb", honeycomb),                     # 49
        ]

        TOTAL_PATTERNS = 50

        # If pattern_index is specified, use that specific pattern
        if pattern_index is not None and 0 <= pattern_index < TOTAL_PATTERNS:
            pattern_name, pattern_fn = all_patterns[pattern_index]
            best_positions = pattern_fn()
            if not best_positions:
                # Fallback to filled rectangle if chosen pattern returns nothing
                best_positions = filled_rectangle()
        else:
            # Auto-select: Score all patterns and pick best match for target_count
            pattern_results = []
            for pattern_name, pattern_fn in all_patterns:
                try:
                    positions = pattern_fn()
                    if positions:
                        # Score based on how close to target count
                        score = -abs(len(positions) - target_count)
                        # Penalize if too few positions
                        if len(positions) < target_count * 0.7:
                            score -= 1000
                        # Bonus for visually interesting patterns
                        if pattern_name in ["star_five_point", "heart_shape", "butterfly", "flower_pattern"]:
                            score += 5
                        pattern_results.append((score, positions, pattern_name))
                except Exception:
                    continue

            if not pattern_results:
                return filled_rectangle()[:target_count]

            # Sort by score and pick best pattern
            pattern_results.sort(key=lambda x: x[0], reverse=True)
            _, best_positions, _ = pattern_results[0]

        # If we have too many positions, trim from edges (maintain symmetry)
        if len(best_positions) > target_count:
            def dist_from_center(pos: str) -> float:
                x, y = map(int, pos.split("_"))
                return ((x - center_x + 0.5) ** 2 + (y - center_y + 0.5) ** 2) ** 0.5
            best_positions.sort(key=dist_from_center)
            best_positions = best_positions[:target_count]

        return best_positions

    def _generate_random_positions(
        self, cols: int, rows: int, target_count: int, symmetry: str
    ) -> List[str]:
        """Generate random positions with optional symmetry."""
        if symmetry == "none":
            all_positions = [f"{x}_{y}" for x in range(cols) for y in range(rows)]
            return random.sample(all_positions, min(target_count, len(all_positions)))

        return self._apply_symmetry(cols, rows, target_count, symmetry, "random")

    def _generate_geometric_positions(
        self, cols: int, rows: int, target_count: int, symmetry: str
    ) -> List[str]:
        """Generate geometric pattern positions with proper symmetry support."""
        # For symmetry modes, generate in base region first, then mirror
        if symmetry == "horizontal":
            # Generate in left half, mirror to right
            base_cols = (cols + 1) // 2
            base_count = (target_count + 1) // 2
            # For symmetry, don't sample - use all positions from pattern
            base_positions = self._generate_base_geometric_for_symmetry(base_cols, rows, base_count)
            return self._mirror_horizontal(cols, rows, base_positions, target_count)

        elif symmetry == "vertical":
            # Generate in top half, mirror to bottom
            base_rows = (rows + 1) // 2
            base_count = (target_count + 1) // 2
            base_positions = self._generate_base_geometric_for_symmetry(cols, base_rows, base_count)
            return self._mirror_vertical(cols, rows, base_positions, target_count)

        elif symmetry == "both":
            # Generate in top-left quadrant, mirror to all 4 quadrants
            base_cols = (cols + 1) // 2
            base_rows = (rows + 1) // 2
            base_count = (target_count + 3) // 4
            base_positions = self._generate_base_geometric_for_symmetry(base_cols, base_rows, base_count)
            return self._mirror_both(cols, rows, base_positions, target_count)

        else:
            # No symmetry - generate full grid patterns with sampling
            return self._generate_base_geometric(cols, rows, target_count, 0, 0)

    def _generate_base_geometric_for_symmetry(
        self, cols: int, rows: int, target_count: int
    ) -> List[str]:
        """Generate geometric pattern for symmetry - returns deterministic positions."""
        center_x, center_y = cols // 2, rows // 2

        # Pattern 1: Filled rectangle from center
        rect_positions = []
        rect_size = int((target_count ** 0.5) * 1.2)
        rect_half = rect_size // 2
        for x in range(max(0, center_x - rect_half), min(cols, center_x + rect_half + 1)):
            for y in range(max(0, center_y - rect_half), min(rows, center_y + rect_half + 1)):
                rect_positions.append(f"{x}_{y}")

        # Pattern 2: Diamond shape
        diamond_positions = []
        radius = int((target_count / 2) ** 0.5) + 1
        for x in range(cols):
            for y in range(rows):
                dist = abs(x - center_x) + abs(y - center_y)
                if dist <= radius:
                    diamond_positions.append(f"{x}_{y}")

        # Pattern 3: Fill all (for maximum coverage)
        all_positions = []
        for x in range(cols):
            for y in range(rows):
                all_positions.append(f"{x}_{y}")

        # Choose the best fitting pattern - return ALL positions from chosen pattern
        # No sampling to preserve symmetry!
        all_patterns = [rect_positions, diamond_positions, all_positions]

        # Find pattern closest to target count
        chosen = min(all_patterns, key=lambda p: abs(len(p) - target_count))

        # If chosen pattern is too big and we need fewer positions,
        # use a deterministic subset (from center outward)
        if len(chosen) > target_count * 1.5:
            # Sort by distance from center and take closest positions
            def dist_from_center(pos: str) -> float:
                x, y = map(int, pos.split("_"))
                return abs(x - center_x) + abs(y - center_y)
            chosen = sorted(chosen, key=dist_from_center)[:target_count]

        return chosen

    def _generate_base_geometric(
        self, cols: int, rows: int, target_count: int, offset_x: int, offset_y: int
    ) -> List[str]:
        """Generate geometric pattern in a base region with diverse shapes."""
        # Random offset to avoid always-centered shapes
        offset_range_x = max(1, cols // 4)
        offset_range_y = max(1, rows // 4)
        rand_offset_x = random.randint(-offset_range_x, offset_range_x)
        rand_offset_y = random.randint(-offset_range_y, offset_range_y)
        center_x = cols // 2 + rand_offset_x
        center_y = rows // 2 + rand_offset_y

        # Clamp center to valid range
        center_x = max(1, min(cols - 2, center_x))
        center_y = max(1, min(rows - 2, center_y))

        all_patterns = []

        # Pattern 1: Filled rectangle (traditional)
        rect_positions = []
        rect_size = int((target_count ** 0.5) * 1.2)
        rect_half = rect_size // 2
        for x in range(max(0, center_x - rect_half), min(cols, center_x + rect_half + 1)):
            for y in range(max(0, center_y - rect_half), min(rows, center_y + rect_half + 1)):
                rect_positions.append(f"{x + offset_x}_{y + offset_y}")
        if rect_positions:
            all_patterns.append(rect_positions)

        # Pattern 2: Diamond shape
        diamond_positions = []
        radius = int((target_count / 2) ** 0.5) + 1
        for x in range(cols):
            for y in range(rows):
                dist = abs(x - center_x) + abs(y - center_y)
                if dist <= radius:
                    diamond_positions.append(f"{x + offset_x}_{y + offset_y}")
        if diamond_positions:
            all_patterns.append(diamond_positions)

        # Pattern 3: L-shape (multiple rotations)
        l_rotation = random.randint(0, 3)
        l_positions = self._generate_l_shape(cols, rows, target_count, l_rotation, offset_x, offset_y)
        if l_positions:
            all_patterns.append(l_positions)

        # Pattern 4: T-shape (multiple rotations)
        t_rotation = random.randint(0, 3)
        t_positions = self._generate_t_shape(cols, rows, target_count, t_rotation, offset_x, offset_y)
        if t_positions:
            all_patterns.append(t_positions)

        # Pattern 5: Cross/Plus shape
        cross_positions = self._generate_cross_shape(cols, rows, target_count, center_x, center_y, offset_x, offset_y)
        if cross_positions:
            all_patterns.append(cross_positions)

        # Pattern 6: Donut/Ring shape
        donut_positions = self._generate_donut_shape(cols, rows, target_count, center_x, center_y, offset_x, offset_y)
        if donut_positions:
            all_patterns.append(donut_positions)

        # Pattern 7: Zigzag pattern
        zigzag_positions = self._generate_zigzag_shape(cols, rows, target_count, offset_x, offset_y)
        if zigzag_positions:
            all_patterns.append(zigzag_positions)

        # Pattern 8: Diagonal stripe
        diagonal_positions = self._generate_diagonal_shape(cols, rows, target_count, offset_x, offset_y)
        if diagonal_positions:
            all_patterns.append(diagonal_positions)

        # Pattern 9: Corner cluster (L positioned at corner)
        corner_cluster = self._generate_corner_cluster(cols, rows, target_count, offset_x, offset_y)
        if corner_cluster:
            all_patterns.append(corner_cluster)

        # Pattern 10: Scattered clusters
        scattered_positions = self._generate_scattered_clusters(cols, rows, target_count, offset_x, offset_y)
        if scattered_positions:
            all_patterns.append(scattered_positions)

        # Pattern 11: Horizontal bar
        h_bar_positions = self._generate_horizontal_bar(cols, rows, target_count, center_y, offset_x, offset_y)
        if h_bar_positions:
            all_patterns.append(h_bar_positions)

        # Pattern 12: Vertical bar
        v_bar_positions = self._generate_vertical_bar(cols, rows, target_count, center_x, offset_x, offset_y)
        if v_bar_positions:
            all_patterns.append(v_bar_positions)

        # Randomly select from all valid patterns (not just closest to target)
        valid_patterns = [p for p in all_patterns if len(p) >= target_count * 0.7]

        if valid_patterns:
            # Randomly choose a pattern for variety
            chosen = random.choice(valid_patterns)
            selected = random.sample(chosen, min(target_count, len(chosen)))
        else:
            # Fallback: use all positions and sample
            all_positions = [f"{x + offset_x}_{y + offset_y}" for x in range(cols) for y in range(rows)]
            selected = random.sample(all_positions, min(target_count, len(all_positions)))

        # Apply random position perturbation for additional diversity
        # This shifts the entire pattern by a random offset
        shift_x = random.randint(-2, 2)
        shift_y = random.randint(-2, 2)
        shifted = []
        for pos in selected:
            x, y = map(int, pos.split("_"))
            new_x = max(0, min(cols - 1, x + shift_x))
            new_y = max(0, min(rows - 1, y + shift_y))
            shifted.append(f"{new_x}_{new_y}")

        # Remove duplicates that may have been created by shifting
        shifted = list(set(shifted))

        # If we lost too many tiles due to deduplication, add random positions
        if len(shifted) < target_count:
            all_positions = [f"{x}_{y}" for x in range(cols) for y in range(rows)]
            available = [p for p in all_positions if p not in shifted]
            if available:
                extra = random.sample(available, min(target_count - len(shifted), len(available)))
                shifted.extend(extra)

        return shifted[:target_count]

    def _generate_l_shape(
        self, cols: int, rows: int, target_count: int, rotation: int, offset_x: int, offset_y: int
    ) -> List[str]:
        """Generate L-shaped pattern with rotation."""
        positions = []
        size = int((target_count / 2) ** 0.5) + 2
        thickness = max(2, size // 2)

        # Base L shape (rotation 0: vertical bar on left, horizontal bar on bottom)
        for x in range(cols):
            for y in range(rows):
                in_vertical = (x < thickness and y < size)
                in_horizontal = (y >= size - thickness and x < size)

                # Apply rotation
                if rotation == 0:
                    if in_vertical or in_horizontal:
                        positions.append(f"{x + offset_x}_{y + offset_y}")
                elif rotation == 1:  # 90 degrees
                    if (y < thickness and x < size) or (x >= size - thickness and y < size):
                        positions.append(f"{x + offset_x}_{y + offset_y}")
                elif rotation == 2:  # 180 degrees
                    if (x >= cols - thickness and y >= rows - size) or (y < thickness and x >= cols - size):
                        positions.append(f"{x + offset_x}_{y + offset_y}")
                elif rotation == 3:  # 270 degrees
                    if (y >= rows - thickness and x >= cols - size) or (x < thickness and y >= rows - size):
                        positions.append(f"{x + offset_x}_{y + offset_y}")

        return positions

    def _generate_t_shape(
        self, cols: int, rows: int, target_count: int, rotation: int, offset_x: int, offset_y: int
    ) -> List[str]:
        """Generate T-shaped pattern with rotation."""
        positions = []
        center_x, center_y = cols // 2, rows // 2
        arm_length = int((target_count / 3) ** 0.5) + 1
        thickness = max(2, arm_length // 2)

        for x in range(cols):
            for y in range(rows):
                # T shape based on rotation
                if rotation == 0:  # T pointing down
                    in_horizontal = (abs(y - center_y) < thickness and x < cols)
                    in_vertical = (abs(x - center_x) < thickness and y >= center_y)
                elif rotation == 1:  # T pointing left
                    in_vertical = (abs(x - center_x) < thickness and y < rows)
                    in_horizontal = (abs(y - center_y) < thickness and x <= center_x)
                elif rotation == 2:  # T pointing up
                    in_horizontal = (abs(y - center_y) < thickness and x < cols)
                    in_vertical = (abs(x - center_x) < thickness and y <= center_y)
                else:  # T pointing right
                    in_vertical = (abs(x - center_x) < thickness and y < rows)
                    in_horizontal = (abs(y - center_y) < thickness and x >= center_x)

                if in_horizontal or in_vertical:
                    positions.append(f"{x + offset_x}_{y + offset_y}")

        return positions

    def _generate_cross_shape(
        self, cols: int, rows: int, target_count: int, center_x: int, center_y: int, offset_x: int, offset_y: int
    ) -> List[str]:
        """Generate cross/plus shaped pattern."""
        positions = []
        arm_length = int((target_count / 4) ** 0.5) + 1
        thickness = max(1, arm_length // 2)

        for x in range(cols):
            for y in range(rows):
                # Horizontal arm
                in_horizontal = (abs(y - center_y) < thickness and abs(x - center_x) <= arm_length)
                # Vertical arm
                in_vertical = (abs(x - center_x) < thickness and abs(y - center_y) <= arm_length)

                if in_horizontal or in_vertical:
                    positions.append(f"{x + offset_x}_{y + offset_y}")

        return positions

    def _generate_donut_shape(
        self, cols: int, rows: int, target_count: int, center_x: int, center_y: int, offset_x: int, offset_y: int
    ) -> List[str]:
        """Generate donut/ring shaped pattern with hollow center."""
        positions = []
        outer_radius = int((target_count / 2.5) ** 0.5) + 2
        inner_radius = max(1, outer_radius // 2)

        for x in range(cols):
            for y in range(rows):
                dist = ((x - center_x) ** 2 + (y - center_y) ** 2) ** 0.5
                if inner_radius <= dist <= outer_radius:
                    positions.append(f"{x + offset_x}_{y + offset_y}")

        return positions

    def _generate_zigzag_shape(
        self, cols: int, rows: int, target_count: int, offset_x: int, offset_y: int
    ) -> List[str]:
        """Generate zigzag pattern."""
        positions = []
        amplitude = max(1, rows // 4)
        thickness = max(2, int((target_count / rows) ** 0.5))

        for x in range(cols):
            # Zigzag center line
            zigzag_y = rows // 2 + int(amplitude * (1 if (x // 2) % 2 == 0 else -1))
            for y in range(rows):
                if abs(y - zigzag_y) < thickness:
                    positions.append(f"{x + offset_x}_{y + offset_y}")

        return positions

    def _generate_diagonal_shape(
        self, cols: int, rows: int, target_count: int, offset_x: int, offset_y: int
    ) -> List[str]:
        """Generate diagonal stripe pattern."""
        positions = []
        thickness = max(2, int((target_count / max(cols, rows)) ** 0.5) + 1)
        direction = random.choice([1, -1])  # 1 = top-left to bottom-right, -1 = top-right to bottom-left

        for x in range(cols):
            for y in range(rows):
                # Diagonal line: y = x (or y = -x) with some offset
                if direction == 1:
                    diag_dist = abs(y - x)
                else:
                    diag_dist = abs(y - (cols - 1 - x))

                if diag_dist < thickness:
                    positions.append(f"{x + offset_x}_{y + offset_y}")

        return positions

    def _generate_corner_cluster(
        self, cols: int, rows: int, target_count: int, offset_x: int, offset_y: int
    ) -> List[str]:
        """Generate cluster positioned at a random corner."""
        positions = []
        corner = random.randint(0, 3)
        cluster_size = int((target_count ** 0.5)) + 1

        # Determine corner position
        if corner == 0:  # Top-left
            start_x, start_y = 0, 0
        elif corner == 1:  # Top-right
            start_x, start_y = max(0, cols - cluster_size), 0
        elif corner == 2:  # Bottom-left
            start_x, start_y = 0, max(0, rows - cluster_size)
        else:  # Bottom-right
            start_x, start_y = max(0, cols - cluster_size), max(0, rows - cluster_size)

        for x in range(start_x, min(cols, start_x + cluster_size)):
            for y in range(start_y, min(rows, start_y + cluster_size)):
                positions.append(f"{x + offset_x}_{y + offset_y}")

        return positions

    def _generate_scattered_clusters(
        self, cols: int, rows: int, target_count: int, offset_x: int, offset_y: int
    ) -> List[str]:
        """Generate multiple small scattered clusters."""
        positions = set()
        num_clusters = random.randint(3, 5)
        tiles_per_cluster = target_count // num_clusters
        cluster_radius = max(1, int((tiles_per_cluster / 3.14) ** 0.5))

        for _ in range(num_clusters):
            # Random cluster center
            cx = random.randint(cluster_radius, cols - cluster_radius - 1)
            cy = random.randint(cluster_radius, rows - cluster_radius - 1)

            for x in range(cols):
                for y in range(rows):
                    dist = ((x - cx) ** 2 + (y - cy) ** 2) ** 0.5
                    if dist <= cluster_radius:
                        positions.add(f"{x + offset_x}_{y + offset_y}")

        return list(positions)

    def _generate_horizontal_bar(
        self, cols: int, rows: int, target_count: int, center_y: int, offset_x: int, offset_y: int
    ) -> List[str]:
        """Generate horizontal bar pattern."""
        positions = []
        bar_height = max(2, target_count // cols + 1)

        for x in range(cols):
            for y in range(max(0, center_y - bar_height // 2), min(rows, center_y + bar_height // 2 + 1)):
                positions.append(f"{x + offset_x}_{y + offset_y}")

        return positions

    def _generate_vertical_bar(
        self, cols: int, rows: int, target_count: int, center_x: int, offset_x: int, offset_y: int
    ) -> List[str]:
        """Generate vertical bar pattern."""
        positions = []
        bar_width = max(2, target_count // rows + 1)

        for x in range(max(0, center_x - bar_width // 2), min(cols, center_x + bar_width // 2 + 1)):
            for y in range(rows):
                positions.append(f"{x + offset_x}_{y + offset_y}")

        return positions

    def _mirror_horizontal(
        self, cols: int, rows: int, base_positions: List[str], target_count: int
    ) -> List[str]:
        """Mirror positions horizontally (left to right).

        Note: Returns all mirrored positions to preserve symmetry.
        The target_count is used only to limit base position generation.
        """
        result = set()
        for pos in base_positions:
            x, y = map(int, pos.split("_"))
            result.add(f"{x}_{y}")
            mirror_x = cols - 1 - x
            if 0 <= mirror_x < cols:
                result.add(f"{mirror_x}_{y}")
        # Return all positions to preserve symmetry - don't slice!
        return list(result)

    def _mirror_vertical(
        self, cols: int, rows: int, base_positions: List[str], target_count: int
    ) -> List[str]:
        """Mirror positions vertically (top to bottom).

        Note: Returns all mirrored positions to preserve symmetry.
        """
        result = set()
        for pos in base_positions:
            x, y = map(int, pos.split("_"))
            result.add(f"{x}_{y}")
            mirror_y = rows - 1 - y
            if 0 <= mirror_y < rows:
                result.add(f"{x}_{mirror_y}")
        return list(result)

    def _mirror_both(
        self, cols: int, rows: int, base_positions: List[str], target_count: int
    ) -> List[str]:
        """Mirror positions in all 4 directions.

        Note: Returns all mirrored positions to preserve symmetry.
        """
        result = set()
        for pos in base_positions:
            x, y = map(int, pos.split("_"))
            mirror_x = cols - 1 - x
            mirror_y = rows - 1 - y
            # Add all 4 quadrants
            result.add(f"{x}_{y}")
            if 0 <= mirror_x < cols:
                result.add(f"{mirror_x}_{y}")
            if 0 <= mirror_y < rows:
                result.add(f"{x}_{mirror_y}")
            if 0 <= mirror_x < cols and 0 <= mirror_y < rows:
                result.add(f"{mirror_x}_{mirror_y}")
        return list(result)

    def _apply_symmetry_to_positions(
        self, cols: int, rows: int, positions: List[str], symmetry: str, target_count: int
    ) -> List[str]:
        """Apply symmetry transformation to a set of positions.

        Takes existing positions and enforces the specified symmetry by:
        1. Keeping positions in one half of the grid
        2. Mirroring them to create perfect symmetry
        """
        if symmetry == "horizontal":
            # Keep only left half, then mirror to right
            center_x = cols / 2.0
            base_positions = []
            for pos in positions:
                x, y = map(int, pos.split("_"))
                if x < center_x or (cols % 2 == 1 and x == cols // 2):
                    base_positions.append(pos)
            return self._mirror_horizontal(cols, rows, base_positions, target_count)

        elif symmetry == "vertical":
            # Keep only top half, then mirror to bottom
            center_y = rows / 2.0
            base_positions = []
            for pos in positions:
                x, y = map(int, pos.split("_"))
                if y < center_y or (rows % 2 == 1 and y == rows // 2):
                    base_positions.append(pos)
            return self._mirror_vertical(cols, rows, base_positions, target_count)

        elif symmetry == "both":
            # Keep only top-left quadrant, then mirror to all 4
            center_x = cols / 2.0
            center_y = rows / 2.0
            base_positions = []
            for pos in positions:
                x, y = map(int, pos.split("_"))
                in_x = x < center_x or (cols % 2 == 1 and x == cols // 2)
                in_y = y < center_y or (rows % 2 == 1 and y == rows // 2)
                if in_x and in_y:
                    base_positions.append(pos)
            return self._mirror_both(cols, rows, base_positions, target_count)

        # No symmetry - return as-is
        return positions

    def _generate_clustered_positions(
        self, cols: int, rows: int, target_count: int, symmetry: str
    ) -> List[str]:
        """Generate clustered positions with proper symmetry support."""
        # For symmetry modes, generate in base region first, then mirror
        if symmetry == "horizontal":
            base_cols = (cols + 1) // 2
            base_count = (target_count + 1) // 2
            base_positions = self._generate_base_clustered_for_symmetry(base_cols, rows, base_count)
            return self._mirror_horizontal(cols, rows, base_positions, target_count)

        elif symmetry == "vertical":
            base_rows = (rows + 1) // 2
            base_count = (target_count + 1) // 2
            base_positions = self._generate_base_clustered_for_symmetry(cols, base_rows, base_count)
            return self._mirror_vertical(cols, rows, base_positions, target_count)

        elif symmetry == "both":
            base_cols = (cols + 1) // 2
            base_rows = (rows + 1) // 2
            base_count = (target_count + 3) // 4
            base_positions = self._generate_base_clustered_for_symmetry(base_cols, base_rows, base_count)
            return self._mirror_both(cols, rows, base_positions, target_count)

        else:
            return self._generate_base_clustered(cols, rows, target_count)

    def _generate_base_clustered_for_symmetry(
        self, cols: int, rows: int, target_count: int
    ) -> List[str]:
        """Generate clustered positions for symmetry - deterministic, no random sampling."""
        # Use center of base region as cluster center
        center_x, center_y = cols // 2, rows // 2

        # Generate all positions within cluster radius
        cluster_radius = int((target_count / 3.14) ** 0.5) + 1
        positions = []

        for x in range(cols):
            for y in range(rows):
                dist = ((x - center_x) ** 2 + (y - center_y) ** 2) ** 0.5
                if dist <= cluster_radius:
                    positions.append((dist, f"{x}_{y}"))

        # Sort by distance and take closest positions (deterministic)
        positions.sort(key=lambda p: p[0])
        result = [pos for _, pos in positions]

        # If we have too many, take the closest to center
        if len(result) > target_count * 1.5:
            result = result[:target_count]

        return result

    def _generate_base_clustered(
        self, cols: int, rows: int, target_count: int
    ) -> List[str]:
        """Generate clustered positions in a base region (with randomness for non-symmetric)."""
        positions = set()

        # Create 1-3 cluster centers
        num_clusters = random.randint(1, min(3, max(1, target_count // 6)))
        tiles_per_cluster = target_count // max(1, num_clusters)

        # Generate cluster centers (avoid edges)
        margin = max(1, min(cols, rows) // 4)
        cluster_centers = []

        for _ in range(num_clusters):
            cx = random.randint(margin, max(margin, cols - margin - 1)) if cols > 2 * margin else cols // 2
            cy = random.randint(margin, max(margin, rows - margin - 1)) if rows > 2 * margin else rows // 2
            cluster_centers.append((cx, cy))

        # Generate positions around each cluster center
        for cx, cy in cluster_centers:
            cluster_radius = int((tiles_per_cluster / 3.14) ** 0.5) + 1
            cluster_positions = []

            for x in range(max(0, cx - cluster_radius), min(cols, cx + cluster_radius + 1)):
                for y in range(max(0, cy - cluster_radius), min(rows, cy + cluster_radius + 1)):
                    dist = ((x - cx) ** 2 + (y - cy) ** 2) ** 0.5
                    if dist <= cluster_radius:
                        cluster_positions.append(f"{x}_{y}")

            sample_count = min(tiles_per_cluster, len(cluster_positions))
            if sample_count > 0:
                sampled = random.sample(cluster_positions, sample_count)
                positions.update(sampled)

        # Fill remaining if needed
        all_positions = [f"{x}_{y}" for x in range(cols) for y in range(rows)]
        remaining = [p for p in all_positions if p not in positions]

        while len(positions) < target_count and remaining:
            pos = random.choice(remaining)
            remaining.remove(pos)
            positions.add(pos)

        return list(positions)[:target_count]

    def _apply_symmetry(
        self, cols: int, rows: int, target_count: int, symmetry: str, pattern: str
    ) -> List[str]:
        """Apply symmetry by generating half and mirroring."""
        if symmetry == "horizontal":
            # Left-right symmetry: generate left half, mirror to right
            half_cols = (cols + 1) // 2
            half_count = (target_count + 1) // 2

            # Generate positions in left half
            left_positions = [f"{x}_{y}" for x in range(half_cols) for y in range(rows)]
            selected_left = random.sample(left_positions, min(half_count, len(left_positions)))

            # Mirror to right
            result = set()
            for pos in selected_left:
                x, y = map(int, pos.split("_"))
                result.add(pos)
                mirror_x = cols - 1 - x
                if mirror_x >= 0 and mirror_x < cols:
                    result.add(f"{mirror_x}_{y}")

            return list(result)[:target_count]

        elif symmetry == "vertical":
            # Top-bottom symmetry: generate top half, mirror to bottom
            half_rows = (rows + 1) // 2
            half_count = (target_count + 1) // 2

            top_positions = [f"{x}_{y}" for x in range(cols) for y in range(half_rows)]
            selected_top = random.sample(top_positions, min(half_count, len(top_positions)))

            result = set()
            for pos in selected_top:
                x, y = map(int, pos.split("_"))
                result.add(pos)
                mirror_y = rows - 1 - y
                if mirror_y >= 0 and mirror_y < rows:
                    result.add(f"{x}_{mirror_y}")

            return list(result)[:target_count]

        elif symmetry == "both":
            # 4-way symmetry: generate top-left quadrant, mirror to all
            half_cols = (cols + 1) // 2
            half_rows = (rows + 1) // 2
            quarter_count = (target_count + 3) // 4

            quadrant_positions = [f"{x}_{y}" for x in range(half_cols) for y in range(half_rows)]
            selected_quadrant = random.sample(quadrant_positions, min(quarter_count, len(quadrant_positions)))

            result = set()
            for pos in selected_quadrant:
                x, y = map(int, pos.split("_"))
                # Add all 4 symmetric positions
                result.add(f"{x}_{y}")
                mirror_x = cols - 1 - x
                mirror_y = rows - 1 - y
                if mirror_x >= 0 and mirror_x < cols:
                    result.add(f"{mirror_x}_{y}")
                if mirror_y >= 0 and mirror_y < rows:
                    result.add(f"{x}_{mirror_y}")
                if mirror_x >= 0 and mirror_x < cols and mirror_y >= 0 and mirror_y < rows:
                    result.add(f"{mirror_x}_{mirror_y}")

            return list(result)[:target_count]

        # Default: no symmetry
        all_positions = [f"{x}_{y}" for x in range(cols) for y in range(rows)]
        return random.sample(all_positions, min(target_count, len(all_positions)))

    def _is_position_covered_by_upper(
        self, level: Dict[str, Any], layer_idx: int, col: int, row: int
    ) -> bool:
        """Check if a position is covered by tiles in upper layers.

        Based on sp_template TileGroup.FindAllUpperTiles logic:
        - Same parity (layer 0→2, 1→3): Check same position only
        - Different parity: Compare layer col sizes to determine offset direction
          - Upper layer col > current layer col: Check (0,0), (+1,0), (0,+1), (+1,+1)
          - Upper layer col <= current layer col: Check (-1,-1), (0,-1), (-1,0), (0,0)

        Parity is determined by layer_idx % 2.
        """
        num_layers = level.get("layer", 8)

        # Early exit if on top layer
        if layer_idx >= num_layers - 1:
            return False

        tile_parity = layer_idx % 2
        cur_layer_data = level.get(f"layer_{layer_idx}", {})
        cur_layer_col = int(cur_layer_data.get("col", 7))

        # Blocking offsets based on parity
        BLOCKING_OFFSETS_SAME_PARITY = ((0, 0),)
        BLOCKING_OFFSETS_UPPER_BIGGER = ((0, 0), (1, 0), (0, 1), (1, 1))
        BLOCKING_OFFSETS_UPPER_SMALLER = ((-1, -1), (0, -1), (-1, 0), (0, 0))

        for upper_layer_idx in range(layer_idx + 1, num_layers):
            upper_layer_key = f"layer_{upper_layer_idx}"
            upper_layer_data = level.get(upper_layer_key, {})
            upper_tiles = upper_layer_data.get("tiles", {})

            if not upper_tiles:
                continue

            upper_parity = upper_layer_idx % 2
            upper_layer_col = int(upper_layer_data.get("col", 7))

            # Determine blocking positions based on parity and layer size
            if tile_parity == upper_parity:
                # Same parity (odd-odd or even-even): only check same position
                blocking_offsets = BLOCKING_OFFSETS_SAME_PARITY
            else:
                # Different parity: compare layer col sizes
                if upper_layer_col > cur_layer_col:
                    # Upper layer is bigger (has more columns)
                    blocking_offsets = BLOCKING_OFFSETS_UPPER_BIGGER
                else:
                    # Upper layer is smaller or same size
                    blocking_offsets = BLOCKING_OFFSETS_UPPER_SMALLER

            for dx, dy in blocking_offsets:
                bx = col + dx
                by = row + dy
                pos_key = f"{bx}_{by}"
                if pos_key in upper_tiles:
                    return True

        return False

    def _add_tutorial_gimmick(
        self, level: Dict[str, Any], gimmick_type: str, min_count: int = 2
    ) -> Dict[str, Any]:
        """
        Add tutorial gimmick to the top layer for tutorial UI display.

        Tutorial gimmicks are placed on the topmost layer with tiles to make them
        immediately visible when the level starts, facilitating tutorial UI overlay.

        Args:
            level: Level data to modify
            gimmick_type: Type of gimmick to add (e.g., 'chain', 'ice', 'frog')
            min_count: Minimum number of gimmicks to place (default: 2)

        Returns:
            Modified level with tutorial gimmicks placed on top layer
        """
        num_layers = level.get("layer", 8)

        # Find the topmost layer with tiles (higher layer index = visually on top)
        # layer_7 (highest index) = TOP (displayed first, blocking layers below)
        # layer_6, layer_5, etc. = layers below
        # This matches the game's visual layer system where higher indices are rendered on top
        top_layer_idx = -1
        for i in range(num_layers - 1, -1, -1):  # num_layers-1 → ... → 0 (highest first)
            layer_key = f"layer_{i}"
            layer_tiles = level.get(layer_key, {}).get("tiles", {})
            if layer_tiles:
                top_layer_idx = i
                break

        if top_layer_idx < 0:
            return level  # No tiles found

        layer_key = f"layer_{top_layer_idx}"
        layer_data = level.get(layer_key, {})
        tiles = layer_data.get("tiles", {})

        # Find eligible tiles (normal tiles without existing gimmicks)
        eligible_positions = []
        for pos, tile_data in tiles.items():
            if not isinstance(tile_data, list) or len(tile_data) == 0:
                continue
            tile_type = tile_data[0]
            # Skip goal tiles (craft_*, stack_*)
            if isinstance(tile_type, str) and (tile_type.startswith("craft_") or tile_type.startswith("stack_")):
                continue
            # Skip tiles with existing gimmicks
            gimmick = tile_data[1] if len(tile_data) > 1 else ""
            if gimmick:
                continue
            eligible_positions.append(pos)

        if not eligible_positions:
            return level  # No eligible positions

        # Place gimmicks on top layer
        positions_to_use = min(min_count, len(eligible_positions))
        random.shuffle(eligible_positions)

        # Map gimmick types to their attribute format
        GIMMICK_ATTRIBUTES = {
            "chain": "chain",
            "ice": "ice",
            "frog": "frog",
            "grass": "grass",
            "bomb": "bomb",
            "curtain": "curtain",
            "crate": "crate",
            "link": "link_e",  # Default to east direction for link
            "teleport": "teleport",
        }

        gimmick_attr = GIMMICK_ATTRIBUTES.get(gimmick_type, gimmick_type)

        placed_count = 0
        for pos in eligible_positions[:positions_to_use]:
            tile_data = tiles[pos]
            if len(tile_data) == 1:
                tile_data.append(gimmick_attr)
            else:
                tile_data[1] = gimmick_attr
            placed_count += 1
            logger.debug(f"Tutorial gimmick '{gimmick_attr}' placed at layer {top_layer_idx}, pos {pos}")

        logger.info(f"Tutorial gimmick '{gimmick_type}' placed: {placed_count} tiles on layer {top_layer_idx}")

        return level

    def _add_obstacles(
        self, level: Dict[str, Any], params: GenerationParams
    ) -> Dict[str, Any]:
        """Add obstacles and attributes to tiles following game rules."""
        # Use None check to allow empty list (empty list means no obstacles)
        obstacle_types = params.obstacle_types if params.obstacle_types is not None else ["chain", "frog"]
        target = params.target_difficulty

        # Get gimmick intensity multiplier (0.0 = no gimmicks, 1.0 = normal, 2.0 = double)
        gimmick_intensity = getattr(params, 'gimmick_intensity', 1.0)

        # If gimmick_intensity is 0, skip all obstacle generation (except tutorial gimmick)
        tutorial_gimmick = getattr(params, 'tutorial_gimmick', None)
        tutorial_gimmick_min_count = getattr(params, 'tutorial_gimmick_min_count', 2)

        # Handle tutorial gimmick first (always placed on top layer for tutorial UI)
        logger.info(f"[_add_obstacles] tutorial_gimmick={tutorial_gimmick}, min_count={tutorial_gimmick_min_count}")
        if tutorial_gimmick:
            logger.info(f"[_add_obstacles] Calling _add_tutorial_gimmick with gimmick_type={tutorial_gimmick}")
            level = self._add_tutorial_gimmick(level, tutorial_gimmick, tutorial_gimmick_min_count)

        if gimmick_intensity <= 0:
            return level

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
                # Apply gimmick_intensity to configured counts
                return int(random.randint(min_count, max_count) * gimmick_intensity)
            # Legacy behavior: scale with difficulty AND gimmick_intensity
            return int(total_tiles * target * default_ratio * gimmick_intensity)

        # Helper to get per-layer obstacle target
        def get_layer_target(layer_idx: int, obstacle_type: str) -> Optional[int]:
            config = params.get_layer_obstacle_config(layer_idx, obstacle_type)
            if config is not None:
                min_count, max_count = config
                # Apply gimmick_intensity to per-layer configs
                return int(random.randint(min_count, max_count) * gimmick_intensity)
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
        #
        # Tile Buster style gimmick distribution:
        # - Gimmicks should be conservative, typically 10-20% of tiles at max difficulty
        # - S grade (0-0.2): ~0% gimmicks
        # - A grade (0.2-0.4): ~3-5% total gimmicks
        # - B grade (0.4-0.6): ~5-8% total gimmicks
        # - C grade (0.6-0.8): ~8-12% total gimmicks
        # - D grade (0.8-1.0): ~12-15% total gimmicks
        #
        # Reduced ratios to match Tile Buster style (was: chain=0.15, frog=0.08, ice=0.12)
        # Target: ~10-15% total gimmicks at max difficulty
        global_targets = {
            "chain": get_global_target("chain", 0.04),
            "frog": get_global_target("frog", 0.02),
            "link": get_global_target("link", 0.02),
            "grass": get_global_target("grass", 0.03),
            "ice": get_global_target("ice", 0.03),
            "bomb": get_global_target("bomb", 0.01),
            "curtain": get_global_target("curtain", 0.02),
            "teleport": get_global_target("teleport", 0.01),
            "crate": get_global_target("crate", 0.02),
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
        """Add frog obstacles to a specific layer.

        RULE: Frogs must only be placed on tiles that are NOT covered by upper layers.
        This is because frogs need to be immediately selectable when the level spawns.
        """
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

            # RULE: Skip positions covered by upper layers (frogs must be selectable at spawn)
            try:
                col, row = map(int, pos.split('_'))
                if self._is_position_covered_by_upper(level, layer_idx, col, row):
                    continue
            except:
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
        """Add frog obstacles.

        RULE: Frogs must only be placed on tiles that are NOT covered by upper layers.
        This is because frogs need to be immediately selectable when the level spawns.
        """
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

                # RULE: Skip positions covered by upper layers (frogs must be selectable at spawn)
                try:
                    col, row = map(int, pos.split('_'))
                    if self._is_position_covered_by_upper(level, i, col, row):
                        continue
                except:
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
        center_row = rows // 2
        symmetry_mode = params.symmetry_mode or "none"
        placed_positions = set()  # Track positions used by goals
        output_positions = set()  # Track output positions of goals
        goal_positions_info = []  # Track (pos, goal_type) for adjacency check

        def is_self_symmetric_position(col: int, row: int) -> bool:
            """Check if position is its own mirror (for placing single goals in symmetric mode)."""
            if symmetry_mode == "horizontal":
                # For horizontal symmetry, only the exact center column(s) work
                # But for even cols, there's no perfect center. Allow near-center.
                mirror_col = cols - 1 - col
                return col == mirror_col  # Only true if col == (cols-1)/2, i.e., odd cols
            elif symmetry_mode == "vertical":
                mirror_row = rows - 1 - row
                return row == mirror_row
            elif symmetry_mode == "both":
                mirror_col = cols - 1 - col
                mirror_row = rows - 1 - row
                return col == mirror_col and row == mirror_row
            return True  # No symmetry, any position works

        def get_preferred_columns_for_symmetry() -> List[int]:
            """Get column order that respects symmetry."""
            if symmetry_mode in ("horizontal", "both"):
                # For horizontal symmetry, prefer center column
                # If cols=8, center is between 3 and 4. For even cols, prefer 3 or 4.
                if cols % 2 == 1:
                    # Odd cols: exact center exists
                    return [cols // 2]
                else:
                    # Even cols: no exact center, use the two middle columns
                    # They are at (cols//2 - 1) and (cols//2)
                    # e.g., for cols=8: 3 and 4
                    return [cols // 2 - 1, cols // 2]
            else:
                # No horizontal symmetry constraint
                return list(range(cols))

        def get_adjacent_positions(col: int, row: int) -> set:
            """Get all adjacent positions (including diagonals)."""
            adjacent = set()
            for dc in [-1, 0, 1]:
                for dr in [-1, 0, 1]:
                    if dc == 0 and dr == 0:
                        continue
                    adjacent.add(f"{col + dc}_{row + dr}")
            return adjacent

        def would_face_each_other(pos1: str, type1: str, pos2: str, type2: str) -> bool:
            """Check if two craft tiles would face each other (output into each other)."""
            col1, row1 = map(int, pos1.split("_"))
            col2, row2 = map(int, pos2.split("_"))

            dir1 = type1[-1] if type1.endswith(('_s', '_n', '_e', '_w')) else 's'
            dir2 = type2[-1] if type2.endswith(('_s', '_n', '_e', '_w')) else 's'

            # Get output positions
            offsets = {'s': (0, 1), 'n': (0, -1), 'e': (1, 0), 'w': (-1, 0)}
            out1 = (col1 + offsets[dir1][0], row1 + offsets[dir1][1])
            out2 = (col2 + offsets[dir2][0], row2 + offsets[dir2][1])

            # Check if they face each other (output to each other's position)
            if out1 == (col2, row2) or out2 == (col1, row1):
                return True

            # Check if outputs collide
            if out1 == out2:
                return True

            return False

        for i, goal in enumerate(goals):
            # Handle both old format (type="craft_s") and new format (type="craft", direction="s")
            base_type = goal.get("type", "craft")
            goal_direction = goal.get("direction") or "s"  # Handle None value

            # If type already includes direction suffix, use as-is
            if base_type.endswith(('_s', '_n', '_e', '_w')):
                goal_type = base_type
            else:
                # Combine type and direction
                goal_type = f"{base_type}_{goal_direction}"

            goal_count = goal.get("count", 3)

            # Calculate preferred column with more spacing between goals
            # For symmetric modes, prefer center columns
            if symmetry_mode in ("horizontal", "both"):
                preferred_cols = get_preferred_columns_for_symmetry()
                target_col = preferred_cols[i % len(preferred_cols)]
            else:
                spacing = 2  # Minimum 2 columns apart
                target_col = center_col - (len(goals) * spacing) // 2 + i * spacing
            target_col = max(0, min(cols - 1, target_col))

            # Find valid position considering direction rules
            pos = None
            row_order = get_row_search_order(goal_type)

            # Build column search order - RANDOMIZED for variety
            if symmetry_mode in ("horizontal", "both"):
                # Start with preferred symmetric columns, then expand outward
                preferred = get_preferred_columns_for_symmetry()
                col_search_order = preferred[:]
                for offset in range(1, cols):
                    for c in preferred:
                        if c - offset >= 0 and (c - offset) not in col_search_order:
                            col_search_order.append(c - offset)
                        if c + offset < cols and (c + offset) not in col_search_order:
                            col_search_order.append(c + offset)
            else:
                # Randomized column search for variety in goal placement
                col_search_order = list(range(cols))
                random.shuffle(col_search_order)

            # Randomize row order while respecting direction constraints
            # (e.g., craft_s can't be at bottom row, craft_n can't be at top row)
            row_order_list = list(row_order)
            random.shuffle(row_order_list)

            # Try positions in randomized order
            for try_row in row_order_list:
                for try_col in col_search_order:
                    try_pos = f"{try_col}_{try_row}"

                    # Check if position is not occupied and not already used
                    if try_pos in tiles or try_pos in placed_positions:
                        continue

                    # Check if this position is valid for the goal direction
                    if not is_valid_goal_position(try_col, try_row, goal_type):
                        continue

                    # Get output position for this goal
                    col_off, row_off = get_output_direction(goal_type)
                    output_pos = f"{try_col + col_off}_{try_row + row_off}"

                    # Check output position is not occupied
                    if output_pos in tiles or output_pos in placed_positions or output_pos in output_positions:
                        continue

                    # Check no adjacent to existing goals (minimum 1 cell gap)
                    adjacent = get_adjacent_positions(try_col, try_row)
                    if adjacent & placed_positions:
                        continue

                    # Check output position adjacency
                    output_adjacent = get_adjacent_positions(try_col + col_off, try_row + row_off)
                    if output_adjacent & output_positions:
                        continue

                    # Check not facing any existing goal
                    facing_conflict = False
                    for existing_pos, existing_type in goal_positions_info:
                        if would_face_each_other(try_pos, goal_type, existing_pos, existing_type):
                            facing_conflict = True
                            break
                    if facing_conflict:
                        continue

                    pos = try_pos
                    break
                if pos:
                    break

            if pos:
                p_col, p_row = map(int, pos.split("_"))
                col_off, row_off = get_output_direction(goal_type)
                output_pos = f"{p_col + col_off}_{p_row + row_off}"

                placed_positions.add(pos)
                output_positions.add(output_pos)
                goal_positions_info.append((pos, goal_type))

                tiles[pos] = [goal_type, "", [goal_count]]

        # Update tile count
        level[layer_key]["num"] = str(len(tiles))

        # Set goalCount for the level - ONLY include goals that were actually placed
        # Build goalCount from successfully placed tiles, not from requested goals
        goalCount = {}
        for pos, tile_data in tiles.items():
            if isinstance(tile_data, list) and len(tile_data) > 0:
                tile_type = tile_data[0]
                # Check if it's a craft/stack goal tile
                if isinstance(tile_type, str) and (tile_type.startswith("craft_") or tile_type.startswith("stack_")):
                    # Extract count from tile_data[2]
                    tile_count = 1
                    if len(tile_data) > 2:
                        extra = tile_data[2]
                        if isinstance(extra, list) and len(extra) > 0:
                            tile_count = int(extra[0]) if extra[0] else 1
                        elif isinstance(extra, (int, float)):
                            tile_count = int(extra)
                    goalCount[tile_type] = goalCount.get(tile_type, 0) + tile_count

        # Warn if not all requested goals were placed
        requested_goals = set()
        for goal in goals:
            base_type = goal.get("type", "craft")
            direction = goal.get("direction") or "s"
            if base_type.endswith(('_s', '_n', '_e', '_w')):
                full_goal_type = base_type
            else:
                full_goal_type = f"{base_type}_{direction}"
            requested_goals.add(full_goal_type)

        placed_goals = set(goalCount.keys())
        missing_goals = requested_goals - placed_goals
        if missing_goals:
            logger.warning(f"Could not place some goals: {missing_goals}. Placed: {placed_goals}")

        level["goalCount"] = goalCount

        return level

    def _adjust_difficulty(
        self, level: Dict[str, Any], target: float, max_tiles: Optional[int] = None, params: Optional["GenerationParams"] = None
    ) -> Dict[str, Any]:
        """Adjust level to match target difficulty within tolerance.

        Args:
            level: The level to adjust
            target: Target difficulty (0.0-1.0)
            max_tiles: If specified, don't add tiles beyond this count
            params: Generation parameters (for symmetry awareness)
        """
        analyzer = get_analyzer()
        target_score = target * 100
        symmetry_mode = params.symmetry_mode if params else "none"

        # Track if we've hit tile limit - need to use obstacles
        tiles_maxed_out = False
        # Track consecutive no-change iterations
        no_change_count = 0
        last_score = None

        for iteration in range(self.MAX_ADJUSTMENT_ITERATIONS):
            report = analyzer.analyze(level)
            current_score = report.score
            diff = target_score - current_score

            if abs(diff) <= self.DIFFICULTY_TOLERANCE:
                break

            # Check if score isn't changing (stuck)
            if last_score is not None and abs(current_score - last_score) < 0.1:
                no_change_count += 1
                if no_change_count >= 3:
                    # Score is stuck, need to use obstacles to increase further
                    tiles_maxed_out = True
            else:
                no_change_count = 0
            last_score = current_score

            if diff > 0:
                # Need to increase difficulty
                # If max_tiles is set, check if we can add more tiles
                if max_tiles is not None:
                    current_tiles = sum(
                        len(level.get(f"layer_{i}", {}).get("tiles", {}))
                        for i in range(level.get("layer", 8))
                    )
                    if current_tiles >= max_tiles:
                        tiles_maxed_out = True

                # Pass target difficulty to enable aggressive obstacle addition for high targets
                level = self._increase_difficulty(level, params, tiles_maxed_out=tiles_maxed_out, target_difficulty=target)
            else:
                # Need to decrease difficulty - pass target for aggressive reduction at low targets
                level = self._decrease_difficulty(level, params, target_difficulty=target)

        return level

    def _increase_difficulty(self, level: Dict[str, Any], params: Optional["GenerationParams"] = None, tiles_maxed_out: bool = False, target_difficulty: float = 0.5) -> Dict[str, Any]:
        """Apply a random modification to increase difficulty.

        When tiles are maxed out or target difficulty is high, adds obstacles
        (chain, frog, ice) to increase difficulty. This allows generating B, C, D grade levels.

        Strategy based on target_difficulty:
        - target < 0.4 (S/A grade): Primarily add tiles
        - target >= 0.4 (B grade): Mix of tiles and obstacles (50% chance each)
        - target >= 0.6 (C grade): Primarily obstacles, multiple per iteration
        - target >= 0.8 (D grade): Aggressive obstacle addition, activate more layers
        """
        symmetry_mode = params.symmetry_mode if params else "none"

        # Check gimmick_intensity - if 0, don't add obstacles, only add tiles
        # For values between 0 and 1, use as probability multiplier
        gimmick_intensity = getattr(params, 'gimmick_intensity', 1.0) if params else 1.0

        # Also check obstacle_types - if empty list, no obstacles should be added
        # This respects the gimmick unlock system where certain levels have no unlocked gimmicks
        obstacle_types = getattr(params, 'obstacle_types', None) if params else None
        obstacles_disabled = gimmick_intensity <= 0 or (obstacle_types is not None and len(obstacle_types) == 0)

        # Obstacle addition actions - filter by allowed obstacle types
        all_obstacle_actions = {
            "chain": self._add_chain_to_tile,
            "frog": self._add_frog_to_tile,
            "ice": self._add_ice_to_tile,
        }
        # If obstacle_types is specified, only allow those actions
        if obstacle_types is not None and len(obstacle_types) > 0:
            obstacle_actions = [all_obstacle_actions[t] for t in obstacle_types if t in all_obstacle_actions]
        else:
            obstacle_actions = list(all_obstacle_actions.values())

        # Helper: check if we should add obstacles based on gimmick_intensity probability
        def should_add_obstacle() -> bool:
            if obstacles_disabled:
                return False
            if gimmick_intensity >= 1.0:
                return True
            # For values 0 < gimmick_intensity < 1, use as probability
            return random.random() < gimmick_intensity

        # For low gimmick_intensity (< 0.5), prefer adding tiles over obstacles
        # This ensures early levels have minimal gimmicks
        prefer_tiles_over_obstacles = gimmick_intensity < 0.5

        # Tile Buster style: Very conservative gimmick addition
        # - Primary difficulty comes from tiles and layers, not obstacles
        # - Obstacles are added very sparingly (10-20% chance)
        # - Skip obstacle addition if already at target gimmick percentage

        # Count current gimmicks to cap at ~15% of total tiles
        total_tiles = 0
        total_gimmicks = 0
        for layer_idx in range(8):
            layer_key = f"layer_{layer_idx}"
            tiles = level.get(layer_key, {}).get("tiles", {})
            total_tiles += len(tiles)
            for tile_data in tiles.values():
                if len(tile_data) > 1 and tile_data[1]:
                    total_gimmicks += 1

        # Cap gimmicks at 15% of total tiles
        max_gimmicks = int(total_tiles * 0.15)
        gimmicks_capped = total_gimmicks >= max_gimmicks

        # D grade (target >= 0.8): Add 1 obstacle with 15% chance
        if target_difficulty >= 0.8:
            if prefer_tiles_over_obstacles and not tiles_maxed_out:
                if symmetry_mode == "none":
                    return self._add_tile_to_layer(level)
            elif not gimmicks_capped and random.random() < 0.15 and should_add_obstacle():
                action = random.choice(obstacle_actions)
                return action(level)
            if symmetry_mode == "none" and not tiles_maxed_out:
                return self._add_tile_to_layer(level)

        # C grade (target >= 0.6): Add 1 obstacle with 10% chance
        if target_difficulty >= 0.6:
            if prefer_tiles_over_obstacles and not tiles_maxed_out:
                if symmetry_mode == "none":
                    return self._add_tile_to_layer(level)
            elif not gimmicks_capped and random.random() < 0.10 and should_add_obstacle():
                action = random.choice(obstacle_actions)
                return action(level)

        # B grade (target >= 0.4): Add 1 obstacle with 5% chance
        if target_difficulty >= 0.4:
            if prefer_tiles_over_obstacles:
                if symmetry_mode == "none" and not tiles_maxed_out:
                    return self._add_tile_to_layer(level)
            elif not gimmicks_capped and random.random() < 0.05 and should_add_obstacle():
                action = random.choice(obstacle_actions)
                return action(level)

        # If tiles are maxed out, add obstacles sparingly (20% chance, if not capped)
        if tiles_maxed_out and not gimmicks_capped and random.random() < 0.2 and should_add_obstacle():
            action = random.choice(obstacle_actions)
            return action(level)

        # For symmetric patterns, skip random tile addition to preserve symmetry
        if symmetry_mode != "none":
            return level

        # Default: add tiles (for S/A grade targets)
        return self._add_tile_to_layer(level)

    def _decrease_difficulty(self, level: Dict[str, Any], params: Optional["GenerationParams"] = None, target_difficulty: float = 0.5) -> Dict[str, Any]:
        """Apply a random modification to decrease difficulty.

        Strategy based on target_difficulty:
        - target >= 0.4: Remove 1 tile (gentle reduction)
        - target >= 0.2 (A grade): Remove 1-2 tiles, possibly remove obstacle
        - target < 0.2 (S grade): Aggressively remove 2-3 tiles and obstacles
        """
        symmetry_mode = params.symmetry_mode if params else "none"
        # For symmetric patterns, skip random tile removal to preserve symmetry
        if symmetry_mode != "none":
            return level

        # S grade (target < 0.2): Very aggressive - remove multiple tiles and obstacles
        if target_difficulty < 0.2:
            # Remove 2-3 tiles per iteration
            num_removals = random.randint(2, 3)
            for _ in range(num_removals):
                level = self._remove_tile_from_layer(level)
            # Also try to remove obstacles if any exist
            if random.random() < 0.7:
                level = self._remove_random_obstacle(level)
            return level

        # A grade (target < 0.4): Moderate reduction
        if target_difficulty < 0.4:
            # Remove 1-2 tiles
            num_removals = random.randint(1, 2)
            for _ in range(num_removals):
                level = self._remove_tile_from_layer(level)
            # Sometimes remove obstacles
            if random.random() < 0.3:
                level = self._remove_random_obstacle(level)
            return level

        # Default: gentle reduction - remove 1 tile
        return self._remove_tile_from_layer(level)

    def _remove_random_obstacle(self, level: Dict[str, Any]) -> Dict[str, Any]:
        """Remove a random obstacle (chain, frog, ice) from the level."""
        num_layers = level.get("layer", 8)

        # Find all tiles with obstacles
        candidates = []
        for i in range(num_layers):
            layer_key = f"layer_{i}"
            tiles = level.get(layer_key, {}).get("tiles", {})
            for pos, tile_data in tiles.items():
                if (isinstance(tile_data, list) and len(tile_data) >= 2
                    and tile_data[1] in ["chain", "frog", "ice"]):
                    candidates.append((layer_key, pos))

        if candidates:
            layer_key, pos = random.choice(candidates)
            level[layer_key]["tiles"][pos][1] = ""

        return level

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
        """Add frog attribute to a random tile.

        RULE: Frogs must only be placed on tiles that are NOT covered by upper layers.
        This is because frogs need to be immediately selectable when the level spawns.
        """
        num_layers = level.get("layer", 8)

        # Collect all tiles without attributes that are NOT covered by upper layers
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
                    # Check if position is covered by upper layers
                    try:
                        col, row = map(int, pos.split('_'))
                        if not self._is_position_covered_by_upper(level, i, col, row):
                            candidates.append((layer_key, pos))
                    except:
                        continue

        if candidates:
            layer_key, pos = random.choice(candidates)
            level[layer_key]["tiles"][pos][1] = "frog"

        return level

    def _add_ice_to_tile(self, level: Dict[str, Any]) -> Dict[str, Any]:
        """Add ice attribute to a random tile.

        Ice tiles require 2 taps to clear: first tap removes ice, second tap clears tile.
        Ice is a good difficulty modifier as it doesn't require neighbor rules like chain.
        """
        return self._add_attribute_to_tile(level, "ice")

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

        # Collect existing tile types from level to match user's selection
        # IMPORTANT: Exclude goal types (craft_s, stack_s, etc.) - they should only be added via _add_goals
        existing_tile_types = set()
        for i in range(num_layers):
            layer_tiles = level.get(f"layer_{i}", {}).get("tiles", {})
            for tile_data in layer_tiles.values():
                if isinstance(tile_data, list) and tile_data:
                    tile_type = tile_data[0]
                    # Exclude goal types and craft/stack tiles
                    if not (tile_type.startswith("craft_") or tile_type.startswith("stack_")):
                        existing_tile_types.add(tile_type)

        # Use existing tile types if available, otherwise fall back to t1~t{useTileCount}
        if existing_tile_types:
            valid_tile_types = list(existing_tile_types)
        else:
            valid_tile_types = [f"t{i}" for i in range(1, use_tile_count + 1)]

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

        CRITICAL: First ensures TOTAL matchable tiles is divisible by 3 by adjusting
        craft_s internal tile counts if necessary.
        """
        num_layers = level.get("layer", 8)
        use_tile_count = level.get("useTileCount", 5)

        # Collect existing tile types from level to match user's selection
        existing_tile_types = set()
        for i in range(num_layers):
            layer_tiles = level.get(f"layer_{i}", {}).get("tiles", {})
            for tile_data in layer_tiles.values():
                if isinstance(tile_data, list) and tile_data:
                    tile_type = tile_data[0]
                    if tile_type.startswith("t") and tile_type not in self.GOAL_TYPES:
                        existing_tile_types.add(tile_type)

        # Use existing tile types if available, otherwise fall back to t1~t{useTileCount}
        if existing_tile_types:
            valid_tile_set = existing_tile_types
            valid_tile_types = list(existing_tile_types)
        else:
            valid_tile_set = {f"t{i}" for i in range(1, use_tile_count + 1)}
            valid_tile_types = [f"t{i}" for i in range(1, use_tile_count + 1)]

        # Step 0: Convert out-of-range tiles to valid range
        for i in range(num_layers):
            layer_key = f"layer_{i}"
            tiles = level.get(layer_key, {}).get("tiles", {})
            for pos, tile_data in tiles.items():
                if isinstance(tile_data, list) and len(tile_data) > 0:
                    tile_type = tile_data[0]
                    # Skip goal tiles (craft_s, craft_n, craft_e, craft_w, stack_s, etc.)
                    if tile_type in self.GOAL_TYPES or tile_type.startswith("craft_") or tile_type.startswith("stack_"):
                        continue
                    # Check if tile type is out of valid range
                    if tile_type.startswith("t") and tile_type not in valid_tile_set:
                        # Convert to a random valid tile type
                        tile_data[0] = random.choice(valid_tile_types)

        # Step 0.5: Ensure TOTAL matchable tiles is divisible by 3
        # This is CRITICAL - if total is not divisible by 3, we can't make all types divisible
        # Count regular tiles on grid + internal tiles in craft/stack
        total_matchable = 0
        goal_tiles_with_internal: List[Tuple[int, str, list]] = []  # (layer_idx, pos, tile_data)

        for i in range(num_layers):
            layer_key = f"layer_{i}"
            tiles = level.get(layer_key, {}).get("tiles", {})
            for pos, tile_data in tiles.items():
                if isinstance(tile_data, list) and len(tile_data) > 0:
                    tile_type = tile_data[0]
                    if tile_type in self.GOAL_TYPES or tile_type.startswith("craft_") or tile_type.startswith("stack_"):
                        # Count internal tiles for goal tiles (craft/stack)
                        if len(tile_data) > 2 and isinstance(tile_data[2], list) and tile_data[2]:
                            internal_count = int(tile_data[2][0]) if tile_data[2][0] else 0
                            total_matchable += internal_count
                            goal_tiles_with_internal.append((i, pos, tile_data))
                    else:
                        total_matchable += 1

        # Adjust total to be divisible by 3 (NOT modifying goal counts)
        # User-specified goal internal counts should be preserved
        # Strategy: Try to add tiles first, if not possible then remove tiles
        # CRITICAL: For symmetric patterns, we must add/remove tiles symmetrically!
        total_remainder = total_matchable % 3
        tiles_were_removed = False  # Track if we removed tiles for total adjustment
        symmetry_mode = params.symmetry_mode or "none"

        if total_remainder != 0:
            cols, rows = params.grid_size

            # First, try to add tiles (3 - remainder tiles needed)
            tiles_to_add = 3 - total_remainder
            added_count = 0

            # For symmetric patterns, add tiles symmetrically
            if symmetry_mode in ("horizontal", "vertical", "both"):
                # For symmetry, we need to add tiles in pairs/quads
                # Just skip adding for now - the tile type redistribution will handle it
                pass
            else:
                for i in range(num_layers):
                    if added_count >= tiles_to_add:
                        break
                    layer_key = f"layer_{i}"
                    layer_data = level.get(layer_key, {})
                    tiles = layer_data.get("tiles", {})
                    if not tiles:
                        continue

                    is_odd_layer = i % 2 == 1
                    layer_cols = cols if is_odd_layer else cols + 1
                    layer_rows = rows if is_odd_layer else rows + 1

                    all_positions = [f"{x}_{y}" for x in range(layer_cols) for y in range(layer_rows)]
                    used_positions = set(tiles.keys())

                    for pos in all_positions:
                        if added_count >= tiles_to_add:
                            break
                        if pos not in used_positions:
                            # Add a t0 tile to this position
                            level[layer_key]["tiles"][pos] = ["t0", ""]
                            level[layer_key]["num"] = str(len(level[layer_key]["tiles"]))
                            added_count += 1

            # If adding tiles failed (no available positions), remove tiles instead
            # If remainder=1, remove 1 tile. If remainder=2, remove 2 tiles.
            # CRITICAL: For symmetric patterns, we SKIP removal to preserve symmetry!
            if added_count < tiles_to_add and symmetry_mode == "none":
                tiles_to_remove = total_remainder  # 1 or 2
                removed_count = 0

                # Collect removable tiles (regular tiles without attributes, not goals)
                removable_tiles: List[Tuple[int, str]] = []
                for i in range(num_layers):
                    layer_key = f"layer_{i}"
                    tiles = level.get(layer_key, {}).get("tiles", {})
                    for pos, tile_data in tiles.items():
                        if isinstance(tile_data, list) and len(tile_data) >= 2:
                            tile_type = tile_data[0]
                            attribute = tile_data[1] if len(tile_data) > 1 else ""
                            # Only remove regular tiles without attributes (not goal tiles)
                            if (tile_type not in self.GOAL_TYPES and
                                not tile_type.startswith("craft_") and
                                not tile_type.startswith("stack_") and
                                not attribute):
                                removable_tiles.append((i, pos))

                # Remove tiles from the end of the list (less impactful positions)
                import random
                random.shuffle(removable_tiles)
                for layer_idx, pos in removable_tiles[:tiles_to_remove]:
                    layer_key = f"layer_{layer_idx}"
                    if pos in level[layer_key]["tiles"]:
                        del level[layer_key]["tiles"][pos]
                        level[layer_key]["num"] = str(len(level[layer_key]["tiles"]))
                        removed_count += 1
                        if removed_count >= tiles_to_remove:
                            break

                if removed_count > 0:
                    tiles_were_removed = True

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
                    if tile_type in self.GOAL_TYPES or tile_type.startswith("craft_") or tile_type.startswith("stack_"):
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
        # IMPORTANT: Skip adding tiles if we already removed tiles for total adjustment
        # Adding tiles would undo the total divisibility fix
        # CRITICAL: For symmetric patterns, skip random tile addition to preserve symmetry!
        if not tiles_were_removed and symmetry_mode == "none":
            for tile_type, tiles_needed in types_needing_add:
                for _ in range(tiles_needed):
                    if not available_positions:
                        break
                    layer_idx, pos = available_positions.pop(0)
                    layer_key = f"layer_{layer_idx}"
                    level[layer_key]["tiles"][pos] = [tile_type, ""]
                    level[layer_key]["num"] = str(len(level[layer_key]["tiles"]))

        # Step 5: Final verification - if still have issues, reassign existing tiles
        # Recount after additions (include internal t0 tiles)
        type_counts_final: Dict[str, int] = {}
        type_positions_final: Dict[str, List[Tuple[int, str]]] = {}

        for i in range(num_layers):
            layer_key = f"layer_{i}"
            tiles = level.get(layer_key, {}).get("tiles", {})
            for pos, tile_data in tiles.items():
                if isinstance(tile_data, list) and len(tile_data) > 0:
                    tile_type = tile_data[0]
                    if tile_type in self.GOAL_TYPES or tile_type.startswith("craft_") or tile_type.startswith("stack_"):
                        # Count internal tiles as t0
                        if len(tile_data) > 2 and isinstance(tile_data[2], list) and tile_data[2]:
                            internal_count = int(tile_data[2][0]) if tile_data[2][0] else 0
                            type_counts_final["t0"] = type_counts_final.get("t0", 0) + internal_count
                    else:
                        type_counts_final[tile_type] = type_counts_final.get(tile_type, 0) + 1
                        if tile_type not in type_positions_final:
                            type_positions_final[tile_type] = []
                        type_positions_final[tile_type].append((i, pos))

        # Check if any type still has remainder
        still_broken = [(t, c % 3) for t, c in type_counts_final.items() if c % 3 != 0]

        # Keep fixing until all types are divisible by 3 or no more fixes possible
        max_fix_iterations = 10
        fix_iteration = 0

        while still_broken and fix_iteration < max_fix_iterations:
            fix_iteration += 1
            fixed_any = False

            # Separate types by remainder
            rem1_types = [t for t, r in still_broken if r == 1]
            rem2_types = [t for t, r in still_broken if r == 2]

            # Strategy 1: Pair rem1 with rem2 types
            while rem1_types and rem2_types:
                type_a = rem1_types.pop(0)  # remainder 1
                type_b = rem2_types.pop(0)  # remainder 2

                # Move 1 tile from type_a to type_b
                # type_a: -1 → remainder 0
                # type_b: +1 → remainder 0
                if type_a in type_positions_final and type_positions_final[type_a]:
                    layer_idx, pos = type_positions_final[type_a].pop()
                    layer_key = f"layer_{layer_idx}"
                    level[layer_key]["tiles"][pos][0] = type_b
                    fixed_any = True

            # Strategy 2: Handle 3 types with same remainder
            # 3 types with rem 1: redistribute 1 tile each to balance
            while len(rem1_types) >= 3:
                type_a = rem1_types.pop(0)
                type_b = rem1_types.pop(0)
                type_c = rem1_types.pop(0)

                # Move 1 from type_a to type_b → a:rem0, b:rem2
                # Move 2 from type_b to type_c → b:rem0, c:rem0
                if type_a in type_positions_final and type_positions_final[type_a]:
                    layer_idx, pos = type_positions_final[type_a].pop()
                    layer_key = f"layer_{layer_idx}"
                    level[layer_key]["tiles"][pos][0] = type_b
                    fixed_any = True

                if type_b in type_positions_final and len(type_positions_final.get(type_b, [])) >= 2:
                    for _ in range(2):
                        layer_idx, pos = type_positions_final[type_b].pop()
                        layer_key = f"layer_{layer_idx}"
                        level[layer_key]["tiles"][pos][0] = type_c
                    fixed_any = True

            # 3 types with rem 2: redistribute 2 tiles each to balance
            while len(rem2_types) >= 3:
                type_a = rem2_types.pop(0)
                type_b = rem2_types.pop(0)
                type_c = rem2_types.pop(0)

                # Move 2 from type_a to type_b → a:rem0, b:rem1
                # Move 1 from type_b to type_c → b:rem0, c:rem0
                if type_a in type_positions_final and len(type_positions_final.get(type_a, [])) >= 2:
                    for _ in range(2):
                        layer_idx, pos = type_positions_final[type_a].pop()
                        layer_key = f"layer_{layer_idx}"
                        level[layer_key]["tiles"][pos][0] = type_b
                    fixed_any = True

                if type_b in type_positions_final and type_positions_final[type_b]:
                    layer_idx, pos = type_positions_final[type_b].pop()
                    layer_key = f"layer_{layer_idx}"
                    level[layer_key]["tiles"][pos][0] = type_c
                    fixed_any = True

            if not fixed_any:
                break

            # Recount for next iteration
            type_counts_final = {}
            type_positions_final = {}
            for i in range(num_layers):
                layer_key = f"layer_{i}"
                tiles = level.get(layer_key, {}).get("tiles", {})
                for pos, tile_data in tiles.items():
                    if isinstance(tile_data, list) and len(tile_data) > 0:
                        tile_type = tile_data[0]
                        if tile_type in self.GOAL_TYPES or tile_type.startswith("craft_") or tile_type.startswith("stack_"):
                            if len(tile_data) > 2 and isinstance(tile_data[2], list) and tile_data[2]:
                                internal_count = int(tile_data[2][0]) if tile_data[2][0] else 0
                                type_counts_final["t0"] = type_counts_final.get("t0", 0) + internal_count
                        else:
                            type_counts_final[tile_type] = type_counts_final.get(tile_type, 0) + 1
                            if tile_type not in type_positions_final:
                                type_positions_final[tile_type] = []
                            type_positions_final[tile_type].append((i, pos))

            still_broken = [(t, c % 3) for t, c in type_counts_final.items() if c % 3 != 0]

        # FINAL STEP: FORCE divisibility by 3
        # If still_broken has any types, it means the total is not divisible by 3
        # or the reassignment strategies failed. Force fix by removing tiles.
        if still_broken:
            # Recount everything one more time
            total_matchable = 0
            removable_tiles_final: List[Tuple[int, str, str]] = []  # (layer_idx, pos, tile_type)

            for i in range(num_layers):
                layer_key = f"layer_{i}"
                tiles = level.get(layer_key, {}).get("tiles", {})
                for pos, tile_data in tiles.items():
                    if isinstance(tile_data, list) and len(tile_data) > 0:
                        tile_type = tile_data[0]
                        if tile_type in self.GOAL_TYPES or tile_type.startswith("craft_") or tile_type.startswith("stack_"):
                            # Count internal tiles
                            if len(tile_data) > 2 and isinstance(tile_data[2], list) and tile_data[2]:
                                internal_count = int(tile_data[2][0]) if tile_data[2][0] else 0
                                total_matchable += internal_count
                        else:
                            total_matchable += 1
                            # Only add regular tiles without obstacles as removable
                            attr = tile_data[1] if len(tile_data) > 1 else ""
                            if not attr:
                                removable_tiles_final.append((i, pos, tile_type))

            total_remainder = total_matchable % 3
            if total_remainder != 0:
                # We MUST remove tiles to fix the total
                tiles_to_remove = total_remainder  # 1 or 2

                # Sort removable tiles by type - prefer removing from types with remainder
                type_counts_for_sort: Dict[str, int] = {}
                for layer_idx, pos, tile_type in removable_tiles_final:
                    type_counts_for_sort[tile_type] = type_counts_for_sort.get(tile_type, 0) + 1

                # Calculate remainder for each type
                type_remainders = {t: c % 3 for t, c in type_counts_for_sort.items()}

                # Sort: prefer types with remainder matching tiles_to_remove
                # e.g., if we need to remove 1 tile, prefer types with remainder 1
                def sort_key(item: Tuple[int, str, str]) -> Tuple[int, str]:
                    _, _, tile_type = item
                    remainder = type_remainders.get(tile_type, 0)
                    # Priority: exact match > any remainder > no remainder
                    if remainder == tiles_to_remove:
                        return (0, tile_type)
                    elif remainder > 0:
                        return (1, tile_type)
                    else:
                        return (2, tile_type)

                removable_tiles_final.sort(key=sort_key)

                removed_count = 0
                for layer_idx, pos, tile_type in removable_tiles_final:
                    if removed_count >= tiles_to_remove:
                        break
                    layer_key = f"layer_{layer_idx}"
                    if pos in level.get(layer_key, {}).get("tiles", {}):
                        del level[layer_key]["tiles"][pos]
                        level[layer_key]["num"] = str(len(level[layer_key]["tiles"]))
                        removed_count += 1

                # After removing tiles for total, we need to re-run type redistribution
                # But now the total IS divisible by 3, so redistribution will work
                if removed_count > 0:
                    # Quick redistribution pass
                    type_counts_final2: Dict[str, int] = {}
                    type_positions_final2: Dict[str, List[Tuple[int, str]]] = {}

                    for i in range(num_layers):
                        layer_key = f"layer_{i}"
                        tiles = level.get(layer_key, {}).get("tiles", {})
                        for pos, tile_data in tiles.items():
                            if isinstance(tile_data, list) and len(tile_data) > 0:
                                tile_type = tile_data[0]
                                if tile_type in self.GOAL_TYPES or tile_type.startswith("craft_") or tile_type.startswith("stack_"):
                                    if len(tile_data) > 2 and isinstance(tile_data[2], list) and tile_data[2]:
                                        internal_count = int(tile_data[2][0]) if tile_data[2][0] else 0
                                        type_counts_final2["t0"] = type_counts_final2.get("t0", 0) + internal_count
                                else:
                                    type_counts_final2[tile_type] = type_counts_final2.get(tile_type, 0) + 1
                                    if tile_type not in type_positions_final2:
                                        type_positions_final2[tile_type] = []
                                    type_positions_final2[tile_type].append((i, pos))

                    # Simple redistribution: pair rem1 with rem2
                    still_broken2 = [(t, c % 3) for t, c in type_counts_final2.items() if c % 3 != 0]
                    rem1_types2 = [t for t, r in still_broken2 if r == 1]
                    rem2_types2 = [t for t, r in still_broken2 if r == 2]

                    while rem1_types2 and rem2_types2:
                        type_a = rem1_types2.pop(0)
                        type_b = rem2_types2.pop(0)
                        if type_a in type_positions_final2 and type_positions_final2[type_a]:
                            layer_idx, pos = type_positions_final2[type_a].pop()
                            layer_key = f"layer_{layer_idx}"
                            if pos in level.get(layer_key, {}).get("tiles", {}):
                                level[layer_key]["tiles"][pos][0] = type_b

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
                            # Target must not be a goal tile (craft/stack)
                            target_type = target_data[0]
                            if (target_type not in self.GOAL_TYPES and
                                not target_type.startswith("craft_") and
                                not target_type.startswith("stack_")):
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
