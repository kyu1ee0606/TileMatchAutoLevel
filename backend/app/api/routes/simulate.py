"""Visual simulation API routes for level playback visualization."""
import random
import time
from copy import deepcopy
from typing import Dict, List, Any, Optional, Set, Tuple
from dataclasses import dataclass, field
from fastapi import APIRouter, HTTPException

from ...models.schemas import (
    VisualSimulationRequest,
    VisualSimulationResponse,
    VisualBotMove,
    VisualBotResult,
    VisualGameState,
    ErrorResponse,
)
from ...models.bot_profile import BotType, get_profile, PREDEFINED_PROFILES
from ...core.bot_simulator import (
    BotSimulator,
    GameState,
    TileState,
    TileEffectType,
    Move,
)


router = APIRouter(prefix="/api/simulate", tags=["Visual Simulation"])


# Bot display names (Korean)
BOT_DISPLAY_NAMES = {
    "novice": "초보자",
    "casual": "캐주얼",
    "average": "일반",
    "expert": "숙련자",
    "optimal": "최적",
}

# Decision reason templates
DECISION_REASONS = {
    "random": "무작위 선택",
    "greedy_goal": "목표 진행 우선",
    "greedy_blocking": "블로킹 해제 우선",
    "greedy_chain": "체인 타일 우선",
    "greedy_match": "3매칭 완성 우선",
    "mistake": "실수 (비최적 선택)",
    "lookahead": "선읽기 기반 선택",
    "dock_safety": "덱 안전 우선",
    "effect_clear": "기믹 해제 우선",
}

# Matchable tile types (same as bot_simulator)
# Note: t0 is a random tile placeholder that gets converted to t1-t15
MATCHABLE_TYPES = {f"t{i}" for i in range(1, 16)} | {"t16"}
# Random tile pool for t0 conversion
RANDOM_TILE_POOL = [f"t{i}" for i in range(1, 16)]
GOAL_TYPES = {"craft_s", "stack_s"}


@dataclass
class DockTileInfo:
    """Tracks a tile in dock with its original board position."""
    tile_type: str
    layer_idx: int
    position: str  # Original board position


class VisualSimulator:
    """Simulator for visual playback with move history.

    Uses the same game rules as BotSimulator:
    - 7-slot dock queue system
    - 3-tile consecutive matching
    - Layer blocking (upper tiles block lower tiles)
    - Obstacle mechanics (ice, chain, grass, link, frog, bomb, curtain, teleport)
    """

    # Default tile count for t0 distribution (matches bot_simulator)
    DEFAULT_USE_TILE_COUNT = 6

    def __init__(self):
        self._rng = random.Random()
        # Re-use core simulation logic from BotSimulator
        self._core = BotSimulator()

    def get_t0_assignments(
        self, level_json: Dict[str, Any], seed: Optional[int] = None
    ) -> Dict[Tuple[int, str], str]:
        """Get t0 tile assignments for visualization.

        Returns a mapping of (layer_idx, pos) -> converted tile type.
        """
        if seed is not None:
            self._rng.seed(seed)

        num_layers = level_json.get("layer", 8)
        rand_seed = level_json.get("randSeed", 0)
        use_tile_count = level_json.get("useTileCount", self.DEFAULT_USE_TILE_COUNT)
        if use_tile_count <= 0:
            use_tile_count = self.DEFAULT_USE_TILE_COUNT

        # Collect all t0 tiles
        t0_tiles: List[Tuple[int, str]] = []
        for layer_idx in range(num_layers):
            layer_key = f"layer_{layer_idx}"
            layer_data = level_json.get(layer_key, {})
            layer_tiles = layer_data.get("tiles", {})

            for pos, tile_data in layer_tiles.items():
                if isinstance(tile_data, list) and tile_data and tile_data[0] == "t0":
                    t0_tiles.append((layer_idx, pos))

        if not t0_tiles:
            return {}

        # Use core's distribution logic
        assignments = self._core._distribute_t0_tiles(
            len(t0_tiles), use_tile_count, rand_seed
        )

        # Build mapping
        result: Dict[Tuple[int, str], str] = {}
        for i, (layer_idx, pos) in enumerate(t0_tiles):
            if i < len(assignments):
                result[(layer_idx, pos)] = assignments[i]

        return result

    def simulate_bot(
        self,
        level_json: Dict[str, Any],
        bot_type: str,
        max_moves: int,
        seed: Optional[int] = None,
        initial_state_seed: Optional[int] = None,
    ) -> Tuple[VisualBotResult, Dict[str, List[str]]]:
        """Run a single simulation for a bot and record all moves.

        Args:
            level_json: Level data
            bot_type: Type of bot to simulate
            max_moves: Maximum moves allowed
            seed: Seed for bot behavior (different per bot for varied gameplay)
            initial_state_seed: Seed for initial state (same for all bots for consistent tiles)

        Returns:
            Tuple of (VisualBotResult, stack_craft_types_map)
            stack_craft_types_map: {layerIdx_pos: [tile_types]} for stack/craft tiles
        """
        # Use initial_state_seed for tile generation (consistent across all bots)
        # Use seed for bot behavior (varied gameplay)
        state_seed = initial_state_seed if initial_state_seed is not None else seed
        if state_seed is not None:
            self._core._rng.seed(state_seed)

        profile = get_profile(bot_type)
        if profile is None:
            raise ValueError(f"Unknown bot type: {bot_type}")

        # Initialize game state using core logic (uses _core._rng for tile types)
        state = self._core._create_initial_state(level_json, max_moves)

        # Now set bot behavior seed (for move selection randomness)
        # IMPORTANT: Only set self._rng for bot behavior, NOT _core._rng
        # _core._rng was used for tile type generation and should not be changed
        if seed is not None:
            self._rng.seed(seed)
        moves: List[VisualBotMove] = []
        move_number = 0
        total_score = 0.0

        # Extract stack/craft tile types from initialized state
        # This ensures frontend visualization uses the same types as simulation
        # Note: tile_types array is in bottom-to-top order (index 0 = bottom, index -1 = top)
        stack_craft_types_map: Dict[str, List[str]] = {}
        for craft_box_key, tile_keys in state.craft_boxes.items():
            # craft_box_key is "layer_idx_x_y", tile_keys are full keys with stack index
            tile_types = []
            for key in tile_keys:
                tile = state.stacked_tiles.get(key)
                if tile:
                    tile_types.append(tile.tile_type)
            if tile_types:
                stack_craft_types_map[craft_box_key] = tile_types


        # Store initial goals for calculating completed goals
        initial_goals = dict(state.goals_remaining)

        # Track dock tiles with their original board positions
        dock_tile_infos: List[DockTileInfo] = []

        # Play game
        while not self._is_game_over(state):
            available_moves = self._core._get_available_moves(state)
            if not available_moves:
                state.failed = True
                break

            # Score moves based on bot profile
            for move in available_moves:
                move.score = self._core._score_move_with_profile(move, state, profile)

            # Select move based on bot behavior
            selected_move = self._core._select_move_with_profile(available_moves, state, profile)
            if selected_move is None:
                state.failed = True
                break

            move_number += 1

            # Determine decision reason
            reason = self._determine_decision_reason(selected_move, available_moves, profile)

            # Store the current tile's board position before applying move
            current_tile_info = DockTileInfo(
                tile_type=selected_move.tile_type,
                layer_idx=selected_move.layer_idx,
                position=selected_move.position,
            )

            # Check dock state before move for match prediction
            dock_count_before = sum(
                1 for dt in dock_tile_infos if dt.tile_type == selected_move.tile_type
            )
            will_match = dock_count_before >= 2

            # Apply move (tile gets picked and added to dock)
            tiles_cleared = self._core._apply_move(state, selected_move)
            score_gained = tiles_cleared * 10.0
            total_score += score_gained

            # Track matched positions (original board positions of matched tiles)
            matched_positions: List[str] = []

            if tiles_cleared >= 3:
                # 3 tiles were matched and removed from dock
                # Find the other 2 tiles of same type that were in dock
                same_type_in_dock = [
                    dt for dt in dock_tile_infos if dt.tile_type == selected_move.tile_type
                ]
                # Take the first 2 (oldest) tiles of same type
                for dt in same_type_in_dock[:2]:
                    matched_positions.append(f"{dt.layer_idx}_{dt.position}")
                    dock_tile_infos.remove(dt)
                # The current tile is also matched (already removed from board by _apply_move)
            else:
                # No match - add current tile to dock tracking
                dock_tile_infos.append(current_tile_info)

            # Process move effects (bomb, frog, curtain, teleport)
            self._core._process_move_effects(state)
            state.moves_used += 1

            # Get current dock state (tile types only)
            dock_after = [dt.tile_type for dt in dock_tile_infos]

            # Get frog positions after move (layerIdx_x_y format)
            # Search all layers for tiles with on_frog=True
            frog_positions_after: List[str] = []
            for layer_idx, layer in state.tiles.items():
                for pos, tile in layer.items():
                    if tile.effect_data.get("on_frog", False):
                        frog_positions_after.append(f"{layer_idx}_{pos}")

            # Get bomb states after move (layerIdx_x_y -> remaining count)
            bomb_states_after: Dict[str, int] = {}
            for layer_idx, layer in state.tiles.items():
                for pos, tile in layer.items():
                    if tile.effect_type == TileEffectType.BOMB and not tile.picked:
                        remaining = tile.effect_data.get("remaining", 0)
                        bomb_states_after[f"{layer_idx}_{pos}"] = remaining

            # Get curtain states after move (layerIdx_x_y -> is_open)
            curtain_states_after: Dict[str, bool] = {}
            for layer_idx, layer in state.tiles.items():
                for pos, tile in layer.items():
                    if tile.effect_type == TileEffectType.CURTAIN and not tile.picked:
                        is_open = tile.effect_data.get("is_open", True)
                        curtain_states_after[f"{layer_idx}_{pos}"] = is_open

            # Get ice states after move (layerIdx_x_y -> remaining layers 1-3)
            # Note: bot_simulator uses "remaining" field for ice (initialized to 3)
            ice_states_after: Dict[str, int] = {}
            for layer_idx, layer in state.tiles.items():
                for pos, tile in layer.items():
                    if tile.effect_type == TileEffectType.ICE and not tile.picked:
                        ice_remaining = tile.effect_data.get("remaining", 3)
                        ice_states_after[f"{layer_idx}_{pos}"] = ice_remaining

            # Get chain states after move (layerIdx_x_y -> unlocked)
            chain_states_after: Dict[str, bool] = {}
            for layer_idx, layer in state.tiles.items():
                for pos, tile in layer.items():
                    if tile.effect_type == TileEffectType.CHAIN and not tile.picked:
                        unlocked = tile.effect_data.get("unlocked", False)
                        chain_states_after[f"{layer_idx}_{pos}"] = unlocked

            # Get grass states after move (layerIdx_x_y -> remaining layers 1-2)
            # Note: bot_simulator uses "remaining" field for grass (initialized to 2)
            grass_states_after: Dict[str, int] = {}
            for layer_idx, layer in state.tiles.items():
                for pos, tile in layer.items():
                    if tile.effect_type == TileEffectType.GRASS and not tile.picked:
                        grass_remaining = tile.effect_data.get("remaining", 2)
                        grass_states_after[f"{layer_idx}_{pos}"] = grass_remaining

            # Get link states after move (layerIdx_x_y -> list of connected position keys)
            link_states_after: Dict[str, List[str]] = {}
            for layer_idx, layer in state.tiles.items():
                for pos, tile in layer.items():
                    if tile.effect_type in (TileEffectType.LINK_EAST, TileEffectType.LINK_WEST,
                                            TileEffectType.LINK_SOUTH, TileEffectType.LINK_NORTH) and not tile.picked:
                        # Get linked positions from effect_data
                        linked_positions = tile.effect_data.get("linked_positions", [])
                        link_states_after[f"{layer_idx}_{pos}"] = linked_positions

            # Record move
            moves.append(VisualBotMove(
                move_number=move_number,
                layer_idx=selected_move.layer_idx,
                position=selected_move.position,
                tile_type=selected_move.tile_type,
                matched_positions=matched_positions,
                tiles_cleared=tiles_cleared,
                goals_after=dict(state.goals_remaining),
                score_gained=score_gained,
                decision_reason=reason,
                dock_after=dock_after,
                frog_positions_after=frog_positions_after,
                bomb_states_after=bomb_states_after,
                curtain_states_after=curtain_states_after,
                ice_states_after=ice_states_after,
                chain_states_after=chain_states_after,
                grass_states_after=grass_states_after,
                link_states_after=link_states_after,
            ))

        # Check clear status - must clear all goals AND all tiles
        goals_cleared = all(count <= 0 for count in state.goals_remaining.values())
        remaining_tiles = sum(
            1 for layer in state.tiles.values()
            for tile in layer.values()
            if not tile.picked
        )
        # Level is cleared only if:
        # 1. All goals are met (or no goals exist)
        # 2. All tiles are removed from the board
        # 3. Dock is empty (all matched)
        cleared = goals_cleared and remaining_tiles == 0 and len(state.dock_tiles) == 0

        return (
            VisualBotResult(
                profile=bot_type,
                profile_display=BOT_DISPLAY_NAMES.get(bot_type, bot_type),
                moves=moves,
                cleared=cleared,
                total_moves=state.moves_used,
                final_score=total_score,
                goals_completed={
                    k: initial_goals.get(k, 0) - v
                    for k, v in state.goals_remaining.items()
                },
            ),
            stack_craft_types_map,
        )

    def _is_game_over(self, state: GameState) -> bool:
        """Check if game is over (uses same logic as core)."""
        # Check goals cleared and all tiles cleared
        if all(count <= 0 for count in state.goals_remaining.values()):
            remaining_unpicked = sum(
                1 for layer in state.tiles.values()
                for tile in layer.values()
                if not tile.picked
            )
            if remaining_unpicked == 0 and len(state.dock_tiles) == 0:
                state.cleared = True
                return True

        # Check dock full (game fail condition)
        if self._core._is_dock_full(state):
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

    def _determine_decision_reason(
        self, selected: Move, all_moves: List[Move], profile: Any
    ) -> str:
        """Determine the reason for the bot's decision."""
        if not all_moves:
            return DECISION_REASONS["random"]

        # Check if this was a mistake (not the best move)
        sorted_moves = sorted(all_moves, key=lambda m: m.score, reverse=True)
        if selected != sorted_moves[0]:
            if self._rng.random() < profile.mistake_rate:
                return DECISION_REASONS["mistake"]

        # Check for specific strategic reasons
        if selected.will_match:
            return DECISION_REASONS["greedy_match"]

        if selected.attribute and selected.attribute != "none":
            effect_type = selected.attribute
            if effect_type in ("chain", "ice", "grass"):
                return DECISION_REASONS["effect_clear"]
            elif effect_type == "frog":
                return DECISION_REASONS["greedy_chain"]

        if selected.layer_idx >= 5:
            return DECISION_REASONS["greedy_blocking"]

        if selected.match_count == 2:
            return DECISION_REASONS["dock_safety"]

        return DECISION_REASONS["greedy_goal"]


def extract_initial_state(
    level_json: Dict[str, Any],
    t0_assignments: Optional[Dict[Tuple[int, str], str]] = None,
    stack_craft_types: Optional[Dict[str, List[str]]] = None,
) -> VisualGameState:
    """Extract initial state for frontend visualization.

    Args:
        level_json: The level JSON data
        t0_assignments: Optional mapping of (layer_idx, pos) -> converted tile type for t0 tiles
        stack_craft_types: Optional mapping of "layer_x_y" -> [tile_types] from simulation
    """
    num_layers = level_json.get("layer", 8)
    tiles: Dict[str, Any] = {}
    goals: Dict[str, int] = {}
    grid_info: Dict[str, Any] = {}
    initial_frog_positions: List[str] = []
    initial_ice_states: Dict[str, int] = {}
    initial_chain_states: Dict[str, bool] = {}
    initial_grass_states: Dict[str, int] = {}
    initial_bomb_states: Dict[str, int] = {}
    initial_curtain_states: Dict[str, bool] = {}
    initial_link_states: Dict[str, List[str]] = {}

    # Use simulator to get proper t0 assignments for stacked tiles too (fallback only)
    simulator = VisualSimulator()

    for i in range(num_layers):
        layer_key = f"layer_{i}"
        layer_data = level_json.get(layer_key, {})

        if layer_data.get("tiles"):
            # Deep copy and convert t0 tiles if assignments provided
            layer_tiles = deepcopy(layer_data.get("tiles", {}))

            if t0_assignments:
                for pos, tile_data in layer_tiles.items():
                    if isinstance(tile_data, list) and tile_data[0] == "t0":
                        converted_type = t0_assignments.get((i, pos))
                        if converted_type:
                            tile_data[0] = converted_type

            # Process stack/craft tiles - convert stacked tile types
            for pos, tile_data in list(layer_tiles.items()):
                if isinstance(tile_data, list) and len(tile_data) > 0:
                    tile_type = tile_data[0]
                    # Handle stack/craft tiles
                    if isinstance(tile_type, str) and (tile_type.startswith("stack_") or tile_type.startswith("craft_")):
                        # Get stack info - format from LevelEditor: [count] only
                        # Handle case where tile_data may not have index 2
                        stack_info = tile_data[2] if len(tile_data) > 2 else None

                        # Default to count of 1 if no stack info
                        total_count = 1
                        if stack_info and isinstance(stack_info, list) and len(stack_info) >= 1:
                            total_count = int(stack_info[0]) if stack_info[0] else 1

                        # Use pre-computed types from simulation if available
                        stack_key = f"{i}_{pos}"
                        if stack_craft_types and stack_key in stack_craft_types:
                            converted_types = stack_craft_types[stack_key]
                            # Update total_count based on actual types from simulation
                            total_count = len(converted_types)
                        else:
                            # Fallback: Generate random types (should not happen with proper flow)
                            converted_types = []
                            for _ in range(total_count):
                                converted_type = simulator._rng.choice(RANDOM_TILE_POOL[:simulator.DEFAULT_USE_TILE_COUNT])
                                converted_types.append(converted_type)

                        # Ensure tile_data has at least 3 elements
                        while len(tile_data) < 3:
                            tile_data.append(None)

                        # Update tile_data with converted types in format [count, "types"]
                        # This format is used by frontend for visualization
                        tile_data[2] = [total_count, "_".join(converted_types)]

            tiles[str(i)] = layer_tiles
            grid_info[str(i)] = {
                "col": int(layer_data.get("col", 7)),
                "row": int(layer_data.get("row", 7)),
            }

            # Extract goals, frog positions, and gimmick states
            for pos, tile_data in layer_data.get("tiles", {}).items():
                if isinstance(tile_data, list):
                    tile_type = tile_data[0]
                    attribute = tile_data[1] if len(tile_data) > 1 else None
                    extra_data = tile_data[2] if len(tile_data) > 2 else None

                    # Goals (includes stack_s and craft_s)
                    if tile_type in GOAL_TYPES:
                        goal_count = extra_data[0] if extra_data else 1
                        goals[tile_type] = goals.get(tile_type, 0) + goal_count
                    # Stack/Craft goals
                    if isinstance(tile_type, str) and (tile_type.startswith("stack_") or tile_type.startswith("craft_")):
                        if extra_data and isinstance(extra_data, list):
                            total_count = int(extra_data[0]) if extra_data[0] else 1
                            goal_key = tile_type.split("_")[0] + "_s"  # stack_s or craft_s
                            goals[goal_key] = goals.get(goal_key, 0) + total_count

                    # Frog positions (attribute is "frog")
                    if attribute == "frog":
                        initial_frog_positions.append(f"{i}_{pos}")

                    # Ice gimmick (attribute is "ice" or "ice_N")
                    if attribute and (attribute == "ice" or attribute.startswith("ice_")):
                        ice_level = 1
                        if attribute.startswith("ice_"):
                            try:
                                ice_level = int(attribute.split("_")[1])
                            except (IndexError, ValueError):
                                ice_level = 1
                        initial_ice_states[f"{i}_{pos}"] = ice_level

                    # Chain gimmick (attribute is "chain")
                    if attribute == "chain":
                        initial_chain_states[f"{i}_{pos}"] = False  # Initially locked

                    # Grass gimmick (attribute is "grass" or "grass_N")
                    if attribute and (attribute == "grass" or attribute.startswith("grass_")):
                        grass_level = 1
                        if attribute.startswith("grass_"):
                            try:
                                grass_level = int(attribute.split("_")[1])
                            except (IndexError, ValueError):
                                grass_level = 1
                        initial_grass_states[f"{i}_{pos}"] = grass_level

                    # Bomb gimmick (attribute is "bomb" or a number)
                    if attribute == "bomb" or (attribute and attribute.isdigit()):
                        bomb_count = 10  # Default bomb count
                        if attribute and attribute.isdigit():
                            bomb_count = int(attribute)
                        initial_bomb_states[f"{i}_{pos}"] = bomb_count

                    # Curtain gimmick (attribute is "curtain_open" or "curtain_close")
                    if attribute and attribute.startswith("curtain_"):
                        is_open = attribute == "curtain_open"
                        initial_curtain_states[f"{i}_{pos}"] = is_open

                    # Link gimmick (attribute is "link_n", "link_s", "link_e", "link_w")
                    if attribute and attribute.startswith("link_"):
                        direction = attribute.split("_")[1]  # n, s, e, w
                        # Calculate linked position based on direction
                        x, y = pos.split("_")
                        x, y = int(x), int(y)
                        linked_pos = None
                        if direction == "n":
                            linked_pos = f"{x}_{y-1}"
                        elif direction == "s":
                            linked_pos = f"{x}_{y+1}"
                        elif direction == "e":
                            linked_pos = f"{x+1}_{y}"
                        elif direction == "w":
                            linked_pos = f"{x-1}_{y}"
                        if linked_pos:
                            initial_link_states[f"{i}_{pos}"] = [f"{i}_{linked_pos}"]

    # Use goalCount from level JSON if available, otherwise use extracted goals
    goal_count = level_json.get("goalCount", {})
    if goal_count:
        goals = dict(goal_count)

    return VisualGameState(
        tiles=tiles,
        goals=goals,
        grid_info=grid_info,
        initial_frog_positions=initial_frog_positions,
        initial_ice_states=initial_ice_states,
        initial_chain_states=initial_chain_states,
        initial_grass_states=initial_grass_states,
        initial_bomb_states=initial_bomb_states,
        initial_curtain_states=initial_curtain_states,
        initial_link_states=initial_link_states,
    )


def extract_dock_info(level_json: Dict[str, Any]) -> Dict[str, Any]:
    """Extract dock configuration for visualization."""
    return {
        "max_slots": 7,  # Fixed 7-slot dock system
        "current_tiles": [],  # Initially empty
    }


@router.post(
    "/visual",
    response_model=VisualSimulationResponse,
    responses={400: {"model": ErrorResponse}},
    summary="Visual simulation with move history",
    description="""
    Run a single simulation for each bot type and return detailed move history.
    Designed for frontend visualization/playback of bot gameplay.

    Game Rules (from sp_template):
    - 7-slot dock queue system
    - Tiles are added to dock when clicked
    - When 3 same-type tiles exist in dock, they are removed (matched)
    - Game fails when dock is full (7 tiles) without any matches
    - Layer blocking: upper layer tiles block lower layer tiles
    - Various obstacle effects affect tile pickability (ice, chain, grass, link, frog, bomb)

    Unlike the multi-bot assessment (which runs many iterations for statistics),
    this endpoint runs just one simulation per bot and records every move.
    """,
)
async def simulate_visual(request: VisualSimulationRequest):
    """Run visual simulation and return move history for playback."""
    try:
        start_time = time.time()

        # Determine which bots to simulate
        bot_types = request.bot_types or ["novice", "casual", "average", "expert", "optimal"]

        # Validate bot types
        valid_types = {"novice", "casual", "average", "expert", "optimal"}
        for bt in bot_types:
            if bt not in valid_types:
                raise HTTPException(
                    status_code=400,
                    detail=f"Invalid bot type: {bt}. Valid types: {valid_types}"
                )

        # Create simulator and get t0 assignments first
        simulator = VisualSimulator()
        t0_assignments = simulator.get_t0_assignments(request.level_json, request.seed)

        # Calculate total tiles to determine max_moves
        # Stack/craft tiles count as multiple tiles based on their totalCount
        total_tiles = 0
        level_json = request.level_json
        num_layers = level_json.get("layer", 0)
        for layer_idx in range(num_layers):
            layer_key = f"layer_{layer_idx}"
            layer_data = level_json.get(layer_key, {})
            tiles = layer_data.get("tiles", {})
            for pos, tile_data in tiles.items():
                if isinstance(tile_data, list) and len(tile_data) > 0:
                    tile_type = tile_data[0]
                    # Check for stack/craft tiles (e.g., stack_t1, craft_t2)
                    if isinstance(tile_type, str) and (tile_type.startswith("stack_") or tile_type.startswith("craft_")):
                        # Get totalCount from extra_data: [totalCount] or [totalCount, "types"]
                        extra_data = tile_data[2] if len(tile_data) > 2 else None
                        if extra_data and isinstance(extra_data, list) and len(extra_data) >= 1:
                            stack_count = int(extra_data[0]) if extra_data[0] else 1
                            total_tiles += stack_count
                        else:
                            total_tiles += 1
                    else:
                        total_tiles += 1
                else:
                    total_tiles += 1

        # max_moves should be at least equal to total tiles (each move removes 1 tile)
        # Add some buffer for potential inefficiencies
        effective_max_moves = max(request.max_moves, total_tiles)

        # Run simulations (reuse simulator created earlier)
        # All bots use the same initial_state_seed for consistent tile types
        # Each bot uses a different behavior seed for varied gameplay
        bot_results: List[VisualBotResult] = []
        stack_craft_types: Optional[Dict[str, List[str]]] = None
        initial_state_seed = request.seed  # Same seed for all bots' initial state

        for i, bot_type in enumerate(bot_types):
            # Different behavior seed per bot, but same initial state seed
            behavior_seed = request.seed + i if request.seed is not None else None
            result, types_map = simulator.simulate_bot(
                request.level_json,
                bot_type,
                effective_max_moves,
                seed=behavior_seed,
                initial_state_seed=initial_state_seed,
            )
            bot_results.append(result)
            # Use the first bot's stack/craft types for initial state
            # (all bots now have the same types due to same initial_state_seed)
            if i == 0:
                stack_craft_types = types_map

        # Extract initial state with t0 tiles and stack/craft types from simulation
        initial_state = extract_initial_state(request.level_json, t0_assignments, stack_craft_types)

        # Calculate max steps
        max_steps = max(len(r.moves) for r in bot_results) if bot_results else 0

        elapsed_ms = int((time.time() - start_time) * 1000)

        return VisualSimulationResponse(
            initial_state=initial_state,
            bot_results=bot_results,
            max_steps=max_steps,
            metadata={
                "elapsed_ms": elapsed_ms,
                "bot_count": len(bot_results),
                "total_tiles": total_tiles,
                "max_moves_setting": effective_max_moves,
                "dock_slots": 7,  # Add dock info to metadata
                "game_rules": "sp_template",  # Indicate which rules are used
            },
        )

    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))
