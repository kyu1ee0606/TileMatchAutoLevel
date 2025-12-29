"""Level simulation engine with dock-based matching system (Townpop rules)."""
import random
import statistics
from typing import Dict, List, Any, Optional, Tuple, Set
from dataclasses import dataclass, field
from enum import Enum
from copy import deepcopy

from ..models.level import SimulationResult


class SimulationStrategy(str, Enum):
    """Simulation strategy enumeration."""
    RANDOM = "random"
    GREEDY = "greedy"
    OPTIMAL = "optimal"


@dataclass
class DockTile:
    """Represents a tile in the dock."""
    tile_type: str
    layer_idx: int
    position: str


@dataclass
class GameState:
    """Represents the current state of a simulated game."""
    tiles: Dict[int, Dict[str, List[Any]]]  # layer_idx -> {pos: tile_data}
    dock: List[DockTile] = field(default_factory=list)  # Current tiles in dock
    dock_max_size: int = 7  # Maximum dock slots
    goals_remaining: Dict[str, int] = field(default_factory=dict)  # goal_type -> count remaining
    moves_used: int = 0
    cleared: bool = False
    failed: bool = False  # Dock overflow
    max_moves: int = 30


@dataclass
class Move:
    """Represents a possible move in the game."""
    layer_idx: int
    position: str
    tile_type: str
    attribute: str = ""
    linked_tiles: List[Tuple[int, str]] = field(default_factory=list)  # (layer_idx, pos) for linked tiles
    score: float = 0.0  # For greedy/optimal strategies


class LevelSimulator:
    """Simulates level play-through with Townpop dock-based matching rules."""

    # Tile matching rules
    MATCHABLE_TYPES = {"t0", "t1", "t2", "t3", "t4", "t5", "t6", "t7", "t10", "t11", "t12", "t14", "t15"}
    GOAL_TYPES = {"craft_s", "stack_s"}

    # Link directions mapping (link attribute -> delta col, delta row)
    LINK_DIRECTIONS = {
        "link_n": (0, -1),   # North = row-1
        "link_s": (0, 1),    # South = row+1
        "link_w": (-1, 0),   # West = col-1
        "link_e": (1, 0),    # East = col+1
    }

    def simulate(
        self,
        level_json: Dict[str, Any],
        iterations: int = 500,
        strategy: str = "greedy",
        max_moves: int = 30,
    ) -> SimulationResult:
        """
        Run Monte Carlo simulation on a level.

        Args:
            level_json: Level data to simulate.
            iterations: Number of simulation runs.
            strategy: Strategy to use (random/greedy/optimal).
            max_moves: Maximum moves per simulation.

        Returns:
            SimulationResult with statistics.
        """
        results = []

        for _ in range(iterations):
            state = self._create_initial_state(level_json, max_moves)
            result = self._play_game(state, SimulationStrategy(strategy))
            results.append(result)

        cleared_count = sum(1 for r in results if r.cleared)
        moves_list = [r.moves_used for r in results]

        return SimulationResult(
            clear_rate=cleared_count / len(results),
            avg_moves=statistics.mean(moves_list) if moves_list else 0,
            min_moves=min(moves_list) if moves_list else 0,
            max_moves=max(moves_list) if moves_list else 0,
            iterations=iterations,
            strategy=strategy,
        )

    def _create_initial_state(
        self, level_json: Dict[str, Any], max_moves: int
    ) -> GameState:
        """Create initial game state from level JSON."""
        num_layers = level_json.get("layer", 8)
        tiles: Dict[int, Dict[str, List[Any]]] = {}
        goals_remaining: Dict[str, int] = {}

        for i in range(num_layers):
            layer_key = f"layer_{i}"
            layer_data = level_json.get(layer_key, {})
            layer_tiles = layer_data.get("tiles", {})

            if layer_tiles:
                tiles[i] = {}
                for pos, tile_data in layer_tiles.items():
                    if isinstance(tile_data, list):
                        # Deep copy tile data
                        tiles[i][pos] = list(tile_data)

                        # Extract goals
                        if tile_data[0] in self.GOAL_TYPES:
                            goal_type = tile_data[0]
                            goal_count = (
                                tile_data[2][0]
                                if len(tile_data) > 2 and tile_data[2]
                                else 1
                            )
                            goals_remaining[goal_type] = (
                                goals_remaining.get(goal_type, 0) + goal_count
                            )

        return GameState(
            tiles=tiles,
            goals_remaining=goals_remaining,
            max_moves=max_moves,
            dock=[],
            dock_max_size=7,
        )

    def _play_game(self, state: GameState, strategy: SimulationStrategy) -> GameState:
        """Play through a game with the given strategy using dock-based matching."""
        while state.moves_used < state.max_moves and not self._is_game_over(state):
            moves = self._get_available_moves(state)

            if not moves:
                break

            if strategy == SimulationStrategy.RANDOM:
                move = random.choice(moves)
            elif strategy == SimulationStrategy.GREEDY:
                move = self._select_greedy_move(moves, state)
            else:  # OPTIMAL - use simple lookahead
                move = self._select_optimal_move(moves, state)

            # Apply the move (adds tiles to dock)
            self._apply_move(state, move)
            state.moves_used += 1

            # Check for dock overflow AFTER matching
            # Matching happens automatically when tiles are added
            if state.failed:
                break

        # Check if all goals are cleared
        if not state.failed:
            state.cleared = all(count <= 0 for count in state.goals_remaining.values())

        return state

    def _is_game_over(self, state: GameState) -> bool:
        """Check if the game is over (all goals cleared, dock overflow, or no tiles left)."""
        # Dock overflow = game over (failed)
        if state.failed:
            return True

        # All goals cleared = game over (success)
        if all(count <= 0 for count in state.goals_remaining.values()):
            return True

        # Check if there are any playable tiles
        for layer_tiles in state.tiles.values():
            for tile_data in layer_tiles.values():
                if tile_data[0] in self.MATCHABLE_TYPES:
                    return False

        return True

    def _get_available_moves(self, state: GameState) -> List[Move]:
        """Get all available moves in the current state."""
        moves = []

        # Get accessible tiles (top-most tiles at each position)
        accessible = self._get_accessible_tiles(state)

        # Pre-compute accessible positions for link checking (performance optimization)
        accessible_positions = {(layer_idx, pos) for layer_idx, pos, _ in accessible}

        for layer_idx, pos, tile_data in accessible:
            tile_type = tile_data[0]
            attribute = tile_data[1] if len(tile_data) > 1 else ""

            # Skip goals (they are collected separately)
            if tile_type in self.GOAL_TYPES:
                continue

            # Skip non-matchable tiles
            if tile_type not in self.MATCHABLE_TYPES:
                continue

            # Check for blocked tiles (chain, ice, curtain need special handling)
            if attribute in ("chain", "crate"):
                # Chain/crate tiles cannot be directly selected
                continue
            if attribute and attribute.startswith("ice_"):
                # Ice tiles need adjacent matches to break
                continue
            if attribute == "curtain_close":
                # Curtain tiles are hidden until adjacent match
                continue

            # Find linked tiles - check both directions
            linked_tiles = []

            # Case 1: This tile has a link attribute (source -> target)
            if attribute and attribute.startswith("link_"):
                linked_tile = self._get_linked_tile_fast(state, layer_idx, pos, attribute, accessible_positions)
                if linked_tile:
                    linked_tiles.append(linked_tile)
            else:
                # Case 2: This tile might be a link target (reverse lookup: target -> source)
                link_source = self._find_link_source_fast(state, layer_idx, pos, accessible_positions)
                if link_source:
                    linked_tiles.append(link_source)

            moves.append(Move(
                layer_idx=layer_idx,
                position=pos,
                tile_type=tile_type,
                attribute=attribute,
                linked_tiles=linked_tiles,
            ))

        return moves

    def _get_linked_tile_fast(
        self, state: GameState, layer_idx: int, pos: str, link_attr: str,
        accessible_positions: Set[Tuple[int, str]]
    ) -> Optional[Tuple[int, str]]:
        """Get the linked tile position for a link attribute (optimized with pre-computed positions).

        IMPORTANT: The target tile must be accessible (not blocked by upper layers)
        for the link pair to work together.
        """
        if link_attr not in self.LINK_DIRECTIONS:
            return None

        try:
            col, row = map(int, pos.split('_'))
        except:
            return None

        delta_col, delta_row = self.LINK_DIRECTIONS[link_attr]
        target_col = col + delta_col
        target_row = row + delta_row
        target_pos = f"{target_col}_{target_row}"

        # Check if target tile exists in the same layer
        layer_tiles = state.tiles.get(layer_idx, {})
        if target_pos in layer_tiles:
            # Check if target tile is accessible (not blocked by upper layer)
            if (layer_idx, target_pos) in accessible_positions:
                return (layer_idx, target_pos)

        return None

    def _get_linked_tile(
        self, state: GameState, layer_idx: int, pos: str, link_attr: str
    ) -> Optional[Tuple[int, str]]:
        """Get the linked tile position for a link attribute.

        IMPORTANT: The target tile must be accessible (not blocked by upper layers)
        for the link pair to work together.
        """
        if link_attr not in self.LINK_DIRECTIONS:
            return None

        try:
            col, row = map(int, pos.split('_'))
        except:
            return None

        delta_col, delta_row = self.LINK_DIRECTIONS[link_attr]
        target_col = col + delta_col
        target_row = row + delta_row
        target_pos = f"{target_col}_{target_row}"

        # Check if target tile exists in the same layer
        layer_tiles = state.tiles.get(layer_idx, {})
        if target_pos in layer_tiles:
            # Check if target tile is accessible (not blocked by upper layer)
            accessible_positions = self._get_accessible_positions(state)
            if (layer_idx, target_pos) in accessible_positions:
                return (layer_idx, target_pos)

        return None

    def _find_link_source_fast(
        self, state: GameState, layer_idx: int, target_pos: str,
        accessible_positions: Set[Tuple[int, str]]
    ) -> Optional[Tuple[int, str]]:
        """Find if any tile has a link attribute pointing TO this position (optimized).

        This handles the case where a tile without a link attribute is selected,
        but another tile has a link pointing to it - both should go to dock together.

        IMPORTANT: The source tile must be accessible (not blocked by upper layers)
        for the link pair to work.
        """
        try:
            target_col, target_row = map(int, target_pos.split('_'))
        except:
            return None

        layer_tiles = state.tiles.get(layer_idx, {})

        # Check all tiles in the same layer for a link pointing to target_pos
        for pos, tile_data in layer_tiles.items():
            if pos == target_pos:
                continue

            if not isinstance(tile_data, list) or len(tile_data) < 2:
                continue

            attr = tile_data[1] if tile_data[1] else ""
            if not attr.startswith("link_"):
                continue

            # This tile has a link attribute - check if it points to target_pos
            if attr not in self.LINK_DIRECTIONS:
                continue

            try:
                source_col, source_row = map(int, pos.split('_'))
            except:
                continue

            delta_col, delta_row = self.LINK_DIRECTIONS[attr]
            linked_col = source_col + delta_col
            linked_row = source_row + delta_row

            # If this tile's link points to target_pos, return this tile as the source
            if linked_col == target_col and linked_row == target_row:
                # Check if source tile is accessible (not blocked by upper layer)
                if (layer_idx, pos) in accessible_positions:
                    return (layer_idx, pos)

        return None

    def _find_link_source(
        self, state: GameState, layer_idx: int, target_pos: str
    ) -> Optional[Tuple[int, str]]:
        """Find if any tile has a link attribute pointing TO this position (reverse lookup).

        This handles the case where a tile without a link attribute is selected,
        but another tile has a link pointing to it - both should go to dock together.

        IMPORTANT: The source tile must be accessible (not blocked by upper layers)
        for the link pair to work.
        """
        try:
            target_col, target_row = map(int, target_pos.split('_'))
        except:
            return None

        # Get all accessible positions to check if source is accessible
        accessible_positions = self._get_accessible_positions(state)

        layer_tiles = state.tiles.get(layer_idx, {})

        # Check all tiles in the same layer for a link pointing to target_pos
        for pos, tile_data in layer_tiles.items():
            if pos == target_pos:
                continue

            if not isinstance(tile_data, list) or len(tile_data) < 2:
                continue

            attr = tile_data[1] if tile_data[1] else ""
            if not attr.startswith("link_"):
                continue

            # This tile has a link attribute - check if it points to target_pos
            if attr not in self.LINK_DIRECTIONS:
                continue

            try:
                source_col, source_row = map(int, pos.split('_'))
            except:
                continue

            delta_col, delta_row = self.LINK_DIRECTIONS[attr]
            linked_col = source_col + delta_col
            linked_row = source_row + delta_row

            # If this tile's link points to target_pos, return this tile as the source
            if linked_col == target_col and linked_row == target_row:
                # Check if source tile is accessible (not blocked by upper layer)
                if (layer_idx, pos) in accessible_positions:
                    return (layer_idx, pos)

        return None

    def _get_accessible_positions(self, state: GameState) -> Set[Tuple[int, str]]:
        """Get set of accessible (layer_idx, position) tuples."""
        accessible = set()
        occupied_positions: Set[str] = set()

        # Start from top layer
        sorted_layers = sorted(state.tiles.keys(), reverse=True)

        for layer_idx in sorted_layers:
            layer_tiles = state.tiles.get(layer_idx, {})

            for pos in layer_tiles.keys():
                if pos not in occupied_positions:
                    accessible.add((layer_idx, pos))
                    occupied_positions.add(pos)

        return accessible

    def _get_accessible_tiles(
        self, state: GameState
    ) -> List[Tuple[int, str, List[Any]]]:
        """Get tiles that are accessible (not blocked by upper layers)."""
        accessible = []
        occupied_positions: Set[str] = set()

        # Start from top layer
        sorted_layers = sorted(state.tiles.keys(), reverse=True)

        for layer_idx in sorted_layers:
            layer_tiles = state.tiles.get(layer_idx, {})

            for pos, tile_data in layer_tiles.items():
                # Check if position is blocked by upper layer tile
                if pos not in occupied_positions:
                    accessible.append((layer_idx, pos, tile_data))
                    occupied_positions.add(pos)

        return accessible

    def _select_greedy_move(self, moves: List[Move], state: GameState) -> Move:
        """Select the best move using greedy strategy."""
        # Score moves based on potential impact
        for move in moves:
            move.score = self._score_move(move, state)

        # Sort by score and pick the best
        moves.sort(key=lambda m: m.score, reverse=True)
        return moves[0]

    def _select_optimal_move(self, moves: List[Move], state: GameState) -> Move:
        """Select move using simple lookahead (limited MCTS)."""
        # For simplicity, just use greedy with higher weight on goal progress
        for move in moves:
            move.score = self._score_move(move, state) * 1.5

        moves.sort(key=lambda m: m.score, reverse=True)
        return moves[0]

    def _score_move(self, move: Move, state: GameState) -> float:
        """Score a move based on its potential value."""
        score = 1.0

        # Count how many of this tile type are in dock
        dock_same_type = sum(1 for dt in state.dock if dt.tile_type == move.tile_type)

        # HIGH PRIORITY: If we have 2 of same type in dock, picking another completes a match
        if dock_same_type == 2:
            score += 10.0  # Very high priority - completes a match
        elif dock_same_type == 1:
            score += 3.0   # Good - gets closer to match

        # Bonus for link tiles (clears 2 tiles at once)
        if move.linked_tiles:
            score += 2.0
            # Check if linked tile type also helps dock matching
            for linked_layer, linked_pos in move.linked_tiles:
                linked_tile = state.tiles.get(linked_layer, {}).get(linked_pos, [])
                if linked_tile:
                    linked_type = linked_tile[0]
                    linked_in_dock = sum(1 for dt in state.dock if dt.tile_type == linked_type)
                    if linked_in_dock == 2:
                        score += 5.0  # Linked tile also completes a match!
                    elif linked_in_dock == 1:
                        score += 1.5

        # Bonus for matching tiles that progress towards goals
        if state.goals_remaining.get("craft_s", 0) > 0:
            score += 0.5

        # Bonus for higher layer moves (clears blocking tiles)
        score += move.layer_idx * 0.2

        # Penalty for adding new tile type to dock (increases dock pressure)
        if dock_same_type == 0:
            # Check dock space
            tiles_to_add = 1 + len(move.linked_tiles)
            current_dock_size = len(state.dock)
            if current_dock_size + tiles_to_add > state.dock_max_size - 2:
                score -= 3.0  # Risk of overflow

        return score

    def _apply_move(self, state: GameState, move: Move) -> None:
        """Apply a move to the game state using dock-based matching."""
        tiles_to_add = []

        # Collect main tile
        layer_tiles = state.tiles.get(move.layer_idx, {})
        if move.position in layer_tiles:
            tile_data = layer_tiles[move.position]
            tile_type = tile_data[0]

            # Handle t0 (random tile) - assign random type
            if tile_type == "t0":
                tile_type = random.choice(["t1", "t2", "t3", "t4", "t5", "t6"])

            tiles_to_add.append(DockTile(
                tile_type=tile_type,
                layer_idx=move.layer_idx,
                position=move.position,
            ))

            # Remove from board
            del layer_tiles[move.position]

        # Collect linked tiles (for link attribute)
        for linked_layer, linked_pos in move.linked_tiles:
            linked_layer_tiles = state.tiles.get(linked_layer, {})
            if linked_pos in linked_layer_tiles:
                linked_tile_data = linked_layer_tiles[linked_pos]
                linked_type = linked_tile_data[0]

                # Handle t0 (random tile)
                if linked_type == "t0":
                    linked_type = random.choice(["t1", "t2", "t3", "t4", "t5", "t6"])

                tiles_to_add.append(DockTile(
                    tile_type=linked_type,
                    layer_idx=linked_layer,
                    position=linked_pos,
                ))

                # Remove from board
                del linked_layer_tiles[linked_pos]

        # Add tiles to dock and process matches
        for dock_tile in tiles_to_add:
            self._add_tile_to_dock(state, dock_tile)

            # Check for dock overflow AFTER trying to match
            if state.failed:
                return

    def _add_tile_to_dock(self, state: GameState, dock_tile: DockTile) -> None:
        """Add a tile to the dock with proper insertion and matching logic."""
        tile_type = dock_tile.tile_type

        # Find insertion position (group with same type if exists)
        insert_idx = len(state.dock)  # Default: end of dock

        for i, existing in enumerate(state.dock):
            if existing.tile_type == tile_type:
                # Find the last consecutive tile of same type
                insert_idx = i + 1
                while insert_idx < len(state.dock) and state.dock[insert_idx].tile_type == tile_type:
                    insert_idx += 1
                break

        # Insert tile at the appropriate position
        state.dock.insert(insert_idx, dock_tile)

        # CRITICAL: Check for matches BEFORE checking overflow
        # This is the Townpop rule - matches happen immediately
        self._process_dock_matches(state)

        # NOW check if dock overflows after matching
        if len(state.dock) > state.dock_max_size:
            state.failed = True

    def _process_dock_matches(self, state: GameState) -> None:
        """Process all matches in the dock (groups of 3+ same type tiles)."""
        matched = True

        while matched:
            matched = False

            # Count consecutive tiles of each type
            if not state.dock:
                break

            i = 0
            while i < len(state.dock):
                current_type = state.dock[i].tile_type
                count = 1

                # Count consecutive same-type tiles
                while i + count < len(state.dock) and state.dock[i + count].tile_type == current_type:
                    count += 1

                # If 3 or more consecutive, remove them
                if count >= 3:
                    # Remove matched tiles (3 tiles only, keeping extras)
                    for _ in range(3):
                        state.dock.pop(i)

                    # Progress goals
                    for goal_type in state.goals_remaining:
                        if state.goals_remaining[goal_type] > 0:
                            state.goals_remaining[goal_type] -= 1
                            break

                    matched = True
                    # Don't increment i, check same position again
                else:
                    i += count


# Singleton instance
_simulator = None


def get_simulator() -> LevelSimulator:
    """Get or create simulator singleton instance."""
    global _simulator
    if _simulator is None:
        _simulator = LevelSimulator()
    return _simulator
