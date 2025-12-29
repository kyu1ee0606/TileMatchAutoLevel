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
    # Complete tile type counts (including hidden tiles in stack/craft)
    # This allows optimal bot to know ALL tile information for perfect play
    all_tile_type_counts: Dict[str, int] = field(default_factory=dict)  # tile_type -> total count


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
    linked_tiles: List[Tuple[int, str]] = field(default_factory=list)  # [(layer_idx, position), ...] for link pairs


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

        # First pass: collect ALL t0 tiles AND count existing t1~t15 tiles
        # This includes:
        # 1. Regular t0 tiles on the board
        # 2. t0 tiles INSIDE stack/craft containers
        # 3. Existing t1~t15 tiles (need to track for proper t0 distribution)
        t0_tiles: List[Tuple[int, str, Any]] = []  # (layer_idx, pos_key, tile_data)
        existing_tile_counts: Dict[str, int] = {}  # t1~t15 counts

        for layer_idx in range(num_layers):
            layer_key = f"layer_{layer_idx}"
            layer_data = level_json.get(layer_key, {})
            layer_tiles = layer_data.get("tiles", {})

            if layer_tiles:
                for pos, tile_data in layer_tiles.items():
                    if not isinstance(tile_data, list) or not tile_data:
                        continue
                    tile_type = tile_data[0]

                    # Check if this is a stack/craft tile with hidden t0 tiles inside
                    is_stack = isinstance(tile_type, str) and tile_type.startswith("stack_")
                    is_craft = isinstance(tile_type, str) and tile_type.startswith("craft_")

                    if is_stack or is_craft:
                        # Stack/craft tiles contain internal t0 tiles
                        # [count] = number of internal tiles to output
                        stack_info = tile_data[2] if len(tile_data) > 2 else None
                        if stack_info and isinstance(stack_info, list) and len(stack_info) > 0:
                            internal_count = int(stack_info[0]) if stack_info[0] else 1
                            # Add internal t0 tiles for distribution
                            for stack_idx in range(internal_count):
                                t0_tiles.append((layer_idx, f"{pos}_stack_{stack_idx}", tile_data))
                    elif tile_type == "t0":
                        # Regular t0 tile
                        t0_tiles.append((layer_idx, pos, tile_data))
                    elif isinstance(tile_type, str) and tile_type.startswith("t") and tile_type[1:].isdigit():
                        # Existing t1~t15 tile - count it
                        tile_num = int(tile_type[1:])
                        if 1 <= tile_num <= 15:
                            existing_tile_counts[tile_type] = existing_tile_counts.get(tile_type, 0) + 1

        # Generate tile type assignments for ALL t0 tiles
        # CRITICAL: Must consider existing t1~t15 counts so that final total per type is divisible by 3
        # Following sp_template's DistributeTiles logic with enhancement
        t0_assignments = self._distribute_t0_tiles(
            len(t0_tiles), use_tile_count, rand_seed, existing_tile_counts
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

        # Calculate complete tile type counts (including hidden tiles in stack/craft)
        # This allows optimal bot to have perfect information about all tiles
        self._calculate_all_tile_counts(state)

        return state

    def _calculate_all_tile_counts(self, state: GameState) -> None:
        """Calculate complete counts of all tile types including hidden tiles.

        This gives optimal bot perfect information about:
        - Regular tiles on the board
        - Tiles hidden inside stack/craft containers

        Used for perfect play decisions.
        """
        counts: Dict[str, int] = {}

        # Count regular tiles (not stack/craft tiles themselves)
        for layer_tiles in state.tiles.values():
            for tile in layer_tiles.values():
                if not tile.is_stack_tile and not tile.is_craft_tile:
                    tile_type = tile.tile_type
                    if tile_type in self.MATCHABLE_TYPES:
                        counts[tile_type] = counts.get(tile_type, 0) + 1

        # Count all stacked tiles (inside stack/craft containers)
        for tile in state.stacked_tiles.values():
            tile_type = tile.tile_type
            if tile_type in self.MATCHABLE_TYPES:
                counts[tile_type] = counts.get(tile_type, 0) + 1

        state.all_tile_type_counts = counts

    def _distribute_t0_tiles(
        self, t0_count: int, use_tile_count: int, rand_seed: int = 0,
        existing_tile_counts: Optional[Dict[str, int]] = None
    ) -> List[str]:
        """Distribute t0 tiles so that (existing + t0) per type is divisible by 3.

        CRITICAL FIX: Must consider existing t1~t15 tile counts!
        - If t1 already has 4 tiles, we need to add 2 more t1 from t0 to make 6 (divisible by 3)
        - If t2 already has 6 tiles, we can add 0 or 3 or 6... t2 from t0

        Args:
            t0_count: Total number of t0 tiles to assign
            use_tile_count: Number of tile types to use (1-15)
            rand_seed: Seed for random distribution
            existing_tile_counts: Existing t1~t15 tile counts in level

        Returns:
            List of tile type strings (e.g., ["t1", "t1", "t1", "t2", "t2", "t2", ...])
        """
        if t0_count == 0:
            return []

        existing_tile_counts = existing_tile_counts or {}

        # DEBUG
        import os
        if os.environ.get('DEBUG_DISTRIBUTE'):
            print(f"[DEBUG] _distribute_t0_tiles: t0_count={t0_count}, use_tile_count={use_tile_count}, existing={existing_tile_counts}")

        # Use a separate random instance with the seed to avoid state pollution
        import random
        dist_rng = random.Random(rand_seed if rand_seed > 0 else 42)

        # Limit tile types to available pool
        use_tile_count = min(use_tile_count, len(self.RANDOM_TILE_POOL))
        available_types = self.RANDOM_TILE_POOL[:use_tile_count]

        # Step 1: Calculate how many tiles each type NEEDS to become divisible by 3
        # existing % 3 = 0 -> need 0 or 3 or 6...
        # existing % 3 = 1 -> need 2 or 5 or 8...
        # existing % 3 = 2 -> need 1 or 4 or 7...
        type_needs: Dict[str, int] = {}  # tiles needed to reach next multiple of 3
        for tile_type in available_types:
            existing = existing_tile_counts.get(tile_type, 0)
            remainder = existing % 3
            if remainder == 0:
                type_needs[tile_type] = 0  # Already divisible, can add 0/3/6...
            else:
                type_needs[tile_type] = 3 - remainder  # Need this many to complete

        # Step 2: First, fulfill the "needs" for each type
        assignments: List[str] = []
        remaining_t0 = t0_count

        # Priority: types that need 1 or 2 tiles to complete
        types_needing = [(t, n) for t, n in type_needs.items() if n > 0]
        # Sort by need (smaller first for efficiency)
        types_needing.sort(key=lambda x: x[1])

        for tile_type, need in types_needing:
            if remaining_t0 >= need:
                assignments.extend([tile_type] * need)
                remaining_t0 -= need
                type_needs[tile_type] = 0  # Fulfilled

        # Step 3: Distribute remaining t0 tiles in complete sets of 3
        if remaining_t0 > 0:
            # Distribute evenly across all available types
            complete_sets = remaining_t0 // 3
            final_remainder = remaining_t0 % 3

            if complete_sets > 0:
                # Distribute complete sets evenly
                sets_per_type = complete_sets // use_tile_count
                extra_sets = complete_sets % use_tile_count

                for i, tile_type in enumerate(available_types):
                    sets_for_this_type = sets_per_type + (1 if i < extra_sets else 0)
                    assignments.extend([tile_type] * (sets_for_this_type * 3))

            # Step 4: Handle final remainder (0, 1, or 2 tiles)
            # These are problematic - they break the 3-divisibility
            # Strategy: Add to types that are already divisible by 3, so we'll need 2 or 1 more later
            # But since this is the last distribution, we need to be smart
            if final_remainder > 0:
                # Find types where adding these won't break existing balance
                # Or add to types that need complementary amounts
                # For now, add to first type(s) - the level generator should ensure total is correct
                for i in range(final_remainder):
                    assignments.append(available_types[i % use_tile_count])

        # DEBUG: Show assignment counts before shuffle
        if os.environ.get('DEBUG_DISTRIBUTE'):
            assign_counts = {}
            for t in assignments:
                assign_counts[t] = assign_counts.get(t, 0) + 1
            print(f"[DEBUG] Assignments (count={len(assignments)}): {assign_counts}")

        # Shuffle assignments for random placement across board
        dist_rng.shuffle(assignments)

        return assignments

    def _process_stack_craft_tiles(
        self,
        state: GameState,
        stack_craft_tiles: List[Tuple[int, str, Any]],
        t0_assignment_map: Dict[Tuple[int, str], str],
        use_tile_count: int,
    ) -> None:
        """Process stack and craft tiles from level JSON.

        NOTE: Both craft_s and stack_* tiles contain internal t0 tiles that need to be distributed.

        Craft tiles (craft_s/e/w/n):
        - [count] = number of internal tiles to output
        - When all internal tiles are output, the craft tile disappears
        - Each craft tile counts as 1 goal (the craft tile itself, not the internal count)

        Stack tiles (stack_e/w/s/n):
        - [count] = number of internal tiles
        - Work similarly to craft but don't have goal tracking

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

            # Both craft and stack tiles contain internal tiles
            # Skip if neither
            if not is_craft and not is_stack:
                continue

            # For craft tiles: each craft tile = 1 goal
            # The [count] is the number of internal tiles, NOT the goal count
            if is_craft:
                # Each craft tile is 1 goal (when all internal tiles are output, goal is achieved)
                state.goals_remaining[tile_type_str] = state.goals_remaining.get(tile_type_str, 0) + 1

            direction = tile_type_str.split("_")[1] if "_" in tile_type_str else "s"

            # Get stack info from tile_data[2]
            # Format from LevelEditor: [count] - single element array with count
            # All tiles in stack are "t0" (random) by default
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
                    # Use pre-computed assignment from first pass
                    # All stack/craft internal tiles should be in t0_assignment_map
                    assignment_key = (layer_idx, f"{pos}_stack_{stack_idx}")
                    if assignment_key in t0_assignment_map:
                        actual_tile_type = t0_assignment_map[assignment_key]
                    else:
                        # This should not happen if first pass collected all tiles correctly
                        # Fallback to random (but this breaks 3-set rule)
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

            # NOTE: Goal tracking for craft tiles is handled earlier in this function
            # (Line 737-738: each craft tile = 1 goal)
            # Don't add total_count here - that's the internal tile count, not the goal count

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

                # Add to tiles dict (remove any picked tile at spawn position first)
                if layer_idx not in state.tiles:
                    state.tiles[layer_idx] = {}
                # Remove picked tile if exists at spawn position
                if spawn_pos in state.tiles[layer_idx] and state.tiles[layer_idx][spawn_pos].picked:
                    del state.tiles[layer_idx][spawn_pos]
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

                    # Update tiles dict (remove any picked tile at spawn position first)
                    pos_key = next_tile.position_key
                    # Remove picked tile if exists at spawn position
                    if spawn_pos in layer_tiles and layer_tiles[spawn_pos].picked:
                        del layer_tiles[spawn_pos]
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

    def _find_linked_tiles(self, state: GameState, tile_state: TileState) -> List[Tuple[int, str]]:
        """Find linked tiles for a given tile (LINK gimmick).

        Returns list of (layer_idx, position) tuples for tiles that will be selected
        together with this tile due to LINK gimmick.
        """
        linked_tiles = []

        # Forward direction: this tile has LINK attribute pointing to another tile
        if tile_state.effect_type in (TileEffectType.LINK_EAST, TileEffectType.LINK_WEST,
                                       TileEffectType.LINK_SOUTH, TileEffectType.LINK_NORTH):
            linked_pos = tile_state.effect_data.get("linked_pos", "")
            if linked_pos:
                # Find linked tile in the SAME LAYER only
                my_layer_idx = tile_state.layer_idx
                layer_tiles = state.tiles.get(my_layer_idx, {})
                linked_tile = layer_tiles.get(linked_pos)
                if linked_tile and not linked_tile.picked:
                    linked_tiles.append((my_layer_idx, linked_pos))
        else:
            # Reverse direction: check if any LINK tile in the SAME LAYER points to this tile
            my_pos = tile_state.position_key
            my_layer_idx = tile_state.layer_idx
            layer_tiles = state.tiles.get(my_layer_idx, {})
            for pos, tile in layer_tiles.items():
                if tile.picked:
                    continue
                if tile.effect_type in (TileEffectType.LINK_EAST, TileEffectType.LINK_WEST,
                                         TileEffectType.LINK_SOUTH, TileEffectType.LINK_NORTH):
                    if tile.effect_data.get("linked_pos", "") == my_pos:
                        linked_tiles.append((my_layer_idx, pos))
                        break

        return linked_tiles

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

            # Find linked tiles (for LINK gimmick)
            linked_tiles = self._find_linked_tiles(state, tile_state)

            # If this tile is a link target (no link attribute but has a link source pointing to it),
            # check if the source tile is blocked - if so, this tile cannot be picked
            if linked_tiles and tile_state.effect_type not in (TileEffectType.LINK_EAST, TileEffectType.LINK_WEST,
                                                                 TileEffectType.LINK_SOUTH, TileEffectType.LINK_NORTH):
                # This is a link target tile - check if the source is blocked
                source_layer_idx, source_pos = linked_tiles[0]
                source_tile = state.tiles.get(source_layer_idx, {}).get(source_pos)
                if source_tile and self._is_blocked_by_upper(state, source_tile):
                    continue  # Source tile is blocked, so target cannot be picked either

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
                linked_tiles=linked_tiles,
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

    def _can_pick_tile(self, state: GameState, tile: TileState) -> bool:
        """Check if a tile can be picked (not blocked, pickable)."""
        if tile.picked:
            return False
        if tile.tile_type not in self.MATCHABLE_TYPES:
            return False
        if not tile.can_pick():
            return False
        if self._is_blocked_by_upper(state, tile):
            return False
        if tile.is_stack_tile and self._is_stack_blocked(state, tile):
            return False
        if tile.is_craft_tile and not self._is_craft_tile_pickable(state, tile):
            return False
        return True

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

        # Check if this is a LINK tile and find its linked tile (forward direction)
        linked_tile = None
        if tile_state.effect_type in (TileEffectType.LINK_EAST, TileEffectType.LINK_WEST,
                                       TileEffectType.LINK_SOUTH, TileEffectType.LINK_NORTH):
            linked_pos = tile_state.effect_data.get("linked_pos", "")
            # Find linked tile in the SAME LAYER only
            my_layer_tiles = state.tiles.get(tile_state.layer_idx, {})
            linked_tile = my_layer_tiles.get(linked_pos)
        else:
            # Check reverse direction: is there a LINK tile in the SAME LAYER pointing to this tile?
            my_pos = tile_state.position_key
            my_layer_idx = tile_state.layer_idx
            layer_tiles = state.tiles.get(my_layer_idx, {})
            for tile in layer_tiles.values():
                if tile.picked:
                    continue
                if tile.effect_type in (TileEffectType.LINK_EAST, TileEffectType.LINK_WEST,
                                         TileEffectType.LINK_SOUTH, TileEffectType.LINK_NORTH):
                    if tile.effect_data.get("linked_pos", "") == my_pos:
                        linked_tile = tile
                        break

        # Mark tile as picked
        tile_state.picked = True

        # Update all_tile_type_counts when tile is picked
        tile_type = tile_state.tile_type
        if tile_type in state.all_tile_type_counts:
            state.all_tile_type_counts[tile_type] = max(0, state.all_tile_type_counts[tile_type] - 1)

        # Handle stack tile removal - update the tiles dict with the next tile
        if tile_state.is_stack_tile and not tile_state.is_craft_tile:
            self._process_stack_after_pick(state, tile_state)

        # Handle craft tile - produce next tile from craft box
        if tile_state.is_craft_tile:
            self._process_craft_after_pick(state, tile_state)

        # Add to dock
        state.dock_tiles.append(tile_state)

        # If this is a LINK tile, also pick the linked tile
        if linked_tile is not None and not linked_tile.picked:
            linked_tile.picked = True

            # Update all_tile_type_counts for linked tile
            linked_type = linked_tile.tile_type
            if linked_type in state.all_tile_type_counts:
                state.all_tile_type_counts[linked_type] = max(0, state.all_tile_type_counts[linked_type] - 1)

            # Handle stack tile removal for linked tile
            if linked_tile.is_stack_tile and not linked_tile.is_craft_tile:
                self._process_stack_after_pick(state, linked_tile)

            # Handle craft tile for linked tile
            if linked_tile.is_craft_tile:
                self._process_craft_after_pick(state, linked_tile)

            # Add linked tile to dock
            state.dock_tiles.append(linked_tile)

            # Update adjacent effects for linked tile
            self._update_adjacent_effects(state, linked_tile)

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

        # Progress craft_s/stack_s goals when craft/stack tiles are cleared
        # The goal is to clear tiles FROM craft/stack boxes, not the tile types
        if tile_state.is_craft_tile and "craft_s" in state.goals_remaining:
            state.goals_remaining["craft_s"] = max(0, state.goals_remaining["craft_s"] - 1)
        if tile_state.is_stack_tile and not tile_state.is_craft_tile and "stack_s" in state.goals_remaining:
            state.goals_remaining["stack_s"] = max(0, state.goals_remaining["stack_s"] - 1)

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
                    # Note: all_tile_type_counts is already decremented in _apply_move
                    # when tile is picked, so no need to decrement again here

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
        for layer_idx, layer_tiles in state.tiles.items():
            for tile in layer_tiles.values():
                if tile.picked:
                    continue

                if tile.effect_type in (TileEffectType.LINK_EAST, TileEffectType.LINK_WEST,
                                         TileEffectType.LINK_SOUTH, TileEffectType.LINK_NORTH):
                    linked_pos = tile.effect_data.get("linked_pos", "")

                    # Find linked tile in the SAME LAYER only
                    linked_tile = layer_tiles.get(linked_pos)

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
        dock_count = len(state.dock_tiles)

        # CRITICAL: Moves that complete a 3-match get MASSIVE bonus
        # This is the most important factor - always prefer matching
        if move.will_match:
            base_score += 100.0  # Very high - matching is always best

        # IMPORTANT: Tiles that bring us to 2-in-dock are valuable
        # because they set up the next match
        if move.match_count == 2:
            # Check if there's a 3rd tile of this type accessible
            accessible = self._get_accessible_tiles(state)
            same_type_accessible = sum(
                1 for t in accessible
                if t.tile_type == move.tile_type
                and t.position_key != move.position
                and self._can_pick_tile(state, t)
            )
            if same_type_accessible >= 1:
                # Good setup - we can complete match next move
                base_score += profile.pattern_recognition * 20.0
            else:
                # For optimal bot: check if there are hidden tiles of this type
                # that will become available later (perfect information)
                if profile.pattern_recognition >= 1.0:
                    # Optimal bot knows ALL tile counts including hidden
                    total_of_type = state.all_tile_type_counts.get(move.tile_type, 0)
                    in_dock = sum(1 for t in state.dock_tiles if t.tile_type == move.tile_type)
                    # Total includes this tile we're about to pick, so subtract 1
                    remaining_hidden = total_of_type - same_type_accessible - in_dock - 1
                    if remaining_hidden >= 1:
                        # There are hidden tiles that will appear later
                        base_score += 15.0  # Good - can complete later
                    else:
                        # No hidden tiles either - this is truly risky
                        base_score -= 10.0
                else:
                    # Risky - might fill dock without completing match
                    base_score += profile.pattern_recognition * 3.0

        # DOCK DANGER MANAGEMENT
        # As dock fills, non-matching moves become increasingly dangerous
        if dock_count >= 6 and not move.will_match:
            base_score -= 50.0  # Critical danger - avoid non-matching
        elif dock_count >= 5 and not move.will_match:
            base_score -= 20.0  # High danger
        elif dock_count >= 4 and not move.will_match:
            base_score -= profile.blocking_awareness * 5.0

        # Prefer tiles that exist multiple times on the board
        # For optimal bot, also consider hidden tiles in stack/craft
        accessible = self._get_accessible_tiles(state)
        same_type_on_board = sum(
            1 for t in accessible
            if t.tile_type == move.tile_type and t.position_key != move.position
        )

        # Optimal bot uses perfect information about total tile counts
        if profile.pattern_recognition >= 1.0:
            total_of_type = state.all_tile_type_counts.get(move.tile_type, 0)
            in_dock = sum(1 for t in state.dock_tiles if t.tile_type == move.tile_type)
            # Check if this type can form complete sets of 3
            remaining_after_pick = total_of_type - 1  # After picking this tile
            remaining_in_dock = in_dock + 1 if not move.will_match else max(0, in_dock - 2)

            # If total remaining (board + dock) is divisible by 3, good
            total_remaining = remaining_after_pick
            if total_remaining % 3 == 0 and total_remaining > 0:
                base_score += 5.0  # Clean matchable count
            elif remaining_after_pick >= 2:
                base_score += 3.0  # At least 2 more to potentially match

        if same_type_on_board >= 2:
            base_score += profile.pattern_recognition * 2.0
        elif same_type_on_board == 0 and move.match_count < 2:
            # This type has no other accessible tiles - check hidden tiles for optimal bot
            if profile.pattern_recognition >= 1.0:
                total_of_type = state.all_tile_type_counts.get(move.tile_type, 0)
                in_dock = sum(1 for t in state.dock_tiles if t.tile_type == move.tile_type)
                hidden_remaining = total_of_type - in_dock - 1  # -1 for this tile
                if hidden_remaining >= 2:
                    # There are hidden tiles that can complete a match
                    base_score += 5.0
                elif hidden_remaining >= 1 and move.match_count == 1:
                    # One in dock + this + one hidden = 3
                    base_score += 3.0
                else:
                    # Truly risky - no hidden tiles to help
                    # FIXED: Optimal bot will filter these out later, so don't penalize here
                    # Just give neutral score - the filtering will handle safety
                    pass  # No penalty - let the safe move filtering handle it
            else:
                # Non-optimal bot doesn't know about hidden tiles
                base_score -= profile.blocking_awareness * 3.0

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

        # STACK/CRAFT TILE PRIORITY (for Expert+ bots)
        # Expert bots: Basic priority for stack/craft tiles
        # Optimal bot: Perfect information - knows what's inside and strategizes accordingly
        if profile.blocking_awareness >= 0.95:  # Expert, Optimal bots only
            tile_state = move.tile_state
            if tile_state:
                # EXPERT BOT: Basic priority (pattern_recognition < 1.0)
                if profile.pattern_recognition < 1.0:
                    # Prioritize craft tiles (they spawn new tiles when cleared)
                    if tile_state.is_craft_tile:
                        if dock_count <= 4:
                            base_score += profile.goal_priority * 15.0
                        elif dock_count <= 5:
                            base_score += profile.goal_priority * 10.0
                        else:
                            base_score += profile.goal_priority * 5.0

                    # Prioritize stack tiles (they have multiple layers)
                    elif tile_state.is_stack_tile:
                        if dock_count <= 4:
                            base_score += profile.goal_priority * 12.0
                        elif dock_count <= 5:
                            base_score += profile.goal_priority * 8.0
                        else:
                            base_score += profile.goal_priority * 4.0

                # OPTIMAL BOT: Perfect information - analyze contents (pattern_recognition >= 1.0)
                else:
                    # CRAFT TILES: Analyze craft box contents
                    if tile_state.is_craft_tile:
                        craft_box_key = f"{tile_state.layer_idx}_{tile_state.position_key}"
                        craft_tile_keys = state.craft_boxes.get(craft_box_key, [])

                        # Count matching types in craft box
                        matching_in_craft = 0
                        goal_tiles_in_craft = 0
                        for tile_key in craft_tile_keys:
                            craft_tile = state.stacked_tiles.get(tile_key)
                            if craft_tile:
                                # Count tiles matching current dock tiles
                                if any(d.tile_type == craft_tile.tile_type for d in state.dock_tiles):
                                    matching_in_craft += 1
                                # Count goal tiles in craft box
                                if craft_tile.tile_type in state.goals_remaining:
                                    goal_tiles_in_craft += 1

                        # Strategic priority based on contents
                        base_priority = 10.0
                        if matching_in_craft >= 2:
                            # Contains tiles that match dock - HIGH PRIORITY (can complete matches)
                            base_priority += 10.0
                        if goal_tiles_in_craft >= 2:
                            # Contains many goal tiles - HIGH PRIORITY
                            base_priority += 8.0

                        # Adjust by dock state
                        if dock_count <= 4:
                            base_score += base_priority * 1.5
                        elif dock_count <= 5:
                            base_score += base_priority
                        else:
                            base_score += base_priority * 0.5

                    # STACK TILES: Analyze stack contents
                    elif tile_state.is_stack_tile:
                        # Count stack depth and analyze contents
                        current_tile = tile_state
                        stack_depth = 0
                        matching_in_stack = 0
                        goal_tiles_in_stack = 0

                        # Traverse down the stack
                        while current_tile:
                            stack_depth += 1
                            # Check if this tile matches dock tiles
                            if any(d.tile_type == current_tile.tile_type for d in state.dock_tiles):
                                matching_in_stack += 1
                            # Check if this is a goal tile
                            if current_tile.tile_type in state.goals_remaining:
                                goal_tiles_in_stack += 1

                            # Move to next tile in stack
                            if current_tile.under_stacked_tile_key:
                                current_tile = state.stacked_tiles.get(current_tile.under_stacked_tile_key)
                            else:
                                break

                        # Strategic priority based on stack contents
                        base_priority = 8.0
                        if matching_in_stack >= 2:
                            # Contains tiles that match dock - HIGH PRIORITY
                            base_priority += 8.0
                        if goal_tiles_in_stack >= 2:
                            # Contains many goal tiles - HIGH PRIORITY
                            base_priority += 6.0
                        if stack_depth >= 3:
                            # Deep stack - extra priority to clear early
                            base_priority += 4.0

                        # Adjust by dock state
                        if dock_count <= 4:
                            base_score += base_priority * 1.5
                        elif dock_count <= 5:
                            base_score += base_priority
                        else:
                            base_score += base_priority * 0.5

        # SPECIAL GAME OVER PREVENTION (for Average+ bots)
        # Learn to avoid moves that lead to effect-based game over scenarios
        if profile.blocking_awareness >= 0.7:  # Average, Expert, Optimal bots
            tile_state = move.tile_state

            # 1. ICE tiles: Penalty if dock is filling and ice tiles are blocking critical tiles
            if tile_state and tile_state.effect_type == TileEffectType.ICE:
                remaining_ice = tile_state.effect_data.get("remaining", 0)
                if remaining_ice > 0 and dock_count >= 4:
                    # Can't pick ice tiles directly - this shouldn't happen, but safety check
                    base_score -= profile.blocking_awareness * 10.0

            # 2. CHAIN tiles: Penalize if many chain tiles remain locked with high dock count
            locked_chains = 0
            for layer in state.tiles.values():
                for tile in layer.values():
                    if not tile.picked and tile.effect_type == TileEffectType.CHAIN:
                        if not tile.effect_data.get("unlocked", False):
                            locked_chains += 1
            if locked_chains >= 3 and dock_count >= 5 and not move.will_match:
                # High risk: many locked chains + filling dock = potential deadlock
                base_score -= profile.blocking_awareness * 8.0

            # 3. GRASS tiles: Penalty if grass tiles are blocking and dock is filling
            blocking_grass = 0
            for layer in state.tiles.values():
                for tile in layer.values():
                    if not tile.picked and tile.effect_type == TileEffectType.GRASS:
                        remaining_grass = tile.effect_data.get("remaining", 0)
                        if remaining_grass > 0:
                            blocking_grass += 1
            if blocking_grass >= 3 and dock_count >= 5 and not move.will_match:
                # High risk: many grass tiles blocking + filling dock
                base_score -= profile.blocking_awareness * 8.0

            # 4. LINK tiles: Bonus for completing link pairs (clears 2 tiles at once)
            if tile_state and tile_state.effect_type in (
                TileEffectType.LINK_EAST, TileEffectType.LINK_WEST,
                TileEffectType.LINK_SOUTH, TileEffectType.LINK_NORTH
            ):
                # Link tiles are valuable - they clear 2 tiles in one move
                if dock_count >= 4:
                    # Extra bonus when dock is filling - link moves are efficient
                    base_score += profile.blocking_awareness * 5.0
                else:
                    base_score += profile.blocking_awareness * 2.0

            # 5. General effect tile deadlock detection
            # If many effect tiles remain and accessible tiles are limited
            accessible = self._get_accessible_tiles(state)
            effect_tiles = sum(
                1 for t in accessible
                if t.effect_type in (TileEffectType.ICE, TileEffectType.CHAIN,
                                     TileEffectType.GRASS, TileEffectType.LINK_EAST,
                                     TileEffectType.LINK_WEST, TileEffectType.LINK_SOUTH,
                                     TileEffectType.LINK_NORTH)
                and not self._can_pick_tile(state, t)
            )
            total_accessible = len(accessible)
            if total_accessible > 0:
                effect_ratio = effect_tiles / total_accessible
                if effect_ratio > 0.5 and dock_count >= 5 and not move.will_match:
                    # More than 50% of accessible tiles are blocked by effects
                    # and dock is filling without a match - HIGH RISK
                    base_score -= profile.blocking_awareness * 15.0

        # Add randomness based on profile (NONE for optimal bot)
        if profile.pattern_recognition < 1.0:
            randomness = (1 - profile.pattern_recognition) * self._rng.random() * 2
            base_score += randomness
        # Optimal bot (pattern_recognition=1.0) is perfectly deterministic

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

        # CRITICAL: Always prefer moves that complete a match (3-in-dock)
        matching_moves = [m for m in moves if m.will_match]
        if matching_moves:
            # Among matching moves, prefer by score
            return max(matching_moves, key=lambda m: m.score)

        # Sort by score
        sorted_moves = sorted(moves, key=lambda m: m.score, reverse=True)

        # Apply patience factor
        if profile.patience < 0.5 and len(sorted_moves) > 1:
            cutoff = max(1, int(len(sorted_moves) * profile.patience))
            return self._rng.choice(sorted_moves[:cutoff])

        # OPTIMAL BOT: Use perfect information to avoid unsafe moves
        if profile.pattern_recognition >= 1.0:
            return self._optimal_perfect_information_strategy(sorted_moves, state, profile)

        # For high-skill bots, use enhanced lookahead
        if profile.lookahead_depth > 0 and len(sorted_moves) > 1:
            candidates_count = min(5, len(sorted_moves))
            best_move = sorted_moves[0]
            best_future_score = self._estimate_future_score(state, best_move, profile.lookahead_depth)

            for move in sorted_moves[1:candidates_count]:
                future_score = self._estimate_future_score(state, move, profile.lookahead_depth)
                if future_score > best_future_score:
                    best_move = move
                    best_future_score = future_score

            return best_move

        return sorted_moves[0]

    def _optimal_perfect_information_strategy(
        self,
        sorted_moves: List[Move],
        state: GameState,
        profile: BotProfile,
    ) -> Move:
        """Optimal bot strategy - perfect information with maximum lookahead.

        Uses full lookahead depth and explores ALL possible moves,
        not just top 5. This ensures optimal bot always finds the best path
        if one exists.
        """
        if len(sorted_moves) <= 1:
            return sorted_moves[0]

        # OPTIMAL BOT: Explore ALL moves with MAXIMUM lookahead depth
        # No shortcuts - exhaustive search for guaranteed optimal play
        best_move = sorted_moves[0]
        best_future_score = self._estimate_future_score_with_deadlock_detection(
            state, best_move, 10
        )

        # Check ALL moves, not just top 5
        for move in sorted_moves[1:]:
            future_score = self._estimate_future_score_with_deadlock_detection(
                state, move, 10
            )
            if future_score > best_future_score:
                best_move = move
                best_future_score = future_score

        return best_move

    def _evaluate_move_sequence(
        self,
        state: GameState,
        first_move: Move,
        profile: BotProfile,
        depth: int,
        max_width: int,
    ) -> float:
        """Recursively evaluate a move sequence to find best continuation.

        Args:
            state: Current game state
            first_move: The first move to evaluate
            profile: Bot profile for scoring
            depth: How many moves ahead to look
            max_width: Maximum number of moves to consider at each level

        Returns:
            Score representing the best achievable outcome from this move
        """
        # Base case: no more depth
        if depth <= 0:
            return self._score_move_with_profile(
                first_move, state, profile
            )

        # Check if this move leads to immediate problems
        sim_info = self._simulate_move(state, first_move)
        if not sim_info:
            return float('-inf')

        # Immediate game over from dock overflow
        if sim_info.get("dock_full", False):
            return -10000.0

        # Deadlock detection
        if self._is_deadlock_likely_from_sim(state, sim_info):
            return -5000.0

        # Simulate this move to get new state
        # We need to create a copy of the state and apply the move
        try:
            next_state = self._copy_state_and_apply_move(state, first_move)
            if not next_state:
                return float('-inf')

            # Check if game is over after this move
            if self._is_game_over(next_state):
                if next_state.cleared:
                    return 10000.0  # Victory!
                else:
                    return -10000.0  # Defeat

            # Get available moves in the new state
            next_moves = self._get_available_moves(next_state)
            if not next_moves:
                # No moves available = game over
                return -10000.0

            # Score all next moves
            for m in next_moves:
                m.score = self._score_move_with_profile(m, next_state, profile)

            # Sort and take top candidates
            next_moves.sort(key=lambda m: m.score, reverse=True)
            candidates = next_moves[:max_width]

            # Recursively evaluate the BEST continuation
            best_continuation_score = float('-inf')
            for next_move in candidates:
                continuation_score = self._evaluate_move_sequence(
                    next_state, next_move, profile, depth - 1, max_width
                )
                best_continuation_score = max(best_continuation_score, continuation_score)

            # Score = immediate move score + discounted future score
            immediate_score = self._score_move_with_profile(
                first_move, state, profile
            )
            discount = 0.95  # Slightly prefer immediate rewards
            return immediate_score + (discount * best_continuation_score)

        except Exception:
            # If simulation fails, return very negative score
            return float('-inf')

    def _copy_state_and_apply_move(
        self,
        state: GameState,
        move: Move
    ) -> Optional[GameState]:
        """Create a deep copy of state and apply the move.

        Returns the new state after the move is applied.
        """
        try:
            # Deep copy the state
            import copy
            new_state = copy.deepcopy(state)

            # Apply the move
            self._apply_move(new_state, move)

            # Update link tile statuses
            self._update_link_tiles_status(new_state)

            return new_state

        except Exception:
            return None

    def _estimate_future_score_with_deadlock_detection(
        self,
        state: GameState,
        move: Move,
        depth: int,
    ) -> float:
        """Enhanced future score estimation with deadlock detection.

        Returns very negative score if this move leads to game over.
        """
        # Get simulated state info (Dict, not GameState)
        sim_info = self._simulate_move(state, move)
        if sim_info:
            # Check for immediate game over (dock full)
            if sim_info.get("dock_full", False):
                return -10000.0  # Catastrophic - leads to dock overflow

            # Check for deadlock patterns using the simulation info
            if self._is_deadlock_likely_from_sim(state, sim_info):
                return -5000.0  # High risk of deadlock

        # Use standard future score estimation
        return self._estimate_future_score(state, move, depth)

    def _is_deadlock_likely_from_sim(
        self,
        state: GameState,
        sim_info: Dict,
    ) -> bool:
        """Detect deadlock using simulation info.

        Args:
            state: Current game state
            sim_info: Simulated move result from _simulate_move
        """
        dock_size = sim_info.get("dock_size", 0)
        dock_types = sim_info.get("dock_types", {})

        # Check 1: Dock nearly full with no matches possible
        if dock_size >= 6:
            # If no type has 2+ tiles in dock, very risky
            has_pair = any(count >= 2 for count in dock_types.values())
            if not has_pair:
                # Check if any accessible tiles match dock
                pickable = sim_info.get("pickable_tiles", {})
                dock_type_set = set(dock_types.keys())
                matching_pickable = sum(
                    count for tile_type, count in pickable.items()
                    if tile_type in dock_type_set
                )

                if matching_pickable == 0:
                    return True  # No way to form pairs

        # Check 2: Too few pickable tiles with filling dock
        total_pickable = sum(sim_info.get("pickable_tiles", {}).values())
        if total_pickable <= 2 and dock_size >= 5:
            return True

        return False

    def _get_craft_spawn_positions(self, state: GameState) -> Set[str]:
        """Get all craft spawn positions that need to be cleared.

        Returns a set of "layer_idx_position" keys for all spawn positions
        where craft boxes need to emit tiles.
        """
        spawn_positions = set()

        for craft_box_key, tile_keys in state.craft_boxes.items():
            # Parse craft box position
            parts = craft_box_key.split("_")
            if len(parts) < 3:
                continue
            layer_idx = int(parts[0])
            box_x = int(parts[1])
            box_y = int(parts[2])

            # Find topmost unpicked tile
            topmost_unpicked = None
            for key in reversed(tile_keys):
                tile = state.stacked_tiles.get(key)
                if tile and not tile.picked:
                    topmost_unpicked = tile
                    break

            if not topmost_unpicked:
                continue

            # Skip if already crafted (already at spawn position)
            if topmost_unpicked.is_crafted:
                continue

            # Calculate spawn position
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

            # Check if spawn position is occupied
            layer_tiles = state.tiles.get(layer_idx, {})
            if spawn_pos in layer_tiles and not layer_tiles[spawn_pos].picked:
                # This spawn position needs to be cleared
                spawn_positions.add(f"{layer_idx}_{spawn_pos}")

        return spawn_positions

    def _find_craft_spawn_blocking_tile(
        self,
        state: GameState,
        sorted_moves: List[Move],
    ) -> Optional[Move]:
        """Find tiles at craft/stack spawn positions that should be prioritized.

        When craft_s/stack_s goal exists, we need to prioritize:
        1. Already emitted craft tiles (is_crafted=True) + Tiles at spawn positions (SAME PRIORITY)
        2. Stack tiles (is_stack_tile=True) - pick these for stack_s goals

        CRITICAL: Only return these tiles if they are SAFE to pick (can complete match).

        Returns the move to pick the prioritized tile.
        """
        # Count dock types
        dock_counts: Dict[str, int] = {}
        for t in state.dock_tiles:
            dock_counts[t.tile_type] = dock_counts.get(t.tile_type, 0) + 1

        # Helper function to check if move is safe
        def is_safe_move(move: Move) -> bool:
            tile_type = move.tile_type
            dock_has = dock_counts.get(tile_type, 0)
            total_remaining = state.all_tile_type_counts.get(tile_type, 0)
            after_pick = dock_has + 1
            needed_for_match = 3 - after_pick
            return total_remaining - 1 >= needed_for_match

        emitted_craft_moves = []
        spawn_blocking_moves = []
        stack_moves = []

        # Collect already emitted craft tiles (ONLY if safe)
        for move in sorted_moves:
            if move.tile_state and move.tile_state.is_craft_tile and move.tile_state.is_crafted:
                if is_safe_move(move):
                    emitted_craft_moves.append(move)

        # Collect tiles at craft spawn positions (ONLY if safe)
        craft_spawn_positions = self._get_craft_spawn_positions(state)
        for move in sorted_moves:
            spawn_key = f"{move.layer_idx}_{move.position}"
            if spawn_key in craft_spawn_positions:
                if is_safe_move(move):
                    spawn_blocking_moves.append(move)

        # Collect stack tiles (ONLY if safe)
        if "stack_s" in state.goals_remaining and state.goals_remaining["stack_s"] > 0:
            for move in sorted_moves:
                if move.tile_state and move.tile_state.is_stack_tile:
                    if is_safe_move(move):
                        stack_moves.append(move)

        # Return in priority order
        # PRIORITY 1: Emitted craft tiles and spawn blocking tiles (SAME PRIORITY)
        high_priority_moves = emitted_craft_moves + spawn_blocking_moves
        if high_priority_moves:
            return high_priority_moves[0]

        # PRIORITY 2: Stack tiles
        if stack_moves:
            return stack_moves[0]

        # No priority moves found
        return None

    def _find_triple_pickable_type(
        self,
        state: GameState,
        available_moves: List[Move],
    ) -> Optional[str]:
        """Find a tile type that has 3+ pickable tiles available right now.

        This is the BEST scenario - we can pick 3 tiles consecutively and
        immediately complete a match without filling the dock.
        """
        # Count pickable tiles by type
        pickable_counts: Dict[str, int] = {}
        for move in available_moves:
            tile_type = move.tile_type
            pickable_counts[tile_type] = pickable_counts.get(tile_type, 0) + 1

        # Find types with 3+ pickable tiles
        for tile_type, count in pickable_counts.items():
            if count >= 3:
                # Perfect! We can pick 3 of this type right now
                return tile_type

        return None

    def _evaluate_sacrifice_strategy(
        self,
        state: GameState,
        sorted_moves: List[Move],
        dock_counts: Dict[str, int],
    ) -> Optional[Move]:
        """Evaluate if we should sacrifice dock space to pick blocking tiles.

        When dock has room (0-2 tiles), we can afford to pick a "blocking" tile
        (one that doesn't immediately help with goals) if it unlocks access to valuable
        hidden tiles in stack/craft containers.

        Strategy:
        1. Identify stack/craft containers with goal tiles (craft_s/stack_s) hidden inside
        2. Check if the topmost tile is blocking access to goal tiles underneath
        3. Verify the blocking tile can eventually be matched (exists in all_tile_type_counts)
        4. Return the blocking tile move if the sacrifice is beneficial

        Returns the blocking tile move if sacrifice is beneficial, None otherwise.
        """
        dock_size = len(state.dock_tiles)

        # Only consider sacrifice when dock has plenty of room
        if dock_size > 2:
            return None

        # Check craft boxes for valuable hidden tiles
        for craft_pos, craft_tile_keys in state.craft_boxes.items():
            if not craft_tile_keys:
                continue

            # Check if this craft box has goal tiles (craft_s)
            has_goal_tiles = False
            topmost_tile = None

            for tile_key in craft_tile_keys:
                tile = state.stacked_tiles.get(tile_key)
                if not tile:
                    continue

                # Check if this is a goal tile
                if tile.tile_type == "craft_s" and not tile.picked:
                    has_goal_tiles = True

                # Find the topmost unpicked tile (highest stack_index)
                if not tile.picked:
                    if topmost_tile is None or tile.stack_index > topmost_tile.stack_index:
                        topmost_tile = tile

            # If we have goal tiles underneath and a blocking tile on top
            if has_goal_tiles and topmost_tile and topmost_tile.tile_type != "craft_s":
                # Check if the blocking tile can eventually be matched
                blocking_type = topmost_tile.tile_type
                total_count = state.all_tile_type_counts.get(blocking_type, 0)
                in_dock = dock_counts.get(blocking_type, 0)

                # Need at least 3 total to make a match eventually
                if total_count >= 3:
                    # Check if topmost tile is currently pickable from sorted_moves
                    for move in sorted_moves:
                        if (move.tile_state and
                            move.tile_state.full_key == topmost_tile.full_key):
                            # Found the blocking tile - sacrifice dock space to pick it!
                            return move

        # Check stacked tiles for valuable hidden tiles
        # Group stacked tiles by root position
        stack_groups: Dict[str, List[TileState]] = {}
        for tile_key, tile in state.stacked_tiles.items():
            if tile.picked or not tile.is_stack_tile:
                continue

            root_key = tile.root_stacked_tile_key or tile_key
            if root_key not in stack_groups:
                stack_groups[root_key] = []
            stack_groups[root_key].append(tile)

        # Check each stack group for goal tiles
        for root_key, stack_tiles in stack_groups.items():
            if not stack_tiles:
                continue

            # Sort by stack_index to find topmost and check for goals underneath
            stack_tiles_sorted = sorted(stack_tiles, key=lambda t: t.stack_index)

            has_goal_tiles = False
            topmost_tile = stack_tiles_sorted[-1]  # Highest stack_index

            # Check if any tiles underneath are goal tiles (stack_s)
            for tile in stack_tiles_sorted[:-1]:  # All except topmost
                if tile.tile_type == "stack_s":
                    has_goal_tiles = True
                    break

            # If we have goal tiles underneath and topmost is blocking
            if has_goal_tiles and topmost_tile.tile_type != "stack_s":
                # Check if the blocking tile can eventually be matched
                blocking_type = topmost_tile.tile_type
                total_count = state.all_tile_type_counts.get(blocking_type, 0)

                # Need at least 3 total to make a match eventually
                if total_count >= 3:
                    # Check if topmost tile is currently pickable from sorted_moves
                    for move in sorted_moves:
                        if (move.tile_state and
                            move.tile_state.full_key == topmost_tile.full_key):
                            # Found the blocking tile - sacrifice dock space to pick it!
                            return move

        return None

    def _estimate_future_score(
        self,
        state: GameState,
        move: Move,
        depth: int = 3,
    ) -> float:
        """Calculate deep search score for a move by simulating future states.

        Returns a score based on:
        - Whether the move leads to dead-end (very negative)
        - Number of matches that can be completed in the next few moves
        - Dock fill level after the sequence
        - Accessibility of matching tiles
        """
        # Simulate the move
        sim_state = self._simulate_move(state, move)

        if sim_state is None:
            return float('-inf')  # Invalid move

        # Check for immediate game over (dock full)
        if sim_state['dock_full']:
            return -10000.0

        # Base score from matches made
        score = sim_state['matches'] * 100.0

        # CRITICAL: Strong penalty for dock fill level
        dock_level = sim_state['dock_size']
        if dock_level >= 6:
            score -= 2000.0  # Critical danger - almost game over
        elif dock_level >= 5:
            score -= 800.0   # Very high danger
        elif dock_level >= 4:
            score -= 300.0   # High danger
        elif dock_level >= 3:
            score -= 50.0    # Moderate danger

        # Bonus for reducing dock size (making matches)
        current_dock = len(state.dock_tiles)
        if sim_state['matches'] > 0:
            dock_reduction = current_dock - dock_level
            score += dock_reduction * 50.0  # Reward clearing dock

        # Check if we're setting up for future matches
        score += self._evaluate_matching_potential(sim_state) * 10.0

        # Recurse for deeper analysis if depth > 1
        if depth > 1 and not sim_state['dock_full']:
            # Find the best next move from simulated state
            next_moves = self._get_simulated_moves(sim_state)
            if next_moves:
                # Check if any next move leads to a match
                matching_next = [m for m in next_moves if m['will_match']]
                if matching_next:
                    # Great - we can match next turn
                    score += 50.0
                    # Recursively evaluate the best matching move
                    best_next_score = float('-inf')
                    for nm in matching_next[:3]:  # Limit to top 3 for performance
                        next_score = self._deep_search_score_simulated(
                            sim_state, nm, depth - 1
                        )
                        best_next_score = max(best_next_score, next_score)
                    score += best_next_score * 0.5  # Discount future scores
                else:
                    # No immediate match - check for dead-end
                    if self._is_simulated_dead_end(sim_state, next_moves):
                        score -= 1000.0  # Avoid dead-end paths
                    else:
                        # Evaluate best non-matching move
                        best_next_score = float('-inf')
                        for nm in next_moves[:5]:  # Limit for performance
                            next_score = self._deep_search_score_simulated(
                                sim_state, nm, depth - 1
                            )
                            best_next_score = max(best_next_score, next_score)
                        score += best_next_score * 0.3
            else:
                # No moves available - this is bad (but might mean game cleared)
                if sim_state['remaining_tiles'] == 0:
                    score += 5000.0  # Game cleared!
                else:
                    score -= 2000.0  # Stuck

        return score

    def _simulate_move(self, state: GameState, move: Move) -> Optional[Dict]:
        """Simulate a move and return the resulting state information.

        Returns a dictionary with:
        - dock_types: Dict of tile_type -> count in dock after move
        - dock_size: Number of tiles in dock after matches
        - matches: Number of 3-matches that occurred
        - dock_full: Whether dock is full (game over)
        - remaining_tiles: Tiles remaining on board
        - pickable_tiles: Dict of tile_type -> count of pickable tiles after move
        - all_tile_counts: Dict of tile_type -> total count (including hidden)
        """
        if move.tile_state is None:
            return None

        # Copy dock state
        dock_types: Dict[str, int] = {}
        for tile in state.dock_tiles:
            dock_types[tile.tile_type] = dock_types.get(tile.tile_type, 0) + 1

        # Add the moved tile to dock
        move_type = move.tile_type
        dock_types[move_type] = dock_types.get(move_type, 0) + 1

        # Calculate matches
        matches = 0
        for tile_type, count in list(dock_types.items()):
            while count >= 3:
                matches += 1
                count -= 3
            dock_types[tile_type] = count

        # Calculate dock size after matches
        dock_size = sum(dock_types.values())
        dock_full = dock_size >= 7

        # Count remaining tiles (excluding the one we're picking)
        remaining_tiles = 0
        pickable_tiles: Dict[str, int] = {}

        for layer_tiles in state.tiles.values():
            for pos, tile in layer_tiles.items():
                if tile.picked:
                    continue
                if pos == move.position and tile.layer_idx == move.layer_idx:
                    continue  # Skip the tile we're picking
                remaining_tiles += 1

                # Check if this tile would be pickable after the move
                # Simplified check - we'll count all unpicked tiles
                tile_type = tile.tile_type
                if tile_type in self.MATCHABLE_TYPES:
                    pickable_tiles[tile_type] = pickable_tiles.get(tile_type, 0) + 1

        # Copy all_tile_type_counts and decrement the picked tile
        all_tile_counts = dict(state.all_tile_type_counts)
        if move_type in all_tile_counts:
            all_tile_counts[move_type] = max(0, all_tile_counts[move_type] - 1)
        # Also decrement for matched tiles
        if matches > 0 and move_type in all_tile_counts:
            all_tile_counts[move_type] = max(0, all_tile_counts[move_type] - (matches * 3 - 1))

        return {
            'dock_types': dock_types,
            'dock_size': dock_size,
            'matches': matches,
            'dock_full': dock_full,
            'remaining_tiles': remaining_tiles,
            'pickable_tiles': pickable_tiles,
            'all_tile_counts': all_tile_counts,
            'picked_type': move_type,
        }

    def _get_simulated_moves(self, sim_state: Dict) -> List[Dict]:
        """Get available moves from a simulated state."""
        moves = []
        for tile_type, count in sim_state['pickable_tiles'].items():
            if count <= 0:
                continue

            # Check if picking this tile would create a match
            dock_count = sim_state['dock_types'].get(tile_type, 0)
            will_match = dock_count >= 2

            moves.append({
                'tile_type': tile_type,
                'count': count,
                'will_match': will_match,
                'dock_count': dock_count,
            })

        # Sort by: matches first, then by dock count (setup for match)
        moves.sort(key=lambda m: (m['will_match'], m['dock_count']), reverse=True)
        return moves

    def _deep_search_score_simulated(
        self,
        sim_state: Dict,
        move: Dict,
        depth: int,
    ) -> float:
        """Calculate score for a simulated move."""
        # Simulate this move
        dock_types = dict(sim_state['dock_types'])
        move_type = move['tile_type']
        dock_types[move_type] = dock_types.get(move_type, 0) + 1

        # Calculate matches
        matches = 0
        for tile_type, count in list(dock_types.items()):
            while count >= 3:
                matches += 1
                count -= 3
            dock_types[tile_type] = count

        dock_size = sum(dock_types.values())

        # Base score
        score = matches * 100.0

        # Dock danger
        if dock_size >= 7:
            return -10000.0
        elif dock_size >= 6:
            score -= 500.0
        elif dock_size >= 5:
            score -= 200.0
        elif dock_size >= 4:
            score -= 50.0

        # Recursion
        if depth > 1:
            # Create next simulated state
            pickable_tiles = dict(sim_state['pickable_tiles'])
            if move_type in pickable_tiles:
                pickable_tiles[move_type] = max(0, pickable_tiles[move_type] - 1)

            next_sim_state = {
                'dock_types': dock_types,
                'dock_size': dock_size,
                'pickable_tiles': pickable_tiles,
                'all_tile_counts': sim_state['all_tile_counts'],
            }

            next_moves = self._get_simulated_moves(next_sim_state)
            if next_moves:
                matching_next = [m for m in next_moves if m['will_match']]
                if matching_next:
                    score += 50.0
                    for nm in matching_next[:2]:
                        next_score = self._deep_search_score_simulated(
                            next_sim_state, nm, depth - 1
                        )
                        score = max(score, score + next_score * 0.3)

        return score

    def _evaluate_matching_potential(self, sim_state: Dict) -> float:
        """Evaluate the matching potential of a simulated state."""
        score = 0.0

        dock_types = sim_state['dock_types']
        pickable_tiles = sim_state['pickable_tiles']
        all_tile_counts = sim_state['all_tile_counts']

        for tile_type, dock_count in dock_types.items():
            if dock_count == 0:
                continue

            pickable_count = pickable_tiles.get(tile_type, 0)
            total_remaining = all_tile_counts.get(tile_type, 0)
            hidden_count = total_remaining - pickable_count

            if dock_count == 2:
                # We need 1 more to match
                if pickable_count >= 1:
                    score += 20.0  # Can match immediately
                elif hidden_count >= 1:
                    score += 5.0   # Can match later
                else:
                    score -= 30.0  # Dead tiles in dock!
            elif dock_count == 1:
                # We need 2 more to match
                if pickable_count >= 2:
                    score += 10.0  # Can match soon
                elif pickable_count >= 1 and hidden_count >= 1:
                    score += 3.0   # Can match eventually
                elif hidden_count >= 2:
                    score += 1.0   # Can match much later
                else:
                    score -= 15.0  # Risky

        return score

    def _is_simulated_dead_end(self, sim_state: Dict, next_moves: List[Dict]) -> bool:
        """Check if a simulated state is a dead-end.

        A dead-end is when:
        1. Dock is nearly full (5+ tiles)
        2. No matching moves available
        3. Any move would fill the dock without matching
        """
        if sim_state['dock_size'] < 5:
            return False  # Not dangerous yet

        # Check if any move can lead to a match
        for move in next_moves:
            if move['will_match']:
                return False  # There's a way out

            # Check if this move would overfill dock
            dock_after = sim_state['dock_size'] + 1
            if dock_after >= 7:
                continue  # This move would lose

            # Check if next move after this could match
            tile_type = move['tile_type']
            new_dock_count = sim_state['dock_types'].get(tile_type, 0) + 1
            if new_dock_count == 2:
                # Would have 2 in dock - check if 3rd exists
                total = sim_state['all_tile_counts'].get(tile_type, 0)
                remaining = total - 1  # -1 for this tile
                if remaining >= 1:
                    return False  # Can complete this match

        # No safe path found
        return True

    def _estimate_future_score(self, state: GameState, move: Move, depth: int = 1) -> float:
        """Estimate future position quality after making a move.

        Uses a combination of immediate effects and future potential analysis.
        """
        score = move.score  # Start with the move's current score

        # Major bonus if move completes a match
        if move.will_match:
            score += 50.0

        # Analyze dock state after this move
        dock_type = move.tile_type
        current_dock_count = sum(1 for t in state.dock_tiles if t.tile_type == dock_type)
        new_dock_count = current_dock_count + 1

        # Get pickable tiles
        accessible = self._get_accessible_tiles(state)
        pickable = [t for t in accessible if self._can_pick_tile(state, t) and t.position_key != move.position]

        if new_dock_count == 2:
            # Will have 2 in dock - check if 3rd is available
            same_type_pickable = sum(1 for t in pickable if t.tile_type == dock_type)
            if same_type_pickable >= 1:
                score += 30.0  # Excellent - can complete match next turn
            else:
                # Check hidden tiles (perfect information for optimal bot)
                total_of_type = state.all_tile_type_counts.get(dock_type, 0)
                # Hidden = total - pickable - in_dock - this_tile
                hidden_of_type = total_of_type - same_type_pickable - new_dock_count
                if hidden_of_type >= 1:
                    # 3rd tile exists but is hidden - will appear later
                    score += 15.0  # Still good - can complete eventually
                else:
                    # 2 in dock but no 3rd anywhere - very dangerous!
                    score -= 25.0

        elif new_dock_count == 1 and not move.will_match:
            # Starting a new type in dock - check if we can complete it
            same_type_pickable = sum(1 for t in pickable if t.tile_type == dock_type)
            if same_type_pickable >= 2:
                score += 10.0  # Good - 2 more available
            elif same_type_pickable == 1:
                # Check for hidden tiles
                total_of_type = state.all_tile_type_counts.get(dock_type, 0)
                hidden_of_type = total_of_type - same_type_pickable - 1  # -1 for this tile
                if hidden_of_type >= 1:
                    score += 5.0  # One pickable + one hidden = can match
                else:
                    score += 2.0  # Only one more - risky
            else:
                # No more pickable - check hidden
                total_of_type = state.all_tile_type_counts.get(dock_type, 0)
                hidden_of_type = total_of_type - 1  # -1 for this tile
                if hidden_of_type >= 2:
                    score += 3.0  # 2 hidden tiles can complete match
                elif hidden_of_type >= 1:
                    score -= 5.0  # Only 1 hidden - partial match risk
                else:
                    # No more of this type anywhere - very risky
                    score -= 20.0

        # Dock fill danger assessment
        current_dock_size = len(state.dock_tiles)
        projected_dock_size = current_dock_size + 1 if not move.will_match else max(0, current_dock_size - 2)

        if projected_dock_size >= 6:
            score -= 40.0  # Critical danger
        elif projected_dock_size >= 5:
            score -= 20.0  # High danger
        elif projected_dock_size >= 4:
            score -= 5.0  # Caution

        # Analyze future matching potential using COMPLETE tile information
        # This gives optimal bot perfect knowledge of all tiles (including hidden)
        for tile_type, total_count in state.all_tile_type_counts.items():
            if tile_type not in self.MATCHABLE_TYPES:
                continue

            dock_has = sum(1 for t in state.dock_tiles if t.tile_type == tile_type)
            pickable_count = sum(1 for t in pickable if t.tile_type == tile_type)

            # Total available = on board (pickable) + in dock
            available_now = pickable_count + dock_has
            # Hidden = total - available_now
            hidden_count = total_count - available_now

            # Check if this type can form complete matches
            if total_count >= 3:
                if available_now >= 3:
                    score += 5.0  # Can match immediately
                elif available_now >= 2 and hidden_count >= 1:
                    score += 3.0  # Can match soon
                elif available_now >= 1 and hidden_count >= 2:
                    score += 1.0  # Can match eventually
            elif total_count == 2:
                # Only 2 of this type - potential problem
                score -= 2.0
            elif total_count == 1:
                # Only 1 of this type - will cause dock fill!
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
