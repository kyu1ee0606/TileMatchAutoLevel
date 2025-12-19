"""Bot-based level simulation engine with correct Tile Match game rules.

Based on sp_template TileGroup/Dock/TileEffect mechanics:
- 7-slot dock queue system
- 3-tile consecutive matching
- Layer blocking (upper tiles block lower tiles)
- Obstacle mechanics (ice, chain, grass, link, frog, bomb, curtain, teleport)
"""
import random
import math
from typing import Dict, List, Any, Optional, Tuple, Set
from dataclasses import dataclass, field
from concurrent.futures import ThreadPoolExecutor, as_completed
import statistics
from enum import Enum

from ..models.bot_profile import BotProfile, BotType, BotTeam, get_profile


class TileEffectType(str, Enum):
    """Tile effect types matching sp_template TileEffectType enum."""
    NONE = "none"
    ICE = "ice"
    CHAIN = "chain"
    GRASS = "grass"
    LINK_EAST = "link_e"
    LINK_WEST = "link_w"
    LINK_SOUTH = "link_s"
    LINK_NORTH = "link_n"
    FROG = "frog"
    BOMB = "bomb"
    CURTAIN = "curtain"
    TELEPORT = "teleport"
    UNKNOWN = "unknown"
    CRAFT = "craft"
    # Stack gimmicks - push blocks in direction when tile is picked
    STACK_NORTH = "stack_n"
    STACK_SOUTH = "stack_s"
    STACK_EAST = "stack_e"
    STACK_WEST = "stack_w"


@dataclass
class TileState:
    """Represents a tile's current state."""
    tile_type: str  # t0, t1, t2, ... t15, t16(key)
    layer_idx: int
    x_idx: int
    y_idx: int
    effect_type: TileEffectType = TileEffectType.NONE
    effect_data: Dict[str, Any] = field(default_factory=dict)
    # Ice: remaining layers (1-3), Chain: unlocked (bool), Grass: remaining (1-2)
    # Link: linked_tile_pos, Bomb: remaining_count, Curtain: is_open
    picked: bool = False

    # Stack/Craft tile fields (matching sp_template Tile.cs)
    is_stack_tile: bool = False
    is_craft_tile: bool = False
    is_crafted: bool = False  # For craft tiles: whether this tile has been "produced" from craft box
    stack_index: int = -1  # Position in stack (0 = root/bottom, higher = towards top)
    stack_max_index: int = -1  # Total tiles in stack - 1
    upper_stacked_tile_key: Optional[str] = None  # Key to upper stacked tile (layerIdx_x_y_stackIdx)
    under_stacked_tile_key: Optional[str] = None  # Key to under stacked tile
    root_stacked_tile_key: Optional[str] = None  # Key to root (bottom) tile of stack
    craft_direction: str = ""  # e/w/s/n for craft tiles
    original_full_key: Optional[str] = None  # Original full_key before position changes (for craft box lookup)

    @property
    def position_key(self) -> str:
        return f"{self.x_idx}_{self.y_idx}"

    @property
    def full_key(self) -> str:
        """Full key including layer and stack index for unique identification."""
        if self.stack_index >= 0:
            return f"{self.layer_idx}_{self.x_idx}_{self.y_idx}_{self.stack_index}"
        return f"{self.layer_idx}_{self.x_idx}_{self.y_idx}"

    def can_pick(self) -> bool:
        """Check if this tile can be picked based on its effect.

        Based on sp_template TileEffect.CheckCanPick():
        - First check onFrog (blocks any tile regardless of effect type)
        - Then check effect-specific conditions
        """
        if self.picked:
            return False

        # sp_template checks onFrog BEFORE effect type switch
        # A frog can move to ANY tile, making it unpickable
        if self.effect_data.get("on_frog", False):
            return False

        if self.effect_type == TileEffectType.ICE:
            return self.effect_data.get("remaining", 0) <= 0
        elif self.effect_type == TileEffectType.CHAIN:
            return self.effect_data.get("unlocked", False)
        elif self.effect_type == TileEffectType.GRASS:
            return self.effect_data.get("remaining", 0) <= 0
        elif self.effect_type in (TileEffectType.LINK_EAST, TileEffectType.LINK_WEST,
                                   TileEffectType.LINK_SOUTH, TileEffectType.LINK_NORTH):
            return self.effect_data.get("can_pick", False)
        elif self.effect_type == TileEffectType.CURTAIN:
            return self.effect_data.get("is_open", True)
        else:
            return True


@dataclass
class DockSlot:
    """Represents a slot in the 7-slot dock queue."""
    index: int
    tile: Optional[TileState] = None
    is_locked: bool = False


@dataclass
class GameState:
    """Represents the current state of a simulated game."""
    # Layer structure: layer_idx -> {pos_key: TileState}
    tiles: Dict[int, Dict[str, TileState]] = field(default_factory=dict)
    # Layer grid sizes: layer_idx -> col (grid column count)
    layer_cols: Dict[int, int] = field(default_factory=dict)
    # 7-slot dock queue
    dock: List[DockSlot] = field(default_factory=list)
    dock_tiles: List[TileState] = field(default_factory=list)  # Tiles currently in dock
    # Goals
    goals_remaining: Dict[str, int] = field(default_factory=dict)
    # Game state
    moves_used: int = 0
    cleared: bool = False
    failed: bool = False
    max_moves: int = 30
    combo_count: int = 0
    total_tiles_cleared: int = 0
    max_dock_slots: int = 7
    # Link tiles tracking
    link_pairs: Dict[str, str] = field(default_factory=dict)  # pos -> linked_pos
    # Frog tracking
    frog_positions: Set[str] = field(default_factory=set)
    # Bomb tracking
    bomb_tiles: Dict[str, int] = field(default_factory=dict)  # pos -> remaining
    # Stack/Craft tile tracking - key: full_key (layerIdx_x_y_stackIdx) -> TileState
    stacked_tiles: Dict[str, TileState] = field(default_factory=dict)
    # Craft boxes: position key -> list of stacked tile keys in order (bottom to top)
    craft_boxes: Dict[str, List[str]] = field(default_factory=dict)
    # Teleport tracking
    teleport_click_count: int = 0  # Click counter for teleport (activates every 3 clicks)
    teleport_tiles: List[Tuple[int, str]] = field(default_factory=list)  # (layer_idx, pos) of teleport tiles


@dataclass
class Move:
    """Represents a possible move in the game."""
    layer_idx: int
    position: str
    tile_type: str
    tile_state: Optional[TileState] = None
    attribute: str = ""
    score: float = 0.0
    match_count: int = 0
    will_match: bool = False  # True if picking this will complete a 3-match


@dataclass
class BotSimulationResult:
    """Result from a single bot's simulation runs."""
    bot_type: BotType
    bot_name: str
    iterations: int
    clear_rate: float
    avg_moves: float
    min_moves: int
    max_moves: int
    std_moves: float
    avg_combo: float
    avg_tiles_cleared: float

    def to_dict(self) -> Dict:
        return {
            "bot_type": self.bot_type.value,
            "bot_name": self.bot_name,
            "iterations": self.iterations,
            "clear_rate": round(self.clear_rate, 4),
            "avg_moves": round(self.avg_moves, 2),
            "min_moves": self.min_moves,
            "max_moves": self.max_moves,
            "std_moves": round(self.std_moves, 2),
            "avg_combo": round(self.avg_combo, 2),
            "avg_tiles_cleared": round(self.avg_tiles_cleared, 2),
        }


@dataclass
class MultiBotAssessmentResult:
    """Aggregated result from multi-bot assessment."""
    bot_results: List[BotSimulationResult]
    overall_difficulty: float
    difficulty_grade: str
    target_audience: str
    difficulty_variance: float
    recommended_moves: int
    analysis_summary: Dict[str, Any]

    def to_dict(self) -> Dict:
        return {
            "bot_results": [r.to_dict() for r in self.bot_results],
            "overall_difficulty": round(self.overall_difficulty, 2),
            "difficulty_grade": self.difficulty_grade,
            "target_audience": self.target_audience,
            "difficulty_variance": round(self.difficulty_variance, 4),
            "recommended_moves": self.recommended_moves,
            "analysis_summary": self.analysis_summary,
        }


class BotSimulator:
    """
    Bot simulator implementing correct Tile Match game rules.

    Game Rules (from sp_template):
    1. 7-slot dock queue system
    2. Tiles are added to dock when clicked
    3. When 3 same-type tiles exist in dock, they are removed (matched)
    4. Game fails when dock is full (7 tiles) without any matches
    5. Layer blocking: upper layer tiles block lower layer tiles
    6. Various obstacle effects affect tile pickability
    7. t0 tiles are random tiles that get assigned a random type (t1-t15)
    8. stack_n/s/w/e gimmicks push blocks in that direction
    """

    # Matchable tile types (t1-t15 are normal tiles, t16 is key tile)
    # Note: t0 is a random tile placeholder, gets converted at level init
    MATCHABLE_TYPES = {f"t{i}" for i in range(1, 16)} | {"t16"}
    # Random tile types that t0 can become (t1-t15)
    RANDOM_TILE_POOL = [f"t{i}" for i in range(1, 16)]
    # Default tile count for random distribution (matches sp_template default)
    DEFAULT_USE_TILE_COUNT = 6
    # Goal types
    GOAL_TYPES = {"craft_s", "stack_s"}

    # Effect type mapping from level JSON
    EFFECT_MAPPING = {
        "ice": TileEffectType.ICE,
        "chain": TileEffectType.CHAIN,
        "grass": TileEffectType.GRASS,
        "link_e": TileEffectType.LINK_EAST,
        "link_w": TileEffectType.LINK_WEST,
        "link_s": TileEffectType.LINK_SOUTH,
        "link_n": TileEffectType.LINK_NORTH,
        "frog": TileEffectType.FROG,
        "bomb": TileEffectType.BOMB,
        "curtain_close": TileEffectType.CURTAIN,
        "curtain_open": TileEffectType.CURTAIN,
        "teleport": TileEffectType.TELEPORT,
        "unknown": TileEffectType.UNKNOWN,
        "craft": TileEffectType.CRAFT,
        # Stack gimmicks - push blocks in that direction
        "stack_n": TileEffectType.STACK_NORTH,
        "stack_s": TileEffectType.STACK_SOUTH,
        "stack_e": TileEffectType.STACK_EAST,
        "stack_w": TileEffectType.STACK_WEST,
    }

    def __init__(self):
        self._rng = random.Random()

    def simulate_with_profile(
        self,
        level_json: Dict[str, Any],
        profile: BotProfile,
        iterations: int = 100,
        max_moves: int = 30,
        seed: Optional[int] = None,
    ) -> BotSimulationResult:
        """Run simulation with a specific bot profile."""
        if seed is not None:
            self._rng.seed(seed)

        results: List[GameState] = []

        for i in range(iterations):
            if seed is not None:
                self._rng.seed(seed + i)

            state = self._create_initial_state(level_json, max_moves)
            final_state = self._play_game(state, profile)
            results.append(final_state)

        cleared_count = sum(1 for r in results if r.cleared)
        moves_list = [r.moves_used for r in results]
        combo_list = [r.combo_count for r in results]
        tiles_list = [r.total_tiles_cleared for r in results]

        return BotSimulationResult(
            bot_type=profile.bot_type,
            bot_name=profile.name,
            iterations=iterations,
            clear_rate=cleared_count / iterations if iterations > 0 else 0,
            avg_moves=statistics.mean(moves_list) if moves_list else 0,
            min_moves=min(moves_list) if moves_list else 0,
            max_moves=max(moves_list) if moves_list else max_moves,
            std_moves=statistics.stdev(moves_list) if len(moves_list) > 1 else 0,
            avg_combo=statistics.mean(combo_list) if combo_list else 0,
            avg_tiles_cleared=statistics.mean(tiles_list) if tiles_list else 0,
        )

    def assess_difficulty(
        self,
        level_json: Dict[str, Any],
        team: Optional[BotTeam] = None,
        max_moves: int = 30,
        parallel: bool = True,
        seed: Optional[int] = None,
    ) -> MultiBotAssessmentResult:
        """Run multi-bot assessment to determine level difficulty."""
        if team is None:
            team = BotTeam.default_team(iterations_per_bot=100)

        bot_results: List[BotSimulationResult] = []

        if parallel and len(team.profiles) > 1:
            with ThreadPoolExecutor(max_workers=min(5, len(team.profiles))) as executor:
                futures = {
                    executor.submit(
                        self.simulate_with_profile,
                        level_json,
                        profile,
                        team.iterations_per_bot,
                        max_moves,
                        seed + i if seed else None,
                    ): profile
                    for i, profile in enumerate(team.profiles)
                }

                for future in as_completed(futures):
                    result = future.result()
                    bot_results.append(result)
        else:
            for i, profile in enumerate(team.profiles):
                result = self.simulate_with_profile(
                    level_json,
                    profile,
                    team.iterations_per_bot,
                    max_moves,
                    seed + i if seed else None,
                )
                bot_results.append(result)

        bot_results.sort(key=lambda r: BotType.all_types().index(r.bot_type))
        return self._aggregate_results(bot_results, team, max_moves)

    def _create_initial_state(
        self, level_json: Dict[str, Any], max_moves: int
    ) -> GameState:
        """Create initial game state from level JSON.

        Follows sp_template logic:
        - t0 tiles are distributed in sets of 3 for guaranteed matchability
        - Uses randSeed from level_json for deterministic distribution
        - Uses useTileCount to limit tile type variety
        """
        num_layers = level_json.get("layer", 8)
        state = GameState(max_moves=max_moves)

        # Initialize 7-slot dock
        for i in range(7):
            state.dock.append(DockSlot(index=i))

        # Get level settings for t0 distribution (sp_template compatible)
        rand_seed = level_json.get("randSeed", 0)
        use_tile_count = level_json.get("useTileCount", self.DEFAULT_USE_TILE_COUNT)
        if use_tile_count <= 0:
            use_tile_count = self.DEFAULT_USE_TILE_COUNT

        # First pass: collect all t0 tiles that need random assignment
        t0_tiles: List[Tuple[int, str, Any]] = []  # (layer_idx, pos, tile_data)

        for layer_idx in range(num_layers):
            layer_key = f"layer_{layer_idx}"
            layer_data = level_json.get(layer_key, {})
            layer_tiles = layer_data.get("tiles", {})

            if layer_tiles:
                for pos, tile_data in layer_tiles.items():
                    if not isinstance(tile_data, list) or not tile_data:
                        continue
                    tile_type = tile_data[0]
                    if tile_type == "t0":
                        t0_tiles.append((layer_idx, pos, tile_data))

        # Generate tile type assignments for t0 tiles (3 tiles per set)
        # Following sp_template's DistributeTiles logic
        t0_assignments = self._distribute_t0_tiles(
            len(t0_tiles), use_tile_count, rand_seed
        )

        # Create a mapping for quick lookup
        t0_assignment_map: Dict[Tuple[int, str], str] = {}
        for i, (layer_idx, pos, _) in enumerate(t0_tiles):
            if i < len(t0_assignments):
                t0_assignment_map[(layer_idx, pos)] = t0_assignments[i]

        # Second pass: create tile states with proper assignments
        # Also track stack/craft tiles for later processing
        stack_craft_tiles: List[Tuple[int, str, Any]] = []  # (layer_idx, pos, tile_data)

        for layer_idx in range(num_layers):
            layer_key = f"layer_{layer_idx}"
            layer_data = level_json.get(layer_key, {})
            layer_tiles = layer_data.get("tiles", {})

            # Store layer col for blocking calculation (sp_template uses col comparison)
            layer_col = layer_data.get("col", 7)
            state.layer_cols[layer_idx] = layer_col

            if layer_tiles:
                state.tiles[layer_idx] = {}

                for pos, tile_data in layer_tiles.items():
                    if not isinstance(tile_data, list) or not tile_data:
                        continue

                    tile_type = tile_data[0]

                    # Check if this is a stack or craft tile (e.g., "stack_e", "craft_s")
                    is_stack = isinstance(tile_type, str) and tile_type.startswith("stack_")
                    is_craft = isinstance(tile_type, str) and tile_type.startswith("craft_")

                    if is_stack or is_craft:
                        # Process stack/craft tiles separately
                        stack_craft_tiles.append((layer_idx, pos, tile_data))
                        continue

                    # Parse position
                    parts = pos.split("_")
                    x_idx = int(parts[0]) if len(parts) > 0 else 0
                    y_idx = int(parts[1]) if len(parts) > 1 else 0

                    # Parse effect
                    effect_type = TileEffectType.NONE
                    effect_data = {}

                    if len(tile_data) > 1 and tile_data[1]:
                        effect_str = str(tile_data[1]).lower()

                        # Map effect string to type
                        if effect_str in self.EFFECT_MAPPING:
                            effect_type = self.EFFECT_MAPPING[effect_str]

                            # Initialize effect-specific data
                            if effect_type == TileEffectType.ICE:
                                effect_data["remaining"] = 3  # 3 layers of ice
                            elif effect_type == TileEffectType.CHAIN:
                                effect_data["unlocked"] = False
                            elif effect_type == TileEffectType.GRASS:
                                effect_data["remaining"] = 2  # 2 grass layers
                            elif effect_type in (TileEffectType.LINK_EAST, TileEffectType.LINK_WEST,
                                                  TileEffectType.LINK_SOUTH, TileEffectType.LINK_NORTH):
                                effect_data["can_pick"] = False
                                # Find linked tile position
                                linked_x, linked_y = x_idx, y_idx
                                if effect_type == TileEffectType.LINK_EAST:
                                    linked_x += 1
                                elif effect_type == TileEffectType.LINK_WEST:
                                    linked_x -= 1
                                elif effect_type == TileEffectType.LINK_SOUTH:
                                    linked_y += 1
                                elif effect_type == TileEffectType.LINK_NORTH:
                                    linked_y -= 1
                                effect_data["linked_pos"] = f"{linked_x}_{linked_y}"
                                state.link_pairs[pos] = f"{linked_x}_{linked_y}"
                            elif effect_type == TileEffectType.FROG:
                                effect_data["on_frog"] = True
                                state.frog_positions.add(pos)
                            elif effect_type == TileEffectType.BOMB:
                                # Parse bomb count from effect string (e.g., "10" -> 10 moves)
                                try:
                                    bomb_count = int(effect_str) if effect_str.isdigit() else 10
                                except:
                                    bomb_count = 10
                                effect_data["remaining"] = bomb_count
                                state.bomb_tiles[pos] = bomb_count
                            elif effect_type == TileEffectType.CURTAIN:
                                effect_data["is_open"] = "open" in effect_str

                    # Handle t0 random tile - use pre-computed assignment
                    actual_tile_type = tile_type
                    if tile_type == "t0":
                        actual_tile_type = t0_assignment_map.get(
                            (layer_idx, pos),
                            self._rng.choice(self.RANDOM_TILE_POOL[:use_tile_count])
                        )

                    # Create tile state
                    tile_state = TileState(
                        tile_type=actual_tile_type,
                        layer_idx=layer_idx,
                        x_idx=x_idx,
                        y_idx=y_idx,
                        effect_type=effect_type,
                        effect_data=effect_data,
                    )

                    state.tiles[layer_idx][pos] = tile_state

                    # Extract goals
                    if tile_type in self.GOAL_TYPES:
                        goal_count = (
                            tile_data[2][0]
                            if len(tile_data) > 2 and tile_data[2]
                            else 1
                        )
                        state.goals_remaining[tile_type] = (
                            state.goals_remaining.get(tile_type, 0) + goal_count
                        )

        # Process stack/craft tiles
        self._process_stack_craft_tiles(state, stack_craft_tiles, t0_assignment_map, use_tile_count)

        # Initialize link pairs can_pick status
        self._update_link_tiles_status(state)

        # Load goalCount from level JSON
        # This overrides any goals set from tile types
        goal_count = level_json.get("goalCount", {})
        if goal_count:
            state.goals_remaining = dict(goal_count)

        return state

    def _distribute_t0_tiles(
        self, t0_count: int, use_tile_count: int, rand_seed: int = 0
    ) -> List[str]:
        """Distribute t0 tiles into matchable sets of 3.

        Follows sp_template's DistributeTiles logic:
        - Each tile type gets assigned in sets of 3
        - Types are distributed across available tile types (t1-t{use_tile_count})
        - Uses seed for deterministic distribution

        Args:
            t0_count: Total number of t0 tiles to assign
            use_tile_count: Number of tile types to use (1-15)
            rand_seed: Seed for random distribution

        Returns:
            List of tile type strings (e.g., ["t1", "t1", "t1", "t2", "t2", "t2", ...])
        """
        if t0_count == 0:
            return []

        # Use seed for deterministic distribution
        if rand_seed > 0:
            self._rng.seed(rand_seed)

        # Limit tile types to available pool
        use_tile_count = min(use_tile_count, len(self.RANDOM_TILE_POOL))
        available_types = self.RANDOM_TILE_POOL[:use_tile_count]

        # Calculate number of complete sets (3 tiles each)
        set_count = t0_count // 3
        remainder = t0_count % 3

        # Distribute sets across tile types
        # Each type gets at least 1 set, then distribute remaining evenly
        type_set_counts: List[int] = [0] * use_tile_count

        # First, ensure minimum 1 set per type if possible
        sets_to_distribute = set_count
        for i in range(min(sets_to_distribute, use_tile_count)):
            type_set_counts[i] = 1
            sets_to_distribute -= 1

        # Distribute remaining sets evenly
        if sets_to_distribute > 0:
            for i in range(sets_to_distribute):
                type_set_counts[i % use_tile_count] += 1

        # Build the assignment list (3 tiles per set)
        assignments: List[str] = []
        for type_idx, count in enumerate(type_set_counts):
            tile_type = available_types[type_idx]
            for _ in range(count * 3):  # 3 tiles per set
                assignments.append(tile_type)

        # Handle remainder (not a complete set of 3)
        # Add tiles that will need extra matching opportunities
        for i in range(remainder):
            # Pick types that already have tiles for better matching chances
            type_idx = i % use_tile_count
            assignments.append(available_types[type_idx])

        # Shuffle assignments for random placement across board
        self._rng.shuffle(assignments)

        return assignments

    def _process_stack_craft_tiles(
        self,
        state: GameState,
        stack_craft_tiles: List[Tuple[int, str, Any]],
        t0_assignment_map: Dict[Tuple[int, str], str],
        use_tile_count: int,
    ) -> None:
        """Process stack and craft tiles from level JSON.

        Based on sp_template TileCraft.cs and Tile.cs:
        - Stack/Craft tiles have tile_type like "stack_e" or "craft_s"
        - The direction (e/w/s/n) indicates where tiles are stacked/produced
        - Stack info is in tile_data[2] with format [total_count, "tile_types"]
        - Tiles are stacked vertically with upperStackedTile/underStackedTile links
        - Only the topmost tile in a stack can be picked
        - For craft: only the "crafted" (produced) tile can be picked

        Args:
            state: GameState to update
            stack_craft_tiles: List of (layer_idx, pos, tile_data) for stack/craft tiles
            t0_assignment_map: Pre-computed t0 tile assignments
            use_tile_count: Number of tile types to use for t0 distribution
        """
        for layer_idx, pos, tile_data in stack_craft_tiles:
            tile_type_str = tile_data[0]  # e.g., "stack_e" or "craft_s"

            # Parse position
            parts = pos.split("_")
            x_idx = int(parts[0]) if len(parts) > 0 else 0
            y_idx = int(parts[1]) if len(parts) > 1 else 0

            # Determine if stack or craft and get direction
            is_craft = tile_type_str.startswith("craft_")
            is_stack = tile_type_str.startswith("stack_")
            direction = tile_type_str.split("_")[1] if "_" in tile_type_str else "s"

            # Get stack info from tile_data[2]
            # Format from LevelEditor: [count] - single element array with count
            # All tiles in stack/craft are "t0" (random) by default
            stack_info = tile_data[2] if len(tile_data) > 2 else None
            if not stack_info or not isinstance(stack_info, list) or len(stack_info) < 1:
                continue

            total_count = int(stack_info[0]) if stack_info[0] else 1
            # All tiles are t0 (random) - sp_template GetTileIDArr() sets all to "t0"
            tile_types = ["t0"] * total_count

            # Calculate spawn position offset based on direction
            # For craft: tiles spawn at adjacent position in the direction
            spawn_offset_x, spawn_offset_y = 0, 0
            if direction == "e":
                spawn_offset_x = 1
            elif direction == "w":
                spawn_offset_x = -1
            elif direction == "s":
                spawn_offset_y = 1
            elif direction == "n":
                spawn_offset_y = -1

            # Create tiles for this stack/craft
            stack_tile_keys: List[str] = []
            created_tiles: List[TileState] = []

            for stack_idx in range(total_count):
                # Get tile type for this stack position
                tile_type = tile_types[stack_idx] if stack_idx < len(tile_types) else "t0"

                # Handle t0 random assignment
                actual_tile_type = tile_type
                if tile_type == "t0":
                    # Use pre-computed assignment or generate new one
                    assignment_key = (layer_idx, f"{pos}_stack_{stack_idx}")
                    if assignment_key in t0_assignment_map:
                        actual_tile_type = t0_assignment_map[assignment_key]
                    else:
                        actual_tile_type = self._rng.choice(self.RANDOM_TILE_POOL[:use_tile_count])

                # Determine effect type
                if is_craft:
                    effect_type = TileEffectType.CRAFT
                elif is_stack and direction == "n":
                    effect_type = TileEffectType.STACK_NORTH
                elif is_stack and direction == "s":
                    effect_type = TileEffectType.STACK_SOUTH
                elif is_stack and direction == "e":
                    effect_type = TileEffectType.STACK_EAST
                elif is_stack and direction == "w":
                    effect_type = TileEffectType.STACK_WEST
                else:
                    effect_type = TileEffectType.NONE

                # Create tile state
                tile_state = TileState(
                    tile_type=actual_tile_type,
                    layer_idx=layer_idx,
                    x_idx=x_idx,
                    y_idx=y_idx,
                    effect_type=effect_type,
                    effect_data={},
                    is_stack_tile=True,
                    is_craft_tile=is_craft,
                    stack_index=stack_idx,
                    stack_max_index=total_count - 1,
                    craft_direction=direction,
                )

                # For craft tiles: only the topmost tile is "crafted" (visible/pickable)
                if is_craft:
                    tile_state.is_crafted = (stack_idx == total_count - 1)

                # Store in stacked_tiles dict with full key
                # Save original_full_key before any position changes (for craft box lookup)
                full_key = tile_state.full_key
                tile_state.original_full_key = full_key
                state.stacked_tiles[full_key] = tile_state
                stack_tile_keys.append(full_key)
                created_tiles.append(tile_state)

            # Set up upper/under stacked tile relationships
            for i, tile in enumerate(created_tiles):
                if i > 0:
                    tile.under_stacked_tile_key = created_tiles[i - 1].full_key
                if i < len(created_tiles) - 1:
                    tile.upper_stacked_tile_key = created_tiles[i + 1].full_key
                tile.root_stacked_tile_key = created_tiles[0].full_key

            # Store craft box info
            craft_box_key = f"{layer_idx}_{pos}"
            state.craft_boxes[craft_box_key] = stack_tile_keys

            # Add the topmost tile (or crafted tile for craft) to the regular tiles dict
            # so it can be found by normal tile picking logic
            if created_tiles:
                # For craft: add the crafted tile at the spawn position if empty
                # For stack: add all tiles at the same position (only topmost pickable)
                if is_craft:
                    # The crafted tile appears at offset position
                    crafted_tile = created_tiles[-1]  # topmost
                    spawn_x = x_idx + spawn_offset_x
                    spawn_y = y_idx + spawn_offset_y
                    spawn_pos = f"{spawn_x}_{spawn_y}"

                    # Check if spawn position is already occupied by another tile
                    # Based on sp_template TileCraft.cs CheckCraftBoxMask():
                    # Craft should only emit if spawn position is empty
                    layer_tiles_at_layer = state.tiles.get(layer_idx, {})
                    spawn_occupied = spawn_pos in layer_tiles_at_layer

                    if not spawn_occupied:
                        # Spawn position is empty, emit the crafted tile
                        crafted_tile.x_idx = spawn_x
                        crafted_tile.y_idx = spawn_y
                        if layer_idx not in state.tiles:
                            state.tiles[layer_idx] = {}
                        state.tiles[layer_idx][spawn_pos] = crafted_tile
                    else:
                        # Spawn position is blocked - keep tile in craft box (not emitted)
                        # The tile stays is_crafted=False until spawn position clears
                        crafted_tile.is_crafted = False
                else:
                    # For stack: all tiles are at the same position, only top is pickable
                    # Add the topmost to tiles dict for picking
                    # Note: created_tiles is built in order [stack_idx=0, 1, 2, ..., n-1]
                    # So created_tiles[-1] is the tile with highest stack_index (the TOP tile)
                    top_tile = created_tiles[-1]

                    if layer_idx not in state.tiles:
                        state.tiles[layer_idx] = {}
                    state.tiles[layer_idx][pos] = top_tile

            # Track goals for stack_s and craft_s
            if tile_type_str in self.GOAL_TYPES:
                state.goals_remaining[tile_type_str] = (
                    state.goals_remaining.get(tile_type_str, 0) + total_count
                )

    def _is_stack_blocked(self, state: GameState, tile: TileState) -> bool:
        """Check if a stack tile is blocked by upper stacked tiles.

        Based on sp_template Tile.cs CheckCanPick() for stack tiles:
        - If upperStackedTile exists and is not picked, tile is blocked
        """
        if not tile.is_stack_tile:
            return False

        if tile.upper_stacked_tile_key:
            upper_tile = state.stacked_tiles.get(tile.upper_stacked_tile_key)
            if upper_tile and not upper_tile.picked:
                return True

        return False

    def _is_craft_tile_pickable(self, state: GameState, tile: TileState) -> bool:
        """Check if a craft tile can be picked.

        Based on sp_template TileCraft.cs CanPickTile():
        - Tile must be crafted (produced from craft box)
        - Tile must not have unpicked upper stacked tile
        - Tile must not be blocked by upper layer tiles
        """
        if not tile.is_craft_tile:
            return True

        # Must be crafted (produced from craft box)
        if not tile.is_crafted:
            return False

        # Check upper stacked tile
        if tile.upper_stacked_tile_key:
            upper_tile = state.stacked_tiles.get(tile.upper_stacked_tile_key)
            if upper_tile and not upper_tile.picked:
                return False

        return True

    def _emit_blocked_craft_tiles(self, state: GameState) -> None:
        """Check all craft boxes and emit tiles if their spawn positions are now available.

        Based on sp_template TileCraft.cs CheckCraftBoxMask():
        - After any tile is removed, craft boxes should check if they can emit
        - If spawn position is empty and craft box has an un-emitted topmost tile, emit it

        NOTE: This only applies to craft tiles, not stack tiles.
        Stack tiles are picked from their original position, not emitted to offset positions.
        """
        for craft_box_key, tile_keys in state.craft_boxes.items():
            # Parse craft box position (layer_idx_x_y)
            parts = craft_box_key.split("_")
            if len(parts) < 3:
                continue
            layer_idx = int(parts[0])
            box_x = int(parts[1])
            box_y = int(parts[2])

            # Find the topmost un-picked tile in this craft box
            topmost_unpicked = None
            for key in reversed(tile_keys):  # Start from top (highest stack index)
                tile = state.stacked_tiles.get(key)
                if tile and not tile.picked:
                    topmost_unpicked = tile
                    break

            if not topmost_unpicked:
                continue

            # Skip stack tiles - they are picked from their original position
            # Only craft tiles emit to offset positions
            if not topmost_unpicked.is_craft_tile:
                continue

            # If tile is already crafted (emitted), skip
            if topmost_unpicked.is_crafted:
                continue

            # Calculate spawn position based on craft direction
            direction = topmost_unpicked.craft_direction
            spawn_offset_x, spawn_offset_y = 0, 0
            if direction == "e":
                spawn_offset_x = 1
            elif direction == "w":
                spawn_offset_x = -1
            elif direction == "s":
                spawn_offset_y = 1
            elif direction == "n":
                spawn_offset_y = -1

            spawn_x = box_x + spawn_offset_x
            spawn_y = box_y + spawn_offset_y
            spawn_pos = f"{spawn_x}_{spawn_y}"

            # Check if spawn position is now empty
            layer_tiles = state.tiles.get(layer_idx, {})
            spawn_occupied = spawn_pos in layer_tiles and not layer_tiles[spawn_pos].picked

            if not spawn_occupied:
                # Spawn position is empty, emit the tile
                topmost_unpicked.is_crafted = True
                topmost_unpicked.x_idx = spawn_x
                topmost_unpicked.y_idx = spawn_y

                # Add to tiles dict
                if layer_idx not in state.tiles:
                    state.tiles[layer_idx] = {}
                state.tiles[layer_idx][spawn_pos] = topmost_unpicked

    def _process_craft_after_pick(self, state: GameState, picked_tile: TileState) -> None:
        """Process craft box after a tile is picked.

        Based on sp_template TileCraft.cs:
        - When crafted tile is picked, the next tile in stack becomes crafted
        - The new crafted tile moves to the spawn position
        """
        if not picked_tile.is_craft_tile:
            return

        # Find the craft box this tile belongs to
        # Use original_full_key since x_idx/y_idx may have changed for craft tiles
        lookup_key = picked_tile.original_full_key or picked_tile.full_key
        craft_box_key = None
        for key, tile_keys in state.craft_boxes.items():
            if lookup_key in tile_keys:
                craft_box_key = key
                break

        if not craft_box_key:
            return

        # Find the next tile in the stack (under the picked tile)
        if picked_tile.under_stacked_tile_key:
            next_tile = state.stacked_tiles.get(picked_tile.under_stacked_tile_key)
            if next_tile and not next_tile.picked:
                # The spawn position is now the position where picked tile was
                spawn_x = picked_tile.x_idx
                spawn_y = picked_tile.y_idx
                spawn_pos = f"{spawn_x}_{spawn_y}"

                # Check if spawn position is empty (the picked tile should be removed already)
                # Craft only emits when spawn position is clear
                layer_tiles = state.tiles.get(next_tile.layer_idx, {})
                spawn_occupied = spawn_pos in layer_tiles and not layer_tiles[spawn_pos].picked

                if not spawn_occupied:
                    # Spawn position is empty, emit the next tile
                    next_tile.is_crafted = True
                    next_tile.upper_stacked_tile_key = None
                    next_tile.x_idx = spawn_x
                    next_tile.y_idx = spawn_y

                    # Update tiles dict
                    pos_key = next_tile.position_key
                    layer_tiles[pos_key] = next_tile
                else:
                    # Spawn position still blocked - tile remains in craft box
                    next_tile.is_crafted = False

    def _play_game(self, state: GameState, profile: BotProfile) -> GameState:
        """Play through a game with the given bot profile."""
        while not self._is_game_over(state):
            moves = self._get_available_moves(state)

            if not moves:
                state.failed = True
                break

            # Score moves based on profile
            for move in moves:
                move.score = self._score_move_with_profile(move, state, profile)

            # Select move based on profile behavior
            selected_move = self._select_move_with_profile(moves, state, profile)

            if selected_move:
                self._apply_move(state, selected_move)
                state.moves_used += 1

                # Process move effects (frog moves, bomb decreases, etc.)
                self._process_move_effects(state)

        # Determine final state
        if not state.failed:
            goals_cleared = all(count <= 0 for count in state.goals_remaining.values())
            remaining_tiles = sum(
                1 for layer in state.tiles.values()
                for tile in layer.values()
                if not tile.picked
            )
            # Level is cleared when all goals met AND all tiles picked AND dock empty
            state.cleared = goals_cleared and remaining_tiles == 0 and len(state.dock_tiles) == 0

        return state

    def _is_game_over(self, state: GameState) -> bool:
        """Check if the game is over."""
        # Check goals cleared
        if all(count <= 0 for count in state.goals_remaining.values()):
            # Also check if all tiles are cleared (only count unpicked tiles)
            remaining_tiles = sum(
                1 for layer in state.tiles.values()
                for tile in layer.values()
                if not tile.picked
            )
            if remaining_tiles == 0 and len(state.dock_tiles) == 0:
                state.cleared = True
                return True

        # Check dock full (game fail condition)
        if self._is_dock_full(state):
            state.failed = True
            return True

        # Check bomb exploded
        for pos, remaining in state.bomb_tiles.items():
            if remaining <= 0:
                state.failed = True
                return True

        # Check max moves
        if state.moves_used >= state.max_moves:
            state.failed = True
            return True

        return False

    def _is_dock_full(self, state: GameState) -> bool:
        """Check if dock is full without any pending matches."""
        # Count tiles in dock that aren't about to be matched
        type_counts: Dict[str, int] = {}
        for tile in state.dock_tiles:
            type_counts[tile.tile_type] = type_counts.get(tile.tile_type, 0) + 1

        # Calculate tiles that will remain after matches
        remaining_count = 0
        for tile_type, count in type_counts.items():
            remaining_count += count % 3  # Only remainder after 3-matches

        return remaining_count >= state.max_dock_slots

    def _get_available_moves(self, state: GameState) -> List[Move]:
        """Get all available moves (pickable tiles) in current state."""
        moves = []
        accessible = self._get_accessible_tiles(state)

        # Count tiles by type in dock for match prediction
        dock_type_counts: Dict[str, int] = {}
        for tile in state.dock_tiles:
            dock_type_counts[tile.tile_type] = dock_type_counts.get(tile.tile_type, 0) + 1

        for tile_state in accessible:
            if tile_state.tile_type not in self.MATCHABLE_TYPES:
                continue

            # Check if tile can be picked (effect conditions)
            if not tile_state.can_pick():
                continue

            # Check if blocked by upper tiles (layer blocking)
            if self._is_blocked_by_upper(state, tile_state):
                continue

            # Check stack blocking (upper stacked tiles in same stack)
            if tile_state.is_stack_tile and self._is_stack_blocked(state, tile_state):
                continue

            # Check craft tile pickability
            if tile_state.is_craft_tile and not self._is_craft_tile_pickable(state, tile_state):
                continue

            # Calculate match info
            dock_count = dock_type_counts.get(tile_state.tile_type, 0)
            will_match = dock_count >= 2  # Will complete a 3-match

            moves.append(Move(
                layer_idx=tile_state.layer_idx,
                position=tile_state.position_key,
                tile_type=tile_state.tile_type,
                tile_state=tile_state,
                attribute=tile_state.effect_type.value,
                match_count=dock_count + 1,
                will_match=will_match,
            ))

        return moves

    def _get_accessible_tiles(self, state: GameState) -> List[TileState]:
        """Get all tiles that are not picked yet."""
        accessible = []

        for layer_idx in sorted(state.tiles.keys(), reverse=True):
            layer_tiles = state.tiles.get(layer_idx, {})
            for pos, tile_state in layer_tiles.items():
                if not tile_state.picked:
                    accessible.append(tile_state)

        return accessible

    def _is_blocked_by_upper(self, state: GameState, tile: TileState) -> bool:
        """Check if a tile is blocked by tiles in upper layers.

        Based on sp_template TileGroup.FindAllUpperTiles logic:
        - Same parity (layer 0→2, 1→3): Check same position only
        - Different parity: Compare layer col sizes to determine offset direction
          - Upper layer col > current layer col: Check (0,0), (+1,0), (0,+1), (+1,+1)
          - Upper layer col <= current layer col: Check (-1,-1), (0,-1), (-1,0), (0,0)

        Parity is determined by layer_idx % 2.
        """
        if not state.tiles:
            return False

        max_layer = max(state.tiles.keys())
        tile_parity = tile.layer_idx % 2
        cur_layer_col = state.layer_cols.get(tile.layer_idx, 7)

        for upper_layer_idx in range(tile.layer_idx + 1, max_layer + 1):
            layer = state.tiles.get(upper_layer_idx, {})
            if not layer:
                continue

            upper_parity = upper_layer_idx % 2
            upper_layer_col = state.layer_cols.get(upper_layer_idx, 7)

            # Determine blocking positions based on parity and layer size
            # This matches sp_template TileGroup.FindAllUpperTiles exactly
            if tile_parity == upper_parity:
                # Same parity (odd-odd or even-even): only check same position
                blocking_offsets = [(0, 0)]
            else:
                # Different parity: compare layer col sizes
                if upper_layer_col > cur_layer_col:
                    # Upper layer is bigger (has more columns)
                    # Check: (0,0), (+1,0), (0,+1), (+1,+1)
                    blocking_offsets = [(0, 0), (1, 0), (0, 1), (1, 1)]
                else:
                    # Upper layer is smaller or same size
                    # Check: (-1,-1), (0,-1), (-1,0), (0,0)
                    blocking_offsets = [(-1, -1), (0, -1), (-1, 0), (0, 0)]

            for dx, dy in blocking_offsets:
                bx = tile.x_idx + dx
                by = tile.y_idx + dy
                pos_key = f"{bx}_{by}"
                if pos_key in layer and not layer[pos_key].picked:
                    return True

        return False

    def _apply_move(self, state: GameState, move: Move) -> int:
        """Apply a move to the game state. Returns number of tiles cleared."""
        tile_state = move.tile_state
        if tile_state is None:
            return 0

        # Mark tile as picked
        tile_state.picked = True

        # Handle stack tile removal - update the tiles dict with the next tile
        if tile_state.is_stack_tile and not tile_state.is_craft_tile:
            self._process_stack_after_pick(state, tile_state)

        # Handle craft tile - produce next tile from craft box
        if tile_state.is_craft_tile:
            self._process_craft_after_pick(state, tile_state)

        # Add to dock
        state.dock_tiles.append(tile_state)

        # Update adjacent tile effects (ice, chain, grass)
        self._update_adjacent_effects(state, tile_state)

        # Check for 3-match in dock
        cleared_by_type = self._process_dock_matches(state)

        total_tiles_cleared = sum(cleared_by_type.values())
        state.total_tiles_cleared += total_tiles_cleared
        if total_tiles_cleared >= 3:
            state.combo_count += 1

        # Progress goals based on cleared tile types
        for tile_type, count in cleared_by_type.items():
            if tile_type in state.goals_remaining:
                state.goals_remaining[tile_type] = max(0, state.goals_remaining[tile_type] - count)

        return total_tiles_cleared

    def _process_stack_after_pick(self, state: GameState, picked_tile: TileState) -> None:
        """Process stack after a tile is picked.

        Based on sp_template Tile.cs RemoveTileFromStack():
        - When a stacked tile is picked, the tile under it becomes the new top
        - Update the tiles dict to point to the new top tile
        """
        if not picked_tile.is_stack_tile:
            return

        # Find the tile under this one
        if picked_tile.under_stacked_tile_key:
            under_tile = state.stacked_tiles.get(picked_tile.under_stacked_tile_key)
            if under_tile and not under_tile.picked:
                # Update the under tile's upper reference
                under_tile.upper_stacked_tile_key = None

                # Update tiles dict to point to the new top tile
                layer_tiles = state.tiles.get(picked_tile.layer_idx, {})
                pos_key = picked_tile.position_key
                if pos_key in layer_tiles:
                    layer_tiles[pos_key] = under_tile

    def _process_dock_matches(self, state: GameState) -> Dict[str, int]:
        """Process 3-matches in dock. Returns dict of cleared tiles by type."""
        cleared_by_type: Dict[str, int] = {}

        # Count tiles by type
        type_counts: Dict[str, List[TileState]] = {}
        for tile in state.dock_tiles:
            if tile.tile_type not in type_counts:
                type_counts[tile.tile_type] = []
            type_counts[tile.tile_type].append(tile)

        # Remove groups of 3
        for tile_type, tiles in type_counts.items():
            while len(tiles) >= 3:
                # Remove 3 tiles
                for _ in range(3):
                    removed = tiles.pop(0)
                    state.dock_tiles.remove(removed)
                    cleared_by_type[tile_type] = cleared_by_type.get(tile_type, 0) + 1

        return cleared_by_type

    def _update_adjacent_effects(self, state: GameState, picked_tile: TileState) -> None:
        """Update effects on tiles when a tile is picked.

        Ice: ANY unblocked ice tile melts (not just adjacent)
        Grass: Only ADJACENT tiles (4-directional)
        Chain: Only HORIZONTAL adjacent tiles
        """
        x, y = picked_tile.x_idx, picked_tile.y_idx
        layer_idx = picked_tile.layer_idx

        # === Ice 처리: 상위 레이어에 막히지 않은 모든 Ice 타일이 녹음 ===
        # sp_template의 TileEffect.cs OnClickOtherTile() 참조:
        # Ice는 인접 여부와 관계없이, 상위 타일에 막히지 않으면 녹음
        for l_idx, layer_tiles in state.tiles.items():
            for pos_key, tile in layer_tiles.items():
                if tile.picked:
                    continue

                if tile.effect_type == TileEffectType.ICE:
                    # 상위 레이어에 막혀있지 않으면 녹음
                    if not self._is_blocked_by_upper(state, tile):
                        remaining = tile.effect_data.get("remaining", 0)
                        if remaining > 0:
                            tile.effect_data["remaining"] = remaining - 1

        # === Grass 처리: 인접 타일(4방향)에만 영향 ===
        # Adjacent positions (4-directional)
        adjacent_positions = [
            (x + 1, y), (x - 1, y), (x, y + 1), (x, y - 1)
        ]

        layer = state.tiles.get(layer_idx, {})

        for adj_x, adj_y in adjacent_positions:
            pos_key = f"{adj_x}_{adj_y}"
            if pos_key not in layer:
                continue

            adj_tile = layer[pos_key]
            if adj_tile.picked:
                continue

            # Grass effect: decrease remaining when adjacent tile is picked
            if adj_tile.effect_type == TileEffectType.GRASS:
                remaining = adj_tile.effect_data.get("remaining", 0)
                if remaining > 0:
                    adj_tile.effect_data["remaining"] = remaining - 1

        # === Chain 처리: 수평 인접 타일에만 영향 ===
        horizontal_positions = [(x + 1, y), (x - 1, y)]

        for adj_x, adj_y in horizontal_positions:
            pos_key = f"{adj_x}_{adj_y}"
            if pos_key not in layer:
                continue

            adj_tile = layer[pos_key]
            if adj_tile.picked:
                continue

            if adj_tile.effect_type == TileEffectType.CHAIN:
                adj_tile.effect_data["unlocked"] = True

        # Update link tiles status
        self._update_link_tiles_status(state)

    def _update_link_tiles_status(self, state: GameState) -> None:
        """Update can_pick status for all link tiles."""
        for layer_tiles in state.tiles.values():
            for tile in layer_tiles.values():
                if tile.picked:
                    continue

                if tile.effect_type in (TileEffectType.LINK_EAST, TileEffectType.LINK_WEST,
                                         TileEffectType.LINK_SOUTH, TileEffectType.LINK_NORTH):
                    linked_pos = tile.effect_data.get("linked_pos", "")

                    # Find linked tile
                    linked_tile = None
                    for lt in state.tiles.values():
                        if linked_pos in lt:
                            linked_tile = lt[linked_pos]
                            break

                    if linked_tile is None or linked_tile.picked:
                        tile.effect_data["can_pick"] = True
                    else:
                        # Both tiles must be unblocked for link to be pickable
                        tile_blocked = self._is_blocked_by_upper(state, tile)
                        linked_blocked = self._is_blocked_by_upper(state, linked_tile)
                        tile.effect_data["can_pick"] = not tile_blocked and not linked_blocked

    def _get_frog_movable_tiles(self, state: GameState) -> List[Tuple[int, str, TileState]]:
        """Get list of tiles that frogs can move to.

        Frogs can move to any selectable tile that:
        - Is not picked
        - Is not blocked by upper layer
        - Does not already have a frog on it
        - Is a matchable tile type (not goal tiles or special tiles)
        """
        available_tiles: List[Tuple[int, str, TileState]] = []

        for layer_idx, layer in state.tiles.items():
            for pos, tile in layer.items():
                # Skip picked tiles
                if tile.picked:
                    continue

                # Skip non-matchable tiles (goal tiles, etc.)
                if tile.tile_type not in self.MATCHABLE_TYPES:
                    continue

                # Skip tiles that already have a frog
                if tile.effect_data.get("on_frog", False):
                    continue

                # Skip tiles blocked by upper layer
                if self._is_blocked_by_upper(state, tile):
                    continue

                # Skip tiles that can't be picked due to effects (chain, ice, etc.)
                if not tile.can_pick():
                    continue

                available_tiles.append((layer_idx, pos, tile))

        return available_tiles

    def _move_all_frogs(self, state: GameState) -> None:
        """Move all frogs to random available tiles.

        - All frogs move simultaneously when user picks a tile
        - Each frog moves to a random selectable tile (excluding current frog positions)
        - If fewer available tiles than frogs, excess frogs are removed
        """
        if not state.frog_positions:
            return

        # Get all tiles that frogs can move to
        available_tiles = self._get_frog_movable_tiles(state)

        # Shuffle for random assignment
        self._rng.shuffle(available_tiles)

        # Collect current frog tiles (any tile with on_frog=True)
        frog_tiles: List[Tuple[int, str, TileState]] = []
        for layer_idx, layer in state.tiles.items():
            for pos, tile in layer.items():
                if tile.effect_data.get("on_frog", False):
                    frog_tiles.append((layer_idx, pos, tile))

        # Clear all current frog positions
        for layer_idx, pos, tile in frog_tiles:
            tile.effect_data["on_frog"] = False
        state.frog_positions.clear()

        # Move frogs to new positions
        # If fewer available tiles than frogs, some frogs won't have a place to go (removed)
        num_frogs_to_move = min(len(frog_tiles), len(available_tiles))

        for i in range(num_frogs_to_move):
            target_layer_idx, target_pos, target_tile = available_tiles[i]
            target_tile.effect_data["on_frog"] = True
            state.frog_positions.add(target_pos)

    def _process_move_effects(self, state: GameState) -> None:
        """Process effects that trigger after each move (frog, bomb, curtain, teleport)."""
        # Decrease bomb counters
        for pos in list(state.bomb_tiles.keys()):
            state.bomb_tiles[pos] -= 1

            # Update tile effect data
            for layer in state.tiles.values():
                if pos in layer:
                    layer[pos].effect_data["remaining"] = state.bomb_tiles[pos]

        # Move frogs to random available tiles (sp_template FrogManager behavior)
        # All frogs move simultaneously when user picks a tile
        self._move_all_frogs(state)

        # Toggle curtains (sp_template deterministic logic)
        # Curtains that are not blocked by upper layer tiles toggle on every move
        for layer in state.tiles.values():
            for tile in layer.values():
                if tile.effect_type == TileEffectType.CURTAIN and not tile.picked:
                    # Only toggle if not blocked by upper layer tiles
                    if not self._is_blocked_by_upper(state, tile):
                        tile.effect_data["is_open"] = not tile.effect_data.get("is_open", True)

        # Process teleport (sp_template TileGroup.AddClickCount logic)
        # Teleport activates every 3 clicks and swaps tile types in a circular manner
        self._process_teleport(state)

        # Check blocked craft tiles and emit if spawn positions are now available
        # This handles cases where a non-craft tile was removed, freeing up a spawn position
        self._emit_blocked_craft_tiles(state)

    def _process_teleport(self, state: GameState) -> None:
        """Process teleport effect - activates every 3 moves.

        Based on sp_template TileGroup.cs AddClickCount():
        - Every 3rd click, all teleport tiles swap their tile types
        - Uses Sattolo shuffle for circular permutation (no tile stays in place)
        - If fewer than 2 teleport tiles remain, teleport is deactivated
        """
        state.teleport_click_count += 1

        # Collect active teleport tiles
        active_teleport_tiles: List[TileState] = []
        for layer_idx, layer in state.tiles.items():
            for pos, tile in layer.items():
                if tile.effect_type == TileEffectType.TELEPORT and not tile.picked:
                    active_teleport_tiles.append(tile)

        # Update teleport_tiles list for tracking
        state.teleport_tiles = [(t.layer_idx, t.position_key) for t in active_teleport_tiles]

        # If fewer than 2 teleport tiles, no swap needed
        if len(active_teleport_tiles) < 2:
            return

        # Check if this is a teleport activation (every 3rd click)
        if state.teleport_click_count % 3 != 0:
            return

        # Perform Sattolo shuffle for circular permutation
        # This ensures every tile gets a new type (no fixed points)
        tiles_copy = active_teleport_tiles.copy()
        n = len(tiles_copy)

        # Sattolo shuffle: i > 0, j = random(0, i-1)
        for i in range(n - 1, 0, -1):
            j = self._rng.randint(0, i - 1)  # Note: exclusive upper bound like Sattolo
            tiles_copy[i], tiles_copy[j] = tiles_copy[j], tiles_copy[i]

        # Now perform circular tile type swap based on shuffled order
        # tiles[0] gets type from tiles[1], tiles[1] from tiles[2], ..., tiles[n-1] from tiles[0]
        if n > 0:
            first_type = active_teleport_tiles[0].tile_type
            for i in range(n - 1):
                active_teleport_tiles[i].tile_type = active_teleport_tiles[i + 1].tile_type
            active_teleport_tiles[n - 1].tile_type = first_type

    def _score_move_with_profile(
        self, move: Move, state: GameState, profile: BotProfile
    ) -> float:
        """Score a move based on bot profile characteristics."""
        base_score = 1.0

        # Major bonus for moves that will complete a 3-match
        if move.will_match:
            base_score += profile.pattern_recognition * 5.0

        # Bonus for tiles that are close to matching (2 in dock)
        if move.match_count == 2:
            base_score += profile.pattern_recognition * 2.0

        # Goal priority bonus
        if state.goals_remaining:
            goal_bonus = profile.goal_priority * 2.0
            base_score += goal_bonus

        # Layer blocking awareness - prefer clearing upper layers
        layer_bonus = move.layer_idx * profile.blocking_awareness * 0.3
        base_score += layer_bonus

        # Chain preference - bonus for clearing effect tiles
        if move.attribute != "none":
            attribute_bonus = profile.chain_preference * 1.5
            base_score += attribute_bonus

        # Penalty for moves that might fill dock without matching
        dock_count = len(state.dock_tiles)
        if dock_count >= 5 and not move.will_match:
            base_score -= profile.blocking_awareness * 2.0

        # Add randomness based on profile
        randomness = (1 - profile.pattern_recognition) * self._rng.random() * 2
        base_score += randomness

        return base_score

    def _select_move_with_profile(
        self,
        moves: List[Move],
        state: GameState,
        profile: BotProfile,
    ) -> Optional[Move]:
        """Select a move based on bot profile."""
        if not moves:
            return None

        # Check for mistake (random wrong choice)
        if self._rng.random() < profile.mistake_rate:
            return self._rng.choice(moves)

        # Sort by score
        sorted_moves = sorted(moves, key=lambda m: m.score, reverse=True)

        # Apply patience factor
        if profile.patience < 0.5 and len(sorted_moves) > 1:
            cutoff = max(1, int(len(sorted_moves) * profile.patience))
            return self._rng.choice(sorted_moves[:cutoff])

        # Lookahead for higher skill bots
        if profile.lookahead_depth > 0 and len(sorted_moves) > 1:
            best_move = sorted_moves[0]
            best_future_score = self._estimate_future_score(state, best_move)

            for move in sorted_moves[1:min(3, len(sorted_moves))]:
                future_score = self._estimate_future_score(state, move)
                if future_score > best_future_score:
                    best_move = move
                    best_future_score = future_score

            return best_move

        return sorted_moves[0]

    def _estimate_future_score(self, state: GameState, move: Move) -> float:
        """Estimate future position quality after making a move."""
        score = 0.0

        # Bonus if move completes a match
        if move.will_match:
            score += 10.0

        # Count how many potential matches would be available
        dock_type = move.tile_type
        dock_count = sum(1 for t in state.dock_tiles if t.tile_type == dock_type)

        if dock_count == 1:  # Would become 2 in dock
            # Check if there are more of this type on the board
            accessible = self._get_accessible_tiles(state)
            same_type_count = sum(
                1 for t in accessible
                if t.tile_type == dock_type and t.position_key != move.position
            )
            if same_type_count >= 1:
                score += 3.0  # Good - can complete match next turn

        # Penalty for filling dock without matching
        if dock_count == 0 and not move.will_match:
            current_dock = len(state.dock_tiles)
            if current_dock >= 5:
                score -= 5.0

        return score

    def _aggregate_results(
        self,
        bot_results: List[BotSimulationResult],
        team: BotTeam,
        max_moves: int,
    ) -> MultiBotAssessmentResult:
        """Aggregate individual bot results into comprehensive assessment."""
        total_weight = 0
        weighted_difficulty = 0

        for result in bot_results:
            profile = None
            for p in team.profiles:
                if p.bot_type == result.bot_type:
                    profile = p
                    break

            if profile is None:
                continue

            bot_difficulty = self._calculate_bot_difficulty(result, max_moves)
            weighted_difficulty += bot_difficulty * profile.weight
            total_weight += profile.weight

        overall_difficulty = (
            weighted_difficulty / total_weight if total_weight > 0 else 50
        )

        difficulties = [
            self._calculate_bot_difficulty(r, max_moves) for r in bot_results
        ]
        variance = statistics.variance(difficulties) if len(difficulties) > 1 else 0

        grade = self._difficulty_to_grade(overall_difficulty)
        target_audience = self._determine_target_audience(bot_results)
        recommended_moves = self._calculate_recommended_moves(bot_results, max_moves)
        analysis_summary = self._build_analysis_summary(bot_results, overall_difficulty)

        return MultiBotAssessmentResult(
            bot_results=bot_results,
            overall_difficulty=overall_difficulty,
            difficulty_grade=grade,
            target_audience=target_audience,
            difficulty_variance=variance,
            recommended_moves=recommended_moves,
            analysis_summary=analysis_summary,
        )

    def _calculate_bot_difficulty(
        self, result: BotSimulationResult, max_moves: int
    ) -> float:
        """Calculate difficulty score for a single bot."""
        clear_difficulty = (1 - result.clear_rate) * 60

        if result.avg_moves > 0:
            move_factor = min(1.0, result.avg_moves / max_moves)
            move_difficulty = move_factor * 30
        else:
            move_difficulty = 30

        variance_factor = min(1.0, result.std_moves / 10) * 10

        return min(100, clear_difficulty + move_difficulty + variance_factor)

    def _difficulty_to_grade(self, score: float) -> str:
        """Convert difficulty score to grade."""
        if score <= 20:
            return "S"
        elif score <= 40:
            return "A"
        elif score <= 60:
            return "B"
        elif score <= 80:
            return "C"
        else:
            return "D"

    def _determine_target_audience(
        self, bot_results: List[BotSimulationResult]
    ) -> str:
        """Determine recommended target audience based on clear rates."""
        target_clear_rate = 0.7
        best_match = None
        best_diff = float('inf')

        for result in bot_results:
            diff = abs(result.clear_rate - target_clear_rate)
            if diff < best_diff:
                best_diff = diff
                best_match = result

        if best_match is None:
            return "Average"

        audience_map = {
            BotType.NOVICE: "초보자 (입문자용)",
            BotType.CASUAL: "캐주얼 플레이어",
            BotType.AVERAGE: "일반 플레이어",
            BotType.EXPERT: "숙련 플레이어",
            BotType.OPTIMAL: "하드코어 플레이어",
        }

        return audience_map.get(best_match.bot_type, "일반 플레이어")

    def _calculate_recommended_moves(
        self, bot_results: List[BotSimulationResult], max_moves: int
    ) -> int:
        """Calculate recommended move count based on Average bot performance."""
        for result in bot_results:
            if result.bot_type == BotType.AVERAGE:
                if result.clear_rate > 0.8:
                    return max(15, int(result.avg_moves * 0.9))
                elif result.clear_rate < 0.6:
                    return min(50, int(result.avg_moves * 1.2))
                else:
                    return int(result.avg_moves)

        if bot_results:
            avg = statistics.mean([r.avg_moves for r in bot_results])
            return int(avg)

        return max_moves

    def _build_analysis_summary(
        self,
        bot_results: List[BotSimulationResult],
        overall_difficulty: float,
    ) -> Dict[str, Any]:
        """Build detailed analysis summary."""
        insights = []

        expert_result = next(
            (r for r in bot_results if r.bot_type == BotType.EXPERT), None
        )
        if expert_result and expert_result.clear_rate > 0.95:
            insights.append("숙련자에게 너무 쉬울 수 있습니다.")

        casual_result = next(
            (r for r in bot_results if r.bot_type == BotType.CASUAL), None
        )
        if casual_result and casual_result.clear_rate < 0.3:
            insights.append("캐주얼 플레이어에게 너무 어려울 수 있습니다.")

        novice_result = next(
            (r for r in bot_results if r.bot_type == BotType.NOVICE), None
        )
        average_result = next(
            (r for r in bot_results if r.bot_type == BotType.AVERAGE), None
        )
        if novice_result and average_result:
            gap = average_result.clear_rate - novice_result.clear_rate
            if gap > 0.5:
                insights.append("초보자와 평균 플레이어 간 난이도 격차가 큽니다.")

        clear_rates = {
            r.bot_type.value: round(r.clear_rate * 100, 1)
            for r in bot_results
        }

        return {
            "clear_rates_by_bot": clear_rates,
            "insights": insights,
            "difficulty_category": self._categorize_difficulty(overall_difficulty),
            "balance_score": self._calculate_balance_score(bot_results),
        }

    def _categorize_difficulty(self, score: float) -> str:
        """Categorize difficulty with Korean description."""
        if score <= 20:
            return "튜토리얼급"
        elif score <= 40:
            return "쉬운 난이도"
        elif score <= 60:
            return "적정 난이도"
        elif score <= 80:
            return "챌린지급"
        else:
            return "극한 난이도"

    def _calculate_balance_score(
        self, bot_results: List[BotSimulationResult]
    ) -> float:
        """Calculate how well-balanced the level is for different skill levels."""
        if len(bot_results) < 2:
            return 1.0

        ideal_rates = {
            BotType.NOVICE: 0.4,
            BotType.CASUAL: 0.6,
            BotType.AVERAGE: 0.75,
            BotType.EXPERT: 0.9,
            BotType.OPTIMAL: 0.98,
        }

        total_deviation = 0
        count = 0

        for result in bot_results:
            ideal = ideal_rates.get(result.bot_type, 0.7)
            deviation = abs(result.clear_rate - ideal)
            total_deviation += deviation
            count += 1

        if count == 0:
            return 1.0

        avg_deviation = total_deviation / count
        balance_score = max(0, 1 - avg_deviation * 2)

        return round(balance_score, 2)


# Singleton instance
_bot_simulator: Optional[BotSimulator] = None


def get_bot_simulator() -> BotSimulator:
    """Get or create bot simulator singleton instance."""
    global _bot_simulator
    if _bot_simulator is None:
        _bot_simulator = BotSimulator()
    return _bot_simulator
